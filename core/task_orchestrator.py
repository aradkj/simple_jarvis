"""Unified Task Orchestrator and Lifecycle Management for JARVIS Phase 10.

Implements all 14 task lifecycle states, verification records, persistent SQLite
checkpoints, progress tracking, bounded error recovery, and safe task resumption.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Generator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from core.events import AgentEvent, AgentEventType, EventBus
from infrastructure.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("core.task_orchestrator")


class TaskLifecycleState(StrEnum):
    """Authoritative lifecycle state machine for JARVIS tasks."""

    CREATED = "created"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    READY = "ready"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class VerificationState(StrEnum):
    """Operational evidence levels for real tool execution."""

    REQUESTED = "requested"
    PLANNED = "planned"
    AUTHORIZED = "authorized"
    STARTED = "started"
    EXECUTED = "executed"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


class OperationRetryClass(StrEnum):
    """Classification of operations according to safe recovery and retry semantics."""

    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    IDEMPOTENT_WITH_VERIFICATION = "idempotent_with_verification"
    NON_IDEMPOTENT = "non_idempotent"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    UNKNOWN_OUTCOME = "unknown_outcome"


def classify_operation(tool_name: str) -> OperationRetryClass:
    """Classify an operation according to its safe retry and idempotency characteristics."""
    tool_lower = (tool_name or "").lower().strip()
    if not tool_lower:
        return OperationRetryClass.UNKNOWN_OUTCOME

    # External side effects: messages, emails, webhook dispatches
    if any(t in tool_lower for t in ("email_send", "whatsapp_send", "sms_send", "post_webhook")):
        return OperationRetryClass.EXTERNAL_SIDE_EFFECT

    # Non-idempotent operations: deletions, moves, kills, arbitrary terminal execution
    if any(t in tool_lower for t in ("delete", "move", "kill", "terminal_execute", "drop")):
        return OperationRetryClass.NON_IDEMPOTENT

    # Read-only operations: queries, reads, inspections, status checks
    if any(
        t in tool_lower
        for t in (
            "read",
            "search",
            "inspect",
            "list",
            "get",
            "status",
            "overview",
            "info",
            "compare",
            "headings",
            "links",
        )
    ):
        return OperationRetryClass.READ_ONLY

    # Idempotent with verification: atomic write, edit, archive create, coding delegation
    if any(t in tool_lower for t in ("write", "edit", "copy", "archive_create", "coding_agent")):
        return OperationRetryClass.IDEMPOTENT_WITH_VERIFICATION

    return OperationRetryClass.UNKNOWN_OUTCOME


@dataclass
class VerificationRecord:
    """Evidence of real operation verification."""

    operation: str = ""
    target: str = ""
    verification_state: VerificationState = VerificationState.VERIFIED
    evidence_details: dict[str, Any] = field(default_factory=dict)
    verified_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    step_id: str = ""
    action_name: str = ""
    state: VerificationState = VerificationState.VERIFIED
    evidence_summary: str = ""
    operation_class: OperationRetryClass = OperationRetryClass.UNKNOWN_OUTCOME
    idempotency_key: str = ""
    recovery_decision: str = ""
    external_request_id: str = ""
    heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.operation and self.action_name:
            self.operation = self.action_name
        elif not self.action_name and self.operation:
            self.action_name = self.operation

        if not self.target and (self.evidence_summary or self.step_id):
            self.target = self.evidence_summary or self.step_id

        if (
            self.state
            and self.state != VerificationState.VERIFIED
            and self.verification_state == VerificationState.VERIFIED
        ):
            self.verification_state = self.state
        elif self.verification_state and not self.state:
            self.state = self.verification_state


@dataclass
class OrchestratedTask:
    """Rich persistent task structure representing a discrete unit of autonomous work."""

    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:10]}")
    user_request: str = ""
    goal: str = ""
    interpreted_intent: str = "unknown"
    session_id: str = ""
    context_references: dict[str, Any] = field(default_factory=dict)
    state: TaskLifecycleState = TaskLifecycleState.CREATED
    execution_plan: dict[str, Any] | None = None
    required_tools: list[str] = field(default_factory=list)
    permission_requirements: list[str] = field(default_factory=list)
    approval_requirements: list[str] = field(default_factory=list)
    current_step_index: int = 0
    total_steps: int = 0
    progress_percentage: float = 0.0
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    verification_records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recovery_actions: list[str] = field(default_factory=list)
    final_outcome: dict[str, Any] | None = None
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 2
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.user_request and self.goal:
            self.user_request = self.goal
        elif not self.goal and self.user_request:
            self.goal = self.user_request

    def transition_to(self, new_state: TaskLifecycleState, reason: str = "") -> None:
        """Apply state transition with timestamp update and checkpoint recording."""
        old_state = self.state
        self.state = new_state
        self.updated_at = datetime.now(UTC)
        checkpoint = {
            "from_state": old_state.value,
            "to_state": new_state.value,
            "reason": reason,
            "timestamp": self.updated_at.isoformat(),
            "step_index": self.current_step_index,
        }
        self.checkpoints.append(checkpoint)
        logger.info(
            f"Task '{self.task_id}' transitioned: {old_state.value} -> {new_state.value} ({reason})"
        )

    def add_verification(
        self,
        operation: str,
        target: str,
        state: VerificationState,
        details: dict[str, Any] | None = None,
    ) -> VerificationRecord:
        """Record concrete verification evidence for an executed operation."""
        det = details or {}
        rec = VerificationRecord(
            operation=operation,
            target=target,
            verification_state=state,
            evidence_details=det,
            step_id=str(det.get("step_id", "")),
            action_name=str(det.get("action_name", "")),
            evidence_summary=str(det.get("evidence_summary", "")),
        )
        self.verification_records.append(rec)
        self.updated_at = datetime.now(UTC)
        return rec

    def to_dict(self) -> dict[str, Any]:
        """Convert task to JSON-serializable dictionary."""
        d = asdict(self)
        d["state"] = self.state.value
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        d["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        d["verification_records"] = [
            asdict(r) if isinstance(r, VerificationRecord) else r for r in self.verification_records
        ]
        for r in d["verification_records"]:
            if (
                isinstance(r, dict)
                and "verified_at" in r
                and hasattr(r["verified_at"], "isoformat")
            ):
                r["verified_at"] = r["verified_at"].isoformat()
            if (
                isinstance(r, dict)
                and "verification_state" in r
                and hasattr(r["verification_state"], "value")
            ):
                r["verification_state"] = r["verification_state"].value
            if isinstance(r, dict) and "state" in r and hasattr(r["state"], "value"):
                r["state"] = r["state"].value
            if (
                isinstance(r, dict)
                and "operation_class" in r
                and hasattr(r["operation_class"], "value")
            ):
                r["operation_class"] = r["operation_class"].value
            if (
                isinstance(r, dict)
                and "heartbeat_at" in r
                and hasattr(r["heartbeat_at"], "isoformat")
            ):
                r["heartbeat_at"] = r["heartbeat_at"].isoformat()
        return d


class TaskDatabaseStore:
    """Persistent SQLite store for orchestrated tasks and resumption checkpoints."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else (settings.data_dir / "tasks.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            with contextlib.suppress(Exception):
                conn.close()

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestrated_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress_percentage REAL DEFAULT 0.0,
                    task_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.commit()

    def save_task(self, task: OrchestratedTask) -> None:
        with self._lock, self._get_connection() as conn:
            task_json = json.dumps(task.to_dict(), default=str)
            conn.execute(
                """
                INSERT INTO orchestrated_tasks (
                    task_id, session_id, user_request, state,
                    progress_percentage, task_json, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state=excluded.state,
                    progress_percentage=excluded.progress_percentage,
                    task_json=excluded.task_json,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.user_request,
                    task.state.value,
                    task.progress_percentage,
                    task_json,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.completed_at.isoformat() if task.completed_at else None,
                ),
            )
            conn.commit()

    def save_verification_record(self, task_id: str, record: VerificationRecord) -> None:
        """Attach and persist a verification record directly for a task."""
        with self._lock:
            task = self.load_task(task_id)
            if task:
                task.verification_records.append(record)
                task.updated_at = datetime.now(UTC)
                self.save_task(task)

    def load_task(self, task_id: str) -> OrchestratedTask | None:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT task_json FROM orchestrated_tasks WHERE task_id = ?", (task_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            data = json.loads(row["task_json"])
            return self._dict_to_task(data)

    def list_active_tasks(self) -> list[OrchestratedTask]:
        """Retrieve tasks that were incomplete before restart for safe resumption."""
        active_states = (
            TaskLifecycleState.CREATED.value,
            TaskLifecycleState.UNDERSTANDING.value,
            TaskLifecycleState.PLANNING.value,
            TaskLifecycleState.READY.value,
            TaskLifecycleState.EXECUTING.value,
            TaskLifecycleState.VERIFYING.value,
            TaskLifecycleState.RETRYING.value,
            TaskLifecycleState.WAITING_FOR_APPROVAL.value,
            TaskLifecycleState.WAITING_FOR_INPUT.value,
        )
        with self._lock, self._get_connection() as conn:
            placeholders = ",".join("?" for _ in active_states)
            cur = conn.execute(
                f"SELECT task_json FROM orchestrated_tasks WHERE state IN ({placeholders}) ORDER BY updated_at DESC",
                active_states,
            )
            tasks = []
            for row in cur.fetchall():
                tasks.append(self._dict_to_task(json.loads(row["task_json"])))
            return tasks

    def _dict_to_task(self, d: dict[str, Any]) -> OrchestratedTask:
        created_at = datetime.fromisoformat(d["created_at"])
        updated_at = datetime.fromisoformat(d["updated_at"])
        completed_at = datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None
        state = TaskLifecycleState(d.get("state", TaskLifecycleState.CREATED.value))

        raw_v_records = d.get("verification_records", [])
        v_records = []
        for r in raw_v_records:
            if isinstance(r, dict):
                op_c_raw = r.get("operation_class", "unknown_outcome")
                try:
                    op_class = OperationRetryClass(op_c_raw)
                except ValueError:
                    op_class = OperationRetryClass.UNKNOWN_OUTCOME

                v_records.append(
                    VerificationRecord(
                        operation=r.get("operation", ""),
                        target=r.get("target", ""),
                        verification_state=VerificationState(
                            r.get("verification_state", "verified")
                        ),
                        evidence_details=r.get("evidence_details", {}),
                        step_id=r.get("step_id", ""),
                        action_name=r.get("action_name", ""),
                        evidence_summary=r.get("evidence_summary", ""),
                        operation_class=op_class,
                        idempotency_key=r.get("idempotency_key", ""),
                        recovery_decision=r.get("recovery_decision", ""),
                        external_request_id=r.get("external_request_id", ""),
                    )
                )
            elif isinstance(r, VerificationRecord):
                v_records.append(r)

        return OrchestratedTask(
            task_id=d["task_id"],
            user_request=d.get("user_request", ""),
            goal=d.get("user_request", ""),
            interpreted_intent=d.get("interpreted_intent", "unknown"),
            session_id=d.get("session_id", ""),
            context_references=d.get("context_references", {}),
            state=state,
            execution_plan=d.get("execution_plan"),
            required_tools=d.get("required_tools", []),
            permission_requirements=d.get("permission_requirements", []),
            approval_requirements=d.get("approval_requirements", []),
            current_step_index=d.get("current_step_index", 0),
            total_steps=d.get("total_steps", 0),
            progress_percentage=d.get("progress_percentage", 0.0),
            tool_results=d.get("tool_results", []),
            verification_records=v_records,
            errors=d.get("errors", []),
            recovery_actions=d.get("recovery_actions", []),
            final_outcome=d.get("final_outcome"),
            checkpoints=d.get("checkpoints", []),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", 2),
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
        )


class UnifiedTaskOrchestrator:
    """Central orchestrator managing multi-step task execution, checkpoints, and verification."""

    _instance: UnifiedTaskOrchestrator | None = None

    def __init__(
        self,
        event_bus: EventBus | None = None,
        db_store: TaskDatabaseStore | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.event_bus = event_bus or EventBus()
        self.db = db_store or TaskDatabaseStore()
        self._active_tasks: dict[str, OrchestratedTask] = {}
        self._load_active_tasks()

    @classmethod
    def get_instance(cls) -> UnifiedTaskOrchestrator:
        if cls._instance is None:
            cls._instance = UnifiedTaskOrchestrator()
        return cls._instance

    def _load_active_tasks(self) -> None:
        try:
            persisted = self.db.list_active_tasks()
            for t in persisted:
                self._active_tasks[t.task_id] = t
            if persisted:
                logger.info(
                    f"Loaded {len(persisted)} active tasks from persistent store for recovery."
                )
        except Exception as exc:
            logger.warning(f"Error restoring active tasks from SQLite: {exc}")

    def create_task(
        self,
        user_request: str = "",
        session_id: str = "",
        interpreted_intent: str = "unknown",
        context_references: dict[str, Any] | None = None,
        goal: str = "",
        **kwargs: Any,
    ) -> OrchestratedTask:
        """Create and register a new persistent task."""
        with self._lock:
            effective_request = (
                user_request or goal or kwargs.get("metadata", {}).get("raw_goal", "Task")
            )
            meta = kwargs.get("metadata", {})
            refs = context_references or meta
            task = OrchestratedTask(
                user_request=effective_request,
                goal=effective_request,
                session_id=session_id,
                interpreted_intent=interpreted_intent,
                context_references=refs,
                state=TaskLifecycleState.CREATED,
            )
            self._active_tasks[task.task_id] = task
            self.db.save_task(task)

            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.TASK_CREATED,
                    payload={"task_id": task.task_id, "user_request": effective_request},
                )
            )
            return task

    def get_task(self, task_id: str) -> OrchestratedTask | None:
        with self._lock:
            if task_id in self._active_tasks:
                return self._active_tasks[task_id]
            return self.db.load_task(task_id)

    def update_task_state(
        self,
        task_id: str,
        new_state: TaskLifecycleState,
        reason: str = "",
        progress: float | None = None,
    ) -> OrchestratedTask | None:
        with self._lock:
            task = self.get_task(task_id)
            if not task:
                return None

            task.transition_to(new_state, reason=reason)
            if progress is not None:
                task.progress_percentage = max(0.0, min(100.0, progress))

            if new_state in (
                TaskLifecycleState.COMPLETED,
                TaskLifecycleState.PARTIALLY_COMPLETED,
                TaskLifecycleState.FAILED,
                TaskLifecycleState.CANCELLED,
            ):
                task.completed_at = datetime.now(UTC)

            self.db.save_task(task)

            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.TASK_PROGRESS,
                    payload={
                        "task_id": task.task_id,
                        "state": task.state.value,
                        "progress": task.progress_percentage,
                        "reason": reason,
                    },
                )
            )
            return task

    transition_task = update_task_state

    def record_verification(
        self,
        task_id: str,
        operation: str = "",
        target: str = "",
        state: VerificationState = VerificationState.VERIFIED,
        details: dict[str, Any] | None = None,
        step_id: str = "",
        action_name: str = "",
        evidence_summary: str = "",
        verified: bool = True,
        **kwargs: Any,
    ) -> VerificationRecord | None:
        """Attach verified operational evidence to an orchestrated task."""
        with self._lock:
            task = self.get_task(task_id)
            if not task:
                return None
            op = operation or action_name or step_id or "verification"
            tgt = target or evidence_summary or "system"
            det = dict(details or {})
            if evidence_summary:
                det["evidence_summary"] = evidence_summary
            det.update(kwargs)
            rec = task.add_verification(op, tgt, state, det)
            self.db.save_task(task)
            return rec

    def recover_interrupted_tasks(self) -> int:
        """Inspect interrupted tasks after application restart with operation-class recovery.

        Enforces:
        - Safe retry only for READ_ONLY operations.
        - Strict prevention of blind retries for EXTERNAL_SIDE_EFFECT (email, WhatsApp)
          and NON_IDEMPOTENT (file delete, process kill).
        - Transition of uncertain tasks to WAITING_FOR_INPUT or PARTIALLY_COMPLETED.
        - Full preservation of all prior execution checkpoints and tool results.
        """
        with self._lock:
            recovered_count = 0
            for task in self.db.list_active_tasks():
                if task.state in (
                    TaskLifecycleState.EXECUTING,
                    TaskLifecycleState.PLANNING,
                    TaskLifecycleState.VERIFYING,
                    TaskLifecycleState.READY,
                ):
                    # Determine operation class from current step or required tools
                    last_tool = ""
                    if task.execution_plan and "steps" in task.execution_plan:
                        steps = task.execution_plan.get("steps", [])
                        if 0 <= task.current_step_index < len(steps):
                            last_tool = steps[task.current_step_index].get("tool_name", "")
                    if not last_tool and task.required_tools:
                        last_tool = task.required_tools[-1]

                    op_class = classify_operation(last_tool)

                    if op_class in (
                        OperationRetryClass.EXTERNAL_SIDE_EFFECT,
                        OperationRetryClass.NON_IDEMPOTENT,
                    ):
                        action_msg = (
                            f"Interrupted during {op_class.value} operation ('{last_tool}'). "
                            f"Blind retry strictly suppressed to prevent duplicate side effects. "
                            f"Previous evidence preserved; user intervention required."
                        )
                        task.recovery_actions.append(action_msg)
                        task.transition_to(
                            TaskLifecycleState.WAITING_FOR_INPUT,
                            reason=action_msg,
                        )
                    elif op_class == OperationRetryClass.READ_ONLY:
                        action_msg = f"Interrupted during read-only operation ('{last_tool}'). Safe to resume."
                        task.recovery_actions.append(action_msg)
                        task.transition_to(
                            TaskLifecycleState.READY,
                            reason=action_msg,
                        )
                    elif op_class == OperationRetryClass.IDEMPOTENT_WITH_VERIFICATION:
                        action_msg = (
                            f"Interrupted during idempotent operation ('{last_tool}'). "
                            f"State must be verified before proceeding."
                        )
                        task.recovery_actions.append(action_msg)
                        task.transition_to(
                            TaskLifecycleState.PARTIALLY_COMPLETED,
                            reason=action_msg,
                        )
                    else:
                        action_msg = f"Application restarted during {task.state.value}; marked as FAILED for safe review."
                        task.recovery_actions.append(action_msg)
                        task.transition_to(
                            TaskLifecycleState.FAILED,
                            reason=action_msg,
                        )

                    self.db.save_task(task)
                    self._active_tasks[task.task_id] = task
                    recovered_count += 1
            return recovered_count

    recover_in_flight_tasks = recover_interrupted_tasks


_task_orchestrator_instance: UnifiedTaskOrchestrator | None = None


def get_task_orchestrator() -> UnifiedTaskOrchestrator:
    global _task_orchestrator_instance
    if _task_orchestrator_instance is None:
        _task_orchestrator_instance = UnifiedTaskOrchestrator.get_instance()
    return _task_orchestrator_instance
