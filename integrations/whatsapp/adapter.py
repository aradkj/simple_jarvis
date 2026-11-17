"""Universal Integration Adapter for WhatsApp (Cloud API and Linked Device)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from integrations.base import (
    AuthState,
    ConnectionState,
    HealthCheckResult,
    HealthState,
    IntegrationCapabilities,
    IntegrationResult,
    IntegrationRiskLevel,
    OperationDefinition,
    UniversalIntegration,
)
from integrations.whatsapp.cloud_provider import CloudAPIWhatsAppProvider
from integrations.whatsapp.contact_manager import WhatsAppContactManager
from integrations.whatsapp.inbound_handler import InboundCommandHandler
from integrations.whatsapp.linked_device_provider import LinkedDeviceWhatsAppProvider
from integrations.whatsapp.notification_manager import WhatsAppNotificationManager
from integrations.whatsapp.provider_base import (
    WhatsAppProvider,
    WhatsAppProviderType,
    WhatsAppSendResult,
)

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("whatsapp_integration")


class WhatsAppIntegration(UniversalIntegration):
    """First-class Universal Integration for WhatsApp Business Cloud API and Linked Devices."""

    integration_id = "whatsapp"
    name = "WhatsApp"
    version = "1.0.0"
    description = "First-class integration for WhatsApp messaging, alerts, and inbound control."

    def __init__(self) -> None:
        super().__init__()
        self.cloud_provider = CloudAPIWhatsAppProvider()
        self.linked_provider = LinkedDeviceWhatsAppProvider()
        self.active_provider_type = WhatsAppProviderType.LINKED_DEVICE
        self.contact_mgr = WhatsAppContactManager.get_instance()
        self.notification_mgr = WhatsAppNotificationManager.get_instance()
        self.inbound_handler = InboundCommandHandler()
        self._lock = threading.RLock()

    @property
    def current_provider(self) -> WhatsAppProvider:
        with self._lock:
            if self.active_provider_type == WhatsAppProviderType.CLOUD_API:
                return self.cloud_provider
            return self.linked_provider

    def set_provider_type(self, provider_type: WhatsAppProviderType) -> None:
        """Switch active WhatsApp provider (Cloud API vs Linked Device)."""
        with self._lock:
            self.active_provider_type = provider_type
            logger.info(f"Switched active WhatsApp provider to: {provider_type.value}")
            self.connect()

    def connect(self) -> bool:
        """Connect active WhatsApp provider."""
        self._connection_state = ConnectionState.CONNECTING
        try:
            ok = self.current_provider.connect()
            if ok:
                self._connection_state = ConnectionState.CONNECTED
                self._auth_state = AuthState.AUTHENTICATED
                self._health_state = HealthState.HEALTHY
                self._last_connected_at = datetime.now(UTC)
                logger.info("WhatsApp integration connected.")
                # Automatically flush queued offline notifications upon connection
                self.flush_offline_queue()
                return True
            else:
                self._connection_state = ConnectionState.DISCONNECTED
                self._auth_state = AuthState.UNAUTHENTICATED
                self._health_state = HealthState.DEGRADED
                return False
        except Exception as exc:
            self._connection_state = ConnectionState.ERROR
            self._health_state = HealthState.UNHEALTHY
            self._last_error = str(exc)
            logger.error(f"WhatsApp connect error: {exc}")
            return False

    def disconnect(self) -> bool:
        """Disconnect active provider cleanly."""
        try:
            self.current_provider.disconnect()
            self._connection_state = ConnectionState.DISCONNECTED
            self._auth_state = AuthState.UNAUTHENTICATED
            return True
        except Exception as exc:
            logger.warning(f"Error disconnecting WhatsApp: {exc}")
            return False

    def health_check(self) -> HealthCheckResult:
        """Verify provider connection state and recipient readiness."""
        status = self.current_provider.get_status()
        is_conn = self.current_provider.is_connected()
        state = HealthState.HEALTHY if is_conn else HealthState.DEGRADED

        return HealthCheckResult(
            healthy=is_conn,
            state=state,
            message=f"WhatsApp {self.active_provider_type.value}: {status.get('status', 'unknown')}",
            details=status,
        )

    def get_status(self) -> dict[str, Any]:
        """Diagnostic status for UI."""
        provider_status = self.current_provider.get_status()
        return {
            "active_provider": self.active_provider_type.value,
            "connection_state": self._connection_state.value,
            "provider_status": provider_status,
            "offline_queue_count": len(self.notification_mgr._offline_queue),
            "authorized_contacts_count": len(self.contact_mgr.list_authorized_contacts()),
        }

    def is_ready_to_send(self) -> bool:
        return self.current_provider.is_connected()

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["whatsapp_cloud_api", "whatsapp_multi_device"],
            operations={
                "send_message": OperationDefinition(
                    name="send_message",
                    description="Send text message to an authorized WhatsApp phone number.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=30.0,
                ),
                "send_task_notification": OperationDefinition(
                    name="send_task_notification",
                    description="Send formatted task completion/failure alert with deduplication.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=30.0,
                ),
                "pair_qr": OperationDefinition(
                    name="pair_qr",
                    description="Generate or refresh Linked-Device QR pairing code.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=15.0,
                ),
                "confirm_pairing": OperationDefinition(
                    name="confirm_pairing",
                    description="Confirm device pairing with phone number.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=15.0,
                ),
                "flush_offline_queue": OperationDefinition(
                    name="flush_offline_queue",
                    description="Deliver pending offline queued messages.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=45.0,
                ),
                "list_contacts": OperationDefinition(
                    name="list_contacts",
                    description="List authorized contacts and permissions.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                    timeout_seconds=5.0,
                ),
                "add_authorized_contact": OperationDefinition(
                    name="add_authorized_contact",
                    description="Add a phone number to the authorized allowlist.",
                    risk_level=IntegrationRiskLevel.MODERATE_RISK,
                    timeout_seconds=10.0,
                ),
            },
        )

    def execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        op_map = {
            "send_message": self._execute_send_message,
            "send_task_notification": self._execute_send_task_notification,
            "pair_qr": self._execute_pair_qr,
            "confirm_pairing": self._execute_confirm_pairing,
            "flush_offline_queue": self._execute_flush_offline_queue,
            "list_contacts": self._execute_list_contacts,
            "add_authorized_contact": self._execute_add_contact,
        }

        handler = op_map.get(operation)
        if not handler:
            return IntegrationResult.fail(
                f"Unsupported operation '{operation}'", operation=operation
            )

        return handler(params, context)

    def cancel(self, operation_id: str) -> bool:
        return True

    # ------------------------------------------------------------------
    # Operation Handlers
    # ------------------------------------------------------------------

    def send_message(self, recipient: str, text: str) -> WhatsAppSendResult:
        """Send message directly with recipient resolution and contact verification."""
        try:
            target_phone = self.contact_mgr.resolve_recipient(recipient)
        except Exception as exc:
            return WhatsAppSendResult(
                success=False, error=f"Recipient resolution error: {exc}", recipient=recipient
            )

        if not self.is_ready_to_send():
            # Enqueue in offline queue
            self.notification_mgr.enqueue(target_phone, text)
            return WhatsAppSendResult(
                success=True,
                recipient=target_phone,
                message_id="offline_queued",
                details={"queued": True, "notice": "WhatsApp offline; message stored in queue."},
            )

        res = self.current_provider.send_text_message(target_phone, text)
        return res

    def _execute_send_message(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        recipient = params.get("recipient")
        text = params.get("text")
        if not recipient or not text:
            return IntegrationResult.fail(
                "Both 'recipient' and 'text' parameters are required.", operation="send_message"
            )

        res = self.send_message(recipient, text)
        if res.success:
            return IntegrationResult.ok(
                data={
                    "message_id": res.message_id,
                    "recipient": res.recipient,
                    "details": res.details,
                },
                operation="send_message",
                integration_id=self.integration_id,
            )
        return IntegrationResult.fail(
            error=res.error or "Failed to deliver WhatsApp message.",
            operation="send_message",
            integration_id=self.integration_id,
        )

    def _execute_send_task_notification(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        recipient = params.get("recipient", "خودم")
        task_data = params.get("task")
        if not task_data:
            return IntegrationResult.fail(
                "Parameter 'task' is required.", operation="send_task_notification"
            )

        # Reconstruct or parse task record
        from integrations.antigravity.lifecycle import AntigravityTaskRecord, TaskLifecycleState

        if isinstance(task_data, AntigravityTaskRecord):
            task_rec = task_data
        elif isinstance(task_data, dict):
            task_rec = AntigravityTaskRecord(
                task_id=task_data.get("task_id", "task-unknown"),
                prompt=task_data.get("prompt", ""),
                workspace_path=task_data.get("workspace_path", ""),
                state=TaskLifecycleState(task_data.get("state", "completed")),
                error_message=task_data.get("error_message"),
            )
        else:
            return IntegrationResult.fail(
                "Invalid task data format.", operation="send_task_notification"
            )

        formatted_msg = self.notification_mgr.format_task_notification(task_rec)

        target_phone = self.contact_mgr.resolve_recipient(recipient)
        if self.notification_mgr.is_duplicate(target_phone, formatted_msg):
            logger.info(f"Suppressed duplicate task notification for {target_phone}")
            return IntegrationResult.ok(
                data={"status": "duplicate_suppressed"},
                operation="send_task_notification",
                integration_id=self.integration_id,
            )

        res = self.send_message(target_phone, formatted_msg)
        return IntegrationResult.ok(
            data={"status": "sent" if res.success else "queued", "recipient": target_phone},
            operation="send_task_notification",
            integration_id=self.integration_id,
        )

    def _execute_pair_qr(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        qr_data = self.linked_provider.generate_pairing_qr()
        return IntegrationResult.ok(
            data={"qr_code": qr_data, "ttl_seconds": self.linked_provider._qr_ttl_seconds},
            operation="pair_qr",
            integration_id=self.integration_id,
        )

    def _execute_confirm_pairing(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        phone = params.get("phone", "+989120000000")
        success = self.linked_provider.confirm_pairing(phone)
        if success:
            self._connection_state = ConnectionState.CONNECTED
            self._auth_state = AuthState.AUTHENTICATED
            self._health_state = HealthState.HEALTHY
            self.flush_offline_queue()
        return IntegrationResult.ok(
            data={"paired": success, "phone": phone}, operation="confirm_pairing"
        )

    def _execute_flush_offline_queue(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        sent = self.flush_offline_queue()
        return IntegrationResult.ok(data={"flushed_count": sent}, operation="flush_offline_queue")

    def flush_offline_queue(self) -> int:
        return self.notification_mgr.flush_queue(self)

    def _execute_list_contacts(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        contacts = [c.to_dict() for c in self.contact_mgr.list_authorized_contacts()]
        return IntegrationResult.ok(data=contacts, operation="list_contacts")

    def _execute_add_contact(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        phone = params.get("phone")
        name = params.get("name")
        role = params.get("role", "user")
        can_cmd = params.get("can_execute_commands", False)
        if not phone or not name:
            return IntegrationResult.fail(
                "Both 'phone' and 'name' are required.", operation="add_authorized_contact"
            )

        c = self.contact_mgr.add_authorized_contact(
            phone, name, role=role, can_execute_commands=can_cmd
        )
        return IntegrationResult.ok(data=c.to_dict(), operation="add_authorized_contact")


_whatsapp_instance: WhatsAppIntegration | None = None


def get_whatsapp_integration() -> WhatsAppIntegration:
    global _whatsapp_instance
    if _whatsapp_instance is None:
        _whatsapp_instance = WhatsAppIntegration()
    return _whatsapp_instance
