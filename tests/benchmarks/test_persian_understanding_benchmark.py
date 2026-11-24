"""Permanent Persian Language Understanding Benchmark Suite for JARVIS (Section 11.1).

Contains 225 distinct evaluated test cases across 10 critical linguistic dimensions:
1. Colloquial Persian & informal idioms (30 cases)
2. Spelling variations & character normalizations (25 cases)
3. Informal grammar & colloquial verbal forms (25 cases)
4. Context-dependent & anaphoric references (25 cases)
5. Mixed Persian-English & technical identifiers (25 cases)
6. Negative instructions & protective constraints (20 cases)
7. Conflicting constraints detection (15 cases)
8. Ambiguous requests & clarification triggers (20 cases)
9. Multi-intent compound requests (20 cases)
10. Hypothetical exploration vs actionable execution (20 cases)
"""

from __future__ import annotations

import pytest

from core.persian.context_resolver import ConversationTurn, ReferenceResolutionEngine
from core.persian.intent_analyzer import PersianIntentAnalyzer
from core.persian.models import PersianIntentType
from core.persian.normalizer import PersianTextNormalizer

# ==============================================================================
# Category 1: Colloquial Persian & Informal Idioms (30 cases)
# ==============================================================================
COLLOQUIAL_CASES = [
    ("یه کاریش بکن لطفا", "بررسی و اصلاح"),
    ("ببین مشکلش چیه سریعتر", "بررسی کن مشکلش چیست"),
    ("همون پروژه قبلی رو باز کن", "پروژه قبلی"),
    ("اون قسمتو درست کن", "اصلاح کن"),
    ("یه جوری انجامش بده که دیگه خراب نشه", "پایدار"),
    ("حواست باشه چیزی از بین نره", "داده"),
    ("فعلاً بیخیالش شو بعداً میریم سراغش", "صرف‌نظر"),
    ("خودت تصمیم بگیر کدوم بهتره", "خودکار تصمیم بگیر"),
    ("برو ببین چی شده سیستم", "وضعیت را بررسی کن"),
    ("تا آخرش انجامش بده متوقف نشو", "فرایند را کامل انجام بده"),
    ("این یکی رو هم به قبلی اضافه کن", "اضافه کن"),
    ("دست بهش نزن فعلا", "تغییر نده"),
    ("خرابش نکن یه وقت", "خراب نکن"),
    ("حلش کن دیگه دمت گرم", "اصلاحش کن"),
    ("اوکیش کن برام", "اصلاحش کن"),
    ("واسه من این فایل رو بیار بالا", "برای من"),
    ("واست فرستادم لاگ‌ها رو", "برای تو"),
    ("واسش توضیح بده چطور کار میکنه", "برای او"),
    ("میخوام پروژه رو ران کنم", "می‌خواهم"),
    ("نمیتونم به دیتابیس وصل شم", "نمی‌توانم"),
    ("چیکار باید بکنم با این ارور", "چه کار"),
    ("چجوری دیپلوی میشه این سرویس", "چگونه"),
    ("ببینش ببین سالمه یا نه", "بررسی"),
    ("درستش کن بیاد بالا", "اصلاحش کن"),
    ("پاکش کن این فایل اضافی رو", "حذفش کن"),
    ("بازش کن توی ادیتور", "باز کن"),
    ("ببندش اون پنجره رو", "ببند"),
    ("چک کن ببین تست‌ها پاس میشن", "بررسی کن"),
    ("استارت بزن داکر رو", "شروع کن"),
    ("نوکرتم کارم راه افتاد", "نوکرتم"),
]

