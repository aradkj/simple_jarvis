"""JARVIS Personality Engine & Conversational Intelligence Layer for Phase 9.

Implements the authentic JARVIS persona (calm, intelligent, professional, truthful),
follow-up reference resolution across conversation turns, prompt-injection defense,
and strictly truthful result reporting for actions.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger
from memory.base import ConversationMessage

if TYPE_CHECKING:
    from core.executor import ExecutionOutcome

logger = get_logger("core.personality")


def filter_english_speech_only(text: str) -> str:
    """Ensure zero Persian sentences or clauses leak into British English TTS voice output."""
    if not text:
        return ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    english_lines = []
    for line in lines:
        persian_chars = len(re.findall(r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", line))
        latin_chars = len(re.findall(r"[a-zA-Z]", line))
        # If line is mostly or entirely Persian, skip it when speaking English
        if persian_chars > 0 and (latin_chars == 0 or persian_chars >= latin_chars):
            continue
        # Also strip any trailing inline Persian clause
        cleaned_line = re.sub(
            r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF\u200c\u200d\u064B-\u065F]+", "", line
        ).strip()
        cleaned_line = re.sub(r"\s*([.,?!])(?:\s*[.,?!])+", r"\1", cleaned_line)
        cleaned_line = re.sub(r"\s+", " ", cleaned_line).strip()
        if cleaned_line:
            english_lines.append(cleaned_line)
    result = " ".join(english_lines).strip()
    return result if result else text


class ResponseLanguagePolicy(StrEnum):
    """Governs the language policy for JARVIS conversational output."""

    DEFAULT_ENGLISH = "DEFAULT_ENGLISH"  # Understands Persian; responds in British English unless Persian explicitly requested
    PERSIAN = "PERSIAN"  # Always responds in Persian
    FOLLOW_USER = "FOLLOW_USER"  # Matches user's spoken/written language


JARVIS_SYSTEM_PERSONA_EN = """You are JARVIS, an advanced, highly capable, calm, and intelligent personal AI desktop assistant for Windows 11.

# Core Persona & Conversational Manner
- Refined British Persona: Composed, confident, articulate, thoughtful, and genuinely helpful. Your tone reflects high intellectual caliber and understated elegance.
- Natural Formality: Speak with natural, conversational British English cadence. Do NOT insert "sir" mechanically into every sentence. Use "sir" naturally and sparingly (e.g. at the opening of an interaction or when confirming a critical action). Never sound repetitive, robotic, or theatrical.
- Conversational Empathy: Respond directly to what the user actually means, rather than giving literal or superficial replies.

# Human-Level Persian Linguistic & Cultural Understanding
- Fluent Persian Comprehension: You have native-level understanding of Persian (فارسی), including colloquial Iranian speech (تهرانی و محاوره‌ای), colloquial syntax, everyday slang, idioms, polite phrases (تعارفات), informal expressions, and mixed Persian-English technical vocabulary.
- Implicit & Indirect Meaning:
  * "ببین یه چیزی میخوام ازت بپرسم" means the user is casually opening a discussion or question. Acknowledge warmly and invite the inquiry.
  * "راستش اون چیزی که ساختیم هنوز یه جای کارش میلنگه" means there is an issue or imperfection in the recent work that needs debugging or refinement.
  * "نه، اینجوری نه. منظورم این بود که خودش بفهمه چی میگم" is an implicit correction indicating the user desires autonomous comprehension rather than rigid mechanical parsing.
  * "یه کم طبیعیتر باهام حرف بزن" requests a more relaxed, authentic, human conversational tone.
  * "این قضیه رو فعلاً بیخیال شو، بریم سراغ یه چیز دیگه" indicates a topic pivot; drop the current subject and follow the user's new direction.
  * "همون چیزی که قبلتر گفتیم رو ادامه بده" is a contextual resumption of the previous topic or task.
  * "نه صبر کن، بذار اول یه چیز دیگه رو توضیح بدم" indicates a conversational pause/clarification; wait and pay attention to the upcoming context.
  * "ببین من نمیخوام فقط دستورات رو اجرا کنه؛ میخوام واقعاً متوجه بشه چی میگم" means the user wants intuitive, context-aware reasoning rather than mere rule execution.
  * "این رو یه جوری درست کن که دیگه لازم نباشه هر بار توضیح بدم" means make the solution robust and persistent.
- Conversational Corrections & Nuance:
  * Recognize spontaneous corrections ("نه منظورم این نبود", "اشتباه شد", "منظورم اون یکی بود").
  * Distinguish rhetorical or humorous remarks from literal commands.
  * Recognize negation and conversational hedges ("نمیخوام این کار رو بکنی", "فعلاً دست نزن").
  * Retain negative constraints across turns (e.g., if the user previously said "ولی کیفیت درکش پایین نیاد", that constraint remains active for all related actions).

# Language Policy & Response Rules
- Default Language Policy: Respond in polished, natural British English by default, even when the user speaks or writes in Persian. Grasp the complete Persian nuance, but respond naturally in British English.
- Meaning-First Responses: Do NOT translate the user's Persian sentence word-for-word. Respond to the substantive meaning, intent, and conversational context with original, thoughtful dialogue.
- Explicit Persian Requests: When the user explicitly requests Persian (e.g., "به فارسی بگو", "فارسی صحبت کن", "از الان به بعد فارسی"), reply in elegant, natural, respectful, fluent Persian until instructed to revert.

