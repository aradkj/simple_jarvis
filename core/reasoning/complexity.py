"""Task Complexity Classifier for JARVIS Reasoning Architecture (Section 7.1).

Classifies requests into appropriate reasoning complexity tiers:
- SIMPLE_CONVERSATIONAL (greetings, acknowledgments, casual conversation)
- INFORMATION_RETRIEVAL (simple memory lookups, basic factual queries)
- CONTEXT_DEPENDENT (requests requiring resolution against previous turns)
- ANALYTICAL (architectural questions, code explanations, trade-off comparisons)
- MULTI_STEP_PLANNING (compound goals, workflows requiring ordered steps)
- TECHNICAL_DIAGNOSIS (bug investigation, error traces, crash analysis)
- TOOL_EXECUTION (file, terminal, git, or application execution)
- HIGH_RISK_OPERATION (destructive file/process actions requiring explicit safety gates)
- CREATIVE_TASK (generating content, architectural brainstorming)
- AMBIGUOUS_TASK (underspecified or conflicting requests needing clarification)
"""

from __future__ import annotations

import re
from typing import Any

from core.persian.models import PersianIntentType, SemanticInterpretation, TaskComplexity


class TaskComplexityClassifier:
    """Classifies user request complexity to dynamically route to lightweight or deep reasoning."""

    # Patterns indicating high-risk operations
    HIGH_RISK_PATTERNS = [
        re.compile(
            r"\b(?:پاک\s*کن|حذف\s*کن|دیلیت|wipe|drop|format|destroy|terminate|kill\s+all)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:reset|override|force\s+push|hard\s+reset|rm\s+-rf)\b", re.IGNORECASE),
    ]

    # Patterns indicating multi-step planning
    MULTI_STEP_PATTERNS = [
        re.compile(
            r"\b(?:ابتدا|اول|سپس|بعد|در\s+نهایت|و\s+سپس|مراحل|plan|workflow|step\s*by\s*step|first\s+.+?\s+then)\b",
            re.IGNORECASE,
        ),
        re.compile(r"[\n;،,]\s*(?:بعدش|بعد|سپس|آنگاه)\s+", re.IGNORECASE),
    ]

    # Patterns indicating analytical diagnosis
    ANALYTICAL_PATTERNS = [
        re.compile(
            r"\b(?:چرا|علت|تحلیل|بررسی\s+کن\s+چرا|تفاوت|مقایسه|معماری|trade-?off|analyze|compare|explain|architect)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:خطای|error|exception|traceback|crash|کرش|تایم‌اوت)\b", re.IGNORECASE),
    ]

    def classify(
        self,
        text: str,
        semantic_interp: SemanticInterpretation | None = None,
        context: Any = None,
    ) -> tuple[TaskComplexity, str]:
        """Classify task complexity and recommended reasoning depth ('lightweight', 'adaptive', 'deep').

        Returns:
            (complexity: TaskComplexity, reasoning_depth: str)
        """
        if not text or not text.strip():
            return TaskComplexity.SIMPLE_CONVERSATIONAL, "lightweight"

        clean = text.strip().lower()

        if semantic_interp is None:
            try:
                from core.persian.intent_analyzer import PersianIntentAnalyzer

                semantic_interp = PersianIntentAnalyzer().interpret(clean)
            except Exception:
                semantic_interp = None

        # 1. Ambiguous tasks (clarification required)
        if semantic_interp and (
            semantic_interp.requires_clarification or semantic_interp.ambiguities
        ):
            return TaskComplexity.AMBIGUOUS_TASK, "lightweight"

        # 2. High-risk operations (mandatory safety analysis)
        for pat in self.HIGH_RISK_PATTERNS:
            if pat.search(clean):
                return TaskComplexity.HIGH_RISK_OPERATION, "deep"

        # 3. Multi-step planning requests
        if semantic_interp and semantic_interp.primary_intent in (
            PersianIntentType.TASK_PLANNING,
            PersianIntentType.MULTI_STEP_EXECUTION,
        ):
            return TaskComplexity.MULTI_STEP_PLANNING, "deep"

        for pat in self.MULTI_STEP_PATTERNS:
            if pat.search(clean):
                return TaskComplexity.MULTI_STEP_PLANNING, "deep"

        # 4. Technical diagnosis & troubleshooting
        if semantic_interp and semantic_interp.primary_intent in (
            PersianIntentType.DEBUGGING,
            PersianIntentType.SYSTEM_DIAGNOSTICS,
        ):
            return TaskComplexity.TECHNICAL_DIAGNOSIS, "deep"

        # 5. Analytical requests & code explanations
        if semantic_interp and semantic_interp.primary_intent in (
            PersianIntentType.CODE_EXPLANATION,
            PersianIntentType.TECHNICAL_EXPLANATION,
        ):
            return TaskComplexity.ANALYTICAL, "deep"

        for pat in self.ANALYTICAL_PATTERNS:
            if pat.search(clean):
                return TaskComplexity.ANALYTICAL, "deep"

        # 6. Tool-execution tasks
        if semantic_interp and semantic_interp.primary_intent in (
            PersianIntentType.FILE_OPERATION,
            PersianIntentType.APPLICATION_CONTROL,
            PersianIntentType.GIT_OPERATION,
            PersianIntentType.INTEGRATION_MANAGEMENT,
        ):
            return TaskComplexity.TOOL_EXECUTION, "adaptive"

        # 7. Context-dependent references
        if semantic_interp and (
            semantic_interp.resolved_references or "همون" in clean or "اون یکی" in clean
        ):
            return TaskComplexity.CONTEXT_DEPENDENT, "adaptive"

        # 8. Information retrieval & web search
        if semantic_interp and semantic_interp.primary_intent in (
            PersianIntentType.WEB_RESEARCH,
            PersianIntentType.MEMORY_RECALL,
            PersianIntentType.QUESTION_ANSWERING,
        ):
            return TaskComplexity.INFORMATION_RETRIEVAL, "lightweight"

        # Default: simple conversational
        return TaskComplexity.SIMPLE_CONVERSATIONAL, "lightweight"
