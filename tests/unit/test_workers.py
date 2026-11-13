"""Unit tests for background QThread workers."""

from unittest.mock import MagicMock

from pytestqt.qtbot import QtBot

from ai.base import ConnectionErrorType, ConnectionTestResult
from ai.providers.gemini import GeminiCancelledError, GeminiProvider
from ui.workers import ConnectionTestWorker, GeminiStreamWorker


def test_gemini_stream_worker_success(qtbot: QtBot) -> None:
    """Verify GeminiStreamWorker emits chunk_received and generation_finished signals."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.stream_text.return_value = ["Hello", " world", "!"]

    worker = GeminiStreamWorker(
        provider=mock_provider,
        prompt="Hi",
        session_id="test-session",
    )

    chunks: list[str] = []
    finished_results: list[tuple[str, str]] = []

    worker.chunk_received.connect(lambda c, sid: chunks.append(c))
    worker.generation_finished.connect(lambda text, sid: finished_results.append((text, sid)))

    with qtbot.waitSignal(worker.generation_finished, timeout=2000):
        worker.start()

    assert chunks == ["Hello", " world", "!"]
    assert finished_results == [("Hello world!", "test-session")]


def test_gemini_stream_worker_error(qtbot: QtBot) -> None:
    """Verify GeminiStreamWorker catches errors and emits generation_error."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.stream_text.side_effect = RuntimeError("API connection lost")

    worker = GeminiStreamWorker(
        provider=mock_provider,
        prompt="Hi",
        session_id="err-session",
    )

    errors_caught: list[tuple[str, str]] = []
    worker.generation_error.connect(lambda msg, sid: errors_caught.append((msg, sid)))

    with qtbot.waitSignal(worker.generation_error, timeout=2000):
        worker.start()

    assert len(errors_caught) == 1
    assert "API connection lost" in errors_caught[0][0]
    assert errors_caught[0][1] == "err-session"


def test_gemini_stream_worker_cancellation(qtbot: QtBot) -> None:
    """Verify GeminiStreamWorker handles cancellation gracefully."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.stream_text.side_effect = GeminiCancelledError("Aborted")

    worker = GeminiStreamWorker(
        provider=mock_provider,
        prompt="Long prompt",
        session_id="cancel-session",
    )

    cancelled_sessions: list[str] = []
    worker.generation_cancelled.connect(lambda sid: cancelled_sessions.append(sid))

    with qtbot.waitSignal(worker.generation_cancelled, timeout=2000):
        worker.start()

    assert cancelled_sessions == ["cancel-session"]


def test_connection_test_worker(qtbot: QtBot) -> None:
    """Verify ConnectionTestWorker executes provider test and emits test_completed."""
    mock_provider = MagicMock(spec=GeminiProvider)
    expected_result = ConnectionTestResult(
        is_success=True,
        message="Model ready",
        error_type=ConnectionErrorType.SUCCESS,
        latency_ms=120.5,
    )
    mock_provider.test_connection.return_value = expected_result

    worker = ConnectionTestWorker(provider=mock_provider)
    results: list[ConnectionTestResult] = []
    worker.test_completed.connect(lambda res: results.append(res))

    with qtbot.waitSignal(worker.test_completed, timeout=2000):
        worker.start()

    assert len(results) == 1
    assert results[0].is_success is True
    assert results[0].latency_ms == 120.5
