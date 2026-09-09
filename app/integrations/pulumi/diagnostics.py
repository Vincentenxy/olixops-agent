"""Read engine versions without changing login or backend configuration."""

import os
import re
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from tempfile import TemporaryDirectory

from app.integrations.pulumi.models import EXPECTED_VERSION, PulumiRuntimeStatus


def check_runtime(cli: str = "pulumi", timeout_seconds: float = 3) -> PulumiRuntimeStatus:
    """Return a sanitized version probe; callers must offload it from async routes."""
    try:
        sdk_version = version("pulumi")
    except PackageNotFoundError:
        sdk_version = None
    executable = shutil.which(cli)
    if executable is None:
        return PulumiRuntimeStatus(
            sdk_version=sdk_version,
            cli_version=None,
            status="unavailable",
            message="Pulumi CLI is not installed or executable.",
        )
    try:
        # The CLI can initialize PULUMI_HOME even for `version`; the probe must
        # not create or read the operator's global Pulumi configuration.
        with TemporaryDirectory(prefix="olixops-pulumi-probe-") as temporary:
            environment = {
                key: os.environ[key]
                for key in ("SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "USER", "USERNAME", "HOME")
                if key in os.environ
            }
            environment.update({"PULUMI_HOME": temporary, "PULUMI_SKIP_UPDATE_CHECK": "true"})
            completed = subprocess.run(
                [executable, "version"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=environment,
            )
    except OSError, subprocess.TimeoutExpired:
        return PulumiRuntimeStatus(
            sdk_version=sdk_version,
            cli_version=None,
            status="unavailable",
            message="Pulumi CLI version check failed or timed out.",
        )
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", completed.stdout.strip())
    if completed.returncode != 0 or match is None:
        return PulumiRuntimeStatus(
            sdk_version=sdk_version,
            cli_version=None,
            status="unavailable",
            message="Pulumi CLI did not return a valid version.",
        )
    cli_version = match[1]
    compatible = sdk_version == cli_version == EXPECTED_VERSION
    return PulumiRuntimeStatus(
        sdk_version=sdk_version,
        cli_version=cli_version,
        status="ready" if compatible else "incompatible",
        message=(
            "Pulumi SDK and CLI versions are ready; no target backend was checked."
            if compatible
            else f"Pulumi SDK and CLI must both use {EXPECTED_VERSION}."
        ),
    )
