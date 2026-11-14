"""Centralized configuration management for JARVIS."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infrastructure.logging import get_logger, register_sensitive_token
from infrastructure.paths import get_data_dir, get_logs_dir, get_project_root

logger = get_logger("config")

AppEnv = Literal["development", "production", "testing"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
SupportedLanguage = Literal["en", "fa"]

# Supported and Verified Providers and Models
SUPPORTED_PROVIDERS = (
    "gemini",
    "openai",
    "anthropic",
    "deepseek",
    "openrouter",
    "groq",
)

SUPPORTED_GEMINI_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.9-flash-preview",
    "gemini-3-flash-preview",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
)


class Settings(BaseSettings):
    """Application settings with validation and secret handling."""

    model_config = SettingsConfigDict(
        env_file=str(get_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Metadata
    app_name: str = Field(default="JARVIS", description="Application display name")
    app_version: str = Field(default="0.2.1", description="Application semantic version")
    app_env: AppEnv = Field(default="development", description="Execution environment")
    debug: bool = Field(default=False, description="Enable verbose debug mode")
    log_level: LogLevel = Field(default="INFO", description="Minimum logging level")
    app_language: SupportedLanguage = Field(
        default="en", description="Default UI language ('en' for English, 'fa' for Persian)"
    )

    # Multi-Provider Routing & Fallback
    default_provider: str = Field(
        default="gemini", description="Default active AI provider ('gemini', 'openai', etc.)"
    )
    enable_auto_fallback: bool = Field(
        default=True, description="Enable automatic fallback to alternative providers"
    )
    allow_intra_provider_fallback: bool = Field(
        default=True,
        description="Allow automatic fallback between models within the same provider.",
    )
    allow_cross_provider_fallback: bool = Field(
        default=False,
        description="Allow automatic fallback to an alternative provider.",
    )
    allow_cross_provider_prompt_transfer: bool = Field(
        default=False,
        description="Allow transmitting the current prompt to an alternative provider on fallback.",
    )
    allow_cross_provider_history_transfer: bool = Field(
        default=False,
        description="Whether conversation history is sent to alternative fallback providers on automatic fallback.",
    )
    fallback_provider_order: list[str] = Field(
        default_factory=lambda: ["gemini", "groq", "openai", "anthropic", "deepseek", "openrouter"],
        description="Priority order for fallback attempts",
    )
    max_fallback_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of model/provider fallback attempts per request",
    )
    failover_cooldown_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=3600.0,
        description="Cooldown period in seconds for temporarily failed models/providers",
    )

    # Provider Enabled Flags
    gemini_enabled: bool = Field(default=True, description="Enable Google Gemini provider")
    openai_enabled: bool = Field(default=True, description="Enable OpenAI provider")
    anthropic_enabled: bool = Field(default=True, description="Enable Anthropic Claude provider")
    deepseek_enabled: bool = Field(default=True, description="Enable DeepSeek provider")
    openrouter_enabled: bool = Field(default=True, description="Enable OpenRouter provider")
    groq_enabled: bool = Field(default=True, description="Enable Groq provider")

    # Google Gemini API Settings
    gemini_api_key: SecretStr | None = Field(
        default=None, description="Google Gemini API Key (keep secret)"
    )
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite", description="Configured Google Gemini model identifier"
    )
    gemini_temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature for text generation"
    )
    gemini_max_output_tokens: int = Field(
        default=4096, gt=0, le=65536, description="Maximum output tokens per generation request"
    )
    gemini_request_timeout: float = Field(
        default=30.0, gt=0.0, le=300.0, description="Network request timeout in seconds"
    )

    # OpenAI Settings
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI API Key (keep secret)"
    )
    openai_model: str = Field(
        default="gpt-6-luna", description="Configured OpenAI model identifier"
    )
    openai_base_url: str | None = Field(
        default=None, description="Optional custom base URL for OpenAI"
    )

    # Anthropic Claude Settings
    anthropic_api_key: SecretStr | None = Field(
        default=None, description="Anthropic API Key (keep secret)"
    )
    anthropic_model: str = Field(
        default="claude-sonnet-5-5", description="Configured Anthropic Claude model"
    )

    # DeepSeek Settings
    deepseek_api_key: SecretStr | None = Field(
        default=None, description="DeepSeek API Key (keep secret)"
    )
    deepseek_model: str = Field(default="deepseek-flash", description="Configured DeepSeek model")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", description="DeepSeek API base endpoint"
    )

    # OpenRouter Settings
    openrouter_api_key: SecretStr | None = Field(
        default=None, description="OpenRouter API Key (keep secret)"
    )
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-5-5", description="Configured OpenRouter model"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", description="OpenRouter API base endpoint"
    )

    # Groq Settings
    groq_api_key: SecretStr | None = Field(default=None, description="Groq API Key (keep secret)")
    groq_model: str = Field(
        default="openai/gpt-oss-120b", description="Configured Groq model identifier"
    )
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", description="Groq API base endpoint"
    )
    conversation_history_limit: int = Field(
        default=20, ge=1, le=200, description="Maximum previous messages sent as context"
    )

    # Phase 3: Agent Core & Planning Settings
    agent_max_planning_iterations: int = Field(
        default=3, ge=1, le=10, description="Maximum planning and replanning cycles"
    )
    agent_max_execution_steps: int = Field(
        default=10, ge=1, le=50, description="Maximum execution steps allowed per agent task"
    )
    agent_max_step_retries: int = Field(
        default=2, ge=0, le=5, description="Maximum retries for an individual failed step"
    )
    agent_step_timeout: float = Field(
        default=30.0, gt=0.0, le=300.0, description="Maximum seconds allowed per execution step"
    )
    agent_task_timeout: float = Field(
        default=180.0,
        gt=0.0,
        le=1200.0,
        description="Maximum seconds allowed for entire agent task",
    )
    agent_mode: str = Field(
        default="balanced", description="Execution mode: 'plan_first', 'balanced', or 'autonomous'"
    )
    agent_auto_approve_low_risk: bool = Field(
        default=True,
        description="Whether low-risk informational tool proposals are automatically approved",
    )

    # Phase 4 System Intelligence & Secure File Inspection Controls
    system_inspection_enabled: bool = Field(
        default=True, description="Enable real Windows hardware and system metrics inspection"
    )
    file_reading_enabled: bool = Field(
        default=True, description="Enable secure read-only authorized directory and file inspection"
    )
    file_max_size_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=50 * 1024 * 1024,
        description="Maximum file size in bytes (default 2MB)",
    )
    file_max_returned_chars: int = Field(
        default=16000, ge=500, le=200000, description="Maximum characters returned from a file read"
    )
    file_max_directory_entries: int = Field(
        default=100, ge=10, le=1000, description="Maximum entries returned by directory listing"
    )
    file_max_search_depth: int = Field(
        default=3, ge=1, le=10, description="Maximum recursion depth for bounded text search"
    )
    file_max_search_results: int = Field(
        default=25, ge=1, le=200, description="Maximum results returned by text search"
    )
    file_allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".txt",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".csv",
            ".log",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".xml",
            ".sql",
        ],
        description="Allowed file extensions for text reading",
    )
    network_expose_mac_addresses: bool = Field(
        default=False,
        description="Whether MAC addresses are exposed in network metrics (privacy setting)",
    )
    secret_redaction_enabled: bool = Field(
        default=True,
        description="Whether regex-based secret redaction is applied to file reading outputs",
    )

    # Phase 5 Persistent Long-Term Memory Controls
    memory_enabled: bool = Field(
        default=True,
        description="Enable persistent long-term memory retrieval and extraction",
    )
    memory_allow_cloud_transmission: bool = Field(
        default=False,
        description="Whether approved persistent memories may be transmitted to external cloud AI providers (default: False for maximum privacy)",
    )
    memory_max_retrieved_records: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of memory records retrieved for context",
    )
    memory_max_context_chars: int = Field(
        default=2500,
        ge=200,
        le=20000,
        description="Maximum character budget for injected memory context",
    )
    memory_min_relevance_score: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score threshold for memory retrieval",
    )
    memory_auto_extract_candidates: bool = Field(
        default=True,
        description="Enable automatic candidate memory identification for user approval",
    )
    memory_episodic_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        description="Retention duration in days for episodic memories",
    )
    memory_embedding_enabled: bool = Field(
        default=False,
        description="Enable optional embedding provider for semantic search (disabled by default)",
    )

    # Phase 6 Windows Desktop Control & Native System Actions
    windows_control_enabled: bool = Field(
        default=True,
        description="Enable Phase 6 Windows Control subsystem and desktop actions",
    )
    windows_app_launch_enabled: bool = Field(
        default=True,
        description="Enable launching approved desktop applications from catalog/allowlist",
    )
    windows_app_close_enabled: bool = Field(
        default=True,
        description="Enable graceful closing of desktop applications",
    )
    windows_window_control_enabled: bool = Field(
        default=True,
        description="Enable desktop window management (focus, minimize, maximize, restore, close)",
    )
    windows_audio_control_enabled: bool = Field(
        default=True,
        description="Enable native Windows audio controls (read, set volume, mute/unmute)",
    )
    windows_display_control_enabled: bool = Field(
        default=True,
        description="Enable physical display brightness inspection and controls where supported",
    )
    windows_power_control_enabled: bool = Field(
        default=True,
        description="Enable power state inspection and high-impact power controls (lock, sleep, restart, shutdown)",
    )
    windows_app_allowlist: list[str] = Field(
        default_factory=lambda: [
            "notepad",
            "calc",
            "calculator",
            "cmd",
            "explorer",
            "chrome",
            "msedge",
            "edge",
            "firefox",
            "brave",
            "code",
            "vscode",
            "wt",
            "terminal",
            "mspaint",
            "paint",
            "taskmgr",
        ],
        description="Configured allowlist of safe application identifiers that may be resolved and launched",
    )

    # Phase 7 Browser Agent
    browser_enabled: bool = Field(
        default=True,
        description="Enable Phase 7 Browser Agent subsystem for web navigation and interaction",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run browser in headless mode (no visible window)",
    )
    browser_navigation_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Maximum seconds to wait for page navigation to complete",
    )
    browser_max_tabs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of browser tabs allowed simultaneously",
    )
    browser_max_navigation_steps: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum cumulative navigation steps allowed per session",
    )
    browser_max_extracted_chars: int = Field(
        default=16000,
        ge=1000,
        le=100000,
        description="Maximum characters returned from DOM text extraction",
    )
    browser_downloads_enabled: bool = Field(
        default=False,
        description="Whether file downloads are allowed (disabled by default for safety)",
    )
    browser_allow_localhost: bool = Field(
        default=False,
        description="Allow navigation to localhost/loopback addresses (only True in testing)",
    )

    # Phase 8 File System, Terminal & Antigravity Coding Agent
    file_modification_enabled: bool = Field(
        default=True,
        description="Enable controlled file modification (create, edit, copy, move, rename, delete, archive)",
    )
    file_recycle_bin_enabled: bool = Field(
        default=True,
        description="Enable recoverable file deletion through Windows Recycle Bin",
    )
    file_archive_max_entries: int = Field(
        default=1000,
        ge=10,
        le=50000,
        description="Maximum entries allowed inside an inspected or extracted archive",
    )
    file_archive_max_total_size_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1024 * 1024,
        le=1024 * 1024 * 1024,
        description="Maximum total uncompressed bytes allowed during archive extraction (100MB default)",
    )
    file_archive_max_ratio: float = Field(
        default=100.0,
        ge=2.0,
        le=1000.0,
        description="Maximum compression ratio threshold for archive bomb defense",
    )
    terminal_enabled: bool = Field(
        default=True,
        description="Enable Phase 8 Restricted Terminal Agent with fixed command registry",
    )
    terminal_default_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Default timeout in seconds for restricted terminal commands",
    )
    terminal_max_timeout_seconds: float = Field(
        default=300.0,
        ge=10.0,
        le=1800.0,
        description="Maximum allowed timeout override for terminal commands",
    )
    terminal_max_output_chars: int = Field(
        default=50000,
        ge=1000,
        le=500000,
        description="Maximum output characters captured from a terminal command",
    )
    antigravity_enabled: bool = Field(
        default=True,
        description="Enable Phase 8 Antigravity Coding Agent CLI integration",
    )
    antigravity_executable_path: str = Field(
        default="",
        description="Path to installed 'agy' executable (discovered from PATH if empty)",
    )
    antigravity_default_model: str = Field(
        default="gemini-3.8-flash-high",
        description="Default model for Antigravity coding tasks",
    )
    antigravity_timeout_seconds: float = Field(
        default=300.0,
        ge=10.0,
        le=1800.0,
        description="Maximum execution timeout in seconds for an Antigravity task",
    )
    antigravity_max_remediation_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum automatic remediation iterations if verification tests fail",
    )
    antigravity_persistent_session_enabled: bool = Field(
        default=False,
        description="Enable persistent NDJSON streaming session if supported (one-shot is default)",
    )
    antigravity_run_tests_on_verify: bool = Field(
        default=True,
        description="Whether to run tests automatically during verification",
    )
    antigravity_authorized_workspaces: list[str] = Field(
        default_factory=list,
        description="Explicit allowlist of canonical directory paths Antigravity is authorized to modify",
    )

    # Storage and Log Directories
    data_dir: Path = Field(default_factory=get_data_dir, description="Persistent data storage path")
    logs_dir: Path = Field(default_factory=get_logs_dir, description="Log files destination path")

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, v: str) -> str:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("development", "production", "testing"):
                return v_lower
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        if isinstance(v, str):
            v_upper = v.upper().strip()
            if v_upper in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                return v_upper
        return v

    @field_validator("app_language", mode="before")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("en", "fa"):
                return v_lower
        return v

    @field_validator("gemini_model", mode="before")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("gemini_model cannot be empty.")
            return cleaned
        return v

    def register_secrets_for_redaction(self) -> None:
        """Register any configured secrets to ensure they are scrubbed from logs."""
        keys = (
            self.gemini_api_key,
            self.openai_api_key,
            self.anthropic_api_key,
            self.deepseek_api_key,
            self.openrouter_api_key,
            self.groq_api_key,
        )
        for k in keys:
            if k is not None:
                raw_key = k.get_secret_value()
                if raw_key and raw_key.strip():
                    register_sensitive_token(raw_key)

    def is_gemini_configured(self) -> bool:
        """Return True only if a non-empty Gemini API key is provided."""
        return self.is_provider_configured("gemini")

    def is_provider_configured(self, provider_id: str) -> bool:
        """Check whether a specific provider has a configured API key."""
        key = self.get_provider_api_key(provider_id)
        if key is None:
            return False
        return bool(key.get_secret_value().strip())

    def get_provider_api_key(self, provider_id: str) -> SecretStr | None:
        """Return the SecretStr API key for a specified provider identifier."""
        pid = provider_id.lower().strip()
        mapping: dict[str, SecretStr | None] = {
            "gemini": self.gemini_api_key,
            "google-gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "deepseek": self.deepseek_api_key,
            "openrouter": self.openrouter_api_key,
            "groq": self.groq_api_key,
        }
        return mapping.get(pid)

    def is_provider_enabled(self, provider_id: str) -> bool:
        """Check whether a provider is enabled in configuration."""
        pid = provider_id.lower().strip()
        mapping: dict[str, bool] = {
            "gemini": self.gemini_enabled,
            "google-gemini": self.gemini_enabled,
            "openai": self.openai_enabled,
            "anthropic": self.anthropic_enabled,
            "deepseek": self.deepseek_enabled,
            "openrouter": self.openrouter_enabled,
            "groq": self.groq_enabled,
        }
        return mapping.get(pid, True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    settings = Settings()
    settings.register_secrets_for_redaction()
    return settings


def reload_settings() -> Settings:
    """Clear cache and reload settings from environment and .env."""
    get_settings.cache_clear()
    return get_settings()


def save_env_settings(updates: dict[str, str], env_path: Path | None = None) -> None:
    """Atomically update key-value pairs in the .env file while preserving comments and order.

    Never logs or exposes secret values.
    """
    target_path = env_path or (get_project_root() / ".env")
    tmp_path = target_path.with_suffix(".tmp")

    lines: list[str] = []
    found_keys: set[str] = set()

    if target_path.exists():
        with open(target_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        new_val = updates[key]
                        lines.append(f"{key}={new_val}\n")
                        found_keys.add(key)
                        continue
                lines.append(line)

    # Append any new keys that were not present in the existing file
    for key, val in updates.items():
        if key not in found_keys:
            lines.append(f"{key}={val}\n")

    # Atomic write via temp file
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp_path, target_path)
        logger.info(f"Successfully updated configuration in {target_path.name}")
    except Exception as exc:
        logger.error(f"Failed to save .env file: {exc}")
        raise
    finally:
        # Guarantee temporary file cleanup
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # Reload application settings in memory
    reload_settings()
