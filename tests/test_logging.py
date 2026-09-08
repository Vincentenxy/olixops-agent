"""Log formats retain useful request fields without serializing arbitrary extras."""

import json
import logging
from datetime import datetime

from app.core.context import trace_id
from app.core.logging import DebugFormatter, JsonFormatter, TraceContextFilter


def test_release_log_has_timezone_and_selected_context() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "request completed", (), None)
    record.method = "GET"
    record.path = "/api/v1/pub/health"
    record.status_code = 200
    record.duration_ms = 1.5
    record.client_ip = "127.0.0.1"
    record.Authorization = "a credential that must not appear as an extra field"
    token = trace_id.set("log-trace")
    try:
        TraceContextFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        trace_id.reset(token)
    assert payload["trace_id"] == "log-trace"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.5
    assert payload["client_ip"] == "127.0.0.1"
    assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None
    assert "Authorization" not in payload


def test_logs_without_context_omit_trace_id() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "started", (), None)
    TraceContextFilter().filter(record)
    assert "trace_id" not in json.loads(JsonFormatter().format(record))


def test_debug_log_has_expected_colors() -> None:
    info = logging.LogRecord("app.test", logging.INFO, __file__, 1, "started", (), None)
    error = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "failed", (), None)
    assert "\033[36mINFO" in DebugFormatter().format(info)
    assert "\033[31mERROR" in DebugFormatter().format(error)
