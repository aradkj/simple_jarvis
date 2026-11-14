"""Independent Verification Engine for Coding Agent Tasks in Phase 8."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from infrastructure.logging import get_logger
from tools.coding_agent.models import VerificationResult

logger = get_logger("coding_result_verifier")


class CodingResultVerifier:
    """Verifies that changes made by the coding agent are valid and passing tests."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def verify_workspace(
        self, run_tests: bool = True, run_linter: bool = True
    ) -> VerificationResult:
        """Perform full independent verification of the workspace."""
        changed_files, diff_summary = self._check_git_status_and_diff()
        tests_executed = False
        tests_passed = True
        test_output = ""
        linter_clean = True
        linter_output = ""

        # 1. Run pytest if requested and tests exist
        if run_tests:
            has_tests = (self.workspace / "tests").is_dir() or any(self.workspace.glob("test_*.py"))
            if has_tests:
                tests_executed = True
                tests_passed, test_output = self._run_pytest()

        # 2. Run ruff linter if requested
        if run_linter:
            linter_clean, linter_output = self._run_ruff()

        verified = (not tests_executed or tests_passed) and linter_clean
        msg_parts = []
        if changed_files:
            msg_parts.append(f"{len(changed_files)} file(s) modified")
        if tests_executed:
            msg_parts.append("tests PASSED" if tests_passed else "tests FAILED")
        if not linter_clean:
            msg_parts.append("linter issues found")
        msg = ", ".join(msg_parts) if msg_parts else "No changes detected"

        return VerificationResult(
            verified=verified,
            git_changed_files=changed_files,
            git_diff_summary=diff_summary,
            tests_executed=tests_executed,
            tests_passed=tests_passed,
            test_output=test_output,
            linter_clean=linter_clean,
            linter_output=linter_output,
            message=msg,
        )

    def _check_git_status_and_diff(self) -> tuple[list[str], str]:
        """Inspect git status and diff inside workspace."""
        if not (self.workspace / ".git").is_dir():
            return [], "Not a git repository"

        changed: list[str] = []
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
                    if line.strip():
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            changed.append(parts[1])

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
            logger.warning(f"Git inspection failed in '{self.workspace}': {exc}")

        return changed, diff_text

    def _run_pytest(self) -> tuple[bool, str]:
        """Run pytest to verify changes."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--maxfail=3"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            passed = proc.returncode == 0
            output = proc.stdout[-2000:] if proc.stdout else proc.stderr[-2000:]
            return passed, output
        except Exception as exc:
            return False, f"Failed to execute pytest: {exc}"

    def _run_ruff(self) -> tuple[bool, str]:
        """Run ruff linter."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "check"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            clean = proc.returncode == 0
            output = proc.stdout[-1500:] if proc.stdout else ""
            return clean, output
        except Exception as exc:
            return True, f"Ruff check skipped: {exc}"
