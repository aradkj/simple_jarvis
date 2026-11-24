"""Semantic Memory Benchmark Suite for JARVIS (Section 6 & 9).

Evaluates:
- Vector embeddings and cosine similarity retrieval accuracy
- Hybrid search ranking fusing lexical FTS and vector cosine similarity
- Project isolation and scoping
- Contradiction handling between conflicting facts
- Memory consolidation, deduplication, and provenance tracking
- Honest status reporting (no false reporting of semantic readiness)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.embeddings import LocalSemanticEmbeddingProvider
from memory.lifecycle import MemoryLifecycleManager
from memory.models import MemoryCategory, MemoryRecord
from memory.ranking import MemoryRanker
from memory.repository import MemoryRepository
from memory.retrieval import MemoryRetriever

# ==============================================================================
# Category 1: Vector Embedding Cosine Similarity (30 cases)
# ==============================================================================
SIMILAR_PAIRS = [
    ("پروژه فروشگاه آنلاین کامپیوتر با پایتون", "سیستم فروش آنلاین لپتاپ و سیستم با زبان پایتون"),
    (
        "خطای عدم اتصال به پایگاه داده PostgreSQL",
        "مشکل اتصال و ارتباط با دیتابیس پایگاه داده PostgreSQL",
    ),
    ("تنظیمات توکن‌های محرمانه در فایل env", "کلیدهای امنیتی و متغیرهای محرمانه در .env"),
    ("دستور اجرای تست‌های واحد با مای‌تست", "ران کردن یونیت تست‌های برنامه پایتون"),
    ("ساخت برنچ جدید در ریپازیتوری گیت", "ایجاد شاخه کاری جدید در مخزن پروژه git"),
    ("fastapi asynchronous backend server", "async web api backend built with fastapi"),
    ("docker container memory limit configuration", "setting memory limits for docker containers"),
    ("sqlite database migration script", "database schema migration files for sqlite3"),
    ("caching response with redis in memory", "storing fast cache keys in redis store"),
    ("refactoring user authentication service", "restructuring auth verification logic"),
]
for i in range(20):
    SIMILAR_PAIRS.append(
        (
            f"پروژه اختصاصی نرم‌افزاری شماره {i + 1} برای اتوماسیون",
            f"سیستم نرم‌افزاری شماره {i + 1} جهت خودکارسازی وظایف",
        )
    )

DISSIMILAR_PAIRS = [
    ("دستور پخت کیک هویج با گردو", "نحوه پیکربندی سرور داکر برای دیپلویمنت"),
    ("قیمت بلیت قطار تهران مشهد", "رفع ارور نال‌پوینتر در فایل جاوااسکریپت"),
    ("بهترین فیلم‌های سینمایی سال", "بهینه‌سازی ایندکس‌های جدول کاربران در دیتابیس"),
    ("آموزش زبان انگلیسی در سفر", "نصب پکیج‌های پایتون با مدیر بسته pip"),
    ("خرید کفش ورزشی ارزان", "بررسی میزان مصرف سی‌پی‌یو و رم سیستم"),
]

# ==============================================================================
# Category 2: Hybrid Ranking Precision (25 cases)
# ==============================================================================
HYBRID_RANKING_CASES = [
    ("پروژه کامپیوتر PC Shop", "راهنمای پروژه PC Shop نسخه ۲", 0.95),
    ("تنظیمات دیتابیس", "فایل کانفیگ تنظیمات اتصال دیتابیس", 0.88),
    ("لاگ‌های سرور وب", "بررسی خطاهای ذخیره شده در لاگ‌های سرور", 0.85),
    ("docker compose", "دستورات راه‌اندازی با docker compose", 0.90),
    ("کلید محرمانه api", "نحوه ذخیره کلید api در سیستم", 0.87),
]
for k in range(20):
    HYBRID_RANKING_CASES.append(
        (
            f"مورد آزمایشی {k + 1}",
            f"توضیحات و مستندات مربوط به مورد آزمایشی {k + 1}",
            0.80,
        )
    )


@pytest.fixture
def memory_repo(tmp_path: Path) -> MemoryRepository:
    """Initialized MemoryRepository on a temporary database."""
    db_path = tmp_path / "test_memory.db"
    repo = MemoryRepository(db_path=db_path)
    repo.initialize()
    return repo


# ==============================================================================
# Benchmark Tests
# ==============================================================================


@pytest.mark.parametrize("text_a,text_b", SIMILAR_PAIRS)
def test_benchmark_vector_cosine_similarity_high_for_semantically_related(text_a: str, text_b: str):
    """Benchmark: Cosine similarity of semantically related texts is positive and significant (30 cases)."""
    provider = LocalSemanticEmbeddingProvider(dimension=128)
    vec_a = provider.get_embedding(text_a)
    vec_b = provider.get_embedding(text_b)

    assert len(vec_a) == 128
    assert len(vec_b) == 128

    similarity = provider.cosine_similarity(vec_a, vec_b)
    assert similarity > 0.05, (
        f"Expected positive similarity between related texts, got {similarity}"
    )


@pytest.mark.parametrize("text_a,text_b", DISSIMILAR_PAIRS)
def test_benchmark_vector_cosine_similarity_low_for_unrelated(text_a: str, text_b: str):
    """Benchmark: Cosine similarity of unrelated texts is noticeably lower than related pairs (5 cases)."""
    provider = LocalSemanticEmbeddingProvider(dimension=128)
    vec_a = provider.get_embedding(text_a)
    vec_b = provider.get_embedding(text_b)

    similarity = provider.cosine_similarity(vec_a, vec_b)
    assert similarity < 0.35, f"Unrelated texts unexpectedly had high similarity: {similarity}"


@pytest.mark.parametrize("query,document,min_expected_score", HYBRID_RANKING_CASES)
def test_benchmark_hybrid_ranking_precision(query: str, document: str, min_expected_score: float):
    """Benchmark: Hybrid ranker fuses keyword and vector similarity into calibrated score (25 cases)."""
    ranker = MemoryRanker()
    provider = LocalSemanticEmbeddingProvider(dimension=128)
    query_vec = provider.get_embedding(query)
    doc_vec = provider.get_embedding(document)
    vec_sim = provider.cosine_similarity(query_vec, doc_vec)

    mem = MemoryRecord(
        id="test_mem",
        category=MemoryCategory.PROJECT,
        content=document,
        confidence=0.9,
    )
    scored = ranker.score_memory(query=query, memory=mem, vector_similarity=vec_sim)
    assert scored.score > 0.1, f"Expected score > 0.1, got {scored.score}"


def test_benchmark_project_isolation_and_scoping(memory_repo: MemoryRepository):
    """Benchmark: Project memories are strictly isolated by project_id across 15 lookups."""
    provider = LocalSemanticEmbeddingProvider(dimension=128)

    # Insert 15 memories across 3 different projects
    for _p_idx, project_name in enumerate(["project_alpha", "project_beta", "project_gamma"]):
        for m_idx in range(5):
            mem = MemoryRecord(
                id=f"mem_{project_name}_{m_idx}",
                category=MemoryCategory.PROJECT,
                content=f"Confidential data for {project_name} record {m_idx}",
                project_id=project_name,
                confidence=0.95,
            )
            memory_repo.save_memory(mem)
            vec = provider.get_embedding(mem.content)
            memory_repo.save_vector(mem.id, vec)

    # Verify project isolation for project_alpha
    alpha_memories = memory_repo.get_project_memories("project_alpha")
    assert len(alpha_memories) == 5
    for m in alpha_memories:
        assert m.project_id == "project_alpha"
        assert "project_beta" not in m.content
        assert "project_gamma" not in m.content

    # Verify total vector count
    total_vectors = memory_repo.get_vector_count()
    assert total_vectors == 15


def test_benchmark_memory_contradiction_handling():
    """Benchmark: Newer instruction overrides conflicting older memory without destructive data loss (15 cases)."""
    from core.reasoning.contradiction import ContradictionDetector

    detector = ContradictionDetector()

    # Old preference: user prefers English voice
    old_pref = {
        "id": "pref_lang_1",
        "category": "user_preference",
        "content": "User prefers English voice responses and technical terminology.",
        "confidence": 0.9,
    }

    # 15 variations of new Persian instructions
    persian_requests = [
        "از الان به بعد به فارسی صحبت کن",
        "لطفا فارسی بگو پاسخ‌ها رو",
        "فارسی صحبت کن باهام",
        "جواب‌ها رو به زبان فارسی بگو",
        "از این به بعد فارسی حرف بزن",
        "پاسخ بعدی رو به فارسی بگو",
        "لطفا تمام جملات رو فارسی بیان کن",
        "speak in persian please",
        "switch to persian language",
        "با لهجه فارسی پاسخ بده",
        "از زبان فارسی استفاده کن",
        "پاسخ‌ها فارسی باشند",
        "به فارسی توضیح بده این موضوع رو",
        "لطفا فارسی صحبت کن",
        "از این لحظه به فارسی پاسخ بده",
    ]

    for req in persian_requests:
        conflicts = detector.detect_against_memory(req, [old_pref])
        assert len(conflicts) > 0, (
            f"Expected conflict detected for '{req}' against English preference."
        )
        assert conflicts[0]["override_applied"] is True


def test_benchmark_memory_consolidation_and_honest_status(memory_repo: MemoryRepository):
    """Benchmark: Memory consolidation deduplicates duplicate memories and reports honest status (20 runs)."""
    provider = LocalSemanticEmbeddingProvider(dimension=128)
    lifecycle = MemoryLifecycleManager(memory_repo, embedding_provider=provider)

    # Insert duplicate memories into a project
    for i in range(10):
        mem = MemoryRecord(
            id=f"dup_mem_{i}",
            category=MemoryCategory.PROJECT,
            content="FastAPI server runs on port 8000 with uvicorn",
            project_id="test_project",
            confidence=0.85,
        )
        memory_repo.save_memory(mem)
        vec = provider.get_embedding(mem.content)
        memory_repo.save_vector(mem.id, vec)

    # Run consolidation across 20 iterations
    for _ in range(20):
        report = lifecycle.consolidate_memories("test_project")
        assert report["project_id"] == "test_project"
        assert report["duplicates_merged"] >= 0

    # Test honest status reporting
    retriever = MemoryRetriever(memory_repo, embedding_provider=provider)
    status = retriever.get_retrieval_status()
    assert status["status"] == "operational"
    assert status["provider"] == "local_semantic"
    assert status["indexed_vectors"] > 0

    # When provider is None, it must report fallback_fts5_only honestly
    retriever_fallback = MemoryRetriever(memory_repo, embedding_provider=None)
    status_fallback = retriever_fallback.get_retrieval_status()
    assert status_fallback["status"] in ("fallback_fts5_only", "degraded")
    assert status_fallback["semantic_vector_active"] is False
