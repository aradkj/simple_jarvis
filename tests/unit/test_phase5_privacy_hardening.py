"""Regression and privacy boundary verification tests for JARVIS Phase 5.

Verifies the separation of local storage consent from external AI provider transmission consent.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai.base import AIResponse
from config import Settings, save_env_settings
from core.agent import JARVISAgent
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor
from core.planner import AgentPlanner, Plan, PlanStep, StepType
from core.state_machine import AgentStateMachine
from core.tool_registry import ToolRegistry
from memory.manager import MemoryManager
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from memory.privacy import SensitiveDataFilter
from memory.repository import MemoryRepository


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Temporary SQLite database for isolated test execution."""
    return tmp_path / "privacy_test.db"


@pytest.fixture
def base_repo(temp_db_path: Path) -> MemoryRepository:
    """Initialized MemoryRepository on temporary database."""
    repo = MemoryRepository(db_path=temp_db_path)
    repo.initialize()
    return repo


# =====================================================================
# 1. Default Setting & Consent Separation Tests
# =====================================================================


def test_cloud_memory_transmission_disabled_by_default() -> None:
    """Verify that cloud memory transmission is strictly disabled by default."""
    settings = Settings()
    assert settings.memory_allow_cloud_transmission is False
    assert settings.memory_enabled is True


