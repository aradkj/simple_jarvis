"""Universal Integration Adapter for Google Antigravity (CLI and IDE)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from integrations.antigravity.cli import AntigravityCLI
from integrations.antigravity.ide import AntigravityIDEManager
from integrations.antigravity.lifecycle import (
    AntigravityLifecycleTracker,
    TaskLifecycleState,
)
from integrations.antigravity.verifier import AntigravityVerifier, TaskVerificationResult
from integrations.antigravity.workspace_lock import WorkspaceLockManager
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

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("antigravity_integration")


class AntigravityIntegration(UniversalIntegration):
    """First-class Universal Integration for Google Antigravity CLI and IDE."""

    integration_id = "antigravity"
    name = "Google Antigravity"
    version = "1.5.9"
    description = "First-class integration for Google Antigravity coding agent CLI and IDE."

    def __init__(self) -> None:
        super().__init__()
        self.cli = AntigravityCLI()
        self.ide = AntigravityIDEManager()
        self.tracker = AntigravityLifecycleTracker.get_instance()
        self.lock_mgr = WorkspaceLockManager.get_instance()
        self._connected = False

    def connect(self) -> bool:
        """Establish readiness and discover CLI and IDE installations."""
        self._connection_state = ConnectionState.CONNECTING
        try:
            cli_ok = self.cli.is_available()
            if cli_ok:
                self._connection_state = ConnectionState.CONNECTED
                self._auth_state = AuthState.AUTHENTICATED
                self._health_state = HealthState.HEALTHY
                self._last_connected_at = datetime.now(UTC)
                self._connected = True
                logger.info("Antigravity integration connected successfully.")
                return True
            else:
                self._connection_state = ConnectionState.DEGRADED
                self._health_state = HealthState.DEGRADED
                self._last_error = "agy.exe executable not found in PATH or standard locations."
                logger.warning(self._last_error)
                return False
        except Exception as exc:
            self._connection_state = ConnectionState.ERROR
            self._health_state = HealthState.UNHEALTHY
            self._last_error = str(exc)
            logger.error(f"Failed to connect Antigravity integration: {exc}")
            return False

    def disconnect(self) -> bool:
        """Cleanly disconnect Antigravity integration and cancel active processes."""
        self._connection_state = ConnectionState.DISCONNECTED
        self._connected = False
        return True

    def health_check(self) -> HealthCheckResult:
        """Verify availability of agy CLI, version, and IDE configuration."""
        cli_available = self.cli.is_available()
        version = self.cli.detect_version() if cli_available else "unavailable"
        ide_info = self.ide.discover_ide()

        healthy = cli_available
        state = HealthState.HEALTHY if healthy else HealthState.DEGRADED

        return HealthCheckResult(
            healthy=healthy,
            state=state,
            message="Antigravity CLI available" if healthy else "Antigravity CLI not found",
            details={
                "cli_installed": cli_available,
                "cli_version": version,
                "cli_path": str(self.cli.locate_executable()) if cli_available else None,
                "ide_installed": ide_info.get("installed", False),
                "ide_path": ide_info.get("executable_path"),
            },
        )

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status information for GUI and monitoring."""
        cli_ok = self.cli.is_available()
        return {
            "connected": self._connected,
            "connection_state": self._connection_state.value,
            "cli_available": cli_ok,
            "cli_version": self.cli.detect_version() if cli_ok else None,
            "ide_discovery": self.ide.discover_ide(),
            "global_hooks": self.ide.get_hooks_status(),
            "active_tasks_count": len(
                [
                    t
                    for t in self.tracker.list_tasks()
                    if t.state in (TaskLifecycleState.STARTED, TaskLifecycleState.ACCEPTED)
                ]
            ),
        }

    def get_capabilities(self) -> IntegrationCapabilities:
        """Declare supported operations, input schemas, and risk levels."""
        return IntegrationCapabilities(
            integration_id=self.integration_id,
            name=self.name,
            version=self.version,
            description=self.description,
            supported_protocols=["cli", "ipc_hooks"],
            operations={
                "delegate_task": OperationDefinition(
                    name="delegate_task",
                    description="Dispatch a coding, debugging, or refactoring task to Google Antigravity.",
                    risk_level=IntegrationRiskLevel.MODERATE_RISK,
                    required_permissions=["coding_agent:execute"],
                    timeout_seconds=600.0,
                ),
                "verify_workspace": OperationDefinition(
                    name="verify_workspace",
                    description="Run independent verification (git diff, tests, lint) on a workspace.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                    required_permissions=["coding_agent:verify"],
                    timeout_seconds=120.0,
                ),
                "get_task_status": OperationDefinition(
                    name="get_task_status",
                    description="Check status, logs, and verification of an Antigravity task.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
                    timeout_seconds=10.0,
                ),
                "cancel_task": OperationDefinition(
                    name="cancel_task",
                    description="Cancel an active running Antigravity task.",
                    risk_level=IntegrationRiskLevel.LOW_RISK,
                    timeout_seconds=15.0,
                ),
                "install_ide_hooks": OperationDefinition(
                    name="install_ide_hooks",
                    description="Install JARVIS lifecycle hooks into Antigravity IDE configuration.",
                    risk_level=IntegrationRiskLevel.MODERATE_RISK,
                    timeout_seconds=15.0,
                ),
                "uninstall_ide_hooks": OperationDefinition(
                    name="uninstall_ide_hooks",
                    description="Remove JARVIS lifecycle hooks from Antigravity IDE configuration.",
                    risk_level=IntegrationRiskLevel.MODERATE_RISK,
                    timeout_seconds=15.0,
                ),
                "get_ide_status": OperationDefinition(
                    name="get_ide_status",
                    description="Query Antigravity IDE presence and hook installation.",
                    risk_level=IntegrationRiskLevel.READ_ONLY,
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
        """Dispatch operation execution."""
        op_map = {
            "delegate_task": self._execute_delegate_task,
            "verify_workspace": self._execute_verify_workspace,
            "get_task_status": self._execute_get_task_status,
            "cancel_task": self._execute_cancel_task,
            "install_ide_hooks": self._execute_install_ide_hooks,
            "uninstall_ide_hooks": self._execute_uninstall_ide_hooks,
            "get_ide_status": self._execute_get_ide_status,
        }

        handler = op_map.get(operation)
        if not handler:
            return IntegrationResult.fail(
                error=f"Unsupported operation '{operation}'",
                operation=operation,
                integration_id=self.integration_id,
            )

        return handler(params, context)

    def cancel(self, operation_id: str) -> bool:
        """Cancel a running task by task_id."""
        return self.cli.cancel_task(operation_id)

    # ------------------------------------------------------------------
    # Operation Handlers
    # ------------------------------------------------------------------

    def _execute_delegate_task(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        prompt = params.get("prompt")
        if not prompt:
            return IntegrationResult.fail(
                "Parameter 'prompt' is required.", operation="delegate_task"
            )

        workspace_raw = params.get("workspace_path") or Path.cwd()
        workspace = Path(workspace_raw).resolve()
        if not workspace.is_dir():
            return IntegrationResult.fail(
                f"Workspace path does not exist: {workspace}", operation="delegate_task"
            )

        model = params.get("model", "inherit")
        auto_verify = params.get("auto_verify", True)
        timeout_seconds = float(params.get("timeout_seconds", 300.0))

        # Create task record
        task = self.tracker.create_task(
            prompt=prompt,
            workspace_path=workspace,
            model=model,
            metadata={"auto_verify": auto_verify},
        )

        # Acquire workspace lock
        if not self.lock_mgr.acquire(workspace, task.task_id, timeout=2.0):
            self.tracker.transition(
                task.task_id, TaskLifecycleState.FAILED, {"error": "Workspace is currently locked"}
            )
            return IntegrationResult.fail(
                error=f"Workspace '{workspace}' is currently locked by another task.",
                operation="delegate_task",
                task_id=task.task_id,
            )

        try:
            self.tracker.transition(task.task_id, TaskLifecycleState.ACCEPTED)

            # Execute via CLI
            exit_code, output_lines = self.cli.execute_task(
                task_id=task.task_id,
                prompt=prompt,
                workspace=workspace,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            task.exit_code = exit_code

            # Verification
            verification_res: TaskVerificationResult | None = None
            if auto_verify:
                verifier = AntigravityVerifier(workspace)
                verification_res = verifier.verify(run_tests=True, run_linter=True)
                task.verification = verification_res

            if exit_code == 0 and (verification_res is None or verification_res.verified):
                self.tracker.transition(task.task_id, TaskLifecycleState.COMPLETED)
                return IntegrationResult.ok(
                    data={
                        "task_id": task.task_id,
                        "state": TaskLifecycleState.COMPLETED.value,
                        "exit_code": exit_code,
                        "verification": verification_res.to_dict() if verification_res else None,
                        "workspace": str(workspace),
                    },
                    operation="delegate_task",
                    integration_id=self.integration_id,
                    task_id=task.task_id,
                )
            else:
                err_msg = f"Task completed with exit_code {exit_code}"
                if verification_res and not verification_res.verified:
                    err_msg += f" but verification failed: {verification_res.message}"
                self.tracker.transition(task.task_id, TaskLifecycleState.FAILED, {"error": err_msg})
                return IntegrationResult.fail(
                    error=err_msg,
                    operation="delegate_task",
                    integration_id=self.integration_id,
                    task_id=task.task_id,
                    verification=verification_res.to_dict() if verification_res else None,
                )

        finally:
            self.lock_mgr.release(workspace, task.task_id)

    def _execute_verify_workspace(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        workspace_raw = params.get("workspace_path") or Path.cwd()
        workspace = Path(workspace_raw).resolve()
        if not workspace.is_dir():
            return IntegrationResult.fail(
                f"Workspace path does not exist: {workspace}", operation="verify_workspace"
            )

        run_tests = params.get("run_tests", True)
        run_linter = params.get("run_linter", True)

        verifier = AntigravityVerifier(workspace)
        res = verifier.verify(run_tests=run_tests, run_linter=run_linter)

        return IntegrationResult.ok(
            data=res.to_dict(),
            operation="verify_workspace",
            integration_id=self.integration_id,
        )

    def _execute_get_task_status(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        task_id = params.get("task_id")
        if not task_id:
            return IntegrationResult.fail(
                "Parameter 'task_id' is required.", operation="get_task_status"
            )

        task = self.tracker.get_task(task_id)
        if not task:
            return IntegrationResult.fail(
                f"Task '{task_id}' not found.", operation="get_task_status"
            )

        return IntegrationResult.ok(data=task.to_dict(), operation="get_task_status")

    def _execute_cancel_task(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        task_id = params.get("task_id")
        if not task_id:
            return IntegrationResult.fail(
                "Parameter 'task_id' is required.", operation="cancel_task"
            )

        success = self.cancel(task_id)
        return IntegrationResult.ok(
            data={"cancelled": success, "task_id": task_id}, operation="cancel_task"
        )

    def _execute_install_ide_hooks(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        workspace_path = params.get("workspace_path")
        success = self.ide.install_hooks(workspace_path)
        return IntegrationResult.ok(data={"installed": success}, operation="install_ide_hooks")

    def _execute_uninstall_ide_hooks(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        workspace_path = params.get("workspace_path")
        success = self.ide.uninstall_hooks(workspace_path)
        return IntegrationResult.ok(data={"uninstalled": success}, operation="uninstall_ide_hooks")

    def _execute_get_ide_status(
        self, params: dict[str, Any], context: ExecutionContext | None
    ) -> IntegrationResult:
        workspace_path = params.get("workspace_path")
        ide_info = self.ide.discover_ide()
        hooks_info = self.ide.get_hooks_status(workspace_path)
        return IntegrationResult.ok(
            data={"ide": ide_info, "hooks": hooks_info},
            operation="get_ide_status",
            integration_id=self.integration_id,
        )


_antigravity_instance: AntigravityIntegration | None = None


def get_antigravity_integration() -> AntigravityIntegration:
    global _antigravity_instance
    if _antigravity_instance is None:
        _antigravity_instance = AntigravityIntegration()
    return _antigravity_instance
