"""Multi-Tool Orchestration Engine for JARVIS Universal Integration Hub."""

from __future__ import annotations

import concurrent.futures
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from integrations.antigravity.adapter import get_antigravity_integration
from integrations.antigravity.lifecycle import AntigravityTaskRecord, TaskLifecycleState
from integrations.base import IntegrationResult
from integrations.hub import get_integration_hub
from integrations.whatsapp.adapter import get_whatsapp_integration

if TYPE_CHECKING:
    pass

logger = get_logger("multi_tool_orchestrator")


@dataclass
class OrchestratedJob:
    job_id: str
    description: str
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    task_id: str | None = None
    notification_status: str = "none"
    result: Any = None
    error: str | None = None


class MultiToolOrchestrator:
    """Coordinates complex cross-tool pipelines: Antigravity -> Verifier -> WhatsApp with failure isolation."""

    _instance: MultiToolOrchestrator | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self.hub = get_integration_hub()
        self.agy = get_antigravity_integration()
        self.wa = get_whatsapp_integration()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="OrchestratorWorker"
        )
        self._jobs: dict[str, OrchestratedJob] = {}

    @classmethod
    def get_instance(cls) -> MultiToolOrchestrator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = MultiToolOrchestrator()
            return cls._instance

    def run_antigravity_with_whatsapp_alert(
        self,
        prompt: str,
        workspace_path: str | Path | None = None,
        recipient: str = "خودم",
        model: str = "inherit",
        auto_verify: bool = True,
        on_progress: Callable[[str], None] | None = None,
    ) -> OrchestratedJob:
        """Run an end-to-end Antigravity task with automated WhatsApp alert upon completion/failure.

        Executes asynchronously in a background thread to prevent blocking the UI or voice loop.
        """
        import uuid

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = OrchestratedJob(
            job_id=job_id,
            description=f"Antigravity coding task with WhatsApp notification to {recipient}",
        )
        with self._lock:
            self._jobs[job_id] = job

        self._executor.submit(
            self._execute_pipeline,
            job_id,
            prompt,
            workspace_path,
            recipient,
            model,
            auto_verify,
            on_progress,
        )
        return job

    def _execute_pipeline(
        self,
        job_id: str,
        prompt: str,
        workspace_path: str | Path | None,
        recipient: str,
        model: str,
        auto_verify: bool,
        on_progress: Callable[[str], None] | None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"

        logger.info(f"Starting orchestrated job {job_id}: prompt='{prompt[:80]}'")
        if on_progress:
            on_progress(f"Job {job_id} initiated.")

        # Step 1: Execute Antigravity Task
        agy_result: IntegrationResult = self.agy.execute(
            "delegate_task",
            {
                "prompt": prompt,
                "workspace_path": str(workspace_path) if workspace_path else str(Path.cwd()),
                "model": model,
                "auto_verify": auto_verify,
            },
        )

        task_id = agy_result.task_id or (
            agy_result.data.get("task_id") if isinstance(agy_result.data, dict) else None
        )
        job.task_id = task_id

        # Retrieve full task record
        task_record: AntigravityTaskRecord | None = None
        if task_id:
            task_record = self.agy.tracker.get_task(task_id)

        if not task_record:
            # Fallback mock task record for notification
            task_record = AntigravityTaskRecord(
                task_id=task_id or "unknown",
                prompt=prompt,
                workspace_path=str(workspace_path or Path.cwd()),
                state=TaskLifecycleState.COMPLETED
                if agy_result.success
                else TaskLifecycleState.FAILED,
                error_message=agy_result.error,
            )

        # Step 2: Update Job Status
        with self._lock:
            job.completed_at = datetime.now(UTC)
            if agy_result.success:
                job.status = "completed"
                job.result = agy_result.data
            else:
                job.status = "failed"
                job.error = agy_result.error

        # Step 3: Trigger WhatsApp Notification with complete failure isolation
        try:
            logger.info(f"Dispatching WhatsApp notification for job {job_id} to {recipient}")
            notif_res = self.wa.execute(
                "send_task_notification",
                {"task": task_record, "recipient": recipient},
            )
            with self._lock:
                job.notification_status = "sent" if notif_res.success else "failed"
        except Exception as exc:
            logger.error(
                f"WhatsApp notification dispatch failed in orchestrator: {exc}", exc_info=True
            )
            with self._lock:
                job.notification_status = f"error: {exc}"

        logger.info(
            f"Orchestrated job {job_id} finished with status={job.status}, notif={job.notification_status}"
        )

    def get_job(self, job_id: str) -> OrchestratedJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[OrchestratedJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


def get_orchestrator() -> MultiToolOrchestrator:
    return MultiToolOrchestrator.get_instance()
