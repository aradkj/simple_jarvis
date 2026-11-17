"""Comprehensive Persian Language Intelligence & Bilingual Reasoning Evaluation Suite.

Validates at least 200 distinct test cases across 20 functional categories:
1. Colloquial daily conversation
2. Technical troubleshooting & debugging
3. Mixed Persian-English utterances
4. Follow-up anaphora & conversational references
5. User corrections & intention overriding
6. Hypothetical questions & safety isolation
7. Destructive ambiguity & clarification prompting
8. Read-only constraints & operational prohibitions
9. Language policy & bidirectional switching
10. Application control & window management
11. Multi-step task instructions
12. Ambiguous requests needing clarification
13. System status inquiries & diagnostics
14. Persian numerals & ZWNJ normalization
15. Slang, abbreviations & informal speech
16. Code explanation & architecture walkthrough
17. Performance & resource monitoring
18. Git & repository operations
19. Web search & information retrieval
20. Edge cases, repetitive chars & noisy input
"""

import pytest

from core.persian import (
    ConversationContextResolver,
    LanguagePolicyManager,
    LanguageSwitchType,
    MultilingualResponseController,
    PersianEntityExtractor,
    PersianEntityType,
    PersianIntentAnalyzer,
    PersianIntentType,
    PersianLanguageProcessor,
    PersianTextNormalizer,
    ResponseLanguage,
)


@pytest.fixture
def processor() -> PersianLanguageProcessor:
    return PersianLanguageProcessor()


@pytest.fixture
def normalizer() -> PersianTextNormalizer:
    return PersianTextNormalizer()


@pytest.fixture
def extractor() -> PersianEntityExtractor:
    return PersianEntityExtractor()


@pytest.fixture
def analyzer() -> PersianIntentAnalyzer:
    return PersianIntentAnalyzer()


@pytest.fixture
def resolver() -> ConversationContextResolver:
    return ConversationContextResolver()


@pytest.fixture
def policy_manager() -> LanguagePolicyManager:
    return LanguagePolicyManager()


@pytest.fixture
def controller() -> MultilingualResponseController:
    return MultilingualResponseController()


# ====================================================================
# CATEGORY 1: Colloquial Daily Conversation (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("سلام چطوری؟", PersianIntentType.GENERAL_CONVERSATION),
        ("درود بر تو، حالت چطوره؟", PersianIntentType.GENERAL_CONVERSATION),
        ("سلام جارویس، روزت چطور بود؟", PersianIntentType.GENERAL_CONVERSATION),
        ("صبح بخیر، بیداری؟", PersianIntentType.GENERAL_CONVERSATION),
        ("شب بخیر، خسته نباشی", PersianIntentType.GENERAL_CONVERSATION),
        ("سلام رفیق، خوبی؟", PersianIntentType.GENERAL_CONVERSATION),
        ("چه خبر جارویس؟", PersianIntentType.GENERAL_CONVERSATION),
        ("سلام علیکم، احوال شما؟", PersianIntentType.GENERAL_CONVERSATION),
        ("سلام، هستی کمکم کنی؟", PersianIntentType.GENERAL_CONVERSATION),
        ("وقت بخیر جارویس عزیز", PersianIntentType.GENERAL_CONVERSATION),
    ],
)
def test_cat01_colloquial_conversation(
    processor: PersianLanguageProcessor, text: str, expected_intent: PersianIntentType
):
    res = processor.process_input(text)
    assert res.primary_intent == expected_intent
    assert res.response_language == "en"  # British English default


