"""Unit and regression tests for Phase 2.5.2 Model Catalog Lifecycle Audit & Integrity."""

from ai.base import LifecycleStatus, ModelCapabilities, ModelInfo
from ai.catalog import ModelCatalog
from config import Settings, get_project_root


def test_every_default_model_has_active_lifecycle_status() -> None:
    """Verify that every provider default is strictly verified as ACTIVE in the catalog."""
    expected_defaults = {
        "gemini": "gemini-3.8-flash",
        "openai": "gpt-6-luna",
        "anthropic": "claude-sonnet-5-5",
        "deepseek": "deepseek-flash",
        "openrouter": "anthropic/claude-sonnet-5-5",
        "groq": "openai/gpt-oss-120b",
    }
    for pid, expected_model in expected_defaults.items():
        actual_default = ModelCatalog.get_default_model(pid)
        assert actual_default == expected_model, (
            f"Provider '{pid}' default was '{actual_default}', expected '{expected_model}'"
        )
        info = ModelCatalog.get_model_info(pid, actual_default)
        assert info is not None, f"Default model '{actual_default}' for '{pid}' not in catalog"
        assert info.lifecycle_status == LifecycleStatus.ACTIVE
        assert not info.is_deprecated
        assert not info.is_preview
        assert info.provider_availability is True


def test_retired_models_cannot_be_selected_as_defaults() -> None:
    """Verify that officially retired models are never returned as defaults and are flagged as retired."""
    retired_cases = [
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("anthropic", "claude-3-5-haiku-20241022"),
        ("anthropic", "claude-3-7-sonnet-20250219"),
        ("anthropic", "claude-3-opus-20240229"),
        ("groq", "mixtral-8x7b-32768"),
        ("groq", "deepseek-r1-distill-llama-70b"),
        ("groq", "qwen-2.5-32b"),
        ("deepseek", "deepseek-chat"),
        ("deepseek", "deepseek-reasoner"),
        ("gemini", "gemini-1.5-pro"),
        ("gemini", "gemini-1.5-flash"),
        ("gemini", "gemini-2.0-flash"),
        ("openai", "o1"),
        ("openai", "o3-mini"),
    ]
    for pid, model_id in retired_cases:
        info = ModelCatalog.get_model_info(pid, model_id)
        assert info is not None, f"Expected retired model '{model_id}' in '{pid}' catalog"
        assert info.lifecycle_status == LifecycleStatus.RETIRED
        assert info.is_deprecated is True
        assert info.provider_availability is False
        assert ModelCatalog.is_model_retired(pid, model_id) is True

        # Default for provider must NOT be this retired model
        assert ModelCatalog.get_default_model(pid) != model_id


def test_deprecated_models_cannot_be_selected_as_defaults() -> None:
    """Verify deprecated models (announced retirement prior to shutdown) are not defaults."""
    deprecated_cases = [
        ("openai", "gpt-4o"),
        ("openai", "gpt-4o-mini"),
        ("gemini", "gemini-3.5-flash"),
        ("gemini", "gemini-3.7-flash"),
    ]
    for pid, model_id in deprecated_cases:
        info = ModelCatalog.get_model_info(pid, model_id)
        assert info is not None, f"Expected model '{model_id}' in '{pid}' catalog"
        assert info.lifecycle_status == LifecycleStatus.DEPRECATED
        assert info.is_deprecated is True
        # Provider availability remains True while shutdown date has not passed
        assert info.provider_availability is True
        assert ModelCatalog.is_model_deprecated(pid, model_id) is True

        # Default for provider must NOT be this deprecated model
        assert ModelCatalog.get_default_model(pid) != model_id


def test_unknown_models_cannot_silently_become_production_defaults() -> None:
    """Verify uncataloged or unknown models cannot become defaults."""
    # When asking default for unknown provider, returns empty or active
    assert ModelCatalog.get_default_model("nonexistent_vendor") == ""

    # Even if an unknown model is registered with UNKNOWN status, it is not a default
    ModelCatalog.register_custom_model(
        ModelInfo(
            provider_id="openai",
            model_id="unverified-experimental-v99",
            display_name="Unverified Model",
            capabilities=ModelCapabilities(),
            lifecycle_status=LifecycleStatus.UNKNOWN,
        ),
        overwrite=True,
    )
    try:
        assert ModelCatalog.get_default_model("openai") != "unverified-experimental-v99"
        assert ModelCatalog.get_default_model("openai") == "gpt-6-luna"
    finally:
        from ai.catalog import _CATALOG

        _CATALOG["openai"] = [
            m for m in _CATALOG["openai"] if m.model_id != "unverified-experimental-v99"
        ]


