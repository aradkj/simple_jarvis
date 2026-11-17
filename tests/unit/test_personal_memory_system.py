"""Unit tests for JARVIS Permanent Personal Memory System (PersonalStore)."""

from pathlib import Path

import pytest

from core.memory.personal_store import PersonalityConfig, PersonalStore


@pytest.fixture
def temp_store(tmp_path: Path) -> PersonalStore:
    db_file = tmp_path / "test_personal_memory.db"
    return PersonalStore(db_path=db_file)


class TestPersonalProfile:
    def test_set_and_get_profile_attribute(self, temp_store: PersonalStore):
        temp_store.set_profile_attribute("user_name", "Arad")
        assert temp_store.get_profile_attribute("user_name") == "Arad"
        assert temp_store.get_profile_attribute("nonexistent", default="unknown") == "unknown"

    def test_update_profile_attribute(self, temp_store: PersonalStore):
        temp_store.set_profile_attribute("user_name", "Arad")
        temp_store.set_profile_attribute("user_name", "Arad K.")
        assert temp_store.get_profile_attribute("user_name") == "Arad K."

    def test_get_full_profile(self, temp_store: PersonalStore):
        temp_store.set_profile_attribute("user_name", "Arad")
        temp_store.set_profile_attribute("occupation", "AI Engineer")
        profile = temp_store.get_full_profile()
        assert profile["user_name"] == "Arad"
        assert profile["occupation"] == "AI Engineer"

    def test_delete_profile_attribute(self, temp_store: PersonalStore):
        temp_store.set_profile_attribute("nickname", "Neo")
        assert temp_store.delete_profile_attribute("nickname") is True
        assert temp_store.get_profile_attribute("nickname") == ""


class TestPeopleAndRelationships:
    def test_add_and_get_person(self, temp_store: PersonalStore):
        person = temp_store.add_or_update_person(
            name="Ali",
            relationship="friend",
            occupation="graphic designer",
            notes="Works at Design Studio",
        )
        assert person.name == "Ali"
        assert person.relationship == "friend"
        assert person.occupation == "graphic designer"

        retrieved = temp_store.get_person("Ali")
        assert retrieved is not None
        assert retrieved.occupation == "graphic designer"

    def test_bilingual_person_lookup(self, temp_store: PersonalStore):
        temp_store.add_or_update_person(
            name="Ali", relationship="friend", occupation="graphic designer"
        )
        # Query using Persian name alias «علی»
        retrieved = temp_store.get_person("علی")
        assert retrieved is not None
        assert retrieved.name == "Ali"
        assert retrieved.occupation == "graphic designer"

    def test_update_person_occupation_and_notes(self, temp_store: PersonalStore):
        temp_store.add_or_update_person(name="Sara", relationship="sister", occupation="student")
        temp_store.add_or_update_person(name="Sara", relationship="sister", occupation="architect")
        retrieved = temp_store.get_person("Sara")
        assert retrieved is not None
        assert retrieved.occupation == "architect"

    def test_find_and_list_people(self, temp_store: PersonalStore):
        temp_store.add_or_update_person(
            name="Reza", relationship="colleague", occupation="frontend lead"
        )
        temp_store.add_or_update_person(
            name="Mohammad", relationship="colleague", occupation="backend lead"
        )

        all_people = temp_store.list_people()
        assert len(all_people) == 2

        results = temp_store.find_people("frontend")
        assert len(results) == 1
        assert results[0].name == "Reza"

    def test_delete_person(self, temp_store: PersonalStore):
        temp_store.add_or_update_person(name="TempContact", relationship="contact")
        assert temp_store.delete_person("TempContact") is True
        assert temp_store.get_person("TempContact") is None


