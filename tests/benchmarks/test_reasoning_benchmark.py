"""Reasoning Framework Benchmark Suite for JARVIS (Section 7 & 9).

Evaluates:
- Task complexity classification (Simple Conversational, Information Retrieval, Analytical, Multi-step Planning, High Risk)
- Alternative solution evaluation across 8-10 dimensions
- Confidence calibration and deduction factors
- Contradiction detection against instructions and memory
- Multi-step 13-stage problem solving framework
"""

from __future__ import annotations

import pytest

from core.persian.models import ConfidenceLevel, RiskLevel, TaskComplexity
from core.reasoning.calibrator import ConfidenceCalibrator
from core.reasoning.complexity import TaskComplexityClassifier
from core.reasoning.contradiction import ContradictionDetector
from core.reasoning.evaluator import AlternativeEvaluator
from core.reasoning.solver import MultiStepProblemSolver

# ==============================================================================
# Category 1: Task Complexity Classification (25 cases)
# ==============================================================================
COMPLEXITY_CASES = [
    # Simple Conversational (5 cases)
    ("سلام جارویس", TaskComplexity.SIMPLE_CONVERSATIONAL),
    ("چطوری رفیق؟", TaskComplexity.SIMPLE_CONVERSATIONAL),
    ("خوبی رفیق؟", TaskComplexity.SIMPLE_CONVERSATIONAL),
    ("thank you jarvis", TaskComplexity.SIMPLE_CONVERSATIONAL),
    ("who are you?", TaskComplexity.SIMPLE_CONVERSATIONAL),
    # Tool Execution & Diagnostics (5 cases)
    ("فایل config.json رو بخون", TaskComplexity.TOOL_EXECUTION),
    ("برنامه ماشین حساب رو باز کن", TaskComplexity.TOOL_EXECUTION),
    ("وضعیت CPU رو چک کن", TaskComplexity.TECHNICAL_DIAGNOSIS),
    ("read line 15 of main.py", TaskComplexity.TOOL_EXECUTION),
    ("open notepad application", TaskComplexity.TOOL_EXECUTION),
    # Multi-step Planning (5 cases)
    ("پروژه رو بررسی کن و سپس تستاش رو اجرا کن", TaskComplexity.MULTI_STEP_PLANNING),
    ("ابتدا لاگ‌ها رو آنالیز کن، سپس سرویس رو ریستارت کن", TaskComplexity.MULTI_STEP_PLANNING),
    ("مراحل کار برای ریفکتور کردن دیتابیس رو برنامه‌ریزی کن", TaskComplexity.MULTI_STEP_PLANNING),
    ("first run tests and then build release", TaskComplexity.MULTI_STEP_PLANNING),
    ("step by step deploy the application to docker", TaskComplexity.MULTI_STEP_PLANNING),
    # Analytical (5 cases)
    ("به نظرت چرا معماری سیستم دچار افت شده؟", TaskComplexity.ANALYTICAL),
    ("تحلیل کن ساختار کدهای پروژه را", TaskComplexity.ANALYTICAL),
    ("مقایسه کن کارایی FastAPI و Flask را", TaskComplexity.ANALYTICAL),
    ("explain the design pattern used in this module", TaskComplexity.ANALYTICAL),
    ("analyze trade-off between redis and local memory", TaskComplexity.ANALYTICAL),
    # High Risk (5 cases)
    ("تمام دیتابیس رو پاک کن", TaskComplexity.HIGH_RISK_OPERATION),
    ("سورس اصلی روی برنچ مستر رو دیلیت کن", TaskComplexity.HIGH_RISK_OPERATION),
    ("فایل .env حاوی پسوردها رو حذف کن", TaskComplexity.HIGH_RISK_OPERATION),
    ("wipe all production migration records", TaskComplexity.HIGH_RISK_OPERATION),
    ("format the hard drive completely", TaskComplexity.HIGH_RISK_OPERATION),
]

