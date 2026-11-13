"""Unified AI provider subsystem for JARVIS."""

from ai.base import (
    AIProviderError,
    AIResponse,
    AuthenticationError,
    BaseAIProvider,
    CapabilityNotSupportedError,
    ConnectionErrorType,
    ConnectionTestResult,
    InvalidRequestError,
    ModelCapabilities,
    ModelInfo,
    ModelNotFoundError,
    NetworkError,
    PermissionError,
    ProviderCancelledError,
    ProviderStatus,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    UnknownProviderError,
)
from ai.catalog import ModelCatalog
from ai.manager import FallbackEvent, ProviderManager
from ai.registry import ProviderRegistry, create_default_registry

__all__ = [
    "AIProviderError",
    "AIResponse",
    "AuthenticationError",
    "BaseAIProvider",
    "CapabilityNotSupportedError",
    "ConnectionErrorType",
    "ConnectionTestResult",
    "FallbackEvent",
    "InvalidRequestError",
    "ModelCapabilities",
    "ModelCatalog",
    "ModelInfo",
    "ModelNotFoundError",
    "NetworkError",
    "PermissionError",
    "ProviderCancelledError",
    "ProviderManager",
    "ProviderRegistry",
    "ProviderStatus",
    "RateLimitError",
    "ServiceUnavailableError",
    "TimeoutError",
    "UnknownProviderError",
    "create_default_registry",
]
