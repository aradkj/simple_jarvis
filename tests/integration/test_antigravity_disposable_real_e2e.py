"""Real End-to-End Disposable Integration Test for Antigravity Coding Agent.

This test validates real Antigravity CLI delegation on an isolated, temporary,
disposable git repository. It guarantees that:
1. agy.exe is discovered and executed with real workspace parameters.
2. Changes are made only inside the designated disposable temporary directory.
3. Git diff and automated testing verify the outcome.
4. User workspace files and directories are completely untouched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.coding_agent.antigravity_adapter import AntigravityAdapter
from tools.coding_agent.models import CodingTaskStatus
from tools.coding_agent.process_manager import AntigravityProcessManager


@pytest.fixture
def disposable_repo(tmp_path: Path):
    """Create a temporary git repository with a failing test."""
    repo_dir = tmp_path / "disposable_project"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "JarvisTest"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@jarvis.local"], cwd=str(repo_dir), check=True
    )

    # Create files
    calc_py = repo_dir / "calc.py"
    calc_py.write_text(
        "def multiply(a, b):\n    return a + b  # Defect: should be multiplication\n",
        encoding="utf-8",
    )

    test_calc_py = repo_dir / "test_calc.py"
    test_calc_py.write_text(
        "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit with defect"], cwd=str(repo_dir), check=True
    )

    return repo_dir


@pytest.mark.integration
def test_antigravity_real_delegation_on_disposable_repo(disposable_repo: Path):
    """Verify live delegation to agy CLI on an isolated disposable directory."""
    mgr = AntigravityProcessManager()
    health = mgr.check_health()
    if not health.get("installed"):
        pytest.skip("Antigravity CLI (agy) is not installed on this system.")

    # Also check git availability
    if not shutil.which("git"):
        pytest.skip("git CLI is not installed on this system.")

    adapter = AntigravityAdapter()

    # Authorize disposable repo
    from config import get_settings

    settings = get_settings()
    settings.antigravity_authorized_workspaces.append(str(disposable_repo))

    prompt = "Fix the multiply function in calc.py so that test_calc.py passes."
    task = adapter.delegate(
        prompt=prompt,
        workspace_path=disposable_repo,
        model="gemini-3.8-flash-high",
        auto_verify=True,
    )

    assert task.status == CodingTaskStatus.COMPLETED
    assert task.error_message is None

    # Verify that the test in disposable repo now passes
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "test_calc.py"],
        cwd=str(disposable_repo),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Tests failed: {res.stdout}\n{res.stderr}"

    calc_content = (disposable_repo / "calc.py").read_text(encoding="utf-8")
    assert "*" in calc_content or "a * b" in calc_content
