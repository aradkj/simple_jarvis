"""Multi-Step Problem Solver for JARVIS Reasoning Architecture (Section 7.2).

Orchestrates the 13-stage problem-solving pipeline:
1. Understand the goal
2. Identify constraints
3. Gather relevant context
4. Identify missing information
5. Generate viable approaches
6. Evaluate trade-offs
7. Select an approach
8. Build an execution plan
9. Validate prerequisites
10. Execute permitted actions (bounded autonomy)
11. Verify actual results
12. Adapt if execution fails
13. Summarize outcome concisely
"""

from __future__ import annotations

import time
from typing import Any

from core.persian.models import (
    DecisionOption,
    DecisionRecord,
    RiskLevel,
    SemanticInterpretation,
    TaskComplexity,
)
from core.reasoning.calibrator import ConfidenceCalibrator
from core.reasoning.complexity import TaskComplexityClassifier
from core.reasoning.contradiction import ContradictionDetector
from core.reasoning.evaluator import AlternativeEvaluator


class MultiStepProblemSolver:
    """Coordinates deep reasoning, trade-off evaluation, and structured decision generation."""

    def __init__(
        self,
        classifier: TaskComplexityClassifier | None = None,
        evaluator: AlternativeEvaluator | None = None,
        calibrator: ConfidenceCalibrator | None = None,
        contradiction_detector: ContradictionDetector | None = None,
    ) -> None:
        self.classifier = classifier or TaskComplexityClassifier()
        self.evaluator = evaluator or AlternativeEvaluator()
        self.calibrator = calibrator or ConfidenceCalibrator()
        self.contradiction_detector = contradiction_detector or ContradictionDetector()

    def solve(
        self,
        goal: str,
        semantic_interp: SemanticInterpretation | None = None,
        context: dict[str, Any] | None = None,
        retrieved_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute structured multi-step reasoning over the input goal.

        Returns comprehensive structured reasoning artifact containing decision record,
        plan steps, risk assessment, and calibrated confidence.
        """
        ctx = context or {}
        memories = retrieved_memories or []

        if semantic_interp is None:
            from core.persian.intent_analyzer import PersianIntentAnalyzer

            semantic_interp = PersianIntentAnalyzer().interpret(goal)

        # 1. Understand the goal & Classify complexity
        complexity, reasoning_depth = self.classifier.classify(goal, semantic_interp, ctx)

        # 2. Identify constraints & prohibitions
        constraints = list(semantic_interp.constraints) if semantic_interp else []
        prohibitions = []
        if semantic_interp and hasattr(semantic_interp, "prohibited_actions"):
            prohibitions = list(semantic_interp.prohibited_actions)

        # 3. Detect contradictions
        contradictions = self.contradiction_detector.detect_in_instructions(
            goal, constraints=constraints, prohibitions=prohibitions
        )
        memory_conflicts = self.contradiction_detector.detect_against_memory(goal, memories)

        # 4. Identify missing information / ambiguities
        ambiguities = list(semantic_interp.ambiguities) if semantic_interp else []
        requires_clarification = (
            bool(semantic_interp.requires_clarification) if semantic_interp else False
        )
        clarification_prompt = semantic_interp.clarification_prompt if semantic_interp else None

        # 5. Generate viable candidate approaches
        candidates = self._generate_candidate_approaches(goal, complexity, semantic_interp)

        # 6. Evaluate trade-offs
        evaluated_options = self.evaluator.evaluate_candidates(
            objective=goal,
            candidates=candidates,
            constraints=constraints,
            user_preferences=ctx.get("user_preferences", []),
        )

        # 7. Select optimal approach
        selected = evaluated_options[0] if evaluated_options else None
        selected_id = selected.option_id if selected else "direct_response"

        # 8. Build execution plan steps
        plan_steps = self._build_plan_steps(goal, selected, semantic_interp, context=ctx)

        # 9. Calibrate confidence
        conf_level, conf_score, conf_expl = self.calibrator.calibrate(
            has_tool_verification=ctx.get("verified", False),
            retrieval_score=ctx.get("retrieval_score", 0.5),
            ambiguity_count=len(ambiguities),
            is_hypothetical=bool(semantic_interp and semantic_interp.is_hypothetical),
            contradiction_detected=len(contradictions) > 0,
            user_confirmed=ctx.get("user_confirmed", False),
        )

        # 10. Construct DecisionRecord (Section 7.4)
        decision_record = DecisionRecord(
            decision_id=f"dec_{int(time.time() * 1000)}",
            objective=goal,
            available_evidence=[f"Context complexity: {complexity.value}"]
            + [f"Memory fact: {m.get('content')}" for m in memories[:3]],
            relevant_constraints=constraints,
            candidate_options=evaluated_options,
            selected_option=selected_id,
            reasons_for_selection=selected.reasons if selected else ["Direct response chosen"],
            risks=[selected.risk_level.value] if selected else [],
            rejected_alternatives=[
                {"option_id": o.option_id, "score": str(o.score), "reasons": "; ".join(o.reasons)}
                for o in evaluated_options[1:]
            ],
            verification_requirements=[
                "Confirm prerequisite file existence",
                "Execute tool within authorized directory",
                "Verify stdout output matches expected regex",
            ],
            confidence_level=conf_level,
            timestamp=time.time(),
            metadata={
                "complexity": complexity.value,
                "reasoning_depth": reasoning_depth,
                "calibrated_confidence": conf_score,
                "confidence_explanation": conf_expl,
            },
        )

        return {
            "complexity": complexity,
            "reasoning_depth": reasoning_depth,
            "decision_record": decision_record,
            "selected_option": selected,
            "plan_steps": plan_steps,
            "contradictions": contradictions,
            "memory_conflicts": memory_conflicts,
            "requires_clarification": requires_clarification or len(contradictions) > 0,
            "clarification_prompt": clarification_prompt
            or (contradictions[0]["description"] if contradictions else None),
            "confidence_level": conf_level,
            "confidence_score": conf_score,
            "confidence_explanation": conf_expl,
        }

    def _generate_candidate_approaches(
        self,
        goal: str,
        complexity: TaskComplexity,
        semantic_interp: SemanticInterpretation | None,
    ) -> list[dict[str, Any]]:
        """Generate 2-3 viable alternatives depending on complexity."""
        if complexity == TaskComplexity.SIMPLE_CONVERSATIONAL:
            return [
                {
                    "option_id": "direct_conversation",
                    "title": "Direct Conversational Reply",
                    "description": "Respond directly without invoking external tools or persistent memory search.",
                    "risk_level": RiskLevel.READ_ONLY,
                    "dimension_scores": {
                        "correctness": 0.95,
                        "security": 1.0,
                        "execution_time": 0.98,
                    },
                }
            ]

        if complexity in (TaskComplexity.TECHNICAL_DIAGNOSIS, TaskComplexity.MULTI_STEP_PLANNING):
            return [
                {
                    "option_id": "inspect_first_then_remediate",
                    "title": "Inspect & Analyze First, Then Plan Remediation",
                    "description": "Inspect repository files and test outputs before attempting code modifications.",
                    "risk_level": RiskLevel.READ_ONLY,
                    "dimension_scores": {
                        "correctness": 0.95,
                        "security": 0.95,
                        "reliability": 0.95,
                        "reversibility": 1.0,
                    },
                },
                {
                    "option_id": "direct_modification",
                    "title": "Direct File Modification",
                    "description": "Directly modify hypothesized file locations without prior inspection.",
                    "risk_level": RiskLevel.REVERSIBLE_MODIFICATION,
                    "dimension_scores": {
                        "correctness": 0.60,
                        "security": 0.65,
                        "reliability": 0.50,
                        "reversibility": 0.7,
                    },
                },
            ]

        # Standard tool execution
        return [
            {
                "option_id": "safe_bounded_tool_execution",
                "title": "Bounded Authorized Execution",
                "description": "Execute permitted tool in authorized workspace and independently verify result.",
                "risk_level": RiskLevel.READ_ONLY,
                "dimension_scores": {
                    "correctness": 0.95,
                    "security": 0.95,
                    "reliability": 0.90,
                    "reversibility": 0.95,
                },
            },
            {
                "option_id": "ask_user_confirmation",
                "title": "Request Explicit Confirmation",
                "description": "Ask user for confirmation before taking external action.",
                "risk_level": RiskLevel.READ_ONLY,
                "dimension_scores": {
                    "correctness": 0.85,
                    "security": 1.0,
                    "reliability": 0.85,
                    "execution_time": 0.6,
                },
            },
        ]

    def _build_plan_steps(
        self,
        goal: str,
        selected_option: DecisionOption | None,
        semantic_interp: SemanticInterpretation | None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Construct dynamic, task-specific plan steps with explicit prerequisites and verification criteria."""
        ctx = context or {}
        g_lower = goal.lower()
        intent = semantic_interp.primary_intent if semantic_interp else None
        intent_val = intent.value if hasattr(intent, "value") else str(intent or "")
        target = (
            (
                (
                    semantic_interp.target_entity
                    or semantic_interp.active_file
                    or semantic_interp.active_project
                )
                if semantic_interp
                else None
            )
            or ctx.get("active_file")
            or ctx.get("active_project")
        )

        is_actionable = any(
            k in g_lower
            for k in (
                "پیاده‌سازی",
                "پیاده سازی",
                "تنظیم",
                "ایجاد",
                "افزودن",
                "بررسی",
                "تست",
                "بکاپ",
                "ریفکتور",
                "پاکسازی",
                "عیب‌یابی",
                "عیب یابی",
                "کوئری",
                "کامیت",
                "کانفیگ",
                "داکر",
                "اسکریپت",
                "لاگ",
                "سرویس",
                "implement",
                "create",
                "setup",
                "configure",
                "test",
                "clean",
                "build",
                "deploy",
                "fix",
            )
        )

        # 1. Direct conversational response (no tools)
        if (
            not selected_option or selected_option.option_id == "direct_conversation"
        ) and not is_actionable:
            return [
                {
                    "step": 1,
                    "action": "formulate_response",
                    "description": f"Formulate direct, context-aware answer for: {goal}",
                    "prerequisites": [],
                    "verification_criteria": "Response provides accurate, coherent information.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": None,
                }
            ]

        # 2. Technical Diagnosis / Debugging / Test Inspection
        if (
            intent_val in ("debugging", "technical_diagnosis", "project_investigation")
            or (selected_option.option_id if selected_option else "")
            == "inspect_first_then_remediate"
            or any(
                k in g_lower
                for k in ("test", "bug", "error", "traceback", "fail", "خطا", "دیباگ", "تست")
            )
        ):
            target_desc = f" ({target})" if target else ""
            return [
                {
                    "step": 1,
                    "action": "inspect_diagnostics",
                    "description": f"Inspect repository telemetry, log files, and stack traces{target_desc}.",
                    "prerequisites": ["Workspace directory accessible"],
                    "verification_criteria": "Error traces and diagnostic symptoms identified.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "file_inspect",
                },
                {
                    "step": 2,
                    "action": "reproduce_failure",
                    "description": "Execute targeted tests or diagnostics to isolate the defect.",
                    "prerequisites": ["Target diagnostic files inspected"],
                    "verification_criteria": "Deterministic reproduction confirms failure boundaries.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "terminal_execute",
                },
                {
                    "step": 3,
                    "action": "formulate_remediation",
                    "description": "Analyze failure root causes and construct minimal targeted fix.",
                    "prerequisites": ["Reproduction confirmed"],
                    "verification_criteria": "Root cause identified and validated against constraints.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": None,
                },
                {
                    "step": 4,
                    "action": "verify_and_report",
                    "description": "Verify remediation via independent regression tests and state checks.",
                    "prerequisites": ["Remediation applied"],
                    "verification_criteria": "All unit and integration tests exit with code 0 (100% green).",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "terminal_execute",
                },
            ]

        # 3. File Operations (Mutation / Creation vs Read / Search)
        is_file_op = intent_val == "file_operation" or any(
            k in g_lower for k in ("file", "folder", "directory", "فایل", "پوشه", "دایرکتوری")
        )
        is_write_op = any(
            k in g_lower
            for k in (
                "write",
                "create",
                "modify",
                "edit",
                "make",
                "touch",
                "ساخت",
                "ایجاد",
                "ویرایش",
                "نوشتن",
            )
        )

        if is_file_op and is_write_op:
            target_name = target or "requested target"
            return [
                {
                    "step": 1,
                    "action": "validate_path_security",
                    "description": f"Validate path authorization within workspace boundaries for '{target_name}'.",
                    "prerequisites": ["Target path specified"],
                    "verification_criteria": "Path is confirmed inside authorized workspace roots.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "path_security",
                },
                {
                    "step": 2,
                    "action": "inspect_pre_state",
                    "description": f"Inspect existing file or directory state prior to modifying '{target_name}'.",
                    "prerequisites": ["Path security validated"],
                    "verification_criteria": "Pre-execution state recorded and backups prepared if needed.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "file_inspect",
                },
                {
                    "step": 3,
                    "action": "execute_modification",
                    "description": f"Apply bounded file modification or creation for '{target_name}'.",
                    "prerequisites": ["Pre-state verified", "Authorization confirmed"],
                    "verification_criteria": "Tool execution returns success status with exit code 0.",
                    "risk_level": RiskLevel.REVERSIBLE_MODIFICATION.value,
                    "status": "pending",
                    "tool_hint": "file_write",
                },
                {
                    "step": 4,
                    "action": "verify_file_outcome",
                    "description": f"Independently verify target '{target_name}' exists on disk with expected content.",
                    "prerequisites": ["Modification step completed"],
                    "verification_criteria": "Target exists, size > 0, and content matches expected modification.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "file_inspect",
                },
            ]

        if is_file_op and not is_write_op:
            target_name = target or "project files"
            return [
                {
                    "step": 1,
                    "action": "search_project_files",
                    "description": f"Search and locate target files matching '{target_name}'.",
                    "prerequisites": ["Authorized workspace path accessible"],
                    "verification_criteria": "Matching files identified within authorized directory.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "file_search",
                },
                {
                    "step": 2,
                    "action": "inspect_target_content",
                    "description": f"Inspect file content and metadata for '{target_name}'.",
                    "prerequisites": ["Target file located"],
                    "verification_criteria": "File successfully read and parsed without error.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "file_inspect",
                },
                {
                    "step": 3,
                    "action": "synthesize_findings",
                    "description": f"Synthesize inspected findings to answer inquiry regarding '{target_name}'.",
                    "prerequisites": ["File content parsed"],
                    "verification_criteria": "Response accurately reflects verified file contents.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": None,
                },
            ]

        # 4. Application Control
        if intent_val == "application_control" or any(
            k in g_lower for k in ("launch", "open", "close", "minimize", "اجرا", "باز کن", "ببند")
        ):
            app_name = target or "target application"
            return [
                {
                    "step": 1,
                    "action": "inspect_process_state",
                    "description": f"Inspect active Windows processes and window handles for '{app_name}'.",
                    "prerequisites": ["System process querying available"],
                    "verification_criteria": "Current process running state determined.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "windows_app_read",
                },
                {
                    "step": 2,
                    "action": "dispatch_app_control",
                    "description": f"Dispatch bounded application action for '{app_name}'.",
                    "prerequisites": ["Process state determined", "Application in allowlist"],
                    "verification_criteria": "System action dispatched cleanly.",
                    "risk_level": RiskLevel.REVERSIBLE_MODIFICATION.value,
                    "status": "pending",
                    "tool_hint": "windows_app_launch",
                },
                {
                    "step": 3,
                    "action": "verify_window_state",
                    "description": f"Independently verify process alive and window visibility for '{app_name}'.",
                    "prerequisites": ["Control action dispatched"],
                    "verification_criteria": "Process confirmed running or terminated as requested.",
                    "risk_level": RiskLevel.READ_ONLY.value,
                    "status": "pending",
                    "tool_hint": "windows_window_read",
                },
            ]

        # 5. Generic Structured Problem-Solving
        return [
            {
                "step": 1,
                "action": "validate_prerequisites",
                "description": f"Validate execution prerequisites, authorization, and constraints for: {goal}",
                "prerequisites": ["User instruction received"],
                "verification_criteria": "All operational constraints satisfied.",
                "risk_level": RiskLevel.READ_ONLY.value,
                "status": "pending",
                "tool_hint": None,
            },
            {
                "step": 2,
                "action": "execute_bounded_action",
                "description": f"Execute authorized action for '{selected_option.title if selected_option else goal}'.",
                "prerequisites": ["Prerequisites validated"],
                "verification_criteria": "Action completed within security boundaries.",
                "risk_level": (
                    selected_option.risk_level.value
                    if selected_option
                    else RiskLevel.READ_ONLY.value
                ),
                "status": "pending",
                "tool_hint": None,
            },
            {
                "step": 3,
                "action": "verify_independent_outcome",
                "description": "Independently inspect system state and verify outcome against ground truth.",
                "prerequisites": ["Action executed"],
                "verification_criteria": "Ground truth verification passes.",
                "risk_level": RiskLevel.READ_ONLY.value,
                "status": "pending",
                "tool_hint": None,
            },
        ]
