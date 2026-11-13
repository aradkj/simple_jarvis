"""Unit tests for agent core orchestrator and task management."""

from core.agent import AgentState, JARVISAgent
from core.events import AgentEvent, AgentEventType, EventBus
from core.task_manager import TaskManager, TaskStatus


def test_agent_lifecycle(test_agent: JARVISAgent) -> None:
    """Verify agent state transitions from INITIALIZING to IDLE to SHUTDOWN."""
    assert test_agent.state == AgentState.IDLE

    # Process message in Phase 2
    notice = test_agent.process_user_message("Hello JARVIS")
    assert "Gemini Notice" in notice or "not configured" in notice.lower()

    # Shutdown
    test_agent.shutdown()
    assert test_agent.state == AgentState.SHUTDOWN


def test_event_bus_pub_sub() -> None:
    """Verify event subscription and publishing."""
    bus = EventBus()
    received_events: list[AgentEvent] = []

    def handler(evt: AgentEvent) -> None:
        received_events.append(evt)

    bus.subscribe(AgentEventType.TASK_CREATED, handler)

    bus.publish(AgentEvent(event_type=AgentEventType.TASK_CREATED, payload={"id": "task-1"}))
    bus.publish(AgentEvent(event_type=AgentEventType.MESSAGE_SENT, payload={"text": "hi"}))

    assert len(received_events) == 1
    assert received_events[0].payload == {"id": "task-1"}


def test_task_manager_lifecycle() -> None:
    """Verify task creation, cancellation, and tracking."""
    event_bus = EventBus()
    task_mgr = TaskManager(event_bus=event_bus)

    task = task_mgr.create_task("Scan system logs")
    assert task.status == TaskStatus.PENDING
    assert task_mgr.get_task(task.task_id) is task

    task.mark_started()
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None

    # Cancel task
    cancelled = task_mgr.cancel_task(task.task_id)
    assert cancelled is True
    assert task.status == TaskStatus.CANCELLED
    assert task.context.is_cancelled() is True
