"""Crash Recovery and Duplicate Side-Effect Prevention Tests for Unified Task Orchestrator (Phase 10).

Validates:
1. Classification of operations into READ_ONLY, IDEMPOTENT, NON_IDEMPOTENT, EXTERNAL_SIDE_EFFECT.
2. Crash recovery on startup:
   - READ_ONLY tasks transition to READY (safe to resume).
   - EXTERNAL_SIDE_EFFECT (email, WhatsApp) tasks transition to WAITING_FOR_INPUT, suppressing blind resends.
   - NON_IDEMPOTENT (file delete, process kill) tasks transition to WAITING_FOR_INPUT, preventing duplicate side effects.
   - IDEMPOTENT_WITH_VERIFICATION (file write, coding agent) tasks transition to PARTIALLY_COMPLETED.
3. Full preservation of previous execution evidence, checkpoints, and tool results across restarts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.task_orchestrator import (
    OperationRetryClass,
    TaskDatabaseStore,
    TaskLifecycleState,
    UnifiedTaskOrchestrator,
    VerificationRecord,
    VerificationState,
    classify_operation,
)


@pytest.fixture
def disposable_orchestrator(tmp_path: Path):
    """Fixture providing an isolated task orchestrator with a disposable SQLite database."""
    db_path = tmp_path / "test_tasks.db"
    store = TaskDatabaseStore(db_path=db_path)
    return UnifiedTaskOrchestrator(db_store=store)


# ==============================================================================
# 1. Operation Classification Verification
# ==============================================================================
def test_operation_classification():
    """Verify tool operations are classified into safe vs. risky retry semantics."""
    assert classify_operation("file_read_text") == OperationRetryClass.READ_ONLY
    assert classify_operation("system_cpu_info") == OperationRetryClass.READ_ONLY
    assert classify_operation("browser_get_headings") == OperationRetryClass.READ_ONLY

    assert classify_operation("email_send") == OperationRetryClass.EXTERNAL_SIDE_EFFECT
    assert classify_operation("whatsapp_send") == OperationRetryClass.EXTERNAL_SIDE_EFFECT

    assert classify_operation("file_delete") == OperationRetryClass.NON_IDEMPOTENT
    assert classify_operation("terminal_execute_command") == OperationRetryClass.NON_IDEMPOTENT

    assert classify_operation("file_write_text") == OperationRetryClass.IDEMPOTENT_WITH_VERIFICATION
    assert (
        classify_operation("coding_agent_delegate_task")
        == OperationRetryClass.IDEMPOTENT_WITH_VERIFICATION
    )

    assert classify_operation("") == OperationRetryClass.UNKNOWN_OUTCOME
    assert classify_operation("unknown_custom_tool") == OperationRetryClass.UNKNOWN_OUTCOME


# ==============================================================================
# 2. Crash Recovery: External Side Effect Suppresses Duplicate Sending
# ==============================================================================
def test_recovery_external_side_effect_suppresses_blind_resend(
    disposable_orchestrator: UnifiedTaskOrchestrator,
):
    """If interrupted during email_send or whatsapp_send, blind retry is suppressed."""
    task = disposable_orchestrator.create_task(
        goal="Send quarterly report to board@example.com",
        interpreted_intent="send_email",
    )
    task.execution_plan = {
        "steps": [{"tool_name": "email_send", "parameters": {"to": "board@example.com"}}]
    }
    task.required_tools = ["email_send"]
    disposable_orchestrator.update_task_state(task.task_id, TaskLifecycleState.EXECUTING)

    # Simulate restart recovery
    recovered_count = disposable_orchestrator.recover_interrupted_tasks()
    assert recovered_count == 1

    loaded = disposable_orchestrator.get_task(task.task_id)
    assert loaded is not None
    assert loaded.state == TaskLifecycleState.WAITING_FOR_INPUT
    assert any("Blind retry strictly suppressed" in action for action in loaded.recovery_actions)


# ==============================================================================
# 3. Crash Recovery: Non-Idempotent Operation (Deletion) Never Repeated
# ==============================================================================
def test_recovery_non_idempotent_delete_never_blindly_repeated(
    disposable_orchestrator: UnifiedTaskOrchestrator,
):
    """If interrupted during file deletion, task transitions to WAITING_FOR_INPUT."""
    task = disposable_orchestrator.create_task(
        goal="Delete temporary build artifacts",
        interpreted_intent="delete_file",
    )
    task.execution_plan = {
        "steps": [{"tool_name": "file_delete", "parameters": {"path": "build/"}}]
    }
    task.required_tools = ["file_delete"]
    disposable_orchestrator.update_task_state(task.task_id, TaskLifecycleState.EXECUTING)

    recovered_count = disposable_orchestrator.recover_interrupted_tasks()
    assert recovered_count == 1

    loaded = disposable_orchestrator.get_task(task.task_id)
    assert loaded is not None
    assert loaded.state == TaskLifecycleState.WAITING_FOR_INPUT
    assert any("Blind retry strictly suppressed" in action for action in loaded.recovery_actions)


# ==============================================================================
# 4. Crash Recovery: Read-Only Operation Transitions to READY
# ==============================================================================
def test_recovery_read_only_operation_transitions_to_ready(
    disposable_orchestrator: UnifiedTaskOrchestrator,
):
    """If interrupted during a read-only query, task safely transitions to READY."""
    task = disposable_orchestrator.create_task(
        goal="Inspect system memory and CPU utilization",
        interpreted_intent="system_overview",
    )
    task.execution_plan = {"steps": [{"tool_name": "system_overview"}]}
    task.required_tools = ["system_overview"]
    disposable_orchestrator.update_task_state(task.task_id, TaskLifecycleState.EXECUTING)

    recovered_count = disposable_orchestrator.recover_interrupted_tasks()
    assert recovered_count == 1

    loaded = disposable_orchestrator.get_task(task.task_id)
    assert loaded is not None
    assert loaded.state == TaskLifecycleState.READY
    assert any("Safe to resume" in action for action in loaded.recovery_actions)


# ==============================================================================
# 5. Crash Recovery: Idempotent Write Requires Verification
# ==============================================================================
def test_recovery_idempotent_write_requires_verification(
    disposable_orchestrator: UnifiedTaskOrchestrator,
):
    """If interrupted during file write, task transitions to PARTIALLY_COMPLETED for verification."""
    task = disposable_orchestrator.create_task(
        goal="Write release notes to docs/release.md",
        interpreted_intent="write_file",
    )
    task.execution_plan = {
        "steps": [{"tool_name": "file_write_text", "parameters": {"path": "release.md"}}]
    }
    task.required_tools = ["file_write_text"]
    disposable_orchestrator.update_task_state(task.task_id, TaskLifecycleState.EXECUTING)

    recovered_count = disposable_orchestrator.recover_interrupted_tasks()
    assert recovered_count == 1

    loaded = disposable_orchestrator.get_task(task.task_id)
    assert loaded is not None
    assert loaded.state == TaskLifecycleState.PARTIALLY_COMPLETED
    assert any("State must be verified" in action for action in loaded.recovery_actions)


# ==============================================================================
# 6. Preservation of Previous Checkpoints and Verification Evidence
# ==============================================================================
def test_recovery_preserves_checkpoints_and_evidence(
    disposable_orchestrator: UnifiedTaskOrchestrator,
):
    """Recovery preserves all prior checkpoints, verification records, and tool results."""
    task = disposable_orchestrator.create_task(goal="Multi-step deployment", session_id="sess_123")
    disposable_orchestrator.update_task_state(
        task.task_id, TaskLifecycleState.PLANNING, reason="Planned step 1"
    )
    disposable_orchestrator.update_task_state(
        task.task_id, TaskLifecycleState.EXECUTING, reason="Executing step 1"
    )

    # Add evidence before crash
    disposable_orchestrator.record_verification(
        task_id=task.task_id,
        operation="file_write_text",
        target="config.json",
        state=VerificationState.VERIFIED,
        evidence_summary="config.json written atomically (512 bytes)",
    )

    # Recover
    disposable_orchestrator.recover_interrupted_tasks()

    loaded = disposable_orchestrator.get_task(task.task_id)
    assert loaded is not None
    assert len(loaded.checkpoints) >= 3
    assert len(loaded.verification_records) == 1
    rec = loaded.verification_records[0]
    if isinstance(rec, VerificationRecord):
        assert rec.operation == "file_write_text"
        assert rec.target == "config.json"
    else:
        assert rec["operation"] == "file_write_text"