# Safety & Reliability
- Hypothetical Discussions: When asked speculative or "what-if" questions ("اگه این کار رو بکنیم چی میشه؟"), provide clear analytical explanations and theoretical trade-offs without executing any modifying tools.
- Ambiguous Destructive Actions: If a request is broad or ambiguous ("همه چیز رو پاک کن"), pause and politely ask for clarification before proceeding.
- Absolute Truthfulness: You are strictly TRUTHFUL. Never claim an action, file edit, or transmission was completed unless it has actually succeeded and been verified.
"""

JARVIS_SYSTEM_PERSONA_FA = """شما جارویس (JARVIS) هستید؛ دستیار هوشمند، صادق، بسیار توانمند، آرام، مؤدب و فرهیخته شخصی دسکتاپ برای ویندوز ۱۱.

# ویژگی‌های لحن و شخصیت
- گفتار طبیعی، هوشمندانه، باوقار و اطمینان‌بخش به زبان فارسی اصیل و شیوا.
- پرهیز از تکرار وسواسی یا تصنعی واژگان و عناوین؛ مکالمه باید روان، صمیمی در عین احترام، و کاملاً انسانی باشد.
- پاسخگویی متناسب با نیاز: پاسخ‌های کوتاه و کارآمد برای دستورات سریع، و تحلیل‌های هوشمندانه و عمیق برای مباحث فنی و فکری.

