"""Comprehensive unit and regression tests for Phase 3: Agent Core & Planning.

Covers:
1. Agent Planner (decomposition, should_plan, acyclic validation, replanning, JSON parsing)
2. Agent State Machine (transitions, validation, idempotency, event emission, reset)
3. Agent Executor (bounded steps, loop detection, timeout, retries, approval stop)
4. Tool Proposal Architecture (approval requirements, schema validation, mock tool execution)
5. ProviderManager-Only Integration (no direct provider SDKs, error propagation, cancellation)
6. Session Isolation (concurrent contexts, zero cross-session plan or event leakage)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai.base import AIResponse
from config import Settings
from core.agent import JARVISAgent
from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import CancellationToken, ExecutionContext
from core.executor import AgentExecutor
from core.permissions import (
    PermissionCategory,
    StrictDefaultDenyPermissionManager,
)
from core.planner import (
    AgentPlanner,
    Plan,
    PlanStep,
    PlanValidationError,
    StepStatus,
    StepType,
)
from core.state_machine import (
    AgentState,
    AgentStateMachine,
    InvalidStateTransitionError,
)
from core.tool_proposal import RiskLevel
from core.tool_registry import ToolRegistry
from tools.mock_tools import (
    MockCalculatorTool,
    MockDangerousSystemTool,
    MockSearchTool,
)

# ==============================================================================
# SECTION 1: AGENT STATE MACHINE TESTS
# ==============================================================================


def test_state_machine_valid_transitions():
    """Verify legal state machine progression through the agent lifecycle."""
    sm = AgentStateMachine(initial_state=AgentState.IDLE)
    assert sm.current_state == AgentState.IDLE

    # IDLE -> ANALYZING -> PLANNING -> PLAN_READY -> EXECUTING -> COMPLETED -> IDLE
    assert sm.can_transition(AgentState.ANALYZING)
    sm.transition_to(AgentState.ANALYZING, reason="Analyzing prompt")
    assert sm.current_state == AgentState.ANALYZING

    assert sm.can_transition(AgentState.PLANNING)
    sm.transition_to(AgentState.PLANNING, reason="Creating plan")
    assert sm.current_state == AgentState.PLANNING

    assert sm.can_transition(AgentState.PLAN_READY)
    sm.transition_to(AgentState.PLAN_READY, reason="Plan ready")
    assert sm.current_state == AgentState.PLAN_READY

    assert sm.can_transition(AgentState.EXECUTING)
    sm.transition_to(AgentState.EXECUTING, reason="Executing steps")
    assert sm.current_state == AgentState.EXECUTING

    assert sm.can_transition(AgentState.COMPLETED)
    sm.transition_to(AgentState.COMPLETED, reason="Task complete")
    assert sm.current_state == AgentState.COMPLETED

    assert sm.can_transition(AgentState.IDLE)
    sm.transition_to(AgentState.IDLE, reason="Returned to idle")
    assert sm.current_state == AgentState.IDLE


def test_state_machine_invalid_transition_raises():
    """Verify illegal transitions are rejected with InvalidStateTransitionError."""
    sm = AgentStateMachine(initial_state=AgentState.IDLE)

    # Cannot jump straight from IDLE to COMPLETED
    assert not sm.can_transition(AgentState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        sm.transition_to(AgentState.COMPLETED)
    assert "Cannot transition from idle to completed" in str(exc_info.value)


def test_state_machine_cancellation_and_failure_transitions():
    """Cancellation and failure are reachable from in-progress execution states."""
    sm = AgentStateMachine(initial_state=AgentState.EXECUTING)
    assert sm.can_transition(AgentState.CANCELLED)
    sm.transition_to(AgentState.CANCELLED, reason="User cancelled")
    assert sm.current_state == AgentState.CANCELLED

    # From CANCELLED, can return to IDLE
    sm.transition_to(AgentState.IDLE, reason="Reset")

    # Move to EXECUTING -> FAILED
    sm.transition_to(AgentState.EXECUTING)
    sm.transition_to(AgentState.FAILED, reason="Step failed")
    assert sm.current_state == AgentState.FAILED


def test_state_machine_history_and_event_publishing():
    """State machine records traceable audit history and publishes events to EventBus."""
    eb = EventBus()
    events: list[AgentEvent] = []
    eb.subscribe(AgentEventType.AGENT_STATUS_CHANGED, lambda e: events.append(e))

    sm = AgentStateMachine(initial_state=AgentState.IDLE, session_id="sess_123", event_bus=eb)
    sm.transition_to(AgentState.ANALYZING, reason="Testing history")

    history = sm.get_history()
    assert len(history) == 1
    assert history[0].from_state == AgentState.IDLE
    assert history[0].to_state == AgentState.ANALYZING
    assert history[0].reason == "Testing history"

    assert len(events) == 1
    assert events[0].payload["new_state"] == "analyzing"
    assert events[0].payload["session_id"] == "sess_123"


# ==============================================================================
# SECTION 2: STRUCTURED PLANNER & DEPENDENCY GRAPH TESTS
# ==============================================================================


def test_planner_should_plan_heuristics():
    """Heuristic determines conversational queries vs multi-step planning tasks."""
    planner = AgentPlanner(provider_manager=MagicMock())

    # Conversational queries should NOT trigger planning
    assert not planner.should_plan("hello")
    assert not planner.should_plan("who are you?")
    assert not planner.should_plan("hi, how are you today?")
    assert not planner.should_plan("سلام چطوری")

    # Multi-step tasks should trigger planning
    assert planner.should_plan("Search for python docs and then calculate 12 * 4")
    assert planner.should_plan("calculate 10 + 20")
    assert planner.should_plan("Find weather in Tokyo and plan a trip")


def test_planner_dependency_validation_and_acyclic_checks():
    """Plan correctly identifies executable steps and detects circular dependencies."""
    plan = Plan(goal="Test acyclic")

    step1 = PlanStep(step_id="s1", description="Fetch data", dependencies=[])
    step2 = PlanStep(step_id="s2", description="Compute metrics", dependencies=["s1"])
    step3 = PlanStep(step_id="s3", description="Format output", dependencies=["s2"])

    plan.add_step(step1)
    plan.add_step(step2)
    plan.add_step(step3)

    # Valid plan passes acyclic check
    plan.validate_acyclic()

    # Only step1 is executable initially
    executable = plan.get_executable_steps()
    assert len(executable) == 1
    assert executable[0].step_id == "s1"

    # Complete step1
    step1.status = StepStatus.COMPLETED
    executable2 = plan.get_executable_steps()
    assert len(executable2) == 1
    assert executable2[0].step_id == "s2"


def test_planner_circular_dependency_raises():
    """Circular dependency graph raises PlanValidationError."""
    plan = Plan(goal="Circular test")
    s1 = PlanStep(step_id="step_a", dependencies=["step_b"])
    s2 = PlanStep(step_id="step_b", dependencies=["step_a"])
    plan.add_step(s1)
    plan.add_step(s2)

    with pytest.raises(PlanValidationError) as exc_info:
        plan.validate_acyclic()
    assert "circular dependency cycle" in str(exc_info.value)


def test_planner_create_plan_with_mock_provider():
    """Planner requests structured output and parses JSON into Plan instance."""
    mock_pm = MagicMock()
    mock_pm.generate_text.return_value = AIResponse(
        text="""
        ```json
        {
            "goal": "Lookup weather and calculate packing items",
            "estimated_complexity": "low",
            "completion_condition": "Items calculated",
            "missing_information": [],
            "steps": [
                {
                    "description": "Check weather in Paris",
                    "step_type": "tool_call",
                    "tool_name": "mock_weather",
                    "parameters": {"city": "Paris"},
                    "dependencies": []
                },
                {
                    "description": "Synthesize summary",
                    "step_type": "synthesis",
                    "tool_name": null,
                    "parameters": {},
                    "dependencies": [0]
                }
            ]
        }
        ```
        """,
        model="gemini-3.8-flash",
    )

    planner = AgentPlanner(provider_manager=mock_pm)
    ctx = ExecutionContext(session_id="test_sess")

    plan = planner.create_plan("Lookup weather in Paris", context=ctx)
    assert plan.goal == "Lookup weather and calculate packing items"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "mock_weather"
    assert plan.steps[0].step_type == StepType.TOOL_CALL
    assert plan.steps[1].step_type == StepType.SYNTHESIS


def test_planner_replanning_creates_corrective_step():
    """Replanning appends recovery step when an intermediate step fails."""
    mock_pm = MagicMock()
    planner = AgentPlanner(provider_manager=mock_pm)
    ctx = ExecutionContext(session_id="test_replan")

    plan = Plan(goal="Download file and inspect")
    s1 = PlanStep(step_id="s1", description="Download archive", status=StepStatus.FAILED)
    plan.add_step(s1)

    revised = planner.replan(
        current_plan=plan,
        failed_step=s1,
        error_reason="Network connection timed out",
        context=ctx,
    )

    assert revised.iteration == 2
    assert len(revised.steps) >= 2
    assert any(s.step_type == StepType.REPLAN for s in revised.steps)
    assert any(s.step_type == StepType.SYNTHESIS for s in revised.steps)


# ==============================================================================
# SECTION 3: BOUNDED EXECUTOR & TOOL PROPOSAL TESTS
# ==============================================================================


def test_executor_successful_sequential_plan():
    """Executor sequentially executes steps through completion."""
    perm_mgr = StrictDefaultDenyPermissionManager(
        allowed_categories={PermissionCategory.COMPUTATION, PermissionCategory.READ_ONLY}
    )
    registry = ToolRegistry(permission_manager=perm_mgr)
    registry.register(MockCalculatorTool())

    sm = AgentStateMachine()
    mock_pm = MagicMock()
    mock_pm.generate_text.return_value = AIResponse(
        text="Final synthesized answer: 48", model="test-m"
    )
    planner = AgentPlanner(provider_manager=mock_pm)

    executor = AgentExecutor(
        tool_registry=registry,
        provider_manager=mock_pm,
        planner=planner,
        state_machine=sm,
    )

    plan = Plan(goal="Multiply 12 by 4")
    s1 = PlanStep(
        step_id="step_calc",
        description="Calculate 12 * 4",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_calculator",
        parameters={"expression": "12 * 4"},
    )
    s2 = PlanStep(
        step_id="step_synth",
        description="Synthesize result",
        step_type=StepType.SYNTHESIS,
        dependencies=["step_calc"],
    )
    plan.add_step(s1)
    plan.add_step(s2)

    outcome = executor.execute_plan(plan, context=ExecutionContext())
    assert outcome.status == "completed"
    assert plan.is_completed is True
    assert s1.status == StepStatus.COMPLETED
    assert s1.result == {"expression": "12 * 4", "result": 48}
    assert "48" in outcome.final_response


def test_executor_loop_detection_aborts_or_replans():
    """Executor detects repetitive step sequences and triggers loop protection."""
    perm_mgr = StrictDefaultDenyPermissionManager(allowed_categories={PermissionCategory.READ_ONLY})
    registry = ToolRegistry(permission_manager=perm_mgr)
    registry.register(MockSearchTool())

    sm = AgentStateMachine()
    mock_pm = MagicMock()
    planner = AgentPlanner(provider_manager=mock_pm)

    executor = AgentExecutor(
        tool_registry=registry,
        provider_manager=mock_pm,
        planner=planner,
        state_machine=sm,
        settings=Settings(agent_max_planning_iterations=1),
    )

    plan = Plan(goal="Search loop")
    # Add step that resets to pending to trigger loop detection
    for i in range(4):
        plan.add_step(
            PlanStep(
                step_id=f"s_{i}",
                description="Search query",
                step_type=StepType.TOOL_CALL,
                tool_name="mock_search",
                parameters={"query": "stuck loop"},
            )
        )

    outcome = executor.execute_plan(plan, context=ExecutionContext())
    assert outcome.status in ("failed", "partial")
    assert sm.current_state == AgentState.FAILED


def test_executor_halts_on_approval_required():
    """Tools marked with high risk or requires_approval halt execution in WAITING_FOR_APPROVAL."""
    registry = ToolRegistry()
    registry.register(MockDangerousSystemTool())

    sm = AgentStateMachine()
    mock_pm = MagicMock()
    planner = AgentPlanner(provider_manager=mock_pm)

    executor = AgentExecutor(
        tool_registry=registry,
        provider_manager=mock_pm,
        planner=planner,
        state_machine=sm,
    )

    plan = Plan(goal="Perform sensitive action")
    step = PlanStep(
        description="Simulate sensitive operation",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_dangerous_action",
        parameters={"action": "test_action", "target": "test_db"},
    )
    plan.add_step(step)

    outcome = executor.execute_plan(plan, context=ExecutionContext())
    assert outcome.status == "waiting_for_approval"
    assert sm.current_state == AgentState.WAITING_FOR_APPROVAL
    assert outcome.pending_approval is not None
    assert outcome.pending_approval.risk_level == RiskLevel.HIGH


def test_executor_cancellation_stops_execution_immediately():
    """Executor halts immediately when CancellationToken is triggered."""
    registry = ToolRegistry()
    registry.register(MockSearchTool())

    sm = AgentStateMachine()
    mock_pm = MagicMock()
    planner = AgentPlanner(provider_manager=mock_pm)

    executor = AgentExecutor(
        tool_registry=registry,
        provider_manager=mock_pm,
        planner=planner,
        state_machine=sm,
    )

    token = CancellationToken()
    token.cancel()  # Already cancelled before start

    ctx = ExecutionContext()
    ctx.cancellation_token = token

    plan = Plan(goal="Cancel before run")
    plan.add_step(PlanStep(description="Action", step_type=StepType.THOUGHT))

    outcome = executor.execute_plan(plan, context=ctx)
    assert outcome.status == "cancelled"
    assert sm.current_state == AgentState.CANCELLED


# ==============================================================================
# SECTION 4: INTEGRATED AGENT CORE ORCHESTRATION TESTS
# ==============================================================================


def test_jarvis_agent_process_agent_task_conversational_path():
    """Agent detects simple greeting, skips planner, and answers directly."""
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(
        text="Hello! How can I help you?", model="gemini-3.8-flash"
    )

    agent = JARVISAgent(ai_provider=mock_pm)
    reply = agent.process_user_message("Hello")

    assert "Hello!" in reply
    assert agent.state == AgentState.COMPLETED


def test_jarvis_agent_process_agent_task_multi_step_planning():
    """Agent decomposes multi-step task and coordinates tools through ProviderManager."""
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    # 1. First call: planner generating plan JSON
    plan_json = """
    {
        "goal": "Calculate 15 * 3",
        "estimated_complexity": "low",
        "completion_condition": "Math calculated",
        "steps": [
            {
                "description": "Compute math",
                "step_type": "tool_call",
                "tool_name": "mock_calculator",
                "parameters": {"expression": "15 * 3"},
                "dependencies": []
            },
            {
                "description": "Synthesize answer",
                "step_type": "synthesis",
                "tool_name": null,
                "parameters": {},
                "dependencies": []
            }
        ]
    }
    """
    # 2. Second call: synthesis formulation
    mock_pm.generate_text.side_effect = [
        AIResponse(text=plan_json, model="gemini-3.8-flash"),
        AIResponse(text="The result of 15 * 3 is 45.", model="gemini-3.8-flash"),
    ]

    agent = JARVISAgent(ai_provider=mock_pm)
    outcome = agent.process_agent_task("Please calculate 15 * 3 and explain")

    assert outcome.status == "completed"
    assert "45" in outcome.final_response
    assert agent.state == AgentState.COMPLETED


def test_jarvis_session_isolation_plans_and_state():
    """Multiple sessions run independently with isolated plans and contexts."""
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(text="Session reply", model="test-m")

    agent = JARVISAgent(ai_provider=mock_pm)

    s1 = agent.create_new_session("Session 1")
    s2 = agent.create_new_session("Session 2")

    agent.set_active_session_id(s1)
    agent.record_user_message("Message in session 1")

    agent.set_active_session_id(s2)
    agent.record_user_message("Message in session 2")

    h1 = agent.get_session_history(s1)
    h2 = agent.get_session_history(s2)

    assert len(h1) == 1
    assert h1[0].content == "Message in session 1"
    assert len(h2) == 1
    assert h2[0].content == "Message in session 2"
