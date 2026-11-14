"""Restricted Command Registry for Terminal Agent in Phase 8.

Enforces a whitelist-only command registry with typed parameters and fixed executable arrays.
Strictly prohibits arbitrary shell command execution, raw shell strings, and shell metacharacters.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.tool_proposal import RiskLevel

# Disallow shell metacharacters in any parameter value
SHELL_METACHAR_PATTERN = re.compile(r"[\&\|\;\>\<\`\$\\\n\r\x00]")


@dataclass
class RegisteredCommand:
    """Definition of an approved command in the restricted terminal registry."""

    command_id: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    builder: Callable[[dict[str, Any], Path], list[str]]
    parameter_spec: dict[str, Any] = field(default_factory=dict)


class CommandRegistryError(Exception):
    """Raised when an invalid or disallowed command is requested."""


def _validate_safe_param(val: str, name: str = "parameter") -> str:
    """Ensure parameter does not contain shell injection metacharacters."""
    if SHELL_METACHAR_PATTERN.search(val):
        raise CommandRegistryError(
            f"Dangerous shell characters detected in command parameter '{name}': '{val}'"
        )
    return val


def _build_git_status(params: dict[str, Any], workspace: Path) -> list[str]:
    short = params.get("short", False)
    cmd = ["git", "status"]
    if short:
        cmd.append("--porcelain=v1")
    return cmd


def _build_git_diff(params: dict[str, Any], workspace: Path) -> list[str]:
    staged = params.get("staged", False)
    target_path = params.get("target_path")
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    if target_path:
        safe_p = _validate_safe_param(str(target_path), "target_path")
        cmd.extend(["--", safe_p])
    return cmd


def _build_git_log(params: dict[str, Any], workspace: Path) -> list[str]:
    limit = int(params.get("limit", 10))
    limit = max(1, min(limit, 50))
    return ["git", "log", f"-n{limit}", "--oneline"]


def _build_python_env_info(params: dict[str, Any], workspace: Path) -> list[str]:
    return [sys.executable, "-V"]


def _build_pip_list(params: dict[str, Any], workspace: Path) -> list[str]:
    out_format = params.get("format", "columns")
    if out_format not in {"columns", "json", "freeze"}:
        out_format = "columns"
    return [sys.executable, "-m", "pip", "list", f"--format={out_format}"]


def _build_pip_check(params: dict[str, Any], workspace: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "check"]


def _build_run_tests(params: dict[str, Any], workspace: Path) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "-q"]
    target_test = params.get("target_test")
    if target_test:
        safe_target = _validate_safe_param(str(target_test), "target_test")
        cmd.append(safe_target)
    k_expr = params.get("filter_expression")
    if k_expr:
        safe_k = _validate_safe_param(str(k_expr), "filter_expression")
        cmd.extend(["-k", safe_k])
    return cmd


def _build_run_linter(params: dict[str, Any], workspace: Path) -> list[str]:
    cmd = [sys.executable, "-m", "ruff", "check"]
    target_path = params.get("target_path")
    if target_path:
        safe_p = _validate_safe_param(str(target_path), "target_path")
        cmd.append(safe_p)
    return cmd


def _build_run_formatter(params: dict[str, Any], workspace: Path) -> list[str]:
    check_only = params.get("check_only", True)
    cmd = [sys.executable, "-m", "ruff", "format"]
    if check_only:
        cmd.append("--check")
    target_path = params.get("target_path")
    if target_path:
        safe_p = _validate_safe_param(str(target_path), "target_path")
        cmd.append(safe_p)
    return cmd


class CommandRegistry:
    """Central registry of approved commands for the Restricted Terminal Agent."""

    def __init__(self) -> None:
        self._commands: dict[str, RegisteredCommand] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Git operations
        self.register(
            RegisteredCommand(
                command_id="git_status",
                description="Check repository working tree status.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_git_status,
                parameter_spec={"short": {"type": "boolean", "default": False}},
            )
        )
        self.register(
            RegisteredCommand(
                command_id="git_diff",
                description="View git unstaged or staged diff in current workspace.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_git_diff,
                parameter_spec={
                    "staged": {"type": "boolean", "default": False},
                    "target_path": {"type": "string", "default": None},
                },
            )
        )
        self.register(
            RegisteredCommand(
                command_id="git_log",
                description="View recent git commit log.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_git_log,
                parameter_spec={"limit": {"type": "integer", "default": 10}},
            )
        )

        # Python environment operations
        self.register(
            RegisteredCommand(
                command_id="python_env_info",
                description="Inspect active Python interpreter version and environment.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_python_env_info,
            )
        )
        self.register(
            RegisteredCommand(
                command_id="pip_list",
                description="List installed packages in active Python environment.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_pip_list,
                parameter_spec={"format": {"type": "string", "default": "columns"}},
            )
        )
        self.register(
            RegisteredCommand(
                command_id="pip_check",
                description="Verify installed packages have compatible dependencies.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_pip_check,
            )
        )

        # Testing & Code Quality operations
        self.register(
            RegisteredCommand(
                command_id="run_tests",
                description="Run pytest suite or specific test file within project workspace.",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=False,
                builder=_build_run_tests,
                parameter_spec={
                    "target_test": {"type": "string", "default": None},
                    "filter_expression": {"type": "string", "default": None},
                },
            )
        )
        self.register(
            RegisteredCommand(
                command_id="run_linter",
                description="Run ruff linter check on project workspace.",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                builder=_build_run_linter,
                parameter_spec={"target_path": {"type": "string", "default": None}},
            )
        )
        self.register(
            RegisteredCommand(
                command_id="run_formatter",
                description="Run ruff code formatter on project workspace.",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                builder=_build_run_formatter,
                parameter_spec={
                    "check_only": {"type": "boolean", "default": True},
                    "target_path": {"type": "string", "default": None},
                },
            )
        )

    def register(self, cmd: RegisteredCommand) -> None:
        self._commands[cmd.command_id] = cmd

    def get(self, command_id: str) -> RegisteredCommand | None:
        return self._commands.get(command_id)

    def list_commands(self) -> list[dict[str, Any]]:
        return [
            {
                "command_id": c.command_id,
                "description": c.description,
                "risk_level": c.risk_level.value,
                "requires_approval": c.requires_approval,
                "parameters": c.parameter_spec,
            }
            for c in self._commands.values()
        ]

    def build_command_args(
        self,
        command_id: str,
        parameters: dict[str, Any],
        workspace: Path,
    ) -> tuple[list[str], RegisteredCommand]:
        cmd = self.get(command_id)
        if not cmd:
            raise CommandRegistryError(
                f"Command '{command_id}' is not in the approved terminal command registry. "
                f"Arbitrary shell commands are strictly prohibited."
            )
        args = cmd.builder(parameters, workspace)
        return args, cmd


_command_registry_instance: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    """Singleton getter for CommandRegistry."""
    global _command_registry_instance
    if _command_registry_instance is None:
        _command_registry_instance = CommandRegistry()
    return _command_registry_instance