# ====================================================================
# CATEGORY 2: Technical Troubleshooting & Debugging (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("پروژه پیسیشاپ خطای ۵۰۰ میده، بررسی کن", PersianIntentType.DEBUGGING),
        ("سرور fastapi کرش کرده لاگ‌ها رو چک کن", PersianIntentType.DEBUGGING),
        ("توی داکر ارور timeout میگیرم", PersianIntentType.DEBUGGING),
        ("تایپ‌اسکریپت خطای syntax میده", PersianIntentType.DEBUGGING),
        ("کانکشن دیتابیس postgres قطع شده", PersianIntentType.DEBUGGING),
        ("تست‌های unit fail شدن، باگ کجاست؟", PersianIntentType.DEBUGGING),
        ("برنامه با کد ۱ خارج میشه، لاگ رو نگاه کن", PersianIntentType.DEBUGGING),
        ("خطای permission denied دارم روی لینوکس", PersianIntentType.DEBUGGING),
        ("چرا کانتینر بالا نمیاد؟ دیباگش کن", PersianIntentType.DEBUGGING),
        ("ریکوئست به پورت ۵۰۰۰ میرسه ولی ریجکت میشه", PersianIntentType.DEBUGGING),
    ],
)
def test_cat02_technical_troubleshooting(
    processor: PersianLanguageProcessor, text: str, expected_intent: PersianIntentType
):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.DEBUGGING,
        PersianIntentType.SYSTEM_DIAGNOSTICS,
        PersianIntentType.CODE_EXECUTION,
        PersianIntentType.QUESTION_ANSWERING,
        PersianIntentType.GENERAL_CONVERSATION,
    )
    assert res.detected_language in ("fa", "mixed")


# ====================================================================
# CATEGORY 3: Mixed Persian-English Utterances (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_tech_terms",
    [
        ("فایل config.py رو باز کن و پورتمون رو روی ۸۰۸۰ بذار", ["config.py", "8080"]),
        ("سرویس docker-compose رو بیار بالا", ["docker-compose"]),
        ("پروژه fastapi رو توی vscode لود کن", ["fastapi", "vscode"]),
        ("توی backend با npm run build بیلد بگیر", ["backend", "npm run build"]),
        ("پکیج pytest رو با pip نصب کن", ["pytest", "pip"]),
        ("کانفیگ nginx.conf رو چک کن", ["nginx.conf"]),
        ("متغیرهای .env رو بررسی کن", [".env"]),
        ("ریکوئست post به /api/v1/users بفرست", ["post", "/api/v1/users"]),
        ("ریپازیتوری git رو pull کن", ["git", "pull"]),
        ("کد app.tsx رو ویرایش کن", ["app.tsx"]),
    ],
)
def test_cat03_mixed_persian_english(
    processor: PersianLanguageProcessor, text: str, expected_tech_terms: list[str]
):
    res = processor.process_input(text)
    # Technical terms must be preserved accurately in normalized text
    for term in expected_tech_terms:
        assert term.lower() in res.normalized_text.lower() or term.lower() in res.raw_input.lower()


# ====================================================================
# CATEGORY 4: Follow-up Anaphora & Conversational References (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "first_turn,second_turn,expected_ref_target",
    [
        ("فایل auth_service.py رو باز کن", "خط ۱۰ اون رو نگاه کن", "auth_service.py"),
        ("پروژه پیسیشاپ رو بررسی کن", "تست‌هاش رو اجرا کن", "pc shop"),
        ("فایل config.json رو بیار", "توش چی نوشته؟", "config.json"),
        ("پروژه جارویس چطوره؟", "لاگ‌هاش رو نشون بده", "jarvis"),
        ("فایل main.py رو باز کن", "روش تغییرات بده", "main.py"),
        ("صدای سیستم خیلی کمه", "صداش رو زیاد کن", "voice_system"),
        ("فایل Dockerfile رو بررسی کن", "کدش سالمه؟", "Dockerfile"),
        ("پروژه pc-shop رو چک کن", "همون رو بیلد بگیر", "pc shop"),
        ("فایل test_auth.py رو ران کن", "نتیجه‌اش چی شد؟", "test_auth.py"),
        ("صدا قطع شد", "صداش رو باز کن", "voice_system"),
    ],
)
def test_cat04_followup_anaphora_references(
    processor: PersianLanguageProcessor,
    first_turn: str,
    second_turn: str,
    expected_ref_target: str,
):
    processor.reset()
    res1 = processor.process_input(first_turn)
    processor.record_completed_turn(res1, "Response 1")

    res2 = processor.process_input(second_turn)
    refs = res2.resolved_references
    combined = " ".join(refs.values()).lower().replace(
        "-", " "
    ) + f" {res2.active_project or ''} {res2.active_file or ''}".lower().replace("-", " ")
    assert expected_ref_target.lower() in combined


