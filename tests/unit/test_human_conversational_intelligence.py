"""Unit tests for JARVIS Human-Level Conversational Intelligence & Memory Processing."""

from pathlib import Path

import pytest

from core.memory.conversational_memory import (
    ConversationalMemoryProcessor,
    MemoryActionType,
)
from core.memory.personal_store import PersonalStore


@pytest.fixture
def memory_proc(tmp_path: Path) -> ConversationalMemoryProcessor:
    store = PersonalStore(db_path=tmp_path / "test_conv_mem.db")
    return ConversationalMemoryProcessor(store=store)


class TestConversationalMemoryStore:
    def test_remember_name_english(self, memory_proc: ConversationalMemoryProcessor):
        res = memory_proc.process("remember that my name is Arad")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        assert res.entity_type == "profile"
        assert res.value == "Arad"
        assert "Arad" in res.response_text
        assert memory_proc.store.get_profile_attribute("user_name") == "Arad"

    def test_remember_name_persian(self, memory_proc: ConversationalMemoryProcessor):
        res = memory_proc.process("یادت باشه اسمم آراد هست")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        assert memory_proc.store.get_profile_attribute("user_name") == "آراد"

    def test_remember_friend_occupation_english(self, memory_proc: ConversationalMemoryProcessor):
        res = memory_proc.process("my friend Ali is a graphic designer")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        assert res.entity_type == "person"
        assert res.subject == "Ali"
        assert "graphic designer" in res.value
        assert "graphic designer" in res.response_text
        person = memory_proc.store.get_person("Ali")
        assert person is not None
        assert person.occupation == "graphic designer"

    def test_remember_friend_occupation_persian(self, memory_proc: ConversationalMemoryProcessor):
        res = memory_proc.process("دوستم علی طراح گرافیک است")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        person = memory_proc.store.get_person("علی")
        assert person is not None
        assert "طراح گرافیک" in person.occupation

    def test_remember_preferred_coding_editor_english(
        self, memory_proc: ConversationalMemoryProcessor
    ):
        res = memory_proc.process("my preferred coding environment is VS Code")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        assert res.entity_type == "preference"
        assert "Visual Studio Code" in res.value
        assert (
            memory_proc.store.get_preference("coding", "preferred_editor") == "Visual Studio Code"
        )

    def test_remember_preferred_coding_editor_persian(
        self, memory_proc: ConversationalMemoryProcessor
    ):
        res = memory_proc.process("محیط کدنویسی من Cursor هست")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.STORE
        assert memory_proc.store.get_preference("coding", "preferred_editor") == "Cursor"


class TestConversationalMemoryQuery:
    def test_query_name_truthful(self, memory_proc: ConversationalMemoryProcessor):
        memory_proc.store.set_profile_attribute("user_name", "Arad")
        res_en = memory_proc.process("what is my name?")
        assert res_en.is_memory_command is True
        assert res_en.action_type == MemoryActionType.QUERY
        assert "Your name is Arad, sir." in res_en.response_text

        res_fa = memory_proc.process("اسم من چیه؟", is_persian_response=True)
        assert res_fa.is_memory_command is True
        assert "نام شما Arad است." in res_fa.response_text

    def test_query_unrecorded_name_honest(self, memory_proc: ConversationalMemoryProcessor):
        res = memory_proc.process("what is my name?")
        assert res.is_memory_command is True
        assert "I do not have your name recorded" in res.response_text

    def test_query_friend_occupation(self, memory_proc: ConversationalMemoryProcessor):
        memory_proc.store.add_or_update_person("Ali", "friend", "graphic designer")
        res = memory_proc.process("who is Ali?")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.QUERY
        assert "Ali is your friend and works as a graphic designer" in res.response_text

    def test_query_friend_occupation_persian_alias(
        self, memory_proc: ConversationalMemoryProcessor
    ):
        memory_proc.store.add_or_update_person("Ali", "friend", "graphic designer")
        res = memory_proc.process("دوستم علی چه کاره است؟")
        assert res.is_memory_command is True
        assert "Ali is your friend and works as a graphic designer" in res.response_text

    def test_query_unknown_person_no_hallucination(
        self, memory_proc: ConversationalMemoryProcessor
    ):
        res = memory_proc.process("who is Sarah?")
        assert res.is_memory_command is True
        assert "I do not have any record of Sarah" in res.response_text

    def test_query_what_do_you_know_about_me(self, memory_proc: ConversationalMemoryProcessor):
        memory_proc.store.set_profile_attribute("user_name", "Arad")
        memory_proc.store.set_preference("coding", "preferred_editor", "Cursor")
        memory_proc.store.add_or_update_person("Ali", "friend", "graphic designer")

        res = memory_proc.process("what do you know about me?")
        assert res.is_memory_command is True
        assert "Arad" in res.response_text
        assert "Cursor" in res.response_text
        assert "Ali" in res.response_text


class TestConversationalMemoryForget:
    def test_forget_person(self, memory_proc: ConversationalMemoryProcessor):
        memory_proc.store.add_or_update_person("Ali", "friend", "graphic designer")
        res = memory_proc.process("forget about Ali")
        assert res.is_memory_command is True
        assert res.action_type == MemoryActionType.FORGET
        assert memory_proc.store.get_person("Ali") is None
        assert "removed Ali" in res.response_text

    def test_forget_person_persian(self, memory_proc: ConversationalMemoryProcessor):
        memory_proc.store.add_or_update_person("Ali", "friend", "graphic designer")
        res = memory_proc.process("فراموش کن که علی گرافیسته")
        assert res.is_memory_command is True
        assert memory_proc.store.get_person("Ali") is None
