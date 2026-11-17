"""End-to-End Integration Tests for JARVIS Windows Personal Agent Subsystems."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.files import get_file_database, get_file_indexer
from core.planner import AgentPlanner
from tools.coding_agent import get_antigravity_adapter
from tools.windows.discovery import get_windows_app_discovery
from tools.windows.windows_service import WindowsControlService


@pytest.fixture
def mock_agent_env(tmp_path: Path):
    """Setup mock agent environment with sample files and projects."""
    project_dir = tmp_path / "pc_shop_project"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='pc-shop'\n", encoding="utf-8")
    (project_dir / "app.py").write_text("print('Shop online')\n", encoding="utf-8")

    resume_file = tmp_path / "resume_arad.pdf"
    resume_file.write_text("%PDF-1.4 sample resume content for Arad", encoding="utf-8")

    get_file_database()
    indexer = get_file_indexer()
    indexer.index_single_file(resume_file)
    indexer.index_single_file(project_dir / "app.py")

    return {
        "project_dir": project_dir,
        "resume_file": resume_file,
    }


def test_file_intelligence_project_resolution(mock_agent_env: dict[str, Path]):
    """Verify that AntigravityAdapter can resolve a project directory via File Intelligence."""
    adapter = get_antigravity_adapter()
    resolved = adapter.resolve_workspace("pc shop")
    assert resolved.exists()
    assert resolved.name in ("pc_shop_project", "jarvis") or (resolved / "pyproject.toml").exists()


def test_universal_app_discovery_live():
    """Verify live Windows application discovery catalogs real system apps."""
    disc = get_windows_app_discovery()
    apps = disc.scan_applications()
    assert len(apps) > 20

    # Ensure critical tools are discovered
    calc = disc.find_application("calculator")
    assert calc is not None

    term = disc.find_application("terminal")
    assert term is not None

    code = disc.find_application("code")
    assert code is not None


def test_windows_control_service_persian_resolution():
    """Verify WindowsControlService resolves applications requested via Persian voice commands."""
    svc = WindowsControlService()

    app_calc = svc.resolve_application("ماشین حساب")
    assert app_calc.display_name.lower() in ("calculator", "calc")

    app_term = svc.resolve_application("ترمینال")
    assert "terminal" in app_term.display_name.lower() or app_term.app_id in ("wt", "terminal")

    app_code = svc.resolve_application("وی اس کد")
    assert "code" in app_code.display_name.lower() or app_code.app_id == "code"


def test_planner_fast_path_file_and_app_intents():
    """Verify AgentPlanner generates sub-second deterministic plans for file search and app launch."""
    from unittest.mock import MagicMock

    from core.files.file_tools import FileSearchTool
    from tools.windows.application_tools import WindowsAppLaunchTool

    planner = AgentPlanner(provider_manager=MagicMock())
    tool_defs = [FileSearchTool.get_definition(), WindowsAppLaunchTool.get_definition()]

    # 1. File search intent
    plan_dict = planner._build_fallback_plan_dict(
        "رزومه‌ام کجاست",
        tool_defs,
    )
    tool_steps = [s for s in plan_dict.get("steps", []) if s.get("step_type") == "tool_call"]
    assert len(tool_steps) >= 1
    assert tool_steps[0].get("tool_name") == "file_search"

    # 2. App launch intent in Persian
    plan_dict_app = planner._build_fallback_plan_dict(
        "ماشین حساب رو باز کن",
        tool_defs,
    )
    tool_steps_app = [
        s for s in plan_dict_app.get("steps", []) if s.get("step_type") == "tool_call"
    ]
    assert len(tool_steps_app) >= 1
    assert tool_steps_app[0].get("tool_name") == "windows_app_launch"
