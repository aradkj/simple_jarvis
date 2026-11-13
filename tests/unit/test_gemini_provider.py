"""Unit tests for GeminiProvider with mocked google-genai SDK client."""

from unittest.mock import MagicMock

import pytest
from google.genai import errors
from pydantic import SecretStr

from ai.base import ConnectionErrorType
from ai.providers.gemini import (
    GeminiAuthenticationError,
    GeminiCancelledError,
    GeminiNotConfiguredError,
    GeminiProvider,
    GeminiServerError,
)
from config import Settings
from core.execution_context import CancellationToken


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        gemini_api_key=SecretStr("AIzaSyMockValidTestKey12345"),
        gemini_model="gemini-3.8-flash",
        gemini_temperature=0.7,
        gemini_max_output_tokens=2048,
        gemini_request_timeout=15.0,
        conversation_history_limit=10,
    )


def test_gemini_provider_unconfigured() -> None:
    """Verify GeminiProvider raises GeminiNotConfiguredError when key is absent."""
    unconfigured_settings = Settings(gemini_api_key=None)
    provider = GeminiProvider(settings=unconfigured_settings)

    assert provider.is_ready() is False
    with pytest.raises(GeminiNotConfiguredError):
        provider._get_client()

    with pytest.raises(GeminiNotConfiguredError):
        provider.generate_text("Hello")


def test_gemini_provider_connection_test_missing_key() -> None:
    """Verify connection test reports missing API key."""
    provider = GeminiProvider(settings=Settings(gemini_api_key=None))
    result = provider.test_connection()
    assert result.is_success is False
    assert result.error_type == ConnectionErrorType.MISSING_API_KEY


def test_gemini_provider_connection_test_success(mock_settings: Settings) -> None:
    """Verify connection test succeeds with mocked SDK response."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "pong"
    mock_client.models.generate_content.return_value = mock_resp

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    result = provider.test_connection()

    assert result.is_success is True
    assert result.error_type == ConnectionErrorType.SUCCESS
    assert "gemini-3.8-flash" in result.message
    assert result.latency_ms is not None


def test_gemini_provider_connection_test_invalid_key(mock_settings: Settings) -> None:
    """Verify connection test catches invalid key errors (400/401/403)."""
    mock_client = MagicMock()
    # Simulate API_KEY_INVALID error from SDK
    client_err = errors.ClientError(
        code=400,
        response_json={"error": {"message": "API_KEY_INVALID: API key not valid."}},
    )
    mock_client.models.generate_content.side_effect = client_err

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    result = provider.test_connection()

    assert result.is_success is False
    assert result.error_type == ConnectionErrorType.INVALID_API_KEY
    assert "invalid or unauthorized" in result.message.lower()


def test_gemini_provider_connection_test_model_not_found(mock_settings: Settings) -> None:
    """Verify connection test catches model 404."""
    mock_client = MagicMock()
    client_err = errors.ClientError(
        code=404,
        response_json={"error": {"message": "models/gemini-unknown is not found"}},
    )
    mock_client.models.generate_content.side_effect = client_err

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    result = provider.test_connection()

    assert result.is_success is False
    assert result.error_type == ConnectionErrorType.MODEL_NOT_FOUND


def test_gemini_provider_connection_test_quota_exceeded(mock_settings: Settings) -> None:
    """Verify connection test catches rate limit 429."""
    mock_client = MagicMock()
    client_err = errors.ClientError(
        code=429,
        response_json={"error": {"message": "RESOURCE_EXHAUSTED: Rate limit exceeded"}},
    )
    mock_client.models.generate_content.side_effect = client_err

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    result = provider.test_connection()

    assert result.is_success is False
    assert result.error_type == ConnectionErrorType.QUOTA_EXCEEDED


def test_gemini_provider_generate_text_success(mock_settings: Settings) -> None:
    """Verify text generation and response normalization."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Hello! I am JARVIS."
    candidate = MagicMock()
    candidate.finish_reason = "STOP"
    mock_resp.candidates = [candidate]
    mock_client.models.generate_content.return_value = mock_resp

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    response = provider.generate_text(prompt="Who are you?")

    assert response.text == "Hello! I am JARVIS."
    assert response.finish_reason == "STOP"
    assert response.model == "gemini-3.8-flash"


def test_gemini_provider_stream_text_success(mock_settings: Settings) -> None:
    """Verify text streaming yields chunks in order."""
    mock_client = MagicMock()
    chunk1 = MagicMock()
    chunk1.text = "Hello "
    chunk2 = MagicMock()
    chunk2.text = "from "
    chunk3 = MagicMock()
    chunk3.text = "JARVIS!"

    mock_client.models.generate_content_stream.return_value = [chunk1, chunk2, chunk3]

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    tokens = list(provider.stream_text("Say hello"))

    assert tokens == ["Hello ", "from ", "JARVIS!"]


def test_gemini_provider_stream_cancellation(mock_settings: Settings) -> None:
    """Verify streaming aborts with GeminiCancelledError when token is set."""
    mock_client = MagicMock()
    token = CancellationToken()

    def chunk_generator():
        yield MagicMock(text="Chunk 1 ")
        token.cancel()  # Cancel mid-stream
        yield MagicMock(text="Chunk 2 ")

    mock_client.models.generate_content_stream.return_value = chunk_generator()

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    received: list[str] = []

    with pytest.raises(GeminiCancelledError):
        for chunk in provider.stream_text("Test cancel", cancellation_token=token):
            received.append(chunk)

    assert received == ["Chunk 1 "]


def test_gemini_provider_exception_mapping(mock_settings: Settings) -> None:
    """Verify custom GeminiProvider exception hierarchy."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = errors.ClientError(
        code=400,
        response_json={"error": {"message": "API_KEY_INVALID"}},
    )

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    with pytest.raises(GeminiAuthenticationError):
        provider.generate_text("Fail please")


def test_gemini_provider_503_overloaded_mapping(mock_settings: Settings) -> None:
    """Verify 503 high demand ServerError produces actionable error message."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = errors.ServerError(
        code=503,
        response_json={
            "error": {
                "code": 503,
                "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
                "status": "UNAVAILABLE",
            }
        },
    )

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    with pytest.raises(GeminiServerError) as exc_info:
        provider.generate_text("Hello")

    err_text = str(exc_info.value)
    assert "503" in err_text
    assert "overloaded" in err_text.lower() or "demand" in err_text.lower()
    assert "gemini-3.5-flash" in err_text


def test_gemini_provider_connection_test_503_server_error(mock_settings: Settings) -> None:
    """Verify test_connection provides guidance when model is overloaded with 503."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = errors.ServerError(
        code=503,
        response_json={
            "error": {
                "code": 503,
                "message": "This model is currently experiencing high demand.",
                "status": "UNAVAILABLE",
            }
        },
    )

    provider = GeminiProvider(settings=mock_settings, client=mock_client)
    result = provider.test_connection()

    assert result.is_success is False
    assert result.error_type == ConnectionErrorType.SERVER_ERROR
    assert "503" in result.message
    assert "gemini-3.5-flash" in result.message
