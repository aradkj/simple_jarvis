"""Comprehensive regression test suite for Phase 3 Approval Workflow and Security Gates."""

import threading
import time
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from core.approval import ApprovalManager
from core.events import EventBus
from core.execution_context import CancellationToken, ExecutionContext
from core.executor import AgentExecutor, LoopDetectedError
from core.permissions import (
    PermissionCategory,
    StrictDefaultDenyPermissionManager,
)
from core.planner import AgentPlanner, Plan, PlanStep, StepStatus, StepType
from core.state_machine import AgentState, AgentStateMachine
from core.tool_proposal import ProposalStatus, RiskLevel, ToolDefinition, ToolProposal
from core.tool_registry import ToolRegistry
from tools.base import BaseTool, ToolResult


class HighRiskInput(BaseModel):
    action: str = Field(description="Action to execute")


class CriticalRiskInput(BaseModel):
    cmd: str = Field(description="Command to execute")


class LowRiskInput(BaseModel):
    x: int = Field(default=0, description="Number to double")


class MockHighRiskTool(BaseTool):
    """Simulated high-risk tool for testing approval gates."""

    name = "mock_high_risk_tool"
    description = "High risk system action requiring explicit approval"
    category = PermissionCategory.SYSTEM
    input_schema = HighRiskInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, HighRiskInput)
        return ToolResult.success(data={"action_executed": params.action})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            parameters_schema={"action": {"type": "string"}},
        )


class MockCriticalRiskTool(BaseTool):
    """Simulated critical-risk tool."""

    name = "mock_critical_tool"
    description = "Critical risk action that must always require approval"
    category = PermissionCategory.SYSTEM
    input_schema = CriticalRiskInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, CriticalRiskInput)
        return ToolResult.success(data={"cmd_executed": params.cmd})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.CRITICAL,
            requires_approval=False,  # Should still require approval due to CRITICAL risk level
            parameters_schema={"cmd": {"type": "string"}},
        )


class MockLowRiskTool(BaseTool):
    """Simulated low-risk tool."""

    name = "mock_low_risk_tool"
    description = "Low risk computation"
    category = PermissionCategory.COMPUTATION
    input_schema = LowRiskInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, LowRiskInput)
        return ToolResult.success(data={"doubled": params.x * 2})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            parameters_schema={"x": {"type": "integer"}},
        )


@pytest.fixture
def test_setup():
    event_bus = EventBus()
    permission_manager = StrictDefaultDenyPermissionManager(
        allowed_categories={PermissionCategory.COMPUTATION}
    )
    tool_registry = ToolRegistry(
        permission_manager=permission_manager,
        event_bus=event_bus,
    )
    high_tool = MockHighRiskTool()
    crit_tool = MockCriticalRiskTool()
    low_tool = MockLowRiskTool()
    tool_registry.register(high_tool)
    tool_registry.register(crit_tool)
    tool_registry.register(low_tool)

    approval_manager = ApprovalManager(
        event_bus=event_bus,
        permission_manager=permission_manager,
    )
    state_machine = AgentStateMachine(session_id="session_test", event_bus=event_bus)

    from config import get_settings

    settings = get_settings()

    mock_provider = MagicMock()
    planner = AgentPlanner(
        provider_manager=mock_provider,
        settings=settings,
        event_bus=event_bus,
    )

    executor = AgentExecutor(
        tool_registry=tool_registry,
        provider_manager=mock_provider,
        planner=planner,
        state_machine=state_machine,
        permission_manager=permission_manager,
        approval_manager=approval_manager,
        settings=settings,
        event_bus=event_bus,
    )

    return {
        "event_bus": event_bus,
        "permission_manager": permission_manager,
        "tool_registry": tool_registry,
        "approval_manager": approval_manager,
        "state_machine": state_machine,
        "executor": executor,
        "planner": planner,
        "settings": settings,
    }


def test_high_risk_and_critical_risk_require_approval(test_setup):
    """Verify that HIGH and CRITICAL risk tools ALWAYS require approval."""
    executor = test_setup["executor"]
    state_machine = test_setup["state_machine"]

    # 1. High risk tool step
    step = PlanStep(
        step_id="step_1",
        description="Run high risk tool",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_high_risk_tool",
        parameters={"action": "reboot"},
    )
    plan = Plan(goal="Test high risk", steps=[step], session_id="session_test")
    ctx = ExecutionContext(session_id="session_test")

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=False)
    assert outcome.status == "waiting_for_approval"
    assert state_machine.current_state == AgentState.WAITING_FOR_APPROVAL
    assert outcome.pending_approval is not None
    assert outcome.pending_approval.tool_name == "mock_high_risk_tool"
    assert outcome.pending_approval.risk_level == RiskLevel.HIGH


