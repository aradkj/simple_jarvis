"""Unit tests for Gemini Automatic Strongest Model Selection and Fast Failover."""

import time
from unittest.mock import MagicMock

import pytest
from google.genai import errors
from pydantic import SecretStr

from ai.base import ConnectionErrorType
from ai.manager import ProviderManager
from ai.providers.gemini import GeminiProvider
from config import Settings


@pytest.fixture(autouse=True)
def clean_gemini_cooldowns():
    """Ensure Gemini cooldowns are clean before and after each test."""
    GeminiProvider.reset_model_cooldowns()
    yield
    GeminiProvider.reset_model_cooldowns()


@pytest.fixture
def auto_settings() -> Settings:
    return Settings(
        gemini_api_key=SecretStr("AIzaSyMockTestKey123"),
        gemini_model="gemini-3.5-flash-lite",
        gemini_auto_model_selection=True,
        gemini_temperature=0.7,
        gemini_max_output_tokens=2048,
        gemini_request_timeout=15.0,
        failover_cooldown_seconds=60.0,
    )


class TestGeminiAutoModelSelection:
    """Test automatic strongest model resolution and cooldown management."""

    def test_default_model_picks_strongest_available(self, auto_settings: Settings) -> None:
        """When auto selection is enabled, default_model returns the top tier (gemini-2.5-pro)."""
        provider = GeminiProvider(settings=auto_settings)
        assert provider.default_model == "gemini-2.5-pro"

    def test_cooldown_skips_overloaded_model_to_next_tier(self, auto_settings: Settings) -> None:
        """Marking top model in cooldown immediately promotes the next strongest tier."""
        provider = GeminiProvider(settings=auto_settings)
        assert provider.default_model == "gemini-2.5-pro"

        # Mark gemini-2.5-pro in cooldown
        provider.mark_model_cooldown("gemini-2.5-pro", duration_seconds=60.0)
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is True

        # Now strongest available becomes gemini-3.8-flash
        assert provider.default_model == "gemini-3.8-flash"

        # Mark gemini-3.8-flash in cooldown as well
        provider.mark_model_cooldown("gemini-3.8-flash", duration_seconds=60.0)
        assert provider.default_model == "gemini-3.7-flash"

    def test_cooldown_expiry_restores_strongest_model(self, auto_settings: Settings) -> None:
        """Once cooldown expires, the strongest model is automatically restored."""
        provider = GeminiProvider(settings=auto_settings)
        # 0.1 second cooldown
        provider.mark_model_cooldown("gemini-2.5-pro", duration_seconds=0.1)
        assert provider.default_model == "gemini-3.8-flash"

        time.sleep(0.15)
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is False
        assert provider.default_model == "gemini-2.5-pro"

    def test_failover_sequence_prioritizes_hierarchy(self, auto_settings: Settings) -> None:
        """Failover sequence follows strength hierarchy, omitting cooled-down models from top."""
        provider = GeminiProvider(settings=auto_settings)
        seq = provider.get_model_failover_sequence()
        assert seq[0] == "gemini-2.5-pro"
        assert seq[1] == "gemini-3.8-flash"

        provider.mark_model_cooldown("gemini-2.5-pro", 60.0)
        seq_cooled = provider.get_model_failover_sequence()
        assert seq_cooled[0] == "gemini-3.8-flash"


