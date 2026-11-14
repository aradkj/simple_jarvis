"""Background worker threads for non-blocking AI provider operations."""

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ai.base import (
    BaseAIProvider,
    ConnectionErrorType,
    ConnectionTestResult,
    ProviderCancelledError,
)
from ai.providers.gemini import GeminiCancelledError
from core.execution_context import CancellationToken
from infrastructure.logging import get_logger
from memory.base import ConversationMessage

logger = get_logger("ui.workers")


class GeminiStreamWorker(QThread):
    """Worker thread that executes AI streaming generation without freezing the GUI."""

    chunk_received = Signal(str, str)  # chunk_text, session_id
    generation_finished = Signal(str, str)  # final_text, session_id
    generation_error = Signal(str, str)  # error_message, session_id
    generation_cancelled = Signal(str)  # session_id

    def __init__(
        self,
        provider: BaseAIProvider,
        prompt: str,
        session_id: str,
        history: list[ConversationMessage] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.prompt = prompt
        self.session_id = session_id
        self.history = history or []
        self.cancellation_token = CancellationToken()
        self._accumulated_text = ""

    def cancel(self) -> None:
        """Signal the cancellation token to abort the active stream."""
        logger.info(f"Cancellation requested for session {self.session_id}")
        self.cancellation_token.cancel()

    def run(self) -> None:
        """Thread execution logic."""
        logger.debug(f"Starting AI streaming worker for session {self.session_id}")
        try:
            for chunk in self.provider.stream_text(
                prompt=self.prompt,
                history=self.history,
                cancellation_token=self.cancellation_token,
            ):
                if self.cancellation_token.is_cancelled():
                    self.generation_cancelled.emit(self.session_id)
                    return

                self._accumulated_text += chunk
                self.chunk_received.emit(chunk, self.session_id)

            if self.cancellation_token.is_cancelled():
                self.generation_cancelled.emit(self.session_id)
            else:
                self.generation_finished.emit(self._accumulated_text, self.session_id)

        except (GeminiCancelledError, ProviderCancelledError):
            logger.info("Stream worker aborted via cancellation error.")
            self.generation_cancelled.emit(self.session_id)

        except Exception as exc:
            err_msg = str(exc)
            logger.error(f"Stream worker encountered error: {err_msg}")
            self.generation_error.emit(err_msg, self.session_id)


# Alias for multi-provider consistency
ProviderStreamWorker = GeminiStreamWorker


class AgentExecutionWorker(QThread):
    """Background worker executing full Phase 3 agent task without freezing GUI."""

    plan_created = Signal(object, str)  # Plan, session_id
    step_started = Signal(str, str, str)  # step_id, description, session_id
    step_completed = Signal(str, str, str)  # step_id, result_summary, session_id
    task_finished = Signal(object, str)  # ExecutionOutcome, session_id
    task_error = Signal(str, str)  # error_msg, session_id
    task_cancelled = Signal(str)  # session_id
    approval_requested = Signal(object, str)  # ToolProposal, session_id

    def __init__(
        self,
        agent: object,
        goal: str,
        session_id: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.agent = agent
        self.goal = goal
        self.session_id = session_id
        self.cancellation_token = CancellationToken()

    def cancel(self) -> None:
        """Signal the cancellation token to abort the active agent task."""
        logger.info(f"Agent cancellation requested for session {self.session_id}")
        self.cancellation_token.cancel()

    def run(self) -> None:
        """Execute autonomous agent pipeline."""
        from core.events import AgentEventType
        from core.execution_context import ExecutionContext

        ctx = ExecutionContext(session_id=self.session_id)
        ctx.cancellation_token = self.cancellation_token

        # Subscribe temporary event listeners to pipe into Qt signals
        def on_event(ev: object) -> None:
            if ev.event_type == AgentEventType.PLAN_CREATED:
                self.plan_created.emit(ev.payload, self.session_id)
            elif ev.event_type == AgentEventType.STEP_STARTED:
                self.step_started.emit(
                    ev.payload.get("step_id", ""),
                    ev.payload.get("description", ""),
                    self.session_id,
                )
            elif ev.event_type == AgentEventType.STEP_COMPLETED:
                self.step_completed.emit(
                    ev.payload.get("step_id", ""),
                    str(ev.payload.get("result", "")),
                    self.session_id,
                )
            elif ev.event_type == AgentEventType.APPROVAL_REQUIRED:
                self.approval_requested.emit(ev.payload, self.session_id)

        self.agent.event_bus.subscribe_all(on_event)

        try:
            outcome = self.agent.process_agent_task(
                goal=self.goal,
                session_id=self.session_id,
                context=ctx,
                wait_for_approval=True,
            )
            if self.cancellation_token.is_cancelled() or outcome.status == "cancelled":
                self.task_cancelled.emit(self.session_id)
            elif outcome.status == "failed":
                self.task_error.emit(outcome.error or "Agent task failed", self.session_id)
            else:
                self.task_finished.emit(outcome, self.session_id)
        except Exception as exc:
            if self.cancellation_token.is_cancelled():
                self.task_cancelled.emit(self.session_id)
            else:
                self.task_error.emit(str(exc), self.session_id)
        finally:
            self.agent.event_bus.unsubscribe_all(on_event)


class ConnectionTestWorker(QThread):
    """Worker thread to test AI provider connectivity without blocking GUI."""

    test_completed = Signal(object)  # ConnectionTestResult

    def __init__(
        self,
        provider: BaseAIProvider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider

    def run(self) -> None:
        """Run connectivity check in background thread."""
        logger.info(f"Executing background connection test for {self.provider.provider_name}...")
        try:
            result = self.provider.test_connection()
            self.test_completed.emit(result)
        except Exception as exc:
            self.test_completed.emit(
                ConnectionTestResult(
                    is_success=False,
                    message=f"Connection test error: {exc}",
                    error_type=ConnectionErrorType.UNKNOWN_ERROR,
                )
            )


class MemoryFetchWorker(QThread):
    """Background worker to query memory records without blocking the GUI thread."""

    records_loaded = Signal(list)  # list[MemoryRecord]
    error_occurred = Signal(str)

    def __init__(
        self,
        memory_manager: Any,
        category: Any = None,
        status: Any = None,
        project_id: str | None = None,
        search_query: str = "",
        limit: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.memory_manager = memory_manager
        self.category = category
        self.status = status
        self.project_id = project_id
        self.search_query = search_query
        self.limit = limit

    def run(self) -> None:
        try:
            records = self.memory_manager.list_memories(
                category=self.category,
                status=self.status,
                project_id=self.project_id,
                search_query=self.search_query,
                limit=self.limit,
            )
            self.records_loaded.emit(records)
        except Exception as exc:
            logger.error(f"MemoryFetchWorker failed: {exc}")
            self.error_occurred.emit(str(exc))


class MemoryOperationWorker(QThread):
    """Background worker to execute memory mutations (add, edit, delete, clear)."""

    operation_finished = Signal(bool, str)  # success, message

    def __init__(
        self,
        operation_fn: Any,
        success_message: str = "Operation completed",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.operation_fn = operation_fn
        self.success_message = success_message

    def run(self) -> None:
        try:
            self.operation_fn()
            self.operation_finished.emit(True, self.success_message)
        except Exception as exc:
            logger.error(f"MemoryOperationWorker failed: {exc}")
            self.operation_finished.emit(False, str(exc))


class CodingAgentWorker(QThread):
    """Background worker executing Antigravity task delegation without freezing the GUI."""

    chunk_received = Signal(str)
    task_completed = Signal(dict)
    task_failed = Signal(str)

    def __init__(
        self,
        prompt: str,
        workspace_path: str | None = None,
        model: str | None = None,
        auto_verify: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.prompt = prompt
        self.workspace_path = workspace_path
        self.model = model
        self.auto_verify = auto_verify
        self.cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self.cancellation_token.cancel()

    def run(self) -> None:
        from core.execution_context import ExecutionContext
        from tools.coding_agent import get_coding_task_manager

        manager = get_coding_task_manager()
        ctx = ExecutionContext()

        def _stream_cb(chunk: str) -> None:
            self.chunk_received.emit(chunk)

        try:
            task = manager.delegate_task(
                prompt=self.prompt,
                workspace_path=self.workspace_path,
                model=self.model,
                auto_verify=self.auto_verify,
                stream_callback=_stream_cb,
                context=ctx,
            )
            if task.status.value == "failed":
                self.task_failed.emit(task.error_message or "Task failed")
            else:
                self.task_completed.emit(task.to_dict())
        except Exception as exc:
            logger.error(f"CodingAgentWorker error: {exc}")
            self.task_failed.emit(str(exc))
