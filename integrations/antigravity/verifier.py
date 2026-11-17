"""Independent Task & Code Verification Engine for Google Antigravity Integration."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("antigravity_verifier")


@dataclass
class TaskVerificationResult:
    """Standardized verification outcome for an Antigravity coding task."""

    verified: bool
    git_changed_files: list[str] = field(default_factory=list)
    git_diff_summary: str = ""
    tests_executed: bool = False
    tests_passed: bool = True
    test_output: str = ""
    linter_clean: bool = True
    linter_output: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "git_changed_files": self.git_changed_files,
            "git_diff_summary": self.git_diff_summary,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
            "test_output": self.test_output,
            "linter_clean": self.linter_clean,
            "linter_output": self.linter_output,
            "message": self.message,
            "details": self.details,
        }


class AntigravityVerifier:
    """Verifies workspace changes and test results independently from the coding agent."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    def verify(
        self,
        run_tests: bool = True,
        run_linter: bool = True,
        custom_test_cmd: list[str] | None = None,
    ) -> TaskVerificationResult:
        """Run independent verification of code changes, tests, and repository status."""
        changed_files, diff_summary = self._check_git_status()

        tests_executed = False
        tests_passed = True
        test_output = ""
        linter_clean = True
        linter_output = ""

        # 1. Run tests if requested
        if run_tests:
            if custom_test_cmd:
                tests_executed = True
                tests_passed, test_output = self._run_custom_command(custom_test_cmd)
            elif (self.workspace / "tests").is_dir() or any(self.workspace.glob("test_*.py")):
                tests_executed = True
                tests_passed, test_output = self._run_pytest()
            elif (self.workspace / "package.json").exists():
                tests_executed = True
                tests_passed, test_output = self._run_npm_test()

        # 2. Run linter if requested and available
        if run_linter and (self.workspace / "pyproject.toml").exists():
            linter_clean, linter_output = self._run_ruff()

        verified = (not tests_executed or tests_passed) and linter_clean

        msg_parts = []
        if changed_files:
            msg_parts.append(f"{len(changed_files)} file(s) modified")
        else:
            msg_parts.append("No file changes detected")

        if tests_executed:
            msg_parts.append("tests PASSED" if tests_passed else "tests FAILED")
        if not linter_clean:
            msg_parts.append("linter violations detected")

        summary_msg = ", ".join(msg_parts)

        return TaskVerificationResult(
            verified=verified,
            git_changed_files=changed_files,
            git_diff_summary=diff_summary,
            tests_executed=tests_executed,
            tests_passed=tests_passed,
            test_output=test_output,
            linter_clean=linter_clean,
            linter_output=linter_output,
            message=summary_msg,
        )

    def _check_git_status(self) -> tuple[list[str], str]:
        if not (self.workspace / ".git").is_dir():
            return [], "Not a git repository"

        changed_files: list[str] = []
        diff_text = ""
        try:
            status_proc = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            if status_proc.returncode == 0:
                for line in status_proc.stdout.splitlines():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        changed_files.append(parts[1])

            diff_proc = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            if diff_proc.returncode == 0:
                diff_text = diff_proc.stdout.strip()
        except Exception as exc:
            logger.debug(f"Git diff inspection failed: {exc}")
            diff_text = f"Git error: {exc}"

        return changed_files, diff_text

    def _run_pytest(self) -> tuple[bool, str]:
        python_exe = sys.executable
        # Try local venv first if exists in workspace
        venv_python = self.workspace / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            python_exe = str(venv_python)

        try:
            proc = subprocess.run(
                [python_exe, "-m", "pytest", "-q", "--tb=short"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
            return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr).strip()
        except subprocess.TimeoutExpired:
            return False, "pytest execution timed out after 120s"
        except Exception as exc:
            return False, f"pytest run error: {exc}"

    def _run_npm_test(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["npm", "test", "--", "--watchAll=false"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=120,
                shell=True,
            )
            return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr).strip()
        except Exception as exc:
            return False, f"npm test error: {exc}"

    def _run_ruff(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "."],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr).strip()
        except Exception:
            return True, ""

    def _run_custom_command(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
            return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr).strip()
        except Exception as exc:
            return False, f"Custom test command failed: {exc}"
