"""Unit tests for conversation context management and multi-turn persistence."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from ai.providers.gemini import GeminiProvider
from config import Settings
from memory.base import ConversationMessage, MessageRole, MessageStatus
from memory.database import SQLiteMemoryStore


@pytest.fixture
def memory_store(tmp_path: Path) -> SQLiteMemoryStore:
    db_file = tmp_path / "conv_test.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()
    return store


def test_multi_turn_history_formatting(memory_store: SQLiteMemoryStore) -> None:
    """Verify GeminiProvider._build_contents preserves prior turns and excludes failed ones."""
    settings = Settings(
        gemini_api_key=SecretStr("AIzaSyMockKey123"),
        conversation_history_limit=5,
    )
    provider = GeminiProvider(settings=settings)

    history = [
        ConversationMessage(
            role=MessageRole.USER,
            content="What is Python?",
            session_id="s1",
            status=MessageStatus.COMPLETED,
        ),
        ConversationMessage(
            role=MessageRole.ASSISTANT,
            content="Python is a programming language.",
            session_id="s1",
            status=MessageStatus.COMPLETED,
        ),
        ConversationMessage(
            role=MessageRole.USER,
            content="Failed query",
            session_id="s1",
            status=MessageStatus.FAILED,  # Must be omitted!
        ),
        ConversationMessage(
            role=MessageRole.ASSISTANT,
            content="Cancelled partial",
            session_id="s1",
            status=MessageStatus.CANCELLED,  # Must be omitted!
        ),
    ]

    contents = provider._build_contents(prompt="Tell me more about it.", history=history)

    # Expected: Turn 1 (user), Turn 2 (model), Current prompt (user) -> 3 contents total
    assert len(contents) == 3
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "What is Python?"
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "Python is a programming language."
    assert contents[2].role == "user"
    assert contents[2].parts[0].text == "Tell me more about it."


def test_conversation_history_limit(memory_store: SQLiteMemoryStore) -> None:
    """Verify conversation history sent to provider is capped by configured limit."""
    settings = Settings(
        gemini_api_key=SecretStr("AIzaSyMockKey123"),
        conversation_history_limit=2,
    )
    provider = GeminiProvider(settings=settings)

    # 4 messages in history
    history = [
        ConversationMessage(role=MessageRole.USER, content="Msg 1", session_id="s1"),
        ConversationMessage(role=MessageRole.ASSISTANT, content="Reply 1", session_id="s1"),
        ConversationMessage(role=MessageRole.USER, content="Msg 2", session_id="s1"),
        ConversationMessage(role=MessageRole.ASSISTANT, content="Reply 2", session_id="s1"),
    ]

    contents = provider._build_contents(prompt="Msg 3", history=history)
    # With limit=2, only last 2 history messages + current prompt = 3 contents
    assert len(contents) == 3
    assert contents[0].parts[0].text == "Msg 2"
    assert contents[1].parts[0].text == "Reply 2"
    assert contents[2].parts[0].text == "Msg 3"


def test_session_lifecycle_and_isolation(memory_store: SQLiteMemoryStore) -> None:
    """Verify creating sessions, storing messages, and session isolation."""
    s1 = memory_store.create_session("Session 1")
    s2 = memory_store.create_session("Session 2")
    assert s1 != s2

    # Insert messages into s1 and s2
    memory_store.store_message(
        ConversationMessage(role=MessageRole.USER, content="S1 user", session_id=s1)
    )
    memory_store.store_message(
        ConversationMessage(role=MessageRole.USER, content="S2 user", session_id=s2)
    )

    msgs_s1 = memory_store.get_messages(s1)
    msgs_s2 = memory_store.get_messages(s2)

    assert len(msgs_s1) == 1
    assert msgs_s1[0].content == "S1 user"
    assert len(msgs_s2) == 1
    assert msgs_s2[0].content == "S2 user"

    # Clear s1
    memory_store.clear_session_messages(s1)
    assert len(memory_store.get_messages(s1)) == 0
    # s2 remains intact
    assert len(memory_store.get_messages(s2)) == 1


def test_message_content_and_status_update(memory_store: SQLiteMemoryStore) -> None:
    """Verify in-flight streaming message can be updated to completed or cancelled."""
    msg = ConversationMessage(
        role=MessageRole.ASSISTANT,
        content="Streaming...",
        session_id="s1",
        status=MessageStatus.STREAMING,
    )
    msg_id = memory_store.store_message(msg)

    # Verify initial status
    stored = memory_store.get_messages("s1")
    assert stored[0].status == MessageStatus.STREAMING
    assert stored[0].content == "Streaming..."

    # Update to COMPLETED
    memory_store.update_message_content(
        message_id=msg_id,
        content="Full completed answer.",
        status=MessageStatus.COMPLETED,
    )
    updated = memory_store.get_messages("s1")
    assert updated[0].status == MessageStatus.COMPLETED
    assert updated[0].content == "Full completed answer."
