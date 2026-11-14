"""Process Manager for Google Antigravity CLI Execution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.coding_agent.exceptions import AntigravityNotFoundError, TaskExecutionError

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("coding_process_manager")


class AntigravityProcessManager:
    """Manages spawning, streaming, and monitoring agy.exe processes."""

    COMMON_AGY_PATHS = [
        Path(os.path.expanduser("~")) / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        Path("C:/Program Files/agy/agy.exe"),
    ]

    def __init__(self, executable_path: str | None = None) -> None:
        self.explicit_path = executable_path

    def locate_executable(self) -> Path:
        """Find the agy executable on the host system."""
        settings = get_settings()

        # 1. Configured explicit path
        if self.explicit_path:
            candidate = Path(self.explicit_path)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()
            raise AntigravityNotFoundError(
                f"Configured Antigravity executable path not found: '{self.explicit_path}'"
            )

        if settings.antigravity_executable_path:
            candidate = Path(settings.antigravity_executable_path)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()
            raise AntigravityNotFoundError(
                f"Configured Antigravity executable path not found: '{settings.antigravity_executable_path}'"
            )

        # 2. PATH resolution
        which_path = shutil.which("agy") or shutil.which("agy.exe")
        if which_path:
            return Path(which_path).resolve()

        # 3. Known installation locations
        for common_p in self.COMMON_AGY_PATHS:
            if common_p.is_file():
                return common_p.resolve()

        raise AntigravityNotFoundError(
            "Google Antigravity CLI (agy.exe) could not be found. "
            "Please ensure agy is installed and added to PATH, or configure antigravity_executable_path."
        )

    def check_health(self) -> dict[str, Any]:
        """Verify agy installation and return version / model info."""
        try:
            exe_path = self.locate_executable()
            proc = subprocess.run(
                [str(exe_path), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            available = proc.returncode == 0
            return {
                "installed": True,
                "executable_path": str(exe_path),
                "healthy": available,
                "return_code": proc.returncode,
            }
        except Exception as exc:
            return {
                "installed": False,
                "executable_path": None,
                "healthy": False,
                "error": str(exc),
            }

    def execute_stream(
        self,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        conversation_id: str | None = None,
        timeout_seconds: float | None = None,
        line_callback: Callable[[str], None] | None = None,
        context: ExecutionContext | None = None,
    ) -> tuple[int, list[str], str, float]:
        """Spawn agy.exe with NDJSON streaming and yield lines in real-time.

        Returns:
            (exit_code, stdout_lines, stderr_text, duration_seconds)
        """
        exe_path = self.locate_executable()
        settings = get_settings()

        cmd = [str(exe_path), "-p", prompt, "--output-format", "stream-json"]

        # Configure session-only allowed tools for headless delegation without modifying global settings
        session_settings = json.dumps(
            {"permissions": {"allow": ["command(*)", "edit(*)", "read(*)"]}}
        )
        cmd.extend(["--settings", session_settings])

        eff_model = model or settings.antigravity_default_model
        if eff_model:
            cmd.extend(["--model", eff_model])

        if conversation_id:
            cmd.extend(["--conversation", conversation_id])

        eff_timeout = timeout_seconds or settings.antigravity_timeout_seconds
        start_time = time.perf_counter()

        logger.info(f"Launching Antigravity task in '{workspace}': model={eff_model}")

        # Sanitized environment
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(workspace),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                bufsize=1,  # Line buffered
            )

            stdout_lines: list[str] = []

            # Stream reader loop
            while True:
                if context and context.is_cancelled():
                    proc.kill()
                    proc.wait()
                    raise TaskExecutionError("Antigravity task cancelled by user.")

                elapsed = time.perf_counter() - start_time
                if elapsed > eff_timeout:
                    proc.kill()
                    proc.wait()
                    raise TaskExecutionError(
                        f"Antigravity task timed out after {eff_timeout:.1f} seconds."
                    )

                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.02)
                    continue

                stdout_lines.append(line)
                if line_callback:
                    try:
                        line_callback(line)
                    except Exception as cb_err:
                        logger.warning(f"Error in stream line callback: {cb_err}")

            stderr_text = proc.stderr.read() if proc.stderr else ""
            exit_code = proc.wait()
            duration = time.perf_counter() - start_time

            logger.info(
                f"Antigravity process finished: exit={exit_code}, lines={len(stdout_lines)}, duration={duration:.2f}s"
            )
            return exit_code, stdout_lines, stderr_text, duration

        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.error(f"Failed to execute Antigravity process: {exc}")
            raise TaskExecutionError(f"Antigravity execution failed: {exc}") from exc
