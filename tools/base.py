"""Base tool definitions and contracts for JARVIS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from core.permissions import PermissionCategory

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class ToolExecutionStatus(StrEnum):
    """Status of a tool execution attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


@dataclass
class ToolResult:
    """Standardized result returned by a tool execution."""

    status: ToolExecutionStatus
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, data: Any = None, **metadata: Any) -> ToolResult:
        return cls(status=ToolExecutionStatus.SUCCESS, data=data, metadata=metadata)

    @classmethod
    def failed(cls, error: str, **metadata: Any) -> ToolResult:
        return cls(status=ToolExecutionStatus.FAILED, error=error, metadata=metadata)

    @classmethod
    def denied(cls, reason: str, **metadata: Any) -> ToolResult:
        return cls(status=ToolExecutionStatus.DENIED, error=reason, metadata=metadata)

    @classmethod
    def cancelled(cls, reason: str = "Execution cancelled by user", **metadata: Any) -> ToolResult:
        return cls(status=ToolExecutionStatus.CANCELLED, error=reason, metadata=metadata)

    @property
    def is_success(self) -> bool:
        return self.status == ToolExecutionStatus.SUCCESS


class BaseTool(ABC):
    """Abstract base class for all JARVIS tools."""

    name: str
    description: str
    category: PermissionCategory
    input_schema: type[BaseModel]

    # Universal Structured Capability Metadata
    operations: list[str] = []
    verification_strategy: str = "exit_code_zero"
    reversible: bool = False
    timeout_seconds: float = 30.0

    def __init__(self) -> None:
        if not hasattr(self, "name") or not self.name:
            raise ValueError(f"Tool {self.__class__.__name__} must define a unique 'name'.")
        if not hasattr(self, "description") or not self.description:
            raise ValueError(f"Tool {self.__class__.__name__} must define a 'description'.")
        if not hasattr(self, "category") or not isinstance(self.category, PermissionCategory):
            raise ValueError(f"Tool {self.__class__.__name__} must define a valid 'category'.")
        if not hasattr(self, "input_schema") or not issubclass(self.input_schema, BaseModel):
            raise ValueError(
                f"Tool {self.__class__.__name__} must define a Pydantic 'input_schema'."
            )

    def get_capabilities(self) -> dict[str, Any]:
        """Return structured capability metadata for this tool."""
        return {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "operations": getattr(self, "operations", [self.name]),
            "verification_strategy": getattr(self, "verification_strategy", "exit_code_zero"),
            "reversible": getattr(self, "reversible", False),
            "timeout_seconds": getattr(self, "timeout_seconds", 30.0),
        }

    def validate_input(self, params: dict[str, Any]) -> BaseModel:
        """Validate input parameters against the tool's schema."""
        return self.input_schema.model_validate(params)

    @abstractmethod
    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        """Execute the tool with validated parameters within the execution context."""
        raise NotImplementedError
