"""Communication Accounts Management Dialog for JARVIS Phase 9.

Provides connection interfaces for Gmail OAuth, Microsoft Graph OAuth,
and Meta WhatsApp Business Cloud API with encrypted Windows DPAPI credential storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import get_settings
from infrastructure.communication_db import get_communication_db
from infrastructure.credential_store import get_credential_store
from tools.communication.email import get_email_service
from tools.communication.whatsapp import get_whatsapp_service
from tools.voice.device_manager import AudioDeviceManager
from tools.voice.tts_service import BritishNeuralTTSService, create_tts_service

if TYPE_CHECKING:
    pass


class CommunicationDialog(QDialog):
    """Configuration dialog for Gmail, Microsoft Graph, and WhatsApp Cloud API accounts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = get_settings()
        self.credential_store = get_credential_store()
        self.email_service = get_email_service()
        self.whatsapp_service = get_whatsapp_service()
        self.comm_db = get_communication_db()
        self.tts_service = create_tts_service()

        self.setWindowTitle("JARVIS — Communication Accounts & Messaging Settings")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setMinimumSize(560, 420)
        self.resize(680, 700)
        self._init_ui()
        self._load_current_status()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Scroll area for responsive, arbitrary window resizing
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(14)

        # Header description
        desc_lbl = QLabel(
            "Configure authenticated email and WhatsApp messaging accounts.\n"
            "All tokens and secrets are encrypted with Windows DPAPI and never logged or leaked."
        )
        desc_lbl.setStyleSheet("color: #deddda; font-size: 12px; margin-bottom: 6px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # 1. Google Gmail (OAuth 2.0 REST API)
        gmail_group = QGroupBox("Google Gmail (Official REST API)")
        gmail_group.setStyleSheet("QGroupBox { font-weight: bold; color: #f6d32d; }")
        gmail_layout = QVBoxLayout(gmail_group)

        self.gmail_status_lbl = QLabel("Status: Checking...")
        self.gmail_status_lbl.setStyleSheet("color: #9a9996;")
        gmail_layout.addWidget(self.gmail_status_lbl)

        gmail_form = QFormLayout()
        self.gmail_token_input = QLineEdit()
        self.gmail_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gmail_token_input.setPlaceholderText("Paste OAuth Access Token (or refresh token)")
        gmail_form.addRow("OAuth Token:", self.gmail_token_input)
        gmail_layout.addLayout(gmail_form)

        gmail_btn_row = QHBoxLayout()
        self.gmail_save_btn = QPushButton("Save Token")
        self.gmail_save_btn.clicked.connect(self._save_gmail_token)
        self.gmail_disconnect_btn = QPushButton("Disconnect")
        self.gmail_disconnect_btn.clicked.connect(self._disconnect_gmail)
        gmail_btn_row.addWidget(self.gmail_save_btn)
        gmail_btn_row.addWidget(self.gmail_disconnect_btn)
        gmail_btn_row.addStretch()
        gmail_layout.addLayout(gmail_btn_row)

        layout.addWidget(gmail_group)

        # 2. Microsoft Outlook / Graph API
        msgraph_group = QGroupBox("Microsoft Outlook / Graph API (Mail.Send)")
        msgraph_group.setStyleSheet("QGroupBox { font-weight: bold; color: #3584e4; }")
        msgraph_layout = QVBoxLayout(msgraph_group)

        self.msgraph_status_lbl = QLabel("Status: Checking...")
        self.msgraph_status_lbl.setStyleSheet("color: #9a9996;")
        msgraph_layout.addWidget(self.msgraph_status_lbl)

        msgraph_form = QFormLayout()
        self.msgraph_token_input = QLineEdit()
        self.msgraph_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.msgraph_token_input.setPlaceholderText("Paste Microsoft Graph Access Token")
        msgraph_form.addRow("Graph Token:", self.msgraph_token_input)
        msgraph_layout.addLayout(msgraph_form)

        msgraph_btn_row = QHBoxLayout()
        self.msgraph_save_btn = QPushButton("Save Token")
        self.msgraph_save_btn.clicked.connect(self._save_msgraph_token)
        self.msgraph_disconnect_btn = QPushButton("Disconnect")
        self.msgraph_disconnect_btn.clicked.connect(self._disconnect_msgraph)
        msgraph_btn_row.addWidget(self.msgraph_save_btn)
        msgraph_btn_row.addWidget(self.msgraph_disconnect_btn)
        msgraph_btn_row.addStretch()
        msgraph_layout.addLayout(msgraph_btn_row)

        layout.addWidget(msgraph_group)

        # 3. Meta WhatsApp Business Cloud API
        wa_group = QGroupBox("Meta WhatsApp Cloud API (Official Business Platform)")
        wa_group.setStyleSheet("QGroupBox { font-weight: bold; color: #26a269; }")
        wa_layout = QVBoxLayout(wa_group)

        self.wa_status_lbl = QLabel("Status: Checking...")
        self.wa_status_lbl.setStyleSheet("color: #9a9996;")
        wa_layout.addWidget(self.wa_status_lbl)

        wa_form = QFormLayout()
        self.wa_phone_id_input = QLineEdit()
        self.wa_phone_id_input.setPlaceholderText("e.g. 10482910492810")
        wa_form.addRow("Phone Number ID:", self.wa_phone_id_input)

        self.wa_token_input = QLineEdit()
        self.wa_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.wa_token_input.setPlaceholderText("Meta System User Access Token")
        wa_form.addRow("Access Token:", self.wa_token_input)

        self.wa_self_phone_input = QLineEdit()
        self.wa_self_phone_input.setPlaceholderText(
            "Your personal phone for 'خودم' (e.g. +989123456789)"
        )
        wa_form.addRow("Self Phone Number:", self.wa_self_phone_input)

        wa_layout.addLayout(wa_form)

        wa_btn_row = QHBoxLayout()
        self.wa_save_btn = QPushButton("Save WhatsApp Config")
        self.wa_save_btn.clicked.connect(self._save_whatsapp_config)
        self.wa_disconnect_btn = QPushButton("Disconnect")
        self.wa_disconnect_btn.clicked.connect(self._disconnect_whatsapp)
        wa_btn_row.addWidget(self.wa_save_btn)
        wa_btn_row.addWidget(self.wa_disconnect_btn)
        wa_btn_row.addStretch()
        wa_layout.addLayout(wa_btn_row)

        # WhatsApp Recipient Consent & Compliance
        wa_consent_lbl = QLabel("Recipient Consent Management (Meta Compliance):")
        wa_consent_lbl.setStyleSheet("color: #deddda; font-size: 11px; margin-top: 6px;")
        wa_layout.addWidget(wa_consent_lbl)

        wa_consent_row = QHBoxLayout()
        self.wa_consent_phone_input = QLineEdit()
        self.wa_consent_phone_input.setPlaceholderText("Recipient Phone (e.g. +989123456789)")
        self.wa_consent_optin_btn = QPushButton("Grant Opt-In")
        self.wa_consent_optin_btn.clicked.connect(self._grant_recipient_consent)
        self.wa_consent_optout_btn = QPushButton("Revoke / Opt-Out")
        self.wa_consent_optout_btn.clicked.connect(self._revoke_recipient_consent)
        wa_consent_row.addWidget(self.wa_consent_phone_input)
        wa_consent_row.addWidget(self.wa_consent_optin_btn)
        wa_consent_row.addWidget(self.wa_consent_optout_btn)
        wa_layout.addLayout(wa_consent_row)

        layout.addWidget(wa_group)

        # 4. Speech, British Voice Identity & Cloud Privacy
        voice_group = QGroupBox("JARVIS Voice Identity & Audio Privacy Controls")
        voice_group.setStyleSheet("QGroupBox { font-weight: bold; color: #3584e4; }")
        voice_layout = QVBoxLayout(voice_group)

        # British Neural Voice Identity controls
        voice_form = QFormLayout()

        self.device_manager = AudioDeviceManager()
        self.voice_mic_combo = QComboBox()
        for dev in self.device_manager.list_input_devices():
            self.voice_mic_combo.addItem(dev.name, dev.id)
        voice_form.addRow("Microphone / ورودی صدا:", self.voice_mic_combo)

        self.voice_engine_combo = QComboBox()
        self.voice_engine_combo.addItem("sapi", "sapi")
        self.voice_engine_combo.addItem("azure_neural (British Neural)", "azure_neural")
        self.voice_engine_combo.addItem(
            "openai_speech (Deprecated / Shutdown Jan 2027)", "openai_speech"
        )
        self.voice_engine_combo.addItem("winrt", "winrt")
        self.voice_engine_combo.addItem("mock", "mock")
        voice_form.addRow("Speech Engine:", self.voice_engine_combo)

        self.voice_name_combo = QComboBox()
        self.voice_name_combo.addItems(
            [
                "en-GB-OliverNeural",
                "en-GB-Ryan:DragonHDLatestNeural",
                "en-GB-RyanNeural",
                "fable",
                "onyx",
                "Microsoft David",
                "Microsoft Mark",
            ]
        )
        voice_form.addRow("Voice Model:", self.voice_name_combo)

        self.voice_resp_lang_combo = QComboBox()
        self.voice_resp_lang_combo.addItems(["en", "fa", "match"])
        voice_form.addRow("Spoken Response Language:", self.voice_resp_lang_combo)

        voice_layout.addLayout(voice_form)

        voice_btn_row = QHBoxLayout()
        self.voice_preview_btn = QPushButton("Preview Voice Identity")
        self.voice_preview_btn.clicked.connect(self._preview_voice)
        self.voice_save_btn = QPushButton("Save Voice Identity")
        self.voice_save_btn.clicked.connect(self._save_voice_settings)
        voice_btn_row.addWidget(self.voice_preview_btn)
        voice_btn_row.addWidget(self.voice_save_btn)
        voice_btn_row.addStretch()
        voice_layout.addLayout(voice_btn_row)

        self.stt_consent_checkbox = QCheckBox(
            "Enable Cloud Speech-to-Text (Google Gemini Multimodal)"
        )
        self.stt_consent_checkbox.setStyleSheet("font-weight: bold; color: #ffffff;")
        self.stt_consent_checkbox.toggled.connect(self._toggle_stt_consent)
        voice_layout.addWidget(self.stt_consent_checkbox)

        self.tts_consent_checkbox = QCheckBox(
            "Enable Cloud Text-to-Speech (Azure Neural & OpenAI Speech)"
        )
        self.tts_consent_checkbox.setStyleSheet("font-weight: bold; color: #ffffff;")
        self.tts_consent_checkbox.toggled.connect(self._toggle_tts_consent)
        voice_layout.addWidget(self.tts_consent_checkbox)

        voice_desc = QLabel(
            "Privacy Notice: Spoken audio captured by your microphone is used locally on-device "
            "for acoustic wake-word detection and is NEVER sent to cloud services unless this option is enabled. "
            "When enabled, recorded speech is transmitted to Google's Gemini multimodal service for "
            "Persian and English speech recognition. Disabling immediately revokes cloud access."
        )
        voice_desc.setWordWrap(True)
        voice_desc.setStyleSheet("color: #9a9996; font-size: 11px;")
        voice_layout.addWidget(voice_desc)

        layout.addWidget(voice_group)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        # Dialog Footer
        btn_footer = QHBoxLayout()
        btn_footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_footer.addWidget(close_btn)
        main_layout.addLayout(btn_footer)

    def _load_current_status(self) -> None:
        """Inspect stored credentials and update status displays."""
        # Gmail
        gmail_prov = self.email_service.get_provider("gmail")
        if gmail_prov.is_authenticated():
            info = gmail_prov.get_account_info()
            email_addr = info.get("email_address", "Connected")
            self.gmail_status_lbl.setText(f"✅ Connected: {email_addr}")
            self.gmail_status_lbl.setStyleSheet("color: #33d17a; font-weight: bold;")
        else:
            self.gmail_status_lbl.setText("❌ Not connected (No token stored)")
            self.gmail_status_lbl.setStyleSheet("color: #9a9996;")

        # MS Graph
        msgraph_prov = self.email_service.get_provider("msgraph")
        if msgraph_prov.is_authenticated():
            info = msgraph_prov.get_account_info()
            self.msgraph_status_lbl.setText(
                f"✅ Connected: {info.get('user_principal_name', 'Office 365')}"
            )
            self.msgraph_status_lbl.setStyleSheet("color: #33d17a; font-weight: bold;")
        else:
            self.msgraph_status_lbl.setText("❌ Not connected (No token stored)")
            self.msgraph_status_lbl.setStyleSheet("color: #9a9996;")

        # WhatsApp
        wa_stat = self.whatsapp_service.get_status()
        self.wa_phone_id_input.setText(
            self.credential_store.get_credential("whatsapp", "phone_number_id") or ""
        )
        self.wa_self_phone_input.setText(getattr(self.settings, "whatsapp_self_phone_number", ""))
        if wa_stat.get("configured"):
            self.wa_status_lbl.setText(f"✅ Configured: Phone ID {wa_stat.get('phone_number_id')}")
            self.wa_status_lbl.setStyleSheet("color: #33d17a; font-weight: bold;")
        else:
            self.wa_status_lbl.setText("❌ Not configured")
            self.wa_status_lbl.setStyleSheet("color: #9a9996;")

        # STT Cloud Consent
        self.stt_consent_checkbox.blockSignals(True)
        self.stt_consent_checkbox.setChecked(
            bool(getattr(self.settings, "voice_cloud_stt_consent", False))
        )
        self.stt_consent_checkbox.blockSignals(False)

        # Voice Identity settings
        curr_mic = getattr(self.settings, "voice_input_device", "")
        if curr_mic:
            idx_m = self.voice_mic_combo.findData(curr_mic)
            if idx_m >= 0:
                self.voice_mic_combo.setCurrentIndex(idx_m)

        curr_eng = getattr(self.settings, "voice_tts_engine", "sapi").lower()
        idx = self.voice_engine_combo.findData(curr_eng)
        if idx < 0:
            idx = self.voice_engine_combo.findText(curr_eng)
        if idx >= 0:
            self.voice_engine_combo.setCurrentIndex(idx)

        curr_voice = getattr(self.settings, "voice_british_voice", "en-GB-RyanNeural")
        idx_v = self.voice_name_combo.findText(curr_voice)
        if idx_v >= 0:
            self.voice_name_combo.setCurrentIndex(idx_v)

        curr_lang = getattr(self.settings, "voice_response_language", "en")
        idx_l = self.voice_resp_lang_combo.findText(curr_lang)
        if idx_l >= 0:
            self.voice_resp_lang_combo.setCurrentIndex(idx_l)

        self.stt_consent_checkbox.setChecked(
            bool(getattr(self.settings, "voice_cloud_stt_consent", False))
        )
        self.tts_consent_checkbox.setChecked(
            bool(getattr(self.settings, "voice_cloud_tts_consent", False))
        )

    def _toggle_stt_consent(self, checked: bool) -> None:
        """Update cloud STT consent in active settings and persistent environment."""
        self.settings.voice_cloud_stt_consent = bool(checked)
        try:
            from config import save_env_settings

            save_env_settings({"VOICE_CLOUD_STT_CONSENT": str(checked)})
        except Exception:
            pass

    def _toggle_tts_consent(self, checked: bool) -> None:
        """Update cloud TTS consent in active settings and persistent environment."""
        self.settings.voice_cloud_tts_consent = bool(checked)
        try:
            from config import save_env_settings

            save_env_settings({"VOICE_CLOUD_TTS_CONSENT": str(checked)})
        except Exception:
            pass

    def _save_gmail_token(self) -> None:
        val = self.gmail_token_input.text().strip()
        if not val:
            QMessageBox.warning(
                self, "Validation Error", "Please provide a valid Gmail OAuth token."
            )
            return
        self.credential_store.store_credential("gmail", "access_token", val)
        self.gmail_token_input.clear()
        QMessageBox.information(self, "Success", "Gmail OAuth token encrypted and stored securely.")
        self._load_current_status()

    def _disconnect_gmail(self) -> None:
        self.email_service.get_provider("gmail").disconnect()
        QMessageBox.information(
            self, "Disconnected", "Gmail account disconnected and token removed."
        )
        self._load_current_status()

    def _save_msgraph_token(self) -> None:
        val = self.msgraph_token_input.text().strip()
        if not val:
            QMessageBox.warning(
                self, "Validation Error", "Please provide a valid Microsoft Graph token."
            )
            return
        self.credential_store.store_credential("msgraph", "access_token", val)
        self.msgraph_token_input.clear()
        QMessageBox.information(
            self, "Success", "Microsoft Graph token encrypted and stored securely."
        )
        self._load_current_status()

    def _disconnect_msgraph(self) -> None:
        self.email_service.get_provider("msgraph").disconnect()
        QMessageBox.information(self, "Disconnected", "Microsoft Graph account disconnected.")
        self._load_current_status()

    def _save_whatsapp_config(self) -> None:
        phone_id = self.wa_phone_id_input.text().strip()
        token = self.wa_token_input.text().strip()
        self_phone = self.wa_self_phone_input.text().strip()

        if phone_id:
            self.credential_store.store_credential("whatsapp", "phone_number_id", phone_id)
        if token:
            self.credential_store.store_credential("whatsapp", "access_token", token)
            self.wa_token_input.clear()

        # Update self phone number in settings if provided
        if self_phone:
            try:
                norm = self.whatsapp_service.normalize_phone_number(self_phone)
                if not self.whatsapp_service.validate_phone_number(norm):
                    QMessageBox.warning(
                        self,
                        "Invalid Phone",
                        f"'{self_phone}' is not a valid international E.164 phone number.",
                    )
                    return
                # Update settings in memory and .env
                from config import save_env_settings

                save_env_settings({"WHATSAPP_SELF_PHONE_NUMBER": norm})
            except Exception as exc:
                QMessageBox.warning(self, "Save Error", f"Failed to save self phone number: {exc}")
                return

        QMessageBox.information(
            self, "Success", "WhatsApp Cloud API credentials encrypted and stored."
        )
        self._load_current_status()

    def _disconnect_whatsapp(self) -> None:
        self.credential_store.delete_credential("whatsapp")
        QMessageBox.information(self, "Disconnected", "WhatsApp credentials removed.")
        self._load_current_status()

    def _grant_recipient_consent(self) -> None:
        raw_phone = self.wa_consent_phone_input.text().strip()
        if not raw_phone:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid phone number.")
            return
        try:
            norm = self.whatsapp_service.normalize_phone_number(raw_phone)
            if not self.whatsapp_service.validate_phone_number(norm):
                QMessageBox.warning(self, "Validation Error", f"'{raw_phone}' is not valid E.164.")
                return
            self.comm_db.record_consent(norm, status="OPTED_IN", source="ui_settings")
            QMessageBox.information(
                self, "Consent Granted", f"Recipient {norm} has been marked as OPTED_IN."
            )
            self.wa_consent_phone_input.clear()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to record consent: {exc}")

    def _revoke_recipient_consent(self) -> None:
        raw_phone = self.wa_consent_phone_input.text().strip()
        if not raw_phone:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid phone number.")
            return
        try:
            norm = self.whatsapp_service.normalize_phone_number(raw_phone)
            self.comm_db.revoke_consent(norm, reason="ui_revocation")
            QMessageBox.information(
                self, "Consent Revoked", f"Recipient {norm} has been marked as OPTED_OUT."
            )
            self.wa_consent_phone_input.clear()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to revoke consent: {exc}")

    def _preview_voice(self) -> None:
        engine = (
            self.voice_engine_combo.currentData() or self.voice_engine_combo.currentText().strip()
        )
        voice = self.voice_name_combo.currentText().strip()
        tts = BritishNeuralTTSService(engine_name=engine, preferred_voice=voice)
        tts.preview_voice()

    def _save_voice_settings(self) -> None:
        mic_id = self.voice_mic_combo.currentData() or self.voice_mic_combo.currentText().strip()
        engine = (
            self.voice_engine_combo.currentData() or self.voice_engine_combo.currentText().strip()
        )
        voice = self.voice_name_combo.currentText().strip()
        resp_lang = self.voice_resp_lang_combo.currentText().strip()

        self.settings.voice_input_device = mic_id
        self.settings.voice_tts_engine = engine
        self.settings.voice_british_voice = voice
        self.settings.voice_response_language = resp_lang

        try:
            from config import save_env_settings

            save_env_settings(
                {
                    "VOICE_INPUT_DEVICE": mic_id,
                    "VOICE_TTS_ENGINE": engine,
                    "VOICE_BRITISH_VOICE": voice,
                    "VOICE_RESPONSE_LANGUAGE": resp_lang,
                }
            )
        except Exception:
            pass

        QMessageBox.information(
            self, "Voice Settings Saved", "JARVIS British voice identity settings updated."
        )
