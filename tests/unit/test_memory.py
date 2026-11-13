"""Unit tests for SQLite memory database and state persistence."""

from pathlib import Path

from memory.base import ConversationMessage, MessageRole
from memory.database import SQLiteMemoryStore


def test_sqlite_memory_store_lifecycle(tmp_path: Path) -> None:
    """Verify SQLite database schema creation, message storage, and query retrieval."""
    db_file = tmp_path / "test_memory.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    session_id = "test-session-001"

    # Store user and assistant messages
    msg1 = ConversationMessage(
        role=MessageRole.USER,
        content="سلام جارویس",
        session_id=session_id,
        metadata={"lang": "fa"},
    )
    msg2 = ConversationMessage(
        role=MessageRole.ASSISTANT,
        content="سلام! چطور می‌توانم کمک کنم؟",
        session_id=session_id,
        metadata={"lang": "fa"},
    )

    id1 = store.store_message(msg1)
    id2 = store.store_message(msg2)

    assert id1 is not None
    assert id2 is not None

    # Retrieve messages
    messages = store.get_messages(session_id)
    assert len(messages) == 2
    assert messages[0].content == "سلام جارویس"
    assert messages[0].role == MessageRole.USER
    assert messages[1].content == "سلام! چطور می‌توانم کمک کنم؟"
    assert messages[1].role == MessageRole.ASSISTANT

    # Preferences
    store.set_preference("ui_theme", "dark_futuristic")
    pref_val = store.get_preference("ui_theme")
    assert pref_val == "dark_futuristic"

    assert store.get_preference("non_existent_key", "default_val") == "default_val"

    store.close()
