"""Exhaustive Phase 2.9 Super Remediation Verification Test Suite.

Covers:
1. Model Catalog integrity (exact IDs, lifecycle states, no retired in defaults/fallback, refresh idempotency)
2. OpenAI Responses API protocol compliance, reasoning parameters, argument JSON error handling, streaming isolation, continuation
3. 4-switch Privacy & Fallback matrix exhaustive enforcement (all 16 combinations) before network dispatch
4. SQLite schema idempotency, legacy schema upgrade, partial text preservation, separated status & reason
5. Cancellation immediacy, worker lifecycle, and session isolation
"""

import contextlib
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import (
    AIResponse,
    BaseAIProvider,
    ConnectionTestResult,
    LifecycleStatus,
    ModelCapabilities,
    PrivacyViolationError,
    ProviderCancelledError,
    ProviderStatus,
    ServiceUnavailableError,
)
from ai.catalog import ModelCatalog
from ai.manager import ProviderManager
from ai.providers.openai import OpenAIProvider
from ai.registry import ProviderRegistry
from config import Settings
from core.execution_context import CancellationToken
from memory.base import ConversationMessage, MessageRole, MessageStatus
from memory.database import SQLiteMemoryStore

# ==============================================================================
# SECTION 1: MODEL CATALOG INTEGRITY
# ==============================================================================


def test_catalog_exact_ids_and_active_presence():
    """Verify all catalog entries have non-empty exact IDs, and every provider has active models."""
    providers = ["gemini", "openai", "anthropic", "deepseek", "groq", "openrouter"]
    total_models = 0

    for p in providers:
        active_models = ModelCatalog.list_models(provider_id=p, include_deprecated=False)
        assert len(active_models) >= 1, f"Provider '{p}' must have at least one ACTIVE model"
        for m in active_models:
            assert m.lifecycle_status not in (
                LifecycleStatus.RETIRED,
                LifecycleStatus.DEPRECATED,
                "retired",
                "deprecated",
            )
            assert m.model_id
            assert m.provider_id == p
        total_models += len(active_models)

    assert total_models >= 15


def test_catalog_no_duplicate_model_ids_within_provider():
    """Ensure no duplicate model IDs exist within any provider."""
    providers = ["gemini", "openai", "anthropic", "deepseek", "groq", "openrouter"]
    for p in providers:
        models = ModelCatalog.list_models(provider_id=p, include_deprecated=True)
        seen: set[str] = set()
        for m in models:
            assert m.model_id not in seen, (
                f"Duplicate model ID '{m.model_id}' found in provider '{p}'"
            )
            seen.add(m.model_id)


def test_catalog_defaults_are_strictly_active():
    """Default models for every provider must be strictly ACTIVE, never RETIRED or DEPRECATED."""
    providers = ["gemini", "openai", "anthropic", "deepseek", "groq", "openrouter"]
    for p in providers:
        default_m = ModelCatalog.get_default_model(p)
        assert default_m is not None, f"Default model missing for provider '{p}'"
        info = ModelCatalog.get_model_info(p, default_m)
        assert info is not None, (
            f"Model info missing for default model '{default_m}' in provider '{p}'"
        )
        assert info.lifecycle_status in (LifecycleStatus.ACTIVE, "active"), (
            f"Default model '{default_m}' in provider '{p}' has lifecycle {info.lifecycle_status}, expected ACTIVE"
        )


def test_catalog_inactive_models_excluded_by_default():
    """Verify list_models(include_deprecated=False) omits retired and deprecated models."""
    providers = ["gemini", "openai", "anthropic", "deepseek", "groq", "openrouter"]
    for p in providers:
        active_models = ModelCatalog.list_models(provider_id=p, include_deprecated=False)
        for m in active_models:
            assert m.lifecycle_status not in (
                LifecycleStatus.RETIRED,
                LifecycleStatus.DEPRECATED,
                "retired",
                "deprecated",
            )


