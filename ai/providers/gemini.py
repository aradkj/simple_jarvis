"""Google Gemini AI Provider implementation using the official google-genai SDK."""

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from google import genai
from google.genai import errors, types

from ai.base import (
    AIProviderError,
    AIResponse,
    AuthenticationError,
    BaseAIProvider,
    ConnectionErrorType,
    ConnectionTestResult,
    ModelInfo,
    ModelNotFoundError,
    NetworkError,
    ProviderCancelledError,
    ProviderStatus,
    RateLimitError,
    ServiceUnavailableError,
)
from ai.base import (
    PermissionError as NormalizedPermissionError,
)
from ai.base import (
    TimeoutError as NormalizedTimeoutError,
)
from ai.catalog import ModelCatalog
from config import Settings, get_settings
from core.execution_context import CancellationToken
from infrastructure.logging import get_logger
from memory.base import ConversationMessage, MessageRole, MessageStatus

logger = get_logger("ai.gemini")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are JARVIS, an intelligent, polite, concise, and highly capable personal AI "
    "desktop assistant for Windows 11. You provide clear, accurate responses and seamlessly "
    "communicate in both English and Persian (فارسی). When answering in Persian, use natural, "
    "respectful phrasing."
)


class GeminiProviderError(AIProviderError):
    """Base exception for Gemini provider errors."""


class GeminiNotConfiguredError(GeminiProviderError, AuthenticationError):
    """Raised when an operation is attempted without a valid API key configured."""


class GeminiAuthenticationError(GeminiProviderError, AuthenticationError):
    """Raised on invalid or unauthorized API key (400/401)."""


class GeminiPermissionError(GeminiProviderError, NormalizedPermissionError):
    """Raised when access is forbidden or permissions are denied (403)."""


class GeminiModelNotFoundError(GeminiProviderError, ModelNotFoundError):
    """Raised when the requested model identifier is unavailable or invalid (404)."""


class GeminiQuotaExceededError(GeminiProviderError, RateLimitError):
    """Raised when rate limits or quotas are exhausted (429)."""


class GeminiNetworkError(GeminiProviderError, NetworkError):
    """Raised on network transport or connection failures."""


class GeminiTimeoutError(GeminiProviderError, NormalizedTimeoutError):
    """Raised when a request exceeds configured timeout limits."""


class GeminiServerError(GeminiProviderError, ServiceUnavailableError):
    """Raised on Google Gemini backend errors (500/503)."""


class GeminiCancelledError(GeminiProviderError, ProviderCancelledError):
    """Raised when a streaming operation is cancelled by the user."""


def _interruptible_sleep(duration_sec: float, token: CancellationToken | None = None) -> None:
    """Sleep in short intervals while checking for user cancellation."""
    start = time.perf_counter()
    while time.perf_counter() - start < duration_sec:
        if token and token.is_cancelled():
            raise GeminiCancelledError("Operation cancelled during retry backoff.")
        remaining = duration_sec - (time.perf_counter() - start)
        time.sleep(min(0.05, max(0.0, remaining)))


