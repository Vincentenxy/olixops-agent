"""Automation API seam for reviewed programs in disposable validation workspaces.

This adapter deliberately owns an isolated local backend. Persistent deployment stacks,
their credentials, policy and distributed scheduling are separate future interfaces.
Only the standalone worker calls this module; it does not accept source code from HTTP.
"""

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pulumi import automation as auto

from app.integrations.pulumi.models import (
    Change,
    EngineEventSummary,
    Operation,
    OperationSummary,
    OutputSummary,
    Severity,
)


@dataclass(frozen=True)
class TrustedProgram:
    """A code-reviewed callback and output names selected by application code."""

    run: Callable[[], None]
    output_names: frozenset[str]


def summarize_changes[T: str](changes: Mapping[T, int]) -> dict[Change, int]:
    """Drop unknown operation names; never copy arbitrary engine strings."""
    result: dict[Change, int] = {}
    for key, count in changes.items():
        try:
            operation = Change(key)
        except ValueError:
            continue
        if type(count) is int and count >= 0:
            result[operation] = count
    return result


def summarize_outputs(
    outputs: Mapping[str, auto.OutputValue], allowed_names: frozenset[str]
) -> list[OutputSummary]:
    """Return only reviewed names and secret flags, with all values redacted."""
    return [
        OutputSummary(name=name, secret=output.secret)
        for name, output in sorted(outputs.items())
        if name in allowed_names
    ]


def summarize_event(event: auto.EngineEvent, operation: Operation) -> EngineEventSummary | None:
    """Exclude stdout, messages, URNs, inputs, outputs, metadata and config entirely."""
    sequence = max(event.sequence, 0)
    if summary := event.summary_event:
        return EngineEventSummary(
            sequence=sequence,
            operation=operation,
            kind="summary",
            changes=summarize_changes(summary.resource_changes),
        )
    if diagnostic := event.diagnostic_event:
        try:
            severity = Severity(diagnostic.severity)
        except ValueError:
            severity = None
        return EngineEventSummary(
            sequence=sequence, operation=operation, kind="diagnostic", severity=severity
        )
    resource = event.resource_pre_event or event.res_outputs_event
    if resource is not None:
        try:
            change = Change(resource.metadata.op)
        except ValueError:
            return None
        return EngineEventSummary(
            sequence=sequence, operation=operation, kind="resource", change=change
        )
    if event.cancel_event is not None:
        # The engine emits this sentinel on normal completion as well.
        return EngineEventSummary(sequence=sequence, operation=operation, kind="stream_end")
    return None


class IsolatedProgramSession:
    """Serialize operations on a fresh local stack belonging only to this validation.

    The caller supplies an empty per-run directory and must enforce a process timeout.
    This is execution isolation, not a sandbox for arbitrary Python programs.
    """

    def __init__(self, directory: Path, program: TrustedProgram) -> None:
        work_dir = directory / "workspace"
        state_dir = directory / "state"
        pulumi_home = directory / "pulumi-home"
        for path in (work_dir, state_dir):
            path.mkdir(mode=0o700)
        # Even the CLI version probe may initialize its isolated home directory.
        pulumi_home.mkdir(mode=0o700, exist_ok=True)
        backend_url = f"file://{state_dir.as_posix()}"
        self._program = program
        self._lock = Lock()
        self.events: list[EngineEventSummary] = []
        self.events_truncated = False
        self.stack_removed = False
        self._stack = auto.create_stack(
            stack_name=f"validation-{uuid4().hex}",
            project_name="olixops-validation",
            program=program.run,
            opts=auto.LocalWorkspaceOptions(
                work_dir=str(work_dir),
                pulumi_home=str(pulumi_home),
                project_settings=auto.ProjectSettings(
                    name="olixops-validation",
                    runtime="python",
                    backend=auto.ProjectBackend(url=backend_url),
                ),
                secrets_provider="passphrase",
                env_vars={
                    "PULUMI_BACKEND_URL": backend_url,
                    "PULUMI_CONFIG_PASSPHRASE": secrets.token_urlsafe(32),
                    "PULUMI_SKIP_UPDATE_CHECK": "true",
                    "PULUMI_DISABLE_AUTOMATIC_PLUGIN_ACQUISITION": "true",
                },
            ),
        )

    def _event_callback(self, operation: Operation) -> Callable[[auto.EngineEvent], None]:
        def callback(event: auto.EngineEvent) -> None:
            summary = summarize_event(event, operation)
            if summary is None:
                return
            if len(self.events) >= 4096:
                self.events_truncated = True
                return
            summary.sequence = len(self.events)
            self.events.append(summary)

        return callback

    def preview(self, *, expect_no_changes: bool = False) -> OperationSummary:
        with self._lock:
            result = self._stack.preview(
                expect_no_changes=expect_no_changes,
                on_event=self._event_callback(Operation.PREVIEW),
                color="never",
                suppress_outputs=True,
            )
            return OperationSummary(
                operation=Operation.PREVIEW, changes=summarize_changes(result.change_summary)
            )

    def up(self) -> OperationSummary:
        with self._lock:
            result = self._stack.up(
                on_event=self._event_callback(Operation.UP),
                show_secrets=False,
                color="never",
                suppress_outputs=True,
            )
            return OperationSummary(
                operation=Operation.UP,
                changes=summarize_changes(result.summary.resource_changes or {}),
                outputs=summarize_outputs(result.outputs, self._program.output_names),
            )

    def verify_constant_output(self, name: str, expected: str) -> bool:
        """Check a known non-secret test constant without exporting output values."""
        if name not in self._program.output_names:
            raise ValueError("Output name is not registered by the trusted program.")
        with self._lock:
            # SDK outputs() has no show_secrets option and may decrypt in memory.
            # Never return or log the OutputMap; only compare the reviewed constant.
            output = self._stack.outputs().get(name)
            return output is not None and not output.secret and output.value == expected

    def refresh(self) -> OperationSummary:
        with self._lock:
            result = self._stack.refresh(
                on_event=self._event_callback(Operation.REFRESH), show_secrets=False, color="never"
            )
            return OperationSummary(
                operation=Operation.REFRESH,
                changes=summarize_changes(result.summary.resource_changes or {}),
            )

    def destroy(self) -> OperationSummary:
        """Explicit cleanup of this disposable validation stack, never failure rollback."""
        with self._lock:
            result = self._stack.destroy(
                on_event=self._event_callback(Operation.DESTROY), show_secrets=False, color="never"
            )
            return OperationSummary(
                operation=Operation.DESTROY,
                changes=summarize_changes(result.summary.resource_changes or {}),
            )

    def remove_stack(self) -> None:
        with self._lock:
            self._stack.workspace.remove_stack(self._stack.name)
            self.stack_removed = True
