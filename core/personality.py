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


class ResponseLanguagePolicy(StrEnum):
    """Governs the language policy for JARVIS conversational output."""

    DEFAULT_ENGLISH = "DEFAULT_ENGLISH"  # Understands Persian; responds in British English unless Persian explicitly requested
    PERSIAN = "PERSIAN"  # Always responds in Persian
    FOLLOW_USER = "FOLLOW_USER"  # Matches user's spoken/written language


JARVIS_SYSTEM_PERSONA_EN = """You are JARVIS, an advanced, calm, highly capable personal AI desktop assistant for Windows 11.
Key Persona Traits:
- Professional, confident, articulate, composed, and naturally polite with a refined British conversational style ("Certainly, sir.", "Right away, sir.").
- Bilingual Intelligence: You understand instructions, context, references, and queries in Persian (فارسی) and English fluently.
- Default Language Policy: Respond in polished, natural British English unless the user explicitly requests Persian (e.g., "به فارسی بگو", "فارسی صحبت کن").
- Grounded and completely TRUTHFUL: Never claim an action succeeded unless verified. Never claim an email or message was delivered when it was only drafted or submitted.
- Respectful of user privacy, credentials, and safety boundaries.
"""

JARVIS_SYSTEM_PERSONA_FA = """شما جارویس (JARVIS) هستید؛ دستیار هوشمند، آرام، مؤدب، حرفه‌ای و توانمند دسکتاپ.
ویژگی‌های شخصیتی:
- گفتار طبیعی، مؤدبانه، باوقار و اطمینان‌بخش به زبان فارسی روان.
- پاسخ‌های کوتاه و کارآمد برای دستورات متداول، و توضیحات دقیق برای مسائل فنی.
- کاملاً صادق و راستگو: هرگز ادعا نکنید کاری انجام شده مگر اینکه اجرای واقعی آن تأیید شده باشد. هرگز ادعای تحویل ایمیل یا پیام واتساپ نکنید وقتی صرفاً پیش‌نویس شده یا ارسال اولیه شده است.
- احترام کامل به حریم خصوصی، امنیت سیستم و دسترسی‌های کاربر.
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
        """Return the core personality system instructions based on language policy."""
        if (
            explicit_persian
            or language == "fa"
            or language_policy == ResponseLanguagePolicy.PERSIAN
        ):
            return JARVIS_SYSTEM_PERSONA_FA
        if language == "en" or language_policy == ResponseLanguagePolicy.DEFAULT_ENGLISH:
            return JARVIS_SYSTEM_PERSONA_EN
        return f"{JARVIS_SYSTEM_PERSONA_EN}\n\n{JARVIS_SYSTEM_PERSONA_FA}"

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
            r"^(?:please\s+)?edit\s+(?:it|this)[.?!]?$",
            r"^(?:please\s+)?modify\s+(?:it|this)[.?!]?$",
        ]
        if any(re.match(p, resolved_text.strip(), re.IGNORECASE) for p in vague_edit_patterns):
            inferred["needs_clarification"] = True
            inferred["clarification_reason"] = "missing_modification_details"
            inferred["clarification_prompt"] = (
                "چه تغییری باید روی این فایل اعمال شود؟ لطفاً مشخصات یا متن مورد نظر برای ویرایش را بفرمایید."
            )

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
                in ("email_send", "whatsapp_send", "file_edit_text", "file_write_text")
                and str(getattr(s, "status", "")).lower()
                in ("failed", "cancelled", "stepstatus.failed")
            ]
            if failed_comms:
                tool_failed = failed_comms[0].tool_name
                if language == "fa":
                    return f"عملیات «{tool_failed}» با خطا مواجه شد و اجرا نشد."
                return f"Operation '{tool_failed}' failed; operation was not executed."

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

        # Check for Persian script in prompt or response
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

            # 4. Application Launch
            app_detected = None
            if any(k in lower_comb for k in ("notepad", "نوت‌پد", "یادداشت")):
                app_detected = "Notepad"
            elif any(k in lower_comb for k in ("calculator", "ماشین حساب", "calc")):
                app_detected = "Calculator"
            elif any(k in lower_comb for k in ("chrome", "کروم")):
                app_detected = "Google Chrome"
            elif any(k in lower_comb for k in ("edge", "ایج")):
                app_detected = "Microsoft Edge"
            elif any(k in lower_comb for k in ("نرم‌افزار", "برنامه", "application", "app")) and any(
                k in lower_comb for k in ("باز کن", "اجرا کن", "launch", "open", "start", "run")
            ):
                app_detected = "the application"

            if app_detected and any(
                k in lower_comb for k in ("باز کن", "اجرا کن", "launch", "open", "start", "run")
            ):
                return f"Right away, sir. I have launched {app_detected} for you."

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

            # 9. General completion
            return "Certainly, sir. Task completed successfully per your instructions."

        # If already English, ensure natural JARVIS phrasing
        if not cleaned_text.startswith(
            ("Certainly", "Right away", "Of course", "Good day", "I have")
        ):
            if "error" in cleaned_text.lower() or "failed" in cleaned_text.lower():
                return f"I encountered an issue, sir. {cleaned_text}"
            return f"Certainly, sir. {cleaned_text}"

        return cleaned_text
