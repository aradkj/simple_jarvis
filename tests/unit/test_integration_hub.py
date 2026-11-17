"""Unit tests for JARVIS Universal Integration Hub."""

from __future__ import annotations

import pytest

from integrations.base import (
    ConnectionState,
    HealthCheckResult,
    HealthState,
    IntegrationCapabilities,
    IntegrationResult,
    IntegrationRiskLevel,
    OperationDefinition,
    UniversalIntegration,
)
from integrations.events import IntegrationEvent, IntegrationEventType
from integrations.hub import IntegrationHub, get_integration_hub


class DummyIntegration(UniversalIntegration):
    integration_id = "dummy"
    name = "Dummy Service"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__()
        self.connected = False

    def connect(self) -> bool:
        self.connected = True
        self._connection_state = ConnectionState.CONNECTED
        self._health_state = HealthState.HEALTHY
        return True

    def disconnect(self) -> bool:
        self.connected = False
        self._connection_state = ConnectionState.DISCONNECTED
        return True

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            healthy=self.connected,
            state=HealthState.HEALTHY if self.connected else HealthState.DEGRADED,
        )

    def get_status(self) -> dict:
        return {"connected": self.connected}

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description="Dummy integration for unit testing",
            operations={
                "echo": OperationDefinition(
                    name="echo", description="Echo input", risk_level=IntegrationRiskLevel.LOW_RISK
                ),
                "fail_op": OperationDefinition(
                    name="fail_op",
                    description="Fail operation",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                ),
            },
        )

    def execute(self, operation: str, params: dict, context=None) -> IntegrationResult:
        if operation == "echo":
            return IntegrationResult.ok(
                data=params, operation=operation, integration_id=self.integration_id
            )
        if operation == "fail_op":
            return IntegrationResult.fail(
                error="Simulated failure", operation=operation, integration_id=self.integration_id
            )
        return IntegrationResult.fail(error=f"Unknown op {operation}")

    def cancel(self, operation_id: str) -> bool:
        return True


@pytest.fixture(autouse=True)
def clean_hub():
    IntegrationHub.reset_instance()
    yield
    IntegrationHub.reset_instance()


def test_hub_registration():
    hub = get_integration_hub()
    dummy = DummyIntegration()
    hub.register(dummy)

    assert hub.get_integration("dummy") is dummy
    assert len(hub.list_integrations()) == 1

    # Unregister
    assert hub.unregister("dummy") is True
    assert hub.get_integration("dummy") is None
    assert len(hub.list_integrations()) == 0


def test_hub_connect_disconnect():
    hub = get_integration_hub()
    dummy = DummyIntegration()
    hub.register(dummy)

    res = hub.connect_all()
    assert res.get("dummy") is True
    assert dummy.connection_state == ConnectionState.CONNECTED

    hub.disconnect_all()
    assert dummy.connection_state == ConnectionState.DISCONNECTED


def test_hub_health_checks():
    hub = get_integration_hub()
    dummy = DummyIntegration()
    hub.register(dummy)

    # Before connecting: degraded
    checks = hub.check_all_health()
    assert "dummy" in checks
    assert checks["dummy"].healthy is False

    # After connecting: healthy
    dummy.connect()
    checks2 = hub.check_all_health()
    assert checks2["dummy"].healthy is True


def test_hub_execute_operation():
    hub = get_integration_hub()
    dummy = DummyIntegration()
    hub.register(dummy)

    # Successful execution
    res = hub.execute("dummy", "echo", {"message": "hello"})
    assert res.success is True
    assert res.data == {"message": "hello"}

    # Failing execution
    res_fail = hub.execute("dummy", "fail_op", {})
    assert res_fail.success is False
    assert "Simulated failure" in res_fail.error

    # Non-existent operation
    res_bad = hub.execute("dummy", "non_existent", {})
    assert res_bad.success is False
    assert "not supported" in res_bad.error

    # Non-existent integration
    res_bad_itg = hub.execute("ghost", "echo", {})
    assert res_bad_itg.success is False
    assert "not registered" in res_bad_itg.error


def test_hub_secret_redaction():
    hub = get_integration_hub()
    raw = {
        "api_key": "sk-proj-1234567890abcdef",
        "auth_token": "Bearer ya29.a0AfH6SMD_very_secret_token",
        "user_email": "test@example.com",
        "nested": {
            "password": "super_secret_password_123",
            "normal_field": "visible",
        },
    }
    redacted = hub.redact_secrets(raw)
    assert redacted["api_key"] == "******"
    assert redacted["auth_token"] == "******"
    assert redacted["user_email"] == "test@example.com"
    assert redacted["nested"]["password"] == "******"
    assert redacted["nested"]["normal_field"] == "visible"


def test_hub_event_pubsub_and_audit():
    hub = get_integration_hub()
    received_events = []

    def _listener(ev: IntegrationEvent):
        received_events.append(ev)

    hub.subscribe(IntegrationEventType.TASK_CREATED, _listener)

    # Publish matching event
    ev1 = IntegrationEvent(
        event_type=IntegrationEventType.TASK_CREATED, integration_id="test", payload={"key": "val"}
    )
    hub.publish(ev1)
    assert len(received_events) == 1

    # Publish non-matching event
    ev2 = IntegrationEvent(event_type=IntegrationEventType.TASK_COMPLETED, integration_id="test")
    hub.publish(ev2)
    assert len(received_events) == 1  # Unchanged

    # Audit trail contains both
    trail = hub.get_audit_trail()
    assert len(trail) >= 2

    # Unsubscribe
    hub.unsubscribe(IntegrationEventType.TASK_CREATED, _listener)
    hub.publish(ev1)
    assert len(received_events) == 1
