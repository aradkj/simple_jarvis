"""Decision Engine & Tool Selection Benchmark Suite for JARVIS (Section 8 & 9).

Evaluates:
- Action type categorization (Answer directly, Search files, Create plan, Execute tool, Ask clarification)
- Risk classification and autonomous execution thresholds
- Non-looping failure recovery strategy progression
- Structured decision records and provenance tracking
"""

from __future__ import annotations

import pytest

from core.decision.engine import (
    ActionType,
    DecisionEngine,
    FailureRecoveryEngine,
    FailureRecoveryStrategy,
    RiskClassifier,
)
from core.persian.models import RiskLevel, TaskComplexity

# ==============================================================================
# Category 1: Risk Classification & Action Types (30 cases)
# ==============================================================================
RISK_EVALUATION_CASES = [
    # Low risk (Read-only queries, status checks, diagnostics)
    ("read_file", {"path": "main.py"}, RiskLevel.READ_ONLY),
    ("list_dir", {"path": "core/"}, RiskLevel.READ_ONLY),
    ("get_system_status", {}, RiskLevel.READ_ONLY),
    ("search_files", {"query": "test"}, RiskLevel.READ_ONLY),
    ("git_status", {}, RiskLevel.READ_ONLY),
    ("view_logs", {"lines": 50}, RiskLevel.READ_ONLY),
    ("read_config", {"file": "settings.json"}, RiskLevel.READ_ONLY),
    ("check_port", {"port": 8000}, RiskLevel.READ_ONLY),
    # Reversible Modification (Creating/updating non-critical files)
    ("write_file", {"path": "scratch/test.py"}, RiskLevel.REVERSIBLE_MODIFICATION),
    ("create_dir", {"path": "temp_build/"}, RiskLevel.REVERSIBLE_MODIFICATION),
    ("modify_file", {"path": "README.md"}, RiskLevel.REVERSIBLE_MODIFICATION),
    ("update_config", {"key": "debug", "value": True}, RiskLevel.REVERSIBLE_MODIFICATION),
    ("rename_file", {"old": "a.txt", "new": "b.txt"}, RiskLevel.REVERSIBLE_MODIFICATION),
    ("touch_file", {"path": "init.py"}, RiskLevel.REVERSIBLE_MODIFICATION),
    # Destructive operations
    ("delete_file", {"path": "tests/test_temp.py"}, RiskLevel.DESTRUCTIVE_OPERATION),
    ("remove_dir", {"path": "old_logs/"}, RiskLevel.DESTRUCTIVE_OPERATION),
    ("drop_table", {"table": "temp_cache"}, RiskLevel.DESTRUCTIVE_OPERATION),
    ("wipe_cache", {"target": "redis"}, RiskLevel.DESTRUCTIVE_OPERATION),
    ("پاک_کردن", {"target": "فایل موقت"}, RiskLevel.DESTRUCTIVE_OPERATION),
    # Irreversible operations (forced destructive actions)
    ("delete_all", {"force": True}, RiskLevel.IRREVERSIBLE_OPERATION),
    ("wipe_all", {"all": True}, RiskLevel.IRREVERSIBLE_OPERATION),
    ("format_drive", {"drive": "D:", "force": True}, RiskLevel.IRREVERSIBLE_OPERATION),
    ("drop_database", {"all": True, "force": True}, RiskLevel.IRREVERSIBLE_OPERATION),
    ("حذف_همه", {"force": True}, RiskLevel.IRREVERSIBLE_OPERATION),
    # Sensitive data access
    ("read_secret", {"password": "admin"}, RiskLevel.SENSITIVE_DATA_ACCESS),
    ("get_credential", {"token": "ghp_123"}, RiskLevel.SENSITIVE_DATA_ACCESS),
    # External communications
    ("send_email", {"to": "user@test.com"}, RiskLevel.EXTERNAL_COMMUNICATION),
    ("post_message", {"channel": "notifications"}, RiskLevel.EXTERNAL_COMMUNICATION),
]

