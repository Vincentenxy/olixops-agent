"""Request-local context; workers will explicitly bind their task's trace ID."""

from contextvars import ContextVar

trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