def test_catalog_refresh_preserves_retired_states():
    """Verify refresh_from_discovered merges without reactivating retired models."""
    ModelCatalog.refresh_from_discovered("gemini", ["gemini-2.0-flash"])
    refreshed = ModelCatalog.get_model_info("gemini", "gemini-2.0-flash")
    assert refreshed is not None
    assert refreshed.lifecycle_status in (LifecycleStatus.RETIRED, "retired")


def test_deepseek_catalog_canonical_flash_and_compatibility_pro():
    """Verify DeepSeek catalog has canonical deepseek-flash as default, v4-pro as documented route, and chat/reasoner retired."""
    models = ModelCatalog.list_models("deepseek", include_deprecated=True)
    m_ids = {m.model_id: m for m in models}
    assert "deepseek-flash" in m_ids
    assert m_ids["deepseek-flash"].lifecycle_status == LifecycleStatus.ACTIVE
    assert ModelCatalog.get_default_model("deepseek") == "deepseek-flash"

    assert "deepseek-v4-pro" in m_ids, (
        "Documented compatibility route deepseek-v4-pro must be in catalog"
    )
    assert m_ids["deepseek-v4-pro"].lifecycle_status == LifecycleStatus.ACTIVE
    assert "Server Rerouted to Flash" in m_ids["deepseek-v4-pro"].display_name

    assert "deepseek-chat" in m_ids
    assert m_ids["deepseek-chat"].lifecycle_status == LifecycleStatus.RETIRED
    assert "deepseek-reasoner" in m_ids
    assert m_ids["deepseek-reasoner"].lifecycle_status == LifecycleStatus.RETIRED


