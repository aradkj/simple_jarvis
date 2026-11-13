"""Chat panel managing conversational message list, input bar, and streaming responses."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.styles import is_persian_text


class ApprovalCardWidget(QFrame):
    """Visual confirmation card for sensitive tool proposals requiring human approval."""

    decision_submitted = Signal(str, bool, str)  # proposal_id, approved, session_id

    def __init__(
        self,
        proposal_id: str,
        tool_name: str,
        arguments: dict,
        risk_level: str,
        rationale: str,
        session_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.proposal_id = proposal_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.risk_level = risk_level.upper()
        self.rationale = rationale
        self.session_id = session_id
        self._decided = False
        self._init_ui()

    def _init_ui(self) -> None:
        self.setObjectName("approvalCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            #approvalCard {
                background-color: #2b2b2b;
                border: 2px solid #e5a50a;
                border-radius: 8px;
                padding: 12px;
                margin: 6px 0px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header: Tool & Risk Badge
        header_layout = QHBoxLayout()
        title_label = QLabel(f"⚠️ Action Requires Confirmation: {self.tool_name}")
        font = QFont()
        font.setBold(True)
        title_label.setFont(font)
        title_label.setStyleSheet("color: #f6d32d; font-size: 14px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        badge_color = "#e01b24" if self.risk_level in ("HIGH", "CRITICAL") else "#e5a50a"
        badge_label = QLabel(f"[{self.risk_level}]")
        badge_label.setStyleSheet(
            f"background-color: {badge_color}; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;"
        )
        header_layout.addWidget(badge_label)
        layout.addLayout(header_layout)

        # Rationale
        if self.rationale:
            reason_label = QLabel(f"Reason: {self.rationale}")
            reason_label.setWordWrap(True)
            if is_persian_text(self.rationale):
                reason_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            reason_label.setStyleSheet("color: #deddda; font-style: italic;")
            layout.addWidget(reason_label)

        # Destructive Power Warning and Mandatory Confirmation Checkbox
        if self.tool_name in ("windows_power_restart", "windows_power_shutdown"):
            warning_frame = QFrame()
            warning_frame.setStyleSheet(
                "background-color: #3d0a0a; border: 1px solid #e01b24; border-radius: 6px; padding: 8px;"
            )
            w_layout = QVBoxLayout(warning_frame)
            w_layout.setContentsMargins(6, 6, 6, 6)
            w_layout.setSpacing(4)
            w_label = QLabel(
                "⚠️ هشدار جدی: تمام کارهای ذخیره‌نشده در همه برنامه‌ها از دست خواهند رفت!\n"
                "CRITICAL WARNING: Unsaved work in all running applications will be permanently lost."
            )
            w_label.setWordWrap(True)
            w_label.setStyleSheet("color: #ff7b72; font-weight: bold; font-size: 12px;")
            w_layout.addWidget(w_label)
            layout.addWidget(warning_frame)

            self.confirm_checkbox = QCheckBox(
                "من تأیید می‌کنم که کارهای ذخیره‌نشده از دست خواهند رفت / "
                "I acknowledge unsaved work will be lost"
            )
            self.confirm_checkbox.setStyleSheet("color: #f6d32d; font-weight: bold; padding: 4px;")
            layout.addWidget(self.confirm_checkbox)

        # Parameters / Arguments
        if self.arguments:
            args_label = QLabel("Proposed Parameters:")
            args_label.setStyleSheet("color: #9a9996; font-size: 12px;")
            layout.addWidget(args_label)

            args_text = "\n".join(f"  • {k}: {v}" for k, v in self.arguments.items())
            args_display = QLabel(args_text)
            args_display.setWordWrap(True)
            args_display.setStyleSheet(
                "background-color: #1e1e1e; color: #33d17a; padding: 6px; border-radius: 4px; font-family: monospace;"
            )
            layout.addWidget(args_display)

        # Action Buttons: Approve / Reject
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setStyleSheet(
            "background-color: #c01c28; color: white; padding: 6px 14px; border-radius: 4px; font-weight: bold;"
        )
        self.reject_btn.clicked.connect(self._on_reject)
        btn_layout.addWidget(self.reject_btn)

        self.approve_btn = QPushButton("Approve")
        self.approve_btn.setStyleSheet(
            "background-color: #2ec27e; color: white; padding: 6px 14px; border-radius: 4px; font-weight: bold;"
        )
        self.approve_btn.clicked.connect(self._on_approve)
        btn_layout.addWidget(self.approve_btn)

        if self.tool_name in ("windows_power_restart", "windows_power_shutdown"):
            self.approve_btn.setEnabled(False)
            self.confirm_checkbox.toggled.connect(self.approve_btn.setEnabled)

        layout.addLayout(btn_layout)

    def _on_approve(self) -> None:
        if self._decided:
            return

        if self.tool_name in ("windows_power_restart", "windows_power_shutdown"):
            if not hasattr(self, "confirm_checkbox") or not self.confirm_checkbox.isChecked():
                return
            action_name = "Restart" if "restart" in self.tool_name else "Shutdown"
            res = QMessageBox.question(
                self,
                f"Confirm Windows {action_name}",
                f"Are you absolutely certain you want to {action_name.lower()} Windows?\n\n"
                "All unsaved progress in open applications will be lost immediately.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return

        self._decided = True
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        if hasattr(self, "confirm_checkbox"):
            self.confirm_checkbox.setEnabled(False)
        self.approve_btn.setText("Approved ✓")
        self.decision_submitted.emit(self.proposal_id, True, self.session_id)

    def _on_reject(self) -> None:
        if self._decided:
            return
        self._decided = True
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        if hasattr(self, "confirm_checkbox"):
            self.confirm_checkbox.setEnabled(False)
        self.reject_btn.setText("Rejected ✗")
        self.decision_submitted.emit(self.proposal_id, False, self.session_id)


class ChatInputField(QPlainTextEdit):
    """Custom input edit that sends on Enter and allows Shift+Enter for newline."""

    send_triggered = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setPlaceholderText("Type a message in English or فارسی... (Press Enter to Send)")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_triggered.emit()
                event.accept()
        else:
            super().keyPressEvent(event)


class MessageBubble(QFrame):
    """Visual bubble for a single chat message with RTL/LTR awareness and status indicators."""

    retry_requested = Signal(str)

    def __init__(
        self,
        sender: str,
        text: str,
        timestamp: str | None = None,
        is_user: bool = False,
        is_streaming: bool = False,
        is_error: bool = False,
        is_cancelled: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sender = sender
        self.raw_text = text
        self.is_user = is_user
        self.is_streaming = is_streaming
        self.is_error = is_error
        self.is_cancelled = is_cancelled
        self.timestamp = timestamp or datetime.now().strftime("%H:%M")
        self._init_ui()

    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 10, 14, 10)
        self.main_layout.setSpacing(4)

        # Header layout
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)

        self.sender_lbl = QLabel(self.sender)
        self._update_sender_style()

        self.time_lbl = QLabel(self.timestamp)
        self.time_lbl.setStyleSheet("font-size: 10px; color: #8b949e;")

        is_persian = is_persian_text(self.raw_text)
        if is_persian:
            self.header_layout.addWidget(self.time_lbl)
            self.header_layout.addStretch()
            self.header_layout.addWidget(self.sender_lbl)
        else:
            self.header_layout.addWidget(self.sender_lbl)
            self.header_layout.addStretch()
            self.header_layout.addWidget(self.time_lbl)

        self.main_layout.addLayout(self.header_layout)

        # Message Text Label
        self.text_lbl = QLabel(self.raw_text)
        self.text_lbl.setWordWrap(True)
        self.text_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._apply_text_direction(self.raw_text)
        self.main_layout.addWidget(self.text_lbl)

        # Optional action bar (e.g. Retry button on errors)
        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 4, 0, 0)
        self.retry_btn = QPushButton("↺ Retry")
        self.retry_btn.setFixedHeight(26)
        self.retry_btn.setStyleSheet(
            "font-size: 11px; padding: 2px 8px; background-color: #30363d; color: #f85149;"
        )
        self.retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.raw_text))
        self.retry_btn.setVisible(self.is_error)
        self.action_layout.addWidget(self.retry_btn)
        self.action_layout.addStretch()
        self.main_layout.addLayout(self.action_layout)

        self._apply_bubble_style()

    def _update_sender_style(self) -> None:
        if self.is_user:
            color = "#58a6ff"
        elif self.is_error:
            color = "#f85149"
        elif self.is_cancelled:
            color = "#d29922"
        else:
            color = "#00d2ff"
        self.sender_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")

    def _apply_text_direction(self, text: str) -> None:
        if is_persian_text(text):
            self.text_lbl.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.text_lbl.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _apply_bubble_style(self) -> None:
        if self.is_user:
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: #1f2937;
                    border: 1px solid #374151;
                    border-radius: 12px;
                }
                QLabel { color: #f3f4f6; font-size: 13px; }
                """
            )
        elif self.is_error:
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: #261114;
                    border: 1px solid #6e1d24;
                    border-left: 3px solid #f85149;
                    border-radius: 12px;
                }
                QLabel { color: #ff7b72; font-size: 13px; }
                """
            )
        elif self.is_cancelled:
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: #231d14;
                    border: 1px solid #5d4822;
                    border-left: 3px solid #d29922;
                    border-radius: 12px;
                }
                QLabel { color: #e3b341; font-size: 13px; }
                """
            )
        else:
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: #111b27;
                    border: 1px solid #1f3a5a;
                    border-left: 3px solid #00d2ff;
                    border-radius: 12px;
                }
                QLabel { color: #e6edf3; font-size: 13px; }
                """
            )

    def set_content(self, text: str) -> None:
        """Update the text content during streaming."""
        self.raw_text = text
        self.text_lbl.setText(text)
        self._apply_text_direction(text)

    def mark_completed(self, final_text: str | None = None) -> None:
        """Mark streaming as successfully finished."""
        if final_text is not None:
            self.set_content(final_text)
        self.is_streaming = False
        self._apply_bubble_style()

    def mark_cancelled(self) -> None:
        """Mark streaming as cancelled."""
        self.is_streaming = False
        self.is_cancelled = True
        cancelled_note = (
            self.raw_text + ("\n\n" if self.raw_text else "") + "*(Generation cancelled)*"
        )
        self.set_content(cancelled_note)
        self._update_sender_style()
        self._apply_bubble_style()

    def mark_failed(self, error_message: str) -> None:
        """Mark streaming as failed."""
        self.is_streaming = False
        self.is_error = True
        if self.raw_text:
            self.set_content(f"{self.raw_text}\n\n⚠️ [Interrupted: {error_message}]")
        else:
            self.set_content(f"Error: {error_message}")
        self.retry_btn.setVisible(True)
        self._update_sender_style()
        self._apply_bubble_style()


class ChatPanel(QWidget):
    """Main conversational interface containing message list, toolbar, and input bar."""

    message_submitted = Signal(str)
    cancellation_requested = Signal()
    new_chat_requested = Signal()
    clear_chat_requested = Signal()
    retry_requested = Signal(str)
    approval_decided = Signal(str, bool, str)  # proposal_id, approved, session_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_streaming_bubble: MessageBubble | None = None
        self._is_generating = False
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(10)

        # 1. Chat Header Toolbar (New Chat / Clear Chat)
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        self.chat_title_lbl = QLabel("Conversation")
        self.chat_title_lbl.setStyleSheet("font-weight: 600; color: #8b949e; font-size: 12px;")
        toolbar_layout.addWidget(self.chat_title_lbl)
        toolbar_layout.addStretch()

        self.new_chat_btn = QPushButton("+ New Chat")
        self.new_chat_btn.setFixedHeight(28)
        self.new_chat_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.new_chat_btn.clicked.connect(self.new_chat_requested.emit)
        toolbar_layout.addWidget(self.new_chat_btn)

        self.clear_chat_btn = QPushButton("🗑 Clear")
        self.clear_chat_btn.setFixedHeight(28)
        self.clear_chat_btn.setStyleSheet("font-size: 11px; padding: 2px 10px; color: #8b949e;")
        self.clear_chat_btn.clicked.connect(self.clear_chat_requested.emit)
        toolbar_layout.addWidget(self.clear_chat_btn)

        main_layout.addWidget(toolbar)

        # 2. Scrollable Message Container
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch()

        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # 3. Input Bar
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self.input_field = ChatInputField()
        self.input_field.send_triggered.connect(self._on_action_clicked)
        input_layout.addWidget(self.input_field, stretch=1)

        self.action_button = QPushButton("Send")
        self.action_button.setObjectName("PrimaryButton")
        self.action_button.setFixedHeight(70)
        self.action_button.setFixedWidth(85)
        self.action_button.clicked.connect(self._on_action_clicked)
        self.send_button = self.action_button
        input_layout.addWidget(self.action_button)

        main_layout.addWidget(input_container)

    def _on_action_clicked(self) -> None:
        if self._is_generating:
            # Action button is acting as "Cancel"
            self.cancellation_requested.emit()
            return

        text = self.input_field.toPlainText().strip()
        if not text:
            return
        self.input_field.clear()
        self.message_submitted.emit(text)

    def set_generating_state(self, is_generating: bool) -> None:
        """Switch input bar state between sending and generating."""
        self._is_generating = is_generating
        if is_generating:
            self.action_button.setText("Cancel")
            self.action_button.setStyleSheet(
                "background-color: #b62324; color: white; border: none; border-radius: 6px; font-weight: bold;"
            )
            self.input_field.setEnabled(False)
        else:
            self.action_button.setText("Send")
            self.action_button.setStyleSheet("")  # Revert to PrimaryButton styling
            self.input_field.setEnabled(True)
            self.input_field.setFocus()

    def add_message(
        self,
        sender: str,
        text: str,
        is_user: bool = False,
        is_error: bool = False,
    ) -> MessageBubble:
        """Add a complete message bubble to the conversation area."""
        bubble = MessageBubble(sender=sender, text=text, is_user=is_user, is_error=is_error)
        bubble.retry_requested.connect(self.retry_requested.emit)
        self._insert_bubble(bubble, is_user=is_user)
        return bubble

    def start_assistant_streaming(self, sender: str = "JARVIS") -> MessageBubble:
        """Create and mount a new empty assistant bubble in streaming mode."""
        bubble = MessageBubble(sender=sender, text="", is_user=False, is_streaming=True)
        bubble.retry_requested.connect(self.retry_requested.emit)
        self._current_streaming_bubble = bubble
        self._insert_bubble(bubble, is_user=False)
        self.set_generating_state(True)
        return bubble

    def append_streaming_chunk(self, chunk: str) -> None:
        """Append a newly received text chunk to the active streaming bubble."""
        if self._current_streaming_bubble:
            current = self._current_streaming_bubble.raw_text
            self._current_streaming_bubble.set_content(current + chunk)
            self._scroll_to_bottom()

    # Alias for naming consistency
    append_assistant_chunk = append_streaming_chunk

    def finish_assistant_streaming(self, final_text: str | None = None) -> None:
        """Finalize the active streaming bubble as completed."""
        if self._current_streaming_bubble:
            self._current_streaming_bubble.mark_completed(final_text)
            self._current_streaming_bubble = None
        self.set_generating_state(False)
        self._scroll_to_bottom()

    def cancel_assistant_streaming(self) -> None:
        """Mark the active streaming bubble as cancelled."""
        if self._current_streaming_bubble:
            self._current_streaming_bubble.mark_cancelled()
            self._current_streaming_bubble = None
        self.set_generating_state(False)
        self._scroll_to_bottom()

    def fail_assistant_streaming(self, error_message: str) -> None:
        """Mark the active streaming bubble as failed with error details."""
        if self._current_streaming_bubble:
            self._current_streaming_bubble.mark_failed(error_message)
            self._current_streaming_bubble = None
        else:
            self.add_message("JARVIS", f"Error: {error_message}", is_user=False, is_error=True)
        self.set_generating_state(False)
        self._scroll_to_bottom()

    def clear_messages(self) -> None:
        """Clear all messages from the conversation view."""
        # Remove all widgets before trailing stretch
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_approval_card(
        self,
        proposal_id: str,
        tool_name: str,
        arguments: dict,
        risk_level: str,
        rationale: str,
        session_id: str = "",
    ) -> ApprovalCardWidget:
        """Add an interactive approval card to the conversation."""
        card = ApprovalCardWidget(
            proposal_id=proposal_id,
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk_level,
            rationale=rationale,
            session_id=session_id,
        )
        card.decision_submitted.connect(self.approval_decided.emit)

        wrapper = QWidget()
        wrap_layout = QHBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        wrap_layout.addWidget(card)

        count = self.messages_layout.count()
        self.messages_layout.insertWidget(count - 1, wrapper)
        self._scroll_to_bottom()
        return card

    def _insert_bubble(self, bubble: MessageBubble, is_user: bool) -> None:
        wrapper = QWidget()
        wrap_layout = QHBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)

        if is_user:
            wrap_layout.addStretch()
            bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            wrap_layout.addWidget(bubble)
        else:
            bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            wrap_layout.addWidget(bubble)
            wrap_layout.addStretch()

        count = self.messages_layout.count()
        self.messages_layout.insertWidget(count - 1, wrapper)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
