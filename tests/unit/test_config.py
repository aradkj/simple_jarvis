"""Unit tests for configuration management and secret security."""

import os
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from config import Settings, get_settings, reload_settings


def test_default_configuration() -> None:
    """Verify default configuration has expected production-safe values."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        settings = Settings(_env_file=None)
        assert settings.app_name == "JARVIS"
        assert settings.app_env in ("development", "production", "testing")
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        assert settings.is_gemini_configured() is False


def test_environment_override() -> None:
    """Verify environment variables override default settings correctly."""
    env_vars = {
        "APP_NAME": "JARVIS-Custom",
        "APP_ENV": "production",
        "LOG_LEVEL": "WARNING",
        "DEBUG": "false",
        "APP_LANGUAGE": "fa",
        "GEMINI_API_KEY": "AIzaSyTestSecret1234567890ABCDEF",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        settings = Settings(_env_file=None)
        assert settings.app_name == "JARVIS-Custom"
        assert settings.app_env == "production"
        assert settings.log_level == "WARNING"
        assert settings.debug is False
        assert settings.app_language == "fa"
        assert settings.is_gemini_configured() is True
        assert settings.gemini_api_key is not None
        assert settings.gemini_api_key.get_secret_value() == "AIzaSyTestSecret1234567890ABCDEF"


def test_secret_str_redaction() -> None:
    """Verify raw secrets are not revealed in string representation or repr."""
    secret = "AIzaSySensitiveSecretKey999"
    settings = Settings(_env_file=None, gemini_api_key=SecretStr(secret))

    # The raw secret string must NEVER be directly in str(settings) or repr(settings)
    assert secret not in str(settings)
    assert secret not in repr(settings)
    assert "**********" in repr(settings.gemini_api_key)


def test_invalid_app_env() -> None:
    """Verify invalid environment specification raises validation error."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="invalid_environment")  # type: ignore[arg-type]


def test_invalid_language() -> None:
    """Verify unsupported languages raise validation error."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_language="unsupported_lang")  # type: ignore[arg-type]


def test_singleton_and_reload() -> None:
    """Verify get_settings returns singleton and reload_settings refreshes cache."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2

    s3 = reload_settings()
    assert s3 is not None