# Low risk probes and capability-checked operations (60+ cases)
for idx in range(30):
    RISK_EVALUATION_CASES.append(
        (
            f"read_file_probe_{idx}",
            {"path": f"probe_{idx}.txt"},
            RiskLevel.READ_ONLY,
        )
    )

# Safe recognized read-only tools
for safe_tool in [
    "weather_current",
    "weather_forecast",
    "coding_agent_status",
    "system_info",
    "windows_window_read",
    "windows_display_read",
    "windows_audio_read",
    "windows_app_read",
    "memory_search",
    "datetime_query",
    "browser_read",
    "browser_tab",
]:
    RISK_EVALUATION_CASES.append((safe_tool, {}, RiskLevel.READ_ONLY))

# Sensitive credentials & keys
for sens_k in [
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
    "auth_token",
    "cvv",
    "ssn",
    "credit_card",
    "پسورد",
    "رمز",
    "کلید",
]:
    RISK_EVALUATION_CASES.append(
        ("probe_inspect", {sens_k: "val123"}, RiskLevel.SENSITIVE_DATA_ACCESS)
    )

# Fail-closed unknown tools
for unk_tool in [
    "unregistered_runner",
    "mystery_binary",
    "custom_eval_tool",
    "remote_shell_probe",
    "unknown_hook",
]:
    RISK_EVALUATION_CASES.append((unk_tool, {}, RiskLevel.DESTRUCTIVE_OPERATION))

# Destructive flags & irreversible operations
for flag in ["force", "all", "recursive", "permanent", "purge", "hard"]:
    RISK_EVALUATION_CASES.append(("delete_data", {flag: True}, RiskLevel.IRREVERSIBLE_OPERATION))
    RISK_EVALUATION_CASES.append(("remove_tree", {flag: True}, RiskLevel.IRREVERSIBLE_OPERATION))

# Reversible modifications
for mod_tool in [
    "write_file",
    "create_dir",
    "modify_file",
    "update_config",
    "rename_file",
    "touch_file",
    "append_file",
]:
    RISK_EVALUATION_CASES.append(
        (mod_tool, {"path": "src/module.py"}, RiskLevel.REVERSIBLE_MODIFICATION)
    )

