"""Model catalog and capabilities registry for all supported AI providers."""

from ai.base import LifecycleStatus, ModelCapabilities, ModelInfo

# --- Static Model Definitions & Verified Capabilities ---

_GEMINI_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash (Recommended Flagship GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        is_preview=False,
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id=None,
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash-Lite (Fast & Cost-Efficient GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id=None,
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite (High Throughput GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=32768,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id=None,
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.9-flash-preview",
        display_name="Gemini 3.9 Flash Preview (Unverified - Restricted)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        is_preview=False,
        lifecycle_status=LifecycleStatus.UNKNOWN,
        provider_availability=False,
        account_availability="unverified",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.8-flash",
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash Preview (Early Prototype)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=32768,
        ),
        is_preview=True,
        lifecycle_status=LifecycleStatus.PREVIEW,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id=None,
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.7-flash",
        display_name="Gemini 3.7 Flash (Deprecated - Deprecated Oct 8, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.DEPRECATED,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.8-flash",
        documentation_url="https://ai.google.dev/gemini-api/docs/deprecations",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash (Deprecated - Deprecated Oct 8, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.DEPRECATED,
        provider_availability=True,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.8-flash",
        documentation_url="https://ai.google.dev/gemini-api/docs/deprecations",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash (Tier Restricted - Legacy Projects)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=65536,
        ),
        is_deprecated=False,
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="tier_restricted",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.5-flash-lite",
        documentation_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash (Retired - Shutdown June 1, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.8-flash",
        documentation_url="https://ai.google.dev/gemini-api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-1.5-pro",
        display_name="Gemini 1.5 Pro (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=2097152,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.8-flash",
        documentation_url="https://ai.google.dev/gemini-api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="gemini",
        model_id="gemini-1.5-flash",
        display_name="Gemini 1.5 Flash (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="generate_content",
        replacement_model_id="gemini-3.5-flash-lite",
        documentation_url="https://ai.google.dev/gemini-api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_OPENAI_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="openai",
        model_id="gpt-6-luna",
        display_name="GPT-6 Luna (Recommended Production GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://developers.openai.com/api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-6-astra",
        display_name="GPT-6 Astra (Flagship Reasoning & Coding GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://developers.openai.com/api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-6.1-sol",
        display_name="GPT-6.1 Sol (Near-Astra Advanced Reasoning)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://developers.openai.com/api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-6.1-terra",
        display_name="GPT-6.1 Terra (Visual Reasoning & Fast)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://developers.openai.com/api/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-4o",
        display_name="GPT-4o (Unversioned Alias - Sunset Jan 14, 2027)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=128000,
            maximum_output_tokens=16384,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.DEPRECATED,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="gpt-6-luna",
        documentation_url="https://developers.openai.com/api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini (Unversioned Alias - Sunset Jan 14, 2027)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=128000,
            maximum_output_tokens=16384,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.DEPRECATED,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="gpt-6-luna",
        documentation_url="https://developers.openai.com/api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="gpt-4o-2024-05-13",
        display_name="GPT-4o (Snapshot 2024-05-13 - Retired Oct 23, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=128000,
            maximum_output_tokens=4096,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="gpt-6-luna",
        documentation_url="https://developers.openai.com/api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="o1",
        display_name="o1 (Retired - Shutdown Oct 23, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=100000,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="gpt-6-astra",
        documentation_url="https://developers.openai.com/api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openai",
        model_id="o3-mini",
        display_name="o3-mini (Retired - Shutdown Oct 23, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=200000,
            maximum_output_tokens=100000,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="gpt-6-astra",
        documentation_url="https://developers.openai.com/api/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_ANTHROPIC_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-sonnet-5-5",
        display_name="Claude Sonnet 5.5 (Flagship Workhorse GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-haiku-5-5",
        display_name="Claude Haiku 5.5 (High Speed & Low Latency GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-opus-5-5",
        display_name="Claude Opus 5.5 (Deep Reasoning & Agentic GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-sonnet-5",
        display_name="Claude Sonnet 5 (High Capability Intermediate)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=64000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-opus-5",
        display_name="Claude Opus 5 (Deep Reasoning Intermediate)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=64000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5 Snapshot (Pinned Oct 1, 2025)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=500000,
            maximum_output_tokens=32768,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id=None,
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-3-7-sonnet-20250219",
        display_name="Claude 3.7 Sonnet (Retired - Shutdown Feb 19, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=64000,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id="claude-sonnet-5-5",
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet v2 (Retired - Shutdown Oct 28, 2025)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id="claude-sonnet-5-5",
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku (Retired - Shutdown Feb 19, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=200000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id="claude-haiku-5-5",
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="anthropic",
        model_id="claude-3-opus-20240229",
        display_name="Claude 3 Opus (Retired - Shutdown Jan 5, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=4096,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="messages",
        replacement_model_id="claude-opus-5-5",
        documentation_url="https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_DEEPSEEK_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="deepseek",
        model_id="deepseek-flash",
        display_name="DeepSeek V4.1 Flash (GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=16384,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://api-docs.deepseek.com",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="deepseek",
        model_id="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro (Documented API Route - Server Rerouted to Flash)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1048576,
            maximum_output_tokens=16384,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="deepseek-flash",
        documentation_url="https://api-docs.deepseek.com/news/news260910/",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="deepseek",
        model_id="deepseek-chat",
        display_name="DeepSeek Chat (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=64000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="deepseek-flash",
        documentation_url="https://api-docs.deepseek.com",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="deepseek",
        model_id="deepseek-reasoner",
        display_name="DeepSeek Reasoner R1 (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=False,
            tool_calling_supported=False,
            vision_supported=False,
            context_window=64000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="deepseek-flash",
        documentation_url="https://api-docs.deepseek.com",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_OPENROUTER_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="openrouter",
        model_id="anthropic/claude-sonnet-5-5",
        display_name="OpenRouter: Claude Sonnet 5.5",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=128000,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="openai/gpt-4o",
        display_name="OpenRouter: GPT-4o (Active Multi-Host Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=128000,
            maximum_output_tokens=4096,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="deepseek/deepseek-r1",
        display_name="OpenRouter: DeepSeek R1 (Active Gateway Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=False,
            tool_calling_supported=False,
            vision_supported=False,
            context_window=163840,
            maximum_output_tokens=8192,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="anthropic/claude-3.5-sonnet",
        display_name="OpenRouter: Claude 3.5 Sonnet (Legacy Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=8192,
        ),
        lifecycle_status=LifecycleStatus.LEGACY,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="anthropic/claude-sonnet-5-5",
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="anthropic/claude-3.7-sonnet",
        display_name="OpenRouter: Claude 3.7 Sonnet (Legacy Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=200000,
            maximum_output_tokens=64000,
        ),
        lifecycle_status=LifecycleStatus.LEGACY,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="anthropic/claude-sonnet-5-5",
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="deepseek/deepseek-chat",
        display_name="OpenRouter: DeepSeek V3 (Legacy Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=64000,
            maximum_output_tokens=8192,
        ),
        lifecycle_status=LifecycleStatus.LEGACY,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="deepseek/deepseek-r1",
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="openrouter",
        model_id="google/gemini-2.0-flash-001",
        display_name="OpenRouter: Gemini 2.0 Flash (Retired Route)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=True,
            context_window=1000000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="anthropic/claude-sonnet-5-5",
        documentation_url="https://openrouter.ai/docs",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_GROQ_MODELS: list[ModelInfo] = [
    ModelInfo(
        provider_id="groq",
        model_id="openai/gpt-oss-120b",
        display_name="Groq: OpenAI GPT-OSS 120B (Recommended Universal GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=131072,
            maximum_output_tokens=65536,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://console.groq.com/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="openai/gpt-oss-20b",
        display_name="Groq: OpenAI GPT-OSS 20B (High-Speed Universal GA)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=131072,
            maximum_output_tokens=65536,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://console.groq.com/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="llama-3.3-70b-versatile",
        display_name="Groq: Llama 3.3 70B Versatile (Enterprise Tier)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=128000,
            maximum_output_tokens=32768,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="tier_restricted",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-120b",
        documentation_url="https://console.groq.com/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="llama-3.1-8b-instant",
        display_name="Groq: Llama 3.1 8B Instant (Enterprise Tier)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=128000,
            maximum_output_tokens=8192,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="tier_restricted",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-20b",
        documentation_url="https://console.groq.com/docs/models",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="openai/gpt-oss-safeguard-20b",
        display_name="Groq: OpenAI GPT-OSS Safeguard 20B (Active Moderation & Safety)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=False,
            vision_supported=False,
            context_window=131072,
            maximum_output_tokens=4096,
        ),
        lifecycle_status=LifecycleStatus.ACTIVE,
        provider_availability=True,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id=None,
        documentation_url="https://console.groq.com/docs/models",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="meta-llama/llama-guard-4-12b",
        display_name="Groq: Llama Guard 4 12B (Retired - Shutdown March 5, 2026)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=False,
            tool_calling_supported=False,
            vision_supported=True,
            context_window=131072,
            maximum_output_tokens=4096,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-safeguard-20b",
        documentation_url="https://console.groq.com/docs/deprecations",
        verified_at="2026-11-13",
        verification_date="2026-11-13",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="deepseek-r1-distill-llama-70b",
        display_name="Groq: DeepSeek R1 Distill Llama 70B (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=128000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-120b",
        documentation_url="https://console.groq.com/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="qwen-2.5-32b",
        display_name="Groq: Qwen 2.5 32B (Retired)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=128000,
            maximum_output_tokens=8192,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-120b",
        documentation_url="https://console.groq.com/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
    ModelInfo(
        provider_id="groq",
        model_id="mixtral-8x7b-32768",
        display_name="Groq: Mixtral 8x7B (Retired / Decommissioned)",
        capabilities=ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=True,
            tool_calling_supported=True,
            vision_supported=False,
            context_window=32768,
            maximum_output_tokens=4096,
        ),
        is_deprecated=True,
        lifecycle_status=LifecycleStatus.RETIRED,
        provider_availability=False,
        account_availability="public",
        endpoint_type="chat_completions",
        replacement_model_id="openai/gpt-oss-120b",
        documentation_url="https://console.groq.com/docs/deprecations",
        verified_at="2026-11-12",
        verification_date="2026-11-12",
    ),
]