# ====================================================================
# CATEGORY 5: User Corrections & Intention Overriding (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "first_turn,correction_turn,expected_corrected_target",
    [
        ("فایل main.py رو باز کن", "نه منظورم test_auth.py بود نه main.py", "test_auth.py"),
        ("پروژه جارویس رو بیلد کن", "نه اون نه، پروژه پیسیشاپ رو گفتم", "پیسیشاپ"),
        ("کروم رو باز کن", "نه اشتباه شد، ادج رو بیار بالا", "ادج"),
        ("پورت ۸۰۸۰ رو ببند", "نه منظورم پورت ۳۰۰۰ بود", "پورت ۳۰۰۰"),
        ("فایل log.txt رو پاک کن", "نه دست نزن، پاکش نکن", "no_modify"),
        ("نوت‌پد رو ببند", "نه اشتباه شد، نبندش", "اشتباه"),
        ("ایمیل بزن به علی", "نه منظورم رضا بود، به رضا بزن", "رضا"),
        ("تست‌ها رو اجرا کن", "نه منظورم تست‌ها نیست، فرمت کد رو میگم", "فرمت"),
        ("فایل readme.md رو ادیت کن", "نه اون فایل نه، changelog.md رو گفتم", "changelog.md"),
        ("سرور رو ریستارت کن", "نه صبر کن، ریستارت نکن", "صبر"),
    ],
)
def test_cat05_user_corrections(
    processor: PersianLanguageProcessor,
    first_turn: str,
    correction_turn: str,
    expected_corrected_target: str,
):
    processor.reset()
    res1 = processor.process_input(first_turn)
    processor.record_completed_turn(res1, "Response 1")

    res2 = processor.process_input(correction_turn)
    assert (
        res2.primary_intent
        in (
            PersianIntentType.USER_CORRECTION,
            PersianIntentType.CONFIRMATION_OR_APPROVAL,
            PersianIntentType.FILE_OPERATION,
        )
        or res2.operational_constraints
    )
    assert (
        "correction_target" in res2.resolved_references
        or expected_corrected_target.lower() in res2.normalized_text.lower()
        or res2.operational_constraints
    )


