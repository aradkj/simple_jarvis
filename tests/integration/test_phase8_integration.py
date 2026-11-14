"""Integration tests for Phase 8 File System, Terminal, and Antigravity Agent in JARVIS."""

from __future__ import annotations

import pytest

from core.agent import JARVISAgent


class TestPhase8Integration:
    """Full lifecycle integration tests for Phase 8."""

    @pytest.fixture
    def jarvis_agent(self):
        return JARVISAgent()

    def test_phase8_tools_registered_in_tool_registry(self, jarvis_agent: JARVISAgent):
        registered_names = set(jarvis_agent.tool_registry.list_tool_names())

        # File system tools
        expected_fs_tools = {
            "file_extract_document",
            "file_write_text",
            "file_edit_text",
            "file_copy",
            "file_move",
            "file_delete",
            "file_compare_diff",
            "file_find_duplicates",
            "file_archive_create",
            "file_archive_inspect",
            "file_archive_extract",
        }
        for tool_name in expected_fs_tools:
            assert tool_name in registered_names, f"Missing tool: {tool_name}"

        # Terminal tools
        expected_term_tools = {
            "terminal_execute_command",
            "terminal_list_commands",
        }
        for tool_name in expected_term_tools:
            assert tool_name in registered_names, f"Missing tool: {tool_name}"

        # Coding agent tools
        expected_coding_tools = {
            "coding_agent_status",
            "coding_agent_delegate_task",
            "coding_agent_get_task_status",
            "coding_agent_verify_task",
        }
        for tool_name in expected_coding_tools:
            assert tool_name in registered_names, f"Missing tool: {tool_name}"

    def test_persian_and_english_coding_agent_delegation_intent(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Persian prompt
        persian_goal = "با آنتی گرویتی کد بنویس برای سیستم کشینگ"
        plan_fa = planner._build_fallback_plan_dict(persian_goal, tools)
        tool_steps_fa = [
            s for s in plan_fa["steps"] if s.get("tool_name") == "coding_agent_delegate_task"
        ]
        assert len(tool_steps_fa) == 1
        assert tool_steps_fa[0]["tool_name"] == "coding_agent_delegate_task"

        # English prompt
        english_goal = "delegate to antigravity to implement redis adapter"
        plan_en = planner._build_fallback_plan_dict(english_goal, tools)
        tool_steps_en = [
            s for s in plan_en["steps"] if s.get("tool_name") == "coding_agent_delegate_task"
        ]
        assert len(tool_steps_en) == 1
        assert tool_steps_en[0]["tool_name"] == "coding_agent_delegate_task"

    def test_persian_and_english_git_status_terminal_intent(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Persian git status
        plan_fa = planner._build_fallback_plan_dict("وضعیت گیت را بررسی کن", tools)
        term_steps_fa = [
            s for s in plan_fa["steps"] if s.get("tool_name") == "terminal_execute_command"
        ]
        assert len(term_steps_fa) == 1
        assert term_steps_fa[0]["parameters"]["command_id"] == "git_status"

        # English git status
        plan_en = planner._build_fallback_plan_dict("check git status", tools)
        term_steps_en = [
            s for s in plan_en["steps"] if s.get("tool_name") == "terminal_execute_command"
        ]
        assert len(term_steps_en) == 1
        assert term_steps_en[0]["parameters"]["command_id"] == "git_status"

    def test_persian_and_english_filesystem_intents(self, jarvis_agent: JARVISAgent):
        planner = jarvis_agent.planner
        tools = [t.get_definition() for t in jarvis_agent.tool_registry.list_tools()]

        # Document extraction
        plan_doc = planner._build_fallback_plan_dict("استخراج متن از فایل 'report.docx'", tools)
        doc_steps = [s for s in plan_doc["steps"] if s.get("tool_name") == "file_extract_document"]
        assert len(doc_steps) == 1

        # Duplicates
        plan_dup = planner._build_fallback_plan_dict("فایل های تکراری را در پروژه پیدا کن", tools)
        dup_steps = [s for s in plan_dup["steps"] if s.get("tool_name") == "file_find_duplicates"]
        assert len(dup_steps) == 1

        # Diff / compare
        plan_diff = planner._build_fallback_plan_dict("مقایسه دو فایل کانفیگ", tools)
        diff_steps = [s for s in plan_diff["steps"] if s.get("tool_name") == "file_compare_diff"]
        assert len(diff_steps) == 1

    def test_high_risk_tool_requires_approval(self, jarvis_agent: JARVISAgent):
        delete_tool = jarvis_agent.tool_registry.get("file_delete")
        assert delete_tool is not None
        delete_def = delete_tool.get_definition()
        assert delete_def.requires_approval is True

        delegate_tool = jarvis_agent.tool_registry.get("coding_agent_delegate_task")
        assert delegate_tool is not None
        delegate_def = delegate_tool.get_definition()
        assert delegate_def.requires_approval is True
