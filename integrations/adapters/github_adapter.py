"""GitHub and Git Integration Adapter for JARVIS."""

from __future__ import annotations

import shutil
import subprocess
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

logger = get_logger("github_integration")


class GitHubIntegration(UniversalIntegration):
    """Integration for Git version control and GitHub CLI."""

    integration_id = "github"
    name = "GitHub & Git"
    version = "1.0.0"
    description = "Integration for local Git repository inspection and GitHub CLI interactions."

    def __init__(self) -> None:
        super().__init__()
        self._git_path = shutil.which("git")
        self._gh_path = shutil.which("gh")

    def connect(self) -> bool:
        self._git_path = shutil.which("git")
        self._gh_path = shutil.which("gh")
        if self._git_path:
            self._connection_state = ConnectionState.CONNECTED
            self._health_state = HealthState.HEALTHY
            self._last_connected_at = datetime.now(UTC)
            return True
        self._connection_state = ConnectionState.DEGRADED
        self._health_state = HealthState.DEGRADED
        return False

    def disconnect(self) -> bool:
        self._connection_state = ConnectionState.DISCONNECTED
        return True

    def health_check(self) -> HealthCheckResult:
        git_ok = bool(shutil.which("git"))
        gh_ok = bool(shutil.which("gh"))
        healthy = git_ok
        state = HealthState.HEALTHY if healthy else HealthState.DEGRADED
        return HealthCheckResult(
            healthy=healthy,
            state=state,
            message="Git available" if git_ok else "Git not found in PATH",
            details={"git_available": git_ok, "gh_cli_available": gh_ok},
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "git_path": self._git_path,
            "gh_path": self._gh_path,
            "connected": self._connection_state == ConnectionState.CONNECTED,
        }

    def get_capabilities(self) -> IntegrationCapabilities:
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["git_cli", "gh_cli"],
            operations={
                "git_status": OperationDefinition(
                    name="git_status",
                    description="Get status of repository working tree.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                ),
                "git_diff": OperationDefinition(
                    name="git_diff",
                    description="Inspect diff of modified files in repository.",
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
        repo_path = params.get("workspace_path") or Path.cwd()
        repo = Path(repo_path).resolve()

        if operation == "git_status":
            try:
                proc = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return IntegrationResult.ok(
                    data={"status": proc.stdout},
                    operation=operation,
                    integration_id=self.integration_id,
                )
            except Exception as exc:
                return IntegrationResult.fail(
                    str(exc), operation=operation, integration_id=self.integration_id
                )

        if operation == "git_diff":
            try:
                proc = subprocess.run(
                    ["git", "diff"], cwd=str(repo), capture_output=True, text=True, timeout=15
                )
                return IntegrationResult.ok(
                    data={"diff": proc.stdout},
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