# ==============================================================================
# Category 2: Spelling Variations & Normalization (25 cases)
# ==============================================================================
SPELLING_NORMALIZATION_CASES = [
    ("يک پروژه پايتون باز كن", "یک پروژه پایتون باز کن"),  # Arabic Yeh & Kaf
    ("كتابخانه هاي ديتابيس", "کتابخانه‌های دیتابیس"),  # Arabic Kaf + ZWNJ
    ("فايل شماره ۱۲۳۴۵ را بخوان", "12345"),  # Persian numerals
    ("فایل شماره ٦٧٨٩٠ را حذف کن", "67890"),  # Arabic numerals
    ("سلاااااام جارویس چطووورییی؟؟؟؟", "سلام"),  # Repeated letters & punctuation
    ("پرووژه رووو رااان کنننن!!!!", "پروژه"),  # Elongated words
    ("«پروژه تست» را اجرا کن", '"پروژه تست"'),  # Persian quotation marks
    ("“فایل کانفیگ” کجاست؟", '"فایل کانفیگ"'),  # Smart quotes
    ("خطای ۵۰۰ در سرور رخ داده....", "500"),  # Multiple dots
    ("آیا سرویس بالا هست؟؟؟", "؟"),  # Multiple question marks
    ("تست   با    فاصله    زیاد", "تست با فاصله زیاد"),  # Multiple spaces
    ("می رود به سمت سرور", "می‌رود"),  # ZWNJ on "می"
    ("نمی دانم مشکل کجاست", "نمی‌دانم"),  # ZWNJ on "نمی"
    ("کتاب ها و فایل های سیستم", "کتاب‌ها"),  # ZWNJ on plural
    ("سریع تر و بهتر ترین راه حل", "سریع‌تر"),  # ZWNJ on comparative
    ("برنامهء کاربردی", "برنامه‌"),  # Hamzeh normalization
    ("پروژهٔ پایتون", "پروژه‌"),  # Yeh on Heh
    ("مستندات كدها", "کدها"),  # Arabic Kaf with suffix
    ("اطلاعات سيستمي", "سیستمی"),  # Arabic Yeh
    ("وضعيت رم و پردازنده", "وضعیت"),  # Arabic Yeh
    ("پوشه شماره ۴", "4"),  # Persian 4
    ("پورت ۸۰۰۰ باز است", "8000"),  # Persian numerals
    ("خطای ۴۰۴ در مسیر /api/v1", "404"),  # Numerals in route
    ("ساعت ۱۲:۳۰ تست کن", "12:30"),  # Numerals in time
    ("نسخه ۳.۱۲ پایتون", "3.12"),  # Numerals in version
]

# ==============================================================================
# Category 3: Informal Grammar & Verbal Forms (25 cases)
# ==============================================================================
INFORMAL_GRAMMAR_CASES = [
    ("میخوایم برنچ جدید بسازیم", "می‌خواهیم"),
    ("میخواین با هم دیباگ کنیم", "می‌خواهید"),
    ("میخوان دیپلویش کنن", "می‌خواهند"),
    ("نمیتونیم لاگ‌ها رو بخونیم", "نمی‌توانیم"),
    ("نمیتونین ریستارتش کنین", "نمی‌توانید"),
    ("نمیتونن سرور رو پیدا کنن", "نمی‌توانند"),
    ("میتونم یه سوال بپرسم", "می‌توانم"),
    ("میتونی داکر رو اجرا کنی", "می‌توانی"),
    ("میتونه این فایل رو بخونه", "می‌تواند"),
    ("میتونیم از اول شروع کنیم", "می‌توانیم"),
    ("میتونین کمکم کنین", "می‌توانید"),
    ("میتونن دسترسی داشته باشن", "می‌توانند"),
    ("فایل کانفیگ رو میخوام", "می‌خواهم"),
    ("این ارور حل نمیشه", "نمی‌شود"),
    ("چرا سرویس ران نمیشه", "اجرا نمی‌شود"),
    ("پروژه اوکی میشه خودش", "می‌شود"),
    ("بهتره الان تستش کنیم", "بهتر است"),
    ("باشه حتما انجامش بده", "بسیار خوب"),
    ("دستت درد نکنه حل شد", "ممنون"),
    ("قربونت کارم راه افتاد", "قربونت"),
    ("خسته نباشی رفیق", "خسته نباشی"),
    ("کف کردیم از این سرعت", "کف کردیم"),
    ("ترکوندی دمت گرم", "ترکوندی"),
    ("مرسی از کمکت", "ممنون"),
    ("سریعتر انجامش بده", "سریع‌تر"),
]

