"""Base AI provider abstractions for JARVIS."""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.execution_context import CancellationToken
from memory.base import ConversationMessage


class ProviderStatus(StrEnum):
    """Operational status of an AI provider."""

    NOT_CONFIGURED = "not_configured"
    READY = "ready"
    CONNECTING = "connecting"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class ConnectionErrorType(StrEnum):
    """Categorized result types for AI connectivity tests."""

    SUCCESS = "success"
    MISSING_API_KEY = "missing_api_key"
    INVALID_API_KEY = "invalid_api_key"
    AUTH_FAILURE = "auth_failure"
    MODEL_NOT_FOUND = "model_not_found"
    QUOTA_EXCEEDED = "quota_exceeded"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ConnectionTestResult:
    """Result of an AI provider connectivity check."""

    is_success: bool
    message: str
    error_type: ConnectionErrorType = ConnectionErrorType.SUCCESS
    latency_ms: float | None = None


@dataclass
class ModelCapabilities:
    """Explicit capability declarations for an AI model."""

    streaming_supported: bool = True
    structured_output_supported: bool = False
    tool_calling_supported: bool = False
    vision_supported: bool = False
    context_window: int = 128000
    maximum_output_tokens: int = 4096


class LifecycleStatus(StrEnum):
    """Lifecycle stages for AI models according to official vendor documentation."""

    ACTIVE = "ACTIVE"
    PREVIEW = "PREVIEW"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    TIER_RESTRICTED = "TIER_RESTRICTED"
    LEGACY = "LEGACY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, value: str | LifecycleStatus | None) -> LifecycleStatus:
        """Normalize string or existing enum to LifecycleStatus without breaking hash/equality semantics."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            return cls.UNKNOWN
        val = value.strip().upper()
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class ModelInfo:
    """Metadata describing an AI model in the catalog."""

    provider_id: str
    model_id: str
    display_name: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    is_deprecated: bool = False
    is_preview: bool = False
    lifecycle_status: str = "ACTIVE"
    provider_availability: bool = True
    account_availability: str = "public"
    endpoint_type: str = "chat_completions"  # "chat_completions", "messages", "generate_content"
    replacement_model_id: str | None = None
    documentation_url: str | None = None
    verified_at: str = "2026-11-12"
    verification_date: str = "2026-11"

    def __post_init__(self) -> None:
        self.lifecycle_status = LifecycleStatus.from_str(self.lifecycle_status)
        if self.lifecycle_status in (LifecycleStatus.DEPRECATED, LifecycleStatus.RETIRED):
            self.is_deprecated = True
            if self.lifecycle_status == LifecycleStatus.RETIRED:
                self.provider_availability = False
        elif self.lifecycle_status == LifecycleStatus.PREVIEW:
            self.is_preview = True
        elif self.lifecycle_status == LifecycleStatus.TIER_RESTRICTED:
            self.account_availability = "tier_restricted"

        if self.verified_at and not self.verification_date:
            self.verification_date = self.verified_at
        elif self.verification_date and not self.verified_at:
            self.verified_at = self.verification_date


@dataclass
class ToolCall:
    """Represents a tool or function call emitted by an AI model."""

    call_id: str
    function_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""
    error: str | None = None
    response_id: str | None = None


@dataclass
class AIResponse:
    """Standardized response from an AI provider."""

    text: str
    raw_response: Any = None
    finish_reason: str | None = None
    model: str | None = None
    provider_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    parsed_tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    is_incomplete: bool = False
    error: Any = None

    @property
    def content(self) -> str:
        """Alias for backward compatibility with callers accessing .content."""
        return self.text


# --- Normalized Provider Error Taxonomy ---


class AIProviderError(Exception):
    """Base exception for all AI provider operations."""

    def __init__(
        self, message: str, provider_id: str = "", raw_error: Exception | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_id = provider_id
        self.raw_error = raw_error


class AuthenticationError(AIProviderError):
    """Raised when provider credentials (API key/token) are invalid or missing."""


class PermissionError(AIProviderError, builtins.PermissionError):
    """Raised when access is forbidden or permissions are denied."""


class PrivacyViolationError(PermissionError):
    """Raised when request routing violates configured privacy constraints."""


class RateLimitError(AIProviderError):
    """Raised when provider rate limits or quotas are exceeded (HTTP 429)."""


class ModelNotFoundError(AIProviderError):
    """Raised when the requested model is not found or unavailable."""


class InvalidRequestError(AIProviderError):
    """Raised when the request parameters or schema are malformed."""


class CapabilityNotSupportedError(AIProviderError):
    """Raised when the selected model/provider does not support a required capability."""


class ServiceUnavailableError(AIProviderError):
    """Raised when the provider endpoint returns 500, 502, 503, 504, or is overloaded."""


class NetworkError(AIProviderError):
    """Raised when network transport or DNS fails."""


class TimeoutError(AIProviderError):
    """Raised when a request to the provider times out."""


class ProviderCancelledError(AIProviderError):
    """Raised when generation is aborted by user cancellation."""


class UnknownProviderError(AIProviderError):
    """Raised when an unregistered or unknown provider is requested."""


class BaseAIProvider(ABC):
    """Abstract contract for AI providers in JARVIS."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'google-gemini')."""
        raise NotImplementedError

    @property
    def provider_id(self) -> str:
        """Short stable identifier of the provider (e.g. 'gemini', 'openai')."""
        return self.provider_name.replace("google-", "")

    @property
    def default_model(self) -> str:
        """Default model identifier for this provider."""
        return ""

    def list_supported_models(self) -> list[ModelInfo]:
        """Return list of supported models with their declared capabilities."""
        return []

    def get_model_capabilities(self, model_id: str) -> ModelCapabilities:
        """Return capabilities for a specific model."""
        for m in self.list_supported_models():
            if m.model_id == model_id:
                return m.capabilities
        return ModelCapabilities()

    def validate_capability(self, capability: str, model_id: str | None = None) -> None:
        """Validate whether the specified or default model supports the required capability."""
        target_model = model_id or self.default_model
        caps = self.get_model_capabilities(target_model)
        attr = f"{capability}_supported"
        if hasattr(caps, attr):
            if not getattr(caps, attr):
                raise CapabilityNotSupportedError(
                    f"Model '{target_model}' under provider '{self.provider_id}' does not support required capability '{capability}'.",
                    provider_id=self.provider_id,
                )
        elif hasattr(caps, capability) and not getattr(caps, capability):
            raise CapabilityNotSupportedError(
                f"Model '{target_model}' under provider '{self.provider_id}' does not support required capability '{capability}'.",
                provider_id=self.provider_id,
            )

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if provider credentials and endpoints are valid and configured."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Get the current operational status of the provider."""
        raise NotImplementedError

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """Perform a minimal live request to verify connectivity and credentials."""
        raise NotImplementedError

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate a complete text response from a prompt and optional conversation history."""
        raise NotImplementedError

    @abstractmethod
    def stream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream text tokens as they become available."""
        raise NotImplementedError

    async def astream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Asynchronously stream text tokens."""
        raise NotImplementedError