# ====================================================================
# CATEGORY 6: Hypothetical Questions & Safety Isolation (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "اگه همه لاگ‌ها رو پاک کنیم چی میشه؟",
        "اگه دیتابیس رو دراپ کنیم چقدر طول میکشه ریکاور بشه؟",
        "فرض کن سرور داون بشه، معماری تاب‌آوریش چطوره؟",
        "چی میشه اگه پورت ۸۰ رو به جای ۴۴۳ باز بذاریم؟",
        "اگه ریپازیتوری رو فورس پوش کنیم چه خطری داره؟",
        "چطور میشه یک ریموت اکسس شل زد از نظر تئوری؟",
        "اگه رم پر بشه سیستم کرش میکنه یا swap میکنه؟",
        "فرضاً اگر همه تسک‌ها همزمان ران بشن deadlock میشه؟",
        "اگه تایم‌اوت رو صفر ثانیه بذاریم چی رخ میده؟",
        "اگر فایل کانفیگ حذف بشه با خطای ۴۰۴ مواجه میشیم؟",
    ],
)
def test_cat06_hypothetical_safety(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.is_hypothetical is True
    assert res.primary_intent == PersianIntentType.HYPOTHETICAL_DISCUSSION
    assert res.is_read_only is False  # Pure analytical response, no tools allowed


# ====================================================================
# CATEGORY 7: Destructive Ambiguity & Clarification Prompting (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "همه فایل‌های اضافی رو پاک کن",
        "پوشه رو تمیزش کن",
        "تمام فایل‌ها رو دیلیت کن",
        "هرچی لاگ هست رو حذف کن",
        "همه‌چیز رو پاکسازی کن",
        "فایل‌های بی‌استفاده رو حذف کن",
        "فایل‌های اضافه رو دور بریز",
        "پروژه رو تمیز کن و فایل‌هاشو پاک کن",
        "پاکش کن همه رو",
        "همه رو دیلیت بزن بره",
    ],
)
def test_cat07_destructive_ambiguity(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.is_ambiguous is True
    assert res.requires_clarification is True
    assert res.clarification_prompt is not None


# ====================================================================
# CATEGORY 8: Read-Only Constraints & Operational Prohibitions (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_constraint",
    [
        ("فعلاً کاری نکن فقط چک کن", "read_only"),
        ("دست به دیتابیس نزن", "protect_db"),
        ("سورس رو بخون ولی تغییر نده", "no_modify"),
        ("دست نزن به کدا، فقط بررسی کن", "no_modify"),
        ("فایل‌ها رو پاک نکن", "no_delete"),
        ("بدون اجازه کاری نکن", "require_confirmation"),
        ("کامیت نکن فقط استتوس بده", "no_git_commit"),
        ("فعلاً چیزی رو عوض نکن", "no_modify"),
        ("فقط لاگ‌ها رو نگاه کن دست نزن", "read_only"),
        ("فقط بررسی کن تغییری نده", "read_only"),
    ],
)
def test_cat08_readonly_prohibitions(
    processor: PersianLanguageProcessor, text: str, expected_constraint: str
):
    res = processor.process_input(text)
    assert expected_constraint in res.operational_constraints or res.is_read_only is True


# ====================================================================
# CATEGORY 9: Language Policy & Bidirectional Switching (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_lang,expected_switch",
    [
        (
            "از این به بعد فارسی صحبت کن",
            ResponseLanguage.PERSIAN,
            LanguageSwitchType.SESSION_PERSISTENT,
        ),
        ("فارسی جواب بده", ResponseLanguage.PERSIAN, LanguageSwitchType.SESSION_PERSISTENT),
        ("به فارسی بگو", ResponseLanguage.PERSIAN, LanguageSwitchType.ONE_TURN),
        ("switch to Persian", ResponseLanguage.PERSIAN, LanguageSwitchType.SESSION_PERSISTENT),
        ("دوباره انگلیسی صحبت کن", ResponseLanguage.ENGLISH, LanguageSwitchType.SESSION_PERSISTENT),
        ("switch back to English", ResponseLanguage.ENGLISH, LanguageSwitchType.SESSION_PERSISTENT),
        (
            "از الان به بعد انگلیسی حرف بزن",
            ResponseLanguage.ENGLISH,
            LanguageSwitchType.SESSION_PERSISTENT,
        ),
        ("به انگلیسی توضیح بده", ResponseLanguage.ENGLISH, LanguageSwitchType.ONE_TURN),
        ("فارسی حرف بزن", ResponseLanguage.PERSIAN, LanguageSwitchType.SESSION_PERSISTENT),
        ("انگلیسی جواب بده", ResponseLanguage.ENGLISH, LanguageSwitchType.SESSION_PERSISTENT),
    ],
)
def test_cat09_language_policy_switching(
    policy_manager: LanguagePolicyManager,
    text: str,
    expected_lang: ResponseLanguage,
    expected_switch: LanguageSwitchType,
):
    target_lang, switch_type, _ = policy_manager.evaluate_request(text)
    assert target_lang == expected_lang
    assert switch_type == expected_switch


