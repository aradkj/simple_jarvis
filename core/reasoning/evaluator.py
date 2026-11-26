"""Alternative Solution Evaluator for JARVIS Reasoning Architecture (Section 7.3).

Evaluates candidate options across 10 engineering dimensions:
1. Correctness (meets user goal and specifications)
2. Security (complies with permission boundaries, zero prompt injection risk)
3. Reliability (robust under adverse or edge-case conditions)
4. Complexity (simplicity, minimal dependencies)
5. Cost (token and API consumption)
6. Execution time (latency and throughput)
7. Maintainability (code clarity, testability)
8. Reversibility (ability to undo or rollback without permanent data loss)
9. Compatibility (Windows 11, Python 3.12, local project environment)
10. User preferences (aligns with persistent user styles and constraints)
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from core.persian.models import DecisionOption, RiskLevel


class ScoreProvenance(StrEnum):
    """Origin tracking for evaluation scores."""

    MEASURED = "measured"
    RULE_DERIVED = "rule_derived"
    USER_PROVIDED = "user_provided"
    UNKNOWN = "unknown"


class AlternativeEvaluator:
    """Evaluates multiple approaches systematically against all 10 engineering criteria (Section 7.3)."""

    DEFAULT_WEIGHTS = {
        "correctness": 0.20,
        "security": 0.15,
        "reliability": 0.15,
        "reversibility": 0.10,
        "compatibility": 0.10,
        "maintainability": 0.10,
        "user_preferences": 0.08,
        "complexity": 0.04,
        "cost": 0.04,
        "execution_time": 0.04,
    }

    CANONICAL_DIMENSIONS = (
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
    )

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        raw_weights = weights or self.DEFAULT_WEIGHTS
        valid_weights: dict[str, float] = {}
        for k, v in raw_weights.items():
            if k not in self.CANONICAL_DIMENSIONS:
                continue
            try:
                val = float(v)
                if math.isnan(val) or math.isinf(val) or val < 0.0:
                    val = 0.0
            except (ValueError, TypeError):
                val = 0.0
            valid_weights[k] = val

        # Ensure all canonical dimensions are present
        for dim in self.CANONICAL_DIMENSIONS:
            if dim not in valid_weights:
                valid_weights[dim] = 0.0

        total = sum(valid_weights.values())
        if total > 0.0:
            self.weights = {k: v / total for k, v in valid_weights.items()}
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()

    def evaluate_candidates(
        self,
        objective: str,
        candidates: list[dict[str, Any]],
        constraints: list[str] | None = None,
        user_preferences: list[str] | None = None,
    ) -> list[DecisionOption]:
        """Score candidate options across all 10 trade-off dimensions and return ranked DecisionOption list."""
        if not candidates:
            return []

        user_prefs = [p.lower() for p in (user_preferences or [])]
        active_constraints = [c.lower() for c in (constraints or [])]

        evaluated: list[DecisionOption] = []
        for cand in candidates:
            opt_id = cand.get("option_id", f"opt_{len(evaluated) + 1}")
            title = cand.get("title", f"Option {opt_id}")
            description = cand.get("description", "")
            risk = cand.get("risk_level", RiskLevel.READ_ONLY)
            raw_scores = cand.get("dimension_scores", {})
            explicit_provenance = cand.get("score_provenance", {})

            # Default scores across all 10 canonical dimensions (0.0 to 1.0)
            scores: dict[str, float] = {}
            provenance_map: dict[str, str] = {}

            for dim in self.CANONICAL_DIMENSIONS:
                if dim in raw_scores:
                    try:
                        val = float(raw_scores[dim])
                        if math.isnan(val) or math.isinf(val):
                            val = 0.0
                        scores[dim] = max(0.0, min(1.0, val))
                        provenance_map[dim] = explicit_provenance.get(
                            dim, ScoreProvenance.USER_PROVIDED.value
                        )
                    except (ValueError, TypeError):
                        scores[dim] = 0.0
                        provenance_map[dim] = ScoreProvenance.UNKNOWN.value
                else:
                    provenance_map[dim] = ScoreProvenance.RULE_DERIVED.value
                    if dim == "correctness":
                        scores[dim] = 0.8
                    elif dim == "security":
                        scores[dim] = (
                            0.9
                            if risk in (RiskLevel.READ_ONLY, RiskLevel.REVERSIBLE_MODIFICATION)
                            else 0.4
                        )
                    elif dim == "reliability":
                        scores[dim] = 0.8
                    elif dim == "reversibility":
                        scores[dim] = 0.95 if risk != RiskLevel.DESTRUCTIVE_OPERATION else 0.2
                    elif dim == "compatibility":
                        scores[dim] = 0.95
                    elif dim == "maintainability":
                        scores[dim] = 0.85
                    elif dim == "user_preferences" or dim == "complexity":
                        scores[dim] = 0.8
                    elif dim == "cost":
                        scores[dim] = 0.85
                    elif dim == "execution_time":
                        scores[dim] = 0.8
                    else:
                        scores[dim] = 0.5

            # Constraint and hard safety enforcement
            reasons: list[str] = []
            violates_hard_constraint = False
            for c in active_constraints:
                if "read_only" in c and risk != RiskLevel.READ_ONLY:
                    violates_hard_constraint = True
                    scores["security"] = 0.0
                    scores["correctness"] = 0.0
                    reasons.append("Violates hard constraint: read-only operation required")
                if "preserve" in c and risk in (
                    RiskLevel.DESTRUCTIVE_OPERATION,
                    RiskLevel.IRREVERSIBLE_OPERATION,
                ):
                    violates_hard_constraint = True
                    scores["security"] = 0.0
                    scores["reversibility"] = 0.0
                    reasons.append("Violates hard constraint: data preservation required")
                if "no_deletion" in c and (
                    risk in (RiskLevel.DESTRUCTIVE_OPERATION, RiskLevel.IRREVERSIBLE_OPERATION)
                    or "delete" in description.lower()
                    or "حذف" in description.lower()
                ):
                    violates_hard_constraint = True
                    reasons.append("Violates hard constraint: deletion prohibited")

            # Preference alignment
            for p in user_prefs:
                if any(k in description.lower() for k in p.split()):
                    scores["user_preferences"] = min(1.0, scores["user_preferences"] + 0.15)
                    reasons.append("Aligns with user preference")

            # Weighted aggregate score across normalized weights
            total_score = sum(scores.get(dim, 0.5) * weight for dim, weight in self.weights.items())
            if violates_hard_constraint:
                total_score = 0.0
            total_score = round(min(1.0, max(0.0, total_score)), 4)

            evaluated.append(
                DecisionOption(
                    option_id=opt_id,
                    title=title,
                    description=description,
                    trade_offs=scores,
                    score_provenance=provenance_map,
                    risk_level=risk,
                    score=total_score,
                    is_recommended=False,
                    reasons=reasons or ["Meets engineering criteria"],
                )
            )

        # Deterministic tie-breaking:
        # Compliant candidates first (0 < 1), highest score (-score), then ascending option_id
        evaluated.sort(
            key=lambda o: (
                0 if not any("Violates hard constraint" in r for r in o.reasons) else 1,
                -round(o.score, 4),
                o.option_id,
            )
        )
        if (
            evaluated
            and evaluated[0].score > 0.0
            and not any("Violates hard constraint" in r for r in evaluated[0].reasons)
        ):
            # Mark top scoring candidate as recommended
            evaluated[0] = DecisionOption(
                option_id=evaluated[0].option_id,
                title=evaluated[0].title,
                description=evaluated[0].description,
                trade_offs=evaluated[0].trade_offs,
                score_provenance=evaluated[0].score_provenance,
                risk_level=evaluated[0].risk_level,
                score=evaluated[0].score,
                is_recommended=True,
                reasons=evaluated[0].reasons
                + ["Highest aggregate trade-off score across criteria"],
            )

        return evaluated