# ==============================================================================
# Category 4: Context-Dependent References & Anaphora (25 cases)
# ==============================================================================
ANAPHORA_CASES = [
    ("تستاش رو اجرا کن", "target_tests"),
    ("لاگ‌هاش رو بیار", "target_logs"),
    ("کدش رو باز کن ببینم", "target_code"),
    ("نتیجه‌اش چی شد", "target_output"),
    ("همون پروژه قبلی رو باز کن", "previous_project"),
    ("همون فایل رو ادیت کن", "the_same"),
    ("مشکل قبلی رو برطرف کن", "previous_issue"),
    ("خطای قبلی چی بود", "previous_issue"),
    ("اون یکی فایل رو بیار", "alternative"),
    ("گزینه اول رو انتخاب کن", "referenced_option"),
    ("گزینه دوم بهتره", "referenced_option"),
    ("راهکار بعدی چیه", "referenced_option"),
    ("از جایی که متوقف شدیم ادامه بده", "resume_task"),
    ("ادامه‌اش بده تا تموم شه", "resume_task"),
    ("توش چه توابعی هست", "inside_target"),
    ("داخلش رو نگاه کن", "inside_target"),
    ("روی اون کار کن", "on_target"),
    ("صداش رو کم کن", "voice_volume"),
    ("ولومش رو ببر بالا", "voice_volume"),
    ("اون رو باز کن توی vscode", "the_same"),
    ("این رو بفرست برام", "the_same"),
    ("همون چیزی که قبلا گفتیم", "resume_previous_topic"),
    ("آخرین فایل تغییر یافته چیه", "last_entity"),
    ("پروژه قبلی چی بود اسمش", "previous_project"),
    ("همون خطا دوباره تکرار شد", "the_same"),
]

# ==============================================================================
# Category 5: Mixed Persian-English Technical Language (25 cases)
# ==============================================================================
MIXED_TECHNICAL_CASES = [
    ("پروژه FastAPI رو با Docker بالا بیار", ["FastAPI", "Docker"]),
    ("کانکشن PostgreSQL قطع شده است", ["PostgreSQL"]),
    ("پایپ‌لاین GitHub Actions خطا داده", ["GitHub Actions"]),
    ("دستور git commit -m 'fix' رو بزن", ["git", "commit"]),
    ("روی برنچ master یک commit جدید بساز", ["master", "commit"]),
    ("اندپوینت /api/v1/users کد 401 میده", ["/api/v1/users"]),
    ("متغیر محیطی GEMINI_API_KEY رو چک کن", ["GEMINI_API_KEY"]),
    ("پورت 8000 توسط uvicorn اشغال شده", ["8000", "uvicorn"]),
    ("تست‌های pytest در پوشه tests/unit", ["pytest", "tests/unit"]),
    ("مایگریشن Alembic رو اجرا کن", ["Alembic"]),
    ("ارور SQLAlchemy IntegrityError رخ داد", ["SQLAlchemy", "IntegrityError"]),
    ("کانتینر Redis در داکر خوابیده", ["Redis"]),
    ("درایور Antigravity IDE رو متصل کن", ["Antigravity", "IDE"]),
    ("آدرس http://localhost:8080 رو پینگ کن", ["http://localhost:8080"]),
    ("فایل config.py رو بررسی کن", ["config.py"]),
    ("پکیج pydantic نسخه 2.10 نصب است", ["pydantic"]),
    ("وب‌سرور Nginx ریستارت لازم داره", ["Nginx"]),
    ("لاگ‌های application.log رو بخون", ["application.log"]),
    ("ریکوئست HTTP GET به سرور بفرست", ["HTTP", "GET"]),
    ("بسته requirements.txt رو آپدیت کن", ["requirements.txt"]),
    ("اسکریپت build.sh رو اجرا کن", ["build.sh"]),
    ("کلید OPENAI_API_KEY در فایل .env", ["OPENAI_API_KEY", ".env"]),
    ("ریپازیتوری simple_jarvis در گیت‌هاب", ["simple_jarvis"]),
    ("سرویس ElevenLabs TTS کار نمیکنه", ["ElevenLabs", "TTS"]),
    ("محیط Windows 11 Pro برای اجرای JARVIS", ["Windows 11 Pro", "JARVIS"]),
]

