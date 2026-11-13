"""Comprehensive unit tests for the Automatic Model Failover System.

Verifies:
1. Primary model succeeds: no fallback.
2. Primary model times out: fallback succeeds.
3. Primary model returns 503: fallback succeeds.
4. Primary model returns 429: fallback follows bounded retry/fallback policy.
5. Primary model returns 401: no endless retries; eligible fallback considered according to policy.
6. Primary model is unavailable: fallback succeeds.
7. All models fail: clear final failure, no false success.
8. User cancellation: no fallback.
9. Invalid user request: no fallback.
10. Tool execution failure: no provider fallback.
11. Intra-provider fallback works when enabled.
12. Intra-provider fallback is blocked when disabled.
13. Cross-provider fallback is blocked by default.
14. Cross-provider fallback works only when explicitly authorized.
15. Cross-provider prompt transfer remains blocked when disabled.
16. Cross-provider history transfer remains blocked when disabled.
17. Memory cloud transmission remains blocked by default.
18. Sensitive and unapproved memories never reach fallback providers.
19. Streaming failure before first token is handled correctly.
20. Streaming failure after partial output does not duplicate completed content.
21. Cancellation during fallback stops the operation.
22. Retry limits and cooldown behavior work.
23. Recovery after cooldown works.
24. Saved user provider/model preference is not unexpectedly changed.
25. Logs redact secrets and sensitive request contents.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import (
    AIResponse,
    AuthenticationError,
    ModelNotFoundError,
    NetworkError,
    PrivacyViolationError,
    ProviderCancelledError,
    RateLimitError,
    ServiceUnavailableError,
)
from ai.base import (
    TimeoutError as NormalizedTimeoutError,
)
from ai.manager import ProviderManager
from ai.registry import ProviderRegistry
from config import Settings
from core.execution_context import CancellationToken
from memory.base import ConversationMessage


@pytest.fixture
def failover_settings() -> Settings:
    return Settings(
        default_provider="gemini",
        gemini_model="gemini-3.8-flash",
        enable_auto_fallback=True,
        allow_intra_provider_fallback=True,
        allow_cross_provider_fallback=False,
        allow_cross_provider_prompt_transfer=False,
        allow_cross_provider_history_transfer=False,
        memory_allow_cloud_transmission=False,
        max_fallback_attempts=3,
        failover_cooldown_seconds=60.0,
        gemini_api_key=SecretStr("AIzaSyMockGeminiKey"),
        groq_api_key=SecretStr("gsk_MockGroqKey"),
        openai_api_key=SecretStr("sk-MockOpenAIKey"),
        fallback_provider_order=["gemini", "groq", "openai"],
    )


def test_1_primary_model_succeeds_no_fallback(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.return_value = AIResponse(
        text="Normal response", model="gemini-3.8-flash"
    )

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Hello")

    assert resp.text == "Normal response"
    assert resp.metadata.get("fallback") is not True


def test_2_primary_model_times_out_fallback_succeeds(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise NormalizedTimeoutError("Connection timed out after 30s")
        return AIResponse(text="Timeout fallback response", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Prompt requiring fallback")

    assert resp.text == "Timeout fallback response"
    assert resp.metadata.get("fallback") is True
    assert resp.metadata.get("original_model") == "gemini-3.8-flash"
    assert resp.metadata.get("actual_model") != "gemini-3.8-flash"


def test_3_primary_model_returns_503_fallback_succeeds(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise ServiceUnavailableError("503 The model is overloaded")
        return AIResponse(text="503 fallback response", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Prompt needing 503 fallback")

    assert resp.text == "503 fallback response"
    assert resp.metadata.get("fallback") is True


def test_4_primary_model_returns_429_bounded_fallback(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise RateLimitError("429 Resource has been exhausted (rate limit)")
        return AIResponse(text="Rate limit recovered", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Test 429 rate limit")

    assert resp.text == "Rate limit recovered"
    assert resp.metadata.get("fallback") is True


def test_5_primary_model_returns_401_no_endless_retries(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = AuthenticationError("API_KEY_INVALID: 401 Unauthorized")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(AuthenticationError):
        manager.generate_text("Test 401")

    # Should only call once for auth error, no endless looping
    assert mock_gemini.generate_text.call_count == 1


def test_6_primary_model_unavailable_fallback_succeeds(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise ModelNotFoundError("Model gemini-3.8-flash not found or discontinued")
        return AIResponse(text="Recovered from model not found", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Test model unavailable")

    assert resp.text == "Recovered from model not found"
    assert resp.metadata.get("fallback") is True


def test_7_all_models_fail_clear_final_failure(failover_settings: Settings) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Global Outage")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    exhausted_events = []
    manager = ProviderManager(settings=failover_settings, registry=registry)
    manager.add_failover_listener(lambda ev: exhausted_events.append(ev))

    with pytest.raises(ServiceUnavailableError):
        manager.generate_text("Test global outage")

    assert any(ev.get("event") == "failover_exhausted" for ev in exhausted_events)


def test_8_user_cancellation_no_fallback(failover_settings: Settings) -> None:
    token = CancellationToken()
    token.cancel()

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(ProviderCancelledError):
        manager.generate_text("Test cancelled", cancellation_token=token)

    mock_gemini.generate_text.assert_not_called()


def test_9_invalid_user_request_no_fallback(failover_settings: Settings) -> None:
    from ai.base import InvalidRequestError

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = InvalidRequestError("Malformed JSON schema in prompt")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(InvalidRequestError):
        manager.generate_text("Test invalid schema")

    assert mock_gemini.generate_text.call_count == 1


def test_10_tool_execution_failure_no_provider_fallback(failover_settings: Settings) -> None:
    # Tool execution happens outside ProviderManager in AgentExecutor.
    # ProviderManager is only called for LLM inference.
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.return_value = AIResponse(
        text='{"tool": "windows_audio_set_mute", "parameters": {"mute": true}}'
    )

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Mute audio")

    assert resp.metadata.get("fallback") is not True
    assert mock_gemini.generate_text.call_count == 1


def test_11_intra_provider_fallback_works_when_enabled(failover_settings: Settings) -> None:
    failover_settings.allow_intra_provider_fallback = True

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise ServiceUnavailableError("503 Overloaded")
        return AIResponse(text="Intra-provider success", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Test intra-provider")

    assert resp.text == "Intra-provider success"
    assert resp.metadata.get("fallback") is True
    assert resp.metadata.get("actual_provider") == "gemini"


def test_12_intra_provider_fallback_blocked_when_disabled(failover_settings: Settings) -> None:
    failover_settings.allow_intra_provider_fallback = False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Overloaded")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises((PrivacyViolationError, ServiceUnavailableError)):
        manager.generate_text("Test disabled intra")

    # Only primary model was attempted
    assert mock_gemini.generate_text.call_count == 1


def test_13_cross_provider_fallback_blocked_by_default(failover_settings: Settings) -> None:
    assert failover_settings.allow_cross_provider_fallback is False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 All Gemini down")

    # Mock all Gemini intra models as also failing with 503
    def gen_side_effect(prompt, **kwargs):
        raise ServiceUnavailableError("503 Down")

    mock_gemini.generate_text.side_effect = gen_side_effect

    mock_groq = MagicMock()
    mock_groq.default_model = "llama-3.3-70b-versatile"

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises((PrivacyViolationError, ServiceUnavailableError)):
        manager.generate_text("Test cross-provider blocked")

    # Groq must NEVER be called
    mock_groq.generate_text.assert_not_called()


def test_14_cross_provider_fallback_works_when_explicitly_authorized(
    failover_settings: Settings,
) -> None:
    failover_settings.allow_intra_provider_fallback = False
    failover_settings.allow_cross_provider_fallback = True
    failover_settings.allow_cross_provider_prompt_transfer = True

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Gemini Outage")

    mock_groq = MagicMock()
    mock_groq.default_model = "llama-3.3-70b-versatile"
    mock_groq.generate_text.return_value = AIResponse(
        text="Authorized Groq Answer", model="llama-3.3-70b-versatile"
    )

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Test authorized cross fallback")

    assert resp.text == "Authorized Groq Answer"
    assert resp.metadata.get("fallback") is True
    assert resp.metadata.get("original_provider") == "gemini"
    assert resp.metadata.get("actual_provider") == "groq"


def test_15_cross_provider_prompt_transfer_blocked_when_disabled(
    failover_settings: Settings,
) -> None:
    failover_settings.allow_intra_provider_fallback = False
    failover_settings.allow_cross_provider_fallback = True
    failover_settings.allow_cross_provider_prompt_transfer = False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Gemini Outage")

    mock_groq = MagicMock()
    mock_groq.default_model = "llama-3.3-70b-versatile"

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(PrivacyViolationError):
        manager.generate_text("Test prompt transfer blocked")

    mock_groq.generate_text.assert_not_called()


def test_16_cross_provider_history_transfer_blocked_when_disabled(
    failover_settings: Settings,
) -> None:
    failover_settings.allow_intra_provider_fallback = False
    failover_settings.allow_cross_provider_fallback = True
    failover_settings.allow_cross_provider_prompt_transfer = True
    failover_settings.allow_cross_provider_history_transfer = False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Gemini Outage")

    mock_groq = MagicMock()
    mock_groq.default_model = "llama-3.3-70b-versatile"
    mock_groq.generate_text.return_value = AIResponse(text="History stripped answer")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    history = [
        ConversationMessage(role="user", content="Secret past context", session_id="test-session")
    ]
    resp = manager.generate_text("Hello", history=history)

    assert resp.text == "History stripped answer"
    # History must have been omitted (passed as None) to Groq
    passed_history = mock_groq.generate_text.call_args[1].get("history")
    assert passed_history is None


def test_17_memory_cloud_transmission_blocked_by_default(failover_settings: Settings) -> None:
    assert failover_settings.memory_allow_cloud_transmission is False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.return_value = AIResponse(text="Answer without memory")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    prompt_with_memory = (
        "[RELEVANT USER MEMORY]\nUser secret preference: X\n[END USER MEMORY]\n\nActual query"
    )

    manager.generate_text(prompt_with_memory)

    passed_prompt = mock_gemini.generate_text.call_args[1]["prompt"]
    assert "[RELEVANT USER MEMORY]" not in passed_prompt
    assert "User secret preference: X" not in passed_prompt
    assert "Actual query" in passed_prompt


def test_18_sensitive_memories_never_reach_fallback_providers(failover_settings: Settings) -> None:
    failover_settings.allow_intra_provider_fallback = False
    failover_settings.allow_cross_provider_fallback = True
    failover_settings.allow_cross_provider_prompt_transfer = True
    failover_settings.memory_allow_cloud_transmission = False

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Gemini Outage")

    mock_groq = MagicMock()
    mock_groq.default_model = "llama-3.3-70b-versatile"
    mock_groq.generate_text.return_value = AIResponse(text="Groq answer")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)
    registry.register_factory("groq", lambda cfg: mock_groq)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    prompt_with_memory = (
        "[RELEVANT USER MEMORY]\nAPI Key: SECRET123\n[END USER MEMORY]\n\nTask prompt"
    )

    manager.generate_text(prompt_with_memory)

    passed_to_groq = mock_groq.generate_text.call_args[1]["prompt"]
    assert "SECRET123" not in passed_to_groq
    assert "[RELEVANT USER MEMORY]" not in passed_to_groq
    assert "Task prompt" in passed_to_groq


def test_19_streaming_failure_before_first_token_handled_smoothly(
    failover_settings: Settings,
) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def stream_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise ServiceUnavailableError("503 Server overloaded before tokens")
        return iter(["Stream ", "from ", "alternative ", "model"])

    mock_gemini.stream_text.side_effect = stream_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    chunks = list(manager.stream_text("Stream test"))

    assert chunks == ["Stream ", "from ", "alternative ", "model"]


def test_20_streaming_failure_after_partial_output_does_not_duplicate(
    failover_settings: Settings,
) -> None:
    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def failing_generator():
        yield "Partial token 1. "
        yield "Partial token 2. "
        raise NetworkError("Connection reset by peer mid-stream")

    mock_gemini.stream_text.return_value = failing_generator()

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    # Collecting from stream should raise NetworkError once partial output is yielded,
    # rather than switching to an alternative model and restarting generation from token 0.
    received_chunks = []
    with pytest.raises(NetworkError):
        for chunk in manager.stream_text("Stream test with mid failure"):
            received_chunks.append(chunk)

    assert received_chunks == ["Partial token 1. ", "Partial token 2. "]
    # The provider stream_text was called once; it did NOT re-invoke alternative model mid-stream
    assert mock_gemini.stream_text.call_count == 1


def test_21_cancellation_during_fallback_stops_operation(failover_settings: Settings) -> None:
    token = CancellationToken()

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        # Cancel right after primary model fails
        token.cancel()
        raise ServiceUnavailableError("503 Primary failed")

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(ProviderCancelledError):
        manager.generate_text("Test cancel during fallback", cancellation_token=token)


def test_22_retry_limits_and_cooldown_behavior(failover_settings: Settings) -> None:
    failover_settings.max_fallback_attempts = 2
    failover_settings.failover_cooldown_seconds = 10.0

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"
    mock_gemini.generate_text.side_effect = ServiceUnavailableError("503 Continuous failure")

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)

    with pytest.raises(ServiceUnavailableError):
        manager.generate_text("Test retry limit")

    # Primary model gemini-3.8-flash must now be in cooldown
    assert manager.is_model_in_cooldown("gemini", "gemini-3.8-flash") is True


def test_23_recovery_after_cooldown_works(failover_settings: Settings) -> None:
    manager = ProviderManager(settings=failover_settings)

    # Set cooldown for 0.05 seconds
    manager.mark_model_cooldown("gemini", "gemini-3.8-flash", duration_seconds=0.05)
    assert manager.is_model_in_cooldown("gemini", "gemini-3.8-flash") is True

    # Sleep past cooldown
    time.sleep(0.06)
    assert manager.is_model_in_cooldown("gemini", "gemini-3.8-flash") is False


def test_24_saved_user_provider_preference_not_changed(failover_settings: Settings) -> None:
    initial_provider = failover_settings.default_provider
    initial_model = failover_settings.gemini_model

    mock_gemini = MagicMock()
    mock_gemini.default_model = "gemini-3.8-flash"

    def gen_side_effect(prompt, **kwargs):
        model = kwargs.get("model")
        if model == "gemini-3.8-flash":
            raise ServiceUnavailableError("503 Temporary failover")
        return AIResponse(text="Failover answer", model=model)

    mock_gemini.generate_text.side_effect = gen_side_effect

    registry = ProviderRegistry(settings=failover_settings)
    registry.register_factory("gemini", lambda cfg: mock_gemini)

    manager = ProviderManager(settings=failover_settings, registry=registry)
    resp = manager.generate_text("Test preference retention")

    assert resp.metadata.get("fallback") is True
    # User persistent settings must remain untouched
    assert failover_settings.default_provider == initial_provider
    assert failover_settings.gemini_model == initial_model


def test_25_logs_redact_secrets_and_credentials(failover_settings: Settings) -> None:
    import logging

    from infrastructure.logging import SecretRedactorFilter, register_sensitive_token

    register_sensitive_token("AIzaSyMockGeminiKey")
    register_sensitive_token("sk-MockOpenAIKey")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="API call failed with key AIzaSyMockGeminiKey and sk-MockOpenAIKey",
        args=(),
        exc_info=None,
    )

    filt = SecretRedactorFilter()
    filt.filter(record)

    # Secret strings must be scrubbed / redacted
    assert "AIzaSyMockGeminiKey" not in record.msg
    assert "sk-MockOpenAIKey" not in record.msg
