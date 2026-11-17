"""Inbound Message Parser and Command Router for WhatsApp."""

from __future__ import annotations

import re
from typing import Any

from infrastructure.logging import get_logger
from integrations.whatsapp.contact_manager import WhatsAppContactManager

logger = get_logger("whatsapp_inbound_handler")


class InboundCommandHandler:
    """Safely parses incoming WhatsApp messages and verifies sender authorization."""

    def __init__(self) -> None:
        self.contacts = WhatsAppContactManager.get_instance()

    def process_incoming(self, sender_phone: str, message_text: str) -> dict[str, Any]:
        """Process incoming text, check authorization, and route command."""
        text = message_text.strip()
        logger.info(f"Incoming WhatsApp message from {sender_phone}: '{text[:60]}'")

        # 1. Authorization check
        if not self.contacts.is_authorized(sender_phone):
            logger.warning(f"Unauthorized WhatsApp access attempt from '{sender_phone}'. Ignoring.")
            return {
                "authorized": False,
                "sender": sender_phone,
                "reply": "⚠️ دسترسی غیرمجاز. شماره شما برای ارسال دستور به جارویس ثبت نشده است.",
                "action": "reject",
            }

        contact = self.contacts.get_contact(sender_phone)
        can_command = contact.can_execute_commands if contact else False

        # 2. Command Parsing
        lower_txt = text.lower()

        # Help
        if lower_txt in ("help", "راهنما", "دستورات", "کمک"):
            return {
                "authorized": True,
                "sender": sender_phone,
                "action": "reply",
                "reply": (
                    "🤖 *دستورات قابل استفاده در جارویس:*\n\n"
                    "• *وضعیت* یا *status*: بررسی وضعیت سیستم و کارهای فعال\n"
                    "• *کد <دستور>*: ارسال تسک جدید به Google Antigravity\n"
                    "• *لغو <task_id>*: لغو کار در حال اجرا\n"
                ),
            }

        # Status
        if lower_txt in ("status", "وضعیت", "چطوری", "status jarvis"):
            from integrations.hub import get_integration_hub

            hub = get_integration_hub()
            overview = hub.get_status_overview()
            itgs = overview.get("integrations", {})
            agy_status = itgs.get("antigravity", {}).get("connection_state", "unknown")
            wa_status = itgs.get("whatsapp", {}).get("connection_state", "unknown")

            return {
                "authorized": True,
                "sender": sender_phone,
                "action": "reply",
                "reply": (
                    f"🟢 *وضعیت زنده جارویس:*\n\n"
                    f"• *Google Antigravity:* `{agy_status}`\n"
                    f"• *WhatsApp:* `{wa_status}`\n"
                    f"• *تعداد یکپارچه‌سازی‌های فعال:* {len(itgs)}\n"
                ),
            }

        # Antigravity Task Trigger
        agy_match = re.match(
            r"^(?:کد|انتی گراویتی|agy|code|task)\s*[:\-]?\s*(.+)$", text, re.IGNORECASE
        )
        if agy_match:
            if not can_command:
                return {
                    "authorized": True,
                    "sender": sender_phone,
                    "action": "reply",
                    "reply": "⛔ شما دسترسی لازم برای اجرای تسک‌های برنامه‌نویسی را ندارید.",
                }
            prompt_instruction = agy_match.group(1).strip()
            return {
                "authorized": True,
                "sender": sender_phone,
                "action": "execute_antigravity",
                "prompt": prompt_instruction,
                "reply": f"⏳ دستور شما دریافت شد و به Google Antigravity واگذار گردید:\n_{prompt_instruction[:100]}_",
            }

        # Cancel Task
        cancel_match = re.match(r"^(?:لغو|cancel|stop)\s*([a-zA-Z0-9_\-]+)?$", text, re.IGNORECASE)
        if cancel_match:
            if not can_command:
                return {
                    "authorized": True,
                    "sender": sender_phone,
                    "action": "reply",
                    "reply": "⛔ دسترسی لغو دستور مجاز نیست.",
                }
            tid = cancel_match.group(1)
            return {
                "authorized": True,
                "sender": sender_phone,
                "action": "cancel_task",
                "task_id": tid,
                "reply": f"دستور لغو برای {tid or 'آخرین کار'} ارسال شد.",
            }

        # Default fallback
        return {
            "authorized": True,
            "sender": sender_phone,
            "action": "echo",
            "reply": "پیام شما دریافت شد. برای مشاهده دستورات کلمه «راهنما» را ارسال کنید.",
        }
