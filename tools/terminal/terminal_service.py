"""Restricted Terminal Execution Service for Phase 8.

Executes only verified registry commands via subprocess (shell=False)
with strict working directory verification, environment sanitization,
output character bounds, and execution cancellation.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.filesystem.path_security import get_path_security_service
from tools.terminal.command_registry import (
    CommandRegistryError,
    get_command_registry,
)

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("terminal_service")


@dataclass
class TerminalExecutionResult:
    """Structured result of a restricted terminal command run."""

    success: bool
    command_id: str
    args: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    working_directory: str
    truncated: bool = False
    message: str = ""
    error: str | None = None


class TerminalService:
    """Service executing pre-approved commands safely."""

    # Environment variables containing sensitive keys to redact from child environment
    SENSITIVE_ENV_VARS = {
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    }

    def __init__(self) -> None:
        self.registry = get_command_registry()
        self.security = get_path_security_service()

    def _prepare_environment(self) -> dict[str, str]:
        """Create sanitized environment copy without sensitive API keys."""
        env = dict(os.environ)
        for var in self.SENSITIVE_ENV_VARS:
            env.pop(var, None)
        # Ensure python unbuffered
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _resolve_working_directory(self, requested_cwd: str | None) -> Path:
        """Verify and resolve working directory inside authorized paths."""
        default_dir = Path.cwd().resolve()
        target = default_dir if not requested_cwd else Path(requested_cwd).resolve()

        # Check containment via path security service
        try:
            return self.security.validate_and_resolve_path(str(target))
        except PermissionError:
            # Fallback: if workspace is the root project directory itself
            if target == default_dir:
                return target
            raise

    def execute_command(
        self,
        command_id: str,
        parameters: dict[str, Any] | None = None,
        working_directory: str | None = None,
        timeout_seconds: float | None = None,
        context: ExecutionContext | None = None,
    ) -> TerminalExecutionResult:
        """Execute a registered command safely."""
        settings = get_settings()
        if not settings.terminal_enabled:
            return TerminalExecutionResult(
                success=False,
                command_id=command_id,
                args=[],
                exit_code=-1,
                stdout="",
                stderr="Terminal execution subsystem is disabled in configuration.",
                duration_ms=0.0,
                working_directory=working_directory or "",
                message="Terminal is disabled in configuration.",
            )

        params = parameters or {}

        try:
            cwd_path = self._resolve_working_directory(working_directory)
        except Exception as exc:
            return TerminalExecutionResult(
                success=False,
                command_id=command_id,
                args=[],
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=0.0,
                working_directory=working_directory or "",
                error=f"Invalid working directory: {exc}",
                message="Invalid working directory.",
            )

        try:
            args, reg_cmd = self.registry.build_command_args(command_id, params, cwd_path)
        except CommandRegistryError as reg_err:
            return TerminalExecutionResult(
                success=False,
                command_id=command_id,
                args=[],
                exit_code=-1,
                stdout="",
                stderr=str(reg_err),
                duration_ms=0.0,
                working_directory=str(cwd_path),
                error=str(reg_err),
                message=f"Command validation failed: {reg_err}",
            )

        eff_timeout = (
            min(timeout_seconds, settings.terminal_max_timeout_seconds)
            if timeout_seconds
            else settings.terminal_default_timeout_seconds
        )

        env = self._prepare_environment()
        start_time = time.perf_counter()

        logger.info(f"Executing registered terminal command '{command_id}': {args} in '{cwd_path}'")

        try:
            proc = subprocess.Popen(
                args,
                cwd=str(cwd_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )

            # Polling loop respecting cancellation and timeout
            poll_interval = 0.05
            while proc.poll() is None:
                if context and context.is_cancelled():
                    proc.kill()
                    proc.wait()
                    duration = (time.perf_counter() - start_time) * 1000
                    return TerminalExecutionResult(
                        success=False,
                        command_id=command_id,
                        args=args,
                        exit_code=-1,
                        stdout="",
                        stderr="Command execution cancelled by user.",
                        duration_ms=duration,
                        working_directory=str(cwd_path),
                        message="Command cancelled by user.",
                    )

                if (time.perf_counter() - start_time) > eff_timeout:
                    proc.kill()
                    proc.wait()
                    duration = (time.perf_counter() - start_time) * 1000
                    return TerminalExecutionResult(
                        success=False,
                        command_id=command_id,
                        args=args,
                        exit_code=-1,
                        stdout="",
                        stderr=f"Command execution timed out after {eff_timeout:.1f}s.",
                        duration_ms=duration,
                        working_directory=str(cwd_path),
                        message=f"Command timed out after {eff_timeout:.1f}s.",
                    )

                time.sleep(poll_interval)

            stdout, stderr = proc.communicate()
            duration = (time.perf_counter() - start_time) * 1000

            # Bounded output
            max_chars = settings.terminal_max_output_chars
            truncated = False
            if len(stdout) > max_chars:
                stdout = stdout[:max_chars]
                truncated = True
            if len(stderr) > max_chars:
                stderr = stderr[:max_chars]
                truncated = True

            success = proc.returncode == 0
            return TerminalExecutionResult(
                success=success,
                command_id=command_id,
                args=args,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=round(duration, 2),
                working_directory=str(cwd_path),
                truncated=truncated,
                message=f"Command '{command_id}' finished with exit code {proc.returncode}.",
            )

        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"Error executing command '{command_id}': {exc}")
            return TerminalExecutionResult(
                success=False,
                command_id=command_id,
                args=args,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=round(duration, 2),
                working_directory=str(cwd_path),
                error=str(exc),
                message=f"Subprocess execution failed: {exc}",
            )


_terminal_service_instance: TerminalService | None = None


def get_terminal_service() -> TerminalService:
    """Singleton getter for TerminalService."""
    global _terminal_service_instance
    if _terminal_service_instance is None:
        _terminal_service_instance = TerminalService()
    return _terminal_service_instance