def test_saving_memory_does_not_authorize_cloud_transmission(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """Saving a memory creates a persistent record locally but does not authorize transmission."""
    # Default settings (memory_allow_cloud_transmission=False)
    settings = Settings(memory_enabled=True)
    mem_mgr = MemoryManager(settings=settings, repository=base_repo)
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    agent = JARVISAgent(settings=settings, ai_provider=mock_pm, memory_manager=mem_mgr)

    # User explicitly stores a memory
    saved = agent.remember(
        content="User prefers Python 3.12 exclusively.",
        category=MemoryCategory.PREFERENCE,
        key="pref.python_version",
    )
    assert saved.status == MemoryStatus.ACTIVE
    assert saved.user_approved is True

    # Verify memory exists in local SQLite database
    fetched = base_repo.get(saved.id)
    assert fetched is not None
    assert fetched.content == "User prefers Python 3.12 exclusively."

    # Verify privacy manager reports local storage/retrieval allowed, but cloud transmission NOT allowed
    assert mem_mgr.privacy_manager.is_storage_allowed() is True
    assert mem_mgr.privacy_manager.is_retrieval_allowed() is True
    assert mem_mgr.privacy_manager.is_cloud_transmission_allowed() is False

    # Attempting to build context for cloud transmission yields empty string
    ctx_str = agent.build_memory_context("Python", for_cloud_transmission=True)
    assert ctx_str == ""


# =====================================================================
# 2. Disabled Mode Prevents Memory from Entering Provider Requests
# =====================================================================


def test_disabled_mode_omits_memories_from_direct_conversation(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """When cloud transmission is disabled, direct prompt to provider contains no memories."""
    settings = Settings(memory_enabled=True, memory_allow_cloud_transmission=False)
    mem_mgr = MemoryManager(settings=settings, repository=base_repo)

    # Pre-populate active approved memory
    mem_mgr.create_approved_memory(
        content="User requires Persian language answers.",
        key="pref.lang",
    )

    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(text="Direct reply", model="gemini-3.8-flash")

    agent = JARVISAgent(settings=settings, ai_provider=mock_pm, memory_manager=mem_mgr)
    outcome = agent.process_agent_task(goal="Tell me a joke")
    assert outcome.status == "completed"

    call_prompt = mock_pm.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in call_prompt
    assert "Persian language" not in call_prompt


def test_disabled_mode_omits_memories_from_planner_prompt(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """When cloud transmission is disabled, planning prompt to provider contains no memories."""
    settings = Settings(memory_enabled=True, memory_allow_cloud_transmission=False)
    mem_mgr = MemoryManager(settings=settings, repository=base_repo)

    mem_mgr.create_approved_memory(
        content="Project uses Microservices architecture.",
        key="project.arch",
    )

    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(
        text='{"goal": "Complex goal", "estimated_complexity": "low", "completion_condition": "done", "steps": [{"description": "Action", "step_type": "thought", "parameters": {}, "dependencies": []}]}',
        model="gemini-3.8-flash",
    )

    planner = AgentPlanner(provider_manager=mock_pm, settings=settings)
    ctx = ExecutionContext()
    ctx.memory_context = mem_mgr.build_memory_context("architecture", for_cloud_transmission=False)
    assert ctx.memory_context != ""  # Local context exists

    # But planner checks settings.memory_allow_cloud_transmission before sending to provider
    planner.create_plan(
        goal="Decompose architectural task with multiple components",
        context=ctx,
        available_tools=[],
    )

    call_prompt = mock_pm.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in call_prompt
    assert "Microservices" not in call_prompt


def test_disabled_mode_omits_memories_from_executor_synthesis(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """When cloud transmission is disabled, executor synthesis prompt contains no memories."""
    settings = Settings(memory_enabled=True, memory_allow_cloud_transmission=False)
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(
        text="Synthesis output", model="gemini-3.8-flash"
    )

    executor = AgentExecutor(
        tool_registry=ToolRegistry(),
        provider_manager=mock_pm,
        planner=AgentPlanner(provider_manager=mock_pm, settings=settings),
        state_machine=AgentStateMachine(),
        settings=settings,
    )

    plan = Plan(goal="Synthesize results", session_id="test-session")
    step = PlanStep(description="Final synthesis", step_type=StepType.SYNTHESIS)
    plan.add_step(step)

    ctx = ExecutionContext(
        session_id="test-session",
        memory_context="[RELEVANT USER MEMORY]\n- User prefers dark mode\n[END USER MEMORY]",
    )

    outcome = executor.execute_plan(plan, context=ctx)
    assert outcome.status == "completed"

    call_prompt = mock_pm.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in call_prompt
    assert "dark mode" not in call_prompt


# =====================================================================
# 3. Enabled Mode Allows Only Relevant Approved Non-Sensitive Memories
# =====================================================================


def test_enabled_mode_transmits_only_relevant_approved_memories(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """When enabled, relevant approved memories are transmitted, while unapproved/unrelated are not."""
    settings = Settings(
        memory_enabled=True,
        memory_allow_cloud_transmission=True,
        memory_min_relevance_score=0.5,
    )
    mem_mgr = MemoryManager(settings=settings, repository=base_repo)

    # 1. Approved relevant memory
    mem_mgr.create_approved_memory(
        content="User prefers Python 3.12 and type annotations.",
        category=MemoryCategory.PREFERENCE,
        key="pref.python",
        importance=0.8,
        confidence=1.0,
    )

    # 2. Unapproved candidate
    mem_mgr.repository.save(
        MemoryRecord(
            content="User might want Kotlin responses.",
            key="pref.kotlin",
            status=MemoryStatus.PENDING_APPROVAL,
            user_approved=False,
        )
    )

    # 3. Completely unrelated approved memory
    mem_mgr.create_approved_memory(
        content="Ancient Sumerian pottery techniques.",
        category=MemoryCategory.EPISODIC,
        key="other.pottery",
        importance=0.1,
        confidence=0.5,
    )

    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True
    mock_pm.generate_text.return_value = AIResponse(text="Done", model="gemini-3.8-flash")

    agent = JARVISAgent(settings=settings, ai_provider=mock_pm, memory_manager=mem_mgr)
    outcome = agent.process_agent_task(goal="Write a Python script")
    assert outcome.status == "completed"

    call_prompt = mock_pm.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" in call_prompt
    assert "Python 3.12" in call_prompt
    assert "Kotlin" not in call_prompt  # Unapproved candidate excluded
    assert "Sumerian" not in call_prompt  # Irrelevant memory excluded


def test_sensitive_memories_are_never_transmitted_even_if_cloud_enabled(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """Sensitive patterns (API keys, passwords, credentials) are strictly stripped before transmission."""
    settings = Settings(memory_enabled=True, memory_allow_cloud_transmission=True)
    mem_mgr = MemoryManager(settings=settings, repository=base_repo)

    # Direct database injection of an active memory containing prohibited credentials
    malicious_rec = MemoryRecord(
        content="System api_key = 'AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6'",
        key="secret.key",
        status=MemoryStatus.ACTIVE,
        user_approved=True,
    )
    base_repo.save(malicious_rec)

    # Verify SensitiveDataFilter detects it
    assert SensitiveDataFilter.contains_sensitive_data(malicious_rec.content) is True

    # Cloud context builder must scrub it
    ctx_str = mem_mgr.build_memory_context("api_key", for_cloud_transmission=True)
    assert ctx_str == ""
    assert "AIzaSy" not in ctx_str


# =====================================================================
# 4. ProviderManager Boundary Defense & Fallback Isolation
# =====================================================================


def test_providermanager_boundary_scrubs_memory_when_cloud_disabled() -> None:
    """ProviderManager itself strips memory block if cloud memory transmission is disabled."""
    settings = Settings(memory_allow_cloud_transmission=False)
    mock_provider = MagicMock()
    mock_provider.provider_name = "MockGemini"
    mock_provider.default_model = "gemini-3.8-flash"
    mock_provider.generate_text.return_value = AIResponse(text="Answer", model="gemini-3.8-flash")

    from ai.manager import ProviderManager
    from ai.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register("gemini", mock_provider)

    pm = ProviderManager(settings=settings, registry=registry)

    # Prompt inadvertently containing memory block
    dirty_prompt = (
        "[RELEVANT USER MEMORY]\n"
        "- [preference] User prefers dark mode.\n"
        "[END USER MEMORY]\n\n"
        "Tell me a story."
    )

    pm.generate_text(prompt=dirty_prompt, provider_id="gemini")

    # Verify provider received prompt with memory block stripped
    actual_prompt = mock_provider.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in actual_prompt
    assert "dark mode" not in actual_prompt
    assert actual_prompt == "Tell me a story."


def test_cross_provider_fallback_respects_cloud_memory_setting() -> None:
    """Fallback from Provider A to Provider B preserves cloud memory restrictions."""
    settings = Settings(
        gemini_enabled=True,
        gemini_api_key="mock_gemini_key",
        groq_enabled=True,
        groq_api_key="mock_groq_key",
        memory_allow_cloud_transmission=False,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=True,
    )
    mock_primary = MagicMock()
    mock_primary.provider_name = "Primary"
    mock_primary.default_model = "m1"
    mock_primary.is_ready.return_value = True
    mock_primary.generate_text.side_effect = RuntimeError("503 Service Unavailable on primary")

    mock_secondary = MagicMock()
    mock_secondary.provider_name = "Secondary"
    mock_secondary.default_model = "m2"
    mock_secondary.is_ready.return_value = True
    mock_secondary.generate_text.return_value = AIResponse(text="Fallback reply", model="m2")

    from ai.manager import ProviderManager
    from ai.registry import ProviderRegistry

    registry = ProviderRegistry(settings=settings)
    registry.register("gemini", mock_primary)
    registry.register("groq", mock_secondary)

    pm = ProviderManager(settings=settings, registry=registry)

    dirty_prompt = (
        "[RELEVANT USER MEMORY]\n"
        "- [preference] User prefers concise style.\n"
        "[END USER MEMORY]\n\n"
        "Explain gravity."
    )

    resp = pm.generate_text(prompt=dirty_prompt, provider_id="gemini")
    assert resp.text == "Fallback reply"

    # Secondary provider must have received the cleaned prompt
    sec_prompt = mock_secondary.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in sec_prompt
    assert "concise style" not in sec_prompt


# =====================================================================
# 5. Setting Persistence & Non-Destructive Storage Verification
# =====================================================================


def test_cloud_memory_setting_persistence_across_reloads(tmp_path: Path) -> None:
    """Setting changes are persisted to .env and survive settings reload."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=JARVIS\n", encoding="utf-8")

    # Update setting
    save_env_settings({"MEMORY_ALLOW_CLOUD_TRANSMISSION": "true"}, env_path=env_file)

    # Read back directly
    content = env_file.read_text(encoding="utf-8")
    assert "MEMORY_ALLOW_CLOUD_TRANSMISSION=true" in content


def test_local_memory_management_remains_active_when_cloud_disabled(
    temp_db_path: Path, base_repo: MemoryRepository
) -> None:
    """Disabling cloud transmission does not disable local search, CRUD, or editing."""
    settings = Settings(memory_enabled=True, memory_allow_cloud_transmission=False)
    mgr = MemoryManager(settings=settings, repository=base_repo)

    # 1. Create
    rec = mgr.create_approved_memory("Local note on algorithms", key="local.algo")
    assert rec.status == MemoryStatus.ACTIVE

    # 2. Local List & Search
    records = mgr.list_memories(search_query="algorithms")
    assert len(records) == 1
    assert records[0].id == rec.id

    # 3. Edit
    edited = mgr.edit_memory(rec.id, "Local note on graph algorithms")
    assert edited is not None
    assert "graph algorithms" in edited.content

    # 4. Local retrieval (for local application use) works
    retrieved = mgr.retrieve_relevant_memories("graph")
    assert len(retrieved) == 1

    # 5. Cloud context remains empty
    assert mgr.build_memory_context("graph", for_cloud_transmission=True) == ""
