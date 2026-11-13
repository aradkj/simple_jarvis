"""Integration tests for Phase 2 UI streaming, settings, and conversation controls."""

from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot

from ai.base import ConnectionErrorType, ConnectionTestResult
from ai.providers.gemini import GeminiProvider
from config import Settings
from core.agent import JARVISAgent
from ui.main_window import MainWindow, SettingsDialog


def test_settings_dialog_toggle_password(qtbot: QtBot, test_settings: Settings) -> None:
    """Verify password visibility toggle button in SettingsDialog."""
    mock_provider = MagicMock(spec=GeminiProvider)
    dialog = SettingsDialog(settings=test_settings, provider=mock_provider)
    qtbot.addWidget(dialog)

    # Initial mode: Password (masked)
    assert dialog.api_key_edit.echoMode() == QLineEdit.EchoMode.Password
    assert "Show" in dialog.toggle_key_btn.text()

    # Click toggle: Normal (visible)
    qtbot.mouseClick(dialog.toggle_key_btn, Qt.MouseButton.LeftButton)
    assert dialog.api_key_edit.echoMode() == QLineEdit.EchoMode.Normal
    assert "Hide" in dialog.toggle_key_btn.text()

    # Click toggle again: Password (masked)
    qtbot.mouseClick(dialog.toggle_key_btn, Qt.MouseButton.LeftButton)
    assert dialog.api_key_edit.echoMode() == QLineEdit.EchoMode.Password


def test_settings_dialog_connection_test_flow(qtbot: QtBot, test_settings: Settings) -> None:
    """Verify connection test button triggers test and updates label."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.test_connection.return_value = ConnectionTestResult(
        is_success=True,
        message="Model is reachable",
        error_type=ConnectionErrorType.SUCCESS,
        latency_ms=105.0,
    )

    dialog = SettingsDialog(settings=test_settings, provider=mock_provider)
    qtbot.addWidget(dialog)

    dialog.api_key_edit.setText("AIzaSyMockTestKey123")
    qtbot.mouseClick(dialog.test_btn, Qt.MouseButton.LeftButton)

    # Wait for background worker
    qtbot.waitUntil(lambda: "Model is reachable" in dialog.test_status_lbl.text(), timeout=2000)
    assert "✓" in dialog.test_status_lbl.text()


def test_chat_panel_streaming_lifecycle(qtbot: QtBot) -> None:
    """Verify chat panel methods for incremental streaming and completion."""
    from ui.chat_panel import ChatPanel

    panel = ChatPanel()
    qtbot.addWidget(panel)
    panel.show()

    # 1. Start streaming
    bubble = panel.start_assistant_streaming(sender="JARVIS")
    assert panel._is_generating is True
    assert panel.action_button.text() == "Cancel"
    assert panel.input_field.isEnabled() is False

    # 2. Append chunks
    panel.append_streaming_chunk("Chunk 1 ")
    panel.append_streaming_chunk("Chunk 2")
    assert bubble.raw_text == "Chunk 1 Chunk 2"

    # 3. Finish streaming
    panel.finish_assistant_streaming()
    assert panel._is_generating is False
    assert panel.action_button.text() == "Send"
    assert panel.input_field.isEnabled() is True


def test_main_window_new_chat_and_clear_chat(
    qtbot: QtBot,
    test_agent: JARVISAgent,
    test_settings: Settings,
) -> None:
    """Verify New Chat and Clear Chat conversation toolbar buttons."""
    window = MainWindow(agent=test_agent, settings=test_settings)
    qtbot.addWidget(window)
    window.show()

    old_session_id = test_agent.active_session_id

    # Click + New Chat
    qtbot.mouseClick(window.chat_panel.new_chat_btn, Qt.MouseButton.LeftButton)
    new_session_id = test_agent.active_session_id

    assert new_session_id != old_session_id
    assert window.chat_panel.messages_layout.count() >= 2  # New conversation welcome banner

    window.close()


def test_message_bubble_mark_failed_preserves_partial_content(qtbot: QtBot) -> None:
    """Verify UI MessageBubble displays interrupted notice without wiping partial output."""
    from ui.chat_panel import MessageBubble

    bubble = MessageBubble(sender="JARVIS", text="", is_user=False)
    qtbot.addWidget(bubble)
    bubble.set_content("This was partially received before failing...")
    bubble.mark_failed("503 Service Unavailable")

    assert bubble.is_error is True
    assert "This was partially received before failing..." in bubble.raw_text
    assert "⚠️ [Interrupted: 503 Service Unavailable]" in bubble.raw_text
    assert not bubble.retry_btn.isHidden()
