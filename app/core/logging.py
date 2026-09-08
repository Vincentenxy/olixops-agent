"""Application log formatting with request context and explicit extra fields."""

import json
import logging
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
)


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
            "message": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            if (value := getattr(record, field, None)) is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class DebugFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        color = "\033[31m" if record.levelno >= logging.ERROR else "\033[36m"
        details = " ".join(
            f"{field}={value}"
            for field in CONTEXT_FIELDS
            if (value := getattr(record, field, None)) is not None
        )
        message = (
            f"{timestamp} {color}{record.levelname}\033[0m {record.name}: {record.getMessage()}"
        )
        if details:
            message += f" {details}"
        if record.exc_info:
            message += f"\n{self.formatException(record.exc_info)}"
        return message


def configure_logging(*, debug: bool) -> None:
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
            },
        }
    )