def test_legacy_models_distinguishable_from_retired() -> None:
    """Verify that LEGACY models are distinct from RETIRED models (available vs shut down)."""
    # OpenRouter legacy route: anthropic/claude-3.5-sonnet
    info = ModelCatalog.get_model_info("openrouter", "anthropic/claude-3.5-sonnet")
    assert info is not None
    assert info.lifecycle_status == LifecycleStatus.LEGACY
    assert info.lifecycle_status != LifecycleStatus.RETIRED
    # Legacy models still have provider availability
    assert info.provider_availability is True
    assert ModelCatalog.is_model_retired("openrouter", "anthropic/claude-3.5-sonnet") is False


def test_preview_models_remain_identifiable() -> None:
    """Verify preview models are marked with is_preview=True and excluded from non-preview listing."""
    info = ModelCatalog.get_model_info("gemini", "gemini-3-flash-preview")
    assert info is not None
    assert info.is_preview is True
    assert info.lifecycle_status == LifecycleStatus.PREVIEW

    active_default = ModelCatalog.get_default_model("gemini")
    assert active_default != "gemini-3-flash-preview"
    assert active_default == "gemini-3.8-flash"


def test_openrouter_routes_evaluated_independently() -> None:
    """Verify that OpenRouter route lifecycles are decoupled from original vendor direct APIs."""
    # Anthropic direct API retired claude-3-5-sonnet-20241022
    anthropic_info = ModelCatalog.get_model_info("anthropic", "claude-3-5-sonnet-20241022")
    assert anthropic_info is not None
    assert anthropic_info.lifecycle_status == LifecycleStatus.RETIRED
    assert anthropic_info.provider_availability is False

    # OpenRouter route for Claude 3.5 Sonnet is LEGACY (still routed through partners)
    openrouter_claude = ModelCatalog.get_model_info("openrouter", "anthropic/claude-3.5-sonnet")
    assert openrouter_claude is not None
    assert openrouter_claude.lifecycle_status == LifecycleStatus.LEGACY
    assert openrouter_claude.provider_availability is True

    # DeepSeek direct API retired deepseek-reasoner
    deepseek_reasoner = ModelCatalog.get_model_info("deepseek", "deepseek-reasoner")
    assert deepseek_reasoner is not None
    assert deepseek_reasoner.lifecycle_status == LifecycleStatus.RETIRED
    assert deepseek_reasoner.provider_availability is False

    # OpenRouter route for DeepSeek R1 is ACTIVE (hosted on third-party inference)
    openrouter_r1 = ModelCatalog.get_model_info("openrouter", "deepseek/deepseek-r1")
    assert openrouter_r1 is not None
    assert openrouter_r1.lifecycle_status == LifecycleStatus.ACTIVE
    assert openrouter_r1.provider_availability is True

    # OpenAI direct API deprecated gpt-4o with sunset scheduled
    openai_4o = ModelCatalog.get_model_info("openai", "gpt-4o")
    assert openai_4o is not None
    assert openai_4o.lifecycle_status == LifecycleStatus.DEPRECATED

    # OpenRouter route for gpt-4o is ACTIVE multi-host route
    openrouter_4o = ModelCatalog.get_model_info("openrouter", "openai/gpt-4o")
    assert openrouter_4o is not None
    assert openrouter_4o.lifecycle_status == LifecycleStatus.ACTIVE
    assert openrouter_4o.provider_availability is True


def test_catalog_refresh_cannot_reactivate_retired_models() -> None:
    """Verify dynamic discovery never reactivates models cataloged as retired or deprecated."""
    ModelCatalog.refresh_from_discovered("groq", ["mixtral-8x7b-32768"])
    groq_info = ModelCatalog.get_model_info("groq", "mixtral-8x7b-32768")
    assert groq_info is not None
    assert groq_info.lifecycle_status == LifecycleStatus.RETIRED
    assert groq_info.is_deprecated is True
    assert groq_info.provider_availability is False

    ModelCatalog.refresh_from_discovered("anthropic", ["claude-3-5-sonnet-20241022"])
    ant_info = ModelCatalog.get_model_info("anthropic", "claude-3-5-sonnet-20241022")
    assert ant_info is not None
    assert ant_info.lifecycle_status == LifecycleStatus.RETIRED
    assert ant_info.is_deprecated is True
    assert ant_info.provider_availability is False