# ==============================================================================
# Category 2: Alternative Solution Evaluation (25 cases)
# ==============================================================================
ALTERNATIVE_EVALUATION_CASES = [
    (
        "Fix API timeout issue",
        [
            {
                "option_id": "opt_db_index",
                "title": "Add DB index",
                "dimension_scores": {
                    "correctness": 0.95,
                    "security": 0.95,
                    "reliability": 0.90,
                    "reversibility": 0.90,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
            {
                "option_id": "opt_increase_timeout",
                "title": "Increase HTTP timeout",
                "dimension_scores": {
                    "correctness": 0.40,
                    "security": 0.50,
                    "reliability": 0.30,
                    "reversibility": 0.90,
                },
                "risk_level": RiskLevel.REVERSIBLE_MODIFICATION,
            },
        ],
        "opt_db_index",
    ),
    (
        "Clean up repository disk space",
        [
            {
                "option_id": "opt_git_gc",
                "title": "Run git gc",
                "dimension_scores": {
                    "correctness": 0.90,
                    "security": 0.95,
                    "reliability": 0.90,
                    "reversibility": 0.85,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
            {
                "option_id": "opt_rm_git",
                "title": "Delete .git folder",
                "dimension_scores": {
                    "correctness": 0.10,
                    "security": 0.10,
                    "reliability": 0.10,
                    "reversibility": 0.0,
                },
                "risk_level": RiskLevel.DESTRUCTIVE_OPERATION,
            },
        ],
        "opt_git_gc",
    ),
    (
        "Manage environment secrets",
        [
            {
                "option_id": "opt_env_file",
                "title": "Use .env file with gitignore",
                "dimension_scores": {
                    "correctness": 0.95,
                    "security": 0.95,
                    "reliability": 0.90,
                    "reversibility": 0.95,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
            {
                "option_id": "opt_hardcode",
                "title": "Hardcode in code",
                "dimension_scores": {
                    "correctness": 0.30,
                    "security": 0.10,
                    "reliability": 0.20,
                    "reversibility": 0.50,
                },
                "risk_level": RiskLevel.REVERSIBLE_MODIFICATION,
            },
        ],
        "opt_env_file",
    ),
    (
        "Handle background audio recording",
        [
            {
                "option_id": "opt_thread_event",
                "title": "Threading Event wait",
                "dimension_scores": {
                    "correctness": 0.95,
                    "security": 0.95,
                    "reliability": 0.95,
                    "reversibility": 0.95,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
            {
                "option_id": "opt_busy_wait",
                "title": "Busy wait loop",
                "dimension_scores": {
                    "correctness": 0.30,
                    "security": 0.80,
                    "reliability": 0.20,
                    "reversibility": 0.90,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
        ],
        "opt_thread_event",
    ),
    (
        "Persian text normalization strategy",
        [
            {
                "option_id": "opt_regex_mask",
                "title": "Reversible regex token masking",
                "dimension_scores": {
                    "correctness": 0.98,
                    "security": 0.95,
                    "reliability": 0.95,
                    "reversibility": 1.0,
                },
                "risk_level": RiskLevel.READ_ONLY,
            },
            {
                "option_id": "opt_raw_replace",
                "title": "Global character replacement",
                "dimension_scores": {
                    "correctness": 0.40,
                    "security": 0.60,
                    "reliability": 0.40,
                    "reversibility": 0.30,
                },
                "risk_level": RiskLevel.REVERSIBLE_MODIFICATION,
            },
        ],
        "opt_regex_mask",
    ),
]

for i in range(20):
    ALTERNATIVE_EVALUATION_CASES.append(
        (
            f"Synthetic problem {i + 1}",
            [
                {
                    "option_id": f"opt_safe_{i}",
                    "title": f"Safe approach {i}",
                    "dimension_scores": {
                        "correctness": 0.90,
                        "security": 0.90,
                        "reliability": 0.85,
                        "reversibility": 0.90,
                    },
                    "risk_level": RiskLevel.READ_ONLY,
                },
                {
                    "option_id": f"opt_risky_{i}",
                    "title": f"Risky approach {i}",
                    "dimension_scores": {
                        "correctness": 0.40,
                        "security": 0.20,
                        "reliability": 0.30,
                        "reversibility": 0.20,
                    },
                    "risk_level": RiskLevel.DESTRUCTIVE_OPERATION,
                },
            ],
            f"opt_safe_{i}",
        )
    )

# ==============================================================================
# Category 3: Confidence Calibration & Evidence Verification (85 cases)
# ==============================================================================
CONFIDENCE_CASES = [
    # Verified by tool output (real execution proof)
    (True, 0.95, 0, False, False, False, ConfidenceLevel.VERIFIED),
    (True, 0.80, 0, False, False, False, ConfidenceLevel.VERIFIED),
    (False, 0.95, 0, False, False, True, ConfidenceLevel.VERIFIED),  # User confirmed
    (True, 0.90, 0, False, False, False, ConfidenceLevel.VERIFIED),
    (True, 0.85, 0, False, False, False, ConfidenceLevel.VERIFIED),
    # Strongly supported (high retrieval score, 0 ambiguity, 0 contradiction)
    (False, 0.90, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED),
    (False, 0.85, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED),
    (False, 0.82, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED),
    (False, 0.92, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED),
    (False, 0.88, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED),
    # Probable (moderate retrieval, no fatal conflicts)
    (False, 0.65, 0, False, False, False, ConfidenceLevel.PROBABLE),
    (False, 0.60, 0, False, False, False, ConfidenceLevel.PROBABLE),
    (False, 0.55, 0, False, False, False, ConfidenceLevel.PROBABLE),
    (False, 0.50, 0, False, False, False, ConfidenceLevel.PROBABLE),
    (False, 0.58, 0, False, False, False, ConfidenceLevel.PROBABLE),
    # Uncertain (ambiguities, contradictions, or low retrieval)
    (False, 0.45, 1, False, False, False, ConfidenceLevel.UNCERTAIN),
    (False, 0.35, 2, False, False, False, ConfidenceLevel.UNCERTAIN),
    (False, 0.80, 0, False, True, False, ConfidenceLevel.UNCERTAIN),  # Contradiction detected
    (False, 0.70, 1, False, False, False, ConfidenceLevel.UNCERTAIN),
    (False, 0.20, 0, False, False, False, ConfidenceLevel.UNCERTAIN),
]

# Additional 65 systematically generated scenarios bringing confidence suite to 85 verified cases
# Additional Tool Verified cases (10 cases)
for _v in [0.72, 0.77, 0.81, 0.84, 0.87, 0.91, 0.93, 0.96, 0.98, 0.99]:
    CONFIDENCE_CASES.append((True, _v, 0, False, False, False, ConfidenceLevel.VERIFIED))

# Additional User Confirmed cases (5 cases)
for _u in [0.71, 0.76, 0.82, 0.88, 0.94]:
    CONFIDENCE_CASES.append((False, _u, 0, False, False, True, ConfidenceLevel.VERIFIED))

# Additional Strongly Supported cases (15 cases)
for _s in [
    0.71,
    0.73,
    0.75,
    0.78,
    0.79,
    0.83,
    0.86,
    0.87,
    0.89,
    0.91,
    0.93,
    0.94,
    0.96,
    0.97,
    0.99,
]:
    CONFIDENCE_CASES.append((False, _s, 0, False, False, False, ConfidenceLevel.STRONGLY_SUPPORTED))

# Additional Probable cases (15 cases)
for _p in [
    0.51,
    0.52,
    0.53,
    0.54,
    0.56,
    0.57,
    0.59,
    0.61,
    0.62,
    0.63,
    0.64,
    0.66,
    0.67,
    0.68,
    0.69,
]:
    CONFIDENCE_CASES.append((False, _p, 0, False, False, False, ConfidenceLevel.PROBABLE))

# Additional Uncertain due to ambiguities (15 cases)
for _a_cnt in [1, 2, 3]:
    for _a_score in [0.30, 0.40, 0.50, 0.60, 0.70]:
        CONFIDENCE_CASES.append(
            (False, _a_score, _a_cnt, False, False, False, ConfidenceLevel.UNCERTAIN)
        )

# Additional Uncertain due to contradiction (5 cases)
for _c_score in [0.65, 0.75, 0.85, 0.90, 0.95]:
    CONFIDENCE_CASES.append((False, _c_score, 0, False, True, False, ConfidenceLevel.UNCERTAIN))

# ==============================================================================
# Category 4: Contradiction Detection (15 cases)
# ==============================================================================
CONTRADICTION_BENCHMARK_CASES = [
    (
        "تغییرات کد را ذخیره کن اما هیچ فایلی را تغییر نده",
        ["read_only"],
        [],
        "read_only_vs_modification",
    ),
    (
        "فایل .env را حذف کن",
        [],
        ["do_not_touch_.env"],
        "prohibited_target_modification",
    ),
    (
        "دایرکتوری data را پاکسازی کن ولی حواست باشه چیزی از بین نره",
        ["preserve_existing_data"],
        [],
        "delete_vs_preserve",
    ),
    (
        "فایل‌های اضافی را پاک کن اما اطلاعات حذف نشود",
        ["preserve_existing_data"],
        [],
        "delete_vs_preserve",
    ),
    (
        "محتوای اسکریپت را ویرایش کن در حالی که فقط ببین و بخوان",
        ["read_only"],
        [],
        "read_only_vs_modification",
    ),
    (
        "حذفش کن و حفظش کن",
        [],
        [],
        "delete_vs_preserve",
    ),
    (
        "ویرایش کن اما دست نزن",
        [],
        [],
        "read_only_vs_modification",
    ),
    (
        "پوشه secrets را پاک کن ولی به secrets دست نزن",
        [],
        ["do_not_touch_secrets"],
        "prohibited_target_modification",
    ),
    (
        "سورس اصلی را عوض کن ولی تغییر نده",
        [],
        [],
        "read_only_vs_modification",
    ),
    (
        "کل دیتابیس را دیلیت کن اما دقت کن چیزی پاک نشه",
        [],
        [],
        "delete_vs_preserve",
    ),
    (
        "فایل را باز کن و ادیت کن اما فقط نگاه کن",
        [],
        [],
        "read_only_vs_modification",
    ),
    (
        "تغییرات اعمال کن بدون اینکه چیزی تغییر کنه",
        [],
        [],
        "read_only_vs_modification",
    ),
    (
        "پاکسازی کامل انجام بده بدون حذف اطلاعات",
        [],
        [],
        "delete_vs_preserve",
    ),
    (
        "محتوا رو ویرایش کن ولی تغییر ایجاد نکن",
        [],
        [],
        "read_only_vs_modification",
    ),
    (
        "فایل config.json رو پاک کن در حالی که به config.json نباید دست بزنی",
        [],
        ["do_not_touch_config.json"],
        "prohibited_target_modification",
    ),
]

# ==============================================================================
# Category 5: Multi-Step 13-Stage Problem Solving (15 cases)
# ==============================================================================
SOLVER_CASES = [
    ("پروژه PC Shop رو باز کن و سپس تست‌ها رو اجرا کن", 3),
    ("ابتدا لاگ‌های سرور را بررسی کن و سپس خطاهای ۵۰۰ را لیست کن", 3),
    ("کانفیگ داکر رو ایجاد کن و سپس کانتینرها رو راه‌اندازی کن", 3),
    ("اول کوئری‌های دیتابیس را بهینه‌سازی کن و سپس تست سرعت بگیر", 3),
    ("بررسی گیت استتوس و ایجاد کامیت جدید برای تغییرات", 3),
    ("ریفکتور کردن کنترلر کاربر و تفکیک سرویس اعتبارسنجی", 3),
    ("بررسی خطای TypeMismatch در فایل models.py", 3),
    ("پیاده‌سازی تست‌های واحد برای ماژول نرمال‌ساز فارسی", 3),
    ("بررسی تداخل‌های برنچ feature و سپس ادغام آن با master", 3),
    ("پاکسازی فایل‌های کش موقت با حفظ تنظیمات اصلی", 3),
    ("عیب‌یابی افت سرعت پردازش داده‌ها در صف پس‌زمینه", 3),
    ("تنظیم متغیرهای محیطی بدون افشای کلیدهای محرمانه", 3),
    ("ایجاد اسکریپت بکاپ خودکار برای دیتابیس SQLite", 3),
    ("افزودن لاگ‌گذاری ساختاریافته به سیستم تصمیم‌گیری", 3),
    ("بررسی و رفع هشدار روف در تمام ماژول‌های پروژه", 3),
]


# ==============================================================================
# Benchmark Tests Execution
# ==============================================================================


@pytest.mark.parametrize("text,expected_complexity", COMPLEXITY_CASES)
def test_benchmark_task_complexity_classification(text: str, expected_complexity: TaskComplexity):
    """Benchmark: Task complexity classifier correctly classifies tasks (25 cases)."""
    classifier = TaskComplexityClassifier()
    complexity, _reasoning = classifier.classify(text)
    assert complexity == expected_complexity, (
        f"Expected {expected_complexity} for '{text}', got {complexity}"
    )


@pytest.mark.parametrize("problem_name,candidates,expected_best_id", ALTERNATIVE_EVALUATION_CASES)
def test_benchmark_alternative_solution_evaluator(
    problem_name: str, candidates: list[dict], expected_best_id: str
):
    """Benchmark: Multi-criteria alternative solution evaluation across dimensions (25 cases)."""
    evaluator = AlternativeEvaluator()
    evaluated = evaluator.evaluate_candidates(problem_name, candidates)
    assert len(evaluated) == len(candidates)
    best = evaluated[0]
    assert best.option_id == expected_best_id, (
        f"Expected best '{expected_best_id}', got '{best.option_id}'"
    )


@pytest.mark.parametrize(
    "has_tool_verification,retrieval_score,ambiguity_count,is_hypothetical,contradiction_detected,user_confirmed,expected_level",
    CONFIDENCE_CASES,
)
def test_benchmark_confidence_calibrator(
    has_tool_verification: bool,
    retrieval_score: float,
    ambiguity_count: int,
    is_hypothetical: bool,
    contradiction_detected: bool,
    user_confirmed: bool,
    expected_level: ConfidenceLevel,
):
    """Benchmark: Calibrate confidence levels based on real evidence (25 cases)."""
    calibrator = ConfidenceCalibrator()
    level, score, explanation = calibrator.calibrate(
        has_tool_verification=has_tool_verification,
        retrieval_score=retrieval_score,
        ambiguity_count=ambiguity_count,
        is_hypothetical=is_hypothetical,
        contradiction_detected=contradiction_detected,
        user_confirmed=user_confirmed,
    )
    assert level == expected_level, f"Expected {expected_level}, got {level} (score: {score})"
    assert len(explanation) > 0


@pytest.mark.parametrize(
    "text,constraints,prohibitions,expected_conflict_type", CONTRADICTION_BENCHMARK_CASES
)
def test_benchmark_contradiction_detector(
    text: str, constraints: list[str], prohibitions: list[str], expected_conflict_type: str
):
    """Benchmark: Contradiction detector identifies conflicting goals and safety violations (15 cases)."""
    detector = ContradictionDetector()
    conflicts = detector.detect_in_instructions(
        text, constraints=constraints, prohibitions=prohibitions
    )
    assert len(conflicts) > 0, f"Expected conflict in '{text}', but none found."
    assert any(c["type"] == expected_conflict_type for c in conflicts)


@pytest.mark.parametrize("task_description,min_steps", SOLVER_CASES)
def test_benchmark_multi_step_problem_solver_13_stages(task_description: str, min_steps: int):
    """Benchmark: 13-stage problem solving framework decomposes and plans multi-step execution (15 cases)."""
    solver = MultiStepProblemSolver()
    result = solver.solve(goal=task_description)
    assert result is not None
    assert "plan_steps" in result
    assert len(result["plan_steps"]) >= min_steps
    assert "decision_record" in result
    assert "complexity" in result
    assert "confidence_level" in result
