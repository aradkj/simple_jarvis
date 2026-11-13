"""Status panel displaying agent, system, connectivity, and voice status."""

import platform
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StatusPanel(QWidget):
    """Sidebar widget presenting live telemetry and subsystem indicators."""

    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(280)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # 1. Agent Status Card
        agent_card = QFrame()
        agent_card.setObjectName("StatusCard")
        agent_layout = QVBoxLayout(agent_card)

        agent_title = QLabel("AGENT STATE")
        agent_title.setObjectName("CardTitle")
        self.agent_status_lbl = QLabel("IDLE")
        self.agent_status_lbl.setObjectName("CardValue")
        self.agent_status_lbl.setStyleSheet("color: #3fb950; font-weight: bold;")

        agent_layout.addWidget(agent_title)
        agent_layout.addWidget(self.agent_status_lbl)
        layout.addWidget(agent_card)

        # 2. Host System Status Card
        sys_card = QFrame()
        sys_card.setObjectName("StatusCard")
        sys_layout = QVBoxLayout(sys_card)

        sys_title = QLabel("HOST SYSTEM")
        sys_title.setObjectName("CardTitle")

        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        py_info = (
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

        sys_os_lbl = QLabel(os_info)
        sys_os_lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        sys_py_lbl = QLabel(py_info)
        sys_py_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")

        sys_layout.addWidget(sys_title)
        sys_layout.addWidget(sys_os_lbl)
        sys_layout.addWidget(sys_py_lbl)
        layout.addWidget(sys_card)

        # 3. Cloud AI Connection Status
        ai_card = QFrame()
        ai_card.setObjectName("StatusCard")
        ai_layout = QVBoxLayout(ai_card)

        ai_title = QLabel("AI PROVIDER")
        ai_title.setObjectName("CardTitle")
        self.ai_model_lbl = QLabel("gemini-3.8-flash")
        self.ai_model_lbl.setObjectName("CardValue")
        self.ai_model_lbl.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 13px;")

        self.ai_status_lbl = QLabel("Standby / Checking...")
        self.ai_status_lbl.setStyleSheet("color: #d29922; font-size: 11px;")

        self.ai_desc_lbl = QLabel("Official Google GenAI SDK integration active.")
        self.ai_desc_lbl.setWordWrap(True)
        self.ai_desc_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")

        ai_layout.addWidget(ai_title)
        ai_layout.addWidget(self.ai_model_lbl)
        ai_layout.addWidget(self.ai_status_lbl)
        ai_layout.addWidget(self.ai_desc_lbl)
        layout.addWidget(ai_card)

        # 4. Voice Engine Status (Phase 9/10 Placeholder)
        voice_card = QFrame()
        voice_card.setObjectName("StatusCard")
        voice_layout = QVBoxLayout(voice_card)

        voice_title = QLabel("VOICE ENGINE")
        voice_title.setObjectName("CardTitle")
        self.voice_status_lbl = QLabel("Standby / Inactive")
        self.voice_status_lbl.setStyleSheet("color: #8b949e; font-weight: 600; font-size: 12px;")

        voice_desc = QLabel("Wake word and Gemini Live audio scheduled for Phase 9/10.")
        voice_desc.setWordWrap(True)
        voice_desc.setStyleSheet("color: #6e7681; font-size: 11px;")

        voice_layout.addWidget(voice_title)
        voice_layout.addWidget(self.voice_status_lbl)
        voice_layout.addWidget(voice_desc)
        layout.addWidget(voice_card)

        layout.addStretch()

        # 5. Settings Button
        settings_btn = QPushButton("⚙ System Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings_btn)

    def set_agent_status(self, status: str, color_hex: str = "#3fb950") -> None:
        """Update the agent status label text and color."""
        self.agent_status_lbl.setText(status.upper())
        self.agent_status_lbl.setStyleSheet(f"color: {color_hex}; font-weight: bold;")

    def set_ai_status(self, model: str, status_text: str, is_ready: bool = False) -> None:
        """Update model identifier and connection indicator."""
        self.ai_model_lbl.setText(model)
        self.ai_status_lbl.setText(status_text)
        color = "#3fb950" if is_ready else "#d29922"
        self.ai_status_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")
