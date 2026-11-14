"""Restricted Terminal Agent Package."""

from tools.terminal.command_registry import (
    CommandRegistry,
    CommandRegistryError,
    RegisteredCommand,
    get_command_registry,
)
from tools.terminal.terminal_service import (
    TerminalExecutionResult,
    TerminalService,
    get_terminal_service,
)
from tools.terminal.terminal_tools import (
    TerminalExecuteCommandTool,
    TerminalListCommandsTool,
)

__all__ = [
    "CommandRegistry",
    "CommandRegistryError",
    "RegisteredCommand",
    "TerminalExecuteCommandTool",
    "TerminalExecutionResult",
    "TerminalListCommandsTool",
    "TerminalService",
    "get_command_registry",
    "get_terminal_service",
]