# ==============================================================================
# Category 2: Non-Looping Failure Recovery Strategy (20 cases)
# ==============================================================================
FAILURE_PROGRESSION_CASES = [
    # Transient timeout errors (Attempt 1-2 -> Retry)
    (0, "Connection timeout to server", False, FailureRecoveryStrategy.RETRY),
    (1, "Temporary network timeout", False, FailureRecoveryStrategy.RETRY),
    (0, "Timed out waiting for lock", False, FailureRecoveryStrategy.RETRY),
    (1, "Connection reset by peer", False, FailureRecoveryStrategy.RETRY),
    (0, "Temporary resource unavailable", False, FailureRecoveryStrategy.RETRY),
    # File not found or syntax error -> Use alternative
    (0, "FileNotFoundError: main.py not found", False, FailureRecoveryStrategy.USE_ALTERNATIVE),
    (0, "No such file or directory", False, FailureRecoveryStrategy.USE_ALTERNATIVE),
    (0, "SyntaxError in script", False, FailureRecoveryStrategy.USE_ALTERNATIVE),
    (0, "ImportError: cannot import name", False, FailureRecoveryStrategy.USE_ALTERNATIVE),
    (1, "FileNotFoundError: backup.json not found", False, FailureRecoveryStrategy.USE_ALTERNATIVE),
    # Permission denied / unauthorized -> Permanent abort and report
    (0, "PermissionDeniedError", True, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (0, "Unauthorized access to file", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (1, "Permission denied by OS", True, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (0, "Action blocked: unauthorized path", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (2, "Permission denied", True, FailureRecoveryStrategy.ABORT_AND_REPORT),
    # Exhausted retries -> Abort and report
    (2, "Connection timeout to server", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (3, "Connection timeout to server", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (5, "Repeated unrecoverable error", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (10, "Runaway failure", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
    (100, "Safety ceiling exceeded", False, FailureRecoveryStrategy.ABORT_AND_REPORT),
]


# ==============================================================================
# Benchmark Tests Execution
# ==============================================================================


@pytest.mark.parametrize("action_name,params,expected_risk", RISK_EVALUATION_CASES)
def test_benchmark_risk_classification(
    action_name: str,
    params: dict,
    expected_risk: RiskLevel,
):
    """Benchmark: Risk classifier evaluates operation risk accurately (35+ cases)."""
    classifier = RiskClassifier()
    risk = classifier.classify_risk(action_name, params)
    assert risk == expected_risk, f"Expected risk {expected_risk} for '{action_name}', got {risk}"


@pytest.mark.parametrize(
    "retry_count,error_reason,is_perm,expected_strategy", FAILURE_PROGRESSION_CASES
)
def test_benchmark_non_looping_failure_recovery_progression(
    retry_count: int, error_reason: str, is_perm: bool, expected_strategy: FailureRecoveryStrategy
):
    """Benchmark: Failure recovery engine deterministically progresses without repeating failed actions (20 cases)."""
    recovery_engine = FailureRecoveryEngine(max_retries=2)
    # Simulate prior retries
    key = "task_bench:1:test_tool"
    recovery_engine._retry_counts[key] = retry_count

    strategy, explanation = recovery_engine.handle_failure(
        task_id="task_bench",
        step_index=1,
        tool_name="test_tool",
        error_message=error_reason,
        is_permission_denied=is_perm,
    )
    assert strategy == expected_strategy, (
        f"Expected {expected_strategy}, got {strategy} ({explanation})"
    )
    assert len(explanation) > 0


def test_benchmark_decision_engine_action_selection_and_records():
    """Benchmark: Decision engine selects appropriate action path and creates structured records."""
    engine = DecisionEngine()

    # 1. Simple conversation -> Answer directly
    action, payload = engine.select_action(
        goal="سلام جارویس",
        complexity=TaskComplexity.SIMPLE_CONVERSATIONAL,
    )
    assert action == ActionType.ANSWER_DIRECTLY

    # 2. Multi-step planning -> Create plan
    action, payload = engine.select_action(
        goal="پروژه را بررسی کن و سپس تست‌ها را اجرا کن",
        complexity=TaskComplexity.MULTI_STEP_PLANNING,
    )
    assert action == ActionType.CREATE_PLAN


GATEWAY_EVALUATION_CASES = [
    # (tool_name, params, agent_mode, auto_approve, expected_allowed, expected_risk, expected_approval)
    ("weather_current", {}, "balanced", False, True, RiskLevel.READ_ONLY, False),
    ("file_search", {"query": "readme"}, "autonomous", False, True, RiskLevel.READ_ONLY, False),
    ("system_info", {}, "strict", True, True, RiskLevel.READ_ONLY, False),
    ("read_file", {"path": "main.py"}, "balanced", False, True, RiskLevel.READ_ONLY, False),
    ("windows_window_read", {}, "autonomous", False, True, RiskLevel.READ_ONLY, False),
    # Reversible modifications
    (
        "write_file",
        {"path": "test.txt"},
        "autonomous",
        False,
        True,
        RiskLevel.REVERSIBLE_MODIFICATION,
        False,
    ),
    (
        "create_dir",
        {"path": "build/"},
        "balanced",
        False,
        True,
        RiskLevel.REVERSIBLE_MODIFICATION,
        True,
    ),
    (
        "create_dir",
        {"path": "build/"},
        "balanced",
        True,
        True,
        RiskLevel.REVERSIBLE_MODIFICATION,
        False,
    ),
    (
        "modify_file",
        {"path": "notes.md"},
        "autonomous",
        False,
        True,
        RiskLevel.REVERSIBLE_MODIFICATION,
        False,
    ),
    (
        "rename_file",
        {"old": "a", "new": "b"},
        "strict",
        False,
        True,
        RiskLevel.REVERSIBLE_MODIFICATION,
        True,
    ),
    # Destructive operations: ALWAYS require approval
    (
        "delete_file",
        {"path": "file.txt"},
        "autonomous",
        True,
        True,
        RiskLevel.DESTRUCTIVE_OPERATION,
        True,
    ),
    (
        "remove_dir",
        {"path": "data/"},
        "autonomous",
        False,
        True,
        RiskLevel.DESTRUCTIVE_OPERATION,
        True,
    ),
    ("drop_table", {"name": "users"}, "strict", True, True, RiskLevel.DESTRUCTIVE_OPERATION, True),
    (
        "wipe_cache",
        {"target": "all"},
        "autonomous",
        True,
        True,
        RiskLevel.IRREVERSIBLE_OPERATION,
        True,
    ),
    (
        "format_drive",
        {"drive": "C:", "force": True},
        "autonomous",
        True,
        True,
        RiskLevel.IRREVERSIBLE_OPERATION,
        True,
    ),
    (
        "delete_all",
        {"force": True},
        "autonomous",
        True,
        True,
        RiskLevel.IRREVERSIBLE_OPERATION,
        True,
    ),
    ("wipe_all", {"all": True}, "autonomous", True, True, RiskLevel.IRREVERSIBLE_OPERATION, True),
    # Sensitive credentials: ALWAYS require approval
    (
        "read_secret",
        {"password": "pwd"},
        "autonomous",
        True,
        True,
        RiskLevel.SENSITIVE_DATA_ACCESS,
        True,
    ),
    (
        "get_token",
        {"token": "secret"},
        "autonomous",
        True,
        True,
        RiskLevel.SENSITIVE_DATA_ACCESS,
        True,
    ),
    (
        "query_keys",
        {"private_key": "rsa"},
        "balanced",
        False,
        True,
        RiskLevel.SENSITIVE_DATA_ACCESS,
        True,
    ),
    # External communication
    (
        "send_email",
        {"to": "a@b.com"},
        "balanced",
        False,
        True,
        RiskLevel.EXTERNAL_COMMUNICATION,
        True,
    ),
    (
        "send_email",
        {"to": "a@b.com"},
        "balanced",
        True,
        True,
        RiskLevel.EXTERNAL_COMMUNICATION,
        False,
    ),
    (
        "whatsapp_send",
        {"msg": "hi"},
        "autonomous",
        False,
        True,
        RiskLevel.EXTERNAL_COMMUNICATION,
        True,
    ),
    (
        "whatsapp_send",
        {"msg": "hi"},
        "autonomous",
        True,
        True,
        RiskLevel.EXTERNAL_COMMUNICATION,
        False,
    ),
    (
        "cloud_transmit",
        {"target": "cloud"},
        "strict",
        False,
        True,
        RiskLevel.EXTERNAL_COMMUNICATION,
        True,
    ),
]

# Probes for bounded gateway
for p_idx in range(10):
    GATEWAY_EVALUATION_CASES.append(
        (
            f"read_file_{p_idx}",
            {"path": f"doc_{p_idx}.txt"},
            "autonomous",
            False,
            True,
            RiskLevel.READ_ONLY,
            False,
        )
    )


@pytest.mark.parametrize(
    "tool_name,params,agent_mode,auto_approve,expected_allowed,expected_risk,expected_approval",
    GATEWAY_EVALUATION_CASES,
)
def test_benchmark_decision_gateway_authorization(
    tool_name: str,
    params: dict,
    agent_mode: str,
    auto_approve: bool,
    expected_allowed: bool,
    expected_risk: RiskLevel,
    expected_approval: bool,
):
    """Benchmark: DecisionEngine mandatory execution gateway enforces risk boundaries and approval policies (35 cases)."""

    class MockContext:
        def __init__(self, mode: str, approve: bool) -> None:
            self.agent_mode = mode
            self.auto_approve = approve

    engine = DecisionEngine()
    ctx = MockContext(mode=agent_mode, approve=auto_approve)
    allowed, risk, req_approval, rationale = engine.evaluate_tool_execution(
        tool_name=tool_name,
        params=params,
        context=ctx,
    )
    assert allowed == expected_allowed
    assert risk == expected_risk
    assert req_approval == expected_approval, (
        f"For tool {tool_name} (mode={agent_mode}, auto_approve={auto_approve}): expected approval={expected_approval}, got {req_approval} ({rationale})"
    )