class GeminiProvider(BaseAIProvider):
    """Google Gemini AI Provider integrating the official google-genai SDK."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client: genai.Client | None = client

    @property
    def provider_name(self) -> str:
        return "google-gemini"

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self.settings.gemini_model

    def list_supported_models(self) -> list[ModelInfo]:
        """Return list of supported Gemini models with declared capabilities."""
        return ModelCatalog.list_models("gemini")

    def _get_client(self) -> genai.Client:
        """Obtain or initialize the official google-genai client."""
        if self._client is not None:
            return self._client

        if not self.is_ready():
            raise GeminiNotConfiguredError(
                "Gemini API key is not configured. Please configure GEMINI_API_KEY in settings or .env."
            )

        from infrastructure.network import configure_system_proxy

        configure_system_proxy()

        assert self.settings.gemini_api_key is not None
        raw_key = self.settings.gemini_api_key.get_secret_value()
        # Application safety policy: Enforce an application safety floor of 10,000ms (10s)
        # to ensure slow network connections or streaming handshakes do not abort prematurely.
        # Note: google-genai SDK HttpOptions timeout is expressed in milliseconds (int).
        timeout_ms = max(10000, int(self.settings.gemini_request_timeout * 1000))
        http_options = types.HttpOptions(timeout=timeout_ms)
        self._client = genai.Client(api_key=raw_key, http_options=http_options)
        return self._client

    def is_ready(self) -> bool:
        """Check if Gemini API key is configured."""
        return self.settings.is_gemini_configured()

    def get_status(self) -> ProviderStatus:
        """Return the current provider configuration status."""
        if self.is_ready():
            return ProviderStatus.READY
        return ProviderStatus.NOT_CONFIGURED

    def test_connection(self) -> ConnectionTestResult:
        """Perform a minimal live ping request to verify model access and credentials."""
        if not self.is_ready():
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.MISSING_API_KEY,
                message="Gemini API key is not configured. Set GEMINI_API_KEY in .env.",
            )

        start_time = time.perf_counter()
        try:
            client = self._get_client()
            # Enforce application safety deadline minimum of 10s (10,000ms)
            timeout_ms = max(10000, int(self.settings.gemini_request_timeout * 1000))
            cfg = types.GenerateContentConfig(
                max_output_tokens=5,
                temperature=0.0,
                http_options=types.HttpOptions(timeout=timeout_ms),
            )
            # Lightweight verification ping
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents="ping",
                config=cfg,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if response and (response.text is not None or response.candidates):
                return ConnectionTestResult(
                    is_success=True,
                    message=f"Connected successfully to {self.settings.gemini_model}.",
                    error_type=ConnectionErrorType.SUCCESS,
                    latency_ms=round(elapsed_ms, 1),
                )
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.UNKNOWN_ERROR,
                message="Received empty response from Gemini endpoint.",
                latency_ms=round(elapsed_ms, 1),
            )

        except errors.ClientError as err:
            err_str = str(err)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            # Distinguish 403 Permission / Forbidden vs 400/401 Invalid Key
            if err.code == 403 or "permission" in err_str.lower():
                return ConnectionTestResult(
                    is_success=False,
                    error_type=ConnectionErrorType.AUTH_FAILURE,
                    message="Access forbidden (403). Ensure Generative Language API is enabled on your project.",
                    latency_ms=round(elapsed_ms, 1),
                )
            if "API_KEY_INVALID" in err_str or err.code in (400, 401):
                return ConnectionTestResult(
                    is_success=False,
                    error_type=ConnectionErrorType.INVALID_API_KEY,
                    message="Invalid or unauthorized Gemini API key. Verify your credentials.",
                    latency_ms=round(elapsed_ms, 1),
                )
            if err.code == 404 or "not found" in err_str.lower():
                return ConnectionTestResult(
                    is_success=False,
                    error_type=ConnectionErrorType.MODEL_NOT_FOUND,
                    message=f"Model '{self.settings.gemini_model}' was not found or is discontinued. Please switch to 'gemini-3.5-flash-lite' in Settings.",
                    latency_ms=round(elapsed_ms, 1),
                )
            if err.code == 429 or "RESOURCE_EXHAUSTED" in err_str:
                return ConnectionTestResult(
                    is_success=False,
                    error_type=ConnectionErrorType.QUOTA_EXCEEDED,
                    message="Gemini API rate limit or quota exceeded. Please try again later.",
                    latency_ms=round(elapsed_ms, 1),
                )
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.UNKNOWN_ERROR,
                message=f"Client request error: {err_str}",
                latency_ms=round(elapsed_ms, 1),
            )

        except errors.ServerError as err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            msg = str(err)
            if err.code == 503 or "demand" in msg.lower() or "unavailable" in msg.lower():
                server_msg = (
                    f"Model '{self.settings.gemini_model}' is temporarily overloaded (503 high demand). "
                    f"Please switch to 'gemini-3.5-flash-lite' in Settings or try again shortly."
                )
            else:
                server_msg = f"Google Gemini server-side error (code {err.code}). Google servers may be temporarily experiencing issues."
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.SERVER_ERROR,
                message=server_msg,
                latency_ms=round(elapsed_ms, 1),
            )

        except (TimeoutError, ConnectionResetError) as err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.TIMEOUT,
                message=f"Connection timed out: {err}",
                latency_ms=round(elapsed_ms, 1),
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            exc_name = exc.__class__.__name__
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.NETWORK_ERROR,
                message=f"Network connection error ({exc_name}). Check your internet connection or proxy/VPN.",
                latency_ms=round(elapsed_ms, 1),
            )

    def _build_contents(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
    ) -> list[types.Content]:
        """Convert prior conversation history and current prompt into SDK Content objects."""
        contents: list[types.Content] = []

        if history:
            # Bound history to configured limit
            bounded_history = history[-self.settings.conversation_history_limit :]
            for msg in bounded_history:
                # Omit failed, cancelled, or empty messages from multi-turn context
                if msg.status != MessageStatus.COMPLETED:
                    continue
                if not msg.content or not msg.content.strip():
                    continue

                role_str = "user" if msg.role == MessageRole.USER else "model"
                contents.append(
                    types.Content(
                        role=role_str,
                        parts=[types.Part.from_text(text=msg.content)],
                    )
                )

        # Append current user prompt
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )
        )
        return contents

    def _build_config(self) -> types.GenerateContentConfig:
        """Create GenerateContentConfig with model parameters, system instruction, and timeout."""
        timeout_ms = max(10000, int(self.settings.gemini_request_timeout * 1000))
        return types.GenerateContentConfig(
            system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
            temperature=self.settings.gemini_temperature,
            max_output_tokens=self.settings.gemini_max_output_tokens,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )

    def _map_exception(self, exc: Exception) -> GeminiProviderError:
        """Translate raw SDK or network exceptions into typed GeminiProviderErrors."""
        if isinstance(exc, errors.ClientError):
            msg = str(exc)
            if exc.code == 403 or "permission" in msg.lower():
                return GeminiPermissionError(
                    "Access forbidden (403): Permission denied or API disabled."
                )
            if "API_KEY_INVALID" in msg or exc.code in (400, 401):
                return GeminiAuthenticationError(
                    "Gemini API key is invalid or lacks permission for this action."
                )
            if exc.code == 404 or "not found" in msg.lower():
                return GeminiModelNotFoundError(
                    f"Model '{self.settings.gemini_model}' was not found or is unavailable."
                )
            if exc.code == 429 or "RESOURCE_EXHAUSTED" in msg:
                return GeminiQuotaExceededError("Gemini API quota or rate limit exceeded.")
            return GeminiProviderError(f"Gemini client request error (code {exc.code})")

        if isinstance(exc, errors.ServerError):
            msg = str(exc)
            if exc.code == 503 or "demand" in msg.lower() or "unavailable" in msg.lower():
                return GeminiServerError(
                    f"Google Gemini model '{self.settings.gemini_model}' is currently overloaded (code 503: high demand). "
                    "Please switch model to 'gemini-3.5-flash' in Settings or try again shortly."
                )
            return GeminiServerError(f"Google Gemini server error (code {exc.code}).")

        if isinstance(exc, TimeoutError):
            return GeminiTimeoutError("Request to Gemini API timed out.")

        if isinstance(exc, (ConnectionError, OSError)):
            return GeminiNetworkError(
                f"Network error communicating with Gemini: {exc.__class__.__name__}"
            )

        return GeminiProviderError(f"Gemini API operation failed: {exc}")

    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate a complete text response from Gemini model."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise GeminiCancelledError("Operation cancelled before invocation.")

        model = kwargs.get("model") or self.settings.gemini_model
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Google. Please select an active model.",
                model,
            )

        client = self._get_client()
        contents = self._build_contents(prompt, history)
        config = self._build_config()

        # Bounded retry for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            if cancellation_token and cancellation_token.is_cancelled():
                raise GeminiCancelledError("Operation cancelled before retry.")

            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                generated_text = response.text or ""
                finish_reason = None
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = str(response.candidates[0].finish_reason)

                return AIResponse(
                    text=generated_text,
                    raw_response=response,
                    finish_reason=finish_reason,
                    model=model,
                    provider_id=self.provider_id,
                )
            except Exception as exc:
                typed_err = self._map_exception(exc)
                if (
                    isinstance(typed_err, (GeminiServerError, GeminiNetworkError))
                    and attempt < max_retries
                ):
                    backoff = (attempt + 1) * 1.0
                    logger.warning(f"Transient error ({typed_err}); retrying in {backoff}s...")
                    _interruptible_sleep(backoff, cancellation_token)
                    continue
                raise typed_err from exc

        raise GeminiProviderError("Failed to generate text after retries.")

    def stream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream text tokens as they are produced by Gemini."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise GeminiCancelledError("Operation cancelled before streaming started.")

        model = kwargs.get("model") or self.settings.gemini_model
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Google. Please select an active model.",
                model,
            )

        client = self._get_client()
        contents = self._build_contents(prompt, history)
        config = self._build_config()

        def _abort_connection() -> None:
            try:
                if self._client and hasattr(self._client, "_api_client"):
                    self._client._api_client.close()
            except Exception as e:
                logger.debug(f"Error aborting Gemini socket on cancel: {e}")

        if cancellation_token:
            cancellation_token.register_callback(_abort_connection)

        try:
            stream = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )

            for chunk in stream:
                if cancellation_token and cancellation_token.is_cancelled():
                    logger.info("Generation streaming cancelled by user token.")
                    raise GeminiCancelledError("Generation cancelled by user.")

                chunk_text = chunk.text
                if chunk_text:
                    yield chunk_text

        except GeminiCancelledError:
            raise
        except Exception as exc:
            if cancellation_token and cancellation_token.is_cancelled():
                logger.info("Stream interrupted due to user cancellation.")
                raise GeminiCancelledError("Generation cancelled by user.") from exc
            typed_err = self._map_exception(exc)
            logger.error(f"Error during streaming generation: {typed_err}")
            raise typed_err from exc

    async def astream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Asynchronously stream text tokens using Gemini model."""
        for token in self.stream_text(
            prompt=prompt,
            history=history,
            cancellation_token=cancellation_token,
            **kwargs,
        ):
            yield token

    def close(self) -> None:
        """Release client references."""
        self._client = None
