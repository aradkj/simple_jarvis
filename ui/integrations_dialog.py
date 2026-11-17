"""PySide6 Universal Integrations Hub Dialog for JARVIS.

Provides full interactive management for:
- Integration status overview & health checks
- Google Antigravity (CLI discovery, IDE hooks, task delegation, verification)
- WhatsApp (Cloud API vs Linked-Device QR pairing, offline queue, authorized contacts)
- Multi-tool orchestrator pipeline (Antigravity -> Verification -> WhatsApp alert)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from infrastructure.logging import get_logger
from integrations.antigravity.adapter import get_antigravity_integration
from integrations.hub import initialize_default_integrations
from integrations.orchestrator import get_orchestrator
from integrations.whatsapp.adapter import get_whatsapp_integration
from integrations.whatsapp.provider_base import WhatsAppProviderType

logger = get_logger("ui.integrations_dialog")


class IntegrationWorker(QThread):
    """Background worker executing integration operations without freezing UI."""

    finished_signal = Signal(object)
    error_signal = Signal(str)

    def __init__(self, func: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            res = self.func(*self.args, **self.kwargs)
            self.finished_signal.emit(res)
        except Exception as exc:
            logger.error(f"Worker error: {exc}", exc_info=True)
            self.error_signal.emit(str(exc))


class IntegrationsDialog(QDialog):
    """Universal Integration Hub Control Panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JARVIS — Universal Integration Hub")
        self.resize(960, 720)

        self.hub = initialize_default_integrations()
        self.agy = get_antigravity_integration()
        self.wa = get_whatsapp_integration()
        self.orchestrator = get_orchestrator()

        self._active_worker: IntegrationWorker | None = None
        self._init_ui()
        self._refresh_overview()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Banner
        header = QFrame()
        header.setStyleSheet("background: #181b20; border-radius: 8px; padding: 10px;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)

        title_lbl = QLabel("<h2>🔌 JARVIS Universal Integration Hub</h2>")
        title_lbl.setStyleSheet("color: #61afef;")
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()

        self.refresh_btn = QPushButton("🔄 Refresh Status")
        self.refresh_btn.clicked.connect(self._refresh_overview)
        h_layout.addWidget(self.refresh_btn)

        self.health_btn = QPushButton("🩺 Health Check All")
        self.health_btn.clicked.connect(self._run_all_health_checks)
        h_layout.addWidget(self.health_btn)

        main_layout.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_overview_tab(), "📊 Overview")
        self.tabs.addTab(self._build_antigravity_tab(), "🚀 Google Antigravity")
        self.tabs.addTab(self._build_whatsapp_tab(), "💬 WhatsApp")
        self.tabs.addTab(self._build_orchestrator_tab(), "⚡ Multi-Tool Orchestrator")
        main_layout.addWidget(self.tabs)

    # ==================================================================
    # TAB 1: OVERVIEW
    # ==================================================================

    def _build_overview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.overview_table = QTableWidget(0, 5)
        self.overview_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Version", "Connection", "Health"]
        )
        self.overview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.overview_table)

        # Audit Trail Log
        audit_group = QGroupBox("Recent Audit Trail & Events")
        audit_layout = QVBoxLayout(audit_group)
        self.audit_log_view = QPlainTextEdit()
        self.audit_log_view.setReadOnly(True)
        self.audit_log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; background: #12151a;"
        )
        audit_layout.addWidget(self.audit_log_view)
        layout.addWidget(audit_group)

        return widget

    def _refresh_overview(self) -> None:
        overview = self.hub.get_status_overview()
        itgs = overview.get("integrations", {})

        self.overview_table.setRowCount(len(itgs))
        for row, (itg_id, data) in enumerate(itgs.items()):
            self.overview_table.setItem(row, 0, QTableWidgetItem(itg_id))
            self.overview_table.setItem(row, 1, QTableWidgetItem(data.get("name", "")))
            self.overview_table.setItem(row, 2, QTableWidgetItem(str(data.get("version", ""))))

            conn_state = data.get("connection_state", "unknown")
            conn_item = QTableWidgetItem(conn_state.upper())
            if conn_state == "connected":
                conn_item.setForeground(Qt.GlobalColor.green)
            else:
                conn_item.setForeground(Qt.GlobalColor.yellow)
            self.overview_table.setItem(row, 3, conn_item)

            health_state = data.get("health_state", "unknown")
            health_item = QTableWidgetItem(health_state.upper())
            if health_state == "healthy":
                health_item.setForeground(Qt.GlobalColor.green)
            else:
                health_item.setForeground(Qt.GlobalColor.red)
            self.overview_table.setItem(row, 4, health_item)

        # Update Audit Trail
        entries = self.hub.get_audit_trail(limit=50)
        lines = []
        for e in entries:
            lines.append(
                f"[{e.get('timestamp')}] {e.get('event_type')} | {e.get('integration_id')} | {e.get('operation')} | {e.get('payload')}"
            )
        self.audit_log_view.setPlainText("\n".join(lines))

    def _run_all_health_checks(self) -> None:
        self.health_btn.setEnabled(False)
        self.health_btn.setText("Checking...")

        def _do_check() -> dict[str, Any]:
            return self.hub.check_all_health()

        def _on_done(res: dict[str, Any]) -> None:
            self.health_btn.setEnabled(True)
            self.health_btn.setText("🩺 Health Check All")
            self._refresh_overview()
            msg = "\n".join(
                f"• {k}: {'HEALTHY' if v.healthy else 'DEGRADED'} ({v.message})"
                for k, v in res.items()
            )
            QMessageBox.information(self, "Health Check Results", msg)

        self._run_async(_do_check, _on_done)

    # ==================================================================
    # TAB 2: GOOGLE ANTIGRAVITY
    # ==================================================================

    def _build_antigravity_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Diagnostic Status Box
        diag_box = QGroupBox("Antigravity Discovery & Status")
        diag_layout = QVBoxLayout(diag_box)
        self.agy_diag_lbl = QLabel("Detecting CLI and IDE...")
        self.agy_diag_lbl.setStyleSheet("font-family: Consolas; font-size: 11px;")
        diag_layout.addWidget(self.agy_diag_lbl)

        # IDE Hook Actions
        h_btn_box = QHBoxLayout()
        self.install_hooks_btn = QPushButton("📥 Install IDE Hooks")
        self.install_hooks_btn.clicked.connect(self._install_ide_hooks)
        h_btn_box.addWidget(self.install_hooks_btn)

        self.uninstall_hooks_btn = QPushButton("📤 Uninstall IDE Hooks")
        self.uninstall_hooks_btn.clicked.connect(self._uninstall_ide_hooks)
        h_btn_box.addWidget(self.uninstall_hooks_btn)
        h_btn_box.addStretch()
        diag_layout.addLayout(h_btn_box)
        layout.addWidget(diag_box)

        # Task Dispatcher Box
        task_box = QGroupBox("Dispatch Coding Task")
        tb_layout = QVBoxLayout(task_box)

        # Workspace Picker
        ws_layout = QHBoxLayout()
        ws_layout.addWidget(QLabel("Workspace:"))
        self.agy_ws_input = QLineEdit(str(Path.cwd()))
        ws_layout.addWidget(self.agy_ws_input)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_agy_workspace)
        ws_layout.addWidget(browse_btn)
        tb_layout.addLayout(ws_layout)

        # Prompt input
        tb_layout.addWidget(QLabel("Instruction / Task Prompt (Persian or English):"))
        self.agy_prompt_input = QTextEdit()
        self.agy_prompt_input.setPlaceholderText(
            "مثال: رفع باگ در تست‌های احراز هویت یا افزودن متد جدید..."
        )
        self.agy_prompt_input.setMaximumHeight(80)
        tb_layout.addWidget(self.agy_prompt_input)

        # Buttons
        act_layout = QHBoxLayout()
        self.agy_run_btn = QPushButton("▶️ Run Antigravity Task")
        self.agy_run_btn.setStyleSheet("background: #28a745; font-weight: bold;")
        self.agy_run_btn.clicked.connect(self._run_agy_task)
        act_layout.addWidget(self.agy_run_btn)

        self.agy_verify_btn = QPushButton("🔍 Run Independent Verifier")
        self.agy_verify_btn.clicked.connect(self._run_agy_verifier)
        act_layout.addWidget(self.agy_verify_btn)

        self.agy_cancel_btn = QPushButton("🛑 Cancel Task")
        self.agy_cancel_btn.clicked.connect(self._cancel_agy_task)
        self.agy_cancel_btn.setEnabled(False)
        act_layout.addWidget(self.agy_cancel_btn)
        tb_layout.addLayout(act_layout)
        layout.addWidget(task_box)

        # Logs & Verification Output
        log_box = QGroupBox("Execution & Verification Logs")
        lb_layout = QVBoxLayout(log_box)
        self.agy_log_view = QPlainTextEdit()
        self.agy_log_view.setReadOnly(True)
        self.agy_log_view.setStyleSheet(
            "font-family: Consolas; font-size: 11px; background: #12151a;"
        )
        lb_layout.addWidget(self.agy_log_view)
        layout.addWidget(log_box)

        self._refresh_agy_status()
        return widget

    def _refresh_agy_status(self) -> None:
        status = self.agy.get_status()
        cli_ok = status.get("cli_available", False)
        cli_v = status.get("cli_version", "N/A")
        ide_disc = status.get("ide_discovery", {})
        hooks = status.get("global_hooks", {})

        info_text = (
            f"• CLI Available: {'YES' if cli_ok else 'NO'} | Version: {cli_v}\n"
            f"• IDE Detected: {'YES' if ide_disc.get('installed') else 'NO'} ({ide_disc.get('executable_path')})\n"
            f"• Hooks File: {hooks.get('hooks_file')} | JARVIS Hooks Installed: {'YES' if hooks.get('jarvis_hooks_installed') else 'NO'}"
        )
        self.agy_diag_lbl.setText(info_text)

    def _browse_agy_workspace(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Workspace Directory", self.agy_ws_input.text()
        )
        if dir_path:
            self.agy_ws_input.setText(dir_path)

    def _install_ide_hooks(self) -> None:
        res = self.agy.execute("install_ide_hooks", {})
        if res.success:
            QMessageBox.information(
                self, "IDE Hooks", "JARVIS lifecycle hooks installed successfully."
            )
            self._refresh_agy_status()
        else:
            QMessageBox.critical(self, "IDE Hooks Error", res.error or "Failed to install hooks.")

    def _uninstall_ide_hooks(self) -> None:
        res = self.agy.execute("uninstall_ide_hooks", {})
        if res.success:
            QMessageBox.information(
                self, "IDE Hooks", "JARVIS lifecycle hooks uninstalled and restored."
            )
            self._refresh_agy_status()
        else:
            QMessageBox.critical(self, "IDE Hooks Error", res.error or "Failed to uninstall hooks.")

    def _run_agy_task(self) -> None:
        prompt = self.agy_prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Input Required", "Please enter a task prompt.")
            return

        ws = self.agy_ws_input.text().strip()
        self.agy_run_btn.setEnabled(False)
        self.agy_cancel_btn.setEnabled(True)
        self.agy_log_view.setPlainText("Launching Antigravity task in background...\n")

        def _task_worker() -> Any:
            return self.agy.execute(
                "delegate_task",
                {"prompt": prompt, "workspace_path": ws, "auto_verify": True},
            )

        def _on_done(res: Any) -> None:
            self.agy_run_btn.setEnabled(True)
            self.agy_cancel_btn.setEnabled(False)
            if res.success:
                self.agy_log_view.appendPlainText(
                    f"\n✅ Task Completed Successfully!\nResult: {res.data}"
                )
            else:
                self.agy_log_view.appendPlainText(f"\n❌ Task Failed: {res.error}")
            self._refresh_overview()

        self._run_async(_task_worker, _on_done)

    def _run_agy_verifier(self) -> None:
        ws = self.agy_ws_input.text().strip()
        self.agy_log_view.appendPlainText("\nRunning independent verification...")

        def _verif_worker() -> Any:
            return self.agy.execute("verify_workspace", {"workspace_path": ws})

        def _on_done(res: Any) -> None:
            if res.success:
                v = res.data
                self.agy_log_view.appendPlainText(
                    f"\n--- Verification Result ---\n"
                    f"Verified: {v.get('verified')}\n"
                    f"Message: {v.get('message')}\n"
                    f"Changed Files: {v.get('git_changed_files')}\n"
                    f"Tests Executed: {v.get('tests_executed')} | Passed: {v.get('tests_passed')}\n"
                )
            else:
                self.agy_log_view.appendPlainText(f"Verification error: {res.error}")

        self._run_async(_verif_worker, _on_done)

    def _cancel_agy_task(self) -> None:
        # Cancel all active tasks
        tasks = self.agy.tracker.list_tasks()
        cancelled_any = False
        for t in tasks:
            if t.state.value in ("created", "accepted", "started", "progress"):
                self.agy.cancel(t.task_id)
                cancelled_any = True
        if cancelled_any:
            self.agy_log_view.appendPlainText("\nRequested task cancellation.")
            self.agy_cancel_btn.setEnabled(False)

    # ==================================================================
    # TAB 3: WHATSAPP
    # ==================================================================

    def _build_whatsapp_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Provider Selector & Status
        prov_box = QGroupBox("WhatsApp Provider & State")
        pb_layout = QHBoxLayout(prov_box)
        pb_layout.addWidget(QLabel("Active Provider:"))
        self.wa_provider_combo = QComboBox()
        self.wa_provider_combo.addItems(["Linked Device (QR Pairing)", "Meta Cloud API"])
        self.wa_provider_combo.currentIndexChanged.connect(self._on_wa_provider_changed)
        pb_layout.addWidget(self.wa_provider_combo)

        self.wa_status_lbl = QLabel("Status: Disconnected")
        self.wa_status_lbl.setStyleSheet("font-weight: bold; margin-left: 15px;")
        pb_layout.addWidget(self.wa_status_lbl)
        pb_layout.addStretch()

        self.wa_reconnect_btn = QPushButton("⚡ Reconnect")
        self.wa_reconnect_btn.clicked.connect(self._reconnect_whatsapp)
        pb_layout.addWidget(self.wa_reconnect_btn)

        layout.addWidget(prov_box)

        # Splitter: QR Pairing / Messaging vs Authorized Contacts
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Pairing & Messaging
        left_widget = QWidget()
        lw_layout = QVBoxLayout(left_widget)

        pair_group = QGroupBox("Personal Device Pairing (QR Code)")
        pg_layout = QVBoxLayout(pair_group)
        self.qr_display = QTextEdit()
        self.qr_display.setReadOnly(True)
        self.qr_display.setMaximumHeight(110)
        self.qr_display.setPlaceholderText("QR Code pairing payload will appear here...")
        pg_layout.addWidget(self.qr_display)

        pair_btns = QHBoxLayout()
        self.gen_qr_btn = QPushButton("📱 Generate Pairing QR")
        self.gen_qr_btn.clicked.connect(self._generate_wa_qr)
        pair_btns.addWidget(self.gen_qr_btn)

        self.confirm_pair_btn = QPushButton("✅ Confirm Pairing (Test)")
        self.confirm_pair_btn.clicked.connect(self._confirm_wa_pairing)
        pair_btns.addWidget(self.confirm_pair_btn)

        self.disconnect_wa_btn = QPushButton("❌ Disconnect Session")
        self.disconnect_wa_btn.clicked.connect(self._disconnect_wa)
        pair_btns.addWidget(self.disconnect_wa_btn)

        pg_layout.addLayout(pair_btns)
        lw_layout.addWidget(pair_group)

        # Outgoing Message Box
        msg_group = QGroupBox("Send Message / Notification")
        mg_layout = QVBoxLayout(msg_group)

        recip_layout = QHBoxLayout()
        recip_layout.addWidget(QLabel("Recipient:"))
        self.wa_recip_input = QLineEdit("خودم")
        recip_layout.addWidget(self.wa_recip_input)
        mg_layout.addLayout(recip_layout)

        mg_layout.addWidget(QLabel("Message:"))
        self.wa_msg_input = QTextEdit("سلام! تست اتصال یکپارچه‌سازی واتساپ جارویس.")
        self.wa_msg_input.setMaximumHeight(60)
        mg_layout.addWidget(self.wa_msg_input)

        msg_act_layout = QHBoxLayout()
        self.send_msg_btn = QPushButton("📤 Send Message")
        self.send_msg_btn.clicked.connect(self._send_wa_message)
        msg_act_layout.addWidget(self.send_msg_btn)

        self.flush_queue_btn = QPushButton("📬 Flush Offline Queue")
        self.flush_queue_btn.clicked.connect(self._flush_wa_queue)
        msg_act_layout.addWidget(self.flush_queue_btn)
        mg_layout.addLayout(msg_act_layout)

        lw_layout.addWidget(msg_group)
        splitter.addWidget(left_widget)

        # Right: Authorized Contacts
        right_widget = QWidget()
        rw_layout = QVBoxLayout(right_widget)
        contact_group = QGroupBox("Authorized Contacts & Permissions")
        cg_layout = QVBoxLayout(contact_group)

        self.contacts_list = QListWidget()
        cg_layout.addWidget(self.contacts_list)

        # Add Contact Form
        add_form = QHBoxLayout()
        self.new_contact_phone = QLineEdit()
        self.new_contact_phone.setPlaceholderText("+98912xxxxxxx")
        add_form.addWidget(self.new_contact_phone)

        self.new_contact_name = QLineEdit()
        self.new_contact_name.setPlaceholderText("Name")
        add_form.addWidget(self.new_contact_name)

        add_contact_btn = QPushButton("➕ Add Contact")
        add_contact_btn.clicked.connect(self._add_wa_contact)
        add_form.addWidget(add_contact_btn)
        cg_layout.addLayout(add_form)

        rw_layout.addWidget(contact_group)
        splitter.addWidget(right_widget)

        layout.addWidget(splitter)
        self._refresh_wa_status()
        return widget

    def _on_wa_provider_changed(self, idx: int) -> None:
        ptype = WhatsAppProviderType.LINKED_DEVICE if idx == 0 else WhatsAppProviderType.CLOUD_API
        self.wa.set_provider_type(ptype)
        self._refresh_wa_status()

    def _refresh_wa_status(self) -> None:
        status = self.wa.get_status()
        status.get("provider_status", {})
        is_conn = self.wa.is_ready_to_send()
        self.wa_status_lbl.setText(f"Status: {'CONNECTED' if is_conn else 'DISCONNECTED'}")
        self.wa_status_lbl.setStyleSheet(
            f"font-weight: bold; color: {'#28a745' if is_conn else '#dc3545'};"
        )

        # Refresh contacts
        self.contacts_list.clear()
        for c in self.wa.contact_mgr.list_authorized_contacts():
            cmd_badge = " [Commands Allowed]" if c.can_execute_commands else ""
            self.contacts_list.addItem(f"{c.name} ({c.phone}) - {c.role}{cmd_badge}")

    def _reconnect_whatsapp(self) -> None:
        self.wa.connect()
        self._refresh_wa_status()

    def _generate_wa_qr(self) -> None:
        res = self.wa.execute("pair_qr", {})
        if res.success:
            qr = res.data.get("qr_code", "")
            self.qr_display.setPlainText(f"Scan with WhatsApp Companion Device:\n\n{qr}")
            self._refresh_wa_status()
        else:
            QMessageBox.critical(self, "QR Error", res.error or "Failed to generate QR.")

    def _confirm_wa_pairing(self) -> None:
        phone = self.new_contact_phone.text().strip() or "+989121112233"
        self.wa.execute("confirm_pairing", {"phone": phone})
        QMessageBox.information(self, "Pairing Confirmed", f"Paired successfully with {phone}.")
        self._refresh_wa_status()

    def _disconnect_wa(self) -> None:
        self.wa.disconnect()
        self.qr_display.clear()
        QMessageBox.information(self, "WhatsApp", "Session disconnected.")
        self._refresh_wa_status()

    def _send_wa_message(self) -> None:
        recip = self.wa_recip_input.text().strip()
        msg = self.wa_msg_input.toPlainText().strip()
        if not recip or not msg:
            return

        res = self.wa.execute("send_message", {"recipient": recip, "text": msg})
        if res.success:
            QMessageBox.information(
                self, "Message Sent", f"Delivered to {res.data.get('recipient')}"
            )
        else:
            QMessageBox.warning(self, "Message Status", f"Result: {res.error or 'Failed'}")
        self._refresh_wa_status()

    def _flush_wa_queue(self) -> None:
        cnt = self.wa.flush_offline_queue()
        QMessageBox.information(self, "Queue Flushed", f"Flushed {cnt} pending messages.")
        self._refresh_wa_status()

    def _add_wa_contact(self) -> None:
        phone = self.new_contact_phone.text().strip()
        name = self.new_contact_name.text().strip()
        if not phone or not name:
            QMessageBox.warning(self, "Required Fields", "Phone and Name are required.")
            return

        self.wa.execute(
            "add_authorized_contact", {"phone": phone, "name": name, "can_execute_commands": True}
        )
        self.new_contact_phone.clear()
        self.new_contact_name.clear()
        self._refresh_wa_status()

    # ==================================================================
    # TAB 4: MULTI-TOOL ORCHESTRATOR
    # ==================================================================

    def _build_orchestrator_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info_box = QGroupBox("Cross-Tool Pipeline: Antigravity -> Verification -> WhatsApp Alert")
        ib_layout = QVBoxLayout(info_box)

        lbl = QLabel(
            "This pipeline executes an end-to-end coding task using Google Antigravity, runs independent\n"
            "verification on modified files, and dispatches real-time WhatsApp completion or failure alerts."
        )
        ib_layout.addWidget(lbl)

        # Form
        orch_form = QHBoxLayout()
        orch_form.addWidget(QLabel("Prompt:"))
        self.orch_prompt_input = QLineEdit("بررسی و اجرای تست‌های ماژول یکپارچه‌سازی")
        orch_form.addWidget(self.orch_prompt_input)

        orch_form.addWidget(QLabel("Recipient:"))
        self.orch_recip_input = QLineEdit("خودم")
        orch_form.addWidget(self.orch_recip_input)

        self.orch_run_btn = QPushButton("⚡ Launch Pipeline")
        self.orch_run_btn.setStyleSheet("background: #007acc; font-weight: bold;")
        self.orch_run_btn.clicked.connect(self._run_orchestrated_pipeline)
        orch_form.addWidget(self.orch_run_btn)
        ib_layout.addLayout(orch_form)

        layout.addWidget(info_box)

        # Jobs Table
        jobs_box = QGroupBox("Orchestrated Jobs History")
        jb_layout = QVBoxLayout(jobs_box)
        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(
            ["Job ID", "Status", "Task ID", "WhatsApp Alert", "Description"]
        )
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        jb_layout.addWidget(self.jobs_table)
        layout.addWidget(jobs_box)

        self._refresh_orchestrator_jobs()
        return widget

    def _run_orchestrated_pipeline(self) -> None:
        prompt = self.orch_prompt_input.text().strip()
        recip = self.orch_recip_input.text().strip()
        if not prompt:
            return

        self.orchestrator.run_antigravity_with_whatsapp_alert(
            prompt=prompt,
            recipient=recip,
        )
        self._refresh_orchestrator_jobs()
        QMessageBox.information(
            self, "Pipeline Started", "Orchestrated pipeline running in background."
        )

    def _refresh_orchestrator_jobs(self) -> None:
        jobs = self.orchestrator.list_jobs()
        self.jobs_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self.jobs_table.setItem(row, 0, QTableWidgetItem(job.job_id))
            self.jobs_table.setItem(row, 1, QTableWidgetItem(job.status))
            self.jobs_table.setItem(row, 2, QTableWidgetItem(job.task_id or "N/A"))
            self.jobs_table.setItem(row, 3, QTableWidgetItem(job.notification_status))
            self.jobs_table.setItem(row, 4, QTableWidgetItem(job.description))

    # ==================================================================
    # Asynchronous Execution Helper
    # ==================================================================

    def _run_async(self, worker_func: Any, on_finished: Any) -> None:
        worker = IntegrationWorker(worker_func)
        worker.finished_signal.connect(on_finished)
        worker.error_signal.connect(lambda err: QMessageBox.critical(self, "Error", err))
        self._active_worker = worker
        worker.start()
