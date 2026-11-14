"""PySide6 Antigravity Coding Agent Dialog for JARVIS Phase 8.

Provides:
- Health and status banner (CLI discovery, active model, workspace containment)
- Workspace path selector with Browse dialog
- Dual-language prompt input (Persian & English) with auto-text direction
- Real-time NDJSON event stream log display
- Verification status (git diff, test execution results, linter status)
- Background execution via CodingAgentWorker without UI freeze
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from infrastructure.logging import get_logger
from tools.coding_agent import get_antigravity_adapter
from ui.styles import is_persian_text
from ui.workers import CodingAgentWorker

logger = get_logger("ui.coding_agent_dialog")


class CodingAgentDialog(QDialog):
    """Interactive control dialog for Google Antigravity Coding Agent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JARVIS — Google Antigravity Coding Agent")
        self.resize(880, 680)
        self.adapter = get_antigravity_adapter()
        self.active_worker: CodingAgentWorker | None = None
        self._init_ui()
        self._refresh_status()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header & Status Banner
        status_card = QFrame()
        status_card.setStyleSheet("background-color: #161b22; border-radius: 6px; padding: 10px;")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(8, 8, 8, 8)

        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet("color: #3fb950; font-size: 16px;")
        self.status_text = QLabel("Checking Antigravity CLI...")
        self.status_text.setStyleSheet("color: #e6edf3; font-weight: bold;")
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_text, 1)

        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self._refresh_status)
        status_layout.addWidget(self.refresh_btn)

        main_layout.addWidget(status_card)

        # 2. Workspace Selector
        ws_card = QFrame()
        ws_layout = QHBoxLayout(ws_card)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        ws_layout.setSpacing(8)

        ws_label = QLabel("Workspace:")
        ws_label.setStyleSheet("color: #8b949e; font-weight: bold;")
        self.ws_input = QLineEdit()
        self.ws_input.setText(str(Path.cwd().resolve()))
        self.ws_browse_btn = QPushButton("Browse...")
        self.ws_browse_btn.clicked.connect(self._browse_workspace)

        ws_layout.addWidget(ws_label)
        ws_layout.addWidget(self.ws_input, 1)
        ws_layout.addWidget(self.ws_browse_btn)
        main_layout.addWidget(ws_card)

        # 3. Main Splitter: Prompt Input & Stream Output
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Prompt input area
        prompt_box = QWidget()
        prompt_layout = QVBoxLayout(prompt_box)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_label = QLabel("Coding Instructions (Persian or English):")
        prompt_label.setStyleSheet("color: #8b949e; font-weight: bold;")
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Describe the software task, bug to fix, or test to implement...\n"
            "مثال: تابع محاسبه هش SHA-256 را پیاده سازی کن و تست های آن را بنویس."
        )
        self.prompt_edit.textChanged.connect(self._on_prompt_changed)
        prompt_layout.addWidget(prompt_label)
        prompt_layout.addWidget(self.prompt_edit)
        splitter.addWidget(prompt_box)

        # Stream / Output area
        stream_box = QWidget()
        stream_layout = QVBoxLayout(stream_box)
        stream_layout.setContentsMargins(0, 0, 0, 0)
        stream_label = QLabel("Antigravity Live Stream & Verification Log:")
        stream_label.setStyleSheet("color: #8b949e; font-weight: bold;")
        self.stream_edit = QTextEdit()
        self.stream_edit.setReadOnly(True)
        self.stream_edit.setStyleSheet(
            "background-color: #0d1117; color: #58a6ff; font-family: Consolas, monospace; font-size: 12px;"
        )
        stream_layout.addWidget(stream_label)
        stream_layout.addWidget(self.stream_edit)
        splitter.addWidget(stream_box)

        splitter.setSizes([200, 320])
        main_layout.addWidget(splitter, 1)

        # 4. Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.delegate_btn = QPushButton("Delegate to Antigravity")
        self.delegate_btn.setStyleSheet(
            "background-color: #238636; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;"
        )
        self.delegate_btn.clicked.connect(self._on_delegate_clicked)

        self.verify_btn = QPushButton("Verify Workspace")
        self.verify_btn.clicked.connect(self._on_verify_clicked)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.delegate_btn)
        btn_layout.addWidget(self.verify_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.close_btn)

        main_layout.addLayout(btn_layout)

    def _on_prompt_changed(self) -> None:
        txt = self.prompt_edit.toPlainText()
        if is_persian_text(txt):
            self.prompt_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            self.prompt_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

    def _refresh_status(self) -> None:
        status = self.adapter.get_status()
        if not status.get("enabled"):
            self.status_icon.setStyleSheet("color: #f85149; font-size: 16px;")
            self.status_text.setText("Antigravity integration is disabled in settings.")
            self.delegate_btn.setEnabled(False)
            return

        if not status.get("installed"):
            self.status_icon.setStyleSheet("color: #d29922; font-size: 16px;")
            self.status_text.setText("agy CLI not detected in PATH or known locations.")
            self.delegate_btn.setEnabled(False)
            return

        exe = status.get("executable_path", "agy.exe")
        model = status.get("model", "default")
        self.status_icon.setStyleSheet("color: #3fb950; font-size: 16px;")
        self.status_text.setText(f"Connected: {os.path.basename(exe)} | Model: {model}")
        self.delegate_btn.setEnabled(True)

    def _browse_workspace(self) -> None:
        dir_selected = QFileDialog.getExistingDirectory(
            self, "Select Workspace Directory", self.ws_input.text()
        )
        if dir_selected:
            self.ws_input.setText(dir_selected)

    def _on_delegate_clicked(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Empty Prompt", "Please enter task instructions.")
            return

        ws = self.ws_input.text().strip()
        self.stream_edit.clear()
        self.stream_edit.append(f">>> Delegating task to Antigravity in '{ws}'...\n")

        self.delegate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.active_worker = CodingAgentWorker(
            prompt=prompt,
            workspace_path=ws,
            parent=self,
        )
        self.active_worker.chunk_received.connect(self._on_stream_chunk)
        self.active_worker.task_completed.connect(self._on_task_completed)
        self.active_worker.task_failed.connect(self._on_task_failed)
        self.active_worker.start()

    def _on_stream_chunk(self, chunk: str) -> None:
        self.stream_edit.insertPlainText(chunk)
        self.stream_edit.ensureCursorVisible()

    def _on_task_completed(self, task_dict: dict[str, Any]) -> None:
        self.delegate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stream_edit.append(
            f"\n\n>>> Task completed in {task_dict.get('duration_seconds', 0):.1f}s. "
            f"Verified: {task_dict.get('verified', False)}"
        )
        QMessageBox.information(self, "Success", "Antigravity task completed successfully!")

    def _on_task_failed(self, error: str) -> None:
        self.delegate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stream_edit.append(f"\n\n>>> Task failed: {error}")
        QMessageBox.critical(self, "Task Error", f"Antigravity task failed:\n{error}")

    def _on_cancel_clicked(self) -> None:
        if self.active_worker:
            self.active_worker.cancel()
            self.stream_edit.append("\n>>> Cancellation requested...")
            self.cancel_btn.setEnabled(False)

    def _on_verify_clicked(self) -> None:
        ws = self.ws_input.text().strip()
        self.stream_edit.append(f"\n>>> Running independent verification in '{ws}'...")
        try:
            res = self.adapter.verify_workspace(ws)
            summary = (
                f"\n--- Verification Result ---\n"
                f"Verified: {res.verified}\n"
                f"Changed files ({len(res.git_changed_files)}): {res.git_changed_files}\n"
                f"Tests executed: {res.tests_executed} (Passed: {res.tests_passed})\n"
                f"Linter clean: {res.linter_clean}\n"
                f"Message: {res.message}\n"
            )
            self.stream_edit.append(summary)
            if res.git_diff_summary:
                self.stream_edit.append(f"Diff Summary:\n{res.git_diff_summary}")
        except Exception as exc:
            self.stream_edit.append(f"Verification error: {exc}")