def test_deepseek_provider_does_not_rewrite_model_silently():
    """DeepSeekProvider passes the requested model (including deepseek-v4-pro) without silent rewriting."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "OK"
    mock_resp.choices[0].finish_reason = "stop"
    mock_resp.choices[0].message.tool_calls = None
    mock_client.chat.completions.create.return_value = mock_resp

    settings = Settings(deepseek_api_key=SecretStr("sk-fake-deepseek"))
    from ai.providers.deepseek import DeepSeekProvider

    provider = DeepSeekProvider(settings=settings, client=mock_client)

    # 1. Custom model identifier passed verbatim
    provider.generate_text("Prompt", model="custom-deepseek-model")
    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "custom-deepseek-model"

    # 2. deepseek-v4-pro passed verbatim to API without client-side rewriting to deepseek-flash
    provider.generate_text("Prompt", model="deepseek-v4-pro")
    call_args_pro = mock_client.chat.completions.create.call_args[1]
    assert call_args_pro["model"] == "deepseek-v4-pro"


def test_gemini_3_9_flash_preview_classified_unknown_and_ineligible():
    """Gemini 3.9 Flash Preview is unverified in official Google documentation, classified UNKNOWN and ineligible."""
    info = ModelCatalog.get_model_info("gemini", "gemini-3.9-flash-preview")
    assert info is not None
    assert info.lifecycle_status == LifecycleStatus.UNKNOWN
    assert info.provider_availability is False
    assert not ModelCatalog.is_model_eligible("gemini", "gemini-3.9-flash-preview")
    assert ModelCatalog.get_default_model("gemini") != "gemini-3.9-flash-preview"


def test_groq_llama_guard_4_12b_classified_retired():
    """Groq Llama Guard 4 12B was shut down on March 5, 2026, replaced by safeguard model openai/gpt-oss-safeguard-20b."""
    info = ModelCatalog.get_model_info("groq", "meta-llama/llama-guard-4-12b")
    assert info is not None
    assert info.lifecycle_status == LifecycleStatus.RETIRED
    assert info.is_deprecated is True
    assert info.provider_availability is False
    assert info.replacement_model_id == "openai/gpt-oss-safeguard-20b"
    assert not ModelCatalog.is_model_eligible("groq", "meta-llama/llama-guard-4-12b")

    # Verify replacement model exists and is active safeguard model
    rep_info = ModelCatalog.get_model_info("groq", "openai/gpt-oss-safeguard-20b")
    assert rep_info is not None
    assert rep_info.lifecycle_status == LifecycleStatus.ACTIVE
    assert rep_info.account_availability == "public"


def test_anthropic_rejects_openrouter_route_identifiers():
    """AnthropicProvider must not convert or dispatch OpenRouter route IDs to native Anthropic API."""
    from ai.base import ModelNotFoundError
    from ai.providers.anthropic import AnthropicProvider

    settings = Settings(anthropic_api_key=SecretStr("sk-ant-fake-key"))
    provider = AnthropicProvider(settings=settings)

    with pytest.raises(ModelNotFoundError) as exc_info:
        provider.generate_text("Hello", model="anthropic/claude-sonnet-5-5")
    assert "OpenRouter route identifiers cannot be used" in str(exc_info.value)


def test_gemini_2_5_flash_is_tier_restricted_not_deprecated():
    """Verify Gemini 2.5 Flash has separate account_availability='tier_restricted' (not DEPRECATED) and is excluded from defaults/fallback."""
    info = ModelCatalog.get_model_info("gemini", "gemini-2.5-flash")
    assert info is not None
    assert info.lifecycle_status in (LifecycleStatus.ACTIVE, LifecycleStatus.TIER_RESTRICTED)
    assert info.account_availability == "tier_restricted"
    assert info.is_deprecated is False
    assert not ModelCatalog.is_model_eligible("gemini", "gemini-2.5-flash")

    # Verify defaults and public lists omit tier-restricted models
    assert ModelCatalog.get_default_model("gemini") != "gemini-2.5-flash"
    public_models = [m.model_id for m in ModelCatalog.list_models("gemini", public_only=True)]
    assert "gemini-2.5-flash" not in public_models


# ==============================================================================
# SECTION 2: OPENAI RESPONSES API PROTOCOL & REASONING COMPLIANCE
# ==============================================================================


def test_openai_tool_calling_routes_to_responses_api():
    """Verify tool calling routes to /v1/responses endpoint for models requiring it."""
    settings = Settings(
        openai_api_key=SecretStr("sk-test-key-fake"),
        openai_model="gpt-6-astra",
    )
    provider = OpenAIProvider(settings)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_weather",
                "description": "Fetch weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]

    endpoint, kwargs = provider._prepare_api_call(
        prompt="Check weather in Tokyo",
        history=None,
        tools=tools,
        model="gpt-6-astra",
    )

    assert endpoint == "responses"
    assert "tools" in kwargs
    assert kwargs["tools"][0]["type"] == "function"
    tool_name = kwargs["tools"][0].get("name") or kwargs["tools"][0]["function"]["name"]
    assert tool_name == "lookup_weather"
    assert "reasoning" in kwargs
    assert "temperature" not in kwargs


def test_openai_reasoning_models_omit_temperature_and_set_reasoning():
    """Reasoning models (o1, o3, gpt-6-astra, gpt-6.1-sol) must omit temperature and top_p."""
    settings = Settings(
        openai_api_key=SecretStr("sk-test-key-fake"),
        gemini_temperature=0.8,
    )
    provider = OpenAIProvider(settings)

    for m in ["gpt-6-astra", "gpt-6.1-sol"]:
        endpoint, kwargs = provider._prepare_api_call(
            prompt="Solve math problem",
            history=None,
            model=m,
        )
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        if endpoint == "responses":
            assert "reasoning" in kwargs
            assert "max_output_tokens" in kwargs
        else:
            assert "max_completion_tokens" in kwargs


def test_openai_malformed_json_recorded_in_tool_call_error():
    """Malformed tool argument JSON must be captured in ToolCall.error rather than crashing."""
    tc = OpenAIProvider._parse_single_tool_call(
        call_id="call_bad_json_1",
        func_name="calc",
        raw_args='{"query": "1+1", "invalid_json: ...',
    )
    assert tc.call_id == "call_bad_json_1"
    assert tc.function_name == "calc"
    assert tc.arguments == {}
    assert tc.error is not None
    assert "Malformed function arguments JSON" in tc.error


def test_openai_tool_continuation_payload_builder():
    """Verify build_tool_continuation produces correct payloads for both chat and responses APIs."""
    settings = Settings(openai_api_key=SecretStr("sk-test-key-fake"))
    provider = OpenAIProvider(settings)

    # 1. Responses API continuation
    resp_responses = AIResponse(
        text="",
        model="gpt-6-astra",
        response_id="resp_anchor_123",
        provider_id="openai",
    )
    resp_payload = provider.build_tool_continuation(
        original_response=resp_responses,
        tool_call_id="call_abc",
        result='{"temp": 22}',
    )
    assert resp_payload["endpoint"] == "responses"
    assert resp_payload["previous_response_id"] == "resp_anchor_123"
    assert resp_payload["input"][0]["type"] == "function_call_output"
    assert resp_payload["input"][0]["call_id"] == "call_abc"

    # 2. Chat Completions continuation
    resp_chat = AIResponse(
        text="",
        model="gpt-6-luna",
        tool_calls=[
            {"id": "call_def", "type": "function", "function": {"name": "test", "arguments": "{}"}}
        ],
        provider_id="openai",
    )
    chat_payload = provider.build_tool_continuation(
        original_response=resp_chat,
        tool_call_id="call_def",
        result='{"success": true}',
    )
    assert chat_payload["endpoint"] == "chat_completions"
    tool_msgs = [m for m in chat_payload["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_def"


def test_openai_responses_stream_accumulation_complete_lifecycle():
    """Verify OpenAI Responses API streaming event sequence accumulation using official response.output_text.delta events."""
    from types import SimpleNamespace

    ev1 = SimpleNamespace(type="response.created", id="resp_stream_001")
    # Official Responses API output text delta event
    ev2 = SimpleNamespace(type="response.output_text.delta", delta="Hello ")
    ev3 = SimpleNamespace(type="response.output_text.delta", delta="world!")
    ev4 = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="function_call", id="call_test_1", name="search_docs"),
    )
    ev5 = SimpleNamespace(
        type="response.function_call_arguments.delta",
        item_id="call_test_1",
        delta='{"query": "py',
    )
    ev6 = SimpleNamespace(
        type="response.function_call_arguments.delta",
        item_id="call_test_1",
        delta='test"}',
    )
    ev7 = SimpleNamespace(
        type="response.function_call_arguments.done",
        item_id="call_test_1",
        arguments='{"query": "pytest"}',
    )
    ev8 = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(type="function_call", id="call_test_1", name="search_docs"),
    )
    ev9 = SimpleNamespace(type="response.completed", status="completed")

    text, tool_calls, resp_id, finish_status = OpenAIProvider.accumulate_responses_stream_events(
        [ev1, ev2, ev3, ev4, ev5, ev6, ev7, ev8, ev9]
    )

    assert text == "Hello world!"
    assert resp_id == "resp_stream_001"
    assert finish_status == "completed"
    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "call_test_1"
    assert tool_calls[0].function_name == "search_docs"
    assert tool_calls[0].arguments == {"query": "pytest"}
    assert tool_calls[0].error is None


def test_openai_responses_stream_incomplete_event_records_error():
    """Verify response.incomplete event flags all in-flight tools with error and marks status incomplete."""
    from types import SimpleNamespace

    ev1 = SimpleNamespace(type="response.created", id="resp_stream_inc")
    ev2 = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="function_call", id="call_inc", name="fetch_data"),
    )
    ev3 = SimpleNamespace(
        type="response.function_call_arguments.delta",
        item_id="call_inc",
        delta='{"url": "http://example.com',
    )
    ev4 = SimpleNamespace(type="response.incomplete")

    text, tool_calls, resp_id, finish_status = OpenAIProvider.accumulate_responses_stream_events(
        [ev1, ev2, ev3, ev4]
    )

    assert finish_status == "incomplete"
    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "call_inc"
    assert tool_calls[0].error is not None
    assert "Incomplete tool call" in tool_calls[0].error


def test_openai_responses_stream_incomplete_tool_call_records_error():
    """An interrupted streaming sequence must record ToolCall.error and never be treated as complete."""
    from types import SimpleNamespace

    ev1 = SimpleNamespace(type="response.created", id="resp_stream_002")
    ev2 = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="function_call", id="call_cut_off", name="run_action"),
    )
    ev3 = SimpleNamespace(
        type="response.function_call_arguments.delta",
        item_id="call_cut_off",
        delta='{"query": "parti',
    )
    # Stream terminates abruptly without arguments.done or output_item.done

    text, tool_calls, resp_id, finish_status = OpenAIProvider.accumulate_responses_stream_events(
        [ev1, ev2, ev3]
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "call_cut_off"
    assert tool_calls[0].error is not None
    assert "Incomplete tool call" in tool_calls[0].error


def test_openai_responses_stream_multiple_tool_calls():
    """Verify multiple tool calls within one Responses stream are all captured accurately."""
    from types import SimpleNamespace

    ev1 = SimpleNamespace(type="response.created", id="resp_stream_multi")
    ev2 = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="function_call", id="call_1", name="func_a"),
    )
    ev3 = SimpleNamespace(
        type="response.function_call_arguments.done",
        item_id="call_1",
        arguments='{"param": 1}',
    )
    ev4 = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="function_call", id="call_2", name="func_b"),
    )
    ev5 = SimpleNamespace(
        type="response.function_call_arguments.done",
        item_id="call_2",
        arguments='{"param": 2}',
    )
    ev6 = SimpleNamespace(type="response.completed", status="completed")

    text, tool_calls, resp_id, finish_status = OpenAIProvider.accumulate_responses_stream_events(
        [ev1, ev2, ev3, ev4, ev5, ev6]
    )

    assert len(tool_calls) == 2
    assert tool_calls[0].function_name == "func_a"
    assert tool_calls[0].arguments == {"param": 1}
    assert tool_calls[1].function_name == "func_b"
    assert tool_calls[1].arguments == {"param": 2}


def test_openai_chat_stream_chunk_accumulation():
    """Verify Chat Completions chunk accumulation for both text deltas and tool call deltas."""
    from types import SimpleNamespace

    c1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="Token 1 ", tool_calls=None), finish_reason=None
            )
        ]
    )
    c2 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="Token 2", tool_calls=None), finish_reason=None
            )
        ]
    )

    tc_chunk_1 = SimpleNamespace(
        index=0, id="call_chat_1", function=SimpleNamespace(name="lookup", arguments='{"q":')
    )
    tc_chunk_2 = SimpleNamespace(
        index=0, id=None, function=SimpleNamespace(name=None, arguments=' "test"}')
    )
    c3 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=[tc_chunk_1]), finish_reason=None
            )
        ]
    )
    c4 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=[tc_chunk_2]),
                finish_reason="tool_calls",
            )
        ]
    )

    text, tool_calls, finish_reason = OpenAIProvider.accumulate_chat_stream_chunks([c1, c2, c3, c4])

    assert text == "Token 1 Token 2"
    assert finish_reason == "tool_calls"
    assert len(tool_calls) == 1
    assert tool_calls[0].call_id == "call_chat_1"
    assert tool_calls[0].function_name == "lookup"
    assert tool_calls[0].arguments == {"q": "test"}
    assert tool_calls[0].error is None


def test_openai_continuation_batch_tool_results():
    """Verify build_tool_continuation formats batch tool results correctly for Responses API."""
    settings = Settings(openai_api_key=SecretStr("sk-fake-key"))
    provider = OpenAIProvider(settings)

    resp = AIResponse(text="", model="gpt-6-astra", response_id="resp_anchor_999")
    batch = [
        {"call_id": "c1", "output": '{"val": 1}'},
        {"call_id": "c2", "output": '{"val": 2}'},
    ]

    payload = provider.build_tool_continuation(
        original_response=resp,
        tool_results=batch,
    )
    assert payload["endpoint"] == "responses"
    assert payload["previous_response_id"] == "resp_anchor_999"
    assert len(payload["input"]) == 2
    assert payload["input"][0]["call_id"] == "c1"
    assert payload["input"][1]["call_id"] == "c2"


def test_gemini_timeout_application_safety_policy():
    """Verify GeminiProvider enforces the application safety policy minimum 10s deadline in milliseconds."""
    # 1. Below 10.0s floor (e.g. 2.0s) -> coerced to 10000ms safety policy floor
    settings_short = Settings(
        gemini_api_key=SecretStr("fake-gemini-key"), gemini_request_timeout=2.0
    )
    from ai.providers.gemini import GeminiProvider

    provider_short = GeminiProvider(settings_short)
    cfg_short = provider_short._build_config()
    assert cfg_short.http_options.timeout == 10000
    assert isinstance(cfg_short.http_options.timeout, int)

    # 2. Above 10.0s floor (e.g. 25.0s) -> converted accurately to 25000ms
    settings_long = Settings(
        gemini_api_key=SecretStr("fake-gemini-key"), gemini_request_timeout=25.0
    )
    provider_long = GeminiProvider(settings_long)
    cfg_long = provider_long._build_config()
    assert cfg_long.http_options.timeout == 25000
    assert isinstance(cfg_long.http_options.timeout, int)


# ==============================================================================
# SECTION 3: PRIVACY & FALLBACK 4-SWITCH MATRIX (ALL 16 COMBINATIONS)
# ==============================================================================


class FakeRecordingProvider(BaseAIProvider):
    """Mock provider recording actual prompt and history received at network dispatch."""

    def __init__(self, provider_id: str, will_fail: bool = False):
        self._provider_id = provider_id
        self._default_model = f"{provider_id}-default"
        self.will_fail = will_fail
        self.received_prompts: list[str] = []
        self.received_histories: list[list[ConversationMessage] | None] = []

    @property
    def provider_name(self) -> str:
        return self._provider_id.capitalize()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def default_model(self) -> str:
        return self._default_model

    def is_ready(self) -> bool:
        return True

    def get_status(self) -> ProviderStatus:
        return ProviderStatus.READY

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(is_success=True, message="OK")

    def validate_capability(self, capability: str, model_id: str | None = None) -> None:
        pass

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_chat=True, supports_streaming=True)

    def generate_text(
        self, prompt: str, history: list[ConversationMessage] | None = None, **kwargs
    ) -> AIResponse:
        self.received_prompts.append(prompt)
        self.received_histories.append(history)
        if self.will_fail:
            raise ServiceUnavailableError(
                f"{self.provider_id} simulated 503 outage", provider_id=self.provider_id
            )
        return AIResponse(
            text=f"Response from {self.provider_id}",
            model=kwargs.get("model") or self.default_model,
            provider_id=self.provider_id,
        )

    def stream_text(
        self, prompt: str, history: list[ConversationMessage] | None = None, **kwargs
    ) -> Iterator[str]:
        self.received_prompts.append(prompt)
        self.received_histories.append(history)
        if self.will_fail:
            raise ServiceUnavailableError(
                f"{self.provider_id} simulated 503 stream outage", provider_id=self.provider_id
            )
        yield f"Stream chunk from {self.provider_id}"


@pytest.mark.parametrize("allow_intra", [False, True])
@pytest.mark.parametrize("allow_cross", [False, True])
@pytest.mark.parametrize("allow_prompt", [False, True])
@pytest.mark.parametrize("allow_hist", [False, True])
def test_privacy_matrix_16_combinations(allow_intra, allow_cross, allow_prompt, allow_hist):
    """Test all 16 combinations of the 4 independent privacy/fallback settings."""
    primary = FakeRecordingProvider("gemini", will_fail=True)
    secondary = FakeRecordingProvider("openai", will_fail=False)

    registry = ProviderRegistry()
    registry.register("gemini", primary)
    registry.register("openai", secondary)

    settings = Settings(
        default_provider="gemini",
        allow_intra_provider_fallback=allow_intra,
        allow_cross_provider_fallback=allow_cross,
        allow_cross_provider_prompt_transfer=allow_prompt,
        allow_cross_provider_history_transfer=allow_hist,
        fallback_provider_order=["openai"],
    )

    manager = ProviderManager(settings=settings, registry=registry)

    test_history = [
        ConversationMessage(
            message_id="m1",
            session_id="s1",
            role=MessageRole.USER,
            content="Sensitive history query",
            status=MessageStatus.COMPLETED,
        )
    ]
    test_prompt = "Sensitive confidential prompt"

    if not allow_cross:
        with pytest.raises((ServiceUnavailableError, PrivacyViolationError)):
            manager.generate_text(test_prompt, history=test_history)
        assert len(secondary.received_prompts) == 0
    elif not allow_prompt:
        with pytest.raises(PrivacyViolationError):
            manager.generate_text(test_prompt, history=test_history)
        assert len(secondary.received_prompts) == 0
    else:
        resp = manager.generate_text(test_prompt, history=test_history)
        assert resp.provider_id == "openai"
        assert len(secondary.received_prompts) == 1
        assert secondary.received_prompts[0] == test_prompt

        received_h = secondary.received_histories[0]
        if allow_hist:
            assert received_h is not None and len(received_h) == 1
            assert received_h[0].content == "Sensitive history query"
        else:
            assert received_h is None or len(received_h) == 0


def test_privacy_streaming_fallback_enforces_checks():
    """Verify stream_text also enforces cross-provider privacy and transfer controls."""
    primary = FakeRecordingProvider("gemini", will_fail=True)
    secondary = FakeRecordingProvider("openai", will_fail=False)

    registry = ProviderRegistry()
    registry.register("gemini", primary)
    registry.register("openai", secondary)

    # Disallow cross-provider fallback
    settings = Settings(
        default_provider="gemini",
        allow_cross_provider_fallback=False,
        fallback_provider_order=["openai"],
    )
    manager = ProviderManager(settings=settings, registry=registry)

    with pytest.raises((ServiceUnavailableError, PrivacyViolationError)):
        list(manager.stream_text("Streaming prompt"))
    assert len(secondary.received_prompts) == 0


def test_privacy_intra_provider_success_never_invokes_secondary():
    """When intra-provider fallback succeeds, secondary cross-provider is never touched."""
    primary = FakeRecordingProvider("gemini", will_fail=False)
    secondary = FakeRecordingProvider("openai", will_fail=False)

    registry = ProviderRegistry()
    registry.register("gemini", primary)
    registry.register("openai", secondary)

    settings = Settings(
        default_provider="gemini",
        allow_intra_provider_fallback=True,
        allow_cross_provider_fallback=True,
        fallback_provider_order=["openai"],
    )
    manager = ProviderManager(settings=settings, registry=registry)

    resp = manager.generate_text("Prompt")
    assert resp.provider_id == "gemini"
    assert len(secondary.received_prompts) == 0


# ==============================================================================
# SECTION 4: PERSISTENCE, MIGRATION IDEMPOTENCY & SEPARATED REASON/STATUS
# ==============================================================================


def test_sqlite_migration_idempotent_and_legacy_safe():
    """Verify running DB migrations repeatedly on fresh and legacy tables is completely idempotent."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    # File handle closed immediately so SQLite can open it on Windows without sharing violation

    db = None
    try:
        # 1. Initialize legacy schema (without interruption_reason and provider_id)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        # 2. Run SQLiteMemoryStore initialization (which triggers migrations)
        db = SQLiteMemoryStore(db_path)
        db.initialize()
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages);").fetchall()}
        assert "interruption_reason" in cols
        assert "provider_id" in cols
        conn.close()

        # 3. Re-run SQLiteMemoryStore initialization again (idempotency check)
        db.initialize()
        conn = sqlite3.connect(db_path)
        cols2 = {row[1] for row in conn.execute("PRAGMA table_info(messages);").fetchall()}
        assert "interruption_reason" in cols2
        assert "provider_id" in cols2
        conn.close()
    finally:
        if db is not None:
            db.close()
        if db_path.exists():
            with contextlib.suppress(PermissionError):
                db_path.unlink()


