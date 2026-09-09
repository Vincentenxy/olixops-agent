"""Application log formatting with request context and explicit extra fields."""

import json
import logging
import re
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from logging.config import dictConfig
from typing import override

from app.core.context import trace_id

CONTEXT_FIELDS = (
    "trace_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "client_ip",
    "task_id",
    "step",
    "port",
    "server_name",
    "user_id",
    "event",
)

_secret_values: tuple[str, ...] = ()
_credential_pattern = re.compile(
    r"(?i)(\b(?:password|passwd|access_token|refresh_token|client_secret|"
    r"authorization|cookie|secret|token|api_key)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)


def redact(value: str) -> str:
    """Mask configured secrets and common credential forms; never log request bodies."""
    for secret in _secret_values:
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(://[^\s/:@]+:)[^\s/@]+(@)", r"\1[REDACTED]\2", value)
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        value,
        flags=re.DOTALL,
    )
    return _credential_pattern.sub(r"\1[REDACTED]", value)


def safe_exception(record: logging.LogRecord) -> str:
    """Retain failure type and stack locations without arbitrary exception text or locals."""
    if not record.exc_info:
        return ""
    exception_type, _, tb = record.exc_info
    frames = traceback.extract_tb(tb)
    locations = "\n".join(f"  {frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
    name = exception_type.__name__ if exception_type else "Exception"
    return redact(f"{name}\n{locations}")


class TraceContextFilter(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id") and (current_trace := trace_id.get()):
            record.trace_id = current_trace
        return True


class JsonFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for field in CONTEXT_FIELDS:
            if (value := getattr(record, field, None)) is not None:
                payload[field] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = safe_exception(record)
        return json.dumps(payload, ensure_ascii=False, default=str)


class DebugFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        color = "\033[31m" if record.levelno >= logging.ERROR else "\033[36m"
        details = " ".join(
            f"{field}={redact(str(value))}"
            for field in CONTEXT_FIELDS
            if (value := getattr(record, field, None)) is not None
        )
        message = (
            f"{timestamp} {color}{record.levelname}\033[0m {record.name}: "
            f"{redact(record.getMessage())}"
        )
        if details:
            message += f" {details}"
        if record.exc_info:
            message += f"\n{safe_exception(record)}"
        return message


def configure_logging(*, debug: bool, secrets: Iterable[str] = ()) -> None:
    global _secret_values
    _secret_values = tuple(sorted({secret for secret in secrets if secret}, key=len, reverse=True))
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"trace": {"()": TraceContextFilter}},
            "formatters": {"app": {"()": DebugFormatter if debug else JsonFormatter}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "app",
                    "filters": ["trace"],
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": "DEBUG" if debug else "INFO"},
            "loggers": {
                "uvicorn": {"handlers": [], "propagate": True},
                "uvicorn.error": {"handlers": [], "propagate": True},
                # Our middleware emits structured access logs with the request ID.
                "uvicorn.access": {"handlers": [], "propagate": False},
                "sqlalchemy.engine": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "httpx2": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                # SDK debug logging includes complete prompts and provider response bodies.
                "openai": {"level": "WARNING"},
                "langsmith": {"level": "WARNING"},
            },
        }
    )
