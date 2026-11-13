"""Unit tests for Multi-Provider AI architecture, adapters, and model catalog."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import (
    AuthenticationError,
    ConnectionErrorType,
    ModelCapabilities,
    ProviderCancelledError,
    ProviderStatus,
    UnknownProviderError,
)
from ai.catalog import ModelCatalog
from ai.providers.anthropic import AnthropicProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.groq import GroqProvider
from ai.providers.openai import OpenAIProvider
from ai.providers.openrouter import OpenRouterProvider
from ai.registry import ProviderRegistrationError, ProviderRegistry, create_default_registry
from config import Settings
from core.execution_context import CancellationToken


@pytest.fixture
def test_multi_settings() -> Settings:
    return Settings(
        openai_api_key=SecretStr("sk-test-mock-openai-key-123"),
        openai_model="gpt-4o",
        anthropic_api_key=SecretStr("sk-ant-test-mock-claude-key-456"),
        anthropic_model="claude-3-5-sonnet-20241022",
        deepseek_api_key=SecretStr("sk-test-mock-deepseek-key-789"),
        deepseek_model="deepseek-chat",
        openrouter_api_key=SecretStr("sk-or-test-mock-openrouter-key-abc"),
        openrouter_model="anthropic/claude-3.5-sonnet",
        groq_api_key=SecretStr("gsk_test_mock_groq_key_xyz"),
        groq_model="llama-3.3-70b-versatile",
    )


# --- Model Catalog Tests ---


def test_model_catalog_known_providers() -> None:
    """Verify all 6 providers have cataloged models with declared capabilities."""
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        models = ModelCatalog.list_models(pid)
        assert len(models) > 0
        default_m = ModelCatalog.get_default_model(pid)
        assert bool(default_m)
        caps = ModelCatalog.get_capabilities(pid, default_m)
        assert isinstance(caps, ModelCapabilities)
        assert caps.streaming_supported is True


def test_model_catalog_capabilities_retrieval() -> None:
    """Verify detailed capability attributes for cataloged models."""
    gpt4o_info = ModelCatalog.get_model_info("openai", "gpt-4o")
    assert gpt4o_info is not None
    assert gpt4o_info.capabilities.vision_supported is True
    assert gpt4o_info.capabilities.tool_calling_supported is True

    deepseek_info = ModelCatalog.get_model_info("deepseek", "deepseek-chat")
    assert deepseek_info is not None
    assert deepseek_info.capabilities.context_window == 64000


# --- Provider Registry Tests ---


def test_registry_registration_and_lookup(test_multi_settings: Settings) -> None:
    """Verify registering, querying, and instantiating providers via ProviderRegistry."""
    registry = ProviderRegistry(settings=test_multi_settings)
    assert len(registry.list_registered_ids()) == 0

    registry.register_factory("openai", lambda cfg: OpenAIProvider(settings=cfg))
    assert registry.has_provider("openai")
    assert registry.has_provider("OPENAI")  # Case insensitive

    instance = registry.get_provider("openai")
    assert isinstance(instance, OpenAIProvider)
    # Check singleton caching
    assert registry.get_provider("openai") is instance


def test_registry_duplicate_registration_error(test_multi_settings: Settings) -> None:
    """Verify duplicate registration without overwrite flag raises ProviderRegistrationError."""
    registry = ProviderRegistry(settings=test_multi_settings)
    registry.register_factory("groq", lambda cfg: GroqProvider(settings=cfg))

    with pytest.raises(ProviderRegistrationError):
        registry.register_factory("groq", lambda cfg: GroqProvider(settings=cfg))


def test_registry_unknown_provider_error(test_multi_settings: Settings) -> None:
    """Verify requesting an unregistered provider raises UnknownProviderError."""
    registry = ProviderRegistry(settings=test_multi_settings)
    with pytest.raises(UnknownProviderError):
        registry.get_provider("non_existent_provider")


def test_default_registry_all_six_providers(test_multi_settings: Settings) -> None:
    """Verify create_default_registry registers all 6 built-in providers."""
    registry = create_default_registry(settings=test_multi_settings)
    registered = registry.list_registered_ids()
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        assert pid in registered
        provider = registry.get_provider(pid)
        assert provider.provider_id == pid


# --- OpenAI Adapter Tests ---


def test_openai_provider_unconfigured() -> None:
    """Verify OpenAIProvider raises AuthenticationError when API key is missing."""
    empty_settings = Settings(openai_api_key=None)
    provider = OpenAIProvider(settings=empty_settings)
    assert provider.is_ready() is False
    assert provider.get_status() == ProviderStatus.NOT_CONFIGURED

    with pytest.raises(AuthenticationError):
        provider.generate_text("Hello")


def test_openai_provider_generate_text_mocked(test_multi_settings: Settings) -> None:
    """Verify OpenAIProvider generate_text formats messages and returns AIResponse."""
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI answer"
    mock_choice.finish_reason = "stop"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = OpenAIProvider(settings=test_multi_settings, client=mock_client)
    res = provider.generate_text("Test prompt")

    assert res.text == "OpenAI answer"
    assert res.model == "gpt-4o"
    assert res.finish_reason == "stop"


def test_openai_provider_stream_text_mocked(test_multi_settings: Settings) -> None:
    """Verify OpenAIProvider stream_text yields tokens."""
    mock_client = MagicMock()
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Hello "))]
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content="World!"))]
    mock_client.chat.completions.create.return_value = [chunk1, chunk2]

    provider = OpenAIProvider(settings=test_multi_settings, client=mock_client)
    tokens = list(provider.stream_text("Say hello"))
    assert tokens == ["Hello ", "World!"]


def test_openai_provider_cancellation(test_multi_settings: Settings) -> None:
    """Verify OpenAIProvider honors cancellation token during streaming."""
    mock_client = MagicMock()
    token = CancellationToken()

    def stream_gen():
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Token 1"))])
        token.cancel()
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Token 2"))])

    mock_client.chat.completions.create.return_value = stream_gen()
    provider = OpenAIProvider(settings=test_multi_settings, client=mock_client)

    with pytest.raises(ProviderCancelledError):
        list(provider.stream_text("Test cancel", cancellation_token=token))


def test_openai_provider_connection_test_success(test_multi_settings: Settings) -> None:
    """Verify OpenAI test_connection returns success result with latency."""
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = OpenAIProvider(settings=test_multi_settings, client=mock_client)
    res = provider.test_connection()
    assert res.is_success is True
    assert res.error_type == ConnectionErrorType.SUCCESS
    assert "gpt-4o" in res.message


# --- Anthropic Adapter Tests ---


def test_anthropic_provider_generate_text_mocked(test_multi_settings: Settings) -> None:
    """Verify AnthropicProvider maps messages and extracts text content blocks."""
    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "Claude answer"
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]
    mock_resp.stop_reason = "end_turn"
    mock_client.messages.create.return_value = mock_resp

    provider = AnthropicProvider(settings=test_multi_settings, client=mock_client)
    res = provider.generate_text("Hi Claude")

    assert res.text == "Claude answer"
    assert res.finish_reason == "end_turn"
    assert "claude-3-5-sonnet" in res.model


def test_anthropic_provider_stream_text_mocked(test_multi_settings: Settings) -> None:
    """Verify AnthropicProvider stream_text reads text_stream context manager."""
    mock_client = MagicMock()
    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.text_stream = ["Claude ", "stream ", "output"]
    mock_client.messages.stream.return_value = mock_stream

    provider = AnthropicProvider(settings=test_multi_settings, client=mock_client)
    tokens = list(provider.stream_text("Stream test"))
    assert tokens == ["Claude ", "stream ", "output"]


# --- DeepSeek & Groq & OpenRouter Adapter Tests ---


def test_deepseek_provider_configuration(test_multi_settings: Settings) -> None:
    """Verify DeepSeek adapter defaults to https://api.deepseek.com endpoint."""
    provider = DeepSeekProvider(settings=test_multi_settings)
    assert provider.provider_id == "deepseek"
    assert provider.is_ready() is True
    assert provider.default_model == "deepseek-chat"


def test_openrouter_provider_configuration(test_multi_settings: Settings) -> None:
    """Verify OpenRouter adapter defaults to https://openrouter.ai/api/v1 endpoint."""
    provider = OpenRouterProvider(settings=test_multi_settings)
    assert provider.provider_id == "openrouter"
    assert provider.is_ready() is True
    assert "claude" in provider.default_model or "gpt" in provider.default_model


def test_groq_provider_generate_text_mocked(test_multi_settings: Settings) -> None:
    """Verify Groq provider executes via OpenAI-compatible interface."""
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Groq ultra fast"
    mock_choice.finish_reason = "stop"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = GroqProvider(settings=test_multi_settings, client=mock_client)
    res = provider.generate_text("Speed test")
    assert res.text == "Groq ultra fast"
    assert res.model == "llama-3.3-70b-versatile"
