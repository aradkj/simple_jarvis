"""PySide6 User Memory Management Dialog for JARVIS Phase 5."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from infrastructure.logging import get_logger
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from ui.styles import is_persian_text
from ui.workers import MemoryFetchWorker, MemoryOperationWorker

logger = get_logger("ui.memory_dialog")

if TYPE_CHECKING:
    from memory.manager import MemoryManager


class MemoryCardWidget(QFrame):
    """Visual card representing a single persistent memory record with actions."""

    approve_requested = Signal(str)
    reject_requested = Signal(str)
    edit_requested = Signal(str, str)
    delete_requested = Signal(str)

    def __init__(self, record: MemoryRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self._init_ui()

    def _init_ui(self) -> None:
        self.setObjectName("memoryCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # Style border based on status
        border_color = "#30363d"
        if self.record.status == MemoryStatus.PENDING_APPROVAL:
            border_color = "#e5a50a"  # Warning amber
        elif self.record.status == MemoryStatus.ACTIVE:
            border_color = "#238636"  # Success green
        elif self.record.status == MemoryStatus.SUPERSEDED:
            border_color = "#6e7681"  # Muted gray

        self.setStyleSheet(
            f"""
            #memoryCard {{
                background-color: #161b22;
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 10px;
                margin-bottom: 6px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 1. Header: Category badge, Key, Status badge, Timestamp
        header_layout = QHBoxLayout()

        category_label = QLabel(f"[{self.record.category.value.upper()}]")
        category_label.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 11px;")
        header_layout.addWidget(category_label)

        if self.record.key:
            key_label = QLabel(self.record.key)
            key_label.setStyleSheet("color: #8b949e; font-size: 11px;")
            header_layout.addWidget(key_label)

        if self.record.project_id:
            proj_label = QLabel(f"📁 {self.record.project_id}")
            proj_label.setStyleSheet("color: #bc8cff; font-size: 11px;")
            header_layout.addWidget(proj_label)

        header_layout.addStretch()

        status_text = self.record.status.value.replace("_", " ").title()
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {border_color}; font-weight: bold; font-size: 11px;")
        header_layout.addWidget(status_label)

        date_str = self.record.updated_at.strftime("%Y-%m-%d %H:%M")
        date_label = QLabel(date_str)
        date_label.setStyleSheet("color: #6e7681; font-size: 10px;")
        header_layout.addWidget(date_label)

        layout.addLayout(header_layout)

        # 2. Content Area (with Persian RTL auto-detection)
        content_label = QLabel(self.record.content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_label.setStyleSheet("color: #c9d1d9; font-size: 13px; line-height: 1.4;")

        if is_persian_text(self.record.content):
            content_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            content_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            content_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            content_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(content_label)

        # 3. Actions Row
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()

        if self.record.status == MemoryStatus.PENDING_APPROVAL:
            approve_btn = QPushButton("✓ Approve")
            approve_btn.setStyleSheet(
                "background-color: #238636; color: white; border-radius: 4px; padding: 4px 10px; font-size: 11px;"
            )
            approve_btn.clicked.connect(lambda: self.approve_requested.emit(self.record.id))
            actions_layout.addWidget(approve_btn)

            reject_btn = QPushButton("✗ Reject")
            reject_btn.setStyleSheet(
                "background-color: #da3633; color: white; border-radius: 4px; padding: 4px 10px; font-size: 11px;"
            )
            reject_btn.clicked.connect(lambda: self.reject_requested.emit(self.record.id))
            actions_layout.addWidget(reject_btn)

        elif self.record.status in (
            MemoryStatus.ACTIVE,
            MemoryStatus.SUPERSEDED,
            MemoryStatus.ARCHIVED,
        ):
            edit_btn = QPushButton("✏ Edit")
            edit_btn.setStyleSheet(
                "background-color: #21262d; color: #58a6ff; border: 1px solid #30363d; border-radius: 4px; padding: 4px 8px; font-size: 11px;"
            )
            edit_btn.clicked.connect(
                lambda: self.edit_requested.emit(self.record.id, self.record.content)
            )
            actions_layout.addWidget(edit_btn)

            delete_btn = QPushButton("🗑 Delete")
            delete_btn.setStyleSheet(
                "background-color: #21262d; color: #f85149; border: 1px solid #30363d; border-radius: 4px; padding: 4px 8px; font-size: 11px;"
            )
            delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.record.id))
            actions_layout.addWidget(delete_btn)

        layout.addLayout(actions_layout)