def test_critical_risk_tool_requires_approval_even_if_flag_false(test_setup):
    """Critical risk tool must require approval even if requires_approval attribute is False."""
    executor = test_setup["executor"]
    step = PlanStep(
        step_id="step_crit",
        description="Run critical tool",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_critical_tool",
        parameters={"cmd": "format"},
    )
    plan = Plan(goal="Test critical risk", steps=[step], session_id="session_test")
    ctx = ExecutionContext(session_id="session_test")

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=False)
    assert outcome.status == "waiting_for_approval"
    assert outcome.pending_approval.risk_level == RiskLevel.CRITICAL


def test_low_risk_auto_approve(test_setup):
    """Low risk tool auto-executes when agent_auto_approve_low_risk is enabled."""
    executor = test_setup["executor"]
    test_setup["settings"].agent_auto_approve_low_risk = True

    step = PlanStep(
        step_id="step_low",
        description="Run low risk computation",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_low_risk_tool",
        parameters={"x": 5},
    )
    plan = Plan(goal="Test low risk", steps=[step], session_id="session_test")
    ctx = ExecutionContext(session_id="session_test")

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=False)
    assert outcome.status == "completed"
    assert step.result == {"doubled": 10}


def test_approval_lifecycle_async_approval(test_setup):
    """Test full async approval flow: wait_for_approval=True, background thread decision."""
    executor = test_setup["executor"]
    approval_manager = test_setup["approval_manager"]

    step = PlanStep(
        step_id="step_async",
        description="Run high risk tool with approval",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_high_risk_tool",
        parameters={"action": "deploy_update"},
    )
    plan = Plan(goal="Test async approval", steps=[step], session_id="session_test")
    ctx = ExecutionContext(session_id="session_test")

    def approve_in_background():
        for _ in range(50):
            prop = approval_manager.get_pending_proposal(session_id="session_test")
            if prop:
                approval_manager.submit_decision(
                    proposal_id=prop.proposal_id,
                    approved=True,
                    session_id="session_test",
                )
                return
            time.sleep(0.02)

    bg_thread = threading.Thread(target=approve_in_background)
    bg_thread.start()

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=True)
    bg_thread.join()

    assert outcome.status == "completed"
    assert step.status == StepStatus.COMPLETED
    assert step.result == {"action_executed": "deploy_update"}


def test_approval_lifecycle_rejection_triggers_replanning(test_setup):
    """Test that rejecting a proposal triggers replanning or safe failure."""
    executor = test_setup["executor"]
    approval_manager = test_setup["approval_manager"]
    planner = test_setup["planner"]

    step = PlanStep(
        step_id="step_rej",
        description="Run high risk tool to reject",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_high_risk_tool",
        parameters={"action": "delete_all"},
    )
    plan = Plan(goal="Test rejection", steps=[step], session_id="session_test")
    ctx = ExecutionContext(session_id="session_test")

    recovery_step = PlanStep(
        step_id="step_fallback",
        description="Safe fallback thought",
        step_type=StepType.THOUGHT,
    )
    recovery_plan = Plan(goal="Safe fallback", steps=[recovery_step], session_id="session_test")
    planner.replan = MagicMock(return_value=recovery_plan)

    def reject_in_background():
        for _ in range(50):
            prop = approval_manager.get_pending_proposal(session_id="session_test")
            if prop:
                approval_manager.submit_decision(
                    proposal_id=prop.proposal_id,
                    approved=False,
                    session_id="session_test",
                    reason="User rejected action",
                )
                return
            time.sleep(0.02)

    bg_thread = threading.Thread(target=reject_in_background)
    bg_thread.start()

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=True)
    bg_thread.join()

    assert outcome.status == "completed"
    assert recovery_step.status == StepStatus.COMPLETED
    planner.replan.assert_called_once()