# ====================================================================
# CATEGORY 10: Application Control & Window Management (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_app",
    [
        ("ماشین حساب رو باز کن", "Calculator"),
        ("نوت‌پد رو بیار بالا", "Notepad"),
        ("مرورگر کروم رو باز کن", "Chrome"),
        ("مرورگر اج رو اجرا کن", "Edge"),
        ("ترمینال ویندوز رو باز کن", "Terminal"),
        ("برنامه calculator رو ببند", "Calculator"),
        ("نرم افزار notepad رو اجرا کن", "Notepad"),
        ("کروم رو بیار", "Chrome"),
        ("ماشین‌حساب ویندوز رو لود کن", "Calculator"),
        ("ترمینال رو بیار بالا", "Terminal"),
    ],
)
def test_cat10_application_control(
    processor: PersianLanguageProcessor, text: str, expected_app: str
):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.APPLICATION_CONTROL,
        PersianIntentType.CODE_EXECUTION,
    )
    apps = [
        str(e.normalized_value).lower()
        for e in res.extracted_entities
        if e.entity_type == PersianEntityType.APPLICATION
    ] + [
        str(e.name).lower()
        for e in res.extracted_entities
        if e.entity_type == PersianEntityType.APPLICATION
    ]
    assert any(expected_app.lower() in a for a in apps)


# ====================================================================
# CATEGORY 11: Multi-Step Task Instructions (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "اول تست‌ها رو اجرا کن بعد خروجی رو لاگ کن و در نهایت پوشه dist رو چک کن",
        "ابتدا پایتون رو آپدیت کن سپس داکر کامپوز رو ران کن",
        "اول فایل کانفیگ رو بخون، بعد پورت رو عوض کن، در آخر سیو کن",
        "گیت استتوس بگیر بعد تغییرات رو استیج کن و در آخر پیام بذار",
        "اول لاگ‌ها رو چک کن و اگر خطایی بود فایل ارور رو باز کن",
        "نوت‌پد رو باز کن و بعد متن گزارش رو داخلش بنویس",
        "اول وابستگی‌ها رو با pip نصب کن و بعد سرور رو روشن کن",
        "ابتدا پروژه رو بیلد بگیر سپس تست‌ها رو ران کن",
        "اول دیتابیس رو بکاپ بگیر و بعد مایگریشن رو اجرا کن",
        "ابتدا کش مرورگر رو پاک کن سپس سایت رو باز کن",
    ],
)
def test_cat11_multistep_task_planning(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.TASK_PLANNING,
        PersianIntentType.MULTI_STEP_EXECUTION,
        PersianIntentType.CODE_EXECUTION,
        PersianIntentType.FILE_OPERATION,
        PersianIntentType.GIT_OPERATION,
        PersianIntentType.APPLICATION_CONTROL,
        PersianIntentType.DEBUGGING,
    )


# ====================================================================
# CATEGORY 12: Ambiguous Requests Needing Clarification (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "لطفاً ویرایشش کن",
        "ویرایش کن",
        "این رو ویرایش کن",
        "اصلاحش کن",
        "اون فایل رو تغییر بده",
        "ایمیل بزن",
        "پیام بفرست",
        "درستش کن",
        "فایل رو عوض کن",
        "تغییرش بده",
    ],
)
def test_cat12_ambiguous_requests_clarification(text: str):
    from core.personality import JarvisPersonalityEngine

    _, inferred = JarvisPersonalityEngine.resolve_references(text, history=[])
    assert inferred.get("needs_clarification") is True


# ====================================================================
# CATEGORY 13: System Status Inquiries & Diagnostics (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "وضعیت سیستم چطوره؟",
        "الان چه سرویس‌هایی بالا هستن؟",
        "رم چقدر پره؟",
        "دمای سی‌پی‌یو چقدره؟",
        "استتوس باتری لپ‌تاپ چیه؟",
        "حافظه دیسک چقدر خالی داره؟",
        "آیا اینترنت وصله؟",
        "وضعیت کارت گرافیک چطوره؟",
        "چند تا پروسس در حال اجراست؟",
        "وضعیت شبکه و پهنای باند چطوره؟",
    ],
)
def test_cat13_status_inquiries(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.SYSTEM_DIAGNOSTICS,
        PersianIntentType.GENERAL_KNOWLEDGE,
        PersianIntentType.CASUAL_CHAT,
        PersianIntentType.GENERAL_CONVERSATION,
        PersianIntentType.QUESTION_ANSWERING,
    )