class TestPreferencesAndConflictResolution:
    def test_set_and_get_preference(self, temp_store: PersonalStore):
        temp_store.set_preference("coding", "preferred_editor", "VS Code")
        assert temp_store.get_preference("coding", "preferred_editor") == "VS Code"

    def test_conflict_resolution_supersedes_older(self, temp_store: PersonalStore):
        temp_store.set_preference("coding", "preferred_editor", "VS Code")
        # User changes preference
        temp_store.set_preference("coding", "preferred_editor", "Cursor")
        assert temp_store.get_preference("coding", "preferred_editor") == "Cursor"

    def test_list_and_delete_preferences(self, temp_store: PersonalStore):
        temp_store.set_preference("coding", "preferred_editor", "Cursor")
        temp_store.set_preference("ui", "theme", "dark")

        prefs = temp_store.list_preferences()
        assert len(prefs) == 2

        assert temp_store.delete_preference("ui", "theme") is True
        assert temp_store.get_preference("ui", "theme") == ""


class TestStructuredFacts:
    def test_add_and_find_facts(self, temp_store: PersonalStore):
        temp_store.add_fact(subject="Ali", predicate="works_as", object_val="graphic designer")
        facts = temp_store.find_facts(subject="Ali")
        assert len(facts) == 1
        assert facts[0].predicate == "works_as"
        assert facts[0].object_val == "graphic designer"

    def test_delete_facts_by_subject(self, temp_store: PersonalStore):
        temp_store.add_fact(subject="Sara", predicate="role", object_val="designer")
        temp_store.add_fact(subject="Sara", predicate="city", object_val="Tehran")
        deleted = temp_store.delete_facts_by_subject("Sara")
        assert deleted == 2
        assert len(temp_store.find_facts(subject="Sara")) == 0


class TestPersonalityConfiguration:
    def test_default_personality_config(self, temp_store: PersonalStore):
        cfg = temp_store.get_personality_config()
        assert cfg.assistant_name == "JARVIS"
        assert cfg.tone == "calm"
        assert cfg.formality == "standard"

    def test_update_personality_config(self, temp_store: PersonalStore):
        new_cfg = PersonalityConfig(
            assistant_name="JARVIS",
            tone="witty",
            formality="casual",
            detail_level="concise",
            proactivity="proactive",
            custom_instructions="Be sharp and use dry British humor.",
        )
        temp_store.update_personality_config(new_cfg)
        loaded = temp_store.get_personality_config()
        assert loaded.tone == "witty"
        assert loaded.formality == "casual"
        assert loaded.custom_instructions == "Be sharp and use dry British humor."


class TestExportImportAndPersistence:
    def test_export_and_import_roundtrip(self, temp_store: PersonalStore, tmp_path: Path):
        temp_store.set_profile_attribute("user_name", "Arad")
        temp_store.add_or_update_person("Ali", "friend", "graphic designer")
        temp_store.set_preference("coding", "preferred_editor", "Cursor")
        temp_store.add_fact("JARVIS", "creator", "Arad")

        exported_json = temp_store.export_all_json()
        assert "Arad" in exported_json
        assert "graphic designer" in exported_json

        # Create fresh store in a new database file
        new_db = tmp_path / "restored_memory.db"
        new_store = PersonalStore(db_path=new_db)
        counts = new_store.import_all_json(exported_json)

        assert counts["profile"] >= 1
        assert counts["people"] >= 1
        assert new_store.get_profile_attribute("user_name") == "Arad"
        assert new_store.get_person("Ali") is not None
        assert new_store.get_preference("coding", "preferred_editor") == "Cursor"

    def test_restart_persistence(self, tmp_path: Path):
        db_file = tmp_path / "persistent_session.db"
        store1 = PersonalStore(db_path=db_file)
        store1.set_profile_attribute("user_name", "Arad")
        store1.add_or_update_person("Ali", "friend", "graphic designer")

        # Simulate full app restart by constructing new instance pointing to same file
        store2 = PersonalStore(db_path=db_file)
        assert store2.get_profile_attribute("user_name") == "Arad"
        p = store2.get_person("Ali")
        assert p is not None
        assert p.occupation == "graphic designer"
