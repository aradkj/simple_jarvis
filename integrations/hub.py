"""Universal Integration Hub for JARVIS.

Central registry, lifecycle manager, event broker, and audit logger for all JARVIS integrations.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from integrations.base import (
    HealthCheckResult,
    HealthState,
    IntegrationResult,
    UniversalIntegration,
)
from integrations.events import IntegrationEvent, IntegrationEventType

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("integration_hub")


class IntegrationHub:
    """Central singleton managing all external integrations, lifecycle, and event dispatch."""

    _instance: IntegrationHub | None = None
    _lock = threading.RLock()

    # Regex patterns for redacting sensitive secrets in logs and audit trails
    SENSITIVE_PATTERNS = [
        re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{15,}"),
        re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_\-\.]{15,})"),
        re.compile(r"(?i)(api[_\-]?key[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_\-\.]{15,})"),
        re.compile(r"(?i)(secret[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_\-\.]{15,})"),
        re.compile(r"(?i)(password[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)"),
    ]

    def __init__(self) -> None:
        self._integrations: dict[str, UniversalIntegration] = {}
        self._listeners: dict[IntegrationEventType, list[Callable[[IntegrationEvent], None]]] = (
            defaultdict(list)
        )
        self._global_listeners: list[Callable[[IntegrationEvent], None]] = []
        self._audit_log: list[dict[str, Any]] = []
        self._max_audit_entries = 1000

    @classmethod
    def get_instance(cls) -> IntegrationHub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = IntegrationHub()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset instance for testing purposes."""
        with cls._lock:
            if cls._instance:
                cls._instance.disconnect_all()
            cls._instance = None

    def register(self, integration: UniversalIntegration) -> None:
        """Register a new integration with the Hub."""
        with self._lock:
            if not isinstance(integration, UniversalIntegration):
                raise TypeError(
                    f"Integration must inherit from UniversalIntegration, got {type(integration)}"
                )

            self._integrations[integration.integration_id] = integration
            logger.info(
                f"Registered integration '{integration.name}' (id='{integration.integration_id}', v={integration.version})"
            )

            self.publish(
                IntegrationEvent(
                    event_type=IntegrationEventType.INTEGRATION_REGISTERED,
                    integration_id=integration.integration_id,
                    payload={"name": integration.name, "version": integration.version},
                )
            )

    def unregister(self, integration_id: str) -> bool:
        """Unregister an integration after cleanly disconnecting it."""
        with self._lock:
            integration = self._integrations.get(integration_id)
            if not integration:
                return False
            try:
                integration.disconnect()
            except Exception as exc:
                logger.warning(
                    f"Error disconnecting integration '{integration_id}' during unregistration: {exc}"
                )

            del self._integrations[integration_id]
            logger.info(f"Unregistered integration '{integration_id}'")
            return True

    def get_integration(self, integration_id: str) -> UniversalIntegration | None:
        """Retrieve an integration by its unique ID."""
        with self._lock:
            return self._integrations.get(integration_id)

    def list_integrations(self) -> list[UniversalIntegration]:
        """Return list of all registered integrations."""
        with self._lock:
            return list(self._integrations.values())

    def connect_all(self) -> dict[str, bool]:
        """Establish connection for all registered integrations."""
        results: dict[str, bool] = {}
        with self._lock:
            integrations = list(self._integrations.values())

        for itg in integrations:
            try:
                success = itg.connect()
                results[itg.integration_id] = success
            except Exception as exc:
                logger.error(f"Failed to connect integration '{itg.integration_id}': {exc}")
                results[itg.integration_id] = False
        return results

    def disconnect_all(self) -> None:
        """Disconnect all registered integrations."""
        with self._lock:
            integrations = list(self._integrations.values())

        for itg in integrations:
            try:
                itg.disconnect()
            except Exception as exc:
                logger.warning(f"Error disconnecting integration '{itg.integration_id}': {exc}")

    def check_all_health(self) -> dict[str, HealthCheckResult]:
        """Run health check across all registered integrations."""
        with self._lock:
            integrations = list(self._integrations.values())

        results: dict[str, HealthCheckResult] = {}
        for itg in integrations:
            try:
                res = itg.health_check()
                results[itg.integration_id] = res
            except Exception as exc:
                logger.error(f"Health check failed for '{itg.integration_id}': {exc}")
                results[itg.integration_id] = HealthCheckResult(
                    healthy=False,
                    state=HealthState.UNHEALTHY,
                    message=f"Health check exception: {exc}",
                )
        return results

    def get_status_overview(self) -> dict[str, Any]:
        """Return high-level diagnostic status overview for GUI and monitoring."""
        with self._lock:
            integrations = list(self._integrations.values())

        overview: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_integrations": len(integrations),
            "integrations": {},
        }

        for itg in integrations:
            try:
                overview["integrations"][itg.integration_id] = {
                    "id": itg.integration_id,
                    "name": itg.name,
                    "version": itg.version,
                    "connection_state": itg.connection_state.value,
                    "auth_state": itg.auth_state.value,
                    "health_state": itg.health_state.value,
                    "last_error": itg.last_error,
                    "last_connected_at": itg.last_connected_at.isoformat()
                    if itg.last_connected_at
                    else None,
                    "status_details": itg.get_status(),
                }
            except Exception as exc:
                overview["integrations"][itg.integration_id] = {
                    "id": itg.integration_id,
                    "name": itg.name,
                    "error": str(exc),
                }

        return overview

    # ------------------------------------------------------------------
    # Operation Dispatch & Security
    # ------------------------------------------------------------------

    def execute(
        self,
        integration_id: str,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        """Safely execute an operation against a registered integration with permission validation."""
        integration = self.get_integration(integration_id)
        if not integration:
            return IntegrationResult.fail(
                error=f"Integration '{integration_id}' is not registered in the Integration Hub.",
                operation=operation,
                integration_id=integration_id,
            )

        caps = integration.get_capabilities()
        op_def = caps.operations.get(operation)
        if not op_def:
            return IntegrationResult.fail(
                error=f"Operation '{operation}' is not supported by integration '{integration_id}'.",
                operation=operation,
                integration_id=integration_id,
            )

        # Validate input schema
        try:
            validated_params = integration.validate_input(operation, params)
        except Exception as exc:
            return IntegrationResult.fail(
                error=f"Input parameter validation failed for operation '{operation}': {exc}",
                operation=operation,
                integration_id=integration_id,
            )

        # Audit start
        redacted_params = self.redact_secrets(validated_params)
        self.publish(
            IntegrationEvent(
                event_type=IntegrationEventType.AUDIT_OPERATION_EXECUTED,
                integration_id=integration_id,
                operation=operation,
                payload={"params": redacted_params, "stage": "start"},
            )
        )

        # Execute
        try:
            result = integration.execute(operation, validated_params, context=context)
            if not result.integration_id:
                result.integration_id = integration_id
            if not result.operation:
                result.operation = operation

            self.publish(
                IntegrationEvent(
                    event_type=IntegrationEventType.AUDIT_OPERATION_EXECUTED,
                    integration_id=integration_id,
                    operation=operation,
                    payload={"success": result.success, "stage": "finish"},
                )
            )
            return result
        except Exception as exc:
            logger.error(f"Execution error on '{integration_id}.{operation}': {exc}", exc_info=True)
            return IntegrationResult.fail(
                error=f"Unhandled execution error: {exc}",
                operation=operation,
                integration_id=integration_id,
            )

    # ------------------------------------------------------------------
    # Event Pub/Sub & Audit
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: IntegrationEventType | None,
        callback: Callable[[IntegrationEvent], None],
    ) -> None:
        """Subscribe to a specific event type or all events if event_type is None."""
        with self._lock:
            if event_type is None:
                if callback not in self._global_listeners:
                    self._global_listeners.append(callback)
            else:
                if callback not in self._listeners[event_type]:
                    self._listeners[event_type].append(callback)

    def unsubscribe(
        self,
        event_type: IntegrationEventType | None,
        callback: Callable[[IntegrationEvent], None],
    ) -> None:
        with self._lock:
            if event_type is None:
                if callback in self._global_listeners:
                    self._global_listeners.remove(callback)
            else:
                if callback in self._listeners[event_type]:
                    self._listeners[event_type].remove(callback)

    def publish(self, event: IntegrationEvent) -> None:
        """Publish an event to all subscribers and append to audit log."""
        # Record in audit log
        with self._lock:
            audit_entry = {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type.value,
                "integration_id": event.integration_id,
                "task_id": event.task_id,
                "operation": event.operation,
                "payload": self.redact_secrets(event.payload),
            }
            self._audit_log.append(audit_entry)
            if len(self._audit_log) > self._max_audit_entries:
                self._audit_log = self._audit_log[-self._max_audit_entries :]

            listeners = list(self._listeners.get(event.event_type, []))
            globals_ = list(self._global_listeners)

        for cb in listeners + globals_:
            try:
                cb(event)
            except Exception as exc:
                logger.warning(f"Error in event listener callback for {event.event_type}: {exc}")

    def get_audit_trail(
        self, limit: int = 100, integration_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return recent audit log entries."""
        with self._lock:
            entries = self._audit_log
            if integration_id:
                entries = [e for e in entries if e.get("integration_id") == integration_id]
            return list(reversed(entries[-limit:]))

    def redact_secrets(self, data: Any) -> Any:
        """Recursively redact sensitive strings or keys from dictionaries and strings."""
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if any(
                    sec in k.lower()
                    for sec in ["token", "secret", "password", "key", "auth", "credential"]
                ):
                    redacted[k] = "******"
                else:
                    redacted[k] = self.redact_secrets(v)
            return redacted
        if isinstance(data, list):
            return [self.redact_secrets(item) for item in data]
        if isinstance(data, str):
            val = data
            for pat in self.SENSITIVE_PATTERNS:
                val = pat.sub(r"\1******", val)
            return val
        return data


def get_integration_hub() -> IntegrationHub:
    """Return the global IntegrationHub singleton."""
    return IntegrationHub.get_instance()


def initialize_default_integrations() -> IntegrationHub:
    """Register all standard first-class and foundation integrations into the Hub."""
    hub = get_integration_hub()

    try:
        from integrations.antigravity.adapter import get_antigravity_integration

        hub.register(get_antigravity_integration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register Antigravity integration: {exc}")

    try:
        from integrations.whatsapp.adapter import get_whatsapp_integration

        hub.register(get_whatsapp_integration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register WhatsApp integration: {exc}")

    try:
        from integrations.adapters.github_adapter import GitHubIntegration

        hub.register(GitHubIntegration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register GitHub integration: {exc}")

    try:
        from integrations.adapters.windows_adapter import WindowsIntegration

        hub.register(WindowsIntegration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register Windows integration: {exc}")

    try:
        from integrations.adapters.filesystem_adapter import FilesystemIntegration

        hub.register(FilesystemIntegration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register Filesystem integration: {exc}")

    try:
        from integrations.adapters.browser_adapter import BrowserIntegration

        hub.register(BrowserIntegration())
    except Exception as exc:
        logger.warning(f"Failed to auto-register Browser integration: {exc}")

    return hub