def test_stale_and_duplicate_decision_rejected(test_setup):
    """Stale or duplicate decisions on proposals must be rejected."""
    approval_manager = test_setup["approval_manager"]
    proposal = ToolProposal(
        proposal_id="prop_1",
        session_id="session_1",
        tool_name="mock_tool",
        arguments={"a": 1},
        status=ProposalStatus.PENDING_APPROVAL,
    )
    with approval_manager._lock:
        approval_manager._pending_proposals["prop_1"] = proposal
        approval_manager._decision_events["prop_1"] = threading.Event()
        approval_manager._initial_signatures["prop_1"] = proposal.compute_signature()

    # First decision succeeds
    success1 = approval_manager.submit_decision(
        proposal_id="prop_1", approved=True, session_id="session_1"
    )
    assert success1 is True
    assert proposal.status == ProposalStatus.APPROVED

    # Duplicate decision fails
    success2 = approval_manager.submit_decision(
        proposal_id="prop_1", approved=True, session_id="session_1"
    )
    assert success2 is False

    # Stale unknown proposal decision fails
    success3 = approval_manager.submit_decision(
        proposal_id="non_existent", approved=True, session_id="session_1"
    )
    assert success3 is False


def test_cross_session_decision_rejected(test_setup):
    """Decisions from different session_ids must be rejected."""
    approval_manager = test_setup["approval_manager"]
    proposal = ToolProposal(
        proposal_id="prop_2",
        session_id="session_A",
        tool_name="mock_tool",
        arguments={"a": 1},
        status=ProposalStatus.PENDING_APPROVAL,
    )
    with approval_manager._lock:
        approval_manager._pending_proposals["prop_2"] = proposal
        approval_manager._decision_events["prop_2"] = threading.Event()
        approval_manager._initial_signatures["prop_2"] = proposal.compute_signature()

    # Attempt to decide from session_B
    success = approval_manager.submit_decision(
        proposal_id="prop_2", approved=True, session_id="session_B"
    )
    assert success is False
    assert proposal.status == ProposalStatus.PENDING_APPROVAL


def test_tamper_detection_invalidates_approval():
    """Modifying tool arguments after approval invalidates approval signature."""
    proposal = ToolProposal(
        proposal_id="prop_tamper",
        session_id="session_1",
        tool_name="mock_high_risk_tool",
        arguments={"action": "clean_tmp"},
    )
    proposal.approve()
    assert proposal.is_valid_approval() is True

    # Tamper with arguments
    proposal.arguments["action"] = "rm_rf_root"
    assert proposal.is_valid_approval() is False


def test_cancellation_while_waiting_for_approval(test_setup):
    """Cancelling context while waiting for approval cleanly aborts without hanging."""
    executor = test_setup["executor"]
    approval_manager = test_setup["approval_manager"]
    state_machine = test_setup["state_machine"]

    step = PlanStep(
        step_id="step_cancel",
        description="Wait for approval and cancel",
        step_type=StepType.TOOL_CALL,
        tool_name="mock_high_risk_tool",
        parameters={"action": "hold"},
    )
    plan = Plan(goal="Test cancel", steps=[step], session_id="session_test")
    cancellation_token = CancellationToken()
    ctx = ExecutionContext(session_id="session_test", cancellation_token=cancellation_token)

    def cancel_after_pause():
        for _ in range(50):
            prop = approval_manager.get_pending_proposal(session_id="session_test")
            if prop:
                time.sleep(0.05)
                cancellation_token.cancel()
                return
            time.sleep(0.02)

    bg_thread = threading.Thread(target=cancel_after_pause)
    bg_thread.start()

    outcome = executor.execute_plan(plan=plan, context=ctx, wait_for_approval=True)
    bg_thread.join()

    assert outcome.status == "cancelled"
    assert state_machine.current_state == AgentState.CANCELLED


def test_loop_detection_allows_legitimate_repeated_actions(test_setup):
    """Loop detection halts identical calls but allows repeated actions with distinct parameters."""
    executor = test_setup["executor"]

    # Repeated calls with different parameters
    for i in range(5):
        step = PlanStep(
            step_id=f"step_{i}",
            description=f"Action step {i}",
            step_type=StepType.TOOL_CALL,
            tool_name="search",
            parameters={"query": f"item_{i}"},
        )
        # Should not raise
        executor._check_for_loops(step)

    # Identical calls 3 times must raise
    identical_step = PlanStep(
        step_id="step_same",
        description="Identical query",
        step_type=StepType.TOOL_CALL,
        tool_name="search",
        parameters={"query": "stuck_item"},
    )
    executor._check_for_loops(identical_step)
    executor._check_for_loops(identical_step)
    with pytest.raises(LoopDetectedError):
        executor._check_for_loops(identical_step)
