"""Application logs retain useful locations while withholding common credential forms."""

import json
import logging
import sys

import pytest

from app.core.logging import DebugFormatter, JsonFormatter, configure_logging, redact


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer unique-credential-value",
        '{"password": "unique-credential-value"}',
        "postgresql://user:unique-credential-value@localhost/database",
        "refresh_token=unique-credential-value",
        "-----BEGIN PRIVATE KEY-----\nunique-credential-value\n-----END PRIVATE KEY-----",
    ],
)
def test_credentials_are_removed_from_both_log_formats(message: str) -> None:
    record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, message, (), None)
    assert "unique-credential-value" not in JsonFormatter().format(record)
    assert "unique-credential-value" not in DebugFormatter().format(record)


def test_configured_secret_is_removed_even_without_a_field_label() -> None:
    configure_logging(debug=False, secrets=["an-unlabelled-secret"])
    try:
        assert redact("provider said an-unlabelled-secret") == "provider said [REDACTED]"
    finally:
        configure_logging(debug=False)


def test_exception_message_and_locals_are_not_serialized() -> None:
    try:
        raise ValueError("unlabelled-sensitive-provider-payload")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "provider call failed", (), sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "unlabelled-sensitive-provider-payload" not in json.dumps(payload)
    assert "ValueError" in payload["exception"]
    assert "test_exception_message_and_locals_are_not_serialized" in payload["exception"]
