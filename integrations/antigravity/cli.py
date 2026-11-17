"""Google Antigravity CLI (agy.exe) Execution and Process Manager."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from config import get_settings
from infrastructure.logging import get_logger
from integrations.antigravity.lifecycle import AntigravityLifecycleTracker, TaskLifecycleState

logger = get_logger("antigravity_cli")


class AntigravityCLIError(Exception):
    """Base exception for Antigravity CLI operations."""


class AntigravityNotFoundError(AntigravityCLIError):
    """Raised when agy.exe is not found on the host system."""


class AntigravityCLI:
    """Manages finding, launching, and streaming agy CLI tasks."""

    KNOWN_SEARCH_PATHS = [
        Path(os.path.expanduser("~")) / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        Path("C:/Program Files/agy/agy.exe"),
        Path("C:/Program Files (x86)/agy/agy.exe"),
    ]

    def __init__(self, executable_path: str | Path | None = None) -> None:
        self.explicit_path = Path(executable_path) if executable_path else None
        self._active_processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def locate_executable(self) -> Path:
        """Locate agy.exe on the system."""
        if self.explicit_path and self.explicit_path.is_file():
            return self.explicit_path.resolve()

        settings = get_settings()
        if getattr(settings, "antigravity_executable_path", None):
            candidate = Path(settings.antigravity_executable_path)
            if candidate.is_file():
                return candidate.resolve()

        # Check PATH
        which_path = shutil.which("agy") or shutil.which("agy.exe")
        if which_path:
            return Path(which_path).resolve()

        # Check common paths
        for p in self.KNOWN_SEARCH_PATHS:
            if p.is_file():
                return p.resolve()

        raise AntigravityNotFoundError(
            "Google Antigravity CLI executable (agy.exe) was not found. "
            "Please verify installation or configure 'antigravity_executable_path'."
        )

    def detect_version(self) -> str:
        """Run agy --version or return detected version string."""
        try:
            exe = self.locate_executable()
            proc = subprocess.run(
                [str(exe), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
            # If --version returns non-zero, try running --help and extract
            proc_help = subprocess.run(
                [str(exe), "--help"],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            if proc_help.returncode == 0:
                for line in proc_help.stdout.splitlines()[:5]:
                    if "version" in line.lower() or "agy" in line.lower():
                        return line.strip()
                return "1.5.x"
            return "unknown"
        except Exception as exc:
            logger.debug(f"Version detection failed: {exc}")
            return "unknown"

    def is_available(self) -> bool:
        """Check if agy is installed and executable."""
        try:
            exe = self.locate_executable()
            return exe.is_file() and os.access(exe, os.X_OK)
        except Exception:
            return False

    def execute_task(
        self,
        task_id: str,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        timeout_seconds: float = 300.0,
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[int, list[str]]:
        """Execute task with agy CLI in headless/print mode and stream output."""
        tracker = AntigravityLifecycleTracker.get_instance()
        exe = self.locate_executable()

        cmd = [
            str(exe),
            "--print",
            prompt,
            "--output-format",
            "stream-json",
        ]
        if model and model != "inherit":
            cmd.extend(["--model", model])

        tracker.transition(task_id, TaskLifecycleState.STARTED, {"command": cmd})
        collected_lines: list[str] = []

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False,
            )

            with self._lock:
                self._active_processes[task_id] = proc

            start_time = time.time()

            if proc.stdout:
                for line in proc.stdout:
                    clean_line = line.strip()
                    if clean_line:
                        collected_lines.append(clean_line)
                        tracker.append_output(task_id, clean_line)
                        if on_chunk:
                            with contextlib.suppress(Exception):
                                on_chunk(clean_line)

                    if time.time() - start_time > timeout_seconds:
                        proc.terminate()
                        tracker.transition(
                            task_id, TaskLifecycleState.TIMEOUT, {"timeout": timeout_seconds}
                        )
                        return -1, collected_lines

            proc.wait(timeout=10)
            returncode = proc.returncode

            with self._lock:
                self._active_processes.pop(task_id, None)

            return returncode, collected_lines

        except subprocess.TimeoutExpired:
            self.cancel_task(task_id)
            tracker.transition(task_id, TaskLifecycleState.TIMEOUT)
            return -1, collected_lines
        except Exception as exc:
            self.cancel_task(task_id)
            logger.error(f"Error executing agy task {task_id}: {exc}")
            tracker.transition(task_id, TaskLifecycleState.FAILED, {"error": str(exc)})
            return -1, collected_lines

    def cancel_task(self, task_id: str) -> bool:
        """Cancel an in-flight agy process."""
        with self._lock:
            proc = self._active_processes.get(task_id)
            if not proc:
                return False

            try:
                proc.terminate()
                # On Windows, try taskkill if process doesn't exit immediately
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        timeout=5,
                        shell=False,
                    )
            except Exception as exc:
                logger.warning(f"Error terminating agy process for task {task_id}: {exc}")

            self._active_processes.pop(task_id, None)

        tracker = AntigravityLifecycleTracker.get_instance()
        tracker.transition(task_id, TaskLifecycleState.CANCELLED)
        return True
