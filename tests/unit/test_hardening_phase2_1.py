"""Regression and hardening tests for Phase 2.1."""

import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.genai import errors
from pydantic import SecretStr
from pytestqt.qtbot import QtBot

from ai.base import ConnectionErrorType
from ai.providers.gemini import (
    GeminiCancelledError,
    GeminiPermissionError,
    GeminiProvider,
    _interruptible_sleep,
)
from config import Settings, save_env_settings
from core.agent import JARVISAgent
from core.execution_context import CancellationToken
from memory.base import ConversationMessage, MessageRole
from memory.database import SQLiteMemoryStore
from ui.main_window import MainWindow


def test_request_timeout_passed_to_http_options() -> None:
    """Verify gemini_request_timeout in seconds is correctly converted to ms in HttpOptions."""
    settings = Settings(
        gemini_api_key=SecretStr("AIzaSyMockKey123"),
        gemini_request_timeout=45.0,
    )
    provider = GeminiProvider(settings=settings)
    cfg = provider._build_config()

    assert cfg.http_options is not None
    # 45.0 seconds -> 45000 milliseconds
    assert cfg.http_options.timeout == 45000


def test_permission_403_vs_invalid_key_401_distinction() -> None:
    """Verify HTTP 403 (Permission) is distinct from HTTP 401 (Invalid Key)."""
    settings = Settings(gemini_api_key=SecretStr("AIzaSyMockKey123"))

    # 1. Test 403 Permission Denied
    mock_client_403 = MagicMock()
    mock_client_403.models.generate_content.side_effect = errors.ClientError(
        code=403,
        response_json={"error": {"message": "Permission denied: Generative Language API disabled"}},
    )
    provider_403 = GeminiProvider(settings=settings, client=mock_client_403)

    res_403 = provider_403.test_connection()
    assert res_403.is_success is False
    assert res_403.error_type == ConnectionErrorType.AUTH_FAILURE
    assert "forbidden" in res_403.message.lower() or "permission" in res_403.message.lower()

    with patch.object(
        mock_client_403.models,
        "generate_content",
        side_effect=errors.ClientError(code=403, response_json={}),
    ):
        try:
            provider_403.generate_text("test")
        except Exception as exc:
            assert isinstance(exc, GeminiPermissionError)

    # 2. Test 401 Invalid Key
    mock_client_401 = MagicMock()
    mock_client_401.models.generate_content.side_effect = errors.ClientError(
        code=401,
        response_json={"error": {"message": "API key not valid."}},
    )
    provider_401 = GeminiProvider(settings=settings, client=mock_client_401)

    res_401 = provider_401.test_connection()
    assert res_401.is_success is False
    assert res_401.error_type == ConnectionErrorType.INVALID_API_KEY


def test_retry_does_not_duplicate_user_message(qtbot: QtBot, tmp_path: Path) -> None:
    """Verify retry action does not add duplicate user bubbles or duplicate database entries."""
    db_file = tmp_path / "retry_test.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    settings = Settings(
        gemini_api_key=SecretStr("AIzaSyMockKey"),
        data_dir=tmp_path,
    )
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.is_ready.return_value = True
    mock_provider.stream_text.return_value = ["Retry answer"]

    agent = JARVISAgent(settings=settings, memory_store=store, ai_provider=mock_provider)
    window = MainWindow(agent=agent, settings=settings)
    qtbot.addWidget(window)
    window.show()

    # 1. Initial user message submission
    window._handle_user_message("Initial Query")
    if window._stream_worker:
        qtbot.waitUntil(lambda: not window._stream_worker.isRunning(), timeout=2000)

    messages_1 = store.get_messages(agent.active_session_id)
    user_msgs_1 = [m for m in messages_1 if m.role == MessageRole.USER]
    assert len(user_msgs_1) == 1
    assert user_msgs_1[0].content == "Initial Query"

    # 2. Retry
    window._handle_retry("Failed error message")
    if window._stream_worker:
        qtbot.waitUntil(lambda: not window._stream_worker.isRunning(), timeout=2000)

    messages_2 = store.get_messages(agent.active_session_id)
    user_msgs_2 = [m for m in messages_2 if m.role == MessageRole.USER]
    # Critical check: User message must NOT be duplicated!
    assert len(user_msgs_2) == 1

    window.close()
    store.close()


def test_deterministic_ordering_with_same_timestamp(tmp_path: Path) -> None:
    """Verify rowid ensures deterministic ordering when timestamps are identical."""
    db_file = tmp_path / "order_test.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    fixed_time = datetime(2026, 11, 12, 10, 0, 0, tzinfo=UTC)
    s_id = "session-order"

    for i in range(10):
        store.store_message(
            ConversationMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=f"Message {i}",
                session_id=s_id,
                created_at=fixed_time,
            )
        )

    retrieved = store.get_messages(s_id, limit=20)
    assert len(retrieved) == 10
    # Must be in exact order Message 0 .. Message 9
    for i in range(10):
        assert retrieved[i].content == f"Message {i}"

    store.close()


def test_sqlite_store_thread_safety(tmp_path: Path) -> None:
    """Verify concurrent thread writes to SQLiteMemoryStore do not corrupt state."""
    db_file = tmp_path / "concurrent_test.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    errors_encountered: list[Exception] = []

    def writer_task(worker_id: int):
        try:
            for j in range(15):
                store.store_message(
                    ConversationMessage(
                        role=MessageRole.USER,
                        content=f"Worker {worker_id} msg {j}",
                        session_id=f"session-{worker_id}",
                    )
                )
        except Exception as exc:
            errors_encountered.append(exc)

    threads = [threading.Thread(target=writer_task, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors_encountered) == 0

    # Total 6 * 15 = 90 messages
    total_messages = 0
    for i in range(6):
        total_messages += len(store.get_messages(f"session-{i}", limit=100))
    assert total_messages == 90

    store.close()


def test_interruptible_sleep_cancellation() -> None:
    """Verify _interruptible_sleep halts immediately on cancellation."""
    token = CancellationToken()
    token.cancel()

    import time

    start = time.perf_counter()
    import pytest

    with pytest.raises(GeminiCancelledError):
        _interruptible_sleep(5.0, token)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2  # Aborted immediately, did not wait 5 seconds!


def test_save_env_settings_tmp_cleanup(tmp_path: Path) -> None:
    """Verify .tmp file is cleaned up even if error occurs."""
    target_env = tmp_path / "protected" / ".env"
    # Target directory doesn't exist, will cause open error
    import pytest

    with pytest.raises(OSError):
        save_env_settings({"KEY": "VAL"}, env_path=target_env)

    tmp_file = target_env.with_suffix(".tmp")
    assert not tmp_file.exists()