def test_custom_models_remain_preserved() -> None:
    """Verify registering a custom model preserves it and does not overwrite existing entries unexpectedly."""
    custom = ModelInfo(
        provider_id="groq",
        model_id="custom-llama-fine-tune-001",
        display_name="Custom Llama Fine-Tune",
        capabilities=ModelCapabilities(streaming_supported=True, context_window=64000),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    registered = ModelCatalog.register_custom_model(custom, overwrite=False)
    assert registered is True

    try:
        # Second register with overwrite=False must reject
        dupe = ModelInfo(
            provider_id="groq",
            model_id="custom-llama-fine-tune-001",
            display_name="Overwritten Name Attempt",
            capabilities=ModelCapabilities(),
        )
        registered_dupe = ModelCatalog.register_custom_model(dupe, overwrite=False)
        assert registered_dupe is False

        fetched = ModelCatalog.get_model_info("groq", "custom-llama-fine-tune-001")
        assert fetched is not None
        assert fetched.display_name == "Custom Llama Fine-Tune"
    finally:
        from ai.catalog import _CATALOG

        _CATALOG["groq"] = [
            m for m in _CATALOG["groq"] if m.model_id != "custom-llama-fine-tune-001"
        ]


def test_existing_gemini_settings_preserved_and_unchanged() -> None:
    """Verify existing .env or .env.example configuration and user-configured Gemini settings."""
    env_file = get_project_root() / ".env"
    if not env_file.exists():
        env_file = get_project_root() / ".env.example"
    assert env_file.exists(), ".env or .env.example file must exist"

    with open(env_file, encoding="utf-8") as f:
        content = f.read()

    # The existing working Gemini configuration must be present
    assert "GEMINI_MODEL=" in content
    assert "GEMINI_API_KEY=" in content

    # Settings object loaded from this env preserves user's gemini_model
    settings = Settings()
    assert settings.gemini_model != ""


def test_tier_restricted_models_and_privacy_settings():
    """Verify Phase 2.6 privacy controls and tier restriction safeguards."""
    # Groq tier restricted model
    assert ModelCatalog.is_model_tier_restricted("groq", "llama-3.3-70b-versatile") is True
    assert ModelCatalog.is_model_tier_restricted("groq", "llama-3.1-8b-instant") is True
    assert ModelCatalog.is_model_tier_restricted("groq", "openai/gpt-oss-120b") is False

    warning = ModelCatalog.get_model_status_warning("groq", "llama-3.3-70b-versatile")
    assert "Enterprise only" in warning

    # Verify Settings defaults for 4 privacy controls
    s = Settings()
    assert s.allow_intra_provider_fallback is True
    assert s.allow_cross_provider_fallback is False
    assert s.allow_cross_provider_prompt_transfer is False
    assert s.allow_cross_provider_history_transfer is False
    assert s.groq_model == "openai/gpt-oss-120b"


def test_complete_lifecycle_audit_metadata_every_provider() -> None:
    """Verify that every provider has complete audit metadata for all its models."""
    for pid in ("gemini", "openai", "anthropic", "deepseek", "openrouter", "groq"):
        models = ModelCatalog.list_models(pid, include_deprecated=True)
        assert len(models) >= 2, f"Provider '{pid}' has insufficient models"
        for m in models:
            assert m.documentation_url is not None and m.documentation_url.startswith("http"), (
                f"Model '{m.model_id}' in '{pid}' missing valid documentation_url"
            )
            assert m.lifecycle_status in (
                LifecycleStatus.ACTIVE,
                LifecycleStatus.LEGACY,
                LifecycleStatus.DEPRECATED,
                LifecycleStatus.RETIRED,
                LifecycleStatus.PREVIEW,
                LifecycleStatus.UNKNOWN,
            ), f"Model '{m.model_id}' in '{pid}' has invalid status: {m.lifecycle_status}"
            assert m.verified_at != "", f"Model '{m.model_id}' in '{pid}' missing verified_at"
            assert m.endpoint_type in (
                "generate_content",
                "chat_completions",
                "messages",
            ), f"Model '{m.model_id}' in '{pid}' has unexpected endpoint_type: {m.endpoint_type}"

            # If retired or deprecated, must offer replacement
            if m.lifecycle_status in (LifecycleStatus.RETIRED, LifecycleStatus.DEPRECATED):
                rep = ModelCatalog.get_replacement_model(pid, m.model_id)
                assert rep != "", f"Retired/deprecated model '{m.model_id}' has no replacement"
                assert rep != m.model_id, (
                    f"Model '{m.model_id}' replacement cannot be itself when retired/deprecated"
                )
                rep_info = ModelCatalog.get_model_info(pid, rep)
                assert rep_info is not None, f"Replacement model '{rep}' not found in catalog"
                assert rep_info.lifecycle_status in (
                    LifecycleStatus.ACTIVE,
                    LifecycleStatus.LEGACY,
                    LifecycleStatus.PREVIEW,
                )