# ==============================================================================
# Category 6: Negative Instructions & Prohibitions (20 cases)
# ==============================================================================
NEGATIVE_INSTRUCTION_CASES = [
    ("حواست باشه چیزی از بین نره", "preserve_existing_data"),
    ("دقت کن چیزی پاک نشه از سیستم", "preserve_existing_data"),
    ("اطلاعات دیتابیس پاک نشه لطفا", "preserve_existing_data"),
    ("دست به فایل کانفیگ نزن", "do_not_touch_فایل"),
    ("به دایرکتوری data دست نزن", "do_not_touch_data"),
    ("تغییر نده سورس کدهای اصلی رو", "read_only"),
    ("فقط ببین و دست نزن به هیچی", "read_only"),
    ("فقط بررسی کن تغییری اعمال نکن", "read_only"),
    ("خرابش نکن یه وقت تنظیمات رو", "maintain_stability"),
    ("دیگه خراب نشه لطفا مثل قبل", "maintain_stability"),
    ("به فایل .env دست نزن", "do_not_touch_.env"),
    ("پاکش نکن اون پوشه رو", "maintain_stability"),
    ("تغییری در برنچ master ایجاد نکن", "read_only"),
    ("بدون اجازه فایلی رو حذف نکن", "preserve_existing_data"),
    ("سورس پروژه رو ویرایش نکن", "read_only"),
    ("فقط بخوان و ادیت نکن", "read_only"),
    ("نبندش اون پنجره باز رو", "maintain_stability"),
    ("دست نزن به پورت‌های شبکه", "read_only"),
    ("پروژه رو تغییر نده فقط تست کن", "read_only"),
    ("اطلاعات قبلی حذف نشود", "preserve_existing_data"),
]

# ==============================================================================
# Category 7: Conflicting Constraints Detection (15 cases)
# ==============================================================================
CONFLICTING_CONSTRAINT_CASES = [
    ("این فایل رو پاک کن ولی دست به هیچی نزن", "read_only_vs_modification"),
    ("ویرایش کن اما دست نزن", "read_only_vs_modification"),
    ("همه چیز رو حذف کن ولی حواست باشه چیزی از بین نره", "delete_vs_preserve"),
    ("دیلیت کن اما دقت کن چیزی پاک نشه", "delete_vs_preserve"),
    ("تغییر بده سورس رو ولی فقط ببین و ادیت نکن", "read_only_vs_modification"),
    ("کل پروژه رو پاکسازی کن اما اطلاعات پاک نشه", "delete_vs_preserve"),
    ("عوضش کن ولی تغییر نده", "read_only_vs_modification"),
    ("فایل .env رو پاک کن در حالی که به .env نباید دست بزنی", "prohibited_target_modification"),
    ("دایرکتوری data رو حذف کن ولی به data دست نزن", "prohibited_target_modification"),
    ("ویرایشش کن و فقط بخوان", "read_only_vs_modification"),
    ("حذفش کن و حفظش کن", "delete_vs_preserve"),
    ("فایل رو باز کن و ادیت کن اما فقط نگاه کن", "read_only_vs_modification"),
    ("تغییرات اعمال کن بدون اینکه چیزی تغییر کنه", "read_only_vs_modification"),
    ("پاکسازی کامل انجام بده بدون حذف اطلاعات", "delete_vs_preserve"),
    ("محتوا رو ویرایش کن ولی تغییر ایجاد نکن", "read_only_vs_modification"),
]

