"""Persistent Multi-Turn Conversational Session & Context Manager for JARVIS Phase 10.

Maintains cross-turn conversation context, active project and file tracking,
anaphoric reference resolution, intent classification (including hypothetical
discussion vs authorization), and bounded context construction.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from infrastructure.logging import get_logger

if TYPE_CHECKING:
    from memory.base import ConversationMessage

logger = get_logger("core.conversation_session")


class IntentType(StrEnum):
    """Categorized user intent for conversational requests."""

    INFORMATION_QUERY = "information_query"
    TASK_PLAN_REQUEST = "task_plan_request"
    ACTION_EXECUTION = "action_execution"
    ACTION_AUTHORIZATION = "action_authorization"
    HYPOTHETICAL_DISCUSSION = "hypothetical_discussion"
    CLARIFICATION_ANSWER = "clarification_answer"
    INTERRUPTION_OR_CORRECTION = "interruption_or_correction"
    GREETING_OR_CLOSING = "greeting_or_closing"
    UNKNOWN = "unknown"


@dataclass
class ConversationEntity:
    """Discrete real-world entity tracked across conversation turns."""

    entity_type: str  # "project", "file", "app", "person", "task", "topic", "url"
    name: str
    value: Any = None
    confidence: float = 1.0
    turn_index: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationSessionContext:
    """Rich conversational state maintained across multiple turns of interaction."""

    session_id: str
    active_project_name: str | None = None
    active_project_path: Path | None = None
    active_file_path: Path | None = None
    active_app_name: str | None = None
    active_topic: str = "general"
    active_task_id: str | None = None
    last_user_goal: str = ""
    last_assistant_response: str = ""
    turn_count: int = 0
    language_override: str | None = None  # Temporary "fa" or "en" override
    entities: dict[str, list[ConversationEntity]] = field(default_factory=dict)
    pending_clarification: dict[str, Any] | None = None
    last_intent: IntentType = IntentType.UNKNOWN
    is_hypothetical: bool = False
    last_created_directory_path: Path | None = None
    last_created_directory_name: str | None = None
    last_target_directory_type: str | None = None

    @property
    def language_preference(self) -> str:
        return self.language_override or "en"

    @language_preference.setter
    def language_preference(self, val: str) -> None:
        self.language_override = val

    def add_entity(
        self, entity_type: str, name: str, value: Any = None, confidence: float = 1.0
    ) -> None:
        """Register or update an entity in the current session context."""
        ent = ConversationEntity(
            entity_type=entity_type,
            name=name,
            value=value,
            confidence=confidence,
            turn_index=self.turn_count,
            timestamp=time.time(),
        )
        if entity_type not in self.entities:
            self.entities[entity_type] = []
        # Keep most recent entity of each name first
        self.entities[entity_type] = [
            e for e in self.entities[entity_type] if e.name.lower() != name.lower()
        ]
        self.entities[entity_type].insert(0, ent)
        # Cap to 20 entities per type
        self.entities[entity_type] = self.entities[entity_type][:20]

    def get_latest_entity(self, entity_type: str) -> ConversationEntity | None:
        """Retrieve the most recently mentioned entity of a given type."""
        lst = self.entities.get(entity_type, [])
        return lst[0] if lst else None


class ConversationSessionManager:
    """Coordinates persistent conversation sessions, entity resolution, and intent analysis."""

    _instance: ConversationSessionManager | None = None

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, ConversationSessionContext] = {}
        self._registered_projects: dict[str, Path] = {}
        self._init_registered_projects()

    @classmethod
    def get_instance(cls) -> ConversationSessionManager:
        if cls._instance is None:
            cls._instance = ConversationSessionManager()
        return cls._instance

    def _init_registered_projects(self) -> None:
        """Discover authorized workspaces and known project roots."""
        try:
            settings = get_settings()
            # Current JARVIS project
            current_root = Path.cwd().resolve()
            self._registered_projects["jarvis"] = current_root

            # Configured workspaces
            for ws in settings.antigravity_authorized_workspaces:
                p = Path(ws).resolve()
                if p.exists() and p.is_dir():
                    self._registered_projects[p.name.lower()] = p

            # Inspect desktop/parent directories for common projects if authorized
            parent_ai = current_root.parent
            if parent_ai.exists() and parent_ai.is_dir():
                try:
                    for child in parent_ai.iterdir():
                        if child.is_dir() and (child / ".git").exists():
                            self._registered_projects[child.name.lower()] = child.resolve()
                except Exception:
                    pass
        except Exception as exc:
            logger.debug(f"Project discovery initialization notice: {exc}")

    def register_project(self, name: str, path: str | Path) -> None:
        """Explicitly register a named project in the project catalog."""
        with self._lock:
            p = Path(path).resolve()
            self._registered_projects[name.strip().lower()] = p
            logger.info(f"Registered project '{name}' at '{p}'")

    def list_registered_projects(self) -> dict[str, str]:
        with self._lock:
            return {k: str(v) for k, v in self._registered_projects.items()}

    def get_or_create_session(self, session_id: str) -> ConversationSessionContext:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationSessionContext(session_id=session_id)
            return self._sessions[session_id]

    get_session = get_or_create_session

    def track_entity(self, session_id: str, entity_type: str, name: str, value: Any = None) -> None:
        """Explicitly track or update an entity in the session context."""
        ctx = self.get_or_create_session(session_id)
        ctx.add_entity(entity_type=entity_type, name=name, value=value)
        if entity_type == "project":
            ctx.active_project_name = name
            if isinstance(value, dict) and "path" in value:
                ctx.active_project_path = Path(str(value["path"]))
            elif isinstance(value, (str, Path)):
                ctx.active_project_path = Path(str(value))

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def classify_intent(self, prompt: str) -> tuple[IntentType, bool]:
        """Classify user intent and determine whether request is hypothetical discussion vs real action.

        Returns:
            (IntentType, is_hypothetical)
        """
        norm = prompt.strip().lower()

        # 1. Hypothetical discussion detection ("what if", "can we theoretically", "فرض کن", "اگر ... چه می‌شود")
        hypothetical_patterns = [
            r"\b(what\s+if|suppose|hypothetically|theoretically|if\s+we\s+were\s+to|could\s+we\s+potentially)\b",
            r"(?:فرض\s*(?:کن|کنیم|کنید|کردیم)?|اگر\s*بخواهیم|اگه\s*بشه|به\s*صورت\s*فرضی|نظری|چه\s*اتفاقی\s*می[‌\s]*افته)",
        ]
        is_hypothetical = any(re.search(p, norm, re.IGNORECASE) for p in hypothetical_patterns)
        if is_hypothetical:
            return IntentType.HYPOTHETICAL_DISCUSSION, True

        # 2. Interruption or correction ("Wait, I meant...", "صبر کن", "نه منظورم این نبود")
        correction_patterns = [
            r"^(?:wait|stop|hold\s+on|cancel\s+that|no\s*,?\s*i\s+meant|not\s+that)\b",
            r"^(?:صبر\s*کن|وایسا|نه\s*منظورم|نه\s*اون\s*نه|دست نگه دار)\b",
        ]
        if any(re.search(p, norm, re.IGNORECASE) for p in correction_patterns):
            return IntentType.INTERRUPTION_OR_CORRECTION, False

        # 3. Explicit Approval / Authorization ("بله تایید میکنم", "approve", "yes proceed")
        approval_patterns = [
            r"^(?:approve|yes\s*,?\s*proceed|confirm|authorize|go\s+ahead)\b",
            r"^(?:تایید\s*میکنم|بله\s*انجام\s*بده|ارسال\s*کن|موافقم|اجرا\s*کن)\b",
        ]
        if any(re.search(p, norm, re.IGNORECASE) for p in approval_patterns):
            return IntentType.ACTION_AUTHORIZATION, False

        # 4. Planning requests ("یک برنامه ریزی کن برای", "how should we approach", "plan out")
        plan_patterns = [
            r"\b(plan\s+out|how\s+should\s+we|prepare\s+a\s+plan|break\s+down\s+the\s+task)\b",
            r"\b(برنامه‌ریزی\s*کن|مراحل\s*کار\s*رو\s*بگو|نقشه\s*راه)\b",
        ]
        if any(re.search(p, norm, re.IGNORECASE) for p in plan_patterns):
            return IntentType.TASK_PLAN_REQUEST, False

        # 5. Information queries ("چرا", "how", "what is", "وضعیت", "status", "explain")
        info_patterns = [
            r"^(?:why|how|what\s+is|explain|describe|status|check)\b",
            r"^(?:چرا|چطور|چگونه|وضعیت|توضیح\s*بده|بررسی\s*کن|علت)\b",
        ]
        if any(re.search(p, norm, re.IGNORECASE) for p in info_patterns):
            return IntentType.INFORMATION_QUERY, False

        # 6. Action Execution (Default for imperative tool instructions)
        return IntentType.ACTION_EXECUTION, False

    def resolve_contextual_references(
        self,
        current_prompt: str,
        history: list[ConversationMessage],
        session_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """Resolve cross-turn anaphora, entity references, active projects, and language overrides.

        Examples:
        - "پروژه پیسیشاپ رو بررسی کن" -> binds active_project = "pc shop"
        - "حالا تستهاشو اجرا کن" -> binds "تستهاشو" to "pc shop" test suite
        - "اگه خطایی داشت درستش کن" -> binds "درستش کن" to "pc shop" bug fix
        - "اون فایل رو تغییر بده" -> asks what change if modification details missing
        """
        with self._lock:
            session = self.get_or_create_session(session_id)
            session.turn_count += 1
            session.last_user_goal = current_prompt

            resolved_text = current_prompt.strip()
            inferred: dict[str, Any] = {}

            # Classify intent & hypothetical flag
            intent, is_hypo = self.classify_intent(resolved_text)
            session.last_intent = intent
            session.is_hypothetical = is_hypo
            inferred["intent"] = intent.value
            inferred["intent_type"] = intent.value
            inferred["is_hypothetical"] = is_hypo

            # 0a. Check pending clarification for folder name
            if (
                session.pending_clarification
                and session.pending_clarification.get("type") == "folder_name"
            ):
                dest = session.pending_clarification.get("destination", "Desktop")
                clean_name = resolved_text.strip().strip("\"'«»")
                m_called = re.search(
                    r'(?:call\s+it|name\s+it|named|called|به\s*اسم|به\s*نام|با\s*نام)\s+["\'«»]?([^"\'«»\n]+)["\'«»]?',
                    clean_name,
                    re.IGNORECASE,
                )
                if m_called:
                    clean_name = m_called.group(1).strip()
                if len(clean_name) > 0 and not any(
                    k in clean_name.lower() for k in ("cancel", "nevermind", "بیخیال", "لغو")
                ):
                    session.pending_clarification = None
                    resolved_text = f"Create a folder on {dest} called {clean_name}"
                    inferred["resolved_folder_name"] = clean_name
                    inferred["resolved_destination"] = dest
                    logger.info(
                        f"Resolved pending folder name clarification: '{clean_name}' on {dest}"
                    )

            # 0b. Check for destination correction ("No, I meant Documents", "روی دسکتاپ نه، تو داکیومنت", "نه منظورم داکیومنتس بود")
            dest_correction_patterns = [
                r"\b(?:no,?\s+)?(?:i\s+meant|in|on)\s+(documents?|desktop|downloads?)\b",
                r"(?:نه|نه\s*منظورم|روی|توی|در)\s*(داکیومنت|دسکتاپ|دانلود|دانلودها|اسناد)",
            ]
            for pat in dest_correction_patterns:
                m_corr = re.search(pat, resolved_text, re.IGNORECASE)
                if m_corr:
                    matched_kw = m_corr.group(1).lower()
                    target_dest = (
                        "Documents"
                        if any(k in matched_kw for k in ("doc", "داکیومنت", "اسناد"))
                        else (
                            "Downloads"
                            if any(k in matched_kw for k in ("download", "دانلود"))
                            else "Desktop"
                        )
                    )
                    if (
                        session.pending_clarification
                        and session.pending_clarification.get("type") == "folder_name"
                    ):
                        session.pending_clarification["destination"] = target_dest
                        resolved_text = f"Create a folder on {target_dest}"
                        inferred["destination_correction"] = target_dest
                        break
                    elif session.last_created_directory_name:
                        resolved_text = f"Create a folder in {target_dest} called {session.last_created_directory_name}"
                        inferred["destination_correction"] = target_dest
                        logger.info(
                            f"Resolved destination correction to '{target_dest}' for folder '{session.last_created_directory_name}'"
                        )
                        break

            # 0c. Check for anaphoric nested folder creation ("Put another folder inside it called Projects")
            nested_cues = (
                "inside it",
                "inside that folder",
                "in it",
                "in that folder",
                "inside the project",
                "in the project",
                "inside project",
                "in project",
                "توش",
                "داخلش",
                "توی اون",
                "درون آن",
                "توی همین پوشه",
                "توی پوشه قبلی",
                "توی همون پوشه",
                "داخل پروژه",
                "توی پروژه",
            )
            has_nested = any(c in resolved_text.lower() for c in nested_cues)
            is_folder_req = any(
                k in resolved_text.lower()
                for k in ("folder", "directory", "پوشه", "فولدر", "دایرکتوری")
            )
            target_parent = (
                session.active_project_path
                if (
                    (
                        "project" in resolved_text.lower()
                        or "پروژه" in resolved_text.lower()
                        or not session.last_created_directory_path
                    )
                    and session.active_project_path
                )
                else session.last_created_directory_path
            )
            if has_nested and is_folder_req and target_parent:
                child_name = ""
                m_sub = re.search(
                    r'(?:called|named|به\s*نام|به\s*اسم|با\s*نام)\s+["\'«»]?([^"\'«»\n]+)["\'«»]?',
                    resolved_text,
                    re.IGNORECASE,
                )
                if m_sub:
                    cand = m_sub.group(1).strip().rstrip(".,;:")
                    cand = re.split(
                        r"\b(inside|in|on|at|توی|روی|در|داخل)\b", cand, flags=re.IGNORECASE
                    )[0].strip()
                    child_name = cand
                elif '"' in resolved_text or "'" in resolved_text:
                    parts = re.split(r'["\']', resolved_text)
                    if len(parts) > 1 and parts[1].strip():
                        child_name = parts[1].strip()

                if child_name:
                    resolved_text = f"Create a directory at {target_parent} called {child_name}"
                    inferred["parent_directory_path"] = str(target_parent)
                    inferred["resolved_child_folder"] = child_name
                    logger.info(
                        f"Resolved nested folder creation inside '{target_parent}' called '{child_name}'"
                    )

            # 0d. Check for folder opening anaphora ("Open that folder", "اون پوشه رو باز کن")
            if (
                re.search(r"\b(open\s+(?:that|the|this)\s+folder)\b", resolved_text, re.IGNORECASE)
                or re.search(
                    r"(?:اون\s*پوشه|همون\s*پوشه|این\s*پوشه)\s*رو\s*باز\s*کن", resolved_text
                )
            ) and session.last_created_directory_path:
                resolved_text = f"Open folder {session.last_created_directory_path}"
                inferred["file_path"] = str(session.last_created_directory_path)
                inferred["resolved_folder_open"] = str(session.last_created_directory_path)

            # 0e. Check for folder name correction or rename ("Actually, call it Backend instead", "نه، اسمشو بگذار Backend")
            rename_cues = [
                r"\b(?:actually,?\s+)?(?:call|name)\s+it\s+[\"']?([^\"'\n]+)[\"']?\s+instead\b",
                r"\b(?:actually,?\s+)?rename\s+it\s+to\s+[\"']?([^\"'\n]+)[\"']?\b",
                r"(?:نه|اصلا|در واقع|به جای اون)?\s*(?:اسمشو|نامش را|اسمش رو)\s*(?:بگذار|بذار|تغییر بده به)\s+[\"\'«»]?([^\"\'«»\n]+)[\"\'«»]?",
            ]
            for pat in rename_cues:
                m_ren = re.search(pat, resolved_text, re.IGNORECASE)
                if m_ren:
                    new_folder_name = m_ren.group(1).strip().rstrip(".,;:")
                    if session.last_created_directory_path:
                        parent_dir = session.last_created_directory_path.parent
                        resolved_text = f"Rename directory at {session.last_created_directory_path} to {new_folder_name}"
                        inferred["rename_source"] = str(session.last_created_directory_path)
                        inferred["rename_target"] = str(parent_dir / new_folder_name)
                        inferred["resolved_folder_name"] = new_folder_name
                        logger.info(
                            f"Resolved directory rename correction from '{session.last_created_directory_path}' to '{new_folder_name}'"
                        )
                        break
                    elif session.active_project_path:
                        resolved_text = f"Create a directory at {session.active_project_path} called {new_folder_name}"
                        inferred["parent_directory_path"] = str(session.active_project_path)
                        inferred["resolved_folder_name"] = new_folder_name
                        logger.info(
                            f"Resolved directory correction inside active project '{session.active_project_path}' called '{new_folder_name}'"
                        )
                        break

            # Check explicit language override request ("به فارسی بگو", "explain in English")
            if re.search(
                r"\b(به\s+فارسی\s+بگو|فارسی\s+توضیح\s+بده|explain\s+(?:that\s+)?in\s+persian)\b",
                resolved_text,
                re.IGNORECASE,
            ):
                session.language_override = "fa"
                inferred["language_override"] = "fa"
                logger.info(
                    f"Session {session_id}: Temporary language override switched to Persian."
                )
            elif re.search(
                r"\b(به\s+انگلیسی\s+بگو|in\s+english|switch\s+(?:back\s+)?to\s+english|back\s+to\s+english)\b",
                resolved_text,
                re.IGNORECASE,
            ):
                session.language_override = "en"
                inferred["language_override"] = "en"
                logger.info(f"Session {session_id}: Language switched back to English.")
            elif session.language_override:
                inferred["language_override"] = session.language_override

            # 1. Project Reference Detection & Resolution
            norm_lower = resolved_text.lower()
            detected_project: str | None = None
            detected_project_path: Path | None = None

            try:
                from core.files.project_resolver import get_project_resolver

                proj_resolver = get_project_resolver()
                resolved_p = proj_resolver.resolve_project(resolved_text)
                if resolved_p:
                    detected_project = resolved_p.name
                    detected_project_path = resolved_p.path
            except Exception as e:
                logger.debug(f"Project resolution lookup error: {e}")

            if not detected_project:
                # Check known project names
                project_keywords = {
                    "pc shop": ["pc shop", "pcshop", "پیسیشاپ", "پی سی شاپ", "فروشگاه کامپیوتر"],
                    "document processing": [
                        "document processing",
                        "doc processing",
                        "پردازش سند",
                        "داکیومنت",
                    ],
                    "jarvis": ["jarvis", "جارویس", "دستیار"],
                }
                for p_name in self._registered_projects:
                    if p_name not in project_keywords:
                        project_keywords[p_name] = [p_name]

                for canon_name, aliases in project_keywords.items():
                    if any(alias in norm_lower for alias in aliases):
                        detected_project = canon_name
                        if canon_name in self._registered_projects:
                            detected_project_path = self._registered_projects[canon_name]
                        break

            if detected_project:
                display_name = detected_project
                session.active_project_name = display_name
                session.active_project_path = detected_project_path
                session.add_entity("project", display_name, value=detected_project_path)
                inferred["resolved_project"] = display_name
                inferred["active_project"] = display_name
                inferred["project_path"] = (
                    str(detected_project_path) if detected_project_path else None
                )
                inferred["active_project_path"] = inferred["project_path"]
                logger.info(
                    f"Resolved explicit project: '{display_name}' (path={detected_project_path})"
                )
            else:
                # 2. Check for anaphoric project references ("its tests", "تستهاشو", "پروژه‌اش", "درستش کن", "open it in VS Code", "بازش کن")
                has_anaphora = any(
                    re.search(p, resolved_text, re.IGNORECASE)
                    for p in (
                        r"\b(its\s+(?:tests?|code|backend|repo)|check\s+it|fix\s+it|open\s+it(?:\s+in\s+[a-zA-Z0-9_\s]+)?)\b",
                        r"(?:تست[‌\s]*هاشو|کدشو|درستش\s*کن|بررسیش\s*کن|همون\s*پروژه|پروژه‌اش|پروژش|بازش\s*کن|توی\s+.+?\s*بازش\s*کن)",
                    )
                )
                if has_anaphora and session.active_project_name:
                    inferred["resolved_project"] = session.active_project_name
                    inferred["active_project"] = session.active_project_name
                    inferred["project_path"] = (
                        str(session.active_project_path) if session.active_project_path else None
                    )
                    inferred["active_project_path"] = inferred["project_path"]
                    inferred["anaphoric_reference_resolved"] = True
                    logger.info(
                        f"Resolved anaphoric reference to active project: '{session.active_project_name}'"
                    )
                    # If goal is "open it in <editor>", enrich the goal text
                    if re.search(r"\bopen\s+it\b", resolved_text, re.IGNORECASE):
                        resolved_text = re.sub(
                            r"\bopen\s+it\b",
                            f"open {session.active_project_name} project",
                            resolved_text,
                            flags=re.IGNORECASE,
                        )
                    elif re.search(r"بازش\s*کن", resolved_text):
                        resolved_text = re.sub(
                            r"بازش\s*کن",
                            f"پروژه {session.active_project_name} رو باز کن",
                            resolved_text,
                        )

            # 3. Check for specific application references
            app_map = {
                "calculator": ["calculator", "calc", "ماشین حساب"],
                "notepad": ["notepad", "نوتپد", "نوت‌پد", "یادداشت"],
                "chrome": ["chrome", "کروم", "گوگل کروم"],
                "edge": ["edge", "ایج", "مایکروسافت ایج"],
                "terminal": ["terminal", "ترمینال", "powershell", "cmd"],
                "code": ["code", "vscode", "وی اس کد", "کد"],
            }
            for app_key, aliases in app_map.items():
                if any(alias in norm_lower for alias in aliases):
                    session.active_app_name = app_key
                    session.add_entity("app", app_key)
                    inferred["resolved_app"] = app_key
                    break

            # 4. Check for file path references
            m_file = re.search(
                r"\b([a-zA-Z0-9_.-]+\.(?:html?|txt|py|json|md|css|js|csv|xml|yaml|yml|log))\b",
                resolved_text,
                re.IGNORECASE,
            )
            if m_file:
                fname = m_file.group(1)
                session.add_entity("file", fname)
                inferred["resolved_filename"] = fname

            return resolved_text, inferred

    def build_bounded_context(
        self,
        session_id: str,
        history: list[ConversationMessage],
        max_turns: int = 6,
        max_chars: int = 3000,
    ) -> str:
        """Construct bounded, relevant recent history without dumping entire unbounded transcript."""
        if not history:
            return ""

        recent_msgs = history[-max_turns:]
        formatted_lines: list[str] = ["[CONVERSATION CONTEXT]"]

        total_chars = len(formatted_lines[0])
        for m in recent_msgs:
            role_tag = "User" if m.role == "user" else "JARVIS"
            content_snippet = m.content.strip()
            if len(content_snippet) > 400:
                content_snippet = content_snippet[:400] + "..."
            line = f"{role_tag}: {content_snippet}"
            if total_chars + len(line) + 1 > max_chars:
                break
            formatted_lines.append(line)
            total_chars += len(line) + 1

        formatted_lines.append("[END CONVERSATION CONTEXT]")
        return "\n".join(formatted_lines)


_session_manager_instance: ConversationSessionManager | None = None


def get_conversation_session_manager() -> ConversationSessionManager:
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = ConversationSessionManager.get_instance()
    return _session_manager_instance
