"""Contact and Authorized Sender Manager for WhatsApp Integration."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config import get_settings
from infrastructure.logging import get_logger

logger = get_logger("whatsapp_contact_manager")


class ContactPermissionError(Exception):
    """Raised when an unauthorized phone number attempts an action."""


@dataclass
class AuthorizedContact:
    phone: str
    name: str
    role: str = "user"  # "admin", "user", "notify_only"
    can_execute_commands: bool = False
    added_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone": self.phone,
            "name": self.name,
            "role": self.role,
            "can_execute_commands": self.can_execute_commands,
            "added_at": self.added_at.isoformat(),
        }


class WhatsAppContactManager:
    """Manages phone normalization, self resolution, and strict authorized sender checks."""

    _instance: WhatsAppContactManager | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self.settings = get_settings()
        self._authorized_contacts: dict[str, AuthorizedContact] = {}
        self._init_defaults()

    @classmethod
    def get_instance(cls) -> WhatsAppContactManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = WhatsAppContactManager()
            return cls._instance

    def _init_defaults(self) -> None:
        """Initialize with self contact if configured."""
        self_phone = getattr(self.settings, "whatsapp_self_phone_number", "")
        if self_phone:
            try:
                norm = self.normalize_phone(self_phone)
                self._authorized_contacts[norm] = AuthorizedContact(
                    phone=norm,
                    name="Owner / Self",
                    role="admin",
                    can_execute_commands=True,
                )
            except Exception as exc:
                logger.warning(f"Could not normalize default self phone '{self_phone}': {exc}")

    def normalize_phone(self, phone: str) -> str:
        """Normalize phone number to international E.164 format (+989..., +1...)."""
        clean = re.sub(r"[\s\-\(\)\.]", "", str(phone)).strip()
        if not clean:
            raise ValueError("Phone number cannot be empty.")

        # Iranian phone normalization
        if clean.startswith("0098"):
            clean = "+" + clean[2:]
        elif clean.startswith("09") and len(clean) == 11:
            clean = "+98" + clean[1:]
        elif clean.startswith("9") and len(clean) == 10:
            clean = "+98" + clean
        elif not clean.startswith("+"):
            clean = "+" + clean if clean.startswith("1") and len(clean) == 11 else "+" + clean

        return clean

    def resolve_recipient(self, recipient_hint: str) -> str:
        """Resolve keywords like 'خودم', 'me', 'self' to configured user phone."""
        clean = recipient_hint.strip().lower()
        if clean in ("خودم", "me", "self", "owner", "admin"):
            self_phone = getattr(self.settings, "whatsapp_self_phone_number", "")
            if not self_phone:
                # Check authorized contacts for admin
                for contact in self._authorized_contacts.values():
                    if contact.role == "admin":
                        return contact.phone
                raise ValueError(
                    "Self phone number is not configured in settings or authorized contacts."
                )
            return self.normalize_phone(self_phone)

        # Check by name in authorized contacts
        for norm_phone, contact in self._authorized_contacts.items():
            if contact.name.lower() == clean:
                return norm_phone

        return self.normalize_phone(recipient_hint)

    def add_authorized_contact(
        self,
        phone: str,
        name: str,
        role: str = "user",
        can_execute_commands: bool = False,
    ) -> AuthorizedContact:
        """Add or update an authorized contact."""
        norm = self.normalize_phone(phone)
        with self._lock:
            contact = AuthorizedContact(
                phone=norm,
                name=name,
                role=role,
                can_execute_commands=can_execute_commands,
            )
            self._authorized_contacts[norm] = contact
            logger.info(
                f"Added authorized contact: {name} ({norm}), role={role}, can_execute={can_execute_commands}"
            )
            return contact

    def remove_authorized_contact(self, phone: str) -> bool:
        """Remove a contact from the allowlist."""
        norm = self.normalize_phone(phone)
        with self._lock:
            if norm in self._authorized_contacts:
                del self._authorized_contacts[norm]
                logger.info(f"Removed authorized contact: {norm}")
                return True
            return False

    def is_authorized(self, phone: str, require_command_permission: bool = False) -> bool:
        """Strict validation of sender authorization."""
        try:
            norm = self.normalize_phone(phone)
        except Exception:
            return False

        with self._lock:
            contact = self._authorized_contacts.get(norm)
            if not contact:
                return False
            return not (require_command_permission and not contact.can_execute_commands)

    def get_contact(self, phone: str) -> AuthorizedContact | None:
        try:
            norm = self.normalize_phone(phone)
            with self._lock:
                return self._authorized_contacts.get(norm)
        except Exception:
            return None

    def list_authorized_contacts(self) -> list[AuthorizedContact]:
        with self._lock:
            return list(self._authorized_contacts.values())