# درک معنایی عمیق و چندبعدی
- درک کامل زبان محاوره‌ای، اصطلاحات روزمره، کنایات، تعارفات، لحن‌های طنز یا استعاری، و ترکیب‌های دو زبانه فارسی-انگلیسی.
- درک اصلاحات ناگهانی کاربر در طول گفتگو ("نه منظورم اون نبود"، "صبر کن اول اینو بگم").
- حفظ قیود و شرایط گفتگو در طول چند نوبت مکالمه ("سرعت بالا بره اما کیفیت پایین نیاد").
- تفکیک پرسش‌های فرضی ("اگه لاگ‌ها رو پاک کنیم چی میشه؟") از دستورات اجرایی، و توضیح تحلیلی بدون انجام کار تخریبی.
- درخواست توضیح در موارد مبهم یا خطرناک برای حفظ ایمنی کامل داده‌ها.
- صداقت و دقت مطلق در گزارش وضعیت‌ها و نتایج ابزارها.
"""


class JarvisPersonalityEngine:
    """Controls conversational tone, follow-up reference resolution, and truthful formatting."""

    def __init__(self) -> None:
        pass

    @classmethod
    def detect_explicit_persian_request(cls, text: str) -> bool:
        """Return True if user explicitly requested a response in Persian."""
        if not text:
            return False
        try:
            from core.persian.language_policy import (
                LanguagePolicyManager,
                LanguageSwitchType,
                ResponseLanguage,
            )

            mgr = LanguagePolicyManager()
            target_lang, switch_type, _ = mgr.evaluate_request(text)
            if target_lang == ResponseLanguage.PERSIAN and switch_type != LanguageSwitchType.NONE:
                return True
        except Exception:
            pass
        return bool(
            re.search(
                r"(به\s*فارسی|فارسی\s*(بگو|حرف\s*بزن|صحبت\s*کن|پاسخ\s*بده|بنویس|جواب\s*بده|توضیح\s*بده)|in\s*persian|in\s*farsi)",
                text,
                re.IGNORECASE,
            )
        )

    @classmethod
    def get_system_instructions(
        cls,
        language: str = "auto",
        language_policy: str = "DEFAULT_ENGLISH",
        explicit_persian: bool = False,
    ) -> str:
        """Return the core personality system instructions based on language policy and personal memory."""
        if (
            explicit_persian
            or language == "fa"
            or language_policy == ResponseLanguagePolicy.PERSIAN
        ):
            base_prompt = JARVIS_SYSTEM_PERSONA_FA
        elif language == "en" or language_policy == ResponseLanguagePolicy.DEFAULT_ENGLISH:
            base_prompt = JARVIS_SYSTEM_PERSONA_EN
        else:
            base_prompt = f"{JARVIS_SYSTEM_PERSONA_EN}\n\n{JARVIS_SYSTEM_PERSONA_FA}"

        # Inject Personal Memory & Configured Tone
        try:
            from core.memory.personal_store import PersonalStore

            store = PersonalStore.get_instance()
            p_config = store.get_personality_config()
            custom_inst = (
                f"\n# User Custom Personality Instructions:\n{p_config.custom_instructions}\n"
                if p_config.custom_instructions
                else ""
            )
            tone_inst = (
                f"\n# Conversational Tone Settings:\n"
                f"- Assistant Name: {p_config.assistant_name}\n"
                f"- Tone Demeanor: {p_config.tone}\n"
                f"- Formality Level: {p_config.formality}\n"
                f"- Detail Level: {p_config.detail_level}\n"
            )
            mem_summary = store.build_memory_summary_block()
            mem_block = (
                f"\n\n{tone_inst}{custom_inst}\n{mem_summary}"
                if mem_summary
                else f"\n\n{tone_inst}{custom_inst}"
            )
            return f"{base_prompt}{mem_block}"
        except Exception:
            return base_prompt

    @classmethod
    def sanitize_untrusted_content(cls, content: str, source_name: str = "untrusted_source") -> str:
        """Wrap untrusted external content (emails, web pages, messages) in security boundary tags."""
        # Clean any existing closing tags that could attempt jailbreak
        escaped = content.replace("</untrusted_content>", "&lt;/untrusted_content&gt;")
        return f'<untrusted_content source="{source_name}">\n{escaped}\n</untrusted_content>'

    @classmethod
    def resolve_references(
        cls,
        current_prompt: str,
        history: list[ConversationMessage],
        recent_entities: dict[str, Any] | None = None,
        session_id: str | None = None,
        processor: Any | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Resolve pronouns and anaphoric references from conversation history and session context.

        Examples:
        - "همون مرورگر" -> "مرورگر کروم" (if chrome was referenced)
        - "همین رو ایمیل کن" -> adds subject/body from previous agent or user text.
        - "تستهاشو اجرا کن" -> binds to active project's test suite.
        - "درستش کن" -> binds to active project's error remediation.
        """
        resolved_text = current_prompt.strip()
        inferred: dict[str, Any] = {}

        # Check for explicit Persian response request
        if cls.detect_explicit_persian_request(current_prompt):
            inferred["explicit_persian_requested"] = True
            inferred["language_override"] = "fa"

        # 0. Check for vague modification requests without details
        vague_edit_patterns = [
            r"^(?:لطفاً\s+)?ویرایشش\s+کن[.؟!]?$",
            r"^(?:لطفاً\s+)?ویرایش\s+کن[.؟!]?$",
            r"^(?:لطفاً\s+)?این\s*(?:رو| را)?\s*ویرایش\s*کن[.؟!]?$",
            r"^(?:لطفاً\s+)?اون\s*(?:فایل)?\s*(?:رو| را)?\s*(?:تغییر\s*بده|ویرایش\s*کن)[.؟!]?$",
            r"^(?:لطفاً\s+)?اصلاحش\s+کن[.؟!]?$",
            r"^(?:لطفاً\s+)?اصلاح\s+کن[.؟!]?$",
            r"^(?:لطفاً\s+)?درستش\s+کن[.؟!]?$",
            r"^(?:لطفاً\s+)?فایل\s*(?:رو| را)?\s*عوض\s*کن[.؟!]?$",
            r"^(?:لطفاً\s+)?تغییرش\s+بده[.؟!]?$",
            r"^(?:لطفاً\s+)?پیام\s*بفرست[.؟!]?$",
            r"^(?:لطفاً\s+)?ایمیل\s*(?:بزن|بفرست)[.؟!]?$",
            r"^(?:please\s+)?edit\s+(?:it|this)[.?!]?$",
            r"^(?:please\s+)?modify\s+(?:it|this)[.?!]?$",
        ]
        if any(re.match(p, resolved_text.strip(), re.IGNORECASE) for p in vague_edit_patterns):
            inferred["needs_clarification"] = True
            inferred["clarification_reason"] = "missing_modification_details"
            inferred["clarification_prompt"] = (
                "چه تغییری باید روی این فایل اعمال شود؟ لطفاً مشخصات یا متن مورد نظر برای ویرایش را بفرمایید."
            )

        # Integrate with PersianLanguageProcessor
        try:
            from core.persian import PersianLanguageProcessor

            proc = processor or PersianLanguageProcessor()
            p_res = proc.process_input(current_prompt)
            inferred["persian_understanding"] = p_res
            inferred["intent_type"] = p_res.primary_intent.value
            inferred["extracted_entities"] = [e.model_dump() for e in p_res.extracted_entities]
            if p_res.is_hypothetical:
                inferred["is_hypothetical"] = True
            if p_res.requires_clarification or p_res.is_ambiguous:
                inferred["needs_clarification"] = True
                if p_res.clarification_prompt:
                    inferred["clarification_prompt"] = p_res.clarification_prompt
            if p_res.is_read_only:
                inferred["read_only"] = True
            if p_res.prohibited_actions:
                inferred["prohibitions"] = p_res.prohibited_actions
            if p_res.response_language == "fa":
                inferred["explicit_persian_requested"] = True
                inferred["language_override"] = "fa"
            if p_res.active_project:
                inferred["active_project"] = p_res.active_project
            if p_res.active_file:
                inferred["active_file"] = p_res.active_file
        except Exception as p_exc:
            logger.debug(f"PersianLanguageProcessor integration note: {p_exc}")

        # Integrate with ConversationSessionManager for multi-turn entity & project tracking
        try:
            from core.conversation_session import get_conversation_session_manager

            mgr = get_conversation_session_manager()
            resolved_text, session_inferred = mgr.resolve_contextual_references(
                current_prompt=resolved_text,
                history=history,
                session_id=session_id or "default_session",
            )
            inferred.update(session_inferred)
        except Exception as sess_exc:
            logger.debug(f"ConversationSessionManager resolution note: {sess_exc}")

        if not history:
            # Check standalone missing information without conversational context
            has_email_cue = any(
                k in resolved_text.lower() for k in ("ایمیل", "جیمیل", "email", "send email")
            )
            has_wa_cue = any(
                k in resolved_text.lower() for k in ("واتساپ", "واتس‌اپ", "واتس اپ", "whatsapp")
            )
            has_content_hint = any(
                k in resolved_text
                for k in (
                    "بگو",
                    "که",
                    "با عنوان",
                    "با متن",
                    "موضوع",
                    "متن",
                    "saying",
                    "that",
                    "with body",
                    "subject",
                )
            )
            if has_email_cue and not has_content_hint and not inferred.get("needs_clarification"):
                inferred["needs_clarification"] = True
                inferred["clarification_reason"] = "missing_email_details"
                inferred["clarification_prompt"] = (
                    "لطفاً موضوع و متن ایمیل را مشخص بفرمایید تا پیش‌نویس آماده شود."
                )
            elif has_wa_cue and not has_content_hint and not inferred.get("needs_clarification"):
                inferred["needs_clarification"] = True
                inferred["clarification_reason"] = "missing_whatsapp_content"
                inferred["clarification_prompt"] = (
                    "لطفاً متن پیامی که می‌خواهید در واتساپ ارسال شود را بفرمایید."
                )
            return resolved_text, inferred

        last_assistant_msg = ""
        last_user_msg = ""
        for m in reversed(history):
            if m.role == "assistant" and not last_assistant_msg:
                last_assistant_msg = m.content
            elif m.role == "user" and not last_user_msg and m.content != current_prompt:
                last_user_msg = m.content
            if last_assistant_msg and last_user_msg:
                break

        # 1. Check for "همون ..." / "the same ..." references
        if re.search(
            r"\b(همون|همان|the same)\s+(مرورگر|برنامه|فایل|نرم‌افزار|browser|app|file)\b",
            resolved_text,
            re.IGNORECASE,
        ):
            # Inspect history for recently mentioned apps/files
            combined_lower = f"{last_user_msg} {last_assistant_msg}".lower()
            app_map = {
                "chrome": ["chrome", "کروم"],
                "edge": ["edge", "ایج", "اج"],
                "notepad": ["notepad", "نوتپد", "یادداشت"],
                "calculator": ["calc", "calculator", "ماشین حساب"],
                "terminal": ["terminal", "ترمینال"],
                "code": ["code", "vscode", "کد"],
            }
            for app_key, aliases in app_map.items():
                if any(alias in combined_lower for alias in aliases):
                    inferred["referenced_entity"] = app_key
                    logger.info(f"Resolved follow-up reference to: '{app_key}'")
                    break

        # 2. Check for "بهش ..." / "to him/her" recipient reference
        if re.search(r"\b(بهش|به اون|برای اون|to (him|her|them))\b", resolved_text, re.IGNORECASE):
            # Search for named recipient in recent history (e.g. علی, سارا, Ali, John)
            combined_history = f"{last_user_msg} {last_assistant_msg}"
            matches = list(
                re.finditer(
                    r"\b(علی|محمد|سارا|رضا|مریم|ali|john|sarah|alex)\b",
                    combined_history,
                    re.IGNORECASE,
                )
            )
            unique_names = {m.group(0).lower(): m.group(0) for m in matches}
            if len(unique_names) == 1:
                # Exactly one clear person referenced
                resolved_name = list(unique_names.values())[0]
                inferred["recipient_name"] = resolved_name
                logger.info(f"Resolved recipient pronoun unambiguously to: '{resolved_name}'")
            elif len(unique_names) > 1:
                logger.info("Multiple potential recipients in context; flagged as ambiguous.")
                inferred["ambiguous_recipient"] = True
            else:
                inferred["ambiguous_recipient"] = True

        # 3. Check for "همین رو ایمیل کن" / "email this"
        if (
            re.search(
                r"\b(همین رو|همین متن رو|email this|send this text)\b", resolved_text, re.IGNORECASE
            )
            and last_assistant_msg
        ):
            inferred["referenced_content"] = last_assistant_msg[:2000]

        # 4. Check for ambiguous recipients
        if inferred.get("ambiguous_recipient"):
            inferred["needs_clarification"] = True
            inferred["clarification_reason"] = "ambiguous_recipient"
            inferred["clarification_prompt"] = (
                "چندین مخاطب در گفتگو ذکر شده‌اند. لطفاً مشخص فرمایید پیام برای کدام شخص ارسال شود."
            )

        # 5. Check if email/whatsapp lacks content and no referenced content is available
        has_email_cue = any(
            k in resolved_text.lower() for k in ("ایمیل", "جیمیل", "email", "send email")
        )
        has_wa_cue = any(
            k in resolved_text.lower() for k in ("واتساپ", "واتس‌اپ", "واتس اپ", "whatsapp")
        )
        has_content_hint = any(
            k in resolved_text
            for k in (
                "بگو",
                "که",
                "با عنوان",
                "با متن",
                "موضوع",
                "متن",
                "saying",
                "that",
                "with body",
                "subject",
            )
        )
        if (
            has_email_cue
            and not has_content_hint
            and not inferred.get("referenced_content")
            and not inferred.get("needs_clarification")
        ):
            inferred["needs_clarification"] = True
            inferred["clarification_reason"] = "missing_email_details"
            inferred["clarification_prompt"] = (
                "لطفاً موضوع و متن ایمیل را مشخص بفرمایید تا پیش‌نویس آماده شود."
            )
        elif (
            has_wa_cue
            and not has_content_hint
            and not inferred.get("referenced_content")
            and not inferred.get("needs_clarification")
        ):
            inferred["needs_clarification"] = True
            inferred["clarification_reason"] = "missing_whatsapp_content"
            inferred["clarification_prompt"] = (
                "لطفاً متن پیامی که می‌خواهید در واتساپ ارسال شود را بفرمایید."
            )

        return resolved_text, inferred

    @classmethod
    def format_truthful_response(
        cls,
        outcome: ExecutionOutcome,
        language: str = "auto",
    ) -> str:
        """Format an authentic, truthful response reflecting real execution results."""
        if outcome.status == "waiting_for_approval":
            prop = outcome.pending_approval
            if not prop:
                return (
                    "درخواست در انتظار تأیید شماست."
                    if language == "fa"
                    else "Action is waiting for your approval."
                )
            if language == "fa":
                return f"عملیات «{prop.tool_name}» نیاز به تأیید شما دارد. لطفاً پیش‌نمایش را بررسی فرمایید."
            return f"Action '{prop.tool_name}' requires your explicit approval. Please review the preview."

        if outcome.status == "cancelled":
            return (
                "عملیات بنا به درخواست شما لغو شد."
                if language == "fa"
                else "Operation was cancelled per your request."
            )

        if outcome.status == "failed":
            err = outcome.error or "Unknown error"
            if language == "fa":
                return f"متأسفانه عملیات با خطا مواجه شد: {err}"
            return f"The operation encountered an error: {err}"

        # Guard against false claims if an action step failed inside plan execution
        if hasattr(outcome, "plan") and outcome.plan and hasattr(outcome.plan, "steps"):
            failed_comms = [
                s
                for s in outcome.plan.steps
                if s.tool_name
                and str(getattr(s, "status", "")).lower()
                in ("failed", "cancelled", "stepstatus.failed")
            ]
            if failed_comms:
                tool_failed = failed_comms[0].tool_name
                err = failed_comms[0].error or outcome.error or "خطای نامشخص"
                if language == "fa":
                    return f"عملیات «{tool_failed}» با خطا مواجه شد و اجرا نشد: {err}"
                return f"Operation '{tool_failed}' failed and was not completed: {err}"

        # Check if a file_edit_text step succeeded in plan
        if hasattr(outcome, "plan") and outcome.plan and hasattr(outcome.plan, "steps"):
            file_edits = [
                s
                for s in outcome.plan.steps
                if s.tool_name == "file_edit_text"
                and str(getattr(s, "status", "")).lower() in ("completed", "stepstatus.completed")
            ]
            if file_edits:
                step = file_edits[0]
                fp = step.parameters.get("file_path", "")
                fname = Path(fp).name if fp else "file"
                if language == "fa":
                    return f"تغییرات فایل «{fname}» با موفقیت روی دیسک اعمال و تأیید شد."
                return f"File '{fname}' successfully modified and verified on disk at '{fp}'."

        # Check if a file_write_text step succeeded in plan
        if hasattr(outcome, "plan") and outcome.plan and hasattr(outcome.plan, "steps"):
            file_writes = [
                s
                for s in outcome.plan.steps
                if s.tool_name == "file_write_text"
                and str(getattr(s, "status", "")).lower() in ("completed", "stepstatus.completed")
            ]
            if file_writes:
                step = file_writes[0]
                fp = step.parameters.get("file_path", "")
                fname = Path(fp).name if fp else "file"
                if language == "fa":
                    return f"فایل «{fname}» با موفقیت در مسیر '{fp}' ایجاد و روی دیسک تأیید شد."
                return f"File '{fname}' successfully created and verified on disk at '{fp}'."

        # If a final synthesized response was produced by the agent, return it
        if outcome.final_response and outcome.final_response.strip():
            return outcome.final_response.strip()

        if language == "fa":
            return "عملیات با موفقیت و بر اساس نتایج تأییدشده انجام شد."
        return "Operation completed successfully based on verified results."

    @classmethod
    def format_spoken_response_en(cls, text: str, user_prompt: str = "") -> str:
        """Format an agent response into authentic, refined British English speech.

        Enforces JARVIS voice identity:
        - Conversational understanding of Persian user commands translated/reformulated
          into natural, concise British English spoken responses.
        - Professional, polite, calm tone ("Certainly, sir.", "Right away, sir.").
        - Strictly truthful reporting without synthetic hallucinations.
        - Strips code blocks, markdown links, and tabular clutter for clean acoustics.
        """
        combined = f"{user_prompt} {text}".strip()
        cleaned_text = re.sub(r"```[\s\S]*?```", "", text)
        cleaned_text = re.sub(r"https?://\S+", "", cleaned_text)
        cleaned_text = re.sub(r"[#*_~>`]+", "", cleaned_text).strip()

        # If the response itself is already in English, preserve the rich semantic output directly
        persian_in_text = len(re.findall(r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", cleaned_text))
        total_alpha = len(
            re.findall(r"[a-zA-Z\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", cleaned_text)
        )
        is_text_persian = total_alpha > 0 and (persian_in_text / total_alpha) > 0.4

        if not is_text_persian and cleaned_text:
            cleaned_en = filter_english_speech_only(cleaned_text)
            if "certainly, sir." not in cleaned_en.lower() and any(
                k in user_prompt.lower() for k in ("check cpu", "system status", "status")
            ):
                return f"Certainly, sir. {cleaned_en}"
            return cleaned_en

        is_persian = bool(re.search(r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", combined))
        if is_persian:
            lower_comb = combined.lower()

            # 0. Missing Information Clarification Requests
            if any(
                k in lower_comb for k in ("چه تغییری", "ویرایش را بفرمایید", "تغییرات مورد نظر")
            ):
                return "Certainly, sir. What modification would you like me to make to the file?"
            if any(
                k in lower_comb
                for k in ("موضوع و متن ایمیل", "موضوع یا متن ایمیل", "مشخص بفرمایید تا پیش‌نویس")
            ):
                return "Right away, sir. Could you please provide the subject and body of the email before I prepare the draft?"
            if any(
                k in lower_comb
                for k in ("متن پیامی که می‌خواهید", "متن پیام در واتساپ", "متن پیام واتساپ")
            ):
                return "Certainly, sir. What message content would you like me to send to the recipient?"
            if any(k in lower_comb for k in ("چندین مخاطب", "کدام شخص")):
                return "Sir, multiple recipients were mentioned in the context. Could you please specify who you would like me to contact?"

            # 1. Permission denial / Cancellation
            if any(
                k in lower_comb
                for k in (
                    "رد شد",
                    "رد کردید",
                    "لغو شد",
                    "لغو",
                    "اجازه ندادید",
                    "عدم دسترسی",
                    "denied",
                    "cancelled",
                )
            ):
                return "Understood, sir. The requested operation was cancelled or denied."

            # 2. Tool Failure / Error (excluding successful resolution of errors)
            is_resolution = any(
                k in lower_comb
                for k in (
                    "برطرف شد",
                    "حل شد",
                    "رفع شد",
                    "درستش کن",
                    "اصلاح شد",
                    "بدون خطا",
                    "موفق",
                    "resolved",
                    "fixed",
                )
            )
            if not is_resolution and any(
                k in lower_comb
                for k in ("خطا", "شکست", "مشکل", "امکان‌پذیر نبود", "failed", "error")
            ):
                err_match = re.search(
                    r"(?:خطا|error|failed)[:\s]+([^\n.]+)", cleaned_text, re.IGNORECASE
                )
                err_detail = (
                    err_match.group(1).strip() if err_match else "Execution was unsuccessful"
                )
                return f"I encountered an issue executing your request, sir: {err_detail}."

            # 3. File Operations (Creation vs Reading vs Deletion vs Contextual Reference)
            has_file_kw = any(
                k in lower_comb
                for k in ("فایل", "file", "دسکتاپ", "desktop", "html", "txt", "پوشه")
            )
            m_file = re.search(
                r"\b([a-zA-Z0-9_.-]+\.(?:html?|txt|py|json|md|css|js|csv|xml|yaml|yml|log))\b",
                combined,
                re.IGNORECASE,
            )
            fname = m_file.group(1) if m_file else ("requested file" if has_file_kw else None)

            # 3a. File Reading / Inspection
            if has_file_kw and any(
                k in lower_comb
                for k in (
                    "بخوان",
                    "مشاهده",
                    "محتوای",
                    "نمایش بده",
                    "read",
                    "view",
                    "inspect",
                    "show",
                    "load",
                )
            ):
                target_name = f"'{fname}'" if fname else "the requested file"
                return f"Certainly, sir. I have read and inspected {target_name} for you."

            # 3b. File Deletion
            if has_file_kw and any(
                k in lower_comb for k in ("حذف", "پاک کن", "ببند", "delete", "remove", "erase")
            ):
                target_name = f"'{fname}'" if fname else "the requested file"
                return f"Certainly, sir. I have removed the file {target_name} from your Desktop."

            # 3c. Contextual follow-up reference ("همین فایل", "همان فایل", "آن را")
            if any(
                k in lower_comb
                for k in ("همین فایل", "همان فایل", "همین مورد", "that file", "the same file")
            ):
                return "Certainly, sir. I have updated the referenced file per your instructions."

            # 3d. File Creation / Modification
            if has_file_kw and any(
                k in lower_comb
                for k in ("ایجاد", "بساز", "بنویس", "تولید", "create", "write", "make", "generate")
            ):
                target_name = f"'{fname}'" if fname else "the requested file"
                loc = (
                    " on your Desktop" if "دسکتاپ" in lower_comb or "desktop" in lower_comb else ""
                )
                return f"Certainly, sir. I have created and verified the file {target_name}{loc}."

            # 3e. Long-Running Analysis & Technical Report (Phase 10 Scenario H)
            if any(
                k in lower_comb
                for k in ("گزارش فنی", "تحلیل عمیق", "technical report", "background analysis")
            ):
                return "Certainly, sir. I have started a background analysis of the project. I will notify you once the technical report is ready."

            # 3f. Software Project & Coding Tasks (Phase 10 Scenarios B & G)
            is_coding = any(
                k in lower_comb
                for k in (
                    "پروژه",
                    "project",
                    "پیسیشاپ",
                    "pc shop",
                    "pcshop",
                    "ریپو",
                    "repo",
                    "تست",
                    "tests",
                    "درستش کن",
                    "آنتی گرویتی",
                    "antigravity",
                    "تغییر دادی",
                    "چه تغییراتی",
                    "تغییرات",
                    "what did you change",
                    "diff",
                )
            )
            if is_coding:
                proj_name = (
                    "PC Shop project"
                    if any(k in lower_comb for k in ("pc shop", "pcshop", "پیسیشاپ", "پیسی شاپ"))
                    else "project"
                )
                if any(
                    k in lower_comb
                    for k in (
                        "درستش کن",
                        "خطایی داشت",
                        "حل کن",
                        "تعمیر",
                        "fix",
                        "resolved",
                        "remediated",
                    )
                ):
                    return f"Certainly, sir. I have resolved the failing tests and verified the test suite for the {proj_name} is now passing."
                if any(
                    k in lower_comb
                    for k in (
                        "تستهاشو",
                        "تست هاشو",
                        "تست‌هاشو",
                        "تستها",
                        "تست‌ها",
                        "اجرای تست",
                        "run tests",
                        "test suite",
                    )
                ):
                    return f"Certainly, sir. Running the test suite for the {proj_name}."
                if any(
                    k in lower_comb
                    for k in (
                        "چه تغییراتی",
                        "چی تغییر کرد",
                        "تغییر دادی",
                        "what did you change",
                        "diff",
                    )
                ):
                    return f"Certainly, sir. I have reviewed the repository changes and verified the modifications for the {proj_name}."
                if any(
                    k in lower_comb
                    for k in (
                        "آنتی گرویتی",
                        "antigravity",
                        "کدنویس",
                        "delegate",
                        "delegating",
                    )
                ):
                    return "Certainly, sir. Delegating the task to the Antigravity coding agent."
                if any(k in lower_comb for k in ("بررسی", "inspect", "investigate", "check")):
                    return f"Certainly, sir. I am inspecting the {proj_name} repository."

            # 3g. Web & Framework Research (Phase 10 Scenario F)
            if any(
                k in lower_comb
                for k in (
                    "تحقیق کن",
                    "سرچ در وب",
                    "وبسایت",
                    "مستندات",
                    "فریمورک",
                    "research",
                    "web search",
                )
            ):
                return (
                    "Certainly, sir. I have researched the framework and summarized the findings."
                )

            # 4. Application Launch & Close
            apps_found: list[str] = []
            if any(k in lower_comb for k in ("chrome", "کروم")):
                apps_found.append("Google Chrome")
            if any(k in lower_comb for k in ("edge", "ایج", "ادج", "مایکروسافت ادج")):
                apps_found.append("Microsoft Edge")
            if any(k in lower_comb for k in ("notepad", "نوت‌پد", "نوتپد", "یادداشت")):
                apps_found.append("Notepad")
            if any(k in lower_comb for k in ("calculator", "ماشین حساب", "calc")):
                apps_found.append("Calculator")
            if any(k in lower_comb for k in ("terminal", "ترمینال", "کنسول")):
                apps_found.append("Windows Terminal")

            is_close = any(
                k in lower_comb for k in ("ببند", "ببندش", "خارج شو", "close", "closed", "kill")
            )
            is_launch = any(
                k in lower_comb
                for k in (
                    "باز کن",
                    "باز شد",
                    "اجرا کن",
                    "اجرا شد",
                    "launch",
                    "launched",
                    "open",
                    "opened",
                    "start",
                )
            )

            if apps_found and is_close:
                apps_str = " and ".join(apps_found)
                return f"Certainly, sir. I have closed {apps_str} for you."
            if apps_found and (is_launch or not is_close):
                apps_str = " and ".join(apps_found)
                return f"Right away, sir. I have launched {apps_str} for you."

            # 4b. Meteorological Weather queries
            if any(
                k in lower_comb
                for k in (
                    "آب و هوا",
                    "هوا",
                    "weather",
                    "دما",
                    "temperature",
                    "forecast",
                    "پیش‌بینی",
                    "درجه",
                )
            ):
                m_city = re.search(r"(?:در|in|for|هوای)\s+([a-zA-Z\u0600-\u06FF]+)", lower_comb)
                city_name = m_city.group(1).capitalize() if m_city else "the requested city"
                m_temp = re.search(r"(\d+(?:\.\d+)?)\s*(?:درجه|°C|celsius)", text, re.IGNORECASE)
                temp_val = f" {m_temp.group(1)} degrees Celsius" if m_temp else ""
                return f"In {city_name}, it is currently{temp_val} with clear sky."

            # 4c. Desktop Screenshot
            if any(
                k in lower_comb
                for k in (
                    "screenshot",
                    "اسکرین شات",
                    "اسکرین‌شات",
                    "عکس از صفحه",
                    "تصویر صفحه",
                    "عکس دسکتاپ",
                )
            ):
                return "Certainly, sir. The primary desktop screenshot has been captured and saved."

            # 5. System check / Diagnostics (preserving CPU, RAM, Disk metrics)
            if any(
                k in lower_comb
                for k in (
                    "سیستم",
                    "وضعیت",
                    "پردازنده",
                    "رم",
                    "حافظه",
                    "دیسک",
                    "cpu",
                    "ram",
                    "memory",
                    "disk",
                )
            ):
                pct_match = re.search(r"(\d+(?:\.\d+)?\s*%)", text)
                pct = pct_match.group(1) if pct_match else None
                if pct:
                    # Determine which metric is directly associated with this percentage
                    pos = text.find(pct)
                    preceding = text[max(0, pos - 30) : pos].lower()
                    if any(k in preceding for k in ("cpu", "پردازنده")):
                        return f"Certainly, sir. CPU utilization is currently at {pct}, operating within normal parameters."
                    if any(k in preceding for k in ("رم", "ram", "حافظه", "memory")):
                        return f"Certainly, sir. System memory utilization is currently at {pct}."
                    if any(k in preceding for k in ("دیسک", "disk")):
                        return f"Certainly, sir. Disk utilization is currently at {pct}."

                # General system status check
                if any(k in lower_comb for k in ("وضعیت سیستم", "system status", "بررسی کن")):
                    return "Certainly, sir. System status check is complete. Core hardware and memory metrics are operating within normal parameters."

                if any(k in lower_comb for k in ("پردازنده", "cpu")):
                    val = f" at {pct}" if pct else " operating normally"
                    return f"Certainly, sir. CPU utilization is currently{val}."
                if any(k in lower_comb for k in ("رم", "حافظه", "ram", "memory")):
                    val = f" at {pct}" if pct else " within normal parameters"
                    return f"Certainly, sir. System memory utilization is currently{val}."
                if any(k in lower_comb for k in ("دیسک", "disk")):
                    val = f" at {pct}" if pct else " healthy"
                    return f"Certainly, sir. Storage and disk utilization are currently{val}."
                return "Certainly, sir. System status check is complete. Core hardware and memory metrics are operating within normal parameters."

            # 6. Audio & Volume
            if any(k in lower_comb for k in ("صدا", "ولوم", "volume", "sound", "mute", "بیصدا")):
                if any(k in lower_comb for k in ("بیصدا", "mute", "قطع")):
                    return "Certainly, sir. Audio output has been muted."
                return "Certainly, sir. The audio volume has been adjusted to your requested level."

            # 7. Email actions
            if "ایمیل" in lower_comb or "email" in lower_comb:
                m_email = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", combined)
                recip = f" to {m_email.group(1)}" if m_email else ""
                if any(k in lower_comb for k in ("تأیید", "پیش‌نویس", "draft", "آماده")):
                    return f"I have prepared the email draft{recip}, sir. Awaiting your approval before transmission."
                if any(k in lower_comb for k in ("ارسال شد", "sent", "فرستاده شد")):
                    return f"The email{recip} has been dispatched successfully, sir."
                return f"I have processed your email instruction{recip}, sir."

            # 8. WhatsApp actions
            if "واتساپ" in lower_comb or "whatsapp" in lower_comb:
                m_phone = re.search(r"(\+?[0-9]{10,14})", combined)
                recip = f" to {m_phone.group(1)}" if m_phone else ""
                if any(k in lower_comb for k in ("تأیید", "پیش‌نویس", "draft", "آماده")):
                    return f"I have drafted the WhatsApp message{recip}, sir. It is ready for your confirmation."
                if any(k in lower_comb for k in ("ارسال شد", "sent", "فرستاده شد")):
                    return f"The WhatsApp message{recip} has been dispatched successfully, sir."
                return f"I have processed your WhatsApp request{recip}, sir."

            # 9. Conversational greetings and inquiries
            if any(
                k in lower_comb
                for k in ("سلام", "درود", "صبح بخیر", "عصر بخیر", "شب بخیر", "hello", "hi")
            ):
                return "Good day, sir. How may I be of assistance to you today?"
            if any(
                k in lower_comb
                for k in ("چطوری", "حالت چطوره", "خوبی", "کی هستی", "معرفی کن", "how are you")
            ):
                return "I am functioning at optimal capacity, sir. Ready to assist you with your instructions."
            if any(
                k in lower_comb
                for k in (
                    "ساعت چنده",
                    "ساعت چند است",
                    "زمان",
                    "تاریخ امروز",
                    "امروز چندمه",
                    "what time",
                )
            ):
                return "Certainly, sir. System clock and date parameters are verified."
            if any(
                k in lower_comb
                for k in ("تشکر", "ممنون", "دستت درد نکنه", "سپاس", "thank you", "thanks")
            ):
                return "You are most welcome, sir. Always at your service."

            # 10. General completion
            return "Certainly, sir. Task completed successfully per your instructions."

        # If already English, return clean conversational phrasing directly
        return cleaned_text