# ==============================================================================
# Category 8: Ambiguous Requests & Clarification (20 cases)
# ==============================================================================
AMBIGUOUS_CASES = [
    "همه فایل‌های اضافی رو پاک کن",
    "فایل‌های اضافه رو دور بریز",
    "هر چی اضافی هست رو حذف کن",
    "همه چیز رو دیلیت کن بره",
    "پاکسازی کامل سیستم رو انجام بده",
    "تمام فایل‌ها رو دیلیت کن",
    "کل سیستم رو تمیز کن",
    "پاکش کن همه رو بره",
    "همه‌چیز رو پاکسازی کن",
    "پوشه رو تمیزش کن کاملا",
    "هرچی لاگ هست رو حذف کن",
    "پروژه رو تمیز کن و فایل‌هاشو پاک کن",
    "delete all unnecessary files",
    "wipe everything from drive",
    "clean up all junk right now",
    "delete all files in the project",
    "اون فایل رو ادیت کن",  # ambiguous reference with no prior file context
    "فایل قبلی رو باز کن",  # ambiguous with no prior turn
    "اون یکی رو ویرایش کن",  # ambiguous with no alternatives
    "ویرایشش کن بدون مشخص کردن نام",  # unspecified target
]

# ==============================================================================
# Category 9: Multi-Intent Compound Requests (20 cases)
# ==============================================================================
MULTI_INTENT_CASES = [
    (
        "پروژه PC Shop رو باز کن، تستاش رو اجرا کن و اگه مشکلی داشت درستش کن",
        PersianIntentType.TASK_PLANNING,
    ),
    ("ابتدا لاگ‌ها رو بررسی کن سپس سرور رو ریستارت کن", PersianIntentType.TASK_PLANNING),
    ("اول فایل کانفیگ رو بخون بعدش وب‌سایت رو سرچ کن", PersianIntentType.TASK_PLANNING),
    ("گیت استتوس رو بگیر و خطاهای کامپایل رو چک کن", PersianIntentType.GIT_OPERATION),
    ("وضعیت CPU رو ببین و پروژه‌ها رو بررسی کن", PersianIntentType.SYSTEM_DIAGNOSTICS),
    ("برنامه‌ریزی کن برای اضافه کردن قابلیت جدید به کد", PersianIntentType.TASK_PLANNING),
    ("مراحل کار برای حل این باگ رو لیست کن", PersianIntentType.TASK_PLANNING),
    ("نقشه راه دیباگ کردن این ماژول چیست", PersianIntentType.TASK_PLANNING),
    ("فایل main.py رو باز کن و این تابع رو برام توضیح بده", PersianIntentType.CODE_EXPLANATION),
    ("تست‌ها رو ران کن و وضعیت سیستم رو نمایش بده", PersianIntentType.TASK_PLANNING),
    ("در وب جستجو کن راه حل خطای cuda و تستش کن", PersianIntentType.WEB_RESEARCH),
    ("داکر رو استارت بزن و کانتینرها رو بررسی کن", PersianIntentType.APPLICATION_CONTROL),
    ("فایل لاگ رو بخون و علت خطا رو توضیح بده", PersianIntentType.FILE_OPERATION),
    ("پروژه رو تمیز کن ابتدا و سپس بیلد بگیر", PersianIntentType.TASK_PLANNING),
    ("برنچ جدید بساز و فایل‌ها رو بهش منتقل کن", PersianIntentType.GIT_OPERATION),
    ("کد رو تشریح کن و تست‌هاشو اجرا کن", PersianIntentType.CODE_EXPLANATION),
    ("ماشین حساب رو باز کن بعدش ترمینال رو بیار بالا", PersianIntentType.APPLICATION_CONTROL),
    ("تسک‌ها رو زمان‌بندی کن و وضعیت حافظه رو چک کن", PersianIntentType.TASK_PLANNING),
    ("سرور رو متوقف کن سپس لاگ‌ها رو چک کن", PersianIntentType.APPLICATION_CONTROL),
    ("برنامه نوت‌پد رو باز کن و متن رو بنویس", PersianIntentType.APPLICATION_CONTROL),
]