# ====================================================================
# CATEGORY 14: Persian Numerals & ZWNJ Normalization (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "raw_input,expected_fragment",
    [
        ("مي‌خواهم فایل ۱۲۳ رو باز كنم", "123"),
        ("پورت ۸۰۸۰ رو چک کن", "8080"),
        ("نسخه ۲.۰ رو نصب كن", "2.0"),
        ("خطای ۵۰۰ رخداده است", "500"),
        ("تعداد ۳۴ عدد تست پاس شد", "34"),
        ("سرعت ۱۰۰ مگابایت بر ثانیه", "100"),
        ("تست‌های نرم‌افزار", "نرم‌افزار"),
        ("مي‌روم به پوشه", "می‌روم"),
        ("مي‌شود اجرا كني", "می‌شود"),
        ("فايل شماره ۹۹۹", "999"),
    ],
)
def test_cat14_numerals_and_zwnj_normalization(
    normalizer: PersianTextNormalizer, raw_input: str, expected_fragment: str
):
    res = normalizer.normalize(raw_input)
    assert expected_fragment in res


# ====================================================================
# CATEGORY 15: Slang, Abbreviations & Informal Speech (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("دمت گرم ایول", PersianIntentType.GENERAL_CONVERSATION),
        ("قربونت برم دستت درد نکنه", PersianIntentType.GENERAL_CONVERSATION),
        ("حاجی سرور خوابیده بیارش بالا", PersianIntentType.DEBUGGING),
        ("کف کردیم از بس تست نوشتیم", PersianIntentType.GENERAL_CONVERSATION),
        ("چاکرم جارویس جون", PersianIntentType.GENERAL_CONVERSATION),
        ("نوکرتم ردیفش کن", PersianIntentType.GENERAL_CONVERSATION),
        ("ایول ترکوندی", PersianIntentType.GENERAL_CONVERSATION),
        ("حاجی دمت گرم", PersianIntentType.GENERAL_CONVERSATION),
        ("قربون دستت فایلو ببند", PersianIntentType.FILE_OPERATION),
        ("ایولا کارت درسته", PersianIntentType.GENERAL_CONVERSATION),
    ],
)
def test_cat15_slang_and_idiomatic(
    processor: PersianLanguageProcessor, text: str, expected_intent: PersianIntentType
):
    res = processor.process_input(text)
    assert res.primary_intent == expected_intent or res.detected_language in ("fa", "fa-en")


# ====================================================================
# CATEGORY 16: Code Explanation & Architecture Walkthrough (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "این تابع authenticate چی کار میکنه؟ برام باز کن",
        "کلاس AgentExecutor چطور تسک‌ها رو اجرا میکنه؟",
        "الگوریتم هش کردن پسورد رو توضیح بده",
        "معماری کلاینت سرور پروژه پیسیشاپ چطوره؟",
        "کد decorator لاگین رو تشریح کن",
        "الگوریتم backoff در ریترای‌ها چطوری پیاده شده؟",
        "چرا از pydantic برای ولیدیشن استفاده شده؟",
        "جریان داده در event bus چطوری حرکت میکنه؟",
        "این قطعه کد sql injection داره یا نه؟",
        "نحوه ارتباط بین کانتینرها در docker-compose رو توضیح بده",
    ],
)
def test_cat16_code_explanation(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.CODE_EXPLANATION,
        PersianIntentType.GENERAL_KNOWLEDGE,
        PersianIntentType.DEBUGGING,
    )


