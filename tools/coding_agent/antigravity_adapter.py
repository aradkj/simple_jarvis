"""Unified Antigravity Adapter for JARVIS."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.coding_agent.models import CodingTask, VerificationResult
from tools.coding_agent.process_manager import AntigravityProcessManager
from tools.coding_agent.result_verifier import CodingResultVerifier
from tools.coding_agent.task_manager import get_coding_task_manager

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("antigravity_adapter")


class AntigravityAdapter:
    """High-level adapter connecting JARVIS to the Google Antigravity coding agent."""

    def __init__(self) -> None:
        self.process_manager = AntigravityProcessManager()
        self.task_manager = get_coding_task_manager()

    def get_status(self) -> dict[str, Any]:
        """Return status of Antigravity installation and configuration."""
        settings = get_settings()
        health = self.process_manager.check_health()
        return {
            "enabled": settings.antigravity_enabled,
            "installed": health.get("installed", False),
            "executable_path": health.get("executable_path"),
            "model": settings.antigravity_default_model,
            "timeout_seconds": settings.antigravity_timeout_seconds,
            "authorized_workspaces": settings.antigravity_authorized_workspaces,
            "active_tasks_count": len(self.task_manager._tasks),
        }

    def delegate(
        self,
        prompt: str,
        workspace_path: str | Path | None = None,
        model: str | None = None,
        auto_verify: bool = True,
        context: ExecutionContext | None = None,
    ) -> CodingTask:
        """Delegate task to Antigravity."""
        return self.task_manager.delegate_task(
            prompt=prompt,
            workspace_path=workspace_path,
            model=model,
            auto_verify=auto_verify,
            context=context,
        )

    def get_task(self, task_id: str) -> CodingTask | None:
        return self.task_manager.get_task(task_id)

    def verify_workspace(
        self,
        workspace_path: str | Path,
        run_tests: bool = True,
        run_linter: bool = True,
    ) -> VerificationResult:
        """Run independent verification on any workspace directory."""
        ws = Path(workspace_path).resolve()
        verifier = CodingResultVerifier(ws)
        return verifier.verify_workspace(run_tests=run_tests, run_linter=run_linter)


_antigravity_adapter_instance: AntigravityAdapter | None = None


def get_antigravity_adapter() -> AntigravityAdapter:
    """Singleton getter for AntigravityAdapter."""
    global _antigravity_adapter_instance
    if _antigravity_adapter_instance is None:
        _antigravity_adapter_instance = AntigravityAdapter()
    return _antigravity_adapter_instance
