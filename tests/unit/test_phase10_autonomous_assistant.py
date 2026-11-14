"""Comprehensive Phase 10 Autonomous Assistant Integration & Unit Test Suite.

Verifies:
1. Multi-turn conversation sessions and cross-turn anaphora resolution (PC Shop, files, apps).
2. Intent classification and strict hypothetical discussion safety boundaries.
3. Unified Task Orchestrator 14 lifecycle states, checkpoints, SQLite persistence, and restart recovery.
4. Extensible Capability Registry discovery, runtime toggling, health checks, and metrics.
5. Voice pipeline barge-in, instant cancellation propagation, and British voice preview.
6. Verification of Acceptance Scenarios A through H.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from core.conversation_session import (
    ConversationSessionManager,
    IntentType,
)
from core.personality import JarvisPersonalityEngine
from core.task_orchestrator import (
    OrchestratedTask,
    TaskDatabaseStore,
    TaskLifecycleState,
    UnifiedTaskOrchestrator,
    VerificationRecord,
    VerificationState,
)
from memory.base import ConversationMessage
from tools.capability_registry import (
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityStatus,
)
from tools.voice.models import VoiceState
from tools.voice.voice_pipeline import ConversationalVoicePipeline


# =====================================================================
# 1. Multi-turn Session & Anaphoric Reference Resolution Tests
# =====================================================================
class TestConversationSessionAndAnaphora:
    """Test multi-turn context retention, anaphora resolution, and language policy."""

    def test_session_creation_and_entity_tracking(self) -> None:
        mgr = ConversationSessionManager()
        ctx = mgr.get_session("session_101")
        assert ctx.session_id == "session_101"
        assert ctx.active_project_name is None

        # Track an entity
        mgr.track_entity("session_101", "project", "PC Shop", {"path": "C:\\AI\\pc-shop"})
        assert ctx.active_project_name == "PC Shop"
        assert str(ctx.active_project_path) == "C:\\AI\\pc-shop"

    def test_anaphora_resolution_for_pc_shop_project(self) -> None:
        mgr = ConversationSessionManager()
        session_id = "session_pcshop"

        # Turn 1: User introduces PC Shop project
        t1, inf1 = mgr.resolve_contextual_references(
            current_prompt="پروژه پیسیشاپ رو بررسی کن",
            history=[],
            session_id=session_id,
        )
        assert inf1.get("active_project") == "PC Shop"
        assert inf1.get("active_project_path") == "C:\\AI\\pc-shop"

        # Create history for Turn 2
        history = [
            ConversationMessage(
                role="user", content="پروژه پیسیشاپ رو بررسی کن", session_id=session_id
            ),
            ConversationMessage(
                role="assistant",
                content="Certainly, sir. I am inspecting the PC Shop project repository.",
                session_id=session_id,
            ),
        ]

        # Turn 2: User refers to project's tests via pronoun/suffix ("تستهاشو اجرا کن")
        t2, inf2 = mgr.resolve_contextual_references(
            current_prompt="حالا تستهاشو اجرا کن",
            history=history,
            session_id=session_id,
        )
        assert inf2.get("active_project") == "PC Shop"
        assert "پیسیشاپ" in t2 or "PC Shop" in t2 or inf2.get("active_project") == "PC Shop"

        # Turn 3: User commands fix ("اگه خطایی داشت درستش کن")
        t3, inf3 = mgr.resolve_contextual_references(
            current_prompt="اگه خطایی داشت درستش کن",
            history=history,
            session_id=session_id,
        )
        assert inf3.get("active_project") == "PC Shop"
        assert inf3.get("intent_type") == IntentType.ACTION_EXECUTION.value

    def test_temporary_persian_response_switch(self) -> None:
        mgr = ConversationSessionManager()
        session_id = "sess_lang"

        _, inf = mgr.resolve_contextual_references(
            current_prompt="این مورد را به فارسی توضیح بده",
            history=[],
            session_id=session_id,
        )
        assert inf.get("language_override") == "fa"
        ctx = mgr.get_session(session_id)
        assert ctx.language_preference == "fa"

        # Next prompt reverts back to British English when requested
        _, inf_en = mgr.resolve_contextual_references(
            current_prompt="Now switch back to English, please.",
            history=[],
            session_id=session_id,
        )
        assert inf_en.get("language_override") == "en"
        assert ctx.language_preference == "en"


# =====================================================================
# 2. Strict Hypothetical Discussion Safety Tests
# =====================================================================
class TestHypotheticalDiscussionSafety:
    """Verify that speculative/hypothetical chat never authorizes real action execution."""

    def test_hypothetical_persian_queries_classified_safely(self) -> None:
        mgr = ConversationSessionManager()
        prompt = "فرض کن پوشه پروژه رو کامل حذف کنیم، چه اتفاقی می‌افته؟"
        intent, is_hypo = mgr.classify_intent(prompt)

        assert is_hypo is True
        assert intent == IntentType.HYPOTHETICAL_DISCUSSION

    def test_hypothetical_english_queries_classified_safely(self) -> None:
        mgr = ConversationSessionManager()
        prompt = "What if we delete the entire database table and restart the server?"
        intent, is_hypo = mgr.classify_intent(prompt)

        assert is_hypo is True
        assert intent == IntentType.HYPOTHETICAL_DISCUSSION

    def test_personality_engine_blocks_action_from_hypothetical(self) -> None:
        prompt = "فرض کنیم فایل اصلی تنظیمات رو پاک کنیم، سیستم کار میکنه؟"
        resolved, inferred = JarvisPersonalityEngine.resolve_references(
            prompt, history=[], session_id="hypo_session"
        )
        assert inferred.get("is_hypothetical") is True
        assert inferred.get("intent_type") == IntentType.HYPOTHETICAL_DISCUSSION.value


# =====================================================================
# 3. Unified Task Orchestrator & Persistent Lifecycle State Tests
# =====================================================================
class TestTaskOrchestratorLifecycleAndPersistence:
    """Verify 14 lifecycle states, SQLite checkpoints, and recovery."""

    def test_all_14_lifecycle_states_exist(self) -> None:
        expected_states = {
            "created",
            "understanding",
            "planning",
            "waiting_for_input",
            "waiting_for_approval",
            "ready",
            "executing",
            "verifying",
            "retrying",
            "completed",
            "partially_completed",
            "failed",
            "cancelled",
            "unknown",
        }
        actual_states = {s.value for s in TaskLifecycleState}
        assert expected_states == actual_states

    def test_all_8_verification_states_exist(self) -> None:
        expected_verifs = {
            "requested",
            "planned",
            "authorized",
            "started",
            "executed",
            "verified",
            "failed",
            "unknown",
        }
        actual_verifs = {v.value for v in VerificationState}
        assert expected_verifs == actual_verifs

    def test_task_sqlite_persistence_and_restart_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks_test.db"
            store = TaskDatabaseStore(db_path=db_path)

            task = OrchestratedTask(
                goal="Investigate PC Shop backend failure",
                session_id="sess_recovery",
                state=TaskLifecycleState.EXECUTING,
            )
            store.save_task(task)

            # Record verification record
            rec = VerificationRecord(
                step_id="step_1",
                action_name="run_tests",
                state=VerificationState.EXECUTED,
                evidence_summary="Executed 45 pytest tests with 1 failure",
            )
            store.save_verification_record(task.task_id, rec)

            # Simulate app crash/restart with brand new store instance
            store2 = TaskDatabaseStore(db_path=db_path)
            loaded = store2.load_task(task.task_id)
            assert loaded is not None
            assert loaded.goal == "Investigate PC Shop backend failure"
            assert loaded.state == TaskLifecycleState.EXECUTING
            assert len(loaded.verification_records) == 1
            assert loaded.verification_records[0].step_id == "step_1"

            # UnifiedTaskOrchestrator recovery on restart:
            orchestrator = UnifiedTaskOrchestrator(db_store=store2)
            recovered_count = orchestrator.recover_in_flight_tasks()
            assert recovered_count >= 1

            # Check that in-flight executing task was safely transitioned to FAILED / recovery needed
            reloaded = store2.load_task(task.task_id)
            assert reloaded is not None
            assert reloaded.state in (TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED)

    def test_task_orchestrator_state_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks_flow.db"
            orchestrator = UnifiedTaskOrchestrator(db_store=TaskDatabaseStore(db_path=db_path))

            task = orchestrator.create_task("Fix authentication bug", "sess_trans")
            assert task.state == TaskLifecycleState.CREATED

            orchestrator.transition_task(
                task.task_id, TaskLifecycleState.UNDERSTANDING, "Analyzing"
            )
            assert task.state == TaskLifecycleState.UNDERSTANDING

            orchestrator.transition_task(task.task_id, TaskLifecycleState.PLANNING, "Decomposing")
            assert task.state == TaskLifecycleState.PLANNING

            orchestrator.transition_task(task.task_id, TaskLifecycleState.READY, "Plan created")
            assert task.state == TaskLifecycleState.READY

            orchestrator.transition_task(
                task.task_id, TaskLifecycleState.EXECUTING, "Running tools"
            )
            assert task.state == TaskLifecycleState.EXECUTING

            orchestrator.transition_task(
                task.task_id, TaskLifecycleState.VERIFYING, "Checking test outcomes"
            )
            assert task.state == TaskLifecycleState.VERIFYING

            orchestrator.record_verification(
                task_id=task.task_id,
                step_id="step_fix",
                action_name="test_verification",
                state=VerificationState.VERIFIED,
                evidence_summary="100% tests passing",
                verified=True,
            )

            orchestrator.transition_task(
                task.task_id, TaskLifecycleState.COMPLETED, "Goal satisfied"
            )
            assert task.state == TaskLifecycleState.COMPLETED
            assert len(task.checkpoints) >= 6


# =====================================================================
# 4. Capability Registry Tests
# =====================================================================
class TestCapabilityRegistry:
    """Verify extensible capability discovery, runtime toggling, and health monitoring."""

    def test_capability_registration_and_listing(self) -> None:
        registry = CapabilityRegistry()
        from core.permissions import PermissionCategory

        cap = CapabilityMetadata(
            capability_id="test_git_cap",
            name="Git Inspector",
            version="1.0.0",
            description="Inspect git repositories and diffs",
            category=PermissionCategory.CODING_AGENT_VERIFY,
            health_check=lambda: True,
        )
        registry.register_capability(cap)

        found = registry.get_capability("test_git_cap")
        assert found is not None
        assert found.name == "Git Inspector"

        listed = registry.list_capabilities(category=PermissionCategory.CODING_AGENT_VERIFY)
        assert len(listed) == 1

    def test_capability_runtime_enable_disable(self) -> None:
        registry = CapabilityRegistry()
        from core.permissions import PermissionCategory

        cap = CapabilityMetadata(
            capability_id="test_toggle_cap",
            name="Audio Controller",
            version="1.0.0",
            description="Controls Windows audio volume",
            category=PermissionCategory.WINDOWS_AUDIO_CONTROL,
        )
        registry.register_capability(cap)

        assert registry.get_capability("test_toggle_cap").enabled is True
        registry.set_enabled("test_toggle_cap", False)
        assert registry.get_capability("test_toggle_cap").enabled is False

        enabled_caps = registry.list_capabilities(only_enabled=True)
        assert "test_toggle_cap" not in [c.capability_id for c in enabled_caps]

    def test_capability_health_checks_and_metrics(self) -> None:
        registry = CapabilityRegistry()
        from core.permissions import PermissionCategory

        cap_healthy = CapabilityMetadata(
            capability_id="healthy_cap",
            name="Healthy Tool",
            version="1.0.0",
            description="Always healthy",
            category=PermissionCategory.READ_ONLY,
            health_check=lambda: True,
        )
        cap_degraded = CapabilityMetadata(
            capability_id="degraded_cap",
            name="Degraded Tool",
            version="1.0.0",
            description="Failing check",
            category=PermissionCategory.NETWORK_INSPECT,
            health_check=lambda: False,
        )
        registry.register_capability(cap_healthy)
        registry.register_capability(cap_degraded)

        health_report = registry.run_health_checks()
        assert health_report["healthy_cap"]["status"] == CapabilityStatus.AVAILABLE.value
        assert health_report["degraded_cap"]["status"] == CapabilityStatus.DEGRADED.value

        # Metrics recording
        registry.record_execution("healthy_cap", "read", success=True, duration_seconds=0.04)
        assert len(registry._execution_history) == 1


# =====================================================================
# 5. Full-Duplex Barge-In & Speech Cancellation Tests
# =====================================================================
class TestVoiceBargeInAndCancellation:
    """Verify speech barge-in, immediate interruption, and voice preview."""

    def test_voice_interruption_and_cancel_active_speech(self) -> None:
        pipeline = ConversationalVoicePipeline()
        mock_tts = MagicMock()
        mock_tts.is_speaking.return_value = True
        pipeline.tts_service = mock_tts

        pipeline.set_state(VoiceState.SPEAKING)
        assert pipeline.state == VoiceState.SPEAKING

        # Trigger cancellation
        pipeline.cancel_active_speech_and_generation()
        assert mock_tts.stop.called
        assert pipeline.state == VoiceState.IDLE

    def test_barge_in_on_active_speech(self) -> None:
        pipeline = ConversationalVoicePipeline()
        mock_tts = MagicMock()
        mock_tts.is_speaking.return_value = True
        pipeline.tts_service = mock_tts

        pipeline.interrupt_speech()
        assert mock_tts.stop.called
        assert pipeline.state == VoiceState.IDLE

    def test_preview_british_voice(self) -> None:
        pipeline = ConversationalVoicePipeline()
        mock_tts = MagicMock()
        mock_tts.preview_voice.return_value = True
        pipeline.tts_service = mock_tts

        res = pipeline.preview_british_voice()
        assert res is True
        assert mock_tts.preview_voice.called


# =====================================================================
# 6. Verification of Acceptance Scenarios A through H
# =====================================================================
class TestAcceptanceScenariosAThroughH:
    """Verify authentic British spoken identity and truthful responses for Scenarios A through H."""

    def test_scenario_a_system_sluggishness(self) -> None:
        # User: "سیستم کند شده، یه نگاه به وضعیتش بنداز"
        # Spoken output should diagnose resource usage in British English
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="وضعیت سیستم: پردازنده ۲۵٪ و حافظه ۴۰٪",
            user_prompt="سیستم کند شده، یه نگاه به وضعیتش بنداز",
        )
        assert "Certainly, sir" in spoken or "System status" in spoken
        assert (
            "operating within normal parameters" in spoken
            or "utilization" in spoken
            or "CPU" in spoken
        )

    def test_scenario_b_pc_shop_project_investigation(self) -> None:
        # Step 1: "پروژه پیسیشاپ رو بررسی کن"
        sp1 = JarvisPersonalityEngine.format_spoken_response_en(
            text="پروژه PC Shop بررسی شد.",
            user_prompt="پروژه پیسیشاپ رو بررسی کن",
        )
        assert "PC Shop project" in sp1
        assert "inspecting" in sp1 or "repository" in sp1

        # Step 2: "تستهاشو اجرا کن"
        sp2 = JarvisPersonalityEngine.format_spoken_response_en(
            text="تست های پروژه اجرا شدند.",
            user_prompt="حالا تستهاشو اجرا کن",
        )
        assert "Running the test suite" in sp2 or "PC Shop" in sp2

        # Step 3: "اگه خطایی داشت درستش کن"
        sp3 = JarvisPersonalityEngine.format_spoken_response_en(
            text="خطاهای پروژه برطرف شد.",
            user_prompt="اگه خطایی داشت درستش کن",
        )
        assert "resolved the failing tests" in sp3 or "verified the test suite" in sp3

        # Step 4: "چه چیزهایی رو تغییر دادی؟"
        sp4 = JarvisPersonalityEngine.format_spoken_response_en(
            text="تغییرات گیت بررسی شد.",
            user_prompt="چه چیزهایی رو تغییر دادی؟",
        )
        assert "reviewed the repository changes" in sp4 or "modifications" in sp4

    def test_scenario_c_interruption(self) -> None:
        # Barge-in interruption
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="استفاده از حافظه سیستم 65% است.",
            user_prompt="صبر کن، رم چقدره؟",
        )
        assert "System memory utilization is currently at 65%" in spoken

    def test_scenario_d_ambiguous_edit_requires_clarification(self) -> None:
        # User says "ویرایشش کن" without details
        resolved, inferred = JarvisPersonalityEngine.resolve_references(
            current_prompt="ویرایشش کن",
            history=[],
        )
        assert inferred.get("needs_clarification") is True
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=inferred.get("clarification_prompt", ""),
            user_prompt="ویرایشش کن",
        )
        assert "What modification would you like me to make" in spoken

    def test_scenario_e_email_draft_preparation(self) -> None:
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="پیش‌نویس ایمیل برای john@example.com آماده شد و در انتظار تأیید است.",
            user_prompt="به john@example.com ایمیل بفرست",
        )
        assert "prepared the email draft to john@example.com" in spoken
        assert "approval before transmission" in spoken or "review" in spoken

    def test_scenario_f_web_research_summary(self) -> None:
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="تحقیقات انجام شد و مستندات بررسی شدند.",
            user_prompt="در وب در مورد معماری فریمورک تحقیق کن",
        )
        assert "researched the framework and summarized the findings" in spoken

    def test_scenario_g_antigravity_delegation(self) -> None:
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="وظیفه به آنتی گرویتی محول شد.",
            user_prompt="این کار رو با آنتی گرویتی بررسی کن",
        )
        assert "Delegating the task to the Antigravity coding agent" in spoken

    def test_scenario_h_long_running_technical_report(self) -> None:
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text="تحلیل عمیق در حال انجام است.",
            user_prompt="یک گزارش فنی از وضعیت پروژه آماده کن",
        )
        assert "started a background analysis" in spoken
        assert "notify you once the technical report is ready" in spoken
