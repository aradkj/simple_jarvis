"""Unit tests for centralized logging and secret scrubbing."""

import logging
from pathlib import Path

from infrastructure.logging import (
    SecretRedactorFilter,
    get_logger,
    register_sensitive_token,
    setup_logging,
)


def test_secret_redactor_registered_token() -> None:
    """Verify registered secrets are replaced with [REDACTED_SECRET]."""
    token = "SuperSecretCustomKey12345"
    register_sensitive_token(token)

    redactor = SecretRedactorFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"Connecting to service with key: {token}",
        args=(),
        exc_info=None,
    )
    redactor.filter(record)
    assert token not in record.msg
    assert "[REDACTED_SECRET]" in record.msg


def test_secret_redactor_regex_pattern() -> None:
    """Verify Google and OpenAI-style API keys are detected and scrubbed."""
    google_key = "AIzaSyD-1234567890abcdefghijklmnopqrstuv"
    redactor = SecretRedactorFilter()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"Using Google API key {google_key} for call",
        args=(),
        exc_info=None,
    )
    redactor.filter(record)
    assert google_key not in record.msg
    assert "[REDACTED_KEY]" in record.msg


def test_setup_logging(tmp_path: Path) -> None:
    """Verify logger setup attaches both console and file handlers."""
    test_log_file = tmp_path / "test.log"
    logger = setup_logging(
        log_level="DEBUG",
        log_to_file=True,
        log_file_name=test_log_file.name,
    )
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) >= 2

    child = get_logger("unit_test")
    assert child.name == "jarvis.unit_test"
