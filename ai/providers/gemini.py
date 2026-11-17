"""Google Gemini AI Provider implementation using the official google-genai SDK."""

import re
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from google import genai
from google.genai import errors, types

from ai.base import (
    AIProviderError,
    AIResponse,
    AudioTranscriptionResult,
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

DEFAULT_GEMINI_STRENGTH_TIERS: list[str] = [
    "gemini-2.5-pro",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]


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

    _model_cooldowns: dict[str, float] = {}

    def __init__(
        self,
        settings: Settings | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client: genai.Client | None = client

    @classmethod
    def mark_model_cooldown(cls, model_id: str, duration_seconds: float = 60.0) -> None:
        """Mark a Gemini model in temporary cooldown due to high demand, rate limits, or errors."""
        norm_model = model_id.lower().strip()
        expires_at = time.time() + duration_seconds
        cls._model_cooldowns[norm_model] = expires_at
        logger.info(
            f"Marked Gemini model '{norm_model}' in cooldown for {duration_seconds:.0f}s (until {expires_at:.1f})"
        )

    @classmethod
    def is_model_in_cooldown(cls, model_id: str) -> bool:
        """Check if a Gemini model is currently in cooldown."""
        norm_model = model_id.lower().strip()
        expires_at = cls._model_cooldowns.get(norm_model, 0.0)
        return time.time() < expires_at

    @classmethod
    def reset_model_cooldowns(cls) -> None:
        """Clear all active model cooldowns."""
        cls._model_cooldowns.clear()
        logger.info("Cleared all Gemini model cooldowns.")

    def get_fallback_hierarchy(self) -> list[str]:
        """Return the prioritized list of Gemini models from strongest to fastest."""
        configured_order = getattr(self.settings, "gemini_model_fallback_order", None)
        if configured_order and isinstance(configured_order, list):
            return list(configured_order)
        return list(DEFAULT_GEMINI_STRENGTH_TIERS)

    def get_strongest_available_model(self, preferred_model: str | None = None) -> str:
        """Return the strongest available Gemini model that is not currently in cooldown."""
        hierarchy = self.get_fallback_hierarchy()

        for cand in hierarchy:
            if not self.is_model_in_cooldown(cand):
                return cand

        if self._model_cooldowns:
            earliest = min(
                hierarchy, key=lambda m: self._model_cooldowns.get(m.lower().strip(), 0.0)
            )
            return earliest

        return preferred_model or self.settings.gemini_model

    def get_model_failover_sequence(self, start_model: str | None = None) -> list[str]:
        """
        Return the ordered sequence of Gemini models to attempt, prioritizing strongest available.
        Models in cooldown are placed at the end or omitted.
        """
        hierarchy = self.get_fallback_hierarchy()
        sequence: list[str] = []

        if start_model and start_model in hierarchy:
            if not self.is_model_in_cooldown(start_model):
                sequence.append(start_model)
            for m in hierarchy:
                if m != start_model and m not in sequence and not self.is_model_in_cooldown(m):
                    sequence.append(m)
        else:
            for m in hierarchy:
                if not self.is_model_in_cooldown(m):
                    sequence.append(m)

        for m in hierarchy:
            if m not in sequence:
                sequence.append(m)

        return sequence

    @property
    def provider_name(self) -> str:
        return "google-gemini"

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        if getattr(self.settings, "gemini_auto_model_selection", False):
            return self.get_strongest_available_model(self.settings.gemini_model)
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
        """Perform a minimal live ping request to verify model access and credentials with auto failover."""
        if not self.is_ready():
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.MISSING_API_KEY,
                message="Gemini API key is not configured. Set GEMINI_API_KEY in .env.",
            )

        start_time = time.perf_counter()
        auto_select = getattr(self.settings, "gemini_auto_model_selection", True)
        models_to_test = (
            self.get_model_failover_sequence() if auto_select else [self.settings.gemini_model]
        )
        primary_model = models_to_test[0] if models_to_test else self.settings.gemini_model

        for idx, test_model in enumerate(models_to_test):
            try:
                client = self._get_client()
                # Enforce application safety deadline minimum of 10s (10,000ms)
                timeout_ms = max(10000, int(self.settings.gemini_request_timeout * 1000))
                cfg = types.GenerateContentConfig(
                    max_output_tokens=5,
                    temperature=0.0,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )
                response = client.models.generate_content(
                    model=test_model,
                    contents="ping",
                    config=cfg,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if response and (response.text is not None or response.candidates):
                    if test_model != primary_model:
                        msg = f"Connected successfully to {test_model} (auto failover from {primary_model})."
                    else:
                        msg = f"Connected successfully to {test_model}."
                    return ConnectionTestResult(
                        is_success=True,
                        message=msg,
                        error_type=ConnectionErrorType.SUCCESS,
                        latency_ms=round(elapsed_ms, 1),
                    )

            except errors.ServerError as err:
                if auto_select and idx < len(models_to_test) - 1:
                    cooldown = getattr(self.settings, "failover_cooldown_seconds", 60.0)
                    self.mark_model_cooldown(test_model, cooldown)
                    continue
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                msg = str(err)
                if err.code == 503 or "demand" in msg.lower() or "unavailable" in msg.lower():
                    server_msg = (
                        f"Model '{test_model}' is temporarily overloaded (503 high demand). "
                        "Please switch to 'gemini-3.5-flash' in Settings or try again shortly."
                    )
                else:
                    server_msg = f"Google Gemini server-side error (code {err.code}): {err}"
                return ConnectionTestResult(
                    is_success=False,
                    error_type=ConnectionErrorType.SERVER_ERROR,
                    message=server_msg,
                    latency_ms=round(elapsed_ms, 1),
                )

            except errors.ClientError as err:
                if auto_select and err.code in (404, 429) and idx < len(models_to_test) - 1:
                    cooldown = getattr(self.settings, "failover_cooldown_seconds", 60.0)
                    self.mark_model_cooldown(test_model, cooldown)
                    continue
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                err_str = str(err)
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
                        message=f"Model '{test_model}' was not found or is discontinued.",
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
                    message=f"Client request error on '{test_model}': {err_str}",
                    latency_ms=round(elapsed_ms, 1),
                )

            except (TimeoutError, ConnectionResetError) as err:
                if auto_select and idx < len(models_to_test) - 1:
                    cooldown = getattr(self.settings, "failover_cooldown_seconds", 60.0)
                    self.mark_model_cooldown(test_model, cooldown)
                    continue
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

        return ConnectionTestResult(
            is_success=False,
            error_type=ConnectionErrorType.SERVER_ERROR,
            message="All tested Gemini models were unavailable.",
            latency_ms=round((time.perf_counter() - start_time) * 1000.0, 1),
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

    def _build_config(self, **kwargs: Any) -> types.GenerateContentConfig:
        """Create GenerateContentConfig with model parameters, system instruction, and timeout."""
        timeout_ms = max(10000, int(self.settings.gemini_request_timeout * 1000))
        sys_inst = kwargs.get("system_instruction") or DEFAULT_SYSTEM_INSTRUCTION
        return types.GenerateContentConfig(
            system_instruction=sys_inst,
            temperature=float(kwargs.get("temperature", self.settings.gemini_temperature)),
            max_output_tokens=int(
                kwargs.get("max_output_tokens", self.settings.gemini_max_output_tokens)
            ),
            http_options=types.HttpOptions(timeout=timeout_ms),
        )

    def _map_exception(self, exc: Exception, model: str | None = None) -> GeminiProviderError:
        """Translate raw SDK or network exceptions into typed GeminiProviderErrors."""
        target_model = model or self.settings.gemini_model
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
                    f"Model '{target_model}' was not found or is unavailable."
                )
            if exc.code == 429 or "RESOURCE_EXHAUSTED" in msg:
                return GeminiQuotaExceededError("Gemini API quota or rate limit exceeded.")
            return GeminiProviderError(
                f"Gemini client request error (code {exc.code}) on '{target_model}'"
            )

        if isinstance(exc, errors.ServerError):
            msg = str(exc)
            if exc.code == 503 or "demand" in msg.lower() or "unavailable" in msg.lower():
                return GeminiServerError(
                    f"Google Gemini model '{target_model}' is currently overloaded (code 503: high demand). "
                    "Please switch model to 'gemini-3.5-flash' in Settings or try again shortly."
                )
            return GeminiServerError(
                f"Google Gemini server error (code {exc.code}) on '{target_model}'."
            )

        if isinstance(exc, TimeoutError):
            return GeminiTimeoutError(f"Request to Gemini API timed out on '{target_model}'.")

        if isinstance(exc, (ConnectionError, OSError)):
            return GeminiNetworkError(
                f"Network error communicating with Gemini ({target_model}): {exc.__class__.__name__}"
            )

        return GeminiProviderError(f"Gemini API operation failed on '{target_model}': {exc}")

    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate a complete text response from Gemini model with automatic strongest model selection and fast failover."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise GeminiCancelledError("Operation cancelled before invocation.")

        client = self._get_client()
        contents = self._build_contents(prompt, history)
        config = self._build_config(**kwargs)

        requested_model = kwargs.get("model")
        auto_select = getattr(self.settings, "gemini_auto_model_selection", True)

        if auto_select:
            failover_candidates = self.get_model_failover_sequence(start_model=requested_model)
        else:
            failover_candidates = [requested_model or self.settings.gemini_model]

        initial_model = (
            failover_candidates[0] if failover_candidates else self.settings.gemini_model
        )
        last_error: Exception | None = None

        for idx, cand_model in enumerate(failover_candidates):
            if cancellation_token and cancellation_token.is_cancelled():
                raise GeminiCancelledError("Operation cancelled before attempt.")

            if ModelCatalog.is_model_retired(self.provider_id, cand_model):
                logger.warning(
                    "Model '%s' is marked RETIRED by Google. Skipping.",
                    cand_model,
                )
                continue

            try:
                logger.debug(f"Attempting Gemini generation with model '{cand_model}'...")
                response = client.models.generate_content(
                    model=cand_model,
                    contents=contents,
                    config=config,
                )
                generated_text = response.text or ""
                finish_reason = None
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = str(response.candidates[0].finish_reason)

                meta = {"model": cand_model}
                if cand_model != initial_model:
                    meta["gemini_auto_failover"] = True
                    meta["original_model"] = initial_model
                    meta["actual_model"] = cand_model
                    logger.info(
                        f"Gemini auto-failover successful: switched from '{initial_model}' to '{cand_model}'"
                    )

                return AIResponse(
                    text=generated_text,
                    raw_response=response,
                    finish_reason=finish_reason,
                    model=cand_model,
                    provider_id=self.provider_id,
                    metadata=meta,
                )

            except Exception as exc:
                last_error = exc
                typed_err = self._map_exception(exc, model=cand_model)

                if cancellation_token and cancellation_token.is_cancelled():
                    raise GeminiCancelledError("Operation cancelled during request.") from exc

                is_failoverable = isinstance(
                    typed_err,
                    (
                        GeminiServerError,
                        GeminiQuotaExceededError,
                        GeminiModelNotFoundError,
                        GeminiTimeoutError,
                        GeminiNetworkError,
                    ),
                )

                if auto_select and is_failoverable and idx < len(failover_candidates) - 1:
                    cooldown_sec = getattr(self.settings, "failover_cooldown_seconds", 60.0)
                    self.mark_model_cooldown(cand_model, cooldown_sec)
                    next_model = failover_candidates[idx + 1]
                    logger.warning(
                        f"Gemini model '{cand_model}' failed ({typed_err}). "
                        f"Fast failover to next strongest model '{next_model}'..."
                    )
                    continue

                if not auto_select:
                    max_retries = 2
                    for attempt in range(1, max_retries + 1):
                        if cancellation_token and cancellation_token.is_cancelled():
                            raise GeminiCancelledError(
                                "Operation cancelled before retry."
                            ) from None
                        if isinstance(typed_err, (GeminiServerError, GeminiNetworkError)):
                            backoff = attempt * 1.0
                            logger.warning(
                                f"Transient error ({typed_err}); retrying in {backoff}s..."
                            )
                            _interruptible_sleep(backoff, cancellation_token)
                            try:
                                resp = client.models.generate_content(
                                    model=cand_model,
                                    contents=contents,
                                    config=config,
                                )
                                return AIResponse(
                                    text=resp.text or "",
                                    raw_response=resp,
                                    model=cand_model,
                                    provider_id=self.provider_id,
                                )
                            except Exception as retry_exc:
                                typed_err = self._map_exception(retry_exc, model=cand_model)
                                last_error = retry_exc
                                continue
                        break

                raise typed_err from exc

        if last_error:
            raise self._map_exception(
                last_error, model=failover_candidates[-1] if failover_candidates else None
            )
        raise GeminiProviderError("Failed to generate text: all Gemini models exhausted.")

    def stream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream text tokens as they are produced by Gemini with fast failover on connection/handshake."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise GeminiCancelledError("Operation cancelled before streaming started.")

        client = self._get_client()
        contents = self._build_contents(prompt, history)
        config = self._build_config(**kwargs)

        def _abort_connection() -> None:
            try:
                if self._client and hasattr(self._client, "_api_client"):
                    self._client._api_client.close()
            except Exception as e:
                logger.debug(f"Error aborting Gemini socket on cancel: {e}")

        if cancellation_token:
            cancellation_token.register_callback(_abort_connection)

        requested_model = kwargs.get("model")
        auto_select = getattr(self.settings, "gemini_auto_model_selection", True)

        if auto_select:
            failover_candidates = self.get_model_failover_sequence(start_model=requested_model)
        else:
            failover_candidates = [requested_model or self.settings.gemini_model]

        for idx, cand_model in enumerate(failover_candidates):
            if cancellation_token and cancellation_token.is_cancelled():
                raise GeminiCancelledError("Operation cancelled before streaming started.")

            if ModelCatalog.is_model_retired(self.provider_id, cand_model):
                continue

            try:
                stream = client.models.generate_content_stream(
                    model=cand_model,
                    contents=contents,
                    config=config,
                )
                stream_iter = iter(stream)
                try:
                    first_chunk = next(stream_iter, None)
                except StopIteration:
                    return

                if first_chunk and first_chunk.text:
                    yield first_chunk.text

                for chunk in stream_iter:
                    if cancellation_token and cancellation_token.is_cancelled():
                        logger.info("Generation streaming cancelled by user token.")
                        raise GeminiCancelledError("Generation cancelled by user.")
                    if chunk.text:
                        yield chunk.text
                return

            except GeminiCancelledError:
                raise
            except Exception as exc:
                if cancellation_token and cancellation_token.is_cancelled():
                    raise GeminiCancelledError("Generation cancelled by user.") from exc

                typed_err = self._map_exception(exc, model=cand_model)
                is_failoverable = isinstance(
                    typed_err,
                    (
                        GeminiServerError,
                        GeminiQuotaExceededError,
                        GeminiModelNotFoundError,
                        GeminiTimeoutError,
                        GeminiNetworkError,
                    ),
                )
                if auto_select and is_failoverable and idx < len(failover_candidates) - 1:
                    cooldown_sec = getattr(self.settings, "failover_cooldown_seconds", 60.0)
                    self.mark_model_cooldown(cand_model, cooldown_sec)
                    next_model = failover_candidates[idx + 1]
                    logger.warning(
                        f"Gemini stream model '{cand_model}' failed to initialize ({typed_err}). "
                        f"Failing over to '{next_model}'..."
                    )
                    continue

                logger.error(f"Error during streaming generation on '{cand_model}': {typed_err}")
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

    def transcribe_audio(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav",
        language: str = "auto",
        prompt: str | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AudioTranscriptionResult:
        """Transcribe audio using Google Gemini multimodal capabilities."""
        if cancellation_token and cancellation_token.is_cancelled():
            return AudioTranscriptionResult(text="", confidence=0.0)

        if not audio_data or len(audio_data) < 320:
            return AudioTranscriptionResult(text="", confidence=0.0)

        client = self._get_client()

        lang_instruction = (
            f"The audio is expected to be in {language}."
            if language in ("fa", "en")
            else "Detect whether the audio is in Persian (fa-IR) or English (en-US)."
        )

        default_prompt = (
            f"You are a high-accuracy Speech-to-Text (STT) engine for JARVIS. {lang_instruction} "
            "Transcribe the spoken audio verbatim in its native script. "
            "Preserve technical terminology (e.g., Python, Windows, CPU, WhatsApp, Email), "
            "digits, dates, names, and phone numbers accurately. "
            "If the audio contains only silence, noise, or clicks, return empty text. "
            "Output ONLY a valid JSON object with these keys: "
            '{"text": "transcription string", "language": "fa" or "en", "confidence": float between 0.0 and 1.0, "is_ambiguous": boolean}'
        )

        instruction = prompt or default_prompt
        part = types.Part.from_bytes(data=audio_data, mime_type=mime_type)
        prompt_part = types.Part.from_text(text=instruction)

        target_model = kwargs.get("model") or self.default_model

        try:
            if cancellation_token and cancellation_token.is_cancelled():
                return AudioTranscriptionResult(text="", confidence=0.0)

            response = client.models.generate_content(
                model=target_model,
                contents=[types.Content(role="user", parts=[part, prompt_part])],
            )
            raw_resp = response.text.strip() if response and response.text else ""
            cleaned_json = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw_resp, flags=re.MULTILINE
            ).strip()

            import json

            parsed = json.loads(cleaned_json)
            return AudioTranscriptionResult(
                text=str(parsed.get("text", "")).strip(),
                language=str(parsed.get("language", language if language != "auto" else "en")),
                confidence=float(parsed.get("confidence", 0.95)),
                is_ambiguous=bool(parsed.get("is_ambiguous", False)),
                raw_response=parsed,
            )
        except json.JSONDecodeError:
            return AudioTranscriptionResult(
                text=raw_resp,
                language=language if language != "auto" else "en",
                confidence=0.85,
                is_ambiguous=False,
                raw_response={"raw": raw_resp},
            )
        except Exception as exc:
            if cancellation_token and cancellation_token.is_cancelled():
                return AudioTranscriptionResult(text="", confidence=0.0)
            typed_err = self._map_exception(exc)
            logger.error(f"Gemini audio transcription error: {typed_err}")
            raise typed_err from exc

    def close(self) -> None:
        """Release client references."""
        self._client = None
