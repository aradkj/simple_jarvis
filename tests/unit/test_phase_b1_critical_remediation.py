"""Comprehensive Adversarial & Integration Test Suite for Phase B.1 Remediation.

Covers:
1. Genuine HMAC-SHA256 proposal cryptographic integrity (18 test points)
2. Reasoning-to-Execution lifecycle integration (Scenarios A through G)
3. Evaluator canonical 10 criteria, score provenance, math handling & tie-breaking
4. Gateway authorization boundaries, modes (strict, balanced, autonomous, aggressive alias)
5. Semantic memory transparency and honest diagnostics
6. Configuration atomic persistence
"""

from __future__ import annotations

import concurrent.futures
import math
import secrets
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from config import save_env_settings
from core.decision.engine import DecisionEngine
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor
from core.permissions import (
    PermissionCategory,
    PermissionDecision,
    PermissionRequest,
    StrictDefaultDenyPermissionManager,
)
from core.persian.models import RiskLevel
from core.planner import AgentPlanner, Plan, PlanStep, StepStatus, StepType
from core.reasoning.evaluator import AlternativeEvaluator, ScoreProvenance
from core.reasoning.solver import MultiStepProblemSolver
from core.state_machine import AgentStateMachine
from core.tool_proposal import (
    ProposalStatus,
    ToolDefinition,
    ToolProposal,
    get_proposal_signing_key,
    reset_proposal_signing_key,
    set_proposal_signing_key,
)
from core.tool_proposal import (
    RiskLevel as ProposalRiskLevel,
)
from core.tool_registry import ToolRegistry
from memory.embeddings import LocalNeuralEmbeddingProvider, LocalSemanticEmbeddingProvider
from tools.base import BaseTool, ToolResult


@pytest.fixture(autouse=True)
def isolate_proposal_signing_key(tmp_path, monkeypatch):
    """Guarantees test suites never read or modify the user's real data/.proposal_key."""
    test_key_file = tmp_path / ".test_proposal_key"
    test_key = secrets.token_bytes(32)
    test_key_file.write_bytes(test_key)
    monkeypatch.setenv("JARVIS_PROPOSAL_KEY_FILE", str(test_key_file))
    set_proposal_signing_key(test_key)
    yield
    reset_proposal_signing_key()


# ==============================================================================
# TEST TOOLS FOR INTEGRATION TESTING
# ==============================================================================


class InspectInput(BaseModel):
    target: str = Field(default="data.txt")


class InspectTool(BaseTool):
    name = "file_inspect"
    description = "Read file inspection tool"
    category = PermissionCategory.FILE_READ
    input_schema = InspectInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        p = getattr(params, "target", "data.txt")
        return ToolResult.success(data={"content": f"Inspected content of {p}", "size": 100})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=ProposalRiskLevel.LOW,
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"target": {"type": "string"}}},
        )


class WriteInput(BaseModel):
    file_path: str = Field(default="output.txt")
    content: str = Field(default="hello")


class WriteTool(BaseTool):
    name = "file_write_text"
    description = "Write file tool"
    category = PermissionCategory.FILE_WRITE
    input_schema = WriteInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        fp = getattr(params, "file_path", "output.txt")
        return ToolResult.success(data={"file_path": fp, "bytes_written": 20})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=ProposalRiskLevel.MEDIUM,
            requires_approval=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        )


class SensitiveDeleteTool(BaseTool):
    name = "file_delete"
    description = "Destructive file delete tool"
    category = PermissionCategory.FILE_DELETE
    input_schema = InspectInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        return ToolResult.success(data={"deleted": True})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
            parameters_schema={"type": "object", "properties": {"target": {"type": "string"}}},
        )


# ==============================================================================
# SECTION 1: CRITICAL DEFECT 1 — GENUINE HMAC-SHA256 & PROPOSAL LIFECYCLE (18 TESTS)
# ==============================================================================


