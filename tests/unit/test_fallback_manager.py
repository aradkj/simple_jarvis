"""Unit tests for ProviderManager routing, session isolation, and intelligent dual fallback."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import (
    AIResponse,
    AuthenticationError,
    ProviderCancelledError,
    RateLimitError,
    ServiceUnavailableError,
)
from ai.manager import ProviderManager
from ai.registry import ProviderRegistry
from config import Settings
from core.execution_context import CancellationToken


@pytest.fixture
def fallback_settings() -> Settings:
    return Settings(
        default_provider="gemini",
        enable_auto_fallback=True,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=True,
        fallback_provider_order=["gemini", "groq", "openai"],
        gemini_api_key=SecretStr("AIzaSyMockGeminiKey"),
        groq_api_key=SecretStr("gsk_MockGroqKey"),
        openai_api_key=SecretStr("sk-MockOpenAIKey"),
    )


def test_provider_manager_default_routing(fallback_settings: Settings) -> None:
    """Verify ProviderManager routes to configured default provider."""
    manager = ProviderManager(settings=fallback_settings)
    assert manager.get_active_provider_id() == "gemini"


def test_provider_manager_per_session_override(fallback_settings: Settings) -> None:
    """Verify session routing isolates conversations to their specific selected provider."""
    manager = ProviderManager(settings=fallback_settings)

    manager.set_session_provider("session-A", "openai")
    manager.set_session_provider("session-B", "groq")

    assert manager.get_active_provider_id("session-A") == "openai"
    assert manager.get_active_provider_id("session-B") == "groq"
    # Unspecified session defaults to global default
    assert manager.get_active_provider_id("session-C") == "gemini"

    manager.clear_session_provider("session-A")
    assert manager.get_active_provider_id("session-A") == "gemini"


def test_provider_manager_auto_fallback_on_503(fallback_settings: Settings) -> None:
    """Verify retryable 503 error on primary triggers automatic fallback to secondary provider."""
    mock_gemini = MagicMock()
    mock_gemini.provider_name = "google-gemini"
    mock_gemini.provider_id = "gemini"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError(
        "503 Overloaded", provider_id="gemini"
    )

    mock_groq = MagicMock()
    mock_groq.provider_name = "groq"
    mock_groq.provider_id = "groq"
    mock_groq.generate_text.return_value = AIResponse(
        text="Fallback answer from Groq",
        model="llama-3.3-70b-versatile",
    )

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)
    response = manager.generate_text("Prompt needing fallback")

    assert response.text == "Fallback answer from Groq"
    assert response.metadata.get("fallback") is True
    assert response.metadata.get("original_provider") == "gemini"
    assert response.metadata.get("actual_provider") == "groq"


def test_provider_manager_auto_fallback_on_rate_limit(fallback_settings: Settings) -> None:
    """Verify rate limit 429 triggers automatic fallback to next available provider."""
    mock_gemini = MagicMock()
    mock_gemini.generate_text.side_effect = RateLimitError(
        "429 Quota Exceeded", provider_id="gemini"
    )

    mock_groq = MagicMock()
    mock_groq.generate_text.return_value = AIResponse(text="Success from Groq")

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)
    resp = manager.generate_text("Test rate limit fallback")
    assert resp.text == "Success from Groq"


def test_provider_manager_no_fallback_on_permanent_auth_error(fallback_settings: Settings) -> None:
    """Verify non-retryable AuthenticationError does NOT trigger fallback and raises directly."""
    mock_gemini = MagicMock()
    mock_gemini.generate_text.side_effect = AuthenticationError(
        "Invalid API key", provider_id="gemini"
    )

    mock_groq = MagicMock()

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)

    with pytest.raises(AuthenticationError):
        manager.generate_text("Fatal auth query")

    # Groq must NEVER have been called
    mock_groq.generate_text.assert_not_called()


def test_provider_manager_no_fallback_on_cancellation(fallback_settings: Settings) -> None:
    """Verify cancelled requests do NOT trigger provider fallback."""
    token = CancellationToken()
    token.cancel()

    mock_gemini = MagicMock()
    mock_groq = MagicMock()

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)

    with pytest.raises(ProviderCancelledError):
        manager.generate_text("Cancelled query", cancellation_token=token)

    mock_gemini.generate_text.assert_not_called()
    mock_groq.generate_text.assert_not_called()


def test_provider_manager_streaming_auto_fallback(fallback_settings: Settings) -> None:
    """Verify stream failure before token yield falls back smoothly to secondary provider."""
    mock_gemini = MagicMock()
    mock_gemini.stream_text.side_effect = ServiceUnavailableError(
        "503 High Demand", provider_id="gemini"
    )

    mock_groq = MagicMock()
    mock_groq.stream_text.return_value = ["Stream ", "from ", "Groq"]

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)
    tokens = list(manager.stream_text("Stream query"))

    assert tokens == ["Stream ", "from ", "Groq"]


def test_provider_manager_disabled_auto_fallback(fallback_settings: Settings) -> None:
    """Verify disabling auto_fallback prevents fallback even on retryable 503 errors."""
    fallback_settings.enable_auto_fallback = False

    mock_gemini = MagicMock()
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Overloaded")

    mock_groq = MagicMock()

    registry = ProviderRegistry(settings=fallback_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=fallback_settings, registry=registry)

    with pytest.raises(ServiceUnavailableError):
        manager.generate_text("Should not fallback")

    mock_groq.generate_text.assert_not_called()
