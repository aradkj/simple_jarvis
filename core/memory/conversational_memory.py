"""Conversational Memory Processor for JARVIS.

Recognizes natural language memory commands (store, query, forget) in both
English and Persian, performs structured extraction, executes updates with
conflict resolution, and produces accurate, truthful conversational responses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from core.memory.personal_store import PersonalStore
from infrastructure.logging import get_logger

logger = get_logger("memory.conversational_memory")


class MemoryActionType(StrEnum):
    """Categorization of conversational memory operations."""

    STORE = "store"
    QUERY = "query"
    FORGET = "forget"
    NONE = "none"


@dataclass
class ConversationalMemoryResult:
    """Outcome of evaluating an input for conversational memory operations."""

    is_memory_command: bool = False
    action_type: MemoryActionType = MemoryActionType.NONE
    entity_type: str = ""  # profile, person, preference, fact
    subject: str = ""
    attribute: str = ""
    value: str = ""
    response_text: str = ""
    executed_successfully: bool = False


class ConversationalMemoryProcessor:
    """Detects, processes, and responds to natural language memory statements and inquiries."""

    def __init__(self, store: PersonalStore | None = None) -> None:
        self.store = store or PersonalStore.get_instance()

    def process(
        self,
        prompt: str,
        is_persian_response: bool = False,
    ) -> ConversationalMemoryResult:
        """Analyze prompt for memory store, query, or forget intents and handle immediately."""
        text = prompt.strip()
        if not text:
            return ConversationalMemoryResult()

        # 1. Try Forget intent first
        forget_res = self._check_forget_intent(text, is_persian_response)
        if forget_res and forget_res.is_memory_command:
            return forget_res

        is_question = bool(
            re.search(
                r"(\?|؟|\b(what|who|where|how|tell me|which|show|list)\b|چیه|چیست|کیه|کیست|کجاست|چیکار|چکاره)",
                text,
                re.IGNORECASE,
            )
        )

        if is_question:
            query_res = self._check_query_intent(text, is_persian_response)
            if query_res and query_res.is_memory_command:
                return query_res
            store_res = self._check_store_intent(text, is_persian_response)
            if store_res and store_res.is_memory_command:
                return store_res
        else:
            store_res = self._check_store_intent(text, is_persian_response)
            if store_res and store_res.is_memory_command:
                return store_res
            query_res = self._check_query_intent(text, is_persian_response)
            if query_res and query_res.is_memory_command:
                return query_res

        return ConversationalMemoryResult()

    # -------------------------------------------------------------------------
    # Memorize / Store Handlers
    # -------------------------------------------------------------------------

    def _check_store_intent(
        self, text: str, is_persian_response: bool
    ) -> ConversationalMemoryResult | None:
        clean = text.strip()
        norm = clean.lower()

        # Pattern: User name
        # English: "remember that my name is Arad", "my name is Arad"
        # Persian: "یادت باشه اسمم آراد هست", "اسم من آراده", "من آرادم"
        name_match_en = re.search(
            r"(?:remember\s+(?:that\s+)?|save\s+(?:that\s+)?)?my\s+name\s+is\s+([A-Z][a-zA-Z0-9_\s]+)",
            clean,
            re.IGNORECASE,
        )
        if name_match_en and any(k in norm for k in ("remember", "my name is")):
            name = name_match_en.group(1).strip().split(".")[0].split(",")[0]
            self.store.set_profile_attribute("user_name", name)
            resp = (
                f"خیلی خوشوقتم {name} جان. این موضوع در حافظه ماندگار ثبت شد."
                if is_persian_response
                else f"Very well, sir. I have committed to memory that your name is {name}."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="profile",
                subject="user",
                attribute="name",
                value=name,
                response_text=resp,
                executed_successfully=True,
            )

        name_match_fa = re.search(
            r"(?:یادت\s+(?:باشه|بمونه)\s+(?:که\s+)?)?(?:اسمم|نام\s+من|اسم\s+من)\s+([^\s.،؟]+)\s*(?:هست|است|بود|باشه|هستم)?",
            clean,
        )
        if name_match_fa and any(k in clean for k in ("اسمم", "نام من", "اسم من", "یادت باشه")):
            raw_name = name_match_fa.group(1).strip()
            name = re.sub(r"[؟?.!,]", "", raw_name).strip()
            # Avoid matching interrogative words like "چیه"
            if name and name not in ("چیه", "چیست", "چی", "کدومه"):
                self.store.set_profile_attribute("user_name", name)
                resp = (
                    f"خیلی عالیه {name} عزیز. نام شما را با کمال میل به خاطر سپردم."
                    if is_persian_response
                    else f"Splendid, sir. I have recorded that your name is {name}."
                )
                return ConversationalMemoryResult(
                    is_memory_command=True,
                    action_type=MemoryActionType.STORE,
                    entity_type="profile",
                    subject="user",
                    attribute="name",
                    value=name,
                    response_text=resp,
                    executed_successfully=True,
                )

        # Pattern: Preferred Coding Editor
        # English: "my preferred coding environment is VS Code", "my favorite editor is Cursor"
        # Persian: "محیط کدنویسی من وی اس کده", "ادیتور مورد علاقه من Cursor هست"
        editor_match_en = re.search(
            r"(?:my\s+(?:preferred|favorite|default)\s+(?:coding\s+(?:environment|editor|ide)|editor|ide)\s+is|i\s+prefer\s+coding\s+in)\s+([a-zA-Z0-9_\s\+]+)",
            clean,
            re.IGNORECASE,
        )
        if editor_match_en:
            editor_raw = editor_match_en.group(1).strip().split(".")[0]
            canon_editor = self._canonicalize_editor(editor_raw)
            self.store.set_preference("coding", "preferred_editor", canon_editor)
            resp = (
                f"محیط کدنویسی ترجیحی شما روی {canon_editor} تنظیم و در حافظه ذخیره شد."
                if is_persian_response
                else f"Understood, sir. I have saved {canon_editor} as your preferred coding environment."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="preference",
                subject="user",
                attribute="preferred_editor",
                value=canon_editor,
                response_text=resp,
                executed_successfully=True,
            )

        editor_match_fa = re.search(
            r"(?:محیط\s+کدنویسی(?:\s+مورد\s+علاقه|\s+ترجیحی)?|ادیتور(?:\s+مورد\s+علاقه)?)\s+(?:من\s+)?([^\s.،]+(?:\s+[^\s.،]+)?)\s*(?:هست|است|باشه|کده|کد است)",
            clean,
        )
        if editor_match_fa and not any(k in clean for k in ("چیه", "چیست")):
            editor_raw = editor_match_fa.group(1).strip()
            canon_editor = self._canonicalize_editor(editor_raw)
            self.store.set_preference("coding", "preferred_editor", canon_editor)
            resp = (
                f"محیط کدنویسی مورد علاقه شما به {canon_editor} به‌روزرسانی شد."
                if is_persian_response
                else f"Very good, sir. I have noted {canon_editor} as your preferred editor."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="preference",
                subject="user",
                attribute="preferred_editor",
                value=canon_editor,
                response_text=resp,
                executed_successfully=True,
            )

        # Pattern: People and Relationships
        # English: "my friend Ali is a graphic designer", "Ali is my friend and a graphic designer", "Sarah is my sister"
        # Persian: "دوستم علی گرافیسته", "دوستم علی طراح گرافیکه", "سارا خواهرمه", "همکارم رضا برنامه‌نویسه"
        rel_match_en = re.search(
            r"my\s+(friend|sister|brother|colleague|coworker|manager|boss|partner|father|mother|cousin)\s+([A-Z][a-zA-Z0-9_]+)\s+is\s+(?:a\s+|an\s+)?([a-zA-Z0-9_\s]+)",
            clean,
            re.IGNORECASE,
        )
        if rel_match_en:
            rel = rel_match_en.group(1).strip().lower()
            name = rel_match_en.group(2).strip()
            occ = rel_match_en.group(3).strip().split(".")[0].split(",")[0]
            self.store.add_or_update_person(name=name, relationship=rel, occupation=occ)
            self.store.add_fact(subject=name, predicate="relationship", object_val=rel)
            self.store.add_fact(subject=name, predicate="works_as", object_val=occ)
            resp = (
                f"اطلاعات {name} ({rel} شما، با تخصص {occ}) با موفقیت در حافظه ثبت شد."
                if is_persian_response
                else f"Understood, sir. I have recorded that your {rel} {name} is a {occ}."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="person",
                subject=name,
                attribute=rel,
                value=occ,
                response_text=resp,
                executed_successfully=True,
            )

        # Persian: دوستم علی گرافیسته / دوستم علی طراح گرافیکه / دوستم علی یک طراح است
        rel_match_fa = re.search(
            r"(دوستم|خواهرم|برادرم|همکارم|مدیرم|هم‌تیمی‌ام|پدرم|مادرم)\s+([^\s.،]+)\s+(.+?)(?:هست|است|بود|باشه|هستش)?$",
            clean,
        )
        if rel_match_fa and not any(k in clean for k in ("چیه", "چیست", "کیه", "چه کاره")):
            rel_word = rel_match_fa.group(1).strip()
            rel_map = {
                "دوستم": "friend",
                "خواهرم": "sister",
                "برادرم": "brother",
                "همکارم": "colleague",
                "مدیرم": "manager",
                "هم‌تیمی‌ام": "teammate",
                "پدرم": "father",
                "مادرم": "mother",
            }
            rel_en = rel_map.get(rel_word, "contact")
            name = rel_match_fa.group(2).strip()
            occ = rel_match_fa.group(3).strip()
            # Clean colloquial suffix e.g. "گرافیسته" -> "طراح گرافیک / گرافیست"
            if occ.endswith("ه"):
                occ = occ[:-1]
            self.store.add_or_update_person(name=name, relationship=rel_en, occupation=occ)
            self.store.add_fact(subject=name, predicate="relationship", object_val=rel_en)
            self.store.add_fact(subject=name, predicate="works_as", object_val=occ)
            resp = (
                f"ثبت شد؛ {name} به عنوان {rel_word} شما ({occ}) در حافظه قرار گرفت."
                if is_persian_response
                else f"Certainly, sir. I have committed to memory that your {rel_en} {name} works as {occ}."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="person",
                subject=name,
                attribute=rel_en,
                value=occ,
                response_text=resp,
                executed_successfully=True,
            )

        # General "Remember that..." / "یادت باشه که..."
        gen_rem_en = re.search(
            r"^(?:please\s+)?(?:remember|don't\s+forget|do\s+not\s+forget)\s+(?:that\s+)?(.+)",
            clean,
            re.IGNORECASE,
        )
        if gen_rem_en:
            fact_statement = gen_rem_en.group(1).strip()
            self.store.add_fact(
                subject="user",
                predicate="note",
                object_val=fact_statement,
                raw_statement=fact_statement,
            )
            resp = (
                "این مورد را در حافظه ثبت کردم."
                if is_persian_response
                else f'Very well, sir. I have committed that to permanent memory: "{fact_statement}".'
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="fact",
                subject="user",
                attribute="note",
                value=fact_statement,
                response_text=resp,
                executed_successfully=True,
            )

        gen_rem_fa = re.search(
            r"^(?:لطفاً\s+)?(?:یادت\s+(?:باشه|بمونه)|فراموش\s+نکن)\s+(?:که\s+)?(.+)",
            clean,
        )
        if gen_rem_fa:
            fact_statement = gen_rem_fa.group(1).strip()
            self.store.add_fact(
                subject="user",
                predicate="note",
                object_val=fact_statement,
                raw_statement=fact_statement,
            )
            resp = (
                f"حتماً، این مورد را در حافظه به خاطر سپردم: «{fact_statement}»."
                if is_persian_response
                else f'Understood, sir. I have saved that fact to memory: "{fact_statement}".'
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.STORE,
                entity_type="fact",
                subject="user",
                attribute="note",
                value=fact_statement,
                response_text=resp,
                executed_successfully=True,
            )

        return None

    # -------------------------------------------------------------------------
    # Memory Query Handlers (Truthful Recall)
    # -------------------------------------------------------------------------

    def _check_query_intent(
        self, text: str, is_persian_response: bool
    ) -> ConversationalMemoryResult | None:
        clean = text.strip()
        norm = clean.lower()

        # 1. Query: What is my name? / اسم من چیه؟
        if any(
            k in norm
            for k in (
                "what is my name",
                "what's my name",
                "who am i",
                "do you know my name",
            )
        ) or any(
            k in clean for k in ("اسم من چیه", "نام من چیست", "من کیم", "من کی هستم", "اسمم چیه")
        ):
            name = self.store.get_profile_attribute("user_name")
            if name:
                resp = (
                    f"نام شما {name} است." if is_persian_response else f"Your name is {name}, sir."
                )
            else:
                resp = (
                    "هنوز نام شما را در حافظه ذخیره نکرده‌ام. مایلید نامتان را بفرمایید تا ثبت کنم؟"
                    if is_persian_response
                    else "I do not have your name recorded in memory yet, sir. May I ask what it is?"
                )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.QUERY,
                entity_type="profile",
                subject="user",
                attribute="name",
                value=name,
                response_text=resp,
                executed_successfully=True,
            )

        # 2. Query: What is my preferred editor / coding environment?
        # English: "what is my preferred editor", "what coding environment do i use"
        # Persian: "محیط کدنویسی من چیه", "ادیتور مورد علاقه من چیه"
        if any(
            k in norm
            for k in (
                "preferred editor",
                "preferred coding",
                "favorite editor",
                "favorite ide",
                "default editor",
                "what editor do i use",
            )
        ) or any(
            k in clean
            for k in (
                "محیط کدنویسی من چیه",
                "ادیتور من چیه",
                "ادیتور مورد علاقم چیه",
                "محیط برنامه نویسی من",
            )
        ):
            editor = self.store.get_preference("coding", "preferred_editor")
            if editor:
                resp = (
                    f"محیط کدنویسی ترجیحی شما {editor} است."
                    if is_persian_response
                    else f"Your preferred coding environment is {editor}, sir."
                )
            else:
                resp = (
                    "هنوز محیط کدنویسی پیش‌فرضی برای شما ثبت نشده است. گزینه‌هایی مانند VS Code یا Cursor در دسترس هستند."
                    if is_persian_response
                    else "You have not designated a preferred coding environment yet, sir. Would you prefer VS Code, Cursor, or another editor?"
                )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.QUERY,
                entity_type="preference",
                subject="user",
                attribute="preferred_editor",
                value=editor,
                response_text=resp,
                executed_successfully=True,
            )

        # 3. Query: People & Relationships
        # English: "who is Ali?", "what does Ali do?", "what is my friend's name?"
        # Persian: "علی کیه؟", "دوستم علی چه کاره است؟", "دوستم علی چیکار میکنه؟", "اسم دوستم چیه؟"
        person_q_en = re.search(
            r"(?:who\s+is|what\s+does\s+([A-Z][a-zA-Z0-9_]+)\s+do|tell\s+me\s+about\s+([A-Z][a-zA-Z0-9_]+))\b",
            clean,
            re.IGNORECASE,
        )
        if person_q_en:
            target_name = (person_q_en.group(1) or person_q_en.group(2) or "").strip()
            if not target_name:
                m_after = re.search(r"who\s+is\s+([A-Z][a-zA-Z0-9_]+)", clean, re.IGNORECASE)
                if m_after:
                    target_name = m_after.group(1).strip()

            if target_name and target_name.lower() not in ("jarvis", "the", "this", "that"):
                person = self.store.get_person(target_name)
                if person:
                    occ_part = f" and works as a {person.occupation}" if person.occupation else ""
                    resp = (
                        f"{person.name} {person.relationship} شماست{(' و به عنوان ' + person.occupation + ' فعالیت می‌کند') if person.occupation else ''}."
                        if is_persian_response
                        else f"{person.name} is your {person.relationship}{occ_part}, sir."
                    )
                else:
                    resp = (
                        f"اطلاعاتی درباره {target_name} در حافظه ثبت نشده است."
                        if is_persian_response
                        else f"I do not have any record of {target_name} in your personal memory, sir."
                    )
                return ConversationalMemoryResult(
                    is_memory_command=True,
                    action_type=MemoryActionType.QUERY,
                    entity_type="person",
                    subject=target_name,
                    response_text=resp,
                    executed_successfully=True,
                )

        person_q_fa = re.search(
            r"([^\s.،؟]+)\s+(?:کیه|کیست|چه\s+کاره\s+است|چیکار\s+میکنه|چکاره\s+است)",
            clean,
        )
        if person_q_fa:
            target_name = person_q_fa.group(1).strip()
            # Filter out generic question tokens
            if target_name not in ("این", "اون", "آن", "اینجا", "پروژه", "جارویس"):
                # Handle "دوستم علی"
                if target_name == "دوستم" or target_name == "همکارم":
                    # Check next word if available
                    m_pair = re.search(r"(?:دوستم|همکارم)\s+([^\s.،؟]+)", clean)
                    if m_pair:
                        target_name = m_pair.group(1).strip()
                person = self.store.get_person(target_name)
                if person:
                    occ_str = (
                        f" و در زمینه {person.occupation} فعالیت دارند" if person.occupation else ""
                    )
                    resp = (
                        f"{person.name} {person.relationship} شما هستند{occ_str}."
                        if is_persian_response
                        else f"{person.name} is your {person.relationship}{(' and works as a ' + person.occupation) if person.occupation else ''}, sir."
                    )
                else:
                    resp = (
                        f"متأسفانه در حافظه اطلاعی درباره {target_name} پیدا نکردم."
                        if is_persian_response
                        else f"I have no record for {target_name} in your personal memory, sir."
                    )
                return ConversationalMemoryResult(
                    is_memory_command=True,
                    action_type=MemoryActionType.QUERY,
                    entity_type="person",
                    subject=target_name,
                    response_text=resp,
                    executed_successfully=True,
                )

        # 4. Query: What do you know about me? / درباره من چی میدونی؟
        if any(
            k in norm
            for k in (
                "what do you know about me",
                "tell me about myself",
                "what is in your memory",
                "show my profile",
            )
        ) or any(
            k in clean
            for k in (
                "درباره من چی میدونی",
                "از من چی میدونی",
                "چه اطلاعاتی از من داری",
                "پروفایل من چیه",
            )
        ):
            summary = self.store.build_memory_summary_block()
            if summary:
                resp = (
                    f"آنچه در حافظه ماندگار درباره شما ثبت شده است:\n\n{summary}"
                    if is_persian_response
                    else f"Here is what I have recorded in your permanent memory, sir:\n\n{summary}"
                )
            else:
                resp = (
                    "در حال حاضر حافظه شخصی شما خالی است. می‌توانید هر زمان مشخصات، دوستان و ترجیحاتتان را بفرمایید تا ذخیره کنم."
                    if is_persian_response
                    else "Your personal profile and memory are currently blank, sir. Feel free to share your name, friends, or preferences at any time."
                )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.QUERY,
                entity_type="profile",
                subject="user",
                response_text=resp,
                executed_successfully=True,
            )

        return None

    # -------------------------------------------------------------------------
    # Forget / Delete Handlers
    # -------------------------------------------------------------------------

    def _check_forget_intent(
        self, text: str, is_persian_response: bool
    ) -> ConversationalMemoryResult | None:
        clean = text.strip()
        clean.lower()

        # English: "forget that...", "forget about Ali", "delete memory of..."
        m_forget_en = re.search(
            r"^(?:please\s+)?(?:forget\s+(?:that\s+|about\s+)?|delete\s+(?:memory\s+(?:of|about)\s+)?)(.+)",
            clean,
            re.IGNORECASE,
        )
        if m_forget_en:
            target = m_forget_en.group(1).strip()
            # If target names a person
            person = self.store.get_person(target)
            if person:
                self.store.delete_person(target)
                self.store.delete_facts_by_subject(target)
                resp = (
                    f"اطلاعات مربوط به {target} از حافظه پاک شد."
                    if is_persian_response
                    else f"Very well, sir. I have removed {target} from your personal records."
                )
                return ConversationalMemoryResult(
                    is_memory_command=True,
                    action_type=MemoryActionType.FORGET,
                    entity_type="person",
                    subject=target,
                    response_text=resp,
                    executed_successfully=True,
                )

            # Delete facts matching target
            self.store.delete_facts_by_subject(target)
            resp = (
                "اطلاعات مربوطه از حافظه پاک شد."
                if is_persian_response
                else "I have expunged that memory record as requested, sir."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.FORGET,
                entity_type="fact",
                subject=target,
                response_text=resp,
                executed_successfully=True,
            )

        # Persian: "فراموش کن که...", "پاک کن که...", "حذف کن اطلاعات علی رو"
        m_forget_fa = re.search(
            r"^(?:لطفاً\s+)?(?:فراموش\s+کن(?:\s+که)?|پاک\s+کن(?:\s+که)?|حذف\s+کن(?:\s+که)?)\s+(.+)",
            clean,
        )
        if m_forget_fa:
            target = m_forget_fa.group(1).strip()
            # Check if target mentions a person
            words = target.split()
            first_word = words[0] if words else target
            person = self.store.get_person(first_word)
            if person:
                self.store.delete_person(first_word)
                self.store.delete_facts_by_subject(first_word)
                resp = (
                    f"اطلاعات مربوط به {first_word} با موفقیت از حافظه پاک شد."
                    if is_persian_response
                    else f"Records regarding {first_word} have been removed from memory, sir."
                )
                return ConversationalMemoryResult(
                    is_memory_command=True,
                    action_type=MemoryActionType.FORGET,
                    entity_type="person",
                    subject=first_word,
                    response_text=resp,
                    executed_successfully=True,
                )

            self.store.delete_facts_by_subject(target)
            resp = (
                "این مورد از حافظه ماندگار پاک شد."
                if is_persian_response
                else "That entry has been removed from memory, sir."
            )
            return ConversationalMemoryResult(
                is_memory_command=True,
                action_type=MemoryActionType.FORGET,
                entity_type="fact",
                subject=target,
                response_text=resp,
                executed_successfully=True,
            )

        return None

    def _canonicalize_editor(self, raw: str) -> str:
        """Map common editor phrases to canonical display names."""
        r = raw.strip().lower()
        if any(k in r for k in ("vs code", "vscode", "وی اس کد", "وی‌اس‌کد", "code")):
            return "Visual Studio Code"
        if "cursor" in r:
            return "Cursor"
        if any(k in r for k in ("antigravity ide", "آنتی گرویتی")):
            return "Antigravity IDE"
        if "pycharm" in r:
            return "PyCharm"
        if "sublime" in r:
            return "Sublime Text"
        return raw.strip().title()
