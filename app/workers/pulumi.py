"""Run a fixed, provider-free Automation API validation outside the web process."""

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType
from typing import Literal

from pydantic import ValidationError

from app.integrations.pulumi.diagnostics import check_runtime
from app.integrations.pulumi.models import SelfTestResult

logger = logging.getLogger(__name__)


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the entire worker process group, including engine/language descendants."""
    if sys.platform != "win32":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # The Python child may exit before a descendant does; always kill the group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    process.wait(timeout=5)


def _run_supervised(
    command: Sequence[str], *, environment: dict[str, str], cwd: Path, timeout: float
) -> Literal["completed", "failed", "timed_out", "interrupted"]:
    """Run a trusted command with no raw console output and a hard process deadline."""
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
        creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
    ) as process:
        try:
            return "completed" if process.wait(timeout=timeout) == 0 else "failed"
        except subprocess.TimeoutExpired:
            return "timed_out"
        except KeyboardInterrupt:
            return "interrupted"
        finally:
            _terminate_tree(process)


def _child_environment(directory: Path, cli: Path) -> dict[str, str]:
    # Do not inherit cloud credentials, Pulumi login, proxy credentials or API config.
    environment = {
        key: os.environ[key]
        # Pulumi's static Go CLI needs HOME for OS user lookup. Preserve its value;
        # all Pulumi configuration/state uses the separate per-run PULUMI_HOME.
        for key in ("SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "USER", "USERNAME", "HOME")
        if key in os.environ
    }
    environment.update(
        {
            "PATH": os.pathsep.join(
                (str(cli.parent), str(Path(sys.executable).parent), os.defpath)
            ),
            "PULUMI_HOME": str(directory / "pulumi-home"),
            "PULUMI_SKIP_UPDATE_CHECK": "true",
            "PULUMI_DISABLE_AUTOMATIC_PLUGIN_ACQUISITION": "true",
            "PYTHONUNBUFFERED": "1",
            "TMPDIR": str(directory),
            "TEMP": str(directory),
            "TMP": str(directory),
        }
    )
    return environment


def run_self_test(cli: str = "pulumi", *, timeout: float = 120) -> SelfTestResult:
    """Validate the fixed test program; it cannot create target-provider resources."""
    if not 0 < timeout <= 600:
        raise ValueError("Self-test timeout must be greater than zero and at most 600 seconds.")
    runtime = check_runtime(cli)
    executable = shutil.which(cli)
    if runtime.status != "ready" or executable is None:
        return SelfTestResult(
            status="unavailable", message="Pulumi runtime is not ready.", runtime=runtime
        )
    cli_path = Path(executable).resolve()
    if cli_path.name not in ("pulumi", "pulumi.exe"):
        return SelfTestResult(
            status="unavailable",
            message="Pulumi executable name is not supported.",
            runtime=runtime,
        )
    repository = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="olixops-pulumi-") as temporary:
        directory = Path(temporary)
        result_path = directory / "result.json"
        try:
            status = _run_supervised(
                [
                    sys.executable,
                    "-m",
                    "app.workers.pulumi",
                    "_self-test-child",
                    "--directory",
                    str(directory),
                ],
                environment=_child_environment(directory, cli_path),
                cwd=repository,
                timeout=timeout,
            )
            if status == "completed" and result_path.stat().st_size <= 2_000_000:
                result = SelfTestResult.model_validate_json(result_path.read_text())
                result.cleanup = "temporary_files_removed"
            else:
                result = SelfTestResult(
                    status="failed" if status == "completed" else status,
                    message="Pulumi validation did not complete; no rollback is claimed.",
                    runtime=runtime,
                    cleanup="temporary_files_removed",
                )
        except OSError, ValueError, ValidationError, subprocess.SubprocessError:
            result = SelfTestResult(
                status="failed",
                message="Pulumi validation failed; no rollback is claimed.",
                runtime=runtime,
                cleanup="temporary_files_removed",
            )
    # No engine text, exceptions, paths, configuration or output values are logged.
    logger.info("Pulumi self-test finished", extra={"step": result.status})
    return result


def _run_child(directory: Path) -> SelfTestResult:
    """Internal registered program; never import or execute user-submitted source."""
    import pulumi

    from app.integrations.pulumi.adapter import IsolatedProgramSession, TrustedProgram

    runtime = check_runtime()
    result = SelfTestResult(
        status="failed",
        message="Pulumi validation failed; no rollback is claimed.",
        runtime=runtime,
    )

    def program() -> None:
        pulumi.export("message", "olixops-pulumi-self-test")
        pulumi.export("secret_probe", pulumi.Output.secret("not-a-real-credential"))

    session: IsolatedProgramSession | None = None
    try:
        session = IsolatedProgramSession(
            directory,
            TrustedProgram(run=program, output_names=frozenset({"message", "secret_probe"})),
        )
        result.operations.append(session.preview())
        result.operations.append(session.up())
        result.outputs_verified = session.verify_constant_output(
            "message", "olixops-pulumi-self-test"
        )
        result.outputs_verified = result.outputs_verified and any(
            output.name == "secret_probe" and output.secret
            for output in result.operations[-1].outputs
        )
        if not result.outputs_verified:
            return result
        result.operations.append(session.refresh())
        result.operations.append(session.preview(expect_no_changes=True))
        result.no_changes_verified = True
        result.operations.append(session.destroy())
        session.remove_stack()
        result.stack_removed = session.stack_removed
        result.status = "succeeded"
        result.message = "Provider-free Pulumi lifecycle and secret filtering checks passed."
    except Exception:
        # The process boundary is the last-resort exception handler. Pulumi errors can
        # contain decrypted configuration; the fixed result intentionally omits them.
        result.status = "failed"
    finally:
        if session is not None:
            result.events = session.events
            result.events_truncated = session.events_truncated
    return result


def _interrupt(_signal: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    self_test = commands.add_parser(
        "self-test", help="Validate an isolated provider-free lifecycle"
    )
    self_test.add_argument("--cli", default="pulumi")
    self_test.add_argument("--timeout", type=float, default=120)
    child = commands.add_parser("_self-test-child", help=argparse.SUPPRESS)
    child.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "_self-test-child":
        directory = Path(args.directory)
        result = _run_child(directory)
        (directory / "result.json").write_text(result.model_dump_json())
        return 0
    signal.signal(signal.SIGTERM, _interrupt)
    result = run_self_test(str(args.cli), timeout=float(args.timeout))
    print(result.model_dump_json())
    return 0 if result.status == "succeeded" else 130 if result.status == "interrupted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
