"""Notification Manager with Deduplication and Offline Queuing for WhatsApp."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir
from integrations.antigravity.lifecycle import AntigravityTaskRecord, TaskLifecycleState

if TYPE_CHECKING:
    from integrations.whatsapp.adapter import WhatsAppIntegration

logger = get_logger("whatsapp_notification_mgr")


@dataclass
class QueuedNotification:
    queue_id: str
    recipient: str
    message: str
    task_id: str | None = None
    priority: int = 1  # 1 = normal, 2 = high, 0 = low
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "recipient": self.recipient,
            "message": self.message,
            "task_id": self.task_id,
            "priority": self.priority,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat(),
        }


class WhatsAppNotificationManager:
    """Dispatches Antigravity task notifications, deduplicates alerts, and manages offline queues."""

    _instance: WhatsAppNotificationManager | None = None
    _lock = threading.RLock()

    def __init__(self, queue_file: Path | None = None) -> None:
        self.queue_file = queue_file or (get_data_dir() / "whatsapp_offline_queue.json")
        self._offline_queue: list[QueuedNotification] = []
        self._recent_hashes: dict[str, float] = {}  # hash -> timestamp
        self._cooldown_seconds: float = 30.0  # deduplication cooldown
        self._load_queue()

    @classmethod
    def get_instance(cls) -> WhatsAppNotificationManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = WhatsAppNotificationManager()
            return cls._instance

    def _hash_content(self, recipient: str, text: str) -> str:
        key = f"{recipient.strip()}::{text.strip()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def is_duplicate(self, recipient: str, text: str) -> bool:
        """Check if identical notification was sent within cooldown period."""
        h = self._hash_content(recipient, text)
        now = time.time()
        with self._lock:
            last_time = self._recent_hashes.get(h)
            if last_time and (now - last_time) < self._cooldown_seconds:
                return True
            # Clean expired hashes
            self._recent_hashes = {
                k: v for k, v in self._recent_hashes.items() if (now - v) < self._cooldown_seconds
            }
            self._recent_hashes[h] = now
            return False

    def _load_queue(self) -> None:
        if not self.queue_file.exists():
            return
        with self._lock:
            try:
                data = json.loads(self.queue_file.read_text(encoding="utf-8"))
                self._offline_queue = [
                    QueuedNotification(
                        queue_id=d["queue_id"],
                        recipient=d["recipient"],
                        message=d["message"],
                        task_id=d.get("task_id"),
                        priority=d.get("priority", 1),
                        attempts=d.get("attempts", 0),
                        created_at=datetime.fromisoformat(d["created_at"]),
                    )
                    for d in data
                ]
                logger.info(f"Loaded {len(self._offline_queue)} offline WhatsApp notifications.")
            except Exception as exc:
                logger.debug(f"Failed to load WhatsApp offline queue: {exc}")

    def _save_queue(self) -> None:
        with self._lock:
            try:
                self.queue_file.parent.mkdir(parents=True, exist_ok=True)
                payload = [n.to_dict() for n in self._offline_queue]
                self.queue_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.error(f"Failed to persist offline WhatsApp queue: {exc}")

    def enqueue(
        self, recipient: str, message: str, task_id: str | None = None, priority: int = 1
    ) -> str:
        """Add notification to persistent offline queue."""
        import uuid

        q_id = f"wq-{uuid.uuid4().hex[:8]}"
        q_item = QueuedNotification(
            queue_id=q_id,
            recipient=recipient,
            message=message,
            task_id=task_id,
            priority=priority,
        )
        with self._lock:
            self._offline_queue.append(q_item)
            self._save_queue()
            logger.info(f"Enqueued offline WhatsApp notification '{q_id}' for {recipient}")
        return q_id

    def flush_queue(self, adapter: WhatsAppIntegration) -> int:
        """Attempt to send all queued messages if WhatsApp is connected."""
        if not adapter.is_ready_to_send():
            logger.debug("Cannot flush offline queue: WhatsApp adapter is not connected.")
            return 0

        with self._lock:
            items_to_send = list(self._offline_queue)

        sent_count = 0
        remaining: list[QueuedNotification] = []

        for item in items_to_send:
            try:
                res = adapter.send_message(recipient=item.recipient, text=item.message)
                if res.success:
                    sent_count += 1
                    logger.info(f"Flushed queued notification {item.queue_id} to {item.recipient}")
                else:
                    item.attempts += 1
                    if item.attempts < 5:
                        remaining.append(item)
                    else:
                        logger.warning(
                            f"Discarding notification {item.queue_id} after {item.attempts} failed attempts."
                        )
            except Exception as exc:
                logger.error(f"Error flushing notification {item.queue_id}: {exc}")
                item.attempts += 1
                remaining.append(item)

        with self._lock:
            self._offline_queue = remaining
            self._save_queue()

        return sent_count

    def format_task_notification(self, task: AntigravityTaskRecord) -> str:
        """Format a clear, professional notification message for Antigravity tasks."""
        duration_sec = int(task.duration_seconds())
        min_part, sec_part = divmod(duration_sec, 60)
        time_str = f"{min_part}m {sec_part}s" if min_part else f"{sec_part}s"

        if task.state == TaskLifecycleState.COMPLETED:
            msg = (
                f"✅ *JARVIS — Task Completed Successfully*\n\n"
                f"• *Task ID:* `{task.task_id}`\n"
                f"• *Duration:* {time_str}\n"
                f"• *Workspace:* `{task.workspace_path}`\n"
                f"• *Prompt:* {task.prompt[:120]}\n"
            )
            if task.verification:
                v = task.verification
                msg += f"• *Verification:* {'PASSED' if v.verified else 'WARNING'}\n"
                if v.git_changed_files:
                    msg += f"• *Changed Files:* {', '.join(v.git_changed_files[:5])}\n"
                if v.tests_executed:
                    msg += f"• *Tests:* {'All passed' if v.tests_passed else 'Failed'}\n"
            return msg.strip()

        elif task.state == TaskLifecycleState.FAILED:
            err = task.error_message or "Unknown failure"
            return (
                f"❌ *JARVIS — Task Failed*\n\n"
                f"• *Task ID:* `{task.task_id}`\n"
                f"• *Duration:* {time_str}\n"
                f"• *Workspace:* `{task.workspace_path}`\n"
                f"• *Error:* {err}\n"
                f"• *Prompt:* {task.prompt[:120]}\n"
            ).strip()

        elif task.state == TaskLifecycleState.CANCELLED:
            return (
                f"⚠️ *JARVIS — Task Cancelled*\n\n"
                f"• *Task ID:* `{task.task_id}`\n"
                f"• *Workspace:* `{task.workspace_path}`\n"
            ).strip()

        return f"ℹ️ *JARVIS Task Update*: Task `{task.task_id}` is now `{task.state.value}`."