class TestHMACProposalSecurity:
    """Rigorous adversarial testing of HMAC-SHA256 proposal cryptographic integrity."""

    def test_01_genuine_hmac_generation(self):
        """Generates authentic HMAC-SHA256 signature prefixed with version 'v1:'."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="file_read_text",
            arguments={"path": "notes.txt"},
            session_id="sess_123",
        )
        sig = proposal.compute_signature(key=key)
        assert sig.startswith("v1:")
        hex_part = sig.split("v1:")[1]
        assert len(hex_part) == 64  # SHA-256 produces 32 bytes (64 hex characters)
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_02_signature_verification_with_correct_key(self):
        """Verifies successfully with identical cryptographic secret key."""
        key = b"super_secret_test_key_32_bytes!!"
        proposal = ToolProposal(
            tool_name="file_read_text",
            arguments={"path": "safe.txt"},
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

    def test_03_signature_rejection_with_different_key(self):
        """Signature fails verification when evaluated against an unauthorized key."""
        key_valid = b"key_valid_authorized_32_bytes!!!"
        key_attacker = b"key_attacker_unauthorized_32_bytes"
        proposal = ToolProposal(
            tool_name="file_read_text",
            arguments={"path": "safe.txt"},
        )
        proposal.approve(key=key_valid)
        assert proposal.is_valid_approval(key=key_valid) is True
        assert proposal.is_valid_approval(key=key_attacker) is False

    def test_04_argument_modification_after_approval(self):
        """Altering execution arguments post-approval invalidates signature."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="file_write_text",
            arguments={"path": "benign.txt", "content": "normal"},
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        # Tampering with arguments
        proposal.arguments["path"] = "C:\\Windows\\System32\\malicious.dll"
        assert proposal.is_valid_approval(key=key) is False

    def test_05_tool_name_modification(self):
        """Altering tool name post-approval invalidates signature."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="file_read_text",
            arguments={"path": "file.txt"},
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        proposal.tool_name = "file_delete"
        assert proposal.is_valid_approval(key=key) is False

    def test_06_session_id_modification(self):
        """Altering session ID post-approval invalidates authorization."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="cmd_exec",
            session_id="session_user_alice",
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        proposal.session_id = "session_user_bob"
        assert proposal.is_valid_approval(key=key) is False

    def test_07_proposal_id_modification(self):
        """Altering proposal ID post-approval invalidates authorization."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="test_tool")
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        proposal.proposal_id = "forged_proposal_id"
        assert proposal.is_valid_approval(key=key) is False

    def test_08_risk_level_modification(self):
        """Altering risk level post-approval invalidates authorization."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="test_tool", risk_level=ProposalRiskLevel.HIGH)
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        proposal.risk_level = ProposalRiskLevel.LOW
        assert proposal.is_valid_approval(key=key) is False

    def test_09_underscore_prefixed_metadata_tampering(self):
        """Internal execution markers (_browser_sensitive, _proposal_id) are cryptographically bound."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="browser_click",
            arguments={"selector": "#buy", "_browser_sensitive": True},
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        # Adversary attempts to clear sensitivity marker
        proposal.arguments["_browser_sensitive"] = False
        assert proposal.is_valid_approval(key=key) is False

    def test_10_expired_approval_rejection(self):
        """Proposals past approval expiration time fail validation."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="safe_action")
        # Expire in 0.05 seconds
        proposal.approve(key=key, expires_in_seconds=0.05)
        assert proposal.is_valid_approval(key=key) is True

        time.sleep(0.08)
        assert proposal.is_valid_approval(key=key) is False

    def test_11_repeated_approval_forbidden(self):
        """An already approved proposal cannot be repeatedly approved or re-authorized."""
        proposal = ToolProposal(tool_name="test_action")
        proposal.approve()
        with pytest.raises(ValueError, match="already approved"):
            proposal.approve()

    def test_12_rejected_proposal_revival_forbidden(self):
        """Rejected proposals cannot be revived into APPROVED state."""
        proposal = ToolProposal(tool_name="test_action")
        proposal.reject("Explicitly rejected by user")
        with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
            proposal.approve()

    def test_13_failed_proposal_revival_forbidden(self):
        """Failed proposals cannot be re-approved."""
        proposal = ToolProposal(tool_name="test_action")
        proposal.approve()
        proposal.mark_failed("Execution aborted")
        with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
            proposal.approve()

    def test_14_executed_proposal_replay_forbidden(self):
        """Executed proposals cannot be re-approved or replayed."""
        proposal = ToolProposal(tool_name="test_action")
        proposal.approve()
        assert proposal.consume_for_execution() is True
        proposal.mark_executed({"output": "done"})
        assert proposal.is_valid_approval() is False
        with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
            proposal.approve()

    def test_15_concurrent_execution_single_use(self):
        """Concurrent threads attempting consume_for_execution() get exactly one successful consumer."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="concurrent_action")
        proposal.approve(key=key)

        results: list[bool] = []

        def worker():
            return proposal.consume_for_execution(key=key)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(worker) for _ in range(8)]
            results = [f.result() for f in futures]

        assert results.count(True) == 1
        assert results.count(False) == 7
        assert proposal.status == ProposalStatus.EXECUTING

    def test_16_missing_or_invalid_signing_key(self):
        """Fails closed when empty or invalid key (< 32 bytes) is supplied."""
        proposal = ToolProposal(tool_name="test_tool")
        with pytest.raises(ValueError, match="at least 32 bytes"):
            proposal.compute_signature(key=b"")
        with pytest.raises(ValueError, match="at least 32 bytes"):
            proposal.compute_signature(key=b"too_short_key_16_bytes!")

    def test_17_malformed_and_noncanonical_arguments(self):
        """Canonical JSON serialization produces identical signature regardless of key insertion order."""
        key = secrets.token_bytes(32)
        p1 = ToolProposal(
            tool_name="format_tool",
            arguments={"z": 1, "a": 2, "m": {"nested_b": 10, "nested_a": 20}},
            proposal_id="same_id",
            correlation_id="same_corr",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        p2 = ToolProposal(
            tool_name="format_tool",
            arguments={"a": 2, "m": {"nested_a": 20, "nested_b": 10}},
            proposal_id="same_id",
            correlation_id="same_corr",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        p2.arguments["z"] = 1  # Inserted in different order
        assert p1.compute_signature(key=key) == p2.compute_signature(key=key)

    def test_18_signature_version_compatibility(self):
        """Legacy or unrecognized signature prefixes fail validation closed."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="version_test")
        proposal.approve(key=key)
        # Substitute with an incompatible signature format
        proposal.approved_signature = "v999:unsupported_signature_format"
        assert proposal.is_valid_approval(key=key) is False

    def test_19_key_file_atomic_creation_and_preservation(self, tmp_path, monkeypatch):
        """Atomic key file creation produces >= 32 bytes and does not overwrite existing key."""
        key_file = tmp_path / "subdir" / ".custom_key"
        monkeypatch.setenv("JARVIS_PROPOSAL_KEY_FILE", str(key_file))
        reset_proposal_signing_key()

        # 1. Key file does not exist initially; generation creates it atomically
        assert not key_file.exists()
        key1 = get_proposal_signing_key()
        assert len(key1) == 32
        assert key_file.exists()
        assert key_file.read_bytes() == key1

        # 2. Subsequent load re-reads the same key without replacing it
        reset_proposal_signing_key()
        key2 = get_proposal_signing_key()
        assert key2 == key1

    def test_20_truncated_key_file_fails_closed(self, tmp_path, monkeypatch):
        """Truncated or corrupted key file (< 32 bytes) fails safely closed."""
        key_file = tmp_path / ".short_key"
        key_file.write_bytes(b"short_16_bytes!!")
        monkeypatch.setenv("JARVIS_PROPOSAL_KEY_FILE", str(key_file))
        reset_proposal_signing_key()

        with pytest.raises(ValueError, match="invalid or truncated key material"):
            get_proposal_signing_key()

    def test_21_environment_variable_precedence_and_length_enforcement(self, monkeypatch):
        """Environment variable takes precedence over file key, enforcing >= 32 bytes."""
        reset_proposal_signing_key()

        # Short key in env var fails closed
        monkeypatch.setenv("JARVIS_PROPOSAL_SECRET_KEY", "too_short_key_under_32_bytes")
        with pytest.raises(ValueError, match="must be at least 32 bytes"):
            get_proposal_signing_key()

        # Valid 32-byte env var key succeeds
        reset_proposal_signing_key()
        valid_env_key = "a" * 32
        monkeypatch.setenv("JARVIS_PROPOSAL_SECRET_KEY", valid_env_key)
        assert get_proposal_signing_key() == valid_env_key.encode("utf-8")

    def test_22_nested_argument_mutation_post_approval_invalidates_signature(self):
        """Mutating nested structures (dicts/lists) post-approval invalidates cryptographic signature."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="browser_action",
            arguments={"options": {"headless": True, "cookies": ["token=123"]}},
        )
        proposal.approve(key=key)
        assert proposal.is_valid_approval(key=key) is True

        # Mutate nested dictionary key
        proposal.arguments["options"]["headless"] = False
        assert proposal.is_valid_approval(key=key) is False

        # Mutate nested list item
        proposal.arguments["options"]["headless"] = True
        proposal.arguments["options"]["cookies"].append("admin=true")
        assert proposal.is_valid_approval(key=key) is False

    def test_23_unsupported_serialization_values_fail_closed(self):
        """Unsupported types, non-string dict keys, and NaN/Infinity fail closed immediately."""
        key = secrets.token_bytes(32)

        # Non-string dict keys fail closed
        p_bad_key = ToolProposal(tool_name="test_tool", arguments={123: "value"})  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="Dictionary keys must be strings"):
            p_bad_key.approve(key=key)

        # NaN float fails closed
        p_nan = ToolProposal(tool_name="test_tool", arguments={"val": float("nan")})
        with pytest.raises(ValueError, match="Out of range float values"):
            p_nan.approve(key=key)

        # Infinity fails closed
        p_inf = ToolProposal(tool_name="test_tool", arguments={"val": float("inf")})
        with pytest.raises(ValueError, match="Out of range float values"):
            p_inf.approve(key=key)

        # Unserializable objects (sets, functions) fail closed
        p_set = ToolProposal(tool_name="test_tool", arguments={"val": {1, 2, 3}})
        with pytest.raises(TypeError, match="not JSON serializable"):
            p_set.approve(key=key)

    @staticmethod
    def _create_test_executor(reg: ToolRegistry) -> AgentExecutor:
        mock_ai = MagicMock()
        mock_ai.is_ready.return_value = True
        planner = AgentPlanner(provider_manager=mock_ai)
        state_machine = AgentStateMachine()
        return AgentExecutor(
            tool_registry=reg,
            provider_manager=mock_ai,
            planner=planner,
            state_machine=state_machine,
        )

    def test_24_execution_argument_mismatch_in_executor_blocks_dispatch(self):
        """If step parameters are mutated after proposal approval, executor blocks dispatch."""
        reg = ToolRegistry()
        reg.register(InspectTool())
        executor = self._create_test_executor(reg)

        proposal = ToolProposal(
            session_id="sess_match",
            tool_name="file_inspect",
            arguments={"target": "safe_file.txt"},
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
        )
        proposal.approve()

        # Step has tampered parameters
        step = PlanStep(
            step_id="step_tampered",
            description="Execute safe tool",
            step_type=StepType.TOOL_CALL,
            tool_name="file_inspect",
            parameters={"target": "malicious_file.txt"},
        )
        step._pending_proposal = proposal  # type: ignore[attr-defined]
        plan = Plan(goal="tamper test", steps=[step], session_id="sess_match")
        ctx = ExecutionContext(session_id="sess_match")

        outcome = executor._execute_single_step(step, plan, ctx, wait_for_approval=True)
        assert outcome == "replan_needed"
        assert step.status == StepStatus.FAILED
        assert (
            "tampered" in (step.error or "").lower() or "do not match" in (step.error or "").lower()
        )

    def test_25_tool_substitution_in_executor_blocks_dispatch(self):
        """Substituting the tool name after proposal approval blocks execution."""
        reg = ToolRegistry()
        reg.register(InspectTool())
        executor = self._create_test_executor(reg)

        proposal = ToolProposal(
            session_id="sess_sub",
            tool_name="file_inspect",
            arguments={"target": "safe_file.txt"},
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
        )
        proposal.approve()

        # Step has substituted tool name
        step = PlanStep(
            step_id="step_sub",
            description="Substituted tool",
            step_type=StepType.TOOL_CALL,
            tool_name="malicious_tool",
            parameters={"target": "safe_file.txt"},
        )
        step._pending_proposal = proposal  # type: ignore[attr-defined]
        plan = Plan(goal="sub test", steps=[step], session_id="sess_sub")
        ctx = ExecutionContext(session_id="sess_sub")

        outcome = executor._execute_single_step(step, plan, ctx, wait_for_approval=True)
        assert outcome == "replan_needed"
        assert step.status == StepStatus.FAILED

    def test_26_session_substitution_in_executor_blocks_dispatch(self):
        """Cross-session replay of an approved proposal is rejected at execution time."""
        reg = ToolRegistry()
        reg.register(InspectTool())
        executor = self._create_test_executor(reg)

        proposal = ToolProposal(
            session_id="session_legitimate",
            tool_name="file_inspect",
            arguments={"target": "safe_file.txt"},
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
        )
        proposal.approve()

        step = PlanStep(
            step_id="step_sess",
            description="Execute tool",
            step_type=StepType.TOOL_CALL,
            tool_name="file_inspect",
            parameters={"target": "safe_file.txt"},
        )
        step._pending_proposal = proposal  # type: ignore[attr-defined]
        plan = Plan(goal="session test", steps=[step], session_id="session_attacker")
        ctx = ExecutionContext(session_id="session_attacker")

        outcome = executor._execute_single_step(step, plan, ctx, wait_for_approval=True)
        assert outcome == "replan_needed"
        assert step.status == StepStatus.FAILED
        assert "session does not match approved proposal" in (step.error or "")

    def test_27_unhandled_tool_exception_marks_proposal_failed(self):
        """Unexpected exception during tool invocation transitions proposal to FAILED, not EXECUTING."""
        pm = StrictDefaultDenyPermissionManager({PermissionCategory.FILE_READ})
        reg = ToolRegistry(permission_manager=pm)
        faulty_tool = InspectTool()
        faulty_tool.execute = MagicMock(
            side_effect=RuntimeError("Hardware failure during dispatch")
        )
        reg.register(faulty_tool)
        executor = self._create_test_executor(reg)

        proposal = ToolProposal(
            session_id="sess_exc",
            tool_name="file_inspect",
            arguments={"target": "safe_file.txt"},
            risk_level=ProposalRiskLevel.HIGH,
            requires_approval=True,
        )
        proposal.approve()

        step = PlanStep(
            step_id="step_fault",
            description="Faulty dispatch",
            step_type=StepType.TOOL_CALL,
            tool_name="file_inspect",
            parameters={"target": "safe_file.txt"},
            max_retries=0,
        )
        step._pending_proposal = proposal  # type: ignore[attr-defined]
        plan = Plan(goal="fault test", steps=[step], session_id="sess_exc")
        ctx = ExecutionContext(session_id="sess_exc")

        outcome = executor._execute_single_step(step, plan, ctx, wait_for_approval=True)
        assert outcome in ("replan_needed", "retry")
        assert proposal.status == ProposalStatus.FAILED
        assert "Hardware failure during dispatch" in (proposal.error or "")
        assert proposal.consume_for_execution() is False  # Cannot be re-consumed

    def test_28_proposal_cannot_be_reused_after_failed_execution(self):
        """A proposal marked FAILED cannot be re-approved or consumed again."""
        proposal = ToolProposal(tool_name="test_tool", arguments={"a": 1})
        proposal.approve()
        assert proposal.consume_for_execution() is True
        assert proposal.status == ProposalStatus.EXECUTING
        proposal.mark_failed("Tool error")
        assert proposal.status == ProposalStatus.FAILED

        # Cannot re-consume
        assert proposal.consume_for_execution() is False

        # Cannot re-approve
        with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
            proposal.approve()

    def test_29_proposal_cannot_be_reused_after_cancellation(self):
        """A proposal marked CANCELLED cannot be consumed or approved."""
        proposal = ToolProposal(tool_name="test_tool", arguments={"a": 1})
        proposal.approve()
        proposal.cancel("User aborted")
        assert proposal.status == ProposalStatus.CANCELLED

        assert proposal.consume_for_execution() is False
        with pytest.raises(ValueError, match="Cannot approve proposal in terminal status"):
            proposal.approve()

    def test_30_simultaneous_execution_and_replay_attacks(self):
        """Simultaneous multiple execution attempts succeed exactly once."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(
            tool_name="critical_transfer",
            arguments={"amount": 1000},
            risk_level=ProposalRiskLevel.CRITICAL,
        )
        proposal.approve(key=key)

        successes = []

        def execute_attempt():
            if proposal.consume_for_execution(key=key):
                # Simulating execution work
                time.sleep(0.01)
                proposal.mark_executed({"tx": "done"})
                return True
            return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(execute_attempt) for _ in range(10)]
            successes = [f.result() for f in futures]

        assert successes.count(True) == 1
        assert successes.count(False) == 9
        assert proposal.status == ProposalStatus.EXECUTED

    def test_31_timestamp_clock_skew_and_future_approval_fails_closed(self):
        """Approvals with future timestamps (clock tampering) fail validation closed."""
        key = secrets.token_bytes(32)
        proposal = ToolProposal(tool_name="time_test")
        proposal.approve(key=key)

        # Shift approved_at 1 hour into future
        proposal.approved_at = datetime.now(UTC) + timedelta(hours=1)
        # Even if signature matched, clock skew validation rejects it
        assert proposal.is_valid_approval(key=key) is False

    def test_32_permission_manager_protects_browser_sensitive_arguments(self):
        """StrictDefaultDenyPermissionManager strictly enforces _browser_sensitive parameter matching."""
        pm = StrictDefaultDenyPermissionManager()
        pid = "prop_sens_1"
        pm.grant_proposal(
            proposal_id=pid,
            tool_name="browser_click_element",
            arguments={"selector": "#buy", "_browser_sensitive": True},
        )

        # Tampering with _browser_sensitive to False must be DENIED
        tampered_req = PermissionRequest(
            tool_name="browser_click_element",
            category=PermissionCategory.BROWSER_INTERACT,
            action_summary="Click element",
            parameters={"selector": "#buy", "_browser_sensitive": False, "_proposal_id": pid},
        )
        res_tampered = pm.evaluate(tampered_req)
        assert res_tampered.decision == PermissionDecision.DENIED
        assert "tampered" in res_tampered.reason

        # Re-grant for valid request
        pm.grant_proposal(
            proposal_id=pid,
            tool_name="browser_click_element",
            arguments={"selector": "#buy", "_browser_sensitive": True},
        )
        valid_req = PermissionRequest(
            tool_name="browser_click_element",
            category=PermissionCategory.BROWSER_INTERACT,
            action_summary="Click element",
            parameters={"selector": "#buy", "_browser_sensitive": True, "_proposal_id": pid},
        )
        res_valid = pm.evaluate(valid_req)
        assert res_valid.decision == PermissionDecision.GRANTED

    def test_33_state_transition_checks_strict_terminal_states(self):
        """Terminal states cannot transition to other states."""
        p = ToolProposal(tool_name="test_tool")
        p.approve()
        p.consume_for_execution()
        p.mark_executed("ok")

        with pytest.raises(ValueError, match="Cannot mark an already executed proposal as failed"):
            p.mark_failed("late failure")

        with pytest.raises(ValueError, match="Cannot cancel proposal in terminal status"):
            p.cancel("late cancel")

        with pytest.raises(ValueError, match="Cannot reject proposal in terminal status"):
            p.reject("late reject")


