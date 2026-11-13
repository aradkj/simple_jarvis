"""Deterministic relevance ranking and multi-signal scoring for retrieved memories."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from memory.models import MemoryRecord


@dataclass(frozen=True)
class ScoredMemory:
    """Memory record paired with computed relevance score components."""

    record: MemoryRecord
    total_score: float
    keyword_score: float
    importance_score: float
    recency_score: float
    confidence_score: float
    project_boost: float


class MemoryRanker:
    """Computes deterministic multi-signal ranking scores for memory candidates."""

    def __init__(
        self,
        weight_relevance: float = 0.40,
        weight_importance: float = 0.25,
        weight_recency: float = 0.20,
        weight_confidence: float = 0.15,
        project_boost_value: float = 0.15,
        recency_half_life_days: float = 30.0,
    ) -> None:
        self.w_rel = weight_relevance
        self.w_imp = weight_importance
        self.w_rec = weight_recency
        self.w_conf = weight_confidence
        self.project_boost = project_boost_value
        self.half_life_days = recency_half_life_days

    def _tokenize(self, text: str) -> set[str]:
        """Extract lowercased word tokens."""
        return set(re.findall(r"\w+", text.lower()))

    def compute_keyword_similarity(self, query: str, content: str, key: str) -> float:
        """Compute token overlap and substring match similarity (0.0 to 1.0)."""
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return 0.0

        c_tokens = self._tokenize(content) | self._tokenize(key)
        if not c_tokens:
            return 0.0

        overlap = q_tokens & c_tokens
        jaccard = len(overlap) / len(q_tokens | c_tokens)
        query_coverage = len(overlap) / len(q_tokens)

        # Direct phrase or keyword substring bonus
        q_clean = query.strip().lower()
        c_clean = content.strip().lower()
        k_clean = key.strip().lower()
        phrase_bonus = (
            0.2 if (q_clean in c_clean or q_clean in k_clean or k_clean in q_clean) else 0.0
        )

        return min(1.0, (0.6 * query_coverage) + (0.2 * jaccard) + phrase_bonus)

    def compute_recency_score(self, dt: datetime) -> float:
        """Exponential decay based on elapsed days since update."""
        now = datetime.now(UTC)
        # Ensure dt is timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta_days = max(0.0, (now - dt).total_seconds() / 86400.0)
        # Half-life exponential decay: e^(-lambda * t), where lambda = ln(2) / half_life
        decay_constant = math.log(2.0) / max(1.0, self.half_life_days)
        return math.exp(-decay_constant * delta_days)

    def score_record(
        self,
        record: MemoryRecord,
        query: str,
        current_project_id: str | None = None,
        base_keyword_score: float | None = None,
    ) -> ScoredMemory:
        """Calculate total deterministic relevance score for a memory record."""
        # 1. Keyword / Lexical Score
        if base_keyword_score is not None:
            kw_score = max(0.0, min(1.0, base_keyword_score))
        else:
            kw_score = self.compute_keyword_similarity(query, record.content, record.key)

        # 2. Importance Score
        imp_score = max(0.0, min(1.0, record.importance))

        # 3. Recency Score
        rec_score = self.compute_recency_score(record.updated_at)

        # 4. Confidence Score
        conf_score = max(0.0, min(1.0, record.confidence))

        # 5. Project Boost
        p_boost = 0.0
        if current_project_id and record.project_id == current_project_id:
            p_boost = self.project_boost

        raw_total = (
            (kw_score * self.w_rel)
            + (imp_score * self.w_imp)
            + (rec_score * self.w_rec)
            + (conf_score * self.w_conf)
            + p_boost
        )

        total_score = min(1.0, round(raw_total, 4))

        return ScoredMemory(
            record=record,
            total_score=total_score,
            keyword_score=round(kw_score, 4),
            importance_score=round(imp_score, 4),
            recency_score=round(rec_score, 4),
            confidence_score=round(conf_score, 4),
            project_boost=p_boost,
        )

    def rank_records(
        self,
        records: list[MemoryRecord],
        query: str,
        current_project_id: str | None = None,
        min_threshold: float = 0.15,
        limit: int = 5,
    ) -> list[ScoredMemory]:
        """Score, filter by threshold, and sort memories deterministically."""
        scored: list[ScoredMemory] = []
        for r in records:
            sm = self.score_record(r, query, current_project_id)
            if sm.total_score >= min_threshold:
                scored.append(sm)

        # Deterministic sorting: highest score first, tie-break by updated_at descending, then id
        scored.sort(
            key=lambda item: (
                -item.total_score,
                -item.record.updated_at.timestamp(),
                item.record.id,
            )
        )

        return scored[:limit]
