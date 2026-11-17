"""PySide6 File Intelligence & Desktop Application Dialog for JARVIS."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.files import get_file_database, get_file_indexer, get_file_search_engine
from infrastructure.logging import get_logger
from tools.windows.discovery import get_windows_app_discovery

logger = get_logger("ui.file_dialog")


class FileIntelligenceDialog(QDialog):
    """Interactive control dialog for JARVIS File Intelligence & Discovered Applications."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JARVIS — File Intelligence & Windows Applications")
        self.resize(920, 680)

        self.db = get_file_database()
        self.indexer = get_file_indexer()
        self.search_engine = get_file_search_engine()
        self.app_discovery = get_windows_app_discovery()

        self._init_ui()
        self._refresh_stats()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Header & Stats Banner
        stats_card = QFrame()
        stats_card.setStyleSheet("background-color: #161b22; border-radius: 6px; padding: 10px;")
        stats_layout = QHBoxLayout(stats_card)
        stats_layout.setContentsMargins(8, 8, 8, 8)

        self.status_icon = QLabel("📁")
        self.status_icon.setStyleSheet("font-size: 18px;")
        self.status_text = QLabel("Loading file index stats...")
        self.status_text.setStyleSheet("color: #e6edf3; font-weight: bold;")
        stats_layout.addWidget(self.status_icon)
        stats_layout.addWidget(self.status_text, 1)

        self.reindex_btn = QPushButton("🔄 Reindex Local Files")
        self.reindex_btn.clicked.connect(self._handle_reindex)
        stats_layout.addWidget(self.reindex_btn)

        layout.addWidget(stats_card)

        # 2. Search Box
        search_card = QFrame()
        search_card.setStyleSheet("background-color: #21262d; border-radius: 6px; padding: 8px;")
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(8, 4, 8, 4)

        search_label = QLabel("Search:")
        search_label.setStyleSheet("color: #8b949e; font-weight: bold;")
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search files or applications in Persian or English (e.g. 'resume', 'پروژه', 'pdf', 'فتوشاپ')..."
        )
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._execute_search)
        search_layout.addWidget(self.search_input, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._execute_search)
        search_layout.addWidget(self.search_btn)

        layout.addWidget(search_card)

        # 3. Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Extension", "Size", "Modified", "Path"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, 1)

        # 4. Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.open_btn = QPushButton("Open File / Launch")
        self.open_btn.clicked.connect(self._open_selected_item)
        btn_bar.addWidget(self.open_btn)

        self.code_btn = QPushButton("Open in VS Code")
        self.code_btn.clicked.connect(self._open_selected_in_code)
        btn_bar.addWidget(self.code_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(self.close_btn)

        layout.addLayout(btn_bar)

    def _refresh_stats(self) -> None:
        stats = self.db.get_stats()
        app_count = len(self.app_discovery.scan_applications())
        size_mb = round(stats.total_size_bytes / (1024 * 1024), 1)
        self.status_text.setText(
            f"FTS5 Index: {stats.total_files:,} files ({size_mb} MB) | {app_count} Windows Applications Discovered"
        )

    def _handle_reindex(self) -> None:
        self.reindex_btn.setEnabled(False)
        self.status_text.setText("Indexing files in background...")
        self.indexer.start_background_indexing(on_complete=self._on_indexing_complete)

    def _on_indexing_complete(self, count: int) -> None:
        QTimer.singleShot(0, lambda: self._finish_reindex(count))

    def _finish_reindex(self, count: int) -> None:
        self.reindex_btn.setEnabled(True)
        self._refresh_stats()
        self._execute_search()

    def _on_search_text_changed(self, text: str) -> None:
        # Auto search if query is at least 2 chars
        if len(text.strip()) >= 2:
            self._execute_search()

    def _execute_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            return

        results = self.search_engine.search(query, limit=50)
        self.table.setRowCount(len(results))

        for row, r in enumerate(results):
            size_kb = round(r.size_bytes / 1024, 1)
            self.table.setItem(row, 0, QTableWidgetItem(r.filename))
            self.table.setItem(row, 1, QTableWidgetItem(r.extension))
            self.table.setItem(row, 2, QTableWidgetItem(f"{size_kb} KB"))
            self.table.setItem(row, 3, QTableWidgetItem(r.to_dict()["modified"]))
            self.table.setItem(row, 4, QTableWidgetItem(r.path))

    def _get_selected_path(self) -> str | None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 4)
            if item:
                return item.text()
        return None

    def _open_selected_item(self) -> None:
        p = self._get_selected_path()
        if not p:
            QMessageBox.information(self, "No Selection", "Please select a file to open.")
            return

        try:
            os.startfile(p)
        except Exception as exc:
            QMessageBox.warning(self, "Open Error", f"Could not open '{p}': {exc}")

    def _open_selected_in_code(self) -> None:
        p = self._get_selected_path()
        if not p:
            QMessageBox.information(self, "No Selection", "Please select a file to open.")
            return

        import subprocess

        try:
            subprocess.Popen(["code", p], shell=True)
        except Exception as exc:
            QMessageBox.warning(self, "VS Code Error", f"Could not launch VS Code: {exc}")
