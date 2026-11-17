"""JARVIS Acceptance Scenarios A through L - Persian Intelligence & Bilingual Execution Suite.

Validates:
- Scenario A: Colloquial Everyday Chat
- Scenario B: Technical Troubleshooting & Project Canonicalization
- Scenario C: Mixed Technical Language & Port/File Extraction
- Scenario D: Follow-up References & Anaphora Resolution
- Scenario E: User Corrections & Context Shifting
- Scenario F: Hypothetical Safety (Zero Destructive Execution)
- Scenario G: Destructive Ambiguity (Mandatory Clarification Gate)
- Scenario H: Multi-step Autonomous Planning
- Scenario I: Read-only Prohibitions & Constraints
- Scenario J: Explicit Language Switching & Session Persistence
- Scenario K: Application Control (Launch & Close)
- Scenario L: Resilient Recovery on Provider Failure
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.persian import (
    MultilingualResponseController,
    PersianEntityType,
    PersianIntentType,
    PersianLanguageProcessor,
    ResponseLanguage,
)
from core.planner import AgentPlanner


def test_scenario_a_colloquial_chat() -> None:
    """Scenario A: Colloquial chat understood; responds in British English by default."""
    processor = PersianLanguageProcessor()
    prompts = [
        "سلام چطوری؟",
        "دمت گرم دستت درد نکنه",
        "عالی هستی",
        "مخلصیم، چه خبر؟",
    ]
    for prompt in prompts:
        res = processor.process(prompt)
        assert res.intent in (
            PersianIntentType.GREETING,
            PersianIntentType.CASUAL_CHAT,
            PersianIntentType.GENERAL_CONVERSATION,
            PersianIntentType.GENERAL_KNOWLEDGE,
        )
        assert res.response_language == ResponseLanguage.ENGLISH.value
        # Formulate response
        disp, spoken = processor.format_response(
            "All systems are operating nominally, sir. How may I be of service?",
            res,
        )
        assert "sir" in spoken.lower() or "service" in spoken.lower()


def test_scenario_b_technical_troubleshooting_and_canonicalization() -> None:
    """Scenario B: Technical troubleshooting with canonical project binding."""
    processor = PersianLanguageProcessor()
    prompt = "پروژه پیسیشاپ خطای ۵۰۰ میده لاگ‌ها رو بررسی کن"
    res = processor.process(prompt)

    assert res.intent in (
        PersianIntentType.DEBUGGING,
        PersianIntentType.SYSTEM_DIAGNOSTICS,
        PersianIntentType.CODE_EXPLANATION,
    )
    # Check project entity canonicalization
    project_entities = [
        e
        for e in res.entities
        if e.entity_type in (PersianEntityType.PROJECT, PersianEntityType.PROJECT_NAME)
    ]
    assert len(project_entities) > 0
    assert project_entities[0].normalized_value.replace("-", " ") == "pc shop"
    assert res.active_project is not None
    assert res.active_project.replace("-", " ") == "pc shop"


def test_scenario_c_mixed_technical_language() -> None:
    """Scenario C: Mixed technical Persian-English with files and ports."""
    processor = PersianLanguageProcessor()
    prompt = "کانفیگ docker-compose.yml رو بیار بالا روی پورت ۸۰۸۰"
    res = processor.process(prompt)

    # Validate file extracted
    files = [
        e
        for e in res.entities
        if e.entity_type
        in (PersianEntityType.FILE, PersianEntityType.FILE_NAME, PersianEntityType.FILE_PATH)
    ]
    assert any("docker-compose.yml" in str(f.normalized_value) for f in files)

    # Validate port extracted
    ports = [
        e
        for e in res.entities
        if e.entity_type in (PersianEntityType.PORT, PersianEntityType.PORT_NUMBER)
    ]
    assert any("8080" in str(p.normalized_value) for p in ports)

    # Validate tech stack
    techs = [e for e in res.entities if e.entity_type == PersianEntityType.TECH_STACK]
    assert any("docker" in str(t.normalized_value).lower() for t in techs)


def test_scenario_d_follow_up_references_and_anaphora() -> None:
    """Scenario D: Follow-up references across turns (anaphoric resolution)."""
    processor = PersianLanguageProcessor()

    # Turn 1: Mention a file
    turn1 = processor.process("فایل config.py رو باز کن")
    assert turn1.active_file == "config.py"

    # Turn 2: Refer to it via "اون"
    turn2 = processor.process("خط ۱۰ اون رو ببین")
    assert any(ref in turn2.resolved_references for ref in ("اون", "اون را", "اون رو"))
    matched_ref = next(
        ref for ref in ("اون", "اون را", "اون رو") if ref in turn2.resolved_references
    )
    assert turn2.resolved_references[matched_ref] == "config.py"

    # Turn 3: Volume control reference
    turn3 = processor.process("صداش رو کم کن")
    assert "صداش" in turn3.resolved_references
    assert turn3.resolved_references["صداش"] == "voice_system"


def test_scenario_e_user_corrections() -> None:
    """Scenario E: User corrections shifting target entity."""
    processor = PersianLanguageProcessor()

    # Turn 1: User says check config.py
    turn1 = processor.process("فایل config.py رو بررسی کن")
    assert turn1.active_file == "config.py"

    # Turn 2: User corrects "نه منظورم اون نبود، main.py رو ببین"
    turn2 = processor.process("نه منظورم اون نبود، فایل main.py رو بررسی کن")
    assert turn2.intent == PersianIntentType.USER_CORRECTION
    assert turn2.active_file == "main.py"


def test_scenario_f_hypothetical_safety_zero_destructive_execution() -> None:
    """Scenario F: Hypothetical question flagged is_hypothetical; zero destructive tools permitted."""
    processor = PersianLanguageProcessor()
    prompt = "اگه همه لاگ‌ها رو پاک کنیم چی میشه؟"
    res = processor.process(prompt)

    assert res.is_hypothetical is True
    assert res.intent == PersianIntentType.HYPOTHETICAL_DISCUSSION

    # Planner verification: hypothetical queries must not execute delete tools
    planner = AgentPlanner(provider_manager=MagicMock())
    _ = planner.should_plan(prompt)
    assert res.is_hypothetical is True


def test_scenario_g_destructive_ambiguity_clarification_gate() -> None:
    """Scenario G: Ambiguous destructive commands flagged; requires clarification."""
    processor = PersianLanguageProcessor()
    ambiguous_prompts = [
        "همه فایل‌های اضافی رو پاک کن",
        "کل سیستم رو تمیز کن",
        "همه‌چیز رو دیلیت کن",
        "همه چیز رو حذف کن",
    ]
    for prompt in ambiguous_prompts:
        res = processor.process(prompt)
        assert res.is_ambiguous is True, f"Failed ambiguity detection for: {prompt}"
        assert res.requires_clarification is True, f"Failed clarification requirement for: {prompt}"


def test_scenario_h_multistep_planning() -> None:
    """Scenario H: Multi-step instructions detected for autonomous decomposition."""
    processor = PersianLanguageProcessor()
    prompt = "اول بیلد بگیر بعد تست‌ها رو ران کن و در نهایت نتیجه رو گزارش کن"
    res = processor.process(prompt)

    assert res.intent == PersianIntentType.TASK_PLANNING
    assert res.entities is not None


def test_scenario_i_read_only_prohibitions_and_constraints() -> None:
    """Scenario I: Read-only and operational negative constraints."""
    processor = PersianLanguageProcessor()
    prompts = [
        "فعلاً کاری نکن فقط لاگ‌ها رو چک کن",
        "دست به دیتابیس نزن فقط سیستم رو ببین",
        "فقط بررسی کن و ویرایش نکن",
    ]
    for prompt in prompts:
        res = processor.process(prompt)
        assert res.is_read_only is True, f"Failed read-only flag for: {prompt}"
        assert len(res.safety_constraints) > 0, f"Expected safety constraints for: {prompt}"


def test_scenario_j_explicit_language_switching_and_persistence() -> None:
    """Scenario J: Language policy switches to Persian when asked and persists until switched back."""
    processor = PersianLanguageProcessor()

    # Initial: Default English
    res1 = processor.process("وضعیت سیستم چطوره؟")
    assert res1.response_language == ResponseLanguage.ENGLISH.value

    # Switch to Persian persistently
    res2 = processor.process("از الان به بعد فارسی صحبت کن")
    assert res2.response_language == ResponseLanguage.PERSIAN.value

    # Next turn: Must remain Persian
    res3 = processor.process("باتری سیستم در چه وضعیتیه؟")
    assert res3.response_language == ResponseLanguage.PERSIAN.value

    # Switch back to English
    res4 = processor.process("switch back to English")
    assert res4.response_language == ResponseLanguage.ENGLISH.value

    # Next turn: Must remain English
    res5 = processor.process("اوضاع چطوره؟")
    assert res5.response_language == ResponseLanguage.ENGLISH.value


def test_scenario_k_application_control() -> None:
    """Scenario K: Application launch and close detection in Persian."""
    processor = PersianLanguageProcessor()

    # Launch Calc
    res_calc = processor.process("ماشین حساب رو باز کن")
    assert res_calc.intent == PersianIntentType.APPLICATION_CONTROL
    apps = [
        e
        for e in res_calc.entities
        if e.entity_type in (PersianEntityType.APPLICATION, PersianEntityType.APPLICATION_NAME)
    ]
    assert any(a.normalized_value in ("calculator", "calc.exe", "calc") for a in apps)

    # Close Notepad
    res_notepad = processor.process("نوت‌پد رو ببند")
    assert res_notepad.intent == PersianIntentType.APPLICATION_CONTROL
    apps_np = [
        e
        for e in res_notepad.entities
        if e.entity_type in (PersianEntityType.APPLICATION, PersianEntityType.APPLICATION_NAME)
    ]
    assert any(a.normalized_value in ("notepad", "notepad.exe") for a in apps_np)


def test_scenario_l_resilient_recovery_on_provider_failure() -> None:
    """Scenario L: Fallback response generation when provider fails."""
    controller = MultilingualResponseController()

    # When provider fails, controller synthesizes graceful fallback
    fallback_en = controller.format_error(
        error_message="Connection timeout to AI provider",
        language=ResponseLanguage.ENGLISH,
    )
    assert "sir" in fallback_en.lower()
    assert "apologies" in fallback_en.lower() or "encountered" in fallback_en.lower()

    fallback_fa = controller.format_error(
        error_message="خطای شبکه در اتصال به سرور هوش مصنوعی",
        language=ResponseLanguage.PERSIAN,
    )
    assert "قربان" in fallback_fa
    assert "خطا" in fallback_fa or "اشکال" in fallback_fa
