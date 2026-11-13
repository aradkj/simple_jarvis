"""Tool proposal models and security boundary validation for JARVIS Phase 3."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory


class RiskLevel(StrEnum):
    """Risk classification for tool proposals."""

    LOW = "low"  # Read-only information retrieval, math, format parsing
    MEDIUM = "medium"  # State queries, non-destructive status checks
    HIGH = "high"  # Modifying session state, simulated sensitive operations
    CRITICAL = "critical"  # Destructive, system-level, or unvetted actions


class ProposalStatus(StrEnum):
    """Lifecycle status of a proposed tool invocation."""

    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class ToolProposal:
    """Represents a proposed tool invocation before authorization or execution."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    status: ProposalStatus = ProposalStatus.PROPOSED
    rationale: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    approved_signature: str | None = None
    executed_at: datetime | None = None
    result: Any = None
    error: str | None = None

    def compute_signature(self) -> str:
        """Generate deterministic signature of tool name and sorted arguments."""
        clean_args = {k: v for k, v in self.arguments.items() if not str(k).startswith("_")}
        return f"{self.tool_name}:{sorted(clean_args.items())}"

    def approve(self) -> None:
        """Authorize the proposal for bounded execution."""
        if self.status in (
            ProposalStatus.REJECTED,
            ProposalStatus.CANCELLED,
            ProposalStatus.EXPIRED,
        ):
            raise ValueError(f"Cannot approve proposal in status '{self.status.value}'")
        self.status = ProposalStatus.APPROVED
        self.approved_at = datetime.now(UTC)
        self.approved_signature = self.compute_signature()

    def reject(self, reason: str = "User or policy rejected execution") -> None:
        """Deny authorization for the proposal."""
        self.status = ProposalStatus.REJECTED
        self.error = reason

    def expire(self, reason: str = "Approval request timed out") -> None:
        """Mark proposal as expired due to timeout."""
        self.status = ProposalStatus.EXPIRED
        self.error = reason

    def cancel(self, reason: str = "Execution cancelled") -> None:
        """Cancel the in-flight proposal."""
        self.status = ProposalStatus.CANCELLED
        self.error = reason

    def is_valid_approval(self) -> bool:
        """Verify proposal is approved and arguments have not been tampered with."""
        if self.status != ProposalStatus.APPROVED:
            return False
        if not self.approved_signature:
            return False
        return self.approved_signature == self.compute_signature()

    def mark_executed(self, result: Any) -> None:
        """Record successful execution result."""
        self.status = ProposalStatus.EXECUTED
        self.result = result
        self.executed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Record execution failure."""
        self.status = ProposalStatus.FAILED
        self.error = error
        self.executed_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert proposal attributes to serializable dictionary."""
        return {
            "proposal_id": self.proposal_id,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "status": self.status.value,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "error": self.error,
        }


class ToolDefinition(BaseModel):
    """Metadata schema defining a tool available to the planner."""

    name: str
    description: str
    category: PermissionCategory = PermissionCategory.SYSTEM
    risk_level: RiskLevel = RiskLevel.LOW
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False

    def to_openai_function_declaration(self) -> dict[str, Any]:
        """Format definition into standard OpenAI / Responses API function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema or {"type": "object", "properties": {}},
            },
        }

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Format definition into Gemini function declaration schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema or {"type": "object", "properties": {}},
        }
