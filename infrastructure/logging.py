"""Centralized logging infrastructure for JARVIS with secret redaction."""

import logging
import re
import sys
from collections.abc import Set
from logging.handlers import RotatingFileHandler

from infrastructure.paths import get_logs_dir

# Set of tokens to scrub from log outputs
_SENSITIVE_TOKENS: set[str] = set()

# Regex pattern for potential API keys or tokens (e.g. AIza..., sk-...)
_API_KEY_PATTERN = re.compile(r"(AIza[0-9A-Za-z\-_]{35}|sk-[a-zA-Z0-9]{20,})")


class SecretRedactorFilter(logging.Filter):
    """Logging filter that scrubs sensitive credentials and API keys from records."""

    def __init__(self, sensitive_tokens: Set[str] | None = None) -> None:
        super().__init__()
        self.sensitive_tokens = (
            sensitive_tokens if sensitive_tokens is not None else _SENSITIVE_TOKENS
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact_value(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact_value(arg) for arg in record.args)
            elif isinstance(record.args, list):
                record.args = [self._redact_value(arg) for arg in record.args]

        return True

    def _redact_value(self, val: object) -> object:
        if isinstance(val, str):
            return self._redact(val)
        return val

    def _redact(self, text: str) -> str:
        # Redact known registered tokens
        for token in self.sensitive_tokens:
            if token and len(token) >= 4 and token in text:
                text = text.replace(token, "[REDACTED_SECRET]")

        # Redact regex matched patterns
        text = _API_KEY_PATTERN.sub("[REDACTED_KEY]", text)
        return text


def register_sensitive_token(token: str | None) -> None:
    """Register a secret token to be redacted from all log outputs."""
    if token and len(token.strip()) >= 4:
        _SENSITIVE_TOKENS.add(token.strip())


def setup_logging(
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_file_name: str = "jarvis.log",
) -> logging.Logger:
    """Initialize and configure centralized application logging.

    Args:
        log_level: Logging level string ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        log_to_file: Whether to attach a file handler.
        log_file_name: Name of the log file under the logs directory.

    Returns:
        The configured root or application logger.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger("jarvis")
    logger.setLevel(level)

    # Avoid adding duplicate handlers on multiple setup calls
    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(threadName)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    redactor = SecretRedactorFilter()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redactor)
    logger.addHandler(console_handler)

    # File Handler
    if log_to_file:
        log_path = get_logs_dir() / log_file_name
        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger(name: str = "jarvis") -> logging.Logger:
    """Get a child or specific logger under the jarvis namespace."""
    if not name.startswith("jarvis"):
        return logging.getLogger(f"jarvis.{name}")
    return logging.getLogger(name)