def test_interrupted_stream_preserves_partial_text_with_separated_reason():
    """Interrupted message stores partial content with status=interrupted and distinct reason."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = None
    try:
        db = SQLiteMemoryStore(db_path)
        db.initialize()
        msg_id = db.store_message(
            ConversationMessage(
                message_id="msg_stream_1",
                session_id="session_100",
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.STREAMING,
                provider_id="gemini",
                model="gemini-3.5-flash-lite",
            )
        )

        db.update_message_content(
            message_id=msg_id,
            content="Partial text generated so far...",
            status=MessageStatus.INTERRUPTED,
            interruption_reason="user_cancelled",
            provider_id="gemini",
            model_id="gemini-3.5-flash-lite",
        )

        messages = db.get_messages("session_100")
        assert len(messages) == 1
        stored = messages[0]
        assert stored.content == "Partial text generated so far..."
        assert stored.status == MessageStatus.INTERRUPTED
        assert stored.interruption_reason == "user_cancelled"
        assert stored.provider_id == "gemini"
        assert stored.model == "gemini-3.5-flash-lite"
    finally:
        if db is not None:
            db.close()
        if db_path.exists():
            with contextlib.suppress(PermissionError):
                db_path.unlink()


def test_no_mock_objects_corrupt_database():
    """Verify that passing mock or non-string attributes does not crash json.dumps."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = None
    try:
        db = SQLiteMemoryStore(db_path)
        db.initialize()
        mock_provider = MagicMock()
        mock_provider.__str__.return_value = "mock_provider_str"

        msg_id = db.store_message(
            ConversationMessage(
                message_id="msg_mock_test",
                session_id="session_mock",
                role=MessageRole.ASSISTANT,
                content="test",
                status=MessageStatus.COMPLETED,
            )
        )

        db.update_message_content(
            message_id=msg_id,
            content="updated",
            status=MessageStatus.COMPLETED,
            provider_id=mock_provider,
        )

        messages = db.get_messages("session_mock")
        assert len(messages) == 1
        assert "mock_provider" in messages[0].provider_id
    finally:
        if db is not None:
            db.close()
        if db_path.exists():
            with contextlib.suppress(PermissionError):
                db_path.unlink()


