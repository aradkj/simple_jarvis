"""Browser Integration Adapter for JARVIS."""

from __future__ import annotations

import webbrowser
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

logger = get_logger("browser_integration")


class BrowserIntegration(UniversalIntegration):
    """Integration for web browsing and web application navigation."""

    integration_id = "browser"
    name = "Web Browser"
    version = "1.0.0"
    description = "Integration for web browsing, URL opening, and web application access."

    def connect(self) -> bool:
        self._connection_state = ConnectionState.CONNECTED
        self._health_state = HealthState.HEALTHY
        self._last_connected_at = datetime.now(UTC)
        return True

    def disconnect(self) -> bool:
        self._connection_state = ConnectionState.DISCONNECTED
        return True

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            healthy=True,
            state=HealthState.HEALTHY,
            message="Browser automation available",
        )

    def get_status(self) -> dict[str, Any]:
        return {"default_browser": "System Default"}

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["http", "https"],
            operations={
                "open_url": OperationDefinition(
                    name="open_url",
                    description="Open a URL in the user's default browser.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                ),
            },
        )

    def execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        if operation == "open_url":
            url = params.get("url")
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                return IntegrationResult.fail("Valid HTTP/HTTPS URL required.", operation=operation)
            try:
                webbrowser.open(url)
                return IntegrationResult.ok(
                    data={"opened": url}, operation=operation, integration_id=self.integration_id
                )
            except Exception as exc:
                return IntegrationResult.fail(str(exc), operation=operation)

        return IntegrationResult.fail(f"Unsupported operation '{operation}'", operation=operation)

    def cancel(self, operation_id: str) -> bool:
        return True