class TestGeminiFastFailoverExecution:
    """Test runtime zero-delay switching when models encounter errors."""

    def test_generate_text_fast_failover_on_503_high_demand(self, auto_settings: Settings) -> None:
        """When 2.5-pro returns 503 high demand, failover to 3.8-flash immediately succeeds."""
        mock_client = MagicMock()

        def side_effect(model, contents, config):
            if model == "gemini-2.5-pro":
                raise errors.ServerError(
                    code=503,
                    response_json={
                        "error": {
                            "code": 503,
                            "message": "This model is currently experiencing high demand.",
                            "status": "UNAVAILABLE",
                        }
                    },
                )
            elif model == "gemini-3.8-flash":
                resp = MagicMock()
                resp.text = "Success from Gemini 3.8 Flash."
                cand = MagicMock()
                cand.finish_reason = "STOP"
                resp.candidates = [cand]
                return resp
            raise ValueError(f"Unexpected model: {model}")

        mock_client.models.generate_content.side_effect = side_effect

        provider = GeminiProvider(settings=auto_settings, client=mock_client)
        t0 = time.perf_counter()
        response = provider.generate_text("Hello JARVIS")
        elapsed = time.perf_counter() - t0

        assert response.text == "Success from Gemini 3.8 Flash."
        assert response.model == "gemini-3.8-flash"
        assert response.metadata.get("gemini_auto_failover") is True
        assert response.metadata.get("original_model") == "gemini-2.5-pro"
        assert response.metadata.get("actual_model") == "gemini-3.8-flash"
        # Zero-delay failover without sleeping
        assert elapsed < 1.0

        # gemini-2.5-pro must now be in cooldown
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is True

    def test_generate_text_fast_failover_on_404_discontinued(self, auto_settings: Settings) -> None:
        """When a model returns 404 (discontinued or not found), system fast-failovers."""
        mock_client = MagicMock()

        def side_effect(model, contents, config):
            if model == "gemini-2.5-pro":
                raise errors.ClientError(
                    code=404,
                    response_json={"error": {"code": 404, "message": "Model not found."}},
                )
            resp = MagicMock()
            resp.text = "Success from alternative model."
            cand = MagicMock()
            cand.finish_reason = "STOP"
            resp.candidates = [cand]
            return resp

        mock_client.models.generate_content.side_effect = side_effect

        provider = GeminiProvider(settings=auto_settings, client=mock_client)
        response = provider.generate_text("Test query")
        assert response.text == "Success from alternative model."
        assert response.model == "gemini-3.8-flash"
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is True

    def test_generate_text_fast_failover_on_429_quota(self, auto_settings: Settings) -> None:
        """When a model returns 429 (Resource Exhausted / Quota), system fast-failovers."""
        mock_client = MagicMock()

        def side_effect(model, contents, config):
            if model == "gemini-2.5-pro":
                raise errors.ClientError(
                    code=429,
                    response_json={"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}},
                )
            resp = MagicMock()
            resp.text = "Quota ok on next tier."
            cand = MagicMock()
            cand.finish_reason = "STOP"
            resp.candidates = [cand]
            return resp

        mock_client.models.generate_content.side_effect = side_effect

        provider = GeminiProvider(settings=auto_settings, client=mock_client)
        response = provider.generate_text("Test query")
        assert response.text == "Quota ok on next tier."
        assert response.model == "gemini-3.8-flash"
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is True

    def test_stream_text_fast_failover_on_initiation_error(self, auto_settings: Settings) -> None:
        """Streaming initiates fast failover if the first model fails on handshake/stream creation."""
        mock_client = MagicMock()

        def side_effect(model, contents, config):
            if model == "gemini-2.5-pro":
                raise errors.ServerError(
                    code=503,
                    response_json={"error": {"code": 503, "message": "High demand"}},
                )
            chunk1 = MagicMock()
            chunk1.text = "Hello "
            chunk2 = MagicMock()
            chunk2.text = "World"
            return iter([chunk1, chunk2])

        mock_client.models.generate_content_stream.side_effect = side_effect

        provider = GeminiProvider(settings=auto_settings, client=mock_client)
        chunks = list(provider.stream_text("Streaming prompt"))
        assert "".join(chunks) == "Hello World"
        assert provider.is_model_in_cooldown("gemini-2.5-pro") is True

    def test_connection_test_fast_failover(self, auto_settings: Settings) -> None:
        """test_connection reports success with failover note when primary model is 503."""
        mock_client = MagicMock()

        def side_effect(model, contents, config):
            if model == "gemini-2.5-pro":
                raise errors.ServerError(
                    code=503,
                    response_json={"error": {"code": 503, "message": "Overloaded"}},
                )
            resp = MagicMock()
            resp.text = "pong"
            return resp

        mock_client.models.generate_content.side_effect = side_effect

        provider = GeminiProvider(settings=auto_settings, client=mock_client)
        result = provider.test_connection()

        assert result.is_success is True
        assert result.error_type == ConnectionErrorType.SUCCESS
        assert "gemini-3.8-flash" in result.message
        assert "auto failover" in result.message.lower()


class TestProviderManagerGeminiIntegration:
    """Test ProviderManager alignment with Gemini strength tiers and bidirectional cooldowns."""

    def test_manager_intra_candidates_follow_strength_order(self, auto_settings: Settings) -> None:
        """ProviderManager._get_intra_provider_candidates returns Gemini models in strength order."""
        manager = ProviderManager(settings=auto_settings)
        candidates = manager._get_intra_provider_candidates("gemini", "gemini-2.5-pro")
        assert candidates[0] == "gemini-3.8-flash"
        assert "gemini-3.5-flash-lite" in candidates

    def test_manager_cooldown_tracking(self, auto_settings: Settings) -> None:
        """ProviderManager properly manages and clears model cooldowns."""
        manager = ProviderManager(settings=auto_settings)

        # Mark in manager
        manager.mark_model_cooldown("gemini", "gemini-3.8-flash", duration_seconds=60.0)
        assert manager.is_model_in_cooldown("gemini", "gemini-3.8-flash") is True

        # Clear via manager
        manager.reset_cooldowns()
        assert manager.is_model_in_cooldown("gemini", "gemini-3.8-flash") is False
