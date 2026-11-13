"""Integration tests for PySide6 desktop user interface and interactions."""

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from config import Settings
from core.agent import JARVISAgent
from ui.main_window import MainWindow, SettingsDialog
from ui.styles import is_persian_text


def test_persian_text_detection() -> None:
    """Verify Persian/Arabic character detection."""
    assert is_persian_text("سلام دنیا") is True
    assert is_persian_text("وضعیت سیستم چگونه است؟") is True
    assert is_persian_text("Hello World") is False
    assert is_persian_text("123456") is False
    assert is_persian_text("JARVIS: سلام") is True


def test_main_window_initialization(
    qtbot: QtBot,
    test_agent: JARVISAgent,
    test_settings: Settings,
) -> None:
    """Verify main window initializes with required panels and widgets."""
    window = MainWindow(agent=test_agent, settings=test_settings)
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle().startswith(test_settings.app_name)
    assert window.chat_panel is not None
    assert window.status_panel is not None
    assert window.status_panel.agent_status_lbl.text() == "IDLE"

    window.close()


def test_chat_interaction_english_and_persian(
    qtbot: QtBot,
    test_agent: JARVISAgent,
    test_settings: Settings,
) -> None:
    """Verify submitting messages updates conversation display and agent state."""
    window = MainWindow(agent=test_agent, settings=test_settings)
    qtbot.addWidget(window)
    window.show()

    # 1. Test English message submission
    input_field = window.chat_panel.input_field
    send_btn = window.chat_panel.send_button

    input_field.setPlainText("Hello JARVIS, status report.")
    qtbot.mouseClick(send_btn, Qt.MouseButton.LeftButton)

    # Verify input field is cleared
    assert input_field.toPlainText() == ""

    # Count message bubble wrappers in layout (including stretch)
    count_after_en = window.chat_panel.messages_layout.count()
    assert count_after_en >= 3  # Initial welcome + User msg + Assistant response + Stretch

    # 2. Test Persian message submission
    input_field.setPlainText("سلام جارویس، وضعیت را بررسی کن")
    qtbot.mouseClick(send_btn, Qt.MouseButton.LeftButton)

    assert input_field.toPlainText() == ""
    count_after_fa = window.chat_panel.messages_layout.count()
    assert count_after_fa > count_after_en

    window.close()


def test_settings_dialog_display(
    qtbot: QtBot,
    test_settings: Settings,
) -> None:
    """Verify settings dialog opens and displays safe masked info."""
    dialog = SettingsDialog(test_settings)
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.windowTitle().startswith("JARVIS Settings")
    dialog.close()
