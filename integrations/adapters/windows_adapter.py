"""Windows Desktop & OS Integration Adapter for JARVIS."""

from __future__ import annotations

import os
import platform
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
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

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("windows_integration")


class WindowsIntegration(UniversalIntegration):
    """Integration for Windows Desktop OS operations."""

    integration_id = "windows"
    name = "Windows OS"
    version = "11.0"
    description = (
        "Integration for native Windows application discovery, launch, and power management."
    )

    def connect(self) -> bool:
        if os.name == "nt":
            self._connection_state = ConnectionState.CONNECTED
            self._health_state = HealthState.HEALTHY
            self._last_connected_at = datetime.now(UTC)
            return True
        self._connection_state = ConnectionState.DEGRADED
        return False

    def disconnect(self) -> bool:
        self._connection_state = ConnectionState.DISCONNECTED
        return True

    def health_check(self) -> HealthCheckResult:
        is_win = os.name == "nt"
        return HealthCheckResult(
            healthy=is_win,
            state=HealthState.HEALTHY if is_win else HealthState.UNHEALTHY,
            message="Windows platform verified" if is_win else "Non-Windows OS",
            details={"platform": platform.platform(), "system": platform.system()},
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
        }

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["win32", "powershell"],
            operations={
                "get_system_info": OperationDefinition(
                    name="get_system_info",
                    description="Retrieve host system platform and OS info.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                ),
                "launch_app": OperationDefinition(
                    name="launch_app",
                    description="Launch an installed Windows desktop application.",
                    risk_level=IntegrationRiskLevel.MODERATE_RISK,
                ),
            },
        )

    def execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        if operation == "get_system_info":
            return IntegrationResult.ok(
                data=self.get_status(),
                operation=operation,
                integration_id=self.integration_id,
            )

        if operation == "launch_app":
            app_name = params.get("app_name")
            if not app_name:
                return IntegrationResult.fail("Parameter 'app_name' required.", operation=operation)
            try:
                os.startfile(app_name)
                return IntegrationResult.ok(
                    data={"launched": app_name},
                    operation=operation,
                    integration_id=self.integration_id,
                )
            except Exception as exc:
                return IntegrationResult.fail(
                    str(exc), operation=operation, integration_id=self.integration_id
                )

        return IntegrationResult.fail(
            f"Unsupported operation '{operation}'",
            operation=operation,
            integration_id=self.integration_id,
        )

    def cancel(self, operation_id: str) -> bool:
        return True
