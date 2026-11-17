"""Filesystem Integration Adapter for JARVIS."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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

logger = get_logger("filesystem_integration")


class FilesystemIntegration(UniversalIntegration):
    """Integration for local filesystem search and file inspection."""

    integration_id = "filesystem"
    name = "Filesystem & Search"
    version = "1.0.0"
    description = "Integration for local file search, workspace discovery, and text extraction."

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
            message="Filesystem accessible",
        )

    def get_status(self) -> dict[str, Any]:
        return {"cwd": str(Path.cwd()), "home": str(Path.home())}

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["posix_fs", "ntfs"],
            operations={
                "search_files": OperationDefinition(
                    name="search_files",
                    description="Search for files by query string or glob pattern.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                ),
                "read_file": OperationDefinition(
                    name="read_file",
                    description="Read text content of a safe file.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                ),
            },
        )

    def execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        if operation == "search_files":
            query = params.get("query", "")
            base_dir = Path(params.get("directory", Path.cwd()))
            matches = [str(p) for p in base_dir.glob(f"*{query}*")][:20]
            return IntegrationResult.ok(
                data={"matches": matches}, operation=operation, integration_id=self.integration_id
            )

        if operation == "read_file":
            path_str = params.get("path")
            if not path_str:
                return IntegrationResult.fail("Parameter 'path' required.", operation=operation)
            p = Path(path_str)
            if not p.is_file():
                return IntegrationResult.fail(f"File not found: {path_str}", operation=operation)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:10000]
                return IntegrationResult.ok(
                    data={"content": content},
                    operation=operation,
                    integration_id=self.integration_id,
                )
            except Exception as exc:
                return IntegrationResult.fail(str(exc), operation=operation)

        return IntegrationResult.fail(f"Unsupported operation '{operation}'", operation=operation)

    def cancel(self, operation_id: str) -> bool:
        return True
