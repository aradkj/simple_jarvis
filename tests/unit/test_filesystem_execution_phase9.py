"""Unit and integration test suite for JARVIS Phase 9 Real Filesystem Tool Execution,
Dynamic Windows Desktop Path Resolution, Persian Understanding & British Voice Identity,
and Cloud TTS Privacy Consent Controls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from config import Settings
from core.agent import JARVISAgent
from core.execution_context import ExecutionContext
from core.personality import JarvisPersonalityEngine
from core.planner import AgentPlanner
from core.tool_proposal import RiskLevel, ToolDefinition
from infrastructure.paths import get_desktop_dir
from tools.filesystem.file_service import FileService
from tools.filesystem.file_tools import FileWriteTextInput, FileWriteTextTool
from tools.filesystem.path_security import PathSecurityService
from tools.voice.models import TTSRequest
from tools.voice.tts_service import BritishNeuralTTSService


@pytest.fixture
def mock_desktop_env(tmp_path: Path):
    """Fixture providing an isolated mock desktop directory and clean path security store."""
    desktop_dir = tmp_path / "MockDesktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    sec_store = tmp_path / "authorized_dirs.json"
    sec = PathSecurityService(storage_path=sec_store)
    sec.clear_all()
    sec.add_directory(str(desktop_dir), display_name="Desktop")

    with patch("infrastructure.paths.get_desktop_dir", return_value=desktop_dir):
        yield desktop_dir, sec


# ==============================================================================
# 1. Dynamic Windows Desktop Path Resolution
# ==============================================================================


def test_get_desktop_dir_resolution() -> None:
    """Verify get_desktop_dir resolves dynamically without hardcoded usernames."""
    desktop = get_desktop_dir()
    assert isinstance(desktop, Path)
    assert desktop.is_absolute()
    # Must exist or resolve to valid home subdirectory
    assert "desktop" in str(desktop).lower()


# ==============================================================================
# 2. Planner Intent Recognition for File Creation & Desktop Operations
# ==============================================================================


def test_planner_detects_desktop_html_file_creation(mock_desktop_env) -> None:
    """Verify planner decomposes user request into file_write_text with desktop path and valid HTML."""
    desktop_dir, _ = mock_desktop_env
    settings = Settings(gemini_api_key=SecretStr("mock"))
    planner = AgentPlanner(provider_manager=MagicMock(), settings=settings)

    tools = [
        ToolDefinition(
            name="file_write_text",
            description="Write text file",
            category="file_write",
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        )
    ]

    goal = "Create a simple HTML file on my Windows Desktop named test.html."
    ctx = ExecutionContext()
    plan = planner.create_plan(goal=goal, context=ctx, available_tools=tools)

    tool_steps = [s for s in plan.steps if s.tool_name == "file_write_text"]
    assert len(tool_steps) == 1, "Expected exactly 1 file_write_text step in plan"

    step = tool_steps[0]
    expected_path = (desktop_dir / "test.html").resolve()
    assert Path(step.parameters["file_path"]).resolve() == expected_path
    assert step.parameters.get("overwrite") is True
    assert "<!DOCTYPE html>" in step.parameters["content"]
    assert "<h1>Hello from JARVIS</h1>" in step.parameters["content"]


def test_planner_detects_persian_desktop_file_creation(mock_desktop_env) -> None:
    """Verify planner understands Persian requests to create desktop files."""
    desktop_dir, _ = mock_desktop_env
    settings = Settings(gemini_api_key=SecretStr("mock"))
    planner = AgentPlanner(provider_manager=MagicMock(), settings=settings)

    tools = [
        ToolDefinition(
            name="file_write_text",
            description="Write text file",
            category="file_write",
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={},
        )
    ]

    goal = "یک فایل html ساده روی دسکتاپ به نام test.html ایجاد کن"
    ctx = ExecutionContext()
    plan = planner.create_plan(goal=goal, context=ctx, available_tools=tools)

    tool_steps = [s for s in plan.steps if s.tool_name == "file_write_text"]
    assert len(tool_steps) == 1

    step = tool_steps[0]
    assert Path(step.parameters["file_path"]).resolve() == (desktop_dir / "test.html").resolve()
    assert "<!DOCTYPE html>" in step.parameters["content"]


def test_planner_detects_custom_content_file_creation(mock_desktop_env) -> None:
    """Verify planner extracts user-provided content from request."""
    desktop_dir, _ = mock_desktop_env
    settings = Settings(gemini_api_key=SecretStr("mock"))
    planner = AgentPlanner(provider_manager=MagicMock(), settings=settings)

    tools = [
        ToolDefinition(
            name="file_write_text",
            description="Write text file",
            category="file_write",
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={},
        )
    ]

    goal = "Make a file on desktop called notes.txt with content Hello World"
    ctx = ExecutionContext()
    plan = planner.create_plan(goal=goal, context=ctx, available_tools=tools)

    tool_steps = [s for s in plan.steps if s.tool_name == "file_write_text"]
    assert len(tool_steps) == 1
    step = tool_steps[0]
    assert Path(step.parameters["file_path"]).resolve() == (desktop_dir / "notes.txt").resolve()
    assert "Hello World" in step.parameters["content"]


# ==============================================================================
# 3. Path Security Containment & Reparse/Sensitive Protection
# ==============================================================================


def test_path_security_scopes_desktop_target_without_permanent_expansion(tmp_path: Path) -> None:
    """Verify validate_and_resolve_path validates Desktop targets for that operation only
    without silently adding Desktop to permanent authorized directories (Strict Default-Deny).
    """
    desktop_dir = tmp_path / "TestDesktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    sec_file = tmp_path / "auth_store.json"
    sec = PathSecurityService(storage_path=sec_file)
    sec.clear_all()
    assert len(sec.list_authorized_directories()) == 0

    with patch("infrastructure.paths.get_desktop_dir", return_value=desktop_dir):
        target = desktop_dir / "test.html"
        resolved = sec.validate_and_resolve_path(str(target))
        assert resolved == target.resolve()
        # Crucial security verification: Persistent authorized directories store is NOT silently expanded
        assert len(sec.list_authorized_directories()) == 0


def test_file_write_input_rejects_conflicting_aliases() -> None:
    """Verify FileWriteTextInput rejects conflicting path or content aliases with ValueError."""
    # Conflicting paths: 'file_path' and 'path' point to different targets
    with pytest.raises(ValueError, match="Ambiguous conflicting path parameters"):
        FileWriteTextInput.model_validate(
            {"file_path": "C:\\Desktop\\a.html", "path": "C:\\Desktop\\b.html", "content": "hello"}
        )

    # Conflicting contents: 'content' and 'text' provide different payloads
    with pytest.raises(ValueError, match="Ambiguous conflicting content parameters"):
        FileWriteTextInput.model_validate(
            {"path": "C:\\Desktop\\a.html", "content": "text_one", "text": "text_two"}
        )

    # Consistent aliases (same target) resolve cleanly
    inp = FileWriteTextInput.model_validate(
        {"file_path": "C:\\Desktop\\a.html", "path": "C:\\Desktop\\a.html", "content": "hello"}
    )
    assert inp.file_path == "C:\\Desktop\\a.html"
    assert inp.content == "hello"


def test_path_security_blocks_traversal_and_sensitive_files(mock_desktop_env) -> None:
    """Verify traversal and sensitive patterns (.env, keys) are strictly denied."""
    desktop_dir, sec = mock_desktop_env

    # 1. Path traversal escape
    traversal_path = str(desktop_dir / ".." / "unauthorized" / "file.txt")
    with pytest.raises(PermissionError, match="outside all authorized directories"):
        sec.validate_and_resolve_path(traversal_path)

    # 2. Sensitive credential file
    sensitive_path = str(desktop_dir / ".env")
    with pytest.raises(PermissionError, match="matches protected secret/credential denylist"):
        sec.validate_and_resolve_path(sensitive_path)

    # 3. UNC share
    unc_path = r"\\malicious-share\desktop\test.html"
    with pytest.raises(PermissionError, match="Network shares and UNC paths are prohibited"):
        sec.validate_and_resolve_path(unc_path)


# ==============================================================================
# 4. FileWriteTextInput Normalization & Tool Execution
# ==============================================================================


def test_file_write_input_alias_normalization() -> None:
    """Verify FileWriteTextInput normalizes path/target_path and text/body aliases."""
    inp1 = FileWriteTextInput.model_validate({"path": "C:\\Desktop\\test.html", "content": "hello"})
    assert inp1.file_path == "C:\\Desktop\\test.html"
    assert inp1.content == "hello"

    inp2 = FileWriteTextInput.model_validate(
        {"target_path": "C:\\Desktop\\test.html", "text": "hello"}
    )
    assert inp2.file_path == "C:\\Desktop\\test.html"
    assert inp2.content == "hello"


def test_real_file_write_tool_execution(mock_desktop_env) -> None:
    """Verify FileWriteTextTool writes atomically and verifies file on disk."""
    desktop_dir, _ = mock_desktop_env
    target_file = desktop_dir / "test.html"
    html_content = "<!DOCTYPE html><html><body><h1>JARVIS Certification</h1></body></html>"

    with patch("tools.filesystem.file_tools.get_file_service") as mock_get_svc:
        real_svc = FileService(security_service=mock_desktop_env[1])
        mock_get_svc.return_value = real_svc

        tool = FileWriteTextTool()
        ctx = ExecutionContext()
        params = FileWriteTextInput(
            file_path=str(target_file),
            content=html_content,
            overwrite=True,
        )

        res = tool.execute(params, ctx)
        assert res.status.value == "success"
        assert res.data["verified"] is True
        assert res.data["bytes_written"] == len(html_content.encode("utf-8"))

        # Verify on actual disk
        assert target_file.exists()
        assert target_file.stat().st_size > 0
        assert target_file.read_text(encoding="utf-8") == html_content


# ==============================================================================
# 5. End-to-End Autonomous Agent Execution & Truthful Spoken Response
# ==============================================================================


def test_autonomous_desktop_html_file_creation_e2e(tmp_path: Path) -> None:
    """Verify full orchestration: User prompt -> AgentPlanner -> FileWriteTextTool -> Verified file on disk."""
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    sec_store = tmp_path / "auth_dirs.json"
    sec = PathSecurityService(storage_path=sec_store)
    sec.clear_all()
    sec.add_directory(str(desktop_dir), display_name="Desktop")

    with (
        patch("infrastructure.paths.get_desktop_dir", return_value=desktop_dir),
        patch("tools.filesystem.path_security.get_path_security_service", return_value=sec),
        patch(
            "tools.filesystem.file_service.get_file_service",
            return_value=FileService(security_service=sec),
        ),
    ):
        settings = Settings(
            app_name="JARVIS",
            default_provider="gemini",
            gemini_api_key=SecretStr("mock_key"),
            agent_mode="autonomous",
            file_modification_enabled=True,
            data_dir=tmp_path / "data",
        )
        mock_ai = MagicMock()
        mock_ai.is_ready.return_value = True
        mock_ai.generate_text.side_effect = Exception("offline test mode")

        agent = JARVISAgent(settings=settings, ai_provider=mock_ai)
        agent.initialize()

        outcome = agent.process_agent_task(
            "Create a simple HTML file on my Windows Desktop named test.html."
        )

        assert outcome.status == "completed"
        created_file = desktop_dir / "test.html"
        assert created_file.exists()
        assert created_file.stat().st_size > 0
        assert "<!DOCTYPE html>" in created_file.read_text(encoding="utf-8")

        # Verify British spoken response generation preserves file name and persona
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=outcome.final_response,
            user_prompt="Create a simple HTML file on my Windows Desktop named test.html.",
        )
        assert "test.html" in spoken
        assert "Desktop" in spoken
        assert spoken.startswith("Certainly, sir.")


# ==============================================================================
# 6. Spoken English Generation Preserves Metrics and Tone
# ==============================================================================


def test_spoken_response_preserves_cpu_and_ram_metrics() -> None:
    """Verify format_spoken_response_en extracts and preserves numerical metrics."""
    # CPU query in Persian
    cpu_spoken = JarvisPersonalityEngine.format_spoken_response_en(
        text="میزان استفاده از پردازنده در حال حاضر 19.5% است.",
        user_prompt="وضعیت cpu چقدره؟",
    )
    assert "19.5%" in cpu_spoken
    assert "CPU" in cpu_spoken
    assert "Certainly, sir." in cpu_spoken

    # RAM query in Persian
    ram_spoken = JarvisPersonalityEngine.format_spoken_response_en(
        text="حافظه رم در وضعیت عادی و مصرف 64% است.",
        user_prompt="وضعیت رم چقدره؟",
    )
    assert "64%" in ram_spoken
    assert "memory" in ram_spoken.lower()


# ==============================================================================
# 7. Cloud TTS Consent Privacy Controls
# ==============================================================================


def test_cloud_tts_consent_default_and_enforcement() -> None:
    """Verify voice_cloud_tts_consent defaults to False and blocks cloud dispatch."""
    settings = Settings(voice_cloud_tts_consent=False, voice_tts_engine="azure_neural")
    assert settings.voice_cloud_tts_consent is False

    mock_fallback = MagicMock()
    service = BritishNeuralTTSService(
        engine_name="azure_neural",
        fallback_engine=mock_fallback,
    )
    service.settings = settings

    assert service.has_cloud_tts_consent() is False

    # Calling speak without consent must fall back to local SAPI
    req = TTSRequest(text="Hello sir", voice_name="en-GB-RyanNeural")
    service.speak(req)
    mock_fallback.speak.assert_called_once_with(req)


def test_cloud_tts_consent_opt_in_and_revocation() -> None:
    """Verify explicit opt-in enables cloud TTS and revocation immediately blocks it."""
    settings = Settings(voice_cloud_tts_consent=True, voice_tts_engine="azure_neural")
    service = BritishNeuralTTSService(engine_name="azure_neural")
    service.settings = settings

    assert service.has_cloud_tts_consent() is True

    # Revoke consent at runtime
    settings.voice_cloud_tts_consent = False
    assert service.has_cloud_tts_consent() is False
