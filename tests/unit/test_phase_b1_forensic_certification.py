"""Comprehensive Forensic Audit & Boundary Certification Suite for JARVIS Phase B.1.

Strictly verifies:
1. Decision Gateway: fail-closed for unknown tools/capabilities, approval signature tamper resistance,
   replay prevention on terminal proposals, active context read-only and prohibition policy blocks.
2. Risk Classification: sensitive keyword handling in tool names vs filenames, irreversible flag inspection.
3. 10-Criteria Evaluator: canonical criteria, normalized weights, hard constraint disqualification.
4. Persian Understanding: subjunctive negations, conditions, command prohibitions, scope constraints,
   and technical identifiers preservation without path/URL corruption.
5. Dynamic Reasoning Integration: solver decomposition translation into executable plan architecture.
6. GUI Settings Persistence: atomic .env writing with comment and order preservation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from config import save_env_settings
from core.decision.engine import DecisionEngine, RiskClassifier
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor
from core.permissions import PermissionCategory, StrictDefaultDenyPermissionManager
from core.persian import PersianIntentAnalyzer, PersianTextNormalizer
from core.persian.models import PersianIntentType, RiskLevel
from core.planner import AgentPlanner, Plan, PlanStep, StepStatus, StepType
from core.reasoning.evaluator import AlternativeEvaluator
from core.state_machine import AgentStateMachine
from core.tool_proposal import (
    ProposalStatus,
    ToolDefinition,
    ToolProposal,
)
from core.tool_proposal import (
    RiskLevel as ProposalRiskLevel,
)
from core.tool_registry import ToolRegistry
from tools.base import BaseTool, ToolResult

# --- MOCK TOOL DEFINITIONS FOR ADVERSARIAL TESTING ---


class SafeDummyInput(BaseModel):
    query: str = Field(default="")


class SafeDummyTool(BaseTool):
    name = "dummy_inspect_tool"
    description = "Safe diagnostic tool"
    category = PermissionCategory.READ_ONLY
    input_schema = SafeDummyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        return ToolResult.success(data={"status": "inspected"})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=ProposalRiskLevel.LOW,
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )


class DeleteDummyTool(BaseTool):
    name = "dummy_delete_tool"
    description = "Simulated deletion tool"
    category = PermissionCategory.FILE_DELETE
    input_schema = SafeDummyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        return ToolResult.success(data={"status": "deleted"})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )


# ==============================================================================
# SECTION 1: DECISION GATEWAY & PROPOSAL REPLAY / TAMPER AUDIT
# ==============================================================================


def test_gateway_blocks_unregistered_tools():
    """Unregistered tools must immediately fail in executor and cannot be proposed or executed."""
    reg = ToolRegistry(
        permission_manager=StrictDefaultDenyPermissionManager(
            allowed_categories={PermissionCategory.READ_ONLY}
        )
    )
    executor = AgentExecutor(
        tool_registry=reg,
        provider_manager=MagicMock(),
        planner=MagicMock(),
        state_machine=AgentStateMachine(),
    )
    ctx = ExecutionContext(session_id="sec_test")
    plan = Plan(goal="Run unregistered", session_id="sec_test")
    step = PlanStep(
        step_id="s1",
        description="Run rogue",
        step_type=StepType.TOOL_CALL,
        tool_name="unregistered_rogue_tool",
    )

    outcome = executor._execute_single_step(step, plan, ctx)
    assert outcome == "replan_needed"
    assert step.status == StepStatus.FAILED
    assert "is not registered" in step.error


def test_gateway_fails_closed_on_unknown_tool_and_capability():
    """Unknown or undeclared tools must never default to READ_ONLY; they fail closed to DESTRUCTIVE."""
    classifier = RiskClassifier()
    # 1. Blank or unregistered tool name
    assert classifier.classify_risk(tool_name="") == RiskLevel.DESTRUCTIVE_OPERATION
    # 2. Completely unknown tool without metadata
    assert (
        classifier.classify_risk(tool_name="unvetted_custom_tool")
        == RiskLevel.DESTRUCTIVE_OPERATION
    )
    # 3. Tool with sensitive keywords in name fails closed to SENSITIVE_DATA_ACCESS
    assert classifier.classify_risk(tool_name="get_auth_token") == RiskLevel.SENSITIVE_DATA_ACCESS
    assert classifier.classify_risk(tool_name="query_secret_key") == RiskLevel.SENSITIVE_DATA_ACCESS


def test_proposal_signature_tamper_proofing():
    """Modifying arguments after approval invalidates approval signature."""
    proposal = ToolProposal(
        tool_name="write_file",
        arguments={"path": "safe.txt", "data": "hello"},
        risk_level=ProposalRiskLevel.HIGH,
        requires_approval=True,
    )
    assert not proposal.is_valid_approval()

    # User approves
    proposal.approve()
    assert proposal.is_valid_approval()

    # Adversary alters target argument after approval
    proposal.arguments["path"] = "C:\\Windows\\System32\\critical.dll"
    assert not proposal.is_valid_approval(), (
        "Tampered parameters must fail approval signature validation"
    )


def test_proposal_replay_prevention_on_terminal_states():
    """Executed or failed proposals cannot be re-approved or replayed."""
    proposal = ToolProposal(
        tool_name="dummy_tool",
        arguments={"x": 1},
        risk_level=ProposalRiskLevel.HIGH,
        requires_approval=True,
    )
    proposal.approve()
    proposal.mark_executed(result={"ok": True})
    assert proposal.status == ProposalStatus.EXECUTED
    assert not proposal.is_valid_approval(), "Executed proposal must not be valid for re-execution"

    with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
        proposal.approve()


def test_gateway_enforces_active_read_only_and_prohibition_policies():
    """Gateway blocks modification and prohibited actions when active in context."""
    engine = DecisionEngine()
    ctx = ExecutionContext(session_id="ctx_sec")
    ctx.metadata["read_only"] = True
    ctx.metadata["prohibited_actions"] = ["no_unauthorized_deletion", "do_not_touch_database"]

    # Read-only tool is allowed
    allowed, risk, req_app, rat = engine.evaluate_tool_execution(
        tool_name="system_info",
        context=ctx,
    )
    assert allowed is True
    assert risk == RiskLevel.READ_ONLY

    # 2. Modification tool is blocked by read_only context
    allowed, risk, req_app, rat = engine.evaluate_tool_execution(
        tool_name="file_write_text",
        params={"file_path": "test.txt"},
        context=ctx,
    )
    assert allowed is False
    assert "read-only" in rat

    # 3. Clear read_only to verify deletion tool blocked specifically by prohibition policy
    ctx.metadata["read_only"] = False
    allowed, risk, req_app, rat = engine.evaluate_tool_execution(
        tool_name="file_delete",
        params={"file_path": "data.txt"},
        context=ctx,
    )
    assert allowed is False
    assert "prohibition policy" in rat

    # Targeted prohibition blocked
    allowed, risk, req_app, rat = engine.evaluate_tool_execution(
        tool_name="db_query",
        params={"target": "database_master"},
        context=ctx,
    )
    assert allowed is False
    assert "explicitly prohibited" in rat


# ==============================================================================
# SECTION 2: RISK CLASSIFICATION & FALSE POSITIVE PREVENTION
# ==============================================================================


def test_risk_classifier_false_positive_prevention():
    """Classifier does not trigger false sensitive or irreversible alarms on benign paths/content."""
    classifier = RiskClassifier()

    # 1. Benign filename containing 'secret' or 'token'
    risk = classifier.classify_risk(
        tool_name="file_read_text",
        params={"file_path": "C:/docs/secret_sauce_recipe.txt"},
        tool_metadata={"category": PermissionCategory.FILE_READ},
    )
    assert risk == RiskLevel.READ_ONLY

    # 2. Benign HTML content containing the word 'automatically'
    risk = classifier.classify_risk(
        tool_name="file_write_text",
        params={
            "file_path": "Desktop/page.html",
            "content": "This page was automatically generated.",
        },
        tool_metadata={"category": PermissionCategory.FILE_WRITE},
    )
    assert risk == RiskLevel.REVERSIBLE_MODIFICATION

    # 3. Explicit credential parameter triggers SENSITIVE_DATA_ACCESS
    risk = classifier.classify_risk(
        tool_name="file_read_text",
        params={"file_path": "docs.txt", "password": "supersecretpassword"},
    )
    assert risk == RiskLevel.SENSITIVE_DATA_ACCESS

    # 4. Explicit destructive flag triggers IRREVERSIBLE_OPERATION
    risk = classifier.classify_risk(
        tool_name="file_delete",
        params={"file_path": "data/", "recursive": True, "force": True},
        tool_metadata={"category": PermissionCategory.FILE_DELETE},
    )
    assert risk == RiskLevel.IRREVERSIBLE_OPERATION


def test_risk_classifier_agent_modes():
    """DecisionEngine enforces distinct behavior across autonomous, balanced, and strict modes."""
    engine = DecisionEngine()

    class MockContext:
        def __init__(self, mode: str):
            self.agent_mode = mode
            self.auto_approve = False

    # Autonomous mode executes reversible modification without prompt
    _, _, req_auto, _ = engine.evaluate_tool_execution(
        tool_name="file_write_text",
        context=MockContext("autonomous"),
    )
    assert req_auto is False

    # Balanced mode requests confirmation for reversible modification
    _, _, req_bal, _ = engine.evaluate_tool_execution(
        tool_name="file_write_text",
        context=MockContext("balanced"),
    )
    assert req_bal is True

    # Strict mode requests confirmation for reversible modification
    _, _, req_strict, _ = engine.evaluate_tool_execution(
        tool_name="file_write_text",
        context=MockContext("strict"),
    )
    assert req_strict is True

    # High-risk / Destructive operations ALWAYS require confirmation across all modes
    for mode in ("autonomous", "balanced", "strict"):
        _, risk, req_dest, _ = engine.evaluate_tool_execution(
            tool_name="file_delete",
            params={"path": "db.sqlite"},
            context=MockContext(mode),
        )
        assert req_dest is True
        assert risk == RiskLevel.DESTRUCTIVE_OPERATION


# ==============================================================================
# SECTION 3: 10-CRITERIA EVALUATOR & HARD CONSTRAINT IMMUNITY
# ==============================================================================


def test_evaluator_ten_canonical_criteria_and_normalization():
    """AlternativeEvaluator strictly covers 10 canonical criteria with weights normalized to 1.0."""
    evaluator = AlternativeEvaluator()
    assert len(evaluator.DEFAULT_WEIGHTS) == 10
    expected_criteria = {
        "correctness",
        "security",
        "reliability",
        "complexity",
        "cost",
        "execution_time",
        "maintainability",
        "reversibility",
        "compatibility",
        "user_preferences",
    }
    assert set(evaluator.DEFAULT_WEIGHTS.keys()) == expected_criteria
    assert pytest.approx(sum(evaluator.weights.values()), 0.0001) == 1.0

    # Custom weights normalization with negative value handling
    custom = AlternativeEvaluator(weights={"correctness": 2.0, "security": 2.0, "cost": -1.0})
    assert pytest.approx(sum(custom.weights.values()), 0.0001) == 1.0
    assert custom.weights["correctness"] == 0.5
    assert custom.weights["security"] == 0.5
    assert custom.weights["cost"] == 0.0


def test_evaluator_hard_constraint_cannot_be_overridden_by_high_score():
    """Candidate violating hard constraint receives score 0.0 and cannot be recommended."""
    evaluator = AlternativeEvaluator()
    candidates = [
        {
            "option_id": "destructive_opt",
            "title": "Wipe entire database",
            "description": "Delete all tables immediately",
            "risk_level": RiskLevel.DESTRUCTIVE_OPERATION,
            "dimension_scores": {
                "correctness": 1.0,
                "reliability": 1.0,
                "complexity": 1.0,
                "cost": 1.0,
                "execution_time": 1.0,
                "maintainability": 1.0,
                "compatibility": 1.0,
                "user_preferences": 1.0,
            },
        },
        {
            "option_id": "safe_opt",
            "title": "Read-only inspection",
            "description": "Inspect schema without modifying",
            "risk_level": RiskLevel.READ_ONLY,
            "dimension_scores": {
                "correctness": 0.8,
                "security": 0.95,
                "reliability": 0.85,
                "reversibility": 1.0,
            },
        },
    ]

    # Evaluate with data preservation and read-only constraints
    ranked = evaluator.evaluate_candidates(
        objective="Inspect data",
        candidates=candidates,
        constraints=["preserve_existing_data", "read_only"],
    )

    destructive_opt = next(o for o in ranked if o.option_id == "destructive_opt")
    safe_opt = next(o for o in ranked if o.option_id == "safe_opt")

    assert destructive_opt.score == 0.0
    assert destructive_opt.is_recommended is False
    assert any("Violates hard constraint" in r for r in destructive_opt.reasons)

    assert safe_opt.score > 0.0
    assert safe_opt.is_recommended is True


# ==============================================================================
# SECTION 4: PERSIAN SEMANTIC NLU & DISAMBIGUATION EVALUATION
# ==============================================================================


def test_persian_subjunctive_and_command_negations():
    """Verify Persian negation with subjunctive verbs, negative commands, and prohibitions."""
    analyzer = PersianIntentAnalyzer()

    # Subjunctive negation with explicit target
    res1 = analyzer.interpret("اجازه نداری این پوشه رو حذف کنی")
    assert "no_unauthorized_deletion" in res1.prohibited_actions
    assert any("این پوشه" in p for p in res1.prohibited_actions)

    # Command execution negation
    res2 = analyzer.interpret("این دستور رو اجرا نکن")
    assert "no_execution" in res2.prohibited_actions
    assert any("دستور" in p for p in res2.prohibited_actions)

    # Unapproved transmission prohibition
    res3 = analyzer.interpret("بدون تأیید من چیزی ارسال نکن")
    assert "requires_user_confirmation" in res3.constraints
    assert "no_unauthorized_transmission" in res3.prohibited_actions


def test_persian_preconditions_and_scope_constraints():
    """Verify conditional preconditions and scope constraint extraction."""
    analyzer = PersianIntentAnalyzer()

    # Precondition extraction with subjunctive verb
    res1 = analyzer.interpret("فقط در صورتی که فایل وجود داشت تغییرش بده")
    assert len(res1.preconditions) > 0
    assert any(k in res1.preconditions for k in ("فایل وجود", "target_exists"))

    # Plural condition
    res2 = analyzer.interpret("اگر تستها موفق شدن، برنامه رو اجرا کن")
    assert any(k in res2.preconditions for k in ("تستها موفق", "tests_pass"))
    assert res2.primary_intent == PersianIntentType.APPLICATION_CONTROL

    # Scope constraint
    res3 = analyzer.interpret("فقط داخل پوشه پروژه کار کن")
    assert any("scoped_to_" in c for c in res3.constraints)


def test_persian_technical_language_and_path_preservation():
    """Normalizer strictly protects technical identifiers, paths, URLs, and commands."""
    normalizer = PersianTextNormalizer()
    sample = "فایل C:\\AI\\jarvis\\config.json و آدرس https://example.com/api/v1 رو بررسی کن."

    norm_text = normalizer.normalize(sample)
    assert "C:\\AI\\jarvis\\config.json" in norm_text
    assert "https://example.com/api/v1" in norm_text


# ==============================================================================
# SECTION 5: REASONING PLAN INTEGRATION INTO AGENT EXECUTION
# ==============================================================================


def test_reasoning_plan_translation_into_executable_steps():
    """Reasoning solver plan steps are translated and executable in AgentPlanner."""
    planner = AgentPlanner(provider_manager=MagicMock())
    ctx = ExecutionContext(session_id="solver_test")
    ctx.metadata["reasoning_plan_steps"] = [
        {
            "step": 1,
            "description": "Inspect diagnostic logs",
            "tool_hint": "dummy_inspect_tool",
            "parameters": {"query": "errors"},
        },
        {
            "step": 2,
            "description": "Synthesize summary",
            "tool_hint": None,
            "parameters": {},
        },
    ]

    tools = [SafeDummyTool.get_definition()]
    plan_dict = planner._build_fallback_plan_dict(
        goal="Diagnose errors",
        available_tools=tools,
        session_id="solver_test",
        context=ctx,
    )

    steps = plan_dict["steps"]
    tool_steps = [s for s in steps if s.get("step_type") == "tool_call"]
    assert len(tool_steps) >= 1
    assert tool_steps[0]["tool_name"] == "dummy_inspect_tool"


# ==============================================================================
# SECTION 6: ATOMIC SETTINGS PERSISTENCE AUDIT
# ==============================================================================


def test_save_env_settings_atomic_preservation(tmp_path: Path):
    """save_env_settings updates keys atomically while preserving comments and order."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Server Configuration\n"
        "APP_ENV=production\n"
        "PORT=8000\n"
        "# Custom note\n"
        "DATABASE_URL=sqlite:///data.db\n",
        encoding="utf-8",
    )

    save_env_settings(
        {
            "PERSIAN_UNDERSTANDING_ENABLED": "true",
            "REASONING_MODE": "deep",
            "PORT": "8080",
        },
        env_path=env_file,
    )

    content = env_file.read_text(encoding="utf-8")
    assert "# Server Configuration" in content
    assert "# Custom note" in content
    assert "PORT=8080" in content
    assert "APP_ENV=production" in content
    assert "PERSIAN_UNDERSTANDING_ENABLED=true" in content
    assert "REASONING_MODE=deep" in content