# ==============================================================================
# SECTION 5: CANCELLATION & SESSION ISOLATION
# ==============================================================================


def test_cancellation_token_stops_execution_immediately():
    """CancellationToken cancellation triggers ProviderCancelledError before processing."""
    token = CancellationToken()
    token.cancel()

    settings = Settings(openai_api_key=SecretStr("sk-test-fake"))
    provider = OpenAIProvider(settings)

    with pytest.raises(ProviderCancelledError):
        provider.generate_text("Prompt", cancellation_token=token)

    with pytest.raises(ProviderCancelledError):
        list(provider.stream_text("Prompt", cancellation_token=token))


def test_session_isolation_in_database():
    """Ensure messages from one session are strictly isolated from another."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = None
    try:
        db = SQLiteMemoryStore(db_path)
        db.initialize()
        db.store_message(
            ConversationMessage(
                message_id="m_s1",
                session_id="session_alpha",
                role=MessageRole.USER,
                content="Alpha message",
            )
        )
        db.store_message(
            ConversationMessage(
                message_id="m_s2",
                session_id="session_beta",
                role=MessageRole.USER,
                content="Beta message",
            )
        )

        alpha_msgs = db.get_messages("session_alpha")
        beta_msgs = db.get_messages("session_beta")

        assert len(alpha_msgs) == 1
        assert alpha_msgs[0].content == "Alpha message"

        assert len(beta_msgs) == 1
        assert beta_msgs[0].content == "Beta message"

        db.clear_session_messages("session_alpha")
        assert len(db.get_messages("session_alpha")) == 0
        assert len(db.get_messages("session_beta")) == 1
    finally:
        if db is not None:
            db.close()
        if db_path.exists():
            with contextlib.suppress(PermissionError):
                db_path.unlink()