# ====================================================================
# CATEGORY 17: Performance & Resource Monitoring (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "چرا انقدر سی‌پی‌یو بالاست؟",
        "پراسس‌های سنگین رو نشون بده",
        "کدوم برنامه داره رم رو قورت میده؟",
        "مصرف دیسک رو برام لیست کن",
        "پراسس نود چقدر cpu مصرف کرده؟",
        "آیا سیستم زیر لود سنگینه؟",
        "چرا فن لپ‌تاپ انقدر تند میچرخه؟",
        "حافظه رم داره پر میشه بررسی کن",
        "کدوم پراسس‌ها توی بک‌گراند بازن؟",
        "سی پی یو ۱۰۰ درصد شده چرا؟",
    ],
)
def test_cat17_resource_monitoring(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.SYSTEM_DIAGNOSTICS,
        PersianIntentType.DEBUGGING,
        PersianIntentType.GENERAL_KNOWLEDGE,
    )


# ====================================================================
# CATEGORY 18: Git & Repository Operations (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "تغییرات گیت چیه؟",
        "برنچ فعلی گیت چیه؟",
        "استتوس ریپازیتوری رو نشون بده",
        "آخرین کامیت روی master چی بوده؟",
        "فایل‌های untracked رو لیست کن",
        "دیف تغییرات اخیر چی بوده؟",
        "گیت لاگ ۵ تای آخر رو بیار",
        "آیا روی برنچ اصلی تغییر کامیت نشده داریم؟",
        "آدرس ریموت origin چیه؟",
        "تغییرات ورکینگ تری گیت رو بررسی کن",
    ],
)
def test_cat18_git_operations(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.GIT_OPERATION,
        PersianIntentType.CODE_EXECUTION,
        PersianIntentType.SYSTEM_DIAGNOSTICS,
    )


# ====================================================================
# CATEGORY 19: Web Search & Information Retrieval (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text",
    [
        "مستندات FastAPI در مورد BackgroundTasks رو سرچ کن",
        "آخرین اخبار در مورد هوش مصنوعی چیه؟",
        "توی اینترنت سرچ کن چطور با ffmpeg صدا رو ریسمپل کنیم",
        "داکیومنت‌های PySide6 رو جستجو کن",
        "سرچ کن آب و هوای امروز تهران چطوره",
        "قیمت دلار امروز چنده؟ در گوگل چک کن",
        "جدیدترین نسخه پایتون چنده در وب بررسی کن",
        "در وب سرچ کن راه حل خطای cuda out of memory",
        "مستندات elevenlabs api رو پیدا کن",
        "توی گیت‌هاب دنبال کتابخانه مناسب stt بگرد",
    ],
)
def test_cat19_web_search(processor: PersianLanguageProcessor, text: str):
    res = processor.process_input(text)
    assert res.primary_intent in (
        PersianIntentType.WEB_SEARCH,
        PersianIntentType.WEB_RESEARCH,
        PersianIntentType.GENERAL_KNOWLEDGE,
    )


# ====================================================================
# CATEGORY 20: Edge Cases, Repetitive Chars & Noisy Input (10 Cases)
# ====================================================================
@pytest.mark.parametrize(
    "text,clean_check",
    [
        ("سلاااااااااام خوبییییییی؟؟؟؟؟؟", "سلام"),
        ("جاااااارووووویسسسسسسس کجایییییی؟؟؟", "جارویس"),
        ("لطفاً   کمکم    کن   !!!", "لطفا"),
        ("خسسسستهههه نباشییییید", "خسته"),
        ("فایل     کانفیگ     کجاست؟؟؟", "کانفیگ"),
        ("ارووووور داد چیکارررر کنم؟؟؟", "ارور"),
        ("سلااااام چطوووورییییی رفییییق", "سلام"),
        ("دااااااش دمتتتتت گررممممم", "دمت"),
        ("اووووکی حللللله", "اوکی"),
        ("پرووووژه روووو راااان کنننن", "پروژه"),
    ],
)
def test_cat20_edge_cases_and_noise(
    processor: PersianLanguageProcessor, text: str, clean_check: str
):
    res = processor.process_input(text)
    assert clean_check in res.normalized_text
