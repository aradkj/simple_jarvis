"""Integration tests for Phase 4: Agent Core with Real-World System and File Tools.

Verifies end-to-end orchestration:
1. Agent plans, decomposes, and executes real system intelligence tools (CPU, Memory, Disk, Overview).
2. Agent inspects authorized files safely with path containment and secret redaction.
3. Agent gracefully reports blocked access when attempting to read outside authorized directories.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ai.base import AIResponse
from core.agent import JARVISAgent
from core.state_machine import AgentState
from tools.filesystem.path_security import get_path_security_service


def test_agent_executes_real_system_cpu_tool():
    """Agent receives prompt asking for CPU details, plans system_get_cpu_info, executes real hardware query."""
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    plan_json = json.dumps(
        {
            "goal": "Get CPU details and summarize",
            "estimated_complexity": "low",
            "completion_condition": "CPU details inspected",
            "steps": [
                {
                    "description": "Query CPU info",
                    "step_type": "tool_call",
                    "tool_name": "system_get_cpu_info",
                    "parameters": {"sample_interval_ms": 10},
                    "dependencies": [],
                },
                {
                    "description": "Summarize CPU hardware",
                    "step_type": "synthesis",
                    "tool_name": None,
                    "parameters": {},
                    "dependencies": [],
                },
            ],
        }
    )

    mock_pm.generate_text.side_effect = [
        AIResponse(text=plan_json, model="gemini-3.8-flash"),
        AIResponse(
            text="The system CPU has been verified and utilization is normal.",
            model="gemini-3.8-flash",
        ),
    ]

    agent = JARVISAgent(ai_provider=mock_pm)
    outcome = agent.process_agent_task("What is my current CPU usage and processor name?")

    assert outcome.status == "completed"
    assert agent.state == AgentState.COMPLETED
    assert len(outcome.plan.steps) == 2

    cpu_step = outcome.plan.steps[0]
    assert cpu_step.step_type.value == "tool_call"
    assert cpu_step.status.value == "completed"
    assert cpu_step.result is not None
    assert "model" in cpu_step.result
    assert "physical_cores" in cpu_step.result
    assert "logical_cores" in cpu_step.result


def test_agent_executes_real_file_inspection_in_authorized_directory(tmp_path):
    """Agent plans file_read_text on an authorized path, safely reads content, and redacts secrets."""
    # Setup temporary authorized directory
    auth_dir = tmp_path / "jarvis_notes"
    auth_dir.mkdir()
    note_file = auth_dir / "project_brief.txt"
    note_file.write_text(
        "Project Jarvis status: Phase 4 in progress. Secret key: AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6",
        encoding="utf-8",
    )

    path_sec = get_path_security_service()
    path_sec.clear_all()
    path_sec.add_directory(str(auth_dir), display_name="Notes")

    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    plan_json = json.dumps(
        {
            "goal": "Read project brief note",
            "estimated_complexity": "low",
            "completion_condition": "File read successfully",
            "steps": [
                {
                    "description": "Read text file",
                    "step_type": "tool_call",
                    "tool_name": "file_read_text",
                    "parameters": {"file_path": str(note_file)},
                    "dependencies": [],
                },
                {
                    "description": "Summarize contents",
                    "step_type": "synthesis",
                    "tool_name": None,
                    "parameters": {},
                    "dependencies": [],
                },
            ],
        }
    )

    mock_pm.generate_text.side_effect = [
        AIResponse(text=plan_json, model="gemini-3.8-flash"),
        AIResponse(
            text="The brief states Phase 4 is in progress.",
            model="gemini-3.8-flash",
        ),
    ]

    agent = JARVISAgent(ai_provider=mock_pm)
    redacted_text = "Project Jarvis status: Phase 4 in progress. Secret key: [REDACTED_API_KEY]"
    fp = path_sec.compute_content_fingerprint(redacted_text)
    agent.authorize_cloud_transmission(agent.active_session_id, "cloud_provider", fp)
    outcome = agent.process_agent_task(f"Read {note_file} and summarize")

    assert outcome.status == "completed"
    read_step = outcome.plan.steps[0]
    assert read_step.status.value == "completed"
    content = read_step.result["content"]
    assert "Phase 4 in progress" in content
    # Verify secret key was redacted
    assert "AIzaSy" not in content
    assert "[REDACTED_API_KEY]" in content

    # Clean up
    path_sec.clear_all()


def test_agent_rejects_unauthorized_file_access(tmp_path):
    """Agent attempts to read outside authorized directory; PathSecurity blocks execution."""
    unauthorized_file = tmp_path / "secret.txt"
    unauthorized_file.write_text("Top secret data", encoding="utf-8")

    # Clear authorized directories
    get_path_security_service().clear_all()

    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    plan_json = json.dumps(
        {
            "goal": "Read unauthorized file",
            "estimated_complexity": "low",
            "completion_condition": "Attempted read",
            "steps": [
                {
                    "description": "Read unauthorized file",
                    "step_type": "tool_call",
                    "tool_name": "file_read_text",
                    "parameters": {"file_path": str(unauthorized_file)},
                    "dependencies": [],
                }
            ],
        }
    )

    mock_pm.generate_text.return_value = AIResponse(text=plan_json, model="gemini-3.8-flash")

    agent = JARVISAgent(ai_provider=mock_pm)
    outcome = agent.process_agent_task(f"Read {unauthorized_file}")

    # The agent catches the unauthorized access failure, recovers via replanning, and synthesizes explanation
    assert any("Read unauthorized file" in str(s.result) for s in outcome.plan.steps)
    # The recovery synthesis step is executed so the user receives a graceful explanation
    assert outcome.status == "completed"
    assert agent.state == AgentState.COMPLETED
