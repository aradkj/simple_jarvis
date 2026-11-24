"""Alternative Solution Evaluator for JARVIS Reasoning Architecture (Section 7.3).

Evaluates candidate options across 10 engineering dimensions:
1. Correctness (meets user goal and specifications)
2. Reliability (robust under adverse or edge-case conditions)
3. Security (complies with permission boundaries, zero prompt injection risk)
4. Complexity (simplicity, minimal dependencies)
5. Cost (token and API consumption)
6. Execution time (latency and throughput)
7. Maintainability (code clarity, testability)
8. Reversibility (ability to undo or rollback without permanent data loss)
9. Compatibility (Windows 11, Python 3.12, local project environment)
10. User preferences (aligns with persistent user styles and constraints)
"""

from __future__ import annotations

from typing import Any

from core.persian.models import DecisionOption, RiskLevel


class AlternativeEvaluator:
    """Evaluates multiple approaches systematically against engineering criteria."""

    DEFAULT_WEIGHTS = {
        "correctness": 0.25,
        "security": 0.20,
        "reliability": 0.15,
        "reversibility": 0.10,
        "compatibility": 0.10,
        "user_preferences": 0.10,
        "execution_time": 0.05,
        "complexity": 0.05,
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or self.DEFAULT_WEIGHTS

    def evaluate_candidates(
        self,
        objective: str,
        candidates: list[dict[str, Any]],
        constraints: list[str] | None = None,
        user_preferences: list[str] | None = None,
    ) -> list[DecisionOption]:
        """Score candidate options across all trade-off dimensions and return ranked DecisionOption list."""
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

            # Default scores (0.0 to 1.0)
            scores = {
                "correctness": float(raw_scores.get("correctness", 0.8)),
                "security": float(
                    raw_scores.get(
                        "security",
                        0.9
                        if risk in (RiskLevel.READ_ONLY, RiskLevel.REVERSIBLE_MODIFICATION)
                        else 0.5,
                    )
                ),
                "reliability": float(raw_scores.get("reliability", 0.8)),
                "reversibility": float(
                    raw_scores.get(
                        "reversibility", 0.9 if risk != RiskLevel.DESTRUCTIVE_OPERATION else 0.2
                    )
                ),
                "compatibility": float(raw_scores.get("compatibility", 0.95)),
                "user_preferences": float(raw_scores.get("user_preferences", 0.8)),
                "execution_time": float(raw_scores.get("execution_time", 0.8)),
                "complexity": float(raw_scores.get("complexity", 0.8)),
            }

            # Constraint penalty
            reasons: list[str] = []
            for c in active_constraints:
                if "read_only" in c and risk != RiskLevel.READ_ONLY:
                    scores["security"] *= 0.2
                    scores["correctness"] *= 0.5
                    reasons.append("Violates read-only operational constraint")
                if "preserve" in c and risk in (
                    RiskLevel.DESTRUCTIVE_OPERATION,
                    RiskLevel.IRREVERSIBLE_OPERATION,
                ):
                    scores["security"] *= 0.1
                    scores["reversibility"] *= 0.1
                    reasons.append("Violates data preservation constraint")

            # Preference alignment
            for p in user_prefs:
                if any(k in description.lower() for k in p.split()):
                    scores["user_preferences"] = min(1.0, scores["user_preferences"] + 0.15)
                    reasons.append("Aligns with user preference")

            # Weighted aggregate score
            total_score = sum(scores.get(dim, 0.5) * weight for dim, weight in self.weights.items())
            total_score = round(min(1.0, max(0.0, total_score)), 4)

            evaluated.append(
                DecisionOption(
                    option_id=opt_id,
                    title=title,
                    description=description,
                    trade_offs=scores,
                    risk_level=risk,
                    score=total_score,
                    is_recommended=False,
                    reasons=reasons or ["Meets engineering criteria"],
                )
            )

        # Sort descending by score
        evaluated.sort(key=lambda o: o.score, reverse=True)
        if evaluated:
            # Mark top scoring candidate as recommended
            evaluated[0] = DecisionOption(
                option_id=evaluated[0].option_id,
                title=evaluated[0].title,
                description=evaluated[0].description,
                trade_offs=evaluated[0].trade_offs,
                risk_level=evaluated[0].risk_level,
                score=evaluated[0].score,
                is_recommended=True,
                reasons=evaluated[0].reasons
                + ["Highest aggregate trade-off score across criteria"],
            )

        return evaluated