_CATALOG: dict[str, list[ModelInfo]] = {
    "gemini": _GEMINI_MODELS,
    "openai": _OPENAI_MODELS,
    "anthropic": _ANTHROPIC_MODELS,
    "deepseek": _DEEPSEEK_MODELS,
    "openrouter": _OPENROUTER_MODELS,
    "groq": _GROQ_MODELS,
}

# Every default model here is strictly verified as ACTIVE and universally public (non-tier-restricted)
_DEFAULTS: dict[str, str] = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-6-luna",
    "anthropic": "claude-sonnet-5-5",
    "deepseek": "deepseek-flash",
    "openrouter": "anthropic/claude-sonnet-5-5",
    "groq": "openai/gpt-oss-120b",
}


class ModelCatalog:
    """Provider-aware model catalog and capabilities registry."""

    @staticmethod
    def list_models(
        provider_id: str,
        include_deprecated: bool = False,
        public_only: bool = False,
    ) -> list[ModelInfo]:
        """Return cataloged models for a specified provider.

        Excludes deprecated/retired by default and filters tier-restricted when public_only is True.
        """
        pid = provider_id.lower().strip().replace("google-", "")
        models = _CATALOG.get(pid, [])
        result: list[ModelInfo] = []
        for m in models:
            if not include_deprecated and (
                m.is_deprecated
                or m.lifecycle_status
                in (
                    LifecycleStatus.RETIRED,
                    LifecycleStatus.DEPRECATED,
                    LifecycleStatus.UNKNOWN,
                    "retired",
                    "deprecated",
                    "unknown",
                )
            ):
                continue
            if public_only and m.account_availability == "tier_restricted":
                continue
            result.append(m)
        return result

    @staticmethod
    def get_model_info(provider_id: str, model_id: str) -> ModelInfo | None:
        """Find model info for a provider and model identifier."""
        models = ModelCatalog.list_models(provider_id, include_deprecated=True)
        for m in models:
            if m.model_id == model_id:
                return m
        return None

    get_model = get_model_info

    @staticmethod
    def get_default_model(provider_id: str, public_only: bool = True) -> str:
        """Return default recommended model for a provider, strictly ensuring it is active and public."""
        pid = provider_id.lower().strip().replace("google-", "")
        default_model = _DEFAULTS.get(pid, "")
        info = ModelCatalog.get_model_info(pid, default_model)
        # Check if default is valid and strictly active
        if (
            info is None
            or info.is_deprecated
            or info.lifecycle_status != LifecycleStatus.ACTIVE
            or (public_only and info.account_availability == "tier_restricted")
        ):
            # Fallback to the first verified ACTIVE and public model in the provider's catalog
            active = [
                m
                for m in ModelCatalog.list_models(
                    pid, include_deprecated=False, public_only=public_only
                )
                if m.lifecycle_status == LifecycleStatus.ACTIVE
            ]
            if active:
                return active[0].model_id
        return default_model

    @staticmethod
    def is_model_retired(provider_id: str, model_id: str) -> bool:
        """Check if model is officially retired / shut down."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if info:
            return bool(
                info.lifecycle_status in (LifecycleStatus.RETIRED, "retired")
                or (info.is_deprecated and not info.provider_availability)
            )
        return False

    @staticmethod
    def is_model_deprecated(provider_id: str, model_id: str) -> bool:
        """Check if model is deprecated (announced retirement) or retired."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if info:
            return bool(
                info.is_deprecated
                or info.lifecycle_status
                in (
                    LifecycleStatus.DEPRECATED,
                    LifecycleStatus.RETIRED,
                    "deprecated",
                    "retired",
                )
            )
        return False

    @staticmethod
    def is_model_tier_restricted(provider_id: str, model_id: str) -> bool:
        """Check if model requires specialized account tier (e.g. Enterprise)."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if info:
            return info.account_availability == "tier_restricted"
        return False

    @staticmethod
    def is_model_eligible(provider_id: str, model_id: str) -> bool:
        """Check if a model satisfies public eligibility policy for defaults and automatic fallback."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if not info:
            return False
        if info.lifecycle_status not in (
            LifecycleStatus.ACTIVE,
            LifecycleStatus.PREVIEW,
            "active",
            "preview",
        ):
            return False
        if info.is_deprecated or not info.provider_availability:
            return False
        return info.account_availability == "public"

    @staticmethod
    def get_replacement_model(provider_id: str, model_id: str) -> str:
        """Return recommended replacement model if target model is retired/deprecated."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if info and info.replacement_model_id:
            return info.replacement_model_id
        if ModelCatalog.is_model_deprecated(provider_id, model_id):
            return ModelCatalog.get_default_model(provider_id)
        return model_id

    @staticmethod
    def get_model_status_warning(provider_id: str, model_id: str) -> str | None:
        """Return human-readable warning if model is retired, deprecated, or tier-restricted."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if not info:
            return None
        rep = ModelCatalog.get_replacement_model(provider_id, model_id)
        if ModelCatalog.is_model_retired(provider_id, model_id):
            return (
                f"Selected model '{model_id}' is officially RETIRED by {provider_id}. "
                f"Recommended replacement: '{rep}'."
            )
        if ModelCatalog.is_model_deprecated(provider_id, model_id):
            return f"Selected model '{model_id}' is DEPRECATED. Recommended replacement: '{rep}'."
        if info.account_availability == "tier_restricted":
            return (
                f"Selected model '{model_id}' is tier-restricted (Enterprise only). "
                f"Standard/free tier alternative: '{rep}'."
            )
        return None

    @staticmethod
    def get_capabilities(provider_id: str, model_id: str) -> ModelCapabilities:
        """Retrieve capabilities for a model, defaulting to conservative baseline if uncataloged."""
        info = ModelCatalog.get_model_info(provider_id, model_id)
        if info:
            return info.capabilities
        # Conservative baseline for uncataloged/custom models
        return ModelCapabilities(
            streaming_supported=True,
            structured_output_supported=False,
            tool_calling_supported=False,
            vision_supported=False,
            context_window=32768,
            maximum_output_tokens=4096,
        )

    @staticmethod
    def register_custom_model(info: ModelInfo, overwrite: bool = False) -> bool:
        """Dynamically add or update a model in the catalog without unexpected overwriting."""
        pid = info.provider_id.lower().strip().replace("google-", "")
        if pid not in _CATALOG:
            _CATALOG[pid] = []
        for i, existing in enumerate(_CATALOG[pid]):
            if existing.model_id == info.model_id:
                if overwrite:
                    _CATALOG[pid][i] = info
                    return True
                return False
        _CATALOG[pid].append(info)
        return True

    @staticmethod
    def refresh_from_discovered(provider_id: str, model_ids: list[str]) -> None:
        """Merge dynamically discovered model IDs into provider's catalog without reactivating retired models."""
        pid = provider_id.lower().strip().replace("google-", "")
        existing_models = {
            m.model_id: m for m in ModelCatalog.list_models(pid, include_deprecated=True)
        }
        for mid in model_ids:
            if mid in existing_models:
                existing = existing_models[mid]
                if existing.is_deprecated or existing.lifecycle_status in (
                    LifecycleStatus.RETIRED,
                    LifecycleStatus.DEPRECATED,
                    "retired",
                    "deprecated",
                ):
                    # Never reactivate retired or deprecated models
                    continue
            else:
                ModelCatalog.register_custom_model(
                    ModelInfo(
                        provider_id=pid,
                        model_id=mid,
                        display_name=f"{pid.capitalize()}: {mid}",
                        capabilities=ModelCapabilities(),
                        lifecycle_status=LifecycleStatus.ACTIVE,
                        verified_at="discovered",
                        verification_date="discovered",
                    )
                )
