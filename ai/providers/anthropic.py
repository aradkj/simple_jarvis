"""Anthropic Claude AI provider adapter for JARVIS."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import anthropic
from anthropic import Anthropic

from ai.base import (
    AIResponse,
    AuthenticationError,
    BaseAIProvider,
    ConnectionErrorType,
    ConnectionTestResult,
    InvalidRequestError,
    ModelInfo,
    ModelNotFoundError,
    NetworkError,
    ProviderCancelledError,
    ProviderStatus,
    RateLimitError,
    ServiceUnavailableError,
    ToolCall,
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

logger = get_logger("ai.anthropic")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are JARVIS, an intelligent, polite, concise, and highly capable personal AI "
    "desktop assistant for Windows 11. You provide clear, accurate responses and seamlessly "
    "communicate in both English and Persian (فارسی)."
)


class AnthropicProvider(BaseAIProvider):
    """Anthropic Claude API provider adapter utilizing the official anthropic SDK."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: Anthropic | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client: Anthropic | None = client

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def provider_id(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self.settings.anthropic_model

    def list_supported_models(self) -> list[ModelInfo]:
        return ModelCatalog.list_models("anthropic")

    def _get_client(self) -> Anthropic:
        """Instantiate or return the Anthropic client."""
        if self._client is not None:
            return self._client

        if not self.is_ready():
            raise AuthenticationError(
                "Anthropic API key is not configured.", provider_id=self.provider_id
            )

        assert self.settings.anthropic_api_key is not None
        raw_key = self.settings.anthropic_api_key.get_secret_value()
        timeout = float(self.settings.gemini_request_timeout)

        self._client = Anthropic(
            api_key=raw_key,
            timeout=timeout,
        )
        return self._client

    def is_ready(self) -> bool:
        """Check if provider has configured API key."""
        return self.settings.is_provider_configured("anthropic")

    def get_status(self) -> ProviderStatus:
        if self.is_ready():
            return ProviderStatus.READY
        return ProviderStatus.NOT_CONFIGURED

    def _build_messages(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
    ) -> list[dict[str, str]]:
        """Format prior conversation messages into Anthropic messages payload."""
        messages: list[dict[str, str]] = []

        if history:
            limit = self.settings.conversation_history_limit
            bounded = history[-limit:]
            for msg in bounded:
                if msg.status != MessageStatus.COMPLETED or not msg.content:
                    continue
                role = "user" if msg.role == MessageRole.USER else "assistant"
                # Consolidate consecutive roles to conform with Anthropic alternating role requirement
                if messages and messages[-1]["role"] == role:
                    messages[-1]["content"] += f"\n\n{msg.content}"
                else:
                    messages.append({"role": role, "content": msg.content})

        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += f"\n\n{prompt}"
        else:
            messages.append({"role": "user", "content": prompt})

        return messages

    def _map_exception(self, exc: Exception) -> Exception:
        """Normalize Anthropic SDK exceptions into typed AIProviderError instances."""
        msg = str(exc)
        if isinstance(exc, anthropic.AuthenticationError):
            return AuthenticationError(
                f"Anthropic Authentication Failed: {msg}",
                provider_id=self.provider_id,
                raw_error=exc,
            )
        if isinstance(exc, anthropic.PermissionDeniedError):
            return NormalizedPermissionError(
                f"Anthropic Permission Denied: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.NotFoundError):
            return ModelNotFoundError(
                f"Anthropic Model Not Found: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.RateLimitError):
            return RateLimitError(
                f"Anthropic Rate Limit Exceeded: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.BadRequestError):
            return InvalidRequestError(
                f"Anthropic Bad Request: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.InternalServerError):
            return ServiceUnavailableError(
                f"Anthropic Server Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.APITimeoutError):
            return NormalizedTimeoutError(
                f"Anthropic Request Timed Out: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return NetworkError(
                f"Anthropic Network Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        return exc

    def test_connection(self) -> ConnectionTestResult:
        """Ping Anthropic messages endpoint with minimal token limit."""
        if not self.is_ready():
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.MISSING_API_KEY,
                message="Anthropic API key is not configured.",
            )

        start_time = time.perf_counter()
        try:
            client = self._get_client()
            resp = client.messages.create(
                model=self.settings.anthropic_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            elapsed = (time.perf_counter() - start_time) * 1000.0
            if resp and resp.content:
                return ConnectionTestResult(
                    is_success=True,
                    message=f"Connected successfully to Anthropic ({self.settings.anthropic_model}).",
                    error_type=ConnectionErrorType.SUCCESS,
                    latency_ms=round(elapsed, 1),
                )
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.UNKNOWN_ERROR,
                message="Received empty response from Anthropic endpoint.",
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            mapped = self._map_exception(exc)
            if isinstance(mapped, AuthenticationError):
                err_type = ConnectionErrorType.INVALID_API_KEY
            elif isinstance(mapped, NormalizedPermissionError):
                err_type = ConnectionErrorType.AUTH_FAILURE
            elif isinstance(mapped, ModelNotFoundError):
                err_type = ConnectionErrorType.MODEL_NOT_FOUND
            elif isinstance(mapped, RateLimitError):
                err_type = ConnectionErrorType.QUOTA_EXCEEDED
            elif isinstance(mapped, ServiceUnavailableError):
                err_type = ConnectionErrorType.SERVER_ERROR
            elif isinstance(mapped, NormalizedTimeoutError):
                err_type = ConnectionErrorType.TIMEOUT
            elif isinstance(mapped, NetworkError):
                err_type = ConnectionErrorType.NETWORK_ERROR
            else:
                err_type = ConnectionErrorType.UNKNOWN_ERROR

            return ConnectionTestResult(
                is_success=False,
                error_type=err_type,
                message=str(mapped),
                latency_ms=round(elapsed, 1),
            )

    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate complete text response via Anthropic."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before invocation.", provider_id=self.provider_id
            )

        model = kwargs.get("model") or self.settings.anthropic_model
        if "/" in model or model.startswith("anthropic/"):
            raise ModelNotFoundError(
                f"Invalid Anthropic native model identifier '{model}'. Gateway/OpenRouter route identifiers cannot be used with native Anthropic API.",
                provider_id=self.provider_id,
            )
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Anthropic. Please select an active model.",
                model,
            )

        client = self._get_client()
        messages = self._build_messages(prompt, history)

        call_kwargs: dict[str, Any] = {
            "model": model,
            "system": DEFAULT_SYSTEM_INSTRUCTION,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.settings.gemini_temperature),
            "max_tokens": kwargs.get("max_tokens", self.settings.gemini_max_output_tokens),
        }
        if "tools" in kwargs and kwargs["tools"]:
            call_kwargs["tools"] = kwargs["tools"]

        try:
            resp = client.messages.create(**call_kwargs)
            # Anthropic response content blocks
            text_parts = [block.text for block in resp.content if hasattr(block, "text")]
            full_text = "".join(text_parts)

            parsed_tool_calls: list[ToolCall] = []
            tool_calls = None
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    tc = ToolCall(
                        call_id=getattr(block, "id", ""),
                        function_name=getattr(block, "name", ""),
                        arguments=getattr(block, "input", {}) or {},
                        response_id=getattr(resp, "id", None),
                    )
                    parsed_tool_calls.append(tc)
            if parsed_tool_calls:
                tool_calls = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {"name": tc.function_name, "arguments": tc.arguments},
                    }
                    for tc in parsed_tool_calls
                ]

            return AIResponse(
                text=full_text,
                raw_response=resp,
                finish_reason=resp.stop_reason,
                model=model,
                provider_id=self.provider_id,
                tool_calls=tool_calls,
                parsed_tool_calls=parsed_tool_calls,
                response_id=getattr(resp, "id", None),
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def stream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream response tokens from Anthropic messages endpoint."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before stream started.", provider_id=self.provider_id
            )

        model = kwargs.get("model") or self.settings.anthropic_model
        if "/" in model or model.startswith("anthropic/"):
            raise ModelNotFoundError(
                f"Invalid Anthropic native model identifier '{model}'. Gateway/OpenRouter route identifiers cannot be used with native Anthropic API.",
                provider_id=self.provider_id,
            )
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Anthropic. Please select an active model.",
                model,
            )

        client = self._get_client()
        messages = self._build_messages(prompt, history)

        def _abort_connection() -> None:
            try:
                if hasattr(client, "close"):
                    client.close()
            except Exception as e:
                logger.debug(f"Error aborting Anthropic socket on cancel: {e}")

        if cancellation_token:
            cancellation_token.register_callback(_abort_connection)

        try:
            with client.messages.stream(
                model=model,
                system=DEFAULT_SYSTEM_INSTRUCTION,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.settings.gemini_temperature,
                max_tokens=self.settings.gemini_max_output_tokens,
            ) as stream:
                for token in stream.text_stream:
                    if cancellation_token and cancellation_token.is_cancelled():
                        raise ProviderCancelledError(
                            "Stream cancelled by user.", provider_id=self.provider_id
                        )
                    yield token
        except Exception as exc:
            if cancellation_token and cancellation_token.is_cancelled():
                logger.info("Stream interrupted due to user cancellation.")
                raise ProviderCancelledError(
                    "Stream cancelled by user.", provider_id=self.provider_id
                ) from exc
            raise self._map_exception(exc) from exc