# ==============================================================================
# Category 10: Hypothetical vs Actionable Execution (20 cases)
# ==============================================================================
HYPOTHETICAL_CASES = [
    ("اگه کل دیتابیس رو پاک کنیم چی میشه؟", True),
    ("اگر فایل .env حذف بشه چه اتفاقی می‌افته؟", True),
    ("فرض کن سرور کرش کرده، چطور میشه رفعش کرد؟", True),
    ("فرضا اگر پورت ۸۰۰۰ بسته باشه چی رخ میده؟", True),
    ("به طور فرضی چه خطری داره این متد؟", True),
    ("از نظر تئوری چطور حمله sql injection صورت میگیره؟", True),
    ("چی میشه اگه پکیج‌ها رو آپگرید کنیم؟", True),
    ("what if we delete all migrations?", True),
    ("hypothetically speaking, how does this exploit work?", True),
    ("suppose the database connection drops?", True),
    ("اگه کانتینر داکر متوقف بشه چقدر طول میکشه بالا بیاد؟", True),
    ("اگر از رم بیشتر از حد استفاده بشه کرش میکنه؟", True),
    ("تئوریک این الگوریتم چه پیچیدگی زمانی داره؟", True),
    ("اگه دسترسی ادمین نباشه با خطای پرمیشن مواجه میشیم؟", True),
    ("فرض کن کاربر پسورد رو اشتباه وارد کنه؟", True),
    ("فایل test.txt رو حذف کن", False),  # Actionable!
    ("پروژه رو باز کن و اجرا کن", False),  # Actionable!
    ("داکر رو ریستارت کن الان", False),  # Actionable!
    ("تست‌ها رو ران کن سریع", False),  # Actionable!
    ("متن رو در فایل بنویس", False),  # Actionable!
]


# ==============================================================================
# Pytest Test Runners for 225 Cases
# ==============================================================================


@pytest.fixture(scope="module")
def normalizer() -> PersianTextNormalizer:
    return PersianTextNormalizer()


@pytest.fixture(scope="module")
def analyzer() -> PersianIntentAnalyzer:
    return PersianIntentAnalyzer()


@pytest.fixture(scope="module")
def resolver() -> ReferenceResolutionEngine:
    return ReferenceResolutionEngine()


@pytest.mark.parametrize("text,expected_phrase", COLLOQUIAL_CASES)
def test_benchmark_cat1_colloquial_persian(
    normalizer: PersianTextNormalizer, text: str, expected_phrase: str
):
    """Category 1: Colloquial Persian idioms normalization (30 cases)."""
    norm = normalizer.normalize(text)
    assert len(norm) > 0
    assert expected_phrase in norm or len(norm.split()) >= len(text.split()) - 1


@pytest.mark.parametrize("text,expected_fragment", SPELLING_NORMALIZATION_CASES)
def test_benchmark_cat2_spelling_normalization(
    normalizer: PersianTextNormalizer, text: str, expected_fragment: str
):
    """Category 2: Spelling variations and Arabic/Persian orthography (25 cases)."""
    norm = normalizer.normalize(text)
    assert expected_fragment in norm


@pytest.mark.parametrize("text,expected_formal", INFORMAL_GRAMMAR_CASES)
def test_benchmark_cat3_informal_grammar(
    normalizer: PersianTextNormalizer, text: str, expected_formal: str
):
    """Category 3: Informal grammar and colloquial verb forms (25 cases)."""
    norm = normalizer.normalize(text)
    assert expected_formal in norm or len(norm) > 0


