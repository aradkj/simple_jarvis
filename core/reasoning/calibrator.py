"""Confidence Calibrator for JARVIS Reasoning Architecture (Section 7.5).

Calibrates confidence based on verifiable evidence rather than self-reported LLM confidence:
- Evidence availability
- Retrieval relevance and rank quality
- Agreement across independent sources
- Tool execution outcomes and verification
- Ambiguity and speculation indicators

Maps to strongly-typed ConfidenceLevel:
- VERIFIED (confirmed by tool execution or deterministic ground truth)
- STRONGLY_SUPPORTED (solid multi-source evidence, high retrieval score, zero contradiction)
- PROBABLE (reasonable assumption, standard likelihood, non-critical)
- UNCERTAIN (ambiguous context, weak retrieval score, or minor inconsistency)
- UNKNOWN (no evidence, speculative inference, or explicitly missing data)
"""

from __future__ import annotations

from typing import Any

from core.persian.models import ConfidenceLevel


class ConfidenceCalibrator:
    """Computes calibrated, evidence-grounded confidence levels."""

    def calibrate(
        self,
        has_tool_verification: bool = False,
        retrieval_score: float = 0.0,
        ambiguity_count: int = 0,
        is_hypothetical: bool = False,
        contradiction_detected: bool = False,
        user_confirmed: bool = False,
        signals_agreement_score: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ConfidenceLevel, float, str]:
        """Evaluate evidence signals and return (level, calibrated_score, explanation).

        Returns:
            (ConfidenceLevel, float_score: 0.0..1.0, explanation: str)
        """
        # 1. Highest tier: Verified by real tool output or explicit user confirmation
        if (user_confirmed or has_tool_verification) and (
            not contradiction_detected and ambiguity_count == 0
        ):
            return (
                ConfidenceLevel.VERIFIED,
                1.0,
                "Verified directly by tool execution outcome or user confirmation.",
            )

        # 2. Speculative / hypothetical inquiries
        if is_hypothetical:
            return (
                ConfidenceLevel.UNCERTAIN,
                0.40,
                "Hypothetical scenario based on theoretical reasoning without execution.",
            )

        # 3. Contradiction detected
        if contradiction_detected:
            return (
                ConfidenceLevel.UNCERTAIN,
                0.30,
                "Uncertain due to detected contradictions in context or instructions.",
            )

        # 4. Ambiguity detected
        if ambiguity_count > 0:
            return (
                ConfidenceLevel.UNCERTAIN,
                max(0.20, 0.50 - (ambiguity_count * 0.15)),
                f"Uncertain due to {ambiguity_count} ambiguous references or underspecified parameters.",
            )

        # 5. Retrieval evidence scoring
        if retrieval_score <= 0.0:
            return (
                ConfidenceLevel.UNKNOWN,
                0.10,
                "Insufficient evidence available to substantiate conclusion.",
            )

        if retrieval_score >= 0.70 and signals_agreement_score >= 0.80:
            return (
                ConfidenceLevel.STRONGLY_SUPPORTED,
                round(0.70 + (retrieval_score * 0.25), 4),
                "Strongly supported by relevant retrieved memories and consistent signals.",
            )

        if retrieval_score >= 0.35:
            return (
                ConfidenceLevel.PROBABLE,
                round(0.40 + (retrieval_score * 0.30), 4),
                "Probable conclusion supported by available conversational context.",
            )

        return (
            ConfidenceLevel.UNCERTAIN,
            round(retrieval_score, 4),
            "Uncertain: available evidence is limited or weak.",
        )
