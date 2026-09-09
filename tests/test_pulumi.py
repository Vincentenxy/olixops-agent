"""Validate the Pulumi trust boundary, not cloud-provider behavior."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pulumi import automation as auto

from app.integrations.pulumi import adapter, diagnostics
from app.integrations.pulumi.adapter import summarize_changes, summarize_event, summarize_outputs
from app.integrations.pulumi.models import EXPECTED_VERSION, Change, Operation, PulumiRuntimeStatus
from app.workers.pulumi import _child_environment, _run_child, _run_supervised, run_self_test


def ready_runtime() -> PulumiRuntimeStatus:
    return PulumiRuntimeStatus(
        sdk_version=EXPECTED_VERSION, cli_version=EXPECTED_VERSION, status="ready", message="Ready"
    )


def test_runtime_missing_cli_reports_absence_without_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.integrations.pulumi.diagnostics.shutil.which", lambda _: None)
    result = diagnostics.check_runtime()
    assert result.status == "unavailable"
    assert result.cli_version is None


def test_runtime_probe_timeout_does_not_expose_process_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["/secret/path/pulumi"], 3, output="credential=canary")

    monkeypatch.setattr(
        "app.integrations.pulumi.diagnostics.shutil.which", lambda _: "/secret/path/pulumi"
    )
    monkeypatch.setattr("app.integrations.pulumi.diagnostics.subprocess.run", timeout)
    result = diagnostics.check_runtime()
    assert result.status == "unavailable"
    assert "canary" not in result.model_dump_json()
    assert "/secret/path" not in result.model_dump_json()


def test_runtime_rejects_unpinned_cli_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.integrations.pulumi.diagnostics.shutil.which", lambda _: "/tools/pulumi"
    )
    monkeypatch.setattr(diagnostics, "version", lambda _: EXPECTED_VERSION)
    monkeypatch.setattr(
        "app.integrations.pulumi.diagnostics.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(["pulumi"], 0, "v3.0.0\n", ""),
    )
    result = diagnostics.check_runtime()
    assert result.status == "incompatible"
    assert result.cli_version == "3.0.0"


def test_runtime_probe_isolates_operator_login_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    operator_directory = tmp_path / "operator-pulumi-home"
    operator_directory.mkdir()
    monkeypatch.setenv("PULUMI_HOME", str(operator_directory))
    monkeypatch.setenv("PULUMI_ACCESS_TOKEN", "credential-canary")
    monkeypatch.setattr(
        "app.integrations.pulumi.diagnostics.shutil.which", lambda _: "/tools/pulumi"
    )

    def inspect_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["PULUMI_HOME"] != str(operator_directory)
        assert "PULUMI_ACCESS_TOKEN" not in environment
        Path(environment["PULUMI_HOME"], "initialized-by-cli").write_text("test")
        return subprocess.CompletedProcess(["pulumi"], 0, f"v{EXPECTED_VERSION}\n", "")

    monkeypatch.setattr("app.integrations.pulumi.diagnostics.subprocess.run", inspect_probe)
    assert diagnostics.check_runtime().status == "ready"
    assert list(operator_directory.iterdir()) == []


def test_outputs_never_include_secret_or_unmarked_values() -> None:
    outputs = {
        "secret": auto.OutputValue({"password": "secret-canary"}, True),
        "public": auto.OutputValue("unmarked-credential-canary", False),
        "unreviewed-name-canary": auto.OutputValue("arbitrary", False),
    }
    result = summarize_outputs(outputs, frozenset({"secret", "public"}))
    serialized = json.dumps([item.model_dump() for item in result])
    assert "canary" not in serialized
    assert {item.name: item.secret for item in result} == {"secret": True, "public": False}
    assert all(item.value == "[REDACTED]" for item in result)


def test_event_mapping_drops_raw_text_and_resource_identity() -> None:
    diagnostic = auto.EngineEvent(
        sequence=3,
        timestamp=1,
        diagnostic_event=auto.DiagnosticEvent(
            message="Authorization: Bearer credential-canary",
            color="raw",
            severity="error",
            urn="resource-canary",
            prefix="prefix-canary",
        ),
    )
    resource = auto.EngineEvent(
        sequence=4,
        timestamp=1,
        resource_pre_event=auto.ResourcePreEvent(
            metadata=auto.StepEventMetadata(
                op=auto.OpType.CREATE,
                urn="credential-canary",
                type="provider-canary",
                provider="secret-canary",
                keys=["private-key-canary"],
                diffs=["password-canary"],
            )
        ),
    )
    mapped = [summarize_event(event, Operation.UP) for event in (diagnostic, resource)]
    assert all(item is not None for item in mapped)
    assert "canary" not in "".join(item.model_dump_json() for item in mapped if item)
    assert mapped[1] is not None and mapped[1].change == Change.CREATE


def test_raw_stdout_and_unknown_change_names_are_omitted() -> None:
    event = auto.EngineEvent(
        sequence=0,
        timestamp=1,
        stdout_event=auto.StdoutEngineEvent(message="credential-canary", color="raw"),
    )
    assert summarize_event(event, Operation.PREVIEW) is None
    assert summarize_changes({"create": 2, "unknown-canary": 3, "delete": -1}) == {Change.CREATE: 2}


def test_worker_discards_inherited_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in (
        "AWS_SECRET_ACCESS_KEY",
        "PULUMI_ACCESS_TOKEN",
        "OLIXOPS_JWT_PRIVATE_KEY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(key, "credential-canary")
    environment = _child_environment(tmp_path, tmp_path / "tools" / "pulumi")
    assert "credential-canary" not in json.dumps(environment)
    assert environment["PULUMI_HOME"] == str(tmp_path / "pulumi-home")


def test_child_failure_does_not_leak_exception_or_claim_rollback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failed_session(*args: object, **kwargs: object) -> None:
        raise RuntimeError("provider failed with password=credential-canary")

    monkeypatch.setattr("app.workers.pulumi.check_runtime", ready_runtime)
    monkeypatch.setattr(adapter, "IsolatedProgramSession", failed_session)
    result = _run_child(tmp_path)
    assert result.status == "failed"
    assert not result.stack_removed
    assert "credential-canary" not in result.model_dump_json()
    assert "no rollback is claimed" in result.message


def test_supervisor_discards_console_output(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    result = _run_supervised(
        [
            sys.executable,
            "-c",
            "import sys;print('credential-canary');sys.stderr.write('secret-canary')",
        ],
        environment={},
        cwd=tmp_path,
        timeout=5,
    )
    assert result == "completed"
    assert "canary" not in "".join(capfd.readouterr())


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group termination behavior")
def test_timeout_terminates_descendant_processes(tmp_path: Path) -> None:
    descendant = (
        "import time;from pathlib import Path;time.sleep(1.5);"
        "Path('orphan-survived').write_text('bad')"
    )
    parent = (
        "import subprocess,sys,time;from pathlib import Path;"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
        "Path('child-started').write_text('ready');time.sleep(30)"
    )
    started = time.monotonic()
    result = _run_supervised(
        [sys.executable, "-c", parent], environment={}, cwd=tmp_path, timeout=0.5
    )
    assert result == "timed_out"
    assert time.monotonic() - started < 5
    assert (tmp_path / "child-started").exists()
    time.sleep(1.2)
    assert not (tmp_path / "orphan-survived").exists()


@pytest.mark.parametrize("timeout", [-1, 0, 601])
def test_self_test_rejects_unbounded_deadlines(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        run_self_test(timeout=timeout)


@pytest.mark.skipif(
    os.environ.get("OLIXOPS_RUN_PULUMI_TEST") != "1",
    reason="Explicit real engine validation opt-in",
)
def test_real_provider_free_lifecycle() -> None:
    result = run_self_test(os.environ.get("OLIXOPS_PULUMI_CLI", "pulumi"))
    assert result.status == "succeeded", result.message
    assert result.outputs_verified and result.no_changes_verified and result.stack_removed
    assert [operation.operation for operation in result.operations] == [
        Operation.PREVIEW,
        Operation.UP,
        Operation.REFRESH,
        Operation.PREVIEW,
        Operation.DESTROY,
    ]
    outputs = result.operations[1].outputs
    assert any(output.name == "secret_probe" and output.secret for output in outputs)
    assert result.cleanup == "temporary_files_removed"
    assert "not-a-real-credential" not in result.model_dump_json()
