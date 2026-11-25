"""Persian Intent Analyzer for JARVIS Conversational Intelligence.

Classifies user requests into strongly-typed intent categories, distinguishing:
- Autonomous actionable execution vs read-only inspection
- Hypothetical discussion ("چی میشه اگه...") -> strictly isolated from tool execution
- Destructive ambiguity ("همه فایل‌های اضافی رو پاک کن") -> requires explicit clarification
- Conversational corrections, language switches, application control, debugging, etc.
"""

from __future__ import annotations

import re
from typing import Any

from core.persian.models import (
    PersianEntity,
    PersianIntentType,
    SemanticInterpretation,
)


class PersianIntentAnalyzer:
    """Analyzes normalized user utterances and identifies intent, ambiguity, and hypothetical safety flags."""

    # 1. Ambiguous destructive / dangerous expressions requiring clarification
    AMBIGUOUS_DESTRUCTIVE_PATTERNS = [
        re.compile(
            r"\b(?:همه\s*(?:ی|ء)?\s*فایل[‌\s]*های\s*اضافی|فایل[‌\s]*های\s*(?:اضافی|اضافه|بی‌[‌\s]*استفاده|اضافه\s+(?:رو|را)\s+دور\s+بریز))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:هر\s*چی\s*اضافی[‌\s]*(?:ه|هست)|همه\s*چیز\s*(?:رو|را)\s*(?:پاک|حذف|دیلیت)\s*کن|همه‌چیز\s*(?:رو|را)\s*(?:پاک|حذف|دیلیت)\s*کن|پاکسازی\s*کامل|کل\s*اطلاعات\s*(?:رو|را)\s*حذف\s*کن|تمام\s*فایل[‌\s]*ها\s*(?:رو|را)\s*دیلیت\s*کن|کل\s+سیستم\s*(?:رو|را)?\s*تمیز\s*کن)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:پاکش\s+کن\s+همه\s*(?:رو|را)|همه\s*(?:رو|را)\s+دیلیت\s+بزن\s+بره|تمیزش\s+کن|همه‌چیز\s*(?:رو|را)\s*پاکسازی\s*کن|پوشه\s*(?:رو|را)\s*تمیزش\s+کن)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:هرچی\s+لاگ\s+هست\s*(?:رو|را)\s*حذف\s*کن|پروژه\s*(?:رو|را)\s*تمیز\s*کن\s*و\s*فایل[‌\s]*هاشو\s*پاک\s*کن)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:delete\s+all\s+unnecessary|wipe\s+everything|clean\s+up\s+all\s+junk|delete\s+all\s+files)\b",
            re.IGNORECASE,
        ),
    ]

    # 2. Hypothetical / speculative exploration (NEVER executes tools)
    HYPOTHETICAL_PATTERNS = [
        re.compile(
            r"\b(?:اگه|اگر)\s+.+?\s+(?:چی\s+میشه|چه\s+اتفاقی\s+می[‌\s]*افته|چه\s+خطری\s+داره|چقدر\s+طول\s+میکشه|با\s+خطای\s+.+?\s+مواجه\s+میشیم|چی\s+رخ\s+میده|کرش\s+میکنه|یا\s+.+?\s*میکنه)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:فرض\s+کن|فرضاً|فرضا|به\s+طور\s+فرضی|از\s+نظر\s+تئوری|تئوریک)\b", re.IGNORECASE
        ),
        re.compile(r"\b(?:چی\s+میشه\s+اگه|چطور\s+میشه\s+.+?\s+از\s+نظر\s+تئوری)\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+if|hypothetically|suppose|theoretically)\b", re.IGNORECASE),
        re.compile(r"\b(?:اگه|اگر)\s+.+?[؟?]$", re.IGNORECASE),
    ]

    # 3. User corrections & intention overrides
    CORRECTION_PATTERNS = [
        re.compile(r"\bنه\s*،?\s*منظورم\s+.+?\s+(?:بود|نبود)\b", re.IGNORECASE),
        re.compile(r"\bنه\s*،?\s*اشتباه\s+شد\b", re.IGNORECASE),
        re.compile(r"\bنه\s+اون\s*(?:فایل|پروژه|برنامه)?\s*نه\b", re.IGNORECASE),
        re.compile(
            r"\bنه\s*،?\s*(?:دست\s+نزن|صبر\s+کن|نبندش|پاکش\s+نکن|ریستارت\s+نکن)\b", re.IGNORECASE
        ),
        re.compile(r"\b(?:نه\s*،?\s*)?منظورم\s+.+?\s+نیست\b", re.IGNORECASE),
    ]

    # 4. Explicit Language Switch Requests
    LANGUAGE_SWITCH_PATTERNS = [
        (
            re.compile(
                r"\b(?:به\s+فارسی\s+(?:بگو|صحبت\s+کن|جواب\s+بده|پاسخ\s+بده|توضیح\s+بده)|از\s+(?:این|الان)\s+به\s+بعد\s+فارسی|فارسی\s+(?:حرف\s+بزن|صحبت\s+کن|جواب\s+بده))\b",
                re.IGNORECASE,
            ),
            "fa",
        ),
        (
            re.compile(
                r"\b(?:به\s+انگلیسی\s+(?:بگو|صحبت\s+کن|جواب\s+بده|پاسخ\s+بده|توضیح\s+بده)|دوباره\s+انگلیسی|از\s+(?:این|الان)\s+به\s+بعد\s+انگلیسی|انگلیسی\s+(?:حرف\s+بزن|صحبت\s+کن|جواب\s+بده))\b",
                re.IGNORECASE,
            ),
            "en",
        ),
        (
            re.compile(
                r"\b(?:switch\s+(?:back\s+)?to\s+(?:english|persian)|speak\s+(?:in\s+)?(?:english|persian|farsi))\b",
                re.IGNORECASE,
            ),
            "en",
        ),
    ]

    # 5. Confirmations and approvals
    APPROVAL_PATTERNS = [
        re.compile(
            r"^(?:تایید\s*میکنم|بله\s*انجام\s*بده|ارسال\s*کن|موافقم|اجرا\s*کن|باشه\s*انجامش\s*بده|اوکی|approve|confirm|proceed)\b",
            re.IGNORECASE,
        ),
    ]

    # 6. Task cancellations
    CANCELLATION_PATTERNS = [
        re.compile(
            r"\b(?:لغو\s*کن|کنسل\s*کن|دست\s*نگه\s*دار|متوقف\s*کن|لغوش\s*کن|cancel|abort|stop)\b",
            re.IGNORECASE,
        ),
    ]

    # 7. Greetings, colloquial slang & pleasantries
    GREETING_PATTERNS = [
        re.compile(
            r"^(?:سلام|درود|صبح\s*بخیر|عصر\s*بخیر|شب\s*بخیر|روز\s*بخیر|وقت\s*بخیر|سلام\s*علیکم|hello|hi|good\s+morning)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:چطوری|حالت\s*چطوره|خوبی|احوال\s*شما|روزت\s*چطور\s*بود|چه\s*خبر|بیداری|هستی\s+کمکم\s+کنی)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:دمت\s*گرم|قربونت|دستت\s*درد\s*نکنه|سپاس|ممنون|خسته\s*نباشی|ایول|ایولا|نوکرتم|چاکرم|کف\s*کردیم|حاجی\s+دمت\s+گرم|ترکوندی)\b",
            re.IGNORECASE,
        ),
    ]

    # 8. Git and repository operations
    GIT_PATTERNS = [
        re.compile(
            r"\b(?:گیت|git|برنچ|کامیت|ریپازیتوری|ورکینگ\s+تری|origin|پول\s+کن|استش\s+کن|مخزن|untracked|دیف|diff|گیت\s+استتوس|git\s+status|استتوس\s+ریپازیتوری)\b",
            re.IGNORECASE,
        ),
    ]

    # 9. Application and window control
    APP_CONTROL_PATTERNS = [
        re.compile(
            r"\b(?:ماشین\s*حساب|ماشین‌حساب|calculator|نوت‌پد|نوتپد|notepad|کروم|chrome|اج|ایج|edge|ترمینال|terminal|cmd|powershell|داکر|docker|کانتینر|container|سرور|server|سرویس|service)\b",
            re.IGNORECASE,
        ),
    ]

    # 10. Technical troubleshooting & debugging
    DEBUGGING_PATTERNS = [
        re.compile(
            r"\b(?:خطای|خطا|ارور|error|باگ|bug|کرش|crash|fail|تایم‌اوت|timeout|ریجکت|reject|اکسپشن|exception|دیباگ|debug|قطع\s+شده|خوابیده|permission\s+denied|کد\s+\d+\s+خارج\s+میشه|چرا\s+بالا\s+نمیاد|کجاش\s+ایراد\s+داره)\b",
            re.IGNORECASE,
        ),
    ]

    # 11. System diagnostics & resource monitoring
    DIAGNOSTICS_PATTERNS = [
        re.compile(
            r"\b(?:وضعیت\s+سیستم|سی‌\s*پی‌\s*یو|سی\s*پی\s*یو|cpu|رم\s+|ram\b|حافظه|دیسک|باتری|پروسس|پراسس|سرویس|اینترنت\s+وصله|کارت\s+گرافیک|پهنای\s+باند|فن\s+لپ‌تاپ|داغ\s+کرده|زیر\s+لود|استتوس\s+باتری)\b",
            re.IGNORECASE,
        ),
    ]

    # 12. Web research & online queries
    WEB_RESEARCH_PATTERNS = [
        re.compile(
            r"\b(?:سرچ\s+کن|جستجو\s+کن|در\s+گوگل|در\s+وب|در\s+اینترنت|توی\s+اینترنت|اخبار|قیمت\s+دلار|مستندات|داکیومنت|دنبال\s+.+?\s+بگرد|web\s+search|google|search)\b",
            re.IGNORECASE,
        ),
    ]

    # 13. Multi-step task planning
    TASK_PLANNING_PATTERNS = [
        re.compile(
            r"\b(?:اول\s+.+?\s+بعد|ابتدا\s+.+?\s+سپس|برنامه‌ریزی\s*کن|نقشه\s*راه|مراحل\s*کار|plan\s+out|زمان[‌\s]*بندی\s*کن)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:باز\s*کن|بررسی\s*کن|استارت\s*بزن|متوقف\s*کن).+?(?:تست[‌\s]*هاش|تستاش|لاگ[‌\s]*ها|سپس|بعد|و\s+اگه).+?(?:اجرا\s*کن|درستش\s*کن|حلش\s*کن|ریستارت\s*کن|نمایش\s*بده|چک\s*کن)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:تست[‌\s]*ها\s*رو\s*ران\s*کن\s*و\s*وضعیت|داکر\s*رو\s*استارت\s*بزن\s*و\s*کانتینر|تسک[‌\s]*ها\s*رو\s*زمان|سرور\s*رو\s*متوقف\s*کن\s*سپس)\b",
            re.IGNORECASE,
        ),
    ]

    # 14. Code explanation & architectural walkthrough
    EXPLANATION_PATTERNS = [
        re.compile(
            r"\b(?:این\s+تابع\s+.+?\s+چی\s+کار\s+میکنه|چی\s+کار\s+میکنه|توضیح\s+بده|تشریح\s+کن|برام\s+باز\s+کن|الگوریتم|معماری|چطور\s+پیاده\s+شده|(?:چطور|چگونه)\s+.+?\s+(?:رو|را)\s+اجرا\s+میکنه|چرا\s+از\s+.+?\s+استفاده\s+شده|چطوری\s+حرکت\s+میکنه|sql\s+injection\s+داره)\b",
            re.IGNORECASE,
        ),
    ]

    def analyze(self, text: str) -> tuple[PersianIntentType, bool, bool, str | None]:
        """Analyze intent from text.

        Returns:
            (intent: PersianIntentType, is_hypothetical: bool, is_ambiguous: bool, clarification_prompt: str | None)
        """
        if not text:
            return PersianIntentType.UNKNOWN, False, False, None

        lower = text.strip().lower()

        # 1. Ambiguous destructive / broad requests (Strict safety boundary)
        for pattern in self.AMBIGUOUS_DESTRUCTIVE_PATTERNS:
            if pattern.search(lower):
                clarification = (
                    "Sir, this request is broad or ambiguous. Could you please specify "
                    "exactly which files or operations you wish to target before I proceed?"
                )
                return PersianIntentType.FILE_OPERATION, False, True, clarification

        # 2. Hypothetical Discussion (Never triggers execution)
        for pattern in self.HYPOTHETICAL_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.HYPOTHETICAL_DISCUSSION, True, False, None

        # 3. User Correction
        for pattern in self.CORRECTION_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.USER_CORRECTION, False, False, None

        # 4. Language Switch Command
        for pattern, _lang in self.LANGUAGE_SWITCH_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.LANGUAGE_SWITCH, False, False, None

        # 5. Confirmation / Approval
        for pattern in self.APPROVAL_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.CONFIRMATION_OR_APPROVAL, False, False, None

        # 6. Cancellation
        for pattern in self.CANCELLATION_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.TASK_CANCELLATION, False, False, None

        # 7. Multi-Step Task Planning
        for pattern in self.TASK_PLANNING_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.TASK_PLANNING, False, False, None

        # 8. Web Research
        for pattern in self.WEB_RESEARCH_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.WEB_RESEARCH, False, False, None

        # 9. Technical Troubleshooting & Debugging
        for pattern in self.DEBUGGING_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.DEBUGGING, False, False, None

        # 10. Git Operations
        for pattern in self.GIT_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.GIT_OPERATION, False, False, None

        # 10.5. Universal Integration Hub (Antigravity & WhatsApp)
        if any(
            w in lower
            for w in (
                "واتساپ",
                "whatsapp",
                "انتی گراویتی",
                "انتی‌گراویتی",
                "antigravity",
                "کیو آر",
                "qr",
                "بارکد",
            )
        ):
            return PersianIntentType.INTEGRATION_MANAGEMENT, False, False, None

        # 11. System Diagnostics
        for pattern in self.DIAGNOSTICS_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.SYSTEM_DIAGNOSTICS, False, False, None

        # 12. Code Explanation Request
        for pattern in self.EXPLANATION_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.CODE_EXPLANATION, False, False, None

        # 13. Application & Technical Service Control
        if any(
            k in lower
            for k in (
                "باز کن",
                "بیار بالا",
                "بیار",
                "اجرا کن",
                "ببند",
                "ببندش",
                "لود کن",
                "open",
                "launch",
                "ران کن",
                "ریستارت کن",
                "ریاستارت کن",
                "استارت کن",
                "استاپ کن",
                "restart",
                "run",
            )
        ):
            if any(
                w in lower
                for w in (
                    "api",
                    "کانتینر",
                    "سرویس",
                    "container",
                    "server",
                    "سرور",
                    "migration",
                    "مایگریشن",
                    "برنامه",
                    "اپلیکیشن",
                    "app",
                )
            ):
                return PersianIntentType.APPLICATION_CONTROL, False, False, None
            for pattern in self.APP_CONTROL_PATTERNS:
                if pattern.search(lower):
                    return PersianIntentType.APPLICATION_CONTROL, False, False, None

        # 14. File Operations
        if any(
            k in lower
            for k in ("فایل", "file", "پوشه", "folder", "دایرکتوری", ".py", ".json", ".md", ".env")
        ) and any(
            k in lower
            for k in (
                "بساز",
                "ایجاد",
                "پاک",
                "حذف",
                "بخوان",
                "بخون",
                "بخونش",
                "مشاهده",
                "باز کن",
                "ادیت",
                "ویرایش",
                "عوض کن",
                "تغییر بده",
                "create",
                "delete",
                "read",
                "view",
            )
        ):
            return PersianIntentType.FILE_OPERATION, False, False, None

        # 15. Greetings & Polite inquiries
        for pattern in self.GREETING_PATTERNS:
            if pattern.search(lower):
                return PersianIntentType.GENERAL_CONVERSATION, False, False, None

        # 16. General Question Answering
        if re.search(
            r"^(?:چرا|چطور|چگونه|وضعیت|علت|ساعت|تاریخ|آیا|why|how|what|status|check)\b", lower
        ):
            return PersianIntentType.QUESTION_ANSWERING, False, False, None

        # Default fallback
        return PersianIntentType.GENERAL_CONVERSATION, False, False, None

    def analyze_intent(self, text: str) -> tuple[PersianIntentType, float, bool, bool, str | None]:
        """Analyze intent returning (intent, confidence, is_ambiguous, is_hypothetical, clarification_prompt)."""
        intent, is_hypo, is_ambig, clarify_prompt = self.analyze(text)
        conf = 0.95 if intent != PersianIntentType.UNKNOWN else 0.3
        return intent, conf, is_ambig, is_hypo, clarify_prompt

    def extract_secondary_intents(
        self, text: str, primary: PersianIntentType
    ) -> list[PersianIntentType]:
        """Extract multi-intent secondary objectives from complex requests (Section 4)."""
        secondaries: list[PersianIntentType] = []
        lower = text.lower()

        # Check diagnostics
        for pat in self.DIAGNOSTICS_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.SYSTEM_DIAGNOSTICS:
                secondaries.append(PersianIntentType.SYSTEM_DIAGNOSTICS)
                break
        # Check git
        for pat in self.GIT_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.GIT_OPERATION:
                secondaries.append(PersianIntentType.GIT_OPERATION)
                break
        # Check debugging
        for pat in self.DEBUGGING_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.DEBUGGING:
                secondaries.append(PersianIntentType.DEBUGGING)
                break
        # Check explanation
        for pat in self.EXPLANATION_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.CODE_EXPLANATION:
                secondaries.append(PersianIntentType.CODE_EXPLANATION)
                break
        # Check file operations
        if (
            any(k in lower for k in ("فایل", "file", "پوشه", "folder"))
            and primary != PersianIntentType.FILE_OPERATION
        ):
            secondaries.append(PersianIntentType.FILE_OPERATION)
        # Check app control
        for pat in self.APP_CONTROL_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.APPLICATION_CONTROL:
                secondaries.append(PersianIntentType.APPLICATION_CONTROL)
                break
        # Check web research
        for pat in self.WEB_RESEARCH_PATTERNS:
            if pat.search(lower) and primary != PersianIntentType.WEB_RESEARCH:
                secondaries.append(PersianIntentType.WEB_RESEARCH)
                break
        return list(dict.fromkeys(secondaries))

    def extract_preconditions(self, text: str) -> list[str]:
        """Extract conditional preconditions from instruction statements."""
        preconditions: list[str] = []
        lower = text.lower()

        # Conditional markers: اگر, اگه, در صورتی که, چنانچه, به شرطی که, فقط در صورتی که, if, in case
        cond_patterns = [
            (
                re.compile(
                    r"(?:اگر|اگه|چنانچه|فقط\s*در\s*صورتی\s*که|در\s*صورتی\s*که|به\s*شرطی\s*که|مشروط\s*بر\s*(?:اینکه)?)\s+(.+?)\s+(?:بود|شد|شدن|شدند|نبود|نشد|داشت|نداشت|پاس\s*شد|پاس\s*شدن|پاس\s*شدند|خطا\s*داد|موجود\s*نبود|موجود\s*بود|باز\s*بود|بسته\s*بود)",
                    re.IGNORECASE,
                ),
                "condition",
            ),
            (
                re.compile(
                    r"if\s+(.+?)\s+(?:exists|fails|passes|is\s+open|is\s+running|not\s+found)",
                    re.IGNORECASE,
                ),
                "condition_en",
            ),
        ]
        for pat, _kind in cond_patterns:
            matches = pat.findall(lower)
            for m in matches:
                clean_cond = str(m).strip()
                if clean_cond:
                    preconditions.append(clean_cond)

        if (
            "اگر خطایی" in lower
            or "در صورت خطا" in lower
            or "if error" in lower
            or "اگه خطا داشت" in lower
            or "اگر خطا داشت" in lower
        ):
            preconditions.append("on_error_detected")
        if "اگر وجود نداشت" in lower or "در صورت عدم وجود" in lower or "if not exists" in lower:
            preconditions.append("target_does_not_exist")
        if "فایل وجود داشت" in lower or "موجود بود" in lower:
            preconditions.append("target_exists")
        if "اگر باز بود" in lower or "در صورتی که باز است" in lower:
            preconditions.append("target_is_open")
        if (
            "اگر تست‌ها پاس شدند" in lower
            or "در صورت موفقیت تست‌ها" in lower
            or "تستها موفق شدن" in lower
            or "تست‌ها موفق شدن" in lower
        ):
            preconditions.append("tests_pass")

        return list(dict.fromkeys(preconditions))

    def extract_constraints(self, text: str) -> tuple[list[str], list[str]]:
        """Extract operational constraints and prohibited actions from instructions (Section 3.5 & 4)."""
        constraints: list[str] = []
        prohibitions: list[str] = []
        lower = text.lower()

        # Data preservation
        if any(
            k in lower
            for k in (
                "حواست باشه چیزی از بین نره",
                "دقت کن چیزی پاک نشه",
                "اطلاعات پاک نشه",
                "دیتابیس پاک نشه",
                "اطلاعات قبلی حذف نشود",
                "حذف نشود",
                "پاک نشه",
                "پاک نکن",
                "حذف نکن",
                "از بین نره",
                "از دست نره",
                "مراقب باش",
                "حفظ کن",
                "حفظش کن",
                "بدون اجازه",
                "preserve data",
                "do not lose data",
            )
        ):
            constraints.append("preserve_existing_data")
            prohibitions.append("no_unauthorized_deletion")

        # Read only constraint
        if any(
            k in lower
            for k in (
                "فقط ببین",
                "فقط بررسی کن",
                "فقط بخوان",
                "فقط بخون",
                "بخون",
                "بخوان",
                "فقط نگاه کن",
                "فقط لیست کن",
                "رو بخون",
                "را بخون",
                "رو بخوان",
                "دست نزن",
                "دست به",
                "دست به هیچی نزن",
                "تغییر نده",
                "ویرایش نکن",
                "ادیت نکن",
                "عوض نکن",
                "تغییری",
                "read only",
                "do not modify",
                "inspect only",
            )
        ):
            constraints.append("read_only")
            prohibitions.append("no_modifications")

        # Non-destructive
        if any(
            k in lower for k in ("خرابش نکن", "دیگه خراب نشه", "نبندش", "پاکش نکن", "do not break")
        ):
            constraints.append("maintain_stability")

        # Strict explicit prohibitions
        if any(
            k in lower
            for k in (
                "اجازه نداری",
                "حق نداری",
                "مجاز نیستی",
                "به هیچ وجه",
                "به هیچ عنوان",
                "تحت هیچ شرایطی",
                "نباید",
                "ممنوع است",
            )
        ):
            constraints.append("prohibition_active")
            prohibitions.append("strictly_forbidden")
            if any(k in lower for k in ("حذف", "پاک", "دیلیت", "remove", "delete")):
                constraints.append("preserve_existing_data")
                prohibitions.append("no_unauthorized_deletion")
            if any(k in lower for k in ("تغییر", "ویرایش", "عوض", "دستکاری", "دست")):
                constraints.append("read_only")
                prohibitions.append("no_modifications")

        # Command and execution negation
        if any(
            k in lower
            for k in (
                "اجرا نکن",
                "ران نکن",
                "دستور رو اجرا نکن",
                "دستور را اجرا نکن",
                "دستور اجرا نشود",
                "دستور را اجرا ننمایید",
            )
        ):
            prohibitions.append("no_execution")
            constraints.append("execution_prohibited")

        # Confirmation before transmission
        if any(k in lower for k in ("بدون تایید", "بدون تأیید", "بدون اجازه")):
            constraints.append("requires_user_confirmation")
            if any(w in lower for w in ("ارسال", "بفرست", "فرستادن", "send", "transmit")):
                prohibitions.append("no_unauthorized_transmission")

        # Scope constraint
        m_scope = re.search(
            r"فقط\s*(?:داخل|در)\s*(.+?)\s*(?:کار\s*کن|انجام\s*بده|اعمال\s*کن)", lower
        )
        if m_scope:
            scope_target = m_scope.group(1).strip()
            constraints.append(f"scoped_to_{scope_target}")

        # Specific prohibited targets and negative verbs
        m1 = re.findall(r"دست\s*به\s+(.+?)\s*نزن", lower)
        m2 = re.findall(
            r"(?:به\s+)(.+?)\s*(?:دست\s*نزن|تغییر\s*نده|پاک\s*نکن|حذف\s*نکن|دسترسی\s*نداشته\s*باش)",
            lower,
        )
        m3 = re.findall(
            r"([a-zA-Z0-9_\-\.\u200c]+|[آ-ی\u200c]+?)\s*(?:رو|را)?\s*(?:پاک\s*نکن|حذف\s*نکن|دیلیت\s*نکن|تغییر\s*نده|دستکاری\s*نکن|عوض\s*نکن|reset\s*نکن|ریست\s*نکن|اجرا\s*نکن)",
            lower,
        )
        m_subj = re.findall(
            r"(?:اجازه\s*نداری|حق\s*نداری|نباید|به\s*هیچ\s*وجه\s*نباید)\s+(.+?)\s*(?:رو|را)?\s*(?:حذف\s*کنی|پاک\s*کنی|دیلیت\s*کنی|تغییر\s*بدی|دست\s*بزنی|دستکاری\s*کنی|اجرا\s*کنی)",
            lower,
        )
        for target in m1 + m2 + m3 + m_subj:
            target_clean = target.strip()
            if target_clean and target_clean not in ("هیچی", "چیزی", "این", "آن", "اون"):
                prohibitions.append(f"do_not_touch_{target_clean}")
                if any(w in lower for w in ("حذف", "پاک", "دیلیت", "reset", "ریست")):
                    prohibitions.append("no_unauthorized_deletion")
                    constraints.append("preserve_existing_data")

        return list(dict.fromkeys(constraints)), list(dict.fromkeys(prohibitions))

    def detect_ambiguities(
        self,
        text: str,
        primary: PersianIntentType,
        entities: list[PersianEntity] | None = None,
        context: Any = None,
    ) -> list[str]:
        """Detect ambiguous or underspecified requests before execution (Section 3.5)."""
        ambiguities: list[str] = []
        lower = text.lower()

        # Destructive broad scope
        for pat in self.AMBIGUOUS_DESTRUCTIVE_PATTERNS:
            if pat.search(lower):
                ambiguities.append("broad_destructive_scope_unspecified_targets")

        # Explicit user confirmation gate
        if any(k in lower for k in ("بعد از تایید", "با تایید من", "با تایید کاربر")):
            ambiguities.append("requires_user_confirmation")

        # Unclear relative reference without context
        if (
            any(k in lower for k in ("اون فایل", "فایل قبلی", "اون یکی"))
            and not context
            and (
                not entities
                or not any(e.entity_type in ("file", "file_name", "file_path") for e in entities)
            )
        ):
            ambiguities.append("unclear_file_reference")

        # Unspecified target
        if "بدون مشخص کردن" in lower or "بدون نام" in lower:
            ambiguities.append("unspecified_target_parameter")

        # Conflicting instructions
        if ("پاک کن" in lower or "حذف کن" in lower) and (
            "دست نزن" in lower or "تغییر نده" in lower
        ):
            ambiguities.append("conflicting_instruction_delete_vs_do_not_touch")

        return ambiguities

    def interpret(
        self,
        text: str,
        entities: list[PersianEntity] | None = None,
        context: Any = None,
        normalized_text: str | None = None,
    ) -> SemanticInterpretation:
        """Full Semantic Interpretation Layer implementation satisfying Section 4 requirements."""
        norm_text = normalized_text or text
        primary, conf, is_ambig, is_hypo, clarification_prompt = self.analyze_intent(norm_text)
        secondaries = self.extract_secondary_intents(norm_text, primary)
        constraints, prohibitions = self.extract_constraints(norm_text)
        ambiguities = self.detect_ambiguities(norm_text, primary, entities, context)
        if is_ambig and "broad_destructive_scope_unspecified_targets" not in ambiguities:
            ambiguities.append("broad_scope_requires_clarification")

        is_read_only = "read_only" in constraints or any(
            k in norm_text.lower() for k in ("فقط ببین", "بررسی کن", "inspect only")
        )
        requires_clarify = len(ambiguities) > 0 or is_ambig
        preconditions = self.extract_preconditions(norm_text)

        action = "conversation"
        if primary == PersianIntentType.FILE_OPERATION:
            action = "file_operation"
        elif primary == PersianIntentType.APPLICATION_CONTROL:
            action = "application_control"
        elif primary == PersianIntentType.GIT_OPERATION:
            action = "git_operation"
        elif primary == PersianIntentType.DEBUGGING:
            action = "diagnose_and_debug"
        elif primary == PersianIntentType.SYSTEM_DIAGNOSTICS:
            action = "system_diagnostics"
        elif primary == PersianIntentType.WEB_RESEARCH:
            action = "web_search"
        elif primary == PersianIntentType.TASK_PLANNING:
            action = "multi_step_plan"

        risks: list[str] = []
        if any(k in norm_text.lower() for k in ("پاک", "حذف", "delete", "remove", "drop", "wipe")):
            risks.append("destructive_file_or_data_loss")
        if primary == PersianIntentType.APPLICATION_CONTROL:
            risks.append("process_termination_or_launch")

        # Contextual reference resolution
        resolved_refs: dict[str, str] = {}
        unresolved_refs: list[str] = []
        active_proj: str | None = None
        active_f: str | None = None

        if context:
            from core.persian.context_resolver import ReferenceResolutionEngine

            resolver = ReferenceResolutionEngine()
            history = (
                getattr(context, "turns", [])
                if hasattr(context, "turns")
                else (context.get("turns", []) if isinstance(context, dict) else [])
            )
            fallback_proj = getattr(context, "active_project_name", None) or (
                context.get("active_project") if isinstance(context, dict) else None
            )
            fallback_f = getattr(context, "active_file_path", None) or (
                context.get("active_file") if isinstance(context, dict) else None
            )
            resolved_refs, unresolved_refs, active_proj, active_f = resolver.resolve(
                current_text=norm_text,
                entities=entities or [],
                history=history,
                fallback_project=fallback_proj,
                fallback_file=str(fallback_f) if fallback_f else None,
            )

        return SemanticInterpretation(
            raw_input=text,
            normalized_text=norm_text,
            detected_language="fa" if any("\u0600" <= c <= "\u06ff" for c in text) else "en",
            primary_intent=primary,
            secondary_intents=secondaries,
            requested_action=action,
            target_entity=entities[0].name if entities else (active_f or active_proj),
            relevant_objects=[
                e.name for e in (entities or []) if e.entity_type in ("file", "app", "project")
            ],
            relevant_locations=[
                e.name for e in (entities or []) if e.entity_type in ("directory", "file_path")
            ],
            constraints=constraints,
            prohibited_actions=prohibitions,
            preconditions=preconditions,
            desired_outcome="execute requested action safely"
            if not is_hypo
            else "provide hypothetical analysis",
            temporal_references=re.findall(
                r"\b(امروز|دیروز|الان|قبلاً|قبلا|بعداً|بعدا|today|yesterday|now)\b",
                norm_text,
                re.IGNORECASE,
            ),
            dependencies=[],
            explicit_user_preferences=[],
            potential_risks=risks,
            ambiguities=ambiguities,
            confidence_indicators={
                "intent": conf,
                "semantic_calibration": 0.95 if not ambiguities else 0.4,
            },
            requires_clarification=requires_clarify,
            clarification_prompt=clarification_prompt,
            is_hypothetical=is_hypo,
            is_read_only=is_read_only,
            extracted_entities=entities or [],
            resolved_references=resolved_refs,
            unresolved_references=unresolved_refs,
            active_project=active_proj,
            active_file=active_f,
            response_language="en",
        )
