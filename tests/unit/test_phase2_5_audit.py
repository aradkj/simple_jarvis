"""Comprehensive audit and hardening test suite for Phase 2.5 Multi-Provider Architecture."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import (
    AIResponse,
    CapabilityNotSupportedError,
    LifecycleStatus,
    ModelCapabilities,
    ModelInfo,
    ServiceUnavailableError,
)
from ai.catalog import ModelCatalog
from ai.manager import ProviderManager
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai import OpenAIProvider
from ai.registry import ProviderRegistry
from config import Settings
from memory.base import ConversationMessage, MessageRole, MessageStatus
from ui.chat_panel import MessageBubble


def test_openai_reasoning_model_parameter_adaptation():
    """Verify that OpenAI reasoning models (o1/o3) use max_completion_tokens, omit temperature, and use developer role."""
    settings = Settings(
        openai_api_key=SecretStr("sk-test-key"),
        openai_model="o3-mini",
        gemini_temperature=0.7,
        gemini_max_output_tokens=2048,
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Reasoning response"
    mock_choice.finish_reason = "stop"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = OpenAIProvider(settings=settings, client=mock_client)
    res = provider.generate_text(
        prompt="Solve logic puzzle",
        history=[
            ConversationMessage(
                session_id="test_session",
                role=MessageRole.USER,
                content="Prior question",
                status=MessageStatus.COMPLETED,
            )
        ],
    )

    assert res.text == "Reasoning response"
    call_args = mock_client.chat.completions.create.call_args[1]

    # Must NOT have temperature
    assert "temperature" not in call_args
    # Must use max_completion_tokens
    assert call_args["max_completion_tokens"] == 2048
    assert "max_tokens" not in call_args
    # First message role must be "developer", not "system"
    assert call_args["messages"][0]["role"] == "developer"


def test_openai_standard_model_parameters():
    """Verify standard OpenAI models (e.g. gpt-4o) retain temperature and max_tokens."""
    settings = Settings(
        openai_api_key=SecretStr("sk-test-key"),
        openai_model="gpt-4o",
        gemini_temperature=0.5,
        gemini_max_output_tokens=1000,
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Standard response"
    mock_choice.finish_reason = "stop"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = OpenAIProvider(settings=settings, client=mock_client)
    res = provider.generate_text(prompt="Hello")

    assert res.text == "Standard response"
    call_args = mock_client.chat.completions.create.call_args[1]

    assert call_args["temperature"] == 0.5
    assert call_args["max_tokens"] == 1000
    assert "max_completion_tokens" not in call_args
    assert call_args["messages"][0]["role"] == "system"


def test_deepseek_reasoner_omits_temperature():
    """Verify DeepSeek reasoner (R1) omits temperature to prevent 400 parameter errors."""
    settings = Settings(
        deepseek_api_key=SecretStr("sk-test-key"),
        deepseek_model="deepseek-reasoner",
        gemini_temperature=0.7,
        gemini_max_output_tokens=4000,
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "DeepSeek R1 reasoning"
    mock_choice.finish_reason = "stop"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = DeepSeekProvider(settings=settings, client=mock_client)
    res = provider.generate_text(prompt="Prove P != NP")

    assert res.text == "DeepSeek R1 reasoning"
    call_args = mock_client.chat.completions.create.call_args[1]
    assert "temperature" not in call_args
    assert call_args["max_tokens"] == 4000


def test_capability_pre_validation():
    """Verify CapabilityNotSupportedError is raised before invoking model lacking declared capability."""
    mock_provider = MagicMock()
    mock_provider.provider_id = "test_prov"
    mock_provider.default_model = "test-model"
    mock_provider.get_model_capabilities.return_value = ModelCapabilities(
        vision_supported=False,
        streaming_supported=True,
    )
    # Inherit default validate_capability behavior
    from ai.base import BaseAIProvider

    mock_provider.validate_capability = lambda cap, model_id=None: (
        BaseAIProvider.validate_capability(mock_provider, cap, model_id)
    )

    # Validating vision should fail
    with pytest.raises(CapabilityNotSupportedError) as exc_info:
        mock_provider.validate_capability("vision")
    assert "does not support required capability 'vision'" in str(exc_info.value)

    # Validating streaming should succeed
    mock_provider.validate_capability("streaming")


def test_cross_provider_privacy_guard_disabled_by_default():
    """Verify conversation history is not transferred to alternative provider on fallback when privacy guard is active."""
    settings = Settings(
        default_provider="prov_a",
        enable_auto_fallback=True,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=True,
        allow_cross_provider_history_transfer=False,
        fallback_provider_order=["prov_a", "prov_b"],
    )

    prov_a = MagicMock()
    prov_a.provider_id = "prov_a"
    prov_a.is_ready.return_value = True
    prov_a.generate_text.side_effect = ServiceUnavailableError(
        "503 Server overloaded", provider_id="prov_a"
    )

    prov_b = MagicMock()
    prov_b.provider_id = "prov_b"
    prov_b.is_ready.return_value = True
    prov_b.generate_text.return_value = AIResponse(text="Fallback response", metadata={})

    registry = ProviderRegistry()
    registry.register_factory("prov_a", lambda s: prov_a)
    registry.register_factory("prov_b", lambda s: prov_b)

    manager = ProviderManager(settings=settings, registry=registry)
    history = [
        ConversationMessage(
            session_id="test_session",
            role=MessageRole.USER,
            content="Sensitive user medical inquiry",
            status=MessageStatus.COMPLETED,
        )
    ]

    response = manager.generate_text(prompt="What medication is this?", history=history)

    assert response.text == "Fallback response"
    # Prov A was invoked with history
    assert prov_a.generate_text.call_args[1]["history"] == history
    # Prov B (fallback) MUST NOT receive the sensitive history because allow_cross_provider_history_transfer is False
    assert prov_b.generate_text.call_args[1]["history"] is None


def test_cross_provider_privacy_guard_when_explicitly_allowed():
    """Verify conversation history IS transferred to fallback provider if allow_cross_provider_history_transfer is True."""
    settings = Settings(
        default_provider="prov_a",
        enable_auto_fallback=True,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=True,
        allow_cross_provider_history_transfer=True,
        fallback_provider_order=["prov_a", "prov_b"],
    )

    prov_a = MagicMock()
    prov_a.provider_id = "prov_a"
    prov_a.is_ready.return_value = True
    prov_a.generate_text.side_effect = ServiceUnavailableError(
        "503 Server overloaded", provider_id="prov_a"
    )

    prov_b = MagicMock()
    prov_b.provider_id = "prov_b"
    prov_b.is_ready.return_value = True
    prov_b.generate_text.return_value = AIResponse(text="Fallback response", metadata={})

    registry = ProviderRegistry()
    registry.register_factory("prov_a", lambda s: prov_a)
    registry.register_factory("prov_b", lambda s: prov_b)

    manager = ProviderManager(settings=settings, registry=registry)
    history = [
        ConversationMessage(
            session_id="test_session",
            role=MessageRole.USER,
            content="Previous context message",
            status=MessageStatus.COMPLETED,
        )
    ]

    response = manager.generate_text(prompt="Next message", history=history)

    assert response.text == "Fallback response"
    # Prov B receives history because user explicitly opted in
    assert prov_b.generate_text.call_args[1]["history"] == history


def test_mid_stream_interruption_no_silent_fallback():
    """Scenario B: When streaming fails mid-stream after yielding tokens, no silent append occurs."""
    settings = Settings(
        default_provider="prov_a",
        enable_auto_fallback=True,
        fallback_provider_order=["prov_a", "prov_b"],
    )

    def failing_stream(*args, **kwargs):
        yield "Initial chunk. "
        raise ServiceUnavailableError("Mid-stream network disconnect", provider_id="prov_a")

    prov_a = MagicMock()
    prov_a.provider_id = "prov_a"
    prov_a.is_ready.return_value = True
    prov_a.stream_text.side_effect = failing_stream

    prov_b = MagicMock()
    prov_b.provider_id = "prov_b"
    prov_b.is_ready.return_value = True
    prov_b.stream_text.return_value = iter(["Should NOT be emitted!"])

    registry = ProviderRegistry()
    registry.register_factory("prov_a", lambda s: prov_a)
    registry.register_factory("prov_b", lambda s: prov_b)

    manager = ProviderManager(settings=settings, registry=registry)

    stream = manager.stream_text(prompt="Write a novel")
    first_chunk = next(stream)
    assert first_chunk == "Initial chunk. "

    # Second pull must raise the error instead of falling back to prov_b
    with pytest.raises(ServiceUnavailableError):
        next(stream)

    prov_b.stream_text.assert_not_called()


def test_message_bubble_mark_failed_preserves_partial_content(qapp):
    """Verify UI MessageBubble displays interrupted notice without wiping partial output."""
    bubble = MessageBubble(sender="JARVIS", text="", is_user=False)
    bubble.set_content("This was partially received before failing...")
    bubble.mark_failed("503 Service Unavailable")

    assert bubble.is_error is True
    assert "This was partially received before failing..." in bubble.raw_text
    assert "⚠️ [Interrupted: 503 Service Unavailable]" in bubble.raw_text
    assert not bubble.retry_btn.isHidden()


def test_model_catalog_deprecation_filtering():
    """Verify deprecated models are excluded by default and discoverable when requested."""
    active_models = ModelCatalog.list_models("groq", include_deprecated=False)
    model_ids = [m.model_id for m in active_models]
    assert "mixtral-8x7b-32768" not in model_ids
    assert "llama-3.3-70b-versatile" in model_ids

    all_models = ModelCatalog.list_models("groq", include_deprecated=True)
    all_ids = [m.model_id for m in all_models]
    assert "mixtral-8x7b-32768" in all_ids


def test_dynamic_model_registration():
    """Verify custom models can be registered into ModelCatalog at runtime."""
    custom_model = ModelInfo(
        provider_id="openai",
        model_id="custom-fine-tuned-v1",
        display_name="Custom Fine Tuned Model",
        capabilities=ModelCapabilities(streaming_supported=True, context_window=64000),
        documentation_url="https://developers.openai.com/api/docs/models",
    )
    try:
        res = ModelCatalog.register_custom_model(custom_model, overwrite=True)
        assert res is True

        fetched = ModelCatalog.get_model("openai", "custom-fine-tuned-v1")
        assert fetched is not None
        assert fetched.display_name == "Custom Fine Tuned Model"
        assert fetched.capabilities.context_window == 64000
    finally:
        from ai.catalog import _CATALOG

        _CATALOG["openai"] = [m for m in _CATALOG["openai"] if m.model_id != "custom-fine-tuned-v1"]


def test_retired_models_cannot_be_selected_as_active_defaults():
    """Verify no provider default is a retired or deprecated model."""
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        default_model = ModelCatalog.get_default_model(pid)
        assert default_model, f"Provider '{pid}' has empty default model."
        info = ModelCatalog.get_model_info(pid, default_model)
        assert info is not None, f"Default model '{default_model}' for '{pid}' not in catalog."
        assert not info.is_deprecated, f"Default model '{default_model}' for '{pid}' is deprecated."
        assert info.lifecycle_status not in (
            "retired",
            "deprecated",
        ), f"Default model '{default_model}' is {info.lifecycle_status}."


def test_model_catalog_ids_unique_within_provider():
    """Verify model identifiers are strictly unique per provider."""
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        models = ModelCatalog.list_models(pid, include_deprecated=True)
        ids = [m.model_id for m in models]
        assert len(ids) == len(set(ids)), f"Duplicate model IDs found in provider '{pid}': {ids}"


def test_gemini_token_limits_differentiated_and_accurate():
    """Verify Gemini models have accurate, distinct token limits reflecting Google documentation."""
    m_15_pro = ModelCatalog.get_model_info("gemini", "gemini-1.5-pro")
    assert m_15_pro is not None
    assert m_15_pro.capabilities.context_window == 2097152
    assert m_15_pro.capabilities.maximum_output_tokens == 8192

    m_20_flash = ModelCatalog.get_model_info("gemini", "gemini-2.0-flash")
    assert m_20_flash is not None
    assert m_20_flash.capabilities.context_window == 1048576
    assert m_20_flash.capabilities.maximum_output_tokens == 8192

    m_35_flash = ModelCatalog.get_model_info("gemini", "gemini-3.5-flash")
    assert m_35_flash is not None
    assert m_35_flash.capabilities.context_window == 1048576
    assert m_35_flash.capabilities.maximum_output_tokens == 65536

    m_31_flash_lite = ModelCatalog.get_model_info("gemini", "gemini-3.1-flash-lite")
    assert m_31_flash_lite is not None
    assert m_31_flash_lite.capabilities.maximum_output_tokens == 32768


def test_preview_models_clearly_identifiable():
    """Verify preview models are explicitly flagged with is_preview=True."""
    m_preview = ModelCatalog.get_model_info("gemini", "gemini-3-flash-preview")
    assert m_preview is not None
    assert m_preview.is_preview is True
    assert m_preview.lifecycle_status in (LifecycleStatus.PREVIEW, "PREVIEW")

    m_stable = ModelCatalog.get_model_info("gemini", "gemini-3.8-flash")
    assert m_stable is not None
    assert m_stable.is_preview is False
    assert m_stable.lifecycle_status in (LifecycleStatus.ACTIVE, "ACTIVE")


def test_custom_model_registration_does_not_overwrite_unexpectedly():
    """Verify registering an existing model ID with overwrite=False does not overwrite it."""
    orig = ModelCatalog.get_model_info("gemini", "gemini-3.5-flash")
    assert orig is not None
    orig_name = orig.display_name

    fake_dupe = ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.5-flash",
        display_name="Malicious Overwrite",
        capabilities=ModelCapabilities(),
    )
    res = ModelCatalog.register_custom_model(fake_dupe, overwrite=False)
    assert res is False

    current = ModelCatalog.get_model_info("gemini", "gemini-3.5-flash")
    assert current is not None
    assert current.display_name == orig_name


def test_model_refresh_does_not_reactivate_retired_entries():
    """Verify model discovery refresh never reactivates retired/deprecated entries."""
    ModelCatalog.refresh_from_discovered("groq", ["mixtral-8x7b-32768"])
    info = ModelCatalog.get_model_info("groq", "mixtral-8x7b-32768")
    assert info is not None
    assert info.is_deprecated is True
    assert info.lifecycle_status in (LifecycleStatus.RETIRED, "RETIRED")


def test_unknown_capability_values_handled_conservatively():
    """Verify uncataloged or unknown models receive conservative baseline capabilities."""
    caps = ModelCatalog.get_capabilities("nonexistent_provider", "unknown-model-xyz")
    assert caps.streaming_supported is True
    assert caps.vision_supported is False
    assert caps.tool_calling_supported is False
    assert caps.structured_output_supported is False
    assert caps.context_window == 32768
    assert caps.maximum_output_tokens == 4096


def test_token_limits_positive_and_valid():
    """Verify all models in catalog have strictly positive and reasonable token limits."""
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        models = ModelCatalog.list_models(pid, include_deprecated=True)
        for m in models:
            assert m.capabilities.context_window >= 1000, (
                f"Context window too small for {m.model_id}"
            )
            assert m.capabilities.maximum_output_tokens >= 100, (
                f"Max output too small for {m.model_id}"
            )
            assert m.provider_id == pid, (
                f"Model {m.model_id} has mismatched provider {m.provider_id} != {pid}"
            )


def test_cancellation_during_fallback_chain():
    """Verify cancelling token between fallback attempts halts execution immediately."""
    from core.execution_context import CancellationToken

    settings = Settings(
        default_provider="p1",
        enable_auto_fallback=True,
        fallback_provider_order=["p1", "p2"],
    )
    token = CancellationToken()

    p1 = MagicMock()
    p1.provider_id = "p1"
    p1.is_ready.return_value = True

    def p1_failure(*args, **kwargs):
        # Cancel right as p1 fails
        token.cancel()
        raise ServiceUnavailableError("503 Fail", provider_id="p1")

    p1.generate_text.side_effect = p1_failure

    p2 = MagicMock()
    p2.provider_id = "p2"
    p2.is_ready.return_value = True

    registry = ProviderRegistry()
    registry.register_factory("p1", lambda s: p1)
    registry.register_factory("p2", lambda s: p2)

    manager = ProviderManager(settings=settings, registry=registry)

    with pytest.raises(Exception) as exc_info:
        manager.generate_text("Hello", cancellation_token=token)

    from ai.base import ProviderCancelledError

    assert isinstance(exc_info.value, ProviderCancelledError)
    p2.generate_text.assert_not_called()


def test_all_fallback_providers_unavailable_raises_clean_error():
    """Verify when all fallback candidates fail with 503, the final error is raised cleanly."""
    settings = Settings(
        default_provider="p1",
        enable_auto_fallback=True,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=True,
        fallback_provider_order=["p1", "p2"],
    )

    p1 = MagicMock()
    p1.provider_id = "p1"
    p1.is_ready.return_value = True
    p1.generate_text.side_effect = ServiceUnavailableError("P1 503", provider_id="p1")

    p2 = MagicMock()
    p2.provider_id = "p2"
    p2.is_ready.return_value = True
    p2.generate_text.side_effect = ServiceUnavailableError("P2 503", provider_id="p2")

    registry = ProviderRegistry()
    registry.register_factory("p1", lambda s: p1)
    registry.register_factory("p2", lambda s: p2)

    manager = ProviderManager(settings=settings, registry=registry)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        manager.generate_text("Hello")

    assert "P2 503" in str(exc_info.value)
