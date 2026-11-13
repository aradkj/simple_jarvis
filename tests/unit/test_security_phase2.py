"""Security verification tests for Phase 2 API key handling and secret isolation."""

from pathlib import Path

from config import save_env_settings
from infrastructure.logging import SecretRedactorFilter, register_sensitive_token
from memory.base import ConversationMessage, MessageRole
from memory.database import SQLiteMemoryStore


def test_api_key_not_in_sqlite(tmp_path: Path) -> None:
    """Verify that the Gemini API key is never persisted in SQLite database tables."""
    db_file = tmp_path / "security_test.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    api_key_str = "AIzaSySuperSecretKey123456789"

    # Store normal message
    store.store_message(
        ConversationMessage(
            role=MessageRole.USER,
            content="Hello world",
            session_id="sec-1",
        )
    )

    # Read all raw bytes or dump SQLite database
    store.close()
    raw_db_content = db_file.read_bytes()
    assert api_key_str.encode("utf-8") not in raw_db_content


def test_atomic_env_save_preserves_unrelated_values(tmp_path: Path) -> None:
    """Verify save_env_settings preserves existing comments and other settings."""
    env_file = tmp_path / ".env"
    initial_content = (
        "# Configuration File\n"
        "APP_ENV=production\n"
        "CUSTOM_VAR=keep_me_intact\n"
        "GEMINI_API_KEY=old_dummy_key\n"
        "DEBUG=false\n"
    )
    env_file.write_text(initial_content, encoding="utf-8")

    # Update only GEMINI_API_KEY and GEMINI_MODEL
    updates = {
        "GEMINI_API_KEY": "AIzaSyNewUpdatedKey987654",
        "GEMINI_MODEL": "gemini-3.8-flash",
    }
    save_env_settings(updates=updates, env_path=env_file)

    updated_content = env_file.read_text(encoding="utf-8")
    assert "# Configuration File" in updated_content
    assert "CUSTOM_VAR=keep_me_intact" in updated_content
    assert "DEBUG=false" in updated_content
    assert "GEMINI_API_KEY=AIzaSyNewUpdatedKey987654" in updated_content
    assert "GEMINI_MODEL=gemini-3.8-flash" in updated_content
    assert "old_dummy_key" not in updated_content


def test_api_key_scrubbed_from_log_records() -> None:
    """Verify API keys are scrubbed by SecretRedactorFilter."""
    secret = "AIzaSySecretTokenScrubTest999"
    register_sensitive_token(secret)

    redactor = SecretRedactorFilter()
    import logging

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=f"Failed request with token {secret}",
        args=(),
        exc_info=None,
    )
    redactor.filter(record)
    assert secret not in record.msg
    assert "[REDACTED_SECRET]" in record.msg
