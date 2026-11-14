"""Main desktop window for the JARVIS personal assistant application."""

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ai.base import BaseAIProvider, ConnectionTestResult
from ai.catalog import ModelCatalog
from ai.providers.gemini import GeminiProvider
from ai.registry import create_default_registry
from config import (
    SUPPORTED_GEMINI_MODELS,
    SUPPORTED_PROVIDERS,
    Settings,
    get_settings,
    save_env_settings,
)
from core.agent import AgentState, JARVISAgent
from core.events import AgentEvent, AgentEventType
from infrastructure.logging import get_logger
from memory.base import MessageStatus
from tools.filesystem.path_security import get_path_security_service
from ui.chat_panel import ChatPanel
from ui.coding_agent_dialog import CodingAgentDialog
from ui.memory_dialog import MemoryManagementDialog
from ui.status_panel import StatusPanel
from ui.styles import DARK_THEME_QSS
from ui.workers import AgentExecutionWorker, ConnectionTestWorker, GeminiStreamWorker

logger = get_logger("ui.main_window")


class SettingsDialog(QDialog):
    """Multi-provider settings configuration dialog for API keys, models, and fallback."""

    def __init__(
        self,
        settings: Settings,
        provider: BaseAIProvider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.provider = provider or GeminiProvider(settings=self.settings)
        self._test_worker: ConnectionTestWorker | None = None
        self._active_provider_id = "gemini"

        # In-memory working copies for all 6 providers
        self._provider_data: dict[str, dict[str, Any]] = {
            "gemini": {
                "api_key": self.settings.gemini_api_key.get_secret_value()
                if self.settings.gemini_api_key
                else "",
                "model": self.settings.gemini_model,
                "base_url": "",
                "enabled": self.settings.gemini_enabled,
            },
            "openai": {
                "api_key": self.settings.openai_api_key.get_secret_value()
                if self.settings.openai_api_key
                else "",
                "model": self.settings.openai_model,
                "base_url": self.settings.openai_base_url or "",
                "enabled": self.settings.openai_enabled,
            },
            "anthropic": {
                "api_key": self.settings.anthropic_api_key.get_secret_value()
                if self.settings.anthropic_api_key
                else "",
                "model": self.settings.anthropic_model,
                "base_url": "",
                "enabled": self.settings.anthropic_enabled,
            },
            "deepseek": {
                "api_key": self.settings.deepseek_api_key.get_secret_value()
                if self.settings.deepseek_api_key
                else "",
                "model": self.settings.deepseek_model,
                "base_url": self.settings.deepseek_base_url or "https://api.deepseek.com",
                "enabled": self.settings.deepseek_enabled,
            },
            "openrouter": {
                "api_key": self.settings.openrouter_api_key.get_secret_value()
                if self.settings.openrouter_api_key
                else "",
                "model": self.settings.openrouter_model,
                "base_url": self.settings.openrouter_base_url or "https://openrouter.ai/api/v1",
                "enabled": self.settings.openrouter_enabled,
            },
            "groq": {
                "api_key": self.settings.groq_api_key.get_secret_value()
                if self.settings.groq_api_key
                else "",
                "model": self.settings.groq_model,
                "base_url": self.settings.groq_base_url or "https://api.groq.com/openai/v1",
                "enabled": self.settings.groq_enabled,
            },
        }

        self.setWindowTitle("JARVIS Settings — Multi-Provider AI Configuration")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setMinimumSize(540, 480)
        self.resize(660, 720)
        self.setStyleSheet(DARK_THEME_QSS)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(14)

        # Title
        title_lbl = QLabel("SYSTEM & AI PROVIDERS CONFIGURATION")
        title_lbl.setObjectName("AppTitle")
        subtitle_lbl = QLabel(
            "Configure credentials, models, and fallback routing for Gemini, OpenAI, Claude, DeepSeek, OpenRouter, and Groq."
        )
        subtitle_lbl.setObjectName("AppSubtitle")
        layout.addWidget(title_lbl)
        layout.addWidget(subtitle_lbl)

        # 1. Global Routing Card
        routing_card = QFrame()
        routing_card.setObjectName("StatusCard")
        routing_layout = QGridLayout(routing_card)
        routing_layout.setContentsMargins(14, 12, 14, 12)
        routing_layout.setSpacing(10)

        routing_layout.addWidget(QLabel("<b>Default Provider:</b>"), 0, 0)
        self.default_provider_combo = QComboBox()
        for p in SUPPORTED_PROVIDERS:
            self.default_provider_combo.addItem(p)
        self.default_provider_combo.setCurrentText(self.settings.default_provider)
        routing_layout.addWidget(self.default_provider_combo, 0, 1)

        self.auto_fallback_chk = QCheckBox("Enable Automatic Fallback (Master Switch)")
        self.auto_fallback_chk.setChecked(self.settings.enable_auto_fallback)
        routing_layout.addWidget(self.auto_fallback_chk, 1, 0, 1, 2)

        self.intra_provider_fallback_chk = QCheckBox(
            "Allow Intra-Provider Model Fallback (within same provider)"
        )
        self.intra_provider_fallback_chk.setChecked(self.settings.allow_intra_provider_fallback)
        routing_layout.addWidget(self.intra_provider_fallback_chk, 2, 0, 1, 2)

        self.cross_provider_fallback_chk = QCheckBox(
            "Allow Cross-Provider Fallback (to alternative providers)"
        )
        self.cross_provider_fallback_chk.setChecked(self.settings.allow_cross_provider_fallback)
        routing_layout.addWidget(self.cross_provider_fallback_chk, 3, 0, 1, 2)

        self.cross_provider_prompt_chk = QCheckBox(
            "Allow Cross-Provider Prompt Transfer (transmit prompt to alternative provider)"
        )
        self.cross_provider_prompt_chk.setChecked(
            self.settings.allow_cross_provider_prompt_transfer
        )
        routing_layout.addWidget(self.cross_provider_prompt_chk, 4, 0, 1, 2)

        self.cross_provider_history_chk = QCheckBox(
            "Allow Cross-Provider History Transfer (transmit chat history to alternative provider)"
        )
        self.cross_provider_history_chk.setChecked(
            self.settings.allow_cross_provider_history_transfer
        )
        routing_layout.addWidget(self.cross_provider_history_chk, 5, 0, 1, 2)
        layout.addWidget(routing_card)

        # 2. Provider Details Card
        form_card = QFrame()
        form_card.setObjectName("StatusCard")
        form_layout = QGridLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(10)

        # Provider Selector row
        form_layout.addWidget(QLabel("<b>Provider:</b>"), 0, 0)
        provider_row = QHBoxLayout()
        self.provider_select_combo = QComboBox()
        for p in SUPPORTED_PROVIDERS:
            self.provider_select_combo.addItem(p)
        self.provider_select_combo.currentTextChanged.connect(self._on_provider_selection_changed)
        provider_row.addWidget(self.provider_select_combo)

        self.provider_enabled_chk = QCheckBox("Enabled")
        self.provider_enabled_chk.setChecked(True)
        provider_row.addWidget(self.provider_enabled_chk)
        form_layout.addLayout(provider_row, 0, 1)

        # API Key Input
        self.api_key_label = QLabel("<b>API Key:</b>")
        form_layout.addWidget(self.api_key_label, 1, 0)
        key_container = QWidget()
        key_layout = QHBoxLayout(key_container)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Enter API Key")
        if self.settings.gemini_api_key:
            self.api_key_edit.setText(self.settings.gemini_api_key.get_secret_value())

        self.toggle_key_btn = QPushButton("👁 Show")
        self.toggle_key_btn.setFixedWidth(65)
        self.toggle_key_btn.clicked.connect(self._toggle_key_visibility)

        key_layout.addWidget(self.api_key_edit)
        key_layout.addWidget(self.toggle_key_btn)
        form_layout.addWidget(key_container, 1, 1)

        # Model Selection
        self.model_label = QLabel("<b>Model:</b>")
        form_layout.addWidget(self.model_label, 2, 0)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        for m in SUPPORTED_GEMINI_MODELS:
            self.model_combo.addItem(m)
        self.model_combo.setCurrentText(self.settings.gemini_model)
        form_layout.addWidget(self.model_combo, 2, 1)

        # Base URL Row (for OpenAI, DeepSeek, OpenRouter, Groq)
        self.base_url_label = QLabel("<b>Base URL:</b>")
        form_layout.addWidget(self.base_url_label, 3, 0)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1 (optional)")
        form_layout.addWidget(self.base_url_edit, 3, 1)

        # Generation Parameters
        form_layout.addWidget(QLabel("<b>Temperature:</b>"), 4, 0)
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(self.settings.gemini_temperature)
        form_layout.addWidget(self.temp_spin, 4, 1)

        form_layout.addWidget(QLabel("<b>Max Tokens:</b>"), 5, 0)
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(256, 32768)
        self.tokens_spin.setSingleStep(512)
        self.tokens_spin.setValue(self.settings.gemini_max_output_tokens)
        form_layout.addWidget(self.tokens_spin, 5, 1)

        form_layout.addWidget(QLabel("<b>Timeout (s):</b>"), 6, 0)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(10.0, 300.0)
        self.timeout_spin.setValue(self.settings.gemini_request_timeout)
        form_layout.addWidget(self.timeout_spin, 6, 1)

        layout.addWidget(form_card)

        # Connection Test Section
        test_container = QWidget()
        test_layout = QHBoxLayout(test_container)
        test_layout.setContentsMargins(0, 0, 0, 0)

        self.test_btn = QPushButton("⚡ Test Connection")
        self.test_btn.clicked.connect(self._run_connection_test)
        self.test_status_lbl = QLabel("")
        self.test_status_lbl.setWordWrap(True)

        test_layout.addWidget(self.test_btn)
        test_layout.addWidget(self.test_status_lbl, stretch=1)
        layout.addWidget(test_container)

        # 3. Phase 4 Authorized Directories Security Card
        dir_card = QFrame()
        dir_card.setObjectName("StatusCard")
        dir_layout = QVBoxLayout(dir_card)
        dir_layout.setContentsMargins(14, 12, 14, 12)
        dir_layout.setSpacing(8)

        dir_title = QLabel("<b>Authorized Directories (Read-Only File Inspection):</b>")
        dir_sub = QLabel(
            "Files and directories outside authorized folders are strictly denied by security policy."
        )
        dir_sub.setStyleSheet("color: #8b949e; font-size: 11px;")
        dir_layout.addWidget(dir_title)
        dir_layout.addWidget(dir_sub)

        self.dir_list = QListWidget()
        self.dir_list.setFixedHeight(120)
        self.dir_list.setStyleSheet(
            "background-color: #1e1e1e; border: 1px solid #30363d; border-radius: 4px;"
        )
        dir_layout.addWidget(self.dir_list)

        dir_btn_row = QHBoxLayout()
        self.add_dir_btn = QPushButton("✚ Add Directory...")
        self.add_dir_btn.clicked.connect(self._on_add_directory)
        self.revoke_dir_btn = QPushButton("🗑 Revoke Selected")
        self.revoke_dir_btn.clicked.connect(self._on_revoke_directory)
        dir_btn_row.addWidget(self.add_dir_btn)
        dir_btn_row.addWidget(self.revoke_dir_btn)
        dir_btn_row.addStretch()
        dir_layout.addLayout(dir_btn_row)

        layout.addWidget(dir_card)
        self._refresh_authorized_dirs_list()

        # 4. Phase 6 Windows Desktop Control & Permissions Card
        win_card = QFrame()
        win_card.setObjectName("StatusCard")
        win_layout = QVBoxLayout(win_card)
        win_layout.setContentsMargins(14, 12, 14, 12)
        win_layout.setSpacing(8)

        win_title = QLabel("<b>Windows Desktop Control & Permissions / دسترسی‌های ویندوز:</b>")
        win_sub = QLabel(
            "Manage granular permissions for native desktop applications, window operations, audio, and power."
        )
        win_sub.setStyleSheet("color: #8b949e; font-size: 11px;")
        win_layout.addWidget(win_title)
        win_layout.addWidget(win_sub)

        self.win_control_chk = QCheckBox("Enable Windows Desktop Control / فعال‌سازی کنترل ویندوز")
        self.win_control_chk.setChecked(getattr(self.settings, "windows_control_enabled", True))
        win_layout.addWidget(self.win_control_chk)

        self.win_app_launch_chk = QCheckBox("Allow Application Launching / اجازه اجرای برنامه‌ها")
        self.win_app_launch_chk.setChecked(
            getattr(self.settings, "windows_app_launch_enabled", True)
        )
        win_layout.addWidget(self.win_app_launch_chk)

        self.win_app_close_chk = QCheckBox("Allow Application Closing / اجازه بستن برنامه‌ها")
        self.win_app_close_chk.setChecked(getattr(self.settings, "windows_app_close_enabled", True))
        win_layout.addWidget(self.win_app_close_chk)

        self.win_window_control_chk = QCheckBox(
            "Allow Window Controls (Focus, Minimize, Maximize) / اجازه مدیریت پنجره‌ها"
        )
        self.win_window_control_chk.setChecked(
            getattr(self.settings, "windows_window_control_enabled", True)
        )
        win_layout.addWidget(self.win_window_control_chk)

        self.win_audio_control_chk = QCheckBox("Allow Audio Controls / اجازه کنترل صدا")
        self.win_audio_control_chk.setChecked(
            getattr(self.settings, "windows_audio_control_enabled", True)
        )
        win_layout.addWidget(self.win_audio_control_chk)

        self.win_display_control_chk = QCheckBox(
            "Allow Display Brightness Controls / اجازه تنظیم روشنایی صفحه"
        )
        self.win_display_control_chk.setChecked(
            getattr(self.settings, "windows_display_control_enabled", True)
        )
        win_layout.addWidget(self.win_display_control_chk)

        self.win_power_control_chk = QCheckBox(
            "Allow Power Operations (Lock, Sleep, Restart, Shutdown) / اجازه کنترل انرژی"
        )
        self.win_power_control_chk.setChecked(
            getattr(self.settings, "windows_power_control_enabled", True)
        )
        win_layout.addWidget(self.win_power_control_chk)

        win_test_row = QHBoxLayout()
        self.audio_status_btn = QPushButton("🔊 Audio Status / وضعیت صدا")
        self.audio_status_btn.clicked.connect(self._on_check_audio_status)
        self.power_status_btn = QPushButton("🔋 Power Status / وضعیت باتری")
        self.power_status_btn.clicked.connect(self._on_check_power_status)
        self.win_list_btn = QPushButton("🪟 Windows Count / تعداد پنجره‌ها")
        self.win_list_btn.clicked.connect(self._on_check_windows_count)

        win_test_row.addWidget(self.audio_status_btn)
        win_test_row.addWidget(self.power_status_btn)
        win_test_row.addWidget(self.win_list_btn)
        win_test_row.addStretch()
        win_layout.addLayout(win_test_row)

        self.win_status_lbl = QLabel("")
        self.win_status_lbl.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: bold;")
        win_layout.addWidget(self.win_status_lbl)

        layout.addWidget(win_card)

        layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll, stretch=1)

        # Dialog Buttons
        btn_bar = QWidget()
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(0, 4, 0, 0)
        btn_layout.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._save_settings)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)
        main_layout.addWidget(btn_bar)

        # Initial populate for Gemini
        self._load_provider_fields("gemini")

    def _save_active_provider_fields(self) -> None:
        """Store current form values into in-memory dictionary for active provider."""
        pid = self._active_provider_id
        if pid in self._provider_data:
            self._provider_data[pid]["api_key"] = self.api_key_edit.text().strip()
            model_val = (
                self.model_combo.currentData()
                or self.model_combo.currentText().strip().split(" [")[0]
            )
            self._provider_data[pid]["model"] = model_val
            self._provider_data[pid]["base_url"] = self.base_url_edit.text().strip()
            self._provider_data[pid]["enabled"] = self.provider_enabled_chk.isChecked()

    def _load_provider_fields(self, provider_id: str) -> None:
        """Populate form fields with selected provider's configuration."""
        pid = provider_id.lower().strip()
        self._active_provider_id = pid
        data = self._provider_data.get(pid, {})

        # Populate key and enabled
        self.api_key_edit.setText(data.get("api_key", ""))
        self.provider_enabled_chk.setChecked(data.get("enabled", True))
        self.base_url_edit.setText(data.get("base_url", ""))

        # Populate model combo with cataloged models
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        catalog_models = ModelCatalog.list_models(pid)
        for m in catalog_models:
            label = f"{m.model_id} [Preview]" if m.is_preview else m.model_id
            self.model_combo.addItem(label, m.model_id)

        # If current model is not in catalog list (or is retired), add it cleanly
        current_model = data.get("model", "")
        if current_model:
            # Check if current_model already in combo
            found_idx = -1
            for idx in range(self.model_combo.count()):
                if (
                    self.model_combo.itemData(idx) == current_model
                    or self.model_combo.itemText(idx) == current_model
                ):
                    found_idx = idx
                    break
            if found_idx == -1:
                retired_tag = (
                    " [Retired]"
                    if ModelCatalog.is_model_retired(pid, current_model)
                    else " [Custom]"
                )
                self.model_combo.addItem(f"{current_model}{retired_tag}", current_model)
                found_idx = self.model_combo.count() - 1
            self.model_combo.setCurrentIndex(found_idx)
        else:
            default_id = ModelCatalog.get_default_model(pid)
            self.model_combo.setCurrentText(default_id)
        self.model_combo.blockSignals(False)

        # Show warning if current model is retired, tier-restricted, or deprecated
        status_warning = ModelCatalog.get_model_status_warning(pid, current_model)
        if status_warning:
            self.test_status_lbl.setText(status_warning)
            self.test_status_lbl.setStyleSheet("color: #d29922; font-weight: bold;")

        # Update labels and placeholders
        placeholders = {
            "gemini": "AIzaSy...",
            "openai": "sk-proj-...",
            "anthropic": "sk-ant-...",
            "deepseek": "sk-...",
            "openrouter": "sk-or-...",
            "groq": "gsk_...",
        }
        self.api_key_edit.setPlaceholderText(
            f"Enter {pid.capitalize()} API key ({placeholders.get(pid, 'key')})"
        )
        self.api_key_label.setText(f"<b>{pid.capitalize()} API Key:</b>")
        self.model_label.setText(f"<b>{pid.capitalize()} Model:</b>")

        # Hide base URL for Gemini / Anthropic where base URL is fixed
        has_base_url = pid in ("openai", "deepseek", "openrouter", "groq")
        self.base_url_label.setVisible(has_base_url)
        self.base_url_edit.setVisible(has_base_url)

    def _on_provider_selection_changed(self, new_provider: str) -> None:
        """Handle provider combobox switch."""
        self._save_active_provider_fields()
        self._load_provider_fields(new_provider)
        self.test_status_lbl.setText("")

    def _toggle_key_visibility(self) -> None:
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("🔒 Hide")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("👁 Show")

    def _run_connection_test(self) -> None:
        self._save_active_provider_fields()
        pid = self._active_provider_id
        data = self._provider_data[pid]
        key = data["api_key"]
        model = data["model"]

        if not key:
            self.test_status_lbl.setText(f"Please enter an API key for {pid} first.")
            self.test_status_lbl.setStyleSheet("color: #d29922; font-weight: bold;")
            return

        self.test_btn.setEnabled(False)
        self.test_status_lbl.setText(f"Testing connection to {pid} endpoint...")
        self.test_status_lbl.setStyleSheet("color: #58a6ff;")

        from pydantic import SecretStr

        # Handle mocked provider passed to dialog during unit/integration tests
        if hasattr(self.provider, "test_connection") and type(self.provider) is not GeminiProvider:
            test_provider = self.provider
        elif pid == "gemini":
            temp_settings = Settings(
                gemini_api_key=SecretStr(key),
                gemini_model=model,
                gemini_request_timeout=self.timeout_spin.value(),
            )
            test_provider = GeminiProvider(settings=temp_settings)
        else:
            # Build custom provider with temporary settings
            registry = create_default_registry()
            provider_instance = registry.get_provider(pid)
            # Update credentials on instance
            provider_instance.settings.gemini_request_timeout = self.timeout_spin.value()
            if pid == "openai":
                provider_instance.settings.openai_api_key = SecretStr(key)
                provider_instance.settings.openai_model = model
                provider_instance.settings.openai_base_url = data["base_url"] or None
                provider_instance._client = None
            elif pid == "anthropic":
                provider_instance.settings.anthropic_api_key = SecretStr(key)
                provider_instance.settings.anthropic_model = model
                provider_instance._client = None
            elif pid == "deepseek":
                provider_instance.settings.deepseek_api_key = SecretStr(key)
                provider_instance.settings.deepseek_model = model
                provider_instance.settings.deepseek_base_url = (
                    data["base_url"] or "https://api.deepseek.com"
                )
                provider_instance._client = None
            elif pid == "openrouter":
                provider_instance.settings.openrouter_api_key = SecretStr(key)
                provider_instance.settings.openrouter_model = model
                provider_instance.settings.openrouter_base_url = (
                    data["base_url"] or "https://openrouter.ai/api/v1"
                )
                provider_instance._client = None
            elif pid == "groq":
                provider_instance.settings.groq_api_key = SecretStr(key)
                provider_instance.settings.groq_model = model
                provider_instance.settings.groq_base_url = (
                    data["base_url"] or "https://api.groq.com/openai/v1"
                )
                provider_instance._client = None
            test_provider = provider_instance

        self._test_worker = ConnectionTestWorker(provider=test_provider, parent=self)
        self._test_worker.test_completed.connect(self._on_test_completed)
        self._test_worker.start()

    def _on_test_completed(self, result: ConnectionTestResult) -> None:
        self.test_btn.setEnabled(True)
        if result.is_success:
            latency_str = f" ({result.latency_ms} ms)" if result.latency_ms else ""
            self.test_status_lbl.setText(f"✓ {result.message}{latency_str}")
            self.test_status_lbl.setStyleSheet("color: #3fb950; font-weight: bold;")
        else:
            self.test_status_lbl.setText(f"✗ {result.message}")
            self.test_status_lbl.setStyleSheet("color: #f85149; font-weight: bold;")

    def _refresh_authorized_dirs_list(self) -> None:
        self.dir_list.clear()
        sec = get_path_security_service()
        for d in sec.list_authorized_directories():
            item = QListWidgetItem(f"📁 {d.display_name} — {d.path}")
            item.setData(Qt.ItemDataRole.UserRole, d.directory_id)
            self.dir_list.addItem(item)

    def _on_add_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Authorize Directory for Read-Only Inspection"
        )
        if chosen:
            try:
                sec = get_path_security_service()
                sec.add_directory(chosen)
                self._refresh_authorized_dirs_list()
            except Exception as exc:
                QMessageBox.warning(self, "Authorization Error", str(exc))

    def _on_revoke_directory(self) -> None:
        item = self.dir_list.currentItem()
        if not item:
            return
        dir_id = item.data(Qt.ItemDataRole.UserRole)
        if dir_id:
            sec = get_path_security_service()
            sec.revoke_directory(dir_id)
            self._refresh_authorized_dirs_list()

    def _on_check_audio_status(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            status = svc.get_audio_status()
            muted_str = "Muted" if status.is_muted else "Unmuted"
            self.win_status_lbl.setText(f"🔊 Master Volume: {status.volume_percent}% ({muted_str})")
        except Exception as exc:
            self.win_status_lbl.setText(f"Audio inspection failed: {exc}")

    def _on_check_power_status(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            status = svc.get_power_status()
            self.win_status_lbl.setText(
                f"🔋 Battery: {status.battery_percent}% (AC: {status.ac_line_status}, State: {status.battery_status})"
            )
        except Exception as exc:
            self.win_status_lbl.setText(f"Power inspection failed: {exc}")

    def _on_check_windows_count(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            wins = svc.list_windows()
            self.win_status_lbl.setText(f"🪟 Active Desktop Windows: {len(wins)} detected")
        except Exception as exc:
            self.win_status_lbl.setText(f"Window enumeration failed: {exc}")

    def _on_check_audio_status(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            status = svc.get_audio_status()
            muted_str = "Muted" if status.is_muted else "Unmuted"
            self.win_status_lbl.setText(f"🔊 Master Volume: {status.volume_percent}% ({muted_str})")
        except Exception as exc:
            self.win_status_lbl.setText(f"Audio inspection failed: {exc}")

    def _on_check_power_status(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            status = svc.get_power_status()
            self.win_status_lbl.setText(
                f"🔋 Battery: {status.battery_percent}% (AC: {status.ac_line_status}, State: {status.battery_status})"
            )
        except Exception as exc:
            self.win_status_lbl.setText(f"Power inspection failed: {exc}")

    def _on_check_windows_count(self) -> None:
        try:
            from tools.windows.windows_service import WindowsControlService

            svc = WindowsControlService(settings=self.settings)
            wins = svc.list_windows()
            self.win_status_lbl.setText(f"🪟 Active Desktop Windows: {len(wins)} detected")
        except Exception as exc:
            self.win_status_lbl.setText(f"Window enumeration failed: {exc}")

    def _save_settings(self) -> None:
        self._save_active_provider_fields()

        # Defect prevention: ensure empty API key inputs do NOT accidentally wipe existing saved keys
        provider_secret_keys = {
            "gemini": self.settings.gemini_api_key,
            "openai": self.settings.openai_api_key,
            "anthropic": self.settings.anthropic_api_key,
            "deepseek": self.settings.deepseek_api_key,
            "openrouter": self.settings.openrouter_api_key,
            "groq": self.settings.groq_api_key,
        }

        for pid, secret_val in provider_secret_keys.items():
            current_input_key = self._provider_data[pid]["api_key"]
            if not current_input_key and secret_val:
                # User left key field blank; preserve the already saved credential
                self._provider_data[pid]["api_key"] = secret_val.get_secret_value()

        updates = {
            # Global routing & privacy controls
            "DEFAULT_PROVIDER": self.default_provider_combo.currentText(),
            "ENABLE_AUTO_FALLBACK": "true" if self.auto_fallback_chk.isChecked() else "false",
            "ALLOW_INTRA_PROVIDER_FALLBACK": (
                "true" if self.intra_provider_fallback_chk.isChecked() else "false"
            ),
            "ALLOW_CROSS_PROVIDER_FALLBACK": (
                "true" if self.cross_provider_fallback_chk.isChecked() else "false"
            ),
            "ALLOW_CROSS_PROVIDER_PROMPT_TRANSFER": (
                "true" if self.cross_provider_prompt_chk.isChecked() else "false"
            ),
            "ALLOW_CROSS_PROVIDER_HISTORY_TRANSFER": (
                "true" if self.cross_provider_history_chk.isChecked() else "false"
            ),
            # Common Generation Params
            "GEMINI_TEMPERATURE": str(self.temp_spin.value()),
            "GEMINI_MAX_OUTPUT_TOKENS": str(self.tokens_spin.value()),
            "GEMINI_REQUEST_TIMEOUT": str(self.timeout_spin.value()),
            # Gemini
            "GEMINI_API_KEY": self._provider_data["gemini"]["api_key"],
            "GEMINI_MODEL": self._provider_data["gemini"]["model"],
            "GEMINI_ENABLED": "true" if self._provider_data["gemini"]["enabled"] else "false",
            # OpenAI
            "OPENAI_API_KEY": self._provider_data["openai"]["api_key"],
            "OPENAI_MODEL": self._provider_data["openai"]["model"],
            "OPENAI_BASE_URL": self._provider_data["openai"]["base_url"],
            "OPENAI_ENABLED": "true" if self._provider_data["openai"]["enabled"] else "false",
            # Anthropic
            "ANTHROPIC_API_KEY": self._provider_data["anthropic"]["api_key"],
            "ANTHROPIC_MODEL": self._provider_data["anthropic"]["model"],
            "ANTHROPIC_ENABLED": "true" if self._provider_data["anthropic"]["enabled"] else "false",
            # DeepSeek
            "DEEPSEEK_API_KEY": self._provider_data["deepseek"]["api_key"],
            "DEEPSEEK_MODEL": self._provider_data["deepseek"]["model"],
            "DEEPSEEK_BASE_URL": self._provider_data["deepseek"]["base_url"],
            "DEEPSEEK_ENABLED": "true" if self._provider_data["deepseek"]["enabled"] else "false",
            # OpenRouter
            "OPENROUTER_API_KEY": self._provider_data["openrouter"]["api_key"],
            "OPENROUTER_MODEL": self._provider_data["openrouter"]["model"],
            "OPENROUTER_BASE_URL": self._provider_data["openrouter"]["base_url"],
            "OPENROUTER_ENABLED": "true"
            if self._provider_data["openrouter"]["enabled"]
            else "false",
            # Groq
            "GROQ_API_KEY": self._provider_data["groq"]["api_key"],
            "GROQ_MODEL": self._provider_data["groq"]["model"],
            "GROQ_BASE_URL": self._provider_data["groq"]["base_url"],
            "GROQ_ENABLED": "true" if self._provider_data["groq"]["enabled"] else "false",
            # Phase 6 Windows Controls
            "WINDOWS_CONTROL_ENABLED": "true" if self.win_control_chk.isChecked() else "false",
            "WINDOWS_APP_LAUNCH_ENABLED": (
                "true" if self.win_app_launch_chk.isChecked() else "false"
            ),
            "WINDOWS_APP_CLOSE_ENABLED": "true" if self.win_app_close_chk.isChecked() else "false",
            "WINDOWS_WINDOW_CONTROL_ENABLED": (
                "true" if self.win_window_control_chk.isChecked() else "false"
            ),
            "WINDOWS_AUDIO_CONTROL_ENABLED": (
                "true" if self.win_audio_control_chk.isChecked() else "false"
            ),
            "WINDOWS_DISPLAY_CONTROL_ENABLED": (
                "true" if self.win_display_control_chk.isChecked() else "false"
            ),
            "WINDOWS_POWER_CONTROL_ENABLED": (
                "true" if self.win_power_control_chk.isChecked() else "false"
            ),
        }

        try:
            save_env_settings(updates)
            QMessageBox.information(
                self,
                "Settings Saved",
                "Multi-Provider configuration updated successfully in .env.",
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to update settings file: {exc}",
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Safely terminate any pending connection test thread."""
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.wait(1000)
        event.accept()


class MainWindow(QMainWindow):
    """JARVIS Main Desktop Application Window."""

    def __init__(
        self,
        agent: JARVISAgent | None = None,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or get_settings()
        self.agent = agent or JARVISAgent(settings=self.settings)

        self._stream_worker: GeminiStreamWorker | None = None
        self._agent_worker: AgentExecutionWorker | None = None
        self._pending_assistant_msg_id: str | None = None
        self._pending_prompt_text: str | None = None
        self._active_stream_text: str = ""

        self.setWindowTitle(f"{self.settings.app_name} — Personal AI Assistant")
        self.resize(1080, 750)
        self.setMinimumSize(850, 580)

        self.setStyleSheet(DARK_THEME_QSS)
        self._init_ui()
        self._wire_agent_events()

        # Display initial welcome message
        QTimer.singleShot(100, self._show_welcome_message)

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_vbox = QVBoxLayout(central_widget)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # 1. Header Bar
        header = QFrame()
        header.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)

        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        app_title = QLabel(self.settings.app_name)
        app_title.setObjectName("AppTitle")
        app_subtitle = QLabel("Personal AI Agent — Phase 2 Multi-Provider Edition")
        app_subtitle.setObjectName("AppSubtitle")

        title_layout.addWidget(app_title)
        title_layout.addWidget(app_subtitle)
        header_layout.addWidget(title_container)

        header_layout.addStretch()

        # Action Buttons in Header
        self.new_chat_btn = QPushButton("✚ New Chat")
        self.new_chat_btn.clicked.connect(self._handle_new_chat)
        header_layout.addWidget(self.new_chat_btn)

        self.clear_chat_btn = QPushButton("🗑 Clear")
        self.clear_chat_btn.clicked.connect(self._handle_clear_chat)
        header_layout.addWidget(self.clear_chat_btn)

        self.memory_btn = QPushButton("🧠 Memory")
        self.memory_btn.clicked.connect(self._open_memory_dialog)
        header_layout.addWidget(self.memory_btn)

        self.coding_agent_btn = QPushButton("💻 Coding Agent")
        self.coding_agent_btn.clicked.connect(self._open_coding_agent_dialog)
        header_layout.addWidget(self.coding_agent_btn)

        self.settings_btn = QPushButton("⚙ Settings")
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        header_layout.addWidget(self.settings_btn)

        main_vbox.addWidget(header)

        # 2. Main Body Splitter (Chat Panel on left/center, Status Panel on right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        self.chat_panel = ChatPanel()
        self.chat_panel.message_submitted.connect(self._handle_user_message)
        self.chat_panel.cancellation_requested.connect(self._handle_cancellation)
        self.chat_panel.retry_requested.connect(self._handle_retry)
        self.chat_panel.new_chat_requested.connect(self._handle_new_chat)
        self.chat_panel.clear_chat_requested.connect(self._handle_clear_chat)
        self.chat_panel.approval_decided.connect(self._handle_approval_decision)
        splitter.addWidget(self.chat_panel)

        self.status_panel = StatusPanel()
        splitter.addWidget(self.status_panel)

        # Give chat panel 75% of space, status panel 25%
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        main_vbox.addWidget(splitter)
        self._refresh_status_panel()

    def _show_welcome_message(self) -> None:
        """Present initial welcome banner with configuration guidance."""
        provider_name = getattr(self.agent.ai_provider, "provider_name", "AI Provider")
        active_model = getattr(self.agent.ai_provider, "default_model", self.settings.gemini_model)

        welcome_text = (
            f"**Welcome to {self.settings.app_name}!**\n\n"
            f"Active Provider: **{provider_name}** | Model: `{active_model}`\n\n"
            "Supported providers: **Google Gemini**, **OpenAI**, **Anthropic Claude**, "
            "**DeepSeek**, **OpenRouter**, and **Groq**.\n\n"
            "You can type your message below to start chatting, or open **⚙ Settings** to configure your API keys and models."
        )
        self.chat_panel.add_message("JARVIS", welcome_text, is_user=False)

    def _wire_agent_events(self) -> None:
        """Subscribe to EventBus events to keep UI synchronized."""
        self.agent.event_bus.subscribe(
            AgentEventType.AGENT_STATUS_CHANGED,
            self._on_agent_status_changed_event,
        )
        self.agent.event_bus.subscribe(
            AgentEventType.APPROVAL_REQUIRED,
            self._on_approval_required_event,
        )
        if hasattr(self.agent.ai_provider, "add_failover_listener"):
            self.agent.ai_provider.add_failover_listener(self._on_failover_event)

    def _on_failover_event(self, event: dict[str, Any]) -> None:
        """Handle model/provider failover notifications and reflect status in UI."""
        event_type = event.get("event")
        if event_type == "failover_attempt":
            orig = event.get("original_model", "")
            target = event.get("target_model", "")
            self.status_panel.set_ai_status(
                model=f"{target} (Failover)",
                status_text=f"Failover: {orig} unavailable -> switching to {target}...",
                is_ready=True,
            )
        elif event_type == "failover_success":
            actual_model = event.get("actual_model", "")
            actual_provider = event.get("actual_provider", "")
            self.status_panel.set_ai_status(
                model=f"{actual_model} ({actual_provider})",
                status_text="Response generated via failover model",
                is_ready=True,
            )
        elif event_type == "failover_exhausted":
            reason = event.get("reason", "All models failed")
            self.status_panel.set_ai_status(
                model="Failover Exhausted",
                status_text=reason,
                is_ready=False,
            )

    def _on_approval_required_event(self, event: AgentEvent) -> None:
        """Display an interactive approval card in chat when a high-risk tool is proposed."""
        payload = event.payload
        self.chat_panel.add_approval_card(
            proposal_id=payload.get("proposal_id", ""),
            tool_name=payload.get("tool_name", "Unknown Tool"),
            arguments=payload.get("arguments", {}),
            risk_level=payload.get("risk_level", "HIGH"),
            rationale=payload.get("rationale", ""),
            session_id=payload.get("session_id", self.agent.active_session_id),
        )

    def _handle_approval_decision(self, proposal_id: str, approved: bool, session_id: str) -> None:
        """Forward user's approval or rejection decision to the agent core."""
        logger.info(
            f"User decision on proposal {proposal_id}: {'Approved' if approved else 'Rejected'} (Session: {session_id})"
        )
        self.agent.submit_approval_decision(
            proposal_id=proposal_id,
            approved=approved,
            session_id=session_id,
        )

    def _refresh_status_panel(self) -> None:
        """Update system and provider readiness display."""
        provider_name = getattr(self.agent.ai_provider, "provider_name", "AI Provider")
        if not isinstance(provider_name, str):
            provider_name = "AI Provider"

        active_model = getattr(self.agent.ai_provider, "default_model", self.settings.gemini_model)
        if not isinstance(active_model, str):
            active_model = self.settings.gemini_model

        is_ready = bool(self.agent.ai_provider.is_ready())

        status_text = f"Connected ({provider_name})" if is_ready else "Not Configured"
        self.status_panel.set_ai_status(
            model=f"{active_model} ({provider_name})",
            status_text=status_text,
            is_ready=is_ready,
        )

    def _on_agent_status_changed_event(self, event: AgentEvent) -> None:
        """Handle agent state changes arriving via EventBus."""
        new_state = event.payload.get("new_state", "idle")
        color_map = {
            "idle": "#3fb950",
            "busy": "#d29922",
            "error": "#f85149",
            "shutdown": "#8b949e",
            "initializing": "#58a6ff",
        }
        color = color_map.get(new_state, "#8b949e")
        self.status_panel.set_agent_status(new_state, color_hex=color)

    def _handle_user_message(self, text: str, is_retry: bool = False) -> None:
        """Handle user input submitted via the chat panel."""
        if not text.strip():
            return

        # Guard against overlapping requests
        if (self._stream_worker and self._stream_worker.isRunning()) or (
            self._agent_worker and self._agent_worker.isRunning()
        ):
            logger.warning("Generation request already running; ignoring overlapping submission.")
            return

        self._pending_prompt_text = text
        logger.info(f"User message: {text[:40]}...")

        if not is_retry:
            self.chat_panel.add_message("User", text, is_user=True)

        # Check API key readiness
        if not self.agent.ai_provider.is_ready():
            notice = (
                "AI Provider is not configured. Please open **⚙ System Settings** "
                "to enter your API key before sending requests."
            )
            self.chat_panel.add_message("JARVIS", notice, is_user=False, is_error=True)
            return

        # Record user message in memory database only if not retrying
        if not is_retry:
            self.agent.record_user_message(text=text)

        # Retrieve prior conversation history
        history = self.agent.get_session_history()
        prior_history = history[:-1] if history else []

        active_model = getattr(self.agent.ai_provider, "default_model", self.settings.gemini_model)
        if not isinstance(active_model, str):
            active_model = self.settings.gemini_model

        provider_name = getattr(self.agent.ai_provider, "provider_name", "AI")
        if not isinstance(provider_name, str):
            provider_name = "AI"

        # Start assistant streaming bubble
        self.chat_panel.start_assistant_streaming(sender="JARVIS")
        self.agent.set_state(AgentState.BUSY, reason=f"Streaming {provider_name} response")
        self.status_panel.set_ai_status(
            model=active_model,
            status_text="Generating response...",
            is_ready=True,
        )

        # Pre-record assistant message with STREAMING status
        self._pending_assistant_msg_id = self.agent.record_assistant_message(
            text="",
            status=MessageStatus.STREAMING,
            model=active_model,
            provider_id=provider_name,
        )

        # Phase 5: Extract candidates and retrieve relevant memory context
        effective_prompt = text
        if self.settings.memory_enabled:
            if not is_retry:
                try:
                    self.agent.extract_memory_candidates(text=text)
                except Exception as exc:
                    logger.debug(f"Memory extraction skipped: {exc}")
            try:
                mem_ctx = self.agent.build_memory_context(query=text)
                if mem_ctx:
                    effective_prompt = f"{mem_ctx}\n\n{text}"
            except Exception as exc:
                logger.warning(f"Memory retrieval encountered safe error: {exc}")

        # Determine execution path: Multi-step / Tool Planning vs Conversational Stream
        needs_plan = self.agent.planner.should_plan(text)
        if needs_plan:
            self._agent_worker = AgentExecutionWorker(
                agent=self.agent,
                goal=effective_prompt,
                session_id=self.agent.active_session_id,
                parent=self,
            )
            self._agent_worker.step_started.connect(self._on_agent_step_started)
            self._agent_worker.task_finished.connect(self._on_agent_task_finished)
            self._agent_worker.task_error.connect(self._on_agent_task_error)
            self._agent_worker.task_cancelled.connect(self._on_agent_task_cancelled)
            self._agent_worker.start()
        else:
            # Launch background conversational stream worker
            self._stream_worker = GeminiStreamWorker(
                provider=self.agent.ai_provider,
                prompt=effective_prompt,
                session_id=self.agent.active_session_id,
                history=prior_history,
                parent=self,
            )
            self._stream_worker.chunk_received.connect(self._on_stream_chunk)
            self._stream_worker.generation_finished.connect(self._on_stream_finished)
            self._stream_worker.generation_error.connect(self._on_stream_error)
            self._stream_worker.generation_cancelled.connect(self._on_stream_cancelled)
            self._stream_worker.start()

    def _on_agent_step_started(self, step_id: str, description: str, session_id: str) -> None:
        """Update status panel when an autonomous plan step starts."""
        if session_id != self.agent.active_session_id:
            return
        active_model = getattr(self.agent.ai_provider, "default_model", self.settings.gemini_model)
        self.status_panel.set_ai_status(
            model=active_model,
            status_text=f"Executing: {description}...",
            is_ready=True,
        )

    def _on_agent_task_finished(self, outcome: Any, session_id: str) -> None:
        """Finalize agent task output and display verified result in chat."""
        if session_id != self.agent.active_session_id:
            return

        final_text = (
            getattr(outcome, "final_response", "")
            or getattr(outcome, "error", "")
            or "Task completed."
        )
        self.chat_panel.finish_assistant_streaming(final_text)

        if self._pending_assistant_msg_id:
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text=final_text,
                status=(
                    MessageStatus.COMPLETED
                    if getattr(outcome, "status", "") == "completed"
                    else MessageStatus.FAILED
                ),
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None

        self.agent.set_state(AgentState.IDLE, reason="Task execution complete")
        self._refresh_status_panel()

    def _on_agent_task_error(self, error_message: str, session_id: str) -> None:
        """Handle execution error during autonomous agent task."""
        if session_id != self.agent.active_session_id:
            return

        self.chat_panel.finish_assistant_streaming(f"Task error: {error_message}")
        if self._pending_assistant_msg_id:
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text=f"Task error: {error_message}",
                status=MessageStatus.FAILED,
                interruption_reason=error_message,
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None

        self.agent.set_state(AgentState.ERROR, reason=error_message)
        self._refresh_status_panel()

    def _on_agent_task_cancelled(self, session_id: str) -> None:
        """Handle cancellation of autonomous agent task."""
        if session_id != self.agent.active_session_id:
            return

        self.chat_panel.finish_assistant_streaming("Task cancelled by user.")
        if self._pending_assistant_msg_id:
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text="Task cancelled by user.",
                status=MessageStatus.CANCELLED,
                interruption_reason="Cancelled by user",
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None

        self.agent.set_state(AgentState.IDLE, reason="Task cancelled")
        self._refresh_status_panel()

    def _on_stream_chunk(self, chunk: str, session_id: str) -> None:
        """Incrementally append chunk to chat bubble if belonging to active session."""
        if session_id != self.agent.active_session_id:
            logger.debug(f"Discarding chunk for inactive session: {session_id}")
            return

        self._active_stream_text += chunk
        self.chat_panel.append_streaming_chunk(chunk)

    def _on_stream_finished(self, final_text: str, session_id: str) -> None:
        """Finalize streamed response and persist complete message to database."""
        if session_id != self.agent.active_session_id:
            logger.debug(f"Discarding finished stream for inactive session: {session_id}")
            return

        self.chat_panel.finish_assistant_streaming(final_text)

        if self._pending_assistant_msg_id:
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text=final_text,
                status=MessageStatus.COMPLETED,
                provider_id=getattr(self.agent.ai_provider, "provider_name", "AI"),
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None
        self._active_stream_text = ""

        self.agent.set_state(AgentState.IDLE, reason="Streaming complete")
        self._refresh_status_panel()

    def _on_stream_error(self, error_message: str, session_id: str) -> None:
        """Handle streaming failure gracefully."""
        if session_id != self.agent.active_session_id:
            return

        logger.error(f"Stream failed for session {session_id}: {error_message}")
        self.chat_panel.fail_assistant_streaming(error_message)

        if self._pending_assistant_msg_id:
            # Preserve the actual partial text content exactly as received without embedding operational tags in content
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text=self._active_stream_text,
                status=MessageStatus.FAILED,
                interruption_reason=error_message,
                provider_id=getattr(self.agent.ai_provider, "provider_name", "AI"),
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None
        self._active_stream_text = ""

        self.agent.set_state(AgentState.ERROR, reason=error_message)
        self._refresh_status_panel()

    def _on_stream_cancelled(self, session_id: str) -> None:
        """Handle user-initiated stream cancellation."""
        if session_id != self.agent.active_session_id:
            return

        logger.info(f"Stream cancelled for session {session_id}")
        self.chat_panel.cancel_assistant_streaming()

        if self._pending_assistant_msg_id:
            # Preserve actual partial text exactly as received, recording cancellation in status/reason
            self.agent.update_assistant_message(
                message_id=self._pending_assistant_msg_id,
                text=self._active_stream_text,
                status=MessageStatus.CANCELLED,
                interruption_reason="Cancelled by user",
                provider_id=getattr(self.agent.ai_provider, "provider_name", "AI"),
                model_id=getattr(
                    self.agent.ai_provider, "default_model", self.settings.gemini_model
                ),
            )
            self._pending_assistant_msg_id = None
        self._active_stream_text = ""

        self.agent.set_state(AgentState.IDLE, reason="Streaming cancelled")
        self._refresh_status_panel()

    def _handle_cancellation(self) -> None:
        """Cancel the active streaming worker or agent task and update UI immediately."""
        if self._stream_worker and self._stream_worker.isRunning():
            logger.info("User requested generation abort.")
            self._stream_worker.cancel()
        if hasattr(self, "_agent_worker") and self._agent_worker and self._agent_worker.isRunning():
            logger.info("User requested agent task abort.")
            self._agent_worker.cancel()
        # Ensure chat panel immediately exits generating state so button reverts to Send
        self.chat_panel.cancel_assistant_streaming()
        self.agent.set_state(AgentState.IDLE, reason="Streaming cancelled")
        self._refresh_status_panel()

    def _handle_new_chat(self) -> None:
        """Start a fresh conversation session."""
        self._handle_cancellation()
        new_id = self.agent.create_new_session()
        self.chat_panel.clear_messages()
        self.chat_panel.add_message(
            "JARVIS",
            f"Started new conversation session ({new_id[:8]}...). How may I help you?",
            is_user=False,
        )

    def _handle_clear_chat(self) -> None:
        """Clear current conversation messages upon confirmation."""
        reply = QMessageBox.question(
            self,
            "Clear Conversation",
            "Are you sure you want to clear all messages in this conversation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._handle_cancellation()
            self.agent.clear_active_session()
            self.chat_panel.clear_messages()
            self.chat_panel.add_message(
                "JARVIS",
                "Conversation history cleared.",
                is_user=False,
            )

    def _handle_retry(self, failed_text: str) -> None:
        """Retry sending the last user message without creating duplicate user messages."""
        if self._pending_prompt_text:
            self._handle_user_message(self._pending_prompt_text, is_retry=True)

    def _open_settings_dialog(self) -> None:
        """Open the multi-provider settings configuration modal."""
        dialog = SettingsDialog(
            settings=self.settings,
            provider=self.agent.ai_provider,
            parent=self,
        )
        if dialog.exec():
            # Refresh settings
            self.settings = get_settings()
            self.agent.settings = self.settings
            if hasattr(self.agent.ai_provider, "settings"):
                self.agent.ai_provider.settings = self.settings
            if hasattr(self.agent.ai_provider, "close"):
                self.agent.ai_provider.close()
            elif hasattr(self.agent.ai_provider, "_client"):
                self.agent.ai_provider._client = None
            self._refresh_status_panel()

    def _open_memory_dialog(self) -> None:
        """Open the Phase 5 Persistent Memory Management Dialog."""
        dialog = MemoryManagementDialog(
            memory_manager=self.agent.memory_manager,
            parent=self,
        )
        dialog.exec()

    def _open_coding_agent_dialog(self) -> None:
        """Open the Phase 8 Antigravity Coding Agent Dialog."""
        dialog = CodingAgentDialog(parent=self)
        dialog.exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle clean window close, signal disconnection, and worker termination."""
        logger.info("Main window closing, disconnecting and shutting down workers...")
        if self._stream_worker and self._stream_worker.isRunning():
            try:
                self._stream_worker.chunk_received.disconnect()
                self._stream_worker.generation_finished.disconnect()
                self._stream_worker.generation_error.disconnect()
                self._stream_worker.generation_cancelled.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._stream_worker.cancel()
            self._stream_worker.wait(1500)

        try:
            self.agent.shutdown()
        except Exception as exc:
            logger.warning(f"Error during agent shutdown: {exc}")
        event.accept()