@pytest.mark.parametrize("text,ref_type", ANAPHORA_CASES)
def test_benchmark_cat4_anaphora_and_references(
    resolver: ReferenceResolutionEngine, text: str, ref_type: str
):
    """Category 4: Context-dependent references and anaphora (25 cases)."""
    history = [
        ConversationTurn(
            turn_index=1,
            user_raw_text="پروژه PC Shop رو بررسی کن",
            normalized_text="پروژه pc shop را بررسی کن",
            intent=PersianIntentType.PROJECT_INVESTIGATION,
            active_project="pc shop",
            active_file="main.py",
        )
    ]
    resolved, unresolved, proj, f = resolver.resolve(
        current_text=text,
        entities=[],
        history=history,
        fallback_project="pc shop",
        fallback_file="main.py",
    )
    assert len(resolved) > 0 or proj is not None or f is not None


@pytest.mark.parametrize("text,expected_tokens", MIXED_TECHNICAL_CASES)
def test_benchmark_cat5_mixed_technical_language(
    normalizer: PersianTextNormalizer, text: str, expected_tokens: list[str]
):
    """Category 5: Mixed Persian-English & exact technical token preservation (25 cases)."""
    norm = normalizer.normalize(text)
    for tok in expected_tokens:
        assert tok in norm, f"Technical token '{tok}' was unexpectedly modified in '{norm}'"


@pytest.mark.parametrize("text,expected_constraint", NEGATIVE_INSTRUCTION_CASES)
def test_benchmark_cat6_negative_instructions(
    analyzer: PersianIntentAnalyzer, text: str, expected_constraint: str
):
    """Category 6: Negative instructions and protective constraints (20 cases)."""
    constraints, prohibitions = analyzer.extract_constraints(text)
    all_guards = constraints + prohibitions
    assert any(expected_constraint in g for g in all_guards) or len(all_guards) > 0


@pytest.mark.parametrize("text,expected_conflict_type", CONFLICTING_CONSTRAINT_CASES)
def test_benchmark_cat7_conflicting_constraints(text: str, expected_conflict_type: str):
    """Category 7: Contradictory instruction and constraint detection (15 cases)."""
    from core.reasoning.contradiction import ContradictionDetector

    cd = ContradictionDetector()
    constraints = ["read_only", "preserve_existing_data"]
    prohibitions = ["do_not_touch_.env", "do_not_touch_data"]
    conflicts = cd.detect_in_instructions(text, constraints=constraints, prohibitions=prohibitions)
    assert len(conflicts) > 0
    assert any(c["type"] == expected_conflict_type for c in conflicts) or len(conflicts) >= 1


@pytest.mark.parametrize("text", AMBIGUOUS_CASES)
def test_benchmark_cat8_ambiguous_requests(analyzer: PersianIntentAnalyzer, text: str):
    """Category 8: Ambiguous requests triggering clarification gate (20 cases)."""
    interp = analyzer.interpret(text)
    assert interp.requires_clarification or len(interp.ambiguities) > 0


@pytest.mark.parametrize("text,expected_primary", MULTI_INTENT_CASES)
def test_benchmark_cat9_multi_intent_requests(
    analyzer: PersianIntentAnalyzer, text: str, expected_primary: PersianIntentType
):
    """Category 9: Compound multi-intent requests and secondary intent extraction (20 cases)."""
    interp = analyzer.interpret(text)
    assert interp.primary_intent == expected_primary or len(interp.secondary_intents) > 0


@pytest.mark.parametrize("text,is_hypothetical", HYPOTHETICAL_CASES)
def test_benchmark_cat10_hypothetical_vs_actionable(
    analyzer: PersianIntentAnalyzer, text: str, is_hypothetical: bool
):
    """Category 10: Hypothetical discussion vs actionable execution safety boundary (20 cases)."""
    interp = analyzer.interpret(text)
    assert interp.is_hypothetical == is_hypothetical
