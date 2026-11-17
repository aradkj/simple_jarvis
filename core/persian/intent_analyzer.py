"""Persian Intent Analyzer for JARVIS Conversational Intelligence.

Classifies user requests into strongly-typed intent categories, distinguishing:
- Autonomous actionable execution vs read-only inspection
- Hypothetical discussion ("چی میشه اگه...") -> strictly isolated from tool execution
- Destructive ambiguity ("همه فایل‌های اضافی رو پاک کن") -> requires explicit clarification
- Conversational corrections, language switches, application control, debugging, etc.
"""

from __future__ import annotations

import re

from core.persian.models import PersianIntentType


class PersianIntentAnalyzer:
    """Analyzes normalized user utterances and identifies intent, ambiguity, and hypothetical safety flags."""

    # 1. Ambiguous destructive / dangerous expressions requiring clarification
    AMBIGUOUS_DESTRUCTIVE_PATTERNS = [
        re.compile(
            r"\b(?:همه\s*(?:ی|ء)?\s*فایل[‌\s]*های\s*اضافی|فایل[‌\s]*های\s*(?:اضافی|اضافه|بی‌[‌\s]*استفاده|اضافه\s+(?:رو|را)\s+دور\s+بریز))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:هر\s*چی\s*اضافی[‌\s]*ه|همه\s*چیز\s*(?:رو|را)\s*(?:پاک|حذف|دیلیت)\s*کن|همه‌چیز\s*(?:رو|را)\s*(?:پاک|حذف|دیلیت)\s*کن|پاکسازی\s*کامل|کل\s*اطلاعات\s*(?:رو|را)\s*حذف\s*کن|تمام\s*فایل[‌\s]*ها\s*(?:رو|را)\s*دیلیت\s*کن|کل\s+سیستم\s*(?:رو|را)?\s*تمیز\s*کن)\b",
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
            r"\b(?:ماشین\s*حساب|ماشین‌حساب|calculator|نوت‌پد|نوتپد|notepad|کروم|chrome|اج|ایج|edge|ترمینال|terminal|cmd|powershell)\b",
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
            r"\b(?:اول\s+.+?\s+بعد|ابتدا\s+.+?\s+سپس|برنامه‌ریزی\s*کن|نقشه\s*راه|مراحل\s*کار|plan\s+out)\b",
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

        # 13. Application Control
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
            )
        ):
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
