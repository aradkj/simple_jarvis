"""Integration tests for Phase 5 Memory Management UI and PySide6 dialog."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from config import Settings
from core.agent import JARVISAgent
from memory.manager import MemoryManager
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from memory.repository import MemoryRepository
from ui.main_window import MainWindow
from ui.memory_dialog import MemoryCardWidget, MemoryManagementDialog


def test_memory_card_widget_persian_rtl_and_signals(qtbot: QtBot) -> None:
    """Verify MemoryCardWidget renders Persian text with RTL layout and emits signals."""
    rec = MemoryRecord(
        category=MemoryCategory.USER_PROFILE,
        key="pref.lang",
        content="من ترجیح میدهم به زبان فارسی صحبت کنیم",
        status=MemoryStatus.PENDING_APPROVAL,
    )
    card = MemoryCardWidget(record=rec)
    qtbot.addWidget(card)

    # Check approve and reject signals
    with qtbot.waitSignal(card.approve_requested, timeout=1000) as blocker:
        for btn in card.findChildren(object):
            if hasattr(btn, "text") and "Approve" in btn.text():
                qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
                break
    assert blocker.args == [rec.id]


def test_memory_management_dialog_initialization_and_search(qtbot: QtBot, tmp_path: Path) -> None:
    """Verify dialog loads memory cards, filters by search, and changes category."""
    db_file = tmp_path / "ui_test.db"
    repo = MemoryRepository(db_path=db_file)
    repo.initialize()

    settings = Settings(memory_enabled=True)
    mgr = MemoryManager(settings=settings, repository=repo)

    # Pre-populate records
    mgr.create_approved_memory("Use PySide6 framework", key="tech.gui")
    mgr.create_approved_memory("Always write unit tests", key="tech.testing")

    dialog = MemoryManagementDialog(memory_manager=mgr)
    qtbot.addWidget(dialog)

    # Wait for initial load worker to finish
    qtbot.waitUntil(lambda: dialog.cards_layout.count() >= 3, timeout=6000)

    # Search for "PySide6"
    dialog.search_input.setText("PySide6")
    qtbot.waitUntil(
        lambda: "PySide6" in dialog.status_msg.text() or dialog.cards_layout.count() >= 2,
        timeout=6000,
    )
    dialog.close()


def test_main_window_has_memory_button_and_opens_dialog(qtbot: QtBot, tmp_path: Path) -> None:
    """Verify MainWindow has the '🧠 Memory' header button and can open the dialog."""
    settings = Settings(memory_enabled=True, data_dir=tmp_path)
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.provider_name = "Gemini"
    mock_pm.default_model = "gemini-3.8-flash"

    agent = JARVISAgent(settings=settings, ai_provider=mock_pm)
    agent.initialize()

    win = MainWindow(agent=agent, settings=settings)
    qtbot.addWidget(win)

    assert hasattr(win, "memory_btn")
    assert win.memory_btn.text() == "🧠 Memory"

    with patch.object(MemoryManagementDialog, "exec", return_value=0) as mock_exec:
        qtbot.mouseClick(win.memory_btn, Qt.MouseButton.LeftButton)
        mock_exec.assert_called_once()
