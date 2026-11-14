"""Integration tests for Phase 9 Voice Intelligence, Personality, Email & WhatsApp in JARVIS."""

from __future__ import annotations

import pytest

from core.agent import JARVISAgent
from tools.communication.email.email_service import get_email_service
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.whatsapp.mock_provider import MockWhatsAppProvider
from tools.communication.whatsapp.whatsapp_service import get_whatsapp_service


class TestPhase9Integration:
    """Full lifecycle integration tests for Phase 9."""

    @pytest.fixture
    def jarvis_agent(self):
        return JARVISAgent()

    def test_phase9_tools_registered_in_tool_registry(self, jarvis_agent: JARVISAgent):
        registered = set(jarvis_agent.tool_registry.list_tool_names())

        expected_phase9_tools = {
            "voice_status",
            "voice_speak",
            "voice_mute",
            "email_compose",
            "email_send",
            "email_status",
            "whatsapp_compose",
            "whatsapp_send",
            "whatsapp_status",
        }
        for tool_name in expected_phase9_tools:
            assert tool_name in registered, f"Missing registered Phase 9 tool: {tool_name}"

    def test_persian_and_english_voice_intent_mapping(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Persian mic mute
        plan_fa = planner._build_fallback_plan_dict("میکروفون رو قطع کن", tools)
        voice_steps_fa = [s for s in plan_fa["steps"] if s.get("tool_name") == "voice_mute"]
        assert len(voice_steps_fa) == 1
        assert voice_steps_fa[0]["parameters"]["mute"] is True

        # English mic unmute
        plan_en = planner._build_fallback_plan_dict("unmute microphone", tools)
        voice_steps_en = [s for s in plan_en["steps"] if s.get("tool_name") == "voice_mute"]
        assert len(voice_steps_en) == 1
        assert voice_steps_en[0]["parameters"]["mute"] is False

    def test_persian_and_english_email_intent_mapping(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Persian email
        plan_fa = planner._build_fallback_plan_dict(
            "برای علی ایمیل بفرست و بگو گزارش آماده است", tools
        )
        email_steps_fa = [s for s in plan_fa["steps"] if s.get("tool_name") == "email_compose"]
        assert len(email_steps_fa) == 1
        assert "گزارش آماده است" in email_steps_fa[0]["parameters"]["body_text"]

        # English email
        plan_en = planner._build_fallback_plan_dict(
            "send an email to bob@example.com saying meeting is confirmed", tools
        )
        email_steps_en = [s for s in plan_en["steps"] if s.get("tool_name") == "email_compose"]
        assert len(email_steps_en) == 1
        assert "bob@example.com" in email_steps_en[0]["parameters"]["to"]

    def test_persian_and_english_whatsapp_intent_mapping(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Persian WhatsApp
        plan_fa = planner._build_fallback_plan_dict(
            "به خودم در واتساپ پیام بده که فایل ذخیره شد", tools
        )
        wa_steps_fa = [s for s in plan_fa["steps"] if s.get("tool_name") == "whatsapp_compose"]
        assert len(wa_steps_fa) == 1
        assert wa_steps_fa[0]["parameters"]["recipient"] == "خودم"

        # English WhatsApp
        plan_en = planner._build_fallback_plan_dict(
            "send whatsapp message to +14155552671 saying server restarted", tools
        )
        wa_steps_en = [s for s in plan_en["steps"] if s.get("tool_name") == "whatsapp_compose"]
        assert len(wa_steps_en) == 1
        assert "+14155552671" in wa_steps_en[0]["parameters"]["recipient"]

    def test_high_risk_communication_tools_require_approval(self, jarvis_agent: JARVISAgent):
        email_send = jarvis_agent.tool_registry.get("email_send")
        assert email_send is not None
        assert email_send.get_definition().requires_approval is True

        wa_send = jarvis_agent.tool_registry.get("whatsapp_send")
        assert wa_send is not None
        assert wa_send.get_definition().requires_approval is True

    def test_end_to_end_mock_email_execution(self, jarvis_agent: JARVISAgent):
        email_svc = get_email_service()
        mock_email = MockEmailProvider(should_succeed=True)
        email_svc.set_mock_provider(mock_email)

        outcome = jarvis_agent.process_agent_task(
            goal="یک ایمیل به client@example.com بفرست با موضوع تست",
            session_id="test_email_session",
            wait_for_approval=False,
        )
        assert outcome.status in ("completed", "waiting_for_approval")

    def test_end_to_end_mock_whatsapp_execution(self, jarvis_agent: JARVISAgent):
        wa_svc = get_whatsapp_service()
        mock_wa = MockWhatsAppProvider(should_succeed=True)
        wa_svc.set_mock_provider(mock_wa)

        outcome = jarvis_agent.process_agent_task(
            goal="در واتساپ به +989121234567 پیام بده که سیستم روشن است",
            session_id="test_wa_session",
            wait_for_approval=False,
        )
        assert outcome.status in ("completed", "waiting_for_approval")

    def test_ambiguous_communication_intents_require_clarification(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Ambiguous email without recipient: planner should NOT invent recipient@example.com
        plan_email_ambig = planner._build_fallback_plan_dict("یک ایمیل بفرست و بگو سلام", tools)
        email_steps = [
            s
            for s in plan_email_ambig["steps"]
            if s.get("tool_name") in ("email_compose", "email_send")
        ]
        assert len(email_steps) == 0

        # Ambiguous whatsapp without recipient: planner should NOT invent "خودم"
        plan_wa_ambig = planner._build_fallback_plan_dict("در واتساپ پیام بفرست و بگو سلام", tools)
        wa_steps = [
            s
            for s in plan_wa_ambig["steps"]
            if s.get("tool_name") in ("whatsapp_compose", "whatsapp_send")
        ]
        assert len(wa_steps) == 0

    def test_voice_approval_bypass_blocked_in_agent(self, jarvis_agent: JARVISAgent):
        from core.tool_proposal import RiskLevel, ToolProposal

        prop = ToolProposal(
            proposal_id="prop_voice_test",
            session_id="test_session",
            tool_name="whatsapp_send",
            risk_level=RiskLevel.HIGH,
            arguments={"draft_id": "draft_test"},
        )
        jarvis_agent.approval_manager._pending_proposals[prop.proposal_id] = prop

        # Voice approval must be rejected
        ok = jarvis_agent.approval_manager.submit_decision(
            proposal_id="prop_voice_test",
            approved=True,
            session_id="test_session",
            source="voice",
        )
        assert ok is False
