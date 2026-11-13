"""Groq high-speed AI provider adapter for JARVIS."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import openai
from openai import OpenAI

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

logger = get_logger("ai.groq")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are JARVIS, an intelligent, polite, concise, and highly capable personal AI "
    "desktop assistant for Windows 11. You provide clear, accurate responses and seamlessly "
    "communicate in both English and Persian (فارسی)."
)


class GroqProvider(BaseAIProvider):
    """Groq ultra-fast LPU inference provider adapter utilizing OpenAI-compatible API."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = client

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def provider_id(self) -> str:
        return "groq"

    @property
    def default_model(self) -> str:
        return self.settings.groq_model

    def list_supported_models(self) -> list[ModelInfo]:
        return ModelCatalog.list_models("groq")

    def _get_client(self) -> OpenAI:
        """Instantiate or return the OpenAI client configured for Groq endpoint."""
        if self._client is not None:
            return self._client

        if not self.is_ready():
            raise AuthenticationError(
                "Groq API key is not configured.", provider_id=self.provider_id
            )

        assert self.settings.groq_api_key is not None
        raw_key = self.settings.groq_api_key.get_secret_value()
        base_url = self.settings.groq_base_url or "https://api.groq.com/openai/v1"
        timeout = float(self.settings.gemini_request_timeout)

        self._client = OpenAI(
            api_key=raw_key,
            base_url=base_url,
            timeout=timeout,
        )
        return self._client

    def is_ready(self) -> bool:
        """Check if provider has configured API key."""
        return self.settings.is_provider_configured("groq")

    def get_status(self) -> ProviderStatus:
        if self.is_ready():
            return ProviderStatus.READY
        return ProviderStatus.NOT_CONFIGURED

    def _build_messages(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
    ) -> list[dict[str, str]]:
        """Format prior conversation messages into messages payload."""
        messages: list[dict[str, str]] = [{"role": "system", "content": DEFAULT_SYSTEM_INSTRUCTION}]

        if history:
            limit = self.settings.conversation_history_limit
            bounded = history[-limit:]
            for msg in bounded:
                if msg.status != MessageStatus.COMPLETED or not msg.content:
                    continue
                role = "user" if msg.role == MessageRole.USER else "assistant"
                messages.append({"role": role, "content": msg.content})

        messages.append({"role": "user", "content": prompt})
        return messages

    def _map_exception(self, exc: Exception) -> Exception:
        """Normalize OpenAI SDK exceptions into typed AIProviderError instances."""
        msg = str(exc)
        if isinstance(exc, openai.AuthenticationError):
            return AuthenticationError(
                f"Groq Authentication Failed: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.PermissionDeniedError):
            return NormalizedPermissionError(
                f"Groq Permission Denied: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.NotFoundError):
            return ModelNotFoundError(
                f"Groq Model Not Found: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.RateLimitError):
            return RateLimitError(
                f"Groq Rate Limit Exceeded: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.BadRequestError):
            return InvalidRequestError(
                f"Groq Bad Request: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.InternalServerError):
            return ServiceUnavailableError(
                f"Groq Server Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.APITimeoutError):
            return NormalizedTimeoutError(
                f"Groq Request Timed Out: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.APIConnectionError):
            return NetworkError(
                f"Groq Network Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        return exc

    def test_connection(self) -> ConnectionTestResult:
        """Ping Groq chat completions with minimal token limit."""
        if not self.is_ready():
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.MISSING_API_KEY,
                message="Groq API key is not configured.",
            )

        start_time = time.perf_counter()
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.settings.groq_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            elapsed = (time.perf_counter() - start_time) * 1000.0
            if resp and resp.choices:
                return ConnectionTestResult(
                    is_success=True,
                    message=f"Connected successfully to Groq ({self.settings.groq_model}).",
                    error_type=ConnectionErrorType.SUCCESS,
                    latency_ms=round(elapsed, 1),
                )
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.UNKNOWN_ERROR,
                message="Received empty response from Groq endpoint.",
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
        """Generate a complete text response via Groq."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before invocation.", provider_id=self.provider_id
            )

        model = kwargs.get("model") or self.settings.groq_model
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Groq. Please use an active model.",
                model,
            )

        client = self._get_client()
        messages = self._build_messages(prompt, history)

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.settings.gemini_temperature),
            "max_tokens": kwargs.get("max_tokens", self.settings.gemini_max_output_tokens),
        }
        if "tools" in kwargs and kwargs["tools"]:
            call_kwargs["tools"] = kwargs["tools"]

        try:
            resp = client.chat.completions.create(**call_kwargs)
            choice = resp.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason

            parsed_tool_calls: list[ToolCall] = []
            tool_calls = None
            if getattr(choice.message, "tool_calls", None):
                tool_calls = []
                for tc_raw in choice.message.tool_calls:
                    cid = getattr(tc_raw, "id", None) or ""
                    fname = getattr(tc_raw.function, "name", "")
                    raw_args = getattr(tc_raw.function, "arguments", "") or "{}"
                    if not isinstance(raw_args, str):
                        raw_args = json.dumps(raw_args)

                    parsed_args: dict[str, Any] = {}
                    parse_err = None
                    try:
                        parsed = json.loads(raw_args)
                        if isinstance(parsed, dict):
                            parsed_args = parsed
                        else:
                            parse_err = f"Arguments is not a dict: {type(parsed).__name__}"
                    except Exception as jerr:
                        parse_err = f"Malformed tool arguments JSON: {jerr}"

                    tc = ToolCall(
                        call_id=cid,
                        function_name=fname,
                        arguments=parsed_args,
                        raw_arguments=raw_args,
                        error=parse_err,
                        response_id=getattr(resp, "id", None),
                    )
                    parsed_tool_calls.append(tc)
                    tool_calls.append(
                        {
                            "id": cid,
                            "type": getattr(tc_raw, "type", "function"),
                            "function": {"name": fname, "arguments": raw_args},
                        }
                    )

            return AIResponse(
                text=content,
                raw_response=resp,
                finish_reason=finish_reason,
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
        """Stream response tokens from Groq chat completions."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before stream started.", provider_id=self.provider_id
            )

        model = kwargs.get("model") or self.settings.groq_model
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by Groq. Please use an active model.",
                model,
            )

        client = self._get_client()
        messages = self._build_messages(prompt, history)

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.settings.gemini_temperature,
                max_tokens=self.settings.gemini_max_output_tokens,
                stream=True,
            )
            for chunk in stream:
                if cancellation_token and cancellation_token.is_cancelled():
                    raise ProviderCancelledError(
                        "Stream cancelled by user.", provider_id=self.provider_id
                    )
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            raise self._map_exception(exc) from exc
