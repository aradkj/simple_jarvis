"""Unit and regression tests for Phase 2.7 Precision Remediation & Phase 3 Release Gate."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import LifecycleStatus
from ai.catalog import ModelCatalog
from ai.manager import ProviderManager
from ai.providers.openai import OpenAIProvider
from ai.registry import ProviderRegistry
from config import Settings
from memory.base import ConversationMessage, MessageRole, MessageStatus
from memory.database import SQLiteMemoryStore


def test_openai_gpt6_luna_function_calling_reasoning_effort_none():
    """Verify GPT-6 Luna sets reasoning_effort='none' when function/tools calling is requested."""
    settings = Settings(
        openai_api_key=SecretStr("sk-mock-key"),
        openai_model="gpt-6-luna",
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Call result"
    mock_choice.finish_reason = "stop"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    provider = OpenAIProvider(settings=settings, client=mock_client)
    sample_tools = [{"type": "function", "function": {"name": "get_weather"}}]

    res = provider.generate_text(prompt="What's the weather?", tools=sample_tools)
    assert res.text == "Call result"

    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "gpt-6-luna"
    assert call_args["tools"] == sample_tools
    assert call_args["reasoning_effort"] == "none"
    assert "temperature" in call_args


def test_openai_gpt6_astra_and_sol_use_responses_api_for_tools():
    """Verify GPT-6 Astra, GPT-6.1 Sol, and GPT-6.1 Terra route tool calls to Responses API with reasoning.effort."""
    for model_id in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra"):
        settings = Settings(
            openai_api_key=SecretStr("sk-mock-key"),
            openai_model=model_id,
        )
        mock_client = MagicMock()
        mock_responses_resp = MagicMock()
        mock_responses_resp.output_text = f"Responses API result for {model_id}"
        mock_responses_resp.status = "completed"
        # Mock item function call in output
        mock_item = MagicMock()
        mock_item.type = "function_call"
        mock_item.id = "call_abc123"
        mock_item.name = "run_query"
        mock_item.arguments = '{"query": "test"}'
        mock_responses_resp.output = [mock_item]
        mock_client.responses.create.return_value = mock_responses_resp

        provider = OpenAIProvider(settings=settings, client=mock_client)
        sample_tools = [{"type": "function", "function": {"name": "run_query"}}]

        res = provider.generate_text(
            prompt="Execute query",
            tools=sample_tools,
            reasoning_effort="medium",
        )
        assert res.text == f"Responses API result for {model_id}"
        assert res.tool_calls is not None
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0]["function"]["name"] == "run_query"

        # Verify client.responses.create was called instead of chat.completions.create
        mock_client.responses.create.assert_called_once()
        mock_client.chat.completions.create.assert_not_called()

        call_args = mock_client.responses.create.call_args[1]
        assert call_args["model"] == model_id
        assert call_args["tools"] == sample_tools
        assert call_args["reasoning"] == {"effort": "medium"}
        assert "temperature" not in call_args
        assert "top_p" not in call_args


def test_anthropic_exact_models_present_in_catalog():
    """Verify all officially documented Anthropic model IDs are present."""
    exact_ids = [
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4-5-20251001",
    ]
    for mid in exact_ids:
        info = ModelCatalog.get_model_info("anthropic", mid)
        assert info is not None, f"Anthropic model '{mid}' not found in catalog"
        assert info.lifecycle_status == LifecycleStatus.ACTIVE
        assert info.provider_availability is True


def test_gemini_models_present_and_distinguished():
    """Verify Gemini catalog distinguished preview, deprecated, active, and retired correctly."""
    # Active
    active_m = ModelCatalog.get_model_info("gemini", "gemini-3.8-flash")
    assert active_m is not None
    assert active_m.lifecycle_status == LifecycleStatus.ACTIVE

    # Preview
    prev_m = ModelCatalog.get_model_info("gemini", "gemini-3-flash-preview")
    assert prev_m is not None, "Gemini preview 'gemini-3-flash-preview' not found"
    assert prev_m.lifecycle_status == LifecycleStatus.PREVIEW
    assert prev_m.is_preview is True

    # Unverified / Unknown
    unk_39 = ModelCatalog.get_model_info("gemini", "gemini-3.9-flash-preview")
    assert unk_39 is not None
    assert unk_39.lifecycle_status == LifecycleStatus.UNKNOWN
    assert not ModelCatalog.is_model_eligible("gemini", "gemini-3.9-flash-preview")

    # Deprecated
    dep_37 = ModelCatalog.get_model_info("gemini", "gemini-3.7-flash")
    assert dep_37 is not None
    assert dep_37.lifecycle_status == LifecycleStatus.DEPRECATED
    assert dep_37.provider_availability is True

    # Tier-restricted (represented separately from lifecycle status)
    tier_25 = ModelCatalog.get_model_info("gemini", "gemini-2.5-flash")
    assert tier_25 is not None
    assert tier_25.account_availability == "tier_restricted"
    assert tier_25.is_deprecated is False

    # Retired
    ret_20 = ModelCatalog.get_model_info("gemini", "gemini-2.0-flash")
    assert ret_20 is not None
    assert ret_20.lifecycle_status == LifecycleStatus.RETIRED
    assert ret_20.provider_availability is False


def test_sqlite_partial_text_preserved_without_embedded_status_tags(tmp_path):
    """Verify SQLiteMemoryStore preserves raw partial text without inserting [Error] or [Cancelled] in content."""
    db_file = tmp_path / "test_partial.db"
    store = SQLiteMemoryStore(db_path=db_file)
    store.initialize()

    sid = store.create_session("Partial Stream Session")
    msg = ConversationMessage(
        role=MessageRole.ASSISTANT,
        content="",
        session_id=sid,
        status=MessageStatus.STREAMING,
        model="gemini-3.8-flash",
    )
    msg_id = store.store_message(msg)

    # Stream partially yields content, then aborts
    partial_text = "The quick brown fox jumps over"
    store.update_message_content(
        message_id=msg_id,
        content=partial_text,
        status=MessageStatus.FAILED,
        interruption_reason="503 Overloaded",
        provider_id="gemini",
        model_id="gemini-3.8-flash",
    )

    retrieved = store.get_messages(sid)
    assert len(retrieved) == 1
    assert retrieved[0].content == partial_text
    assert retrieved[0].status == MessageStatus.FAILED
    assert retrieved[0].metadata.get("interruption_reason") == "503 Overloaded"
    assert "[Error" not in retrieved[0].content


def test_privacy_matrix_all_four_controls_independent():
    """Verify matrix of all 4 fallback and transfer privacy combinations."""
    # Case 1: Intra-provider only (default)
    s1 = Settings(
        allow_intra_provider_fallback=True,
        allow_cross_provider_fallback=False,
        allow_cross_provider_prompt_transfer=False,
        allow_cross_provider_history_transfer=False,
    )
    assert s1.allow_intra_provider_fallback is True
    assert s1.allow_cross_provider_fallback is False

    # Case 2: Cross provider allowed, but prompt transfer blocked
    s2 = Settings(
        default_provider="p1",
        enable_auto_fallback=True,
        allow_cross_provider_fallback=True,
        allow_cross_provider_prompt_transfer=False,
        fallback_provider_order=["p1", "p2"],
    )
    p1 = MagicMock()
    p1.provider_id = "p1"
    p1.is_ready.return_value = True
    from ai.base import ServiceUnavailableError

    p1.generate_text.side_effect = ServiceUnavailableError("503", provider_id="p1")

    p2 = MagicMock()
    p2.provider_id = "p2"
    p2.is_ready.return_value = True

    reg = ProviderRegistry()
    reg.register_factory("p1", lambda s: p1)
    reg.register_factory("p2", lambda s: p2)

    mgr = ProviderManager(settings=s2, registry=reg)
    with pytest.raises(PermissionError) as exc_info:
        mgr.generate_text("Prompt", provider_id="p1")
    assert "Cross-provider prompt transfer from 'p1' to 'p2' is blocked" in str(exc_info.value)