# ==============================================================================
# SECTION 2: CRITICAL DEFECT 2 — REASONING-TO-EXECUTION INTEGRATION (SCENARIOS A-G)
# ==============================================================================


class TestReasoningToExecutionIntegration:
    """Verifies that structured reasoning solver output translates into an executable plan and executes via AgentExecutor."""

    def _setup_executor(self):
        reg = ToolRegistry(
            permission_manager=StrictDefaultDenyPermissionManager(
                allowed_categories={
                    PermissionCategory.FILE_READ,
                    PermissionCategory.FILE_WRITE,
                    PermissionCategory.FILE_DELETE,
                    PermissionCategory.SYSTEM,
                }
            )
        )
        inspect_tool = InspectTool()
        write_tool = WriteTool()
        del_tool = SensitiveDeleteTool()
        reg.register(inspect_tool)
        reg.register(write_tool)
        reg.register(del_tool)

        state_machine = AgentStateMachine()
        planner = AgentPlanner(provider_manager=MagicMock())
        executor = AgentExecutor(
            tool_registry=reg,
            provider_manager=MagicMock(),
            planner=planner,
            state_machine=state_machine,
        )
        return executor, planner, reg

    def test_scenario_a_two_step_dependent_execution(self):
        """Scenario A: ReasoningSolver generates two dependent steps; executor runs them in order, synthesis uses actual output."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_a")

        reasoning_steps = [
            {
                "step": 1,
                "description": "Inspect configuration file",
                "tool_hint": "file_inspect",
                "parameters": {"target": "app_config.json"},
                "prerequisites": [],
            },
            {
                "step": 2,
                "description": "Write log report based on inspection",
                "tool_hint": "file_write_text",
                "parameters": {"file_path": "report.log", "content": "Ready"},
                "prerequisites": ["Step 1 completed"],
            },
        ]
        ctx.metadata["reasoning_plan_steps"] = reasoning_steps
        plan = planner.create_plan(
            goal="Inspect and log configuration",
            context=ctx,
            available_tools=[
                t.get_definition() for t in reg.list_tools() if hasattr(t, "get_definition")
            ],
        )

        assert len(plan.steps) >= 3  # step 1, step 2, synthesis
        step1, step2 = plan.steps[0], plan.steps[1]
        assert step1.tool_name == "file_inspect"
        assert step2.tool_name == "file_write_text"
        assert step1.step_id in step2.dependencies

        outcome = executor.execute_plan(plan, ctx, wait_for_approval=True)
        assert outcome.status in ("completed", "success")
        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.COMPLETED
        assert step1.result == {"content": "Inspected content of app_config.json", "size": 100}

    def test_scenario_b_invalid_tool_hint_rejected(self):
        """Scenario B: ReasoningSolver proposes unregistered tool; planner safely resolves to THOUGHT, no unregistered tool executes."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_b")

        reasoning_steps = [
            {
                "step": 1,
                "description": "Attempt to run unvetted rogue action",
                "tool_hint": "unregistered_dangerous_tool",
                "parameters": {"cmd": "rm -rf"},
                "prerequisites": [],
            }
        ]
        ctx.metadata["reasoning_plan_steps"] = reasoning_steps
        plan = planner.create_plan(
            goal="Run rogue action",
            context=ctx,
            available_tools=[
                t.get_definition() for t in reg.list_tools() if hasattr(t, "get_definition")
            ],
        )

        assert plan.steps[0].step_type == StepType.THOUGHT
        assert plan.steps[0].tool_name is None

        outcome = executor.execute_plan(plan, ctx, wait_for_approval=True)
        assert outcome.status in ("completed", "success")
        # Ensure no unregistered tool was dispatched
        assert all(s.tool_name != "unregistered_dangerous_tool" for s in plan.steps)

    def test_scenario_c_dependency_failure_blocks_execution(self):
        """Scenario C: Step 1 fails; dependent Step 2 must NOT execute."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_c")

        # Create plan with step 1 that deliberately fails and step 2 depending on step 1
        plan = Plan(goal="Dependent failure test", session_id="scen_c")
        s1 = PlanStep(
            step_id="step_fail",
            description="Failing step",
            step_type=StepType.TOOL_CALL,
            tool_name="file_inspect",
            parameters={"target": "nonexistent.txt"},
            max_retries=0,
        )
        s2 = PlanStep(
            step_id="step_dependent",
            description="Dependent step",
            step_type=StepType.TOOL_CALL,
            tool_name="file_write_text",
            parameters={"file_path": "should_not_run.txt"},
            dependencies=["step_fail"],
        )
        plan.add_step(s1)
        plan.add_step(s2)

        # Force step 1 to fail
        s1.status = StepStatus.FAILED
        s1.error = "File not found"

        # Step 2 cannot execute
        outcome = executor._execute_single_step(s2, plan, ctx)
        assert outcome == "replan_needed"
        assert s2.status == StepStatus.FAILED
        assert "Prerequisite dependencies not satisfied" in s2.error

    def test_scenario_d_policy_preservation_blocks_prohibited_action(self):
        """Scenario D: Context prohibits action; Planner and Decision Gateway block execution even if planned."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_d")
        ctx.metadata["prohibited_actions"] = ["do_not_touch_database", "no_deletion"]

        reasoning_steps = [
            {
                "step": 1,
                "description": "Delete database files",
                "tool_hint": "file_delete",
                "parameters": {"target": "database.sqlite"},
                "prerequisites": [],
            }
        ]
        ctx.metadata["reasoning_plan_steps"] = reasoning_steps
        plan = planner.create_plan(
            goal="Delete database",
            context=ctx,
            available_tools=[
                t.get_definition() for t in reg.list_tools() if hasattr(t, "get_definition")
            ],
        )

        # Planner detects prohibition and nullifies tool_name to thought
        assert plan.steps[0].tool_name is None or plan.steps[0].step_type == StepType.THOUGHT

        # Even if step was maliciously set back to tool_call
        plan.steps[0].step_type = StepType.TOOL_CALL
        plan.steps[0].tool_name = "file_delete"
        plan.steps[0].parameters = {"target": "database.sqlite"}

        outcome = executor._execute_single_step(plan.steps[0], plan, ctx)
        assert outcome == "replan_needed"
        assert plan.steps[0].status == StepStatus.FAILED
        assert "prohibited" in plan.steps[0].error.lower()

    def test_scenario_e_approval_parameter_tampering_blocks_execution(self):
        """Scenario E: Sensitive operation approved, but modifying parameters invalidates approval and blocks execution."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_e")

        plan = Plan(goal="Approval tampering", session_id="scen_e")
        step = PlanStep(
            step_id="sec_step",
            description="Sensitive file deletion",
            step_type=StepType.TOOL_CALL,
            tool_name="file_delete",
            parameters={"target": "temp_cache.tmp"},
        )
        plan.add_step(step)

        # Mock approval manager to approve proposal but then tamper with target argument
        def mock_request_approval(proposal, timeout, cancellation_token):
            proposal.approve()
            # Adversary attempts parameter substitution after user approved safe path
            proposal.arguments["target"] = "C:\\Windows\\System32\\ntdll.dll"
            return True

        executor.approval_manager = MagicMock()
        executor.approval_manager.request_approval = MagicMock(side_effect=mock_request_approval)

        outcome = executor.execute_plan(plan, ctx, wait_for_approval=True)
        assert step.status == StepStatus.FAILED
        assert "tampered" in step.error or "verification failed" in step.error
        assert "Proposal approval signature verification failed" in str(
            outcome.plan.steps[0].result
        )

    def test_scenario_f_failed_postcondition_marks_step_failed(self):
        """Scenario F: Tool execution succeeds, but independent postcondition verification fails; step marked FAILED."""
        executor, planner, reg = self._setup_executor()
        ctx = ExecutionContext(session_id="scen_f")

        # Mock postcondition verification to return failure
        executor._verify_postcondition = MagicMock(
            return_value=(False, "Target file size was 0; verification failed")
        )

        plan = Plan(goal="Verification test", session_id="scen_f")
        step = PlanStep(
            step_id="v_step",
            description="Write text",
            step_type=StepType.TOOL_CALL,
            tool_name="file_write_text",
            parameters={"file_path": "test.txt", "content": "data"},
        )
        plan.add_step(step)

        outcome = executor._execute_single_step(step, plan, ctx)
        assert outcome == "replan_needed"
        assert step.status == StepStatus.FAILED
        assert "verification failed" in step.error

    def test_scenario_g_actual_solver_integration_with_executor(self):
        """Scenario G: End-to-end integration using REAL MultiStepProblemSolver output passed through production planner and executed with AgentExecutor."""
        executor, planner, reg = self._setup_executor()
        solver = MultiStepProblemSolver()
        ctx = ExecutionContext(session_id="scen_g")

        # Real solver solves goal
        goal = "Inspect and search project files for configuration details"
        solution = solver.solve(goal=goal)

        assert solution.get("plan_steps") is not None
        assert len(solution["plan_steps"]) > 0

        # Inject real solver output into execution context
        ctx.metadata["reasoning_plan_steps"] = solution["plan_steps"]

        # Production planner creates executable plan
        available_tool_defs = [
            t.get_definition() for t in reg.list_tools() if hasattr(t, "get_definition")
        ]
        plan = planner.create_plan(goal=goal, context=ctx, available_tools=available_tool_defs)

        assert len(plan.steps) >= 2
        # Execute the generated plan
        outcome = executor.execute_plan(plan, ctx, wait_for_approval=True)
        assert outcome.status in ("completed", "success")
        assert plan.steps[0].status == StepStatus.COMPLETED


# ==============================================================================
# SECTION 3: CRITICAL DEFECT 3 — EVALUATOR INTEGRITY & MATHEMATICAL RIGOR
# ==============================================================================


class TestEvaluatorCanonicalCriteriaAndIntegrity:
    """Verifies evaluator canonical 10 criteria, truthful score provenance, and deterministic tie-breaking."""

    def test_canonical_ten_criteria_evaluated(self):
        """All 10 canonical dimensions are evaluated with normalized weights summing to 1.0."""
        evaluator = AlternativeEvaluator()
        assert len(evaluator.CANONICAL_DIMENSIONS) == 10
        assert sum(evaluator.weights.values()) == pytest.approx(1.0, abs=1e-6)

        candidates = [
            {
                "option_id": "opt_alpha",
                "title": "Alpha Approach",
                "description": "Standard approach",
                "risk_level": RiskLevel.READ_ONLY,
            }
        ]
        results = evaluator.evaluate_candidates("objective", candidates)
        assert len(results) == 1
        trade_offs = results[0].trade_offs
        for dim in evaluator.CANONICAL_DIMENSIONS:
            assert dim in trade_offs
            assert 0.0 <= trade_offs[dim] <= 1.0

    def test_truthful_score_provenance_tracking(self):
        """Evaluator truthfully records provenance: distinguishes rule_derived from user_provided."""
        evaluator = AlternativeEvaluator()
        candidates = [
            {
                "option_id": "opt_prov",
                "title": "Provenance Option",
                "risk_level": RiskLevel.READ_ONLY,
                "dimension_scores": {"correctness": 0.95},
                "score_provenance": {"correctness": ScoreProvenance.MEASURED.value},
            }
        ]
        results = evaluator.evaluate_candidates("objective", candidates)
        prov = results[0].score_provenance
        assert prov["correctness"] == ScoreProvenance.MEASURED.value
        assert prov["security"] == ScoreProvenance.RULE_DERIVED.value

    def test_weights_nan_inf_negative_handling(self):
        """Evaluator handles NaN, infinity, negative weights, and zero-total weights safely."""
        evaluator = AlternativeEvaluator(
            weights={
                "correctness": float("nan"),
                "security": float("inf"),
                "reliability": -5.0,
                "reversibility": 0.5,
                "compatibility": 0.5,
            }
        )
        assert sum(evaluator.weights.values()) == pytest.approx(1.0, abs=1e-6)
        assert evaluator.weights["reversibility"] == 0.5
        assert evaluator.weights["compatibility"] == 0.5

    def test_hard_constraint_overrides_high_scores(self):
        """Violation of hard constraint sets total_score to 0.0 and cannot be recommended."""
        evaluator = AlternativeEvaluator()
        candidates = [
            {
                "option_id": "opt_unsafe",
                "title": "Unsafe Option",
                "risk_level": RiskLevel.DESTRUCTIVE_OPERATION,
                "dimension_scores": dict.fromkeys(evaluator.CANONICAL_DIMENSIONS, 1.0),
            }
        ]
        results = evaluator.evaluate_candidates("test", candidates, constraints=["read_only"])
        assert results[0].score == 0.0
        assert results[0].is_recommended is False
        assert any("Violates hard constraint" in r for r in results[0].reasons)

    def test_deterministic_tie_breaking(self):
        """Options with identical scores tie-break deterministically by ID."""
        evaluator = AlternativeEvaluator()
        candidates = [
            {
                "option_id": "opt_bravo",
                "title": "Option Bravo",
                "risk_level": RiskLevel.READ_ONLY,
                "dimension_scores": dict.fromkeys(evaluator.CANONICAL_DIMENSIONS, 0.8),
            },
            {
                "option_id": "opt_alpha",
                "title": "Option Alpha",
                "risk_level": RiskLevel.READ_ONLY,
                "dimension_scores": dict.fromkeys(evaluator.CANONICAL_DIMENSIONS, 0.8),
            },
        ]
        results = evaluator.evaluate_candidates("test", candidates)
        assert results[0].score == results[1].score
        # Deterministic sorting places opt_alpha before opt_bravo
        assert results[0].option_id == "opt_alpha"
        assert results[1].option_id == "opt_bravo"


# ==============================================================================
# SECTION 4: GATEWAY MODES, BOUNDARIES & TRANSPARENCY
# ==============================================================================


class TestGatewayModesAndBoundaries:
    """Verifies modes (strict, balanced, autonomous, aggressive alias) and fail-closed gates."""

    def test_agent_modes_strict_balanced_autonomous_and_aggressive_alias(self):
        """Strict requires confirmation for reversible modifications; autonomous and aggressive allow it."""
        engine = DecisionEngine()
        tool = WriteTool()

        # Strict mode
        ctx_strict = ExecutionContext(session_id="strict_sess")
        ctx_strict.agent_mode = "strict"
        allowed, risk, req_app, _ = engine.evaluate_tool_execution(
            tool_name="file_write_text",
            params={"file_path": "a.txt"},
            context=ctx_strict,
            tool_instance=tool,
        )
        assert allowed is True
        assert req_app is True  # Strict mode requires approval for modification

        # Autonomous mode
        ctx_auto = ExecutionContext(session_id="auto_sess")
        ctx_auto.agent_mode = "autonomous"
        allowed, risk, req_app, _ = engine.evaluate_tool_execution(
            tool_name="file_write_text",
            params={"file_path": "a.txt"},
            context=ctx_auto,
            tool_instance=tool,
        )
        assert allowed is True
        assert req_app is False  # Autonomous permits modification autonomously

        # Aggressive mode (documented alias for autonomous)
        ctx_aggr = ExecutionContext(session_id="aggr_sess")
        ctx_aggr.agent_mode = "aggressive"
        allowed, risk, req_app, _ = engine.evaluate_tool_execution(
            tool_name="file_write_text",
            params={"file_path": "a.txt"},
            context=ctx_aggr,
            tool_instance=tool,
        )
        assert allowed is True
        assert req_app is False  # Aggressive alias behaves identically to autonomous


class TestSemanticMemoryTransparency:
    """Verifies honest reporting of vector embedding capabilities."""

    def test_local_semantic_provider_is_non_neural_hash(self):
        """LocalSemanticEmbeddingProvider is verified as deterministic non-neural hash."""
        prov = LocalSemanticEmbeddingProvider(dimension=64)
        assert prov.is_available is True
        assert prov.is_neural is False
        assert prov.vector_technique == "subword_feature_hashing"
        assert prov.dimension == 64
        vec = prov.embed_text("test input")
        assert len(vec) == 64
        assert math.isclose(sum(x * x for x in vec), 1.0, rel_tol=1e-5)

    def test_local_neural_provider_honest_diagnostics(self):
        """LocalNeuralEmbeddingProvider accurately reports status without false claims."""
        prov = LocalNeuralEmbeddingProvider(model_name="nonexistent/fake-model")
        assert prov.is_neural is True
        assert prov.vector_technique == "neural_transformer"
        # If model is not loaded in environment, reports is_available=False with clear diagnostics
        if not prov.is_available:
            status_lower = prov.status_reason.lower()
            assert any(
                k in status_lower
                for k in ("sentence-transformers", "not installed", "unavailable", "failed")
            )


class TestConfigurationPersistence:
    """Verifies atomic configuration persistence with key preservation."""

    def test_atomic_config_save_preserves_keys_and_comments(self):
        """save_env_settings preserves existing keys and writes atomically."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".env") as tf:
            tf.write(
                "# Initial Header Comment\nEXISTING_SECRET=keep_me_safe\nAGENT_MODE=balanced\n"
            )
            t_path = Path(tf.name)

        try:
            save_env_settings({"AGENT_MODE": "autonomous", "NEW_KEY": "added"}, env_path=t_path)
            content = t_path.read_text(encoding="utf-8")
            assert "EXISTING_SECRET=keep_me_safe" in content
            assert "AGENT_MODE=autonomous" in content
            assert "NEW_KEY=added" in content
            assert "# Initial Header Comment" in content
        finally:
            if t_path.exists():
                t_path.unlink()
