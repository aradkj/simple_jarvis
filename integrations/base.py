"""Universal Tool and Integration Contract for the JARVIS Universal Integration Hub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class ConnectionState(StrEnum):
    """Network and operational connection states for integrations."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


class AuthState(StrEnum):
    """Authentication and credential states for integrations."""

    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    REVOKED = "revoked"


class HealthState(StrEnum):
    """Overall operational health state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class IntegrationRiskLevel(StrEnum):
    """Risk classification for operations supported by integrations."""

    READ_ONLY = "read_only"
    LOW_RISK = "low_risk"
    MODERATE_RISK = "moderate_risk"
    HIGH_RISK = "high_risk"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """Result of an integration health check."""

    healthy: bool
    state: HealthState
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class OperationDefinition:
    """Definition and metadata of an individual operation supported by an integration."""

    name: str
    description: str
    risk_level: IntegrationRiskLevel = IntegrationRiskLevel.LOW_RISK
    required_permissions: list[str] = field(default_factory=list)
    input_schema: type[BaseModel] | dict[str, Any] | None = None
    timeout_seconds: float = 60.0
    idempotent: bool = False
    requires_approval: bool = False


@dataclass
class IntegrationCapabilities:
    """Declared capabilities, operations, and metadata for an integration."""

    integration_id: str
    name: str
    version: str
    description: str
    operations: dict[str, OperationDefinition] = field(default_factory=dict)
    supported_protocols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationResult:
    """Standardized result returned by an integration execution."""

    success: bool
    data: Any = None
    error: str | None = None
    operation: str = ""
    integration_id: str = ""
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def ok(
        cls, data: Any = None, operation: str = "", integration_id: str = "", **metadata: Any
    ) -> IntegrationResult:
        return cls(
            success=True,
            data=data,
            operation=operation,
            integration_id=integration_id,
            metadata=metadata,
        )

    @classmethod
    def fail(
        cls, error: str, operation: str = "", integration_id: str = "", **metadata: Any
    ) -> IntegrationResult:
        return cls(
            success=False,
            error=error,
            operation=operation,
            integration_id=integration_id,
            metadata=metadata,
        )


class UniversalIntegration(ABC):
    """Abstract Base Class defining the Universal Tool Contract for all JARVIS Integrations."""

    integration_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""

    def __init__(self) -> None:
        self._connection_state = ConnectionState.DISCONNECTED
        self._auth_state = AuthState.UNAUTHENTICATED
        self._health_state = HealthState.UNKNOWN
        self._last_error: str | None = None
        self._last_connected_at: datetime | None = None

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    @property
    def auth_state(self) -> AuthState:
        return self._auth_state

    @property
    def health_state(self) -> HealthState:
        return self._health_state

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_connected_at(self) -> datetime | None:
        return self._last_connected_at

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection or session with the external service or application."""
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Terminate connection or session cleanly."""
        ...

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Perform an active health and availability verification."""
        ...

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status information for UI and monitoring."""
        ...

    @abstractmethod
    def get_capabilities(self) -> IntegrationCapabilities:
        """Return declared capabilities, supported operations, and permission requirements."""
        ...

    @abstractmethod
    def execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> IntegrationResult:
        """Execute a supported operation with safety, timeout, and cancellation boundaries."""
        ...

    @abstractmethod
    def cancel(self, operation_id: str) -> bool:
        """Cancel an in-flight operation or task."""
        ...

    def validate_input(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        """Validate input parameters against the operation schema."""
        caps = self.get_capabilities()
        op_def = caps.operations.get(operation)
        if not op_def:
            raise ValueError(
                f"Unknown operation '{operation}' on integration '{self.integration_id}'."
            )
        if op_def.input_schema and issubclass(op_def.input_schema, BaseModel):
            validated = op_def.input_schema.model_validate(params)
            return validated.model_dump()
        return params

    def validate_output(self, operation: str, result: Any) -> bool:
        """Validate operation outcome format."""
        return True