class MemoryManagementDialog(QDialog):
    """Full-featured memory viewer, search, approval, and management dialog."""

    def __init__(self, memory_manager: MemoryManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.memory_manager = memory_manager
        self._fetch_worker: MemoryFetchWorker | None = None
        self._op_worker: MemoryOperationWorker | None = None

        self.setWindowTitle("JARVIS — Persistent Memory Management")
        self.resize(780, 560)
        self.setMinimumSize(600, 420)
        self._init_ui()
        self.refresh_memories()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header title & description
        title_label = QLabel("🧠 Long-Term Persistent Memory")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #f0f6fc;")
        main_layout.addWidget(title_label)

        desc_label = QLabel(
            "User-approved persistent memories personalize future responses. "
            "Unapproved memory candidates require explicit confirmation."
        )
        desc_label.setStyleSheet("font-size: 12px; color: #8b949e;")
        main_layout.addWidget(desc_label)

        # 2. Filter & Search Controls
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search memory content or keys...")
        self.search_input.textChanged.connect(self._on_search_changed)
        filter_bar.addWidget(self.search_input, stretch=2)

        self.category_combo = QComboBox()
        self.category_combo.addItem("All Categories", None)
        self.category_combo.addItem("User Profile", MemoryCategory.USER_PROFILE)
        self.category_combo.addItem("Preference", MemoryCategory.PREFERENCE)
        self.category_combo.addItem("Project", MemoryCategory.PROJECT)
        self.category_combo.addItem("Episodic", MemoryCategory.EPISODIC)
        self.category_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(self.category_combo, stretch=1)

        self.status_combo = QComboBox()
        self.status_combo.addItem("Active Memories", MemoryStatus.ACTIVE)
        self.status_combo.addItem("Pending Approval", MemoryStatus.PENDING_APPROVAL)
        self.status_combo.addItem("Superseded", MemoryStatus.SUPERSEDED)
        self.status_combo.addItem("Archived", MemoryStatus.ARCHIVED)
        self.status_combo.addItem("All Statuses", None)
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(self.status_combo, stretch=1)

        main_layout.addLayout(filter_bar)

        # Privacy Policy Toggle: Cloud AI Transmission Control
        privacy_bar = QHBoxLayout()
        privacy_bar.setContentsMargins(2, 2, 2, 4)

        self.cloud_transmission_cb = QCheckBox(
            "🌐 Allow sending memories to cloud AI / اجازه ارسال حافظه به سرویس‌های ابری"
        )
        self.cloud_transmission_cb.setToolTip(
            "When unchecked (default), memories remain strictly on your local device and are NEVER sent to external AI providers."
        )
        self.cloud_transmission_cb.setChecked(
            getattr(self.memory_manager.settings, "memory_allow_cloud_transmission", False)
        )
        self.cloud_transmission_cb.toggled.connect(self._on_cloud_transmission_toggled)
        self.cloud_transmission_cb.setStyleSheet("color: #58a6ff; font-size: 11px;")
        privacy_bar.addWidget(self.cloud_transmission_cb)
        privacy_bar.addStretch()

        main_layout.addLayout(privacy_bar)

        # 3. Scrollable List of Memory Cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px;"
        )

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(10, 10, 10, 10)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area)

        # 4. Status Bar & Bottom Actions
        bottom_bar = QHBoxLayout()

        self.status_msg = QLabel("Loading memories...")
        self.status_msg.setStyleSheet("color: #8b949e; font-size: 11px;")
        bottom_bar.addWidget(self.status_msg)

        bottom_bar.addStretch()

        add_btn = QPushButton("✚ Add Memory")
        add_btn.setStyleSheet(
            "background-color: #238636; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;"
        )
        add_btn.clicked.connect(self._on_add_memory)
        bottom_bar.addWidget(add_btn)

        clear_btn = QPushButton("🗑 Clear All")
        clear_btn.setStyleSheet(
            "background-color: #21262d; color: #f85149; border: 1px solid #30363d; border-radius: 4px; padding: 6px 12px;"
        )
        clear_btn.clicked.connect(self._on_clear_all)
        bottom_bar.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; border-radius: 4px; padding: 6px 12px;"
        )
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)

        main_layout.addLayout(bottom_bar)

    def closeEvent(self, event) -> None:
        if self._fetch_worker and self._fetch_worker.isRunning():
            try:
                self._fetch_worker.records_loaded.disconnect()
                self._fetch_worker.error_occurred.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._fetch_worker.wait(2000)
        super().closeEvent(event)

    def _on_search_changed(self, text: str) -> None:
        self.refresh_memories()

    def _on_filter_changed(self) -> None:
        self.refresh_memories()

    def _on_cloud_transmission_toggled(self, checked: bool) -> None:
        """Update and persist user choice for transmitting memories to cloud providers."""
        self.memory_manager.settings.memory_allow_cloud_transmission = checked
        self.memory_manager.privacy_manager.allow_cloud_transmission = checked
        try:
            from config import save_env_settings

            save_env_settings({"MEMORY_ALLOW_CLOUD_TRANSMISSION": str(checked).lower()})
            status = "enabled" if checked else "disabled"
            self.status_msg.setText(f"Cloud memory transmission {status}.")
        except Exception as exc:
            logger.warning(f"Failed to persist cloud memory transmission setting: {exc}")

    def refresh_memories(self) -> None:
        """Fetch and populate memory records in background worker."""
        if self._fetch_worker and self._fetch_worker.isRunning():
            try:
                self._fetch_worker.records_loaded.disconnect()
                self._fetch_worker.error_occurred.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._fetch_worker.wait(2000)

        cat = self.category_combo.currentData()
        stat = self.status_combo.currentData()
        search_txt = self.search_input.text().strip()

        self.status_msg.setText("Refreshing...")

        self._fetch_worker = MemoryFetchWorker(
            memory_manager=self.memory_manager,
            category=cat,
            status=stat,
            search_query=search_txt,
            parent=self,
        )
        self._fetch_worker.records_loaded.connect(self._on_records_loaded)
        self._fetch_worker.error_occurred.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_records_loaded(self, records: list[MemoryRecord]) -> None:
        # Clear existing cards
        while self.cards_layout.count() > 1:
            child = self.cards_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for rec in records:
            card = MemoryCardWidget(record=rec, parent=self.cards_container)
            card.approve_requested.connect(self._on_approve_memory)
            card.reject_requested.connect(self._on_reject_memory)
            card.edit_requested.connect(self._on_edit_memory)
            card.delete_requested.connect(self._on_delete_memory)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        count = len(records)
        self.status_msg.setText(f"{count} memory record{'s' if count != 1 else ''} found.")

    def _on_fetch_error(self, err: str) -> None:
        self.status_msg.setText(f"Error loading memories: {err}")

    def _on_approve_memory(self, memory_id: str) -> None:
        self.memory_manager.approve_candidate(memory_id)
        self.refresh_memories()

    def _on_reject_memory(self, memory_id: str) -> None:
        self.memory_manager.reject_candidate(memory_id)
        self.refresh_memories()

    def _on_edit_memory(self, memory_id: str, current_content: str) -> None:
        new_text, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Memory Record",
            "Update memory content:",
            current_content,
        )
        if ok and new_text.strip():
            try:
                self.memory_manager.edit_memory(memory_id=memory_id, new_content=new_text.strip())
                self.refresh_memories()
            except Exception as exc:
                QMessageBox.warning(self, "Edit Failed", str(exc))

    def _on_delete_memory(self, memory_id: str) -> None:
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this memory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.memory_manager.delete_memory(memory_id, soft=True)
            self.refresh_memories()

    def _on_add_memory(self) -> None:
        content, ok = QInputDialog.getMultiLineText(
            self,
            "Add Persistent Memory",
            "Enter facts, preferences, or project notes to remember:",
        )
        if ok and content.strip():
            try:
                self.memory_manager.create_approved_memory(
                    content=content.strip(),
                    category=MemoryCategory.PREFERENCE,
                )
                self.refresh_memories()
            except Exception as exc:
                QMessageBox.warning(self, "Save Failed", str(exc))

    def _on_clear_all(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Confirm Permanent Erasure",
            "Are you sure you want to delete ALL long-term memories?\n\n"
            "This will not affect your conversation history, but all saved personal preferences and project context will be erased.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            count = self.memory_manager.clear_all()
            QMessageBox.information(
                self, "Cleared", f"Successfully cleared {count} memory records."
            )
            self.refresh_memories()
