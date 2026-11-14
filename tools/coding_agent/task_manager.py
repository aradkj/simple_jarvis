"""Task Lifecycle Manager and Remediation Loop for Antigravity Coding Agent."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.coding_agent.exceptions import TaskExecutionError
from tools.coding_agent.models import CodingTask, CodingTaskStatus
from tools.coding_agent.process_manager import AntigravityProcessManager
from tools.coding_agent.result_verifier import CodingResultVerifier
from tools.coding_agent.stream_parser import StreamParser
from tools.coding_agent.workspace_policy import WorkspacePolicy

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("coding_task_manager")


class CodingTaskManager:
    """Manages active tasks, NDJSON streaming, and bounded remediation loops."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, CodingTask] = {}
        self.process_manager = AntigravityProcessManager()

    def get_task(self, task_id: str) -> CodingTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
            tasks.sort(key=lambda t: t.created_at, reverse=True)
            return [t.to_dict() for t in tasks[:limit]]

    def delegate_task(
        self,
        prompt: str,
        workspace_path: str | Path | None = None,
        model: str | None = None,
        auto_verify: bool = True,
        stream_callback: Callable[[str], None] | None = None,
        context: ExecutionContext | None = None,
    ) -> CodingTask:
        """Delegate a software development task to Google Antigravity."""
        settings = get_settings()
        if not settings.antigravity_enabled:
            raise TaskExecutionError("Antigravity integration is disabled in configuration.")

        # 1. Resolve & validate workspace
        target_ws = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
        validated_ws = WorkspacePolicy.validate_workspace(target_ws)

        task = CodingTask(
            prompt=prompt,
            workspace=str(validated_ws),
            model=model or settings.antigravity_default_model,
            status=CodingTaskStatus.RUNNING,
        )

        with self._lock:
            self._tasks[task.task_id] = task

        logger.info(f"Delegating task {task.task_id} in '{validated_ws}'")

        try:
            self._run_task_execution(
                task=task,
                workspace=validated_ws,
                auto_verify=auto_verify,
                stream_callback=stream_callback,
                context=context,
            )
            return task
        except Exception as exc:
            task.status = CodingTaskStatus.FAILED
            task.error_message = str(exc)
            task.completed_at = datetime.now(UTC)
            logger.error(f"Task {task.task_id} failed: {exc}")
            return task

    def _run_task_execution(
        self,
        task: CodingTask,
        workspace: Path,
        auto_verify: bool,
        stream_callback: Callable[[str], None] | None,
        context: ExecutionContext | None,
    ) -> None:
        settings = get_settings()
        max_remediations = settings.antigravity_max_remediation_retries
        current_prompt = task.prompt

        while True:
            task.status = CodingTaskStatus.STREAMING
            parser = StreamParser()

            def _line_handler(line: str, p: StreamParser = parser) -> None:
                task.raw_lines.append(line)
                ev = p.parse_line(line)
                if ev:
                    task.events.append(ev)
                    if ev.text_delta and stream_callback:
                        stream_callback(ev.text_delta)

            try:
                exit_code, lines, stderr, duration = self.process_manager.execute_stream(
                    prompt=current_prompt,
                    workspace=workspace,
                    model=task.model,
                    conversation_id=task.conversation_id,
                    line_callback=_line_handler,
                    context=context,
                )
            except Exception as proc_err:
                task.status = CodingTaskStatus.FAILED
                task.error_message = str(proc_err)
                task.completed_at = datetime.now(UTC)
                return

            if not task.raw_lines and lines:
                for line in lines:
                    _line_handler(line)

            task.duration_seconds += duration
            task.conversation_id = parser.conversation_id or task.conversation_id
            task.response_text = parser.get_full_response()
            if parser.final_result and "usage" in parser.final_result:
                task.usage = parser.final_result["usage"]

            # Independent verification
            if auto_verify:
                task.status = CodingTaskStatus.VERIFYING
                verifier = CodingResultVerifier(workspace)
                verification = verifier.verify_workspace(
                    run_tests=settings.antigravity_run_tests_on_verify
                )
                task.verification = verification

                # Check if remediation is required and possible
                if (
                    not verification.verified
                    and verification.tests_executed
                    and not verification.tests_passed
                    and task.remediation_attempts < max_remediations
                ):
                    task.remediation_attempts += 1
                    logger.warning(
                        f"Tests failed for task {task.task_id}. Initiating remediation attempt "
                        f"{task.remediation_attempts}/{max_remediations}"
                    )
                    current_prompt = (
                        f"Your previous changes caused automated test failures. Please fix the issue.\n\n"
                        f"--- Test Output ---\n{verification.test_output}\n\n"
                        f"Original task: {task.prompt}"
                    )
                    continue

            task.status = CodingTaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
            break


_task_manager_instance: CodingTaskManager | None = None


def get_coding_task_manager() -> CodingTaskManager:
    """Singleton getter for CodingTaskManager."""
    global _task_manager_instance
    if _task_manager_instance is None:
        _task_manager_instance = CodingTaskManager()
    return _task_manager_instance
