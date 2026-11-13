"""OpenAI AI provider adapter for JARVIS."""

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

logger = get_logger("ai.openai")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are JARVIS, an intelligent, polite, concise, and highly capable personal AI "
    "desktop assistant for Windows 11. You provide clear, accurate responses and seamlessly "
    "communicate in both English and Persian (فارسی)."
)


class OpenAIProvider(BaseAIProvider):
    """OpenAI API provider adapter utilizing the official openai SDK."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = client

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def provider_id(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self.settings.openai_model

    def list_supported_models(self) -> list[ModelInfo]:
        return ModelCatalog.list_models("openai")

    def _get_client(self) -> OpenAI:
        """Instantiate or return the OpenAI client."""
        if self._client is not None:
            return self._client

        if not self.is_ready():
            raise AuthenticationError(
                "OpenAI API key is not configured.", provider_id=self.provider_id
            )

        assert self.settings.openai_api_key is not None
        raw_key = self.settings.openai_api_key.get_secret_value()
        base_url = self.settings.openai_base_url or None
        timeout = float(self.settings.gemini_request_timeout)

        self._client = OpenAI(
            api_key=raw_key,
            base_url=base_url,
            timeout=timeout,
        )
        return self._client

    def is_ready(self) -> bool:
        """Check if provider has configured API key."""
        return self.settings.is_provider_configured("openai")

    def get_status(self) -> ProviderStatus:
        if self.is_ready():
            return ProviderStatus.READY
        return ProviderStatus.NOT_CONFIGURED

    def _build_messages(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        model: str | None = None,
    ) -> list[dict[str, str]]:
        """Format prior conversation messages into OpenAI messages payload."""
        # Use developer role for reasoning models (o1, o3, gpt-6-astra, gpt-6.1-sol)
        is_dev_role = model and (
            model.startswith(("o1", "o3")) or model in ("gpt-6-astra", "gpt-6.1-sol")
        )
        sys_role = "developer" if is_dev_role else "system"
        messages: list[dict[str, str]] = [{"role": sys_role, "content": DEFAULT_SYSTEM_INSTRUCTION}]

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
                f"OpenAI Authentication Failed: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.PermissionDeniedError):
            return NormalizedPermissionError(
                f"OpenAI Permission Denied: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.NotFoundError):
            return ModelNotFoundError(
                f"OpenAI Model Not Found: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.RateLimitError):
            return RateLimitError(
                f"OpenAI Rate Limit Exceeded: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.BadRequestError):
            return InvalidRequestError(
                f"OpenAI Bad Request: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.InternalServerError):
            return ServiceUnavailableError(
                f"OpenAI Server Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.APITimeoutError):
            return NormalizedTimeoutError(
                f"OpenAI Request Timed Out: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        if isinstance(exc, openai.APIConnectionError):
            return NetworkError(
                f"OpenAI Network Error: {msg}", provider_id=self.provider_id, raw_error=exc
            )
        return exc

    def test_connection(self) -> ConnectionTestResult:
        """Ping OpenAI chat completions with minimal token limit."""
        if not self.is_ready():
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.MISSING_API_KEY,
                message="OpenAI API key is not configured.",
            )

        start_time = time.perf_counter()
        try:
            client = self._get_client()
            model = self.settings.openai_model
            is_reasoning = model.startswith(("o1", "o3"))
            test_kwargs: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
            }
            if is_reasoning:
                test_kwargs["max_completion_tokens"] = 5
            else:
                test_kwargs["max_tokens"] = 5

            resp = client.chat.completions.create(**test_kwargs)
            elapsed = (time.perf_counter() - start_time) * 1000.0
            if resp and resp.choices:
                return ConnectionTestResult(
                    is_success=True,
                    message=f"Connected successfully to OpenAI ({self.settings.openai_model}).",
                    error_type=ConnectionErrorType.SUCCESS,
                    latency_ms=round(elapsed, 1),
                )
            return ConnectionTestResult(
                is_success=False,
                error_type=ConnectionErrorType.UNKNOWN_ERROR,
                message="Received empty response from OpenAI endpoint.",
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

    @staticmethod
    def _parse_single_tool_call(
        call_id: str,
        func_name: str,
        raw_args: str | Any,
        response_id: str | None = None,
    ) -> ToolCall:
        """Parse raw JSON tool arguments safely, capturing malformed JSON into ToolCall.error."""
        if not isinstance(raw_args, str):
            raw_args = json.dumps(raw_args)
        parsed_args: dict[str, Any] = {}
        parse_error: str | None = None
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                parsed_args = parsed
            else:
                parse_error = f"Parsed arguments is not a dictionary: {type(parsed).__name__}"
        except Exception as json_err:
            parse_error = f"Malformed function arguments JSON: {json_err}"

        return ToolCall(
            call_id=call_id,
            function_name=func_name,
            arguments=parsed_args,
            raw_arguments=raw_args,
            error=parse_error,
            response_id=response_id,
        )

    def _prepare_api_call(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """High-level preparation of API call endpoint and kwargs."""
        target_model = model or self.settings.openai_model
        messages = self._build_messages(prompt, history, model=target_model)
        return self._prepare_call_kwargs(target_model, messages, tools=tools, **kwargs)

    def _prepare_call_kwargs(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Prepare validated call kwargs and endpoint selection (chat_completions vs responses).

        Endpoint and parameter compatibility rules:
        - gpt-6-luna: Chat Completions function calling supported with reasoning_effort='none'.
        - gpt-6-astra, gpt-6.1-sol & gpt-6.1-terra: Tool calling requires Responses API with reasoning.effort.
        - Reasoning models (o1, o3, gpt-6-astra, gpt-6.1-sol, gpt-6.1-terra): Temperature, top_p, etc. prohibited.
          Output tokens configured via max_completion_tokens (chat) or max_output_tokens (responses).
        """
        if ModelCatalog.is_model_retired(self.provider_id, model):
            logger.warning(
                "Model '%s' is marked RETIRED by OpenAI. Please migrate to an active model.",
                model,
            )

        is_pure_reasoning = model.startswith(("o1", "o3")) or model in (
            "gpt-6-astra",
            "gpt-6.1-sol",
            "gpt-6.1-terra",
        )
        endpoint = "chat_completions"

        call_kwargs: dict[str, Any] = {
            "model": model,
        }

        # Route tool calling to Responses API for Astra, Sol, Terra
        if tools and model in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra"):
            endpoint = "responses"
            call_kwargs["input"] = messages
            call_kwargs["tools"] = tools
            call_kwargs["reasoning"] = {"effort": kwargs.get("reasoning_effort", "high")}
            if "max_completion_tokens" in kwargs or "max_output_tokens" in kwargs:
                call_kwargs["max_output_tokens"] = kwargs.get(
                    "max_completion_tokens", kwargs.get("max_output_tokens")
                )
            if "previous_response_id" in kwargs:
                call_kwargs["previous_response_id"] = kwargs["previous_response_id"]
            return endpoint, call_kwargs

        # Chat Completions endpoint formatting
        call_kwargs["messages"] = messages

        if tools:
            call_kwargs["tools"] = tools
            if model == "gpt-6-luna":
                # GPT-6 Luna supports function calling with reasoning_effort="none"
                call_kwargs["reasoning_effort"] = "none"

        if is_pure_reasoning:
            call_kwargs["max_completion_tokens"] = kwargs.get(
                "max_completion_tokens", self.settings.gemini_max_output_tokens
            )
            if "reasoning_effort" in kwargs:
                call_kwargs["reasoning_effort"] = kwargs["reasoning_effort"]
            # Exclude temperature and top_p for pure reasoning models
        else:
            if "temperature" in kwargs or self.settings.gemini_temperature is not None:
                call_kwargs["temperature"] = kwargs.get(
                    "temperature", self.settings.gemini_temperature
                )
            call_kwargs["max_tokens"] = kwargs.get(
                "max_tokens", self.settings.gemini_max_output_tokens
            )
            if "reasoning_effort" in kwargs and model == "gpt-6-luna":
                call_kwargs["reasoning_effort"] = kwargs["reasoning_effort"]

        return endpoint, call_kwargs

    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate a complete text response via OpenAI."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before invocation.", provider_id=self.provider_id
            )

        client = self._get_client()
        model = kwargs.get("model") or self.settings.openai_model
        messages = self._build_messages(prompt, history, model=model)
        tools = kwargs.get("tools")

        extra_kwargs = {k: v for k, v in kwargs.items() if k not in ("model", "tools")}
        endpoint, call_kwargs = self._prepare_call_kwargs(
            model=model, messages=messages, tools=tools, **extra_kwargs
        )

        try:
            if endpoint == "responses":
                # Official OpenAI Responses API client interface
                resp = client.responses.create(**call_kwargs)
                response_id = getattr(resp, "id", None)
                status = getattr(resp, "status", "completed")

                if status == "failed":
                    err_details = getattr(resp, "error", None) or "Responses API invocation failed."
                    raise ServiceUnavailableError(
                        f"OpenAI Responses API error: {err_details}",
                        provider_id=self.provider_id,
                    )

                content = getattr(resp, "output_text", "") or ""
                tool_calls: list[dict[str, Any]] = []
                parsed_tool_calls: list[ToolCall] = []

                # Extract text and tool calls from response output items
                if hasattr(resp, "output") and resp.output:
                    output_items = resp.output if isinstance(resp.output, list) else [resp.output]
                    for item in output_items:
                        # Extract text content
                        if not content and hasattr(item, "content") and item.content:
                            content_parts = (
                                item.content if isinstance(item.content, list) else [item.content]
                            )
                            for part in content_parts:
                                if hasattr(part, "text") and part.text:
                                    content += str(part.text)
                        if hasattr(item, "text") and item.text and not content:
                            content += str(item.text)

                        # Extract function call item
                        item_type = getattr(item, "type", None)
                        if item_type == "function_call":
                            call_id = (
                                getattr(item, "id", None) or getattr(item, "call_id", None) or ""
                            )
                            func_name = getattr(item, "name", "")
                            raw_args = getattr(item, "arguments", "") or "{}"
                            tc = self._parse_single_tool_call(
                                call_id=call_id,
                                func_name=func_name,
                                raw_args=raw_args,
                                response_id=response_id,
                            )
                            parsed_tool_calls.append(tc)
                            tool_calls.append(
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": func_name,
                                        "arguments": raw_args,
                                    },
                                }
                            )

                refusal = getattr(resp, "refusal", None)
                metadata: dict[str, Any] = {}
                if refusal:
                    metadata["refusal"] = refusal

                return AIResponse(
                    text=content,
                    raw_response=resp,
                    finish_reason=status,
                    model=model,
                    provider_id=self.provider_id,
                    tool_calls=tool_calls if tool_calls else None,
                    parsed_tool_calls=parsed_tool_calls,
                    response_id=response_id,
                    is_incomplete=(status == "incomplete"),
                    metadata=metadata,
                )
            else:
                resp = client.chat.completions.create(**call_kwargs)
                choice = resp.choices[0]
                content = choice.message.content or ""
                finish_reason = choice.finish_reason
                response_id = getattr(resp, "id", None)
                tool_calls_raw = getattr(choice.message, "tool_calls", None)

                tool_calls = []
                parsed_tool_calls = []
                if tool_calls_raw:
                    for tc_raw in tool_calls_raw:
                        cid = getattr(tc_raw, "id", None) or ""
                        fname = getattr(tc_raw.function, "name", "")
                        raw_args = getattr(tc_raw.function, "arguments", "") or "{}"
                        tc = self._parse_single_tool_call(
                            call_id=cid,
                            func_name=fname,
                            raw_args=raw_args,
                            response_id=response_id,
                        )
                        parsed_tool_calls.append(tc)
                        tool_calls.append(
                            {
                                "id": cid,
                                "type": getattr(tc_raw, "type", "function"),
                                "function": {
                                    "name": fname,
                                    "arguments": raw_args,
                                },
                            }
                        )

                refusal = getattr(choice.message, "refusal", None)
                metadata = {}
                if refusal:
                    metadata["refusal"] = refusal

                return AIResponse(
                    text=content,
                    raw_response=resp,
                    finish_reason=finish_reason,
                    model=model,
                    provider_id=self.provider_id,
                    tool_calls=tool_calls if tool_calls else None,
                    parsed_tool_calls=parsed_tool_calls,
                    response_id=response_id,
                    metadata=metadata,
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
        """Stream response tokens from OpenAI chat completions or Responses API."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError(
                "Operation cancelled before stream started.", provider_id=self.provider_id
            )

        client = self._get_client()
        model = kwargs.get("model") or self.settings.openai_model
        messages = self._build_messages(prompt, history, model=model)
        tools = kwargs.get("tools")

        extra_kwargs = {k: v for k, v in kwargs.items() if k not in ("model", "tools")}
        endpoint, call_kwargs = self._prepare_call_kwargs(
            model=model, messages=messages, tools=tools, **extra_kwargs
        )
        call_kwargs["stream"] = True

        def _abort_connection() -> None:
            try:
                if hasattr(client, "close"):
                    client.close()
            except Exception as e:
                logger.debug(f"Error aborting OpenAI socket on cancel: {e}")

        if cancellation_token:
            cancellation_token.register_callback(_abort_connection)

        try:
            if endpoint == "responses":
                stream = client.responses.create(**call_kwargs)
                for event in stream:
                    if cancellation_token and cancellation_token.is_cancelled():
                        raise ProviderCancelledError(
                            "Stream cancelled by user.", provider_id=self.provider_id
                        )

                    ev_type = getattr(event, "type", "")
                    if ev_type in ("response.failed", "error"):
                        err_obj = getattr(event, "error", None) or "Responses streaming error."
                        raise ServiceUnavailableError(
                            f"OpenAI Responses API stream failure: {err_obj}",
                            provider_id=self.provider_id,
                        )

                    # Do not yield tool call argument fragments as chat text
                    if ev_type in (
                        "response.function_call_arguments.delta",
                        "response.function_call_arguments.done",
                    ):
                        continue

                    if ev_type in (
                        "response.output_text.delta",
                        "response.text.delta",
                    ):
                        delta_val = getattr(event, "delta", None) or getattr(event, "text", None)
                        if delta_val:
                            yield str(delta_val)
                    elif ev_type == "response.output_item.delta":
                        delta_obj = getattr(event, "delta", None)
                        if isinstance(delta_obj, str):
                            yield delta_obj
                        elif hasattr(delta_obj, "text") and delta_obj.text:
                            yield str(delta_obj.text)
                    elif hasattr(event, "output_text_delta") and event.output_text_delta:
                        yield str(event.output_text_delta)
                    elif (
                        hasattr(event, "delta")
                        and event.delta
                        and not ev_type.startswith("response.function_call")
                    ):
                        yield str(event.delta)
                    elif hasattr(event, "item") and hasattr(event.item, "content"):
                        for part in event.item.content:
                            if hasattr(part, "text") and part.text:
                                yield str(part.text)
            else:
                stream = client.chat.completions.create(**call_kwargs)
                for chunk in stream:
                    if cancellation_token and cancellation_token.is_cancelled():
                        raise ProviderCancelledError(
                            "Stream cancelled by user.", provider_id=self.provider_id
                        )
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
        except Exception as exc:
            if cancellation_token and cancellation_token.is_cancelled():
                logger.info("Stream interrupted due to user cancellation.")
                raise ProviderCancelledError(
                    "Stream cancelled by user.", provider_id=self.provider_id
                ) from exc
            raise self._map_exception(exc) from exc

    @classmethod
    def accumulate_responses_stream_events(
        cls,
        events: Any,
    ) -> tuple[str, list[ToolCall], str | None, str | None]:
        """Process Responses API streaming event sequence, safely accumulating text deltas and tool calls.

        Guarantees:
        - Text deltas are separated from function call argument deltas.
        - Tool calls are only returned when explicitly marked complete.
        - Malformed argument JSON is captured in ToolCall.error without unhandled exception.
        - Incomplete function calls (e.g. stream cut off) record error and are not marked complete.
        """
        accumulated_text = ""
        in_flight_tools: dict[str, dict[str, Any]] = {}
        completed_tools: list[ToolCall] = []
        response_id: str | None = None
        finish_status: str | None = None

        for event in events:
            ev_type = getattr(event, "type", "")
            ev_id = getattr(event, "id", None)
            if isinstance(ev_id, str):
                response_id = ev_id

            if ev_type in ("response.created", "response.done", "response.completed"):
                status_val = getattr(event, "status", None)
                if isinstance(status_val, str):
                    finish_status = status_val
                resp_obj = getattr(event, "response", None)
                if resp_obj and hasattr(resp_obj, "id") and isinstance(resp_obj.id, str):
                    response_id = resp_obj.id
                if resp_obj and hasattr(resp_obj, "status") and isinstance(resp_obj.status, str):
                    finish_status = resp_obj.status

            elif ev_type in ("response.failed", "error"):
                finish_status = "failed"
            elif ev_type == "response.incomplete":
                finish_status = "incomplete"

            elif ev_type in (
                "response.output_text.delta",
                "response.text.delta",
            ):
                delta = getattr(event, "delta", None) or getattr(event, "text", None)
                if delta:
                    accumulated_text += str(delta)

            elif ev_type in ("response.output_item.added", "output_item.added"):
                item = getattr(event, "item", None)
                if item and getattr(item, "type", None) == "function_call":
                    cid = str(getattr(item, "id", None) or getattr(item, "call_id", None) or "")
                    fname = str(getattr(item, "name", "") or "")
                    if cid in in_flight_tools:
                        if fname and not in_flight_tools[cid]["name"]:
                            in_flight_tools[cid]["name"] = fname
                    else:
                        in_flight_tools[cid] = {
                            "call_id": cid,
                            "name": fname,
                            "args_accum": "",
                            "is_done": False,
                        }

            elif ev_type in (
                "response.function_call_arguments.delta",
                "function_call_arguments.delta",
            ):
                cid = str(getattr(event, "item_id", None) or getattr(event, "call_id", None) or "")
                delta = str(
                    getattr(event, "delta", None) or getattr(event, "arguments", None) or ""
                )
                if cid in in_flight_tools:
                    in_flight_tools[cid]["args_accum"] += delta
                else:
                    in_flight_tools[cid] = {
                        "call_id": cid,
                        "name": str(getattr(event, "name", "") or ""),
                        "args_accum": delta,
                        "is_done": False,
                    }

            elif ev_type in (
                "response.function_call_arguments.done",
                "function_call_arguments.done",
            ):
                cid = str(getattr(event, "item_id", None) or getattr(event, "call_id", None) or "")
                final_args = getattr(event, "arguments", None)
                if cid in in_flight_tools:
                    if final_args is not None:
                        in_flight_tools[cid]["args_accum"] = str(final_args)
                    in_flight_tools[cid]["is_done"] = True

            elif ev_type in ("response.output_item.done", "output_item.done"):
                item = getattr(event, "item", None)
                if item and getattr(item, "type", None) == "function_call":
                    cid = str(getattr(item, "id", None) or getattr(item, "call_id", None) or "")
                    if cid in in_flight_tools:
                        in_flight_tools[cid]["is_done"] = True

        for _cid, tdata in in_flight_tools.items():
            if not tdata["is_done"] or finish_status in ("incomplete", "failed"):
                reason = (
                    f"stream finished with status '{finish_status}'"
                    if finish_status in ("incomplete", "failed")
                    else "streaming cut off before completion"
                )
                completed_tools.append(
                    ToolCall(
                        call_id=tdata["call_id"],
                        function_name=tdata["name"],
                        arguments={},
                        raw_arguments=tdata["args_accum"],
                        error=f"Incomplete tool call: {reason}",
                        response_id=response_id,
                    )
                )
            else:
                tc = cls._parse_single_tool_call(
                    call_id=tdata["call_id"],
                    func_name=tdata["name"],
                    raw_args=tdata["args_accum"],
                    response_id=response_id,
                )
                completed_tools.append(tc)

        return accumulated_text, completed_tools, response_id, finish_status

    @classmethod
    def accumulate_chat_stream_chunks(
        cls,
        chunks: Any,
    ) -> tuple[str, list[ToolCall], str | None]:
        """Process Chat Completions streaming chunk sequence, accumulating text deltas and tool calls."""
        accumulated_text = ""
        tools_by_index: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        for chunk in chunks:
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

            delta = getattr(choice, "delta", None)
            if not delta:
                continue

            if getattr(delta, "content", None):
                accumulated_text += delta.content

            if getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = getattr(tc_delta, "index", 0)
                    if idx not in tools_by_index:
                        tools_by_index[idx] = {
                            "id": getattr(tc_delta, "id", None) or "",
                            "name": "",
                            "args": "",
                        }
                    tid = getattr(tc_delta, "id", None)
                    if isinstance(tid, str):
                        tools_by_index[idx]["id"] = tid
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        fn_name = getattr(tc_delta.function, "name", None)
                        if isinstance(fn_name, str):
                            tools_by_index[idx]["name"] += fn_name
                        fn_args = getattr(tc_delta.function, "arguments", None)
                        if isinstance(fn_args, str):
                            tools_by_index[idx]["args"] += fn_args

        completed_tools: list[ToolCall] = []
        for idx in sorted(tools_by_index.keys()):
            tinfo = tools_by_index[idx]
            if not finish_reason or finish_reason not in ("tool_calls", "stop"):
                err = "Incomplete tool call: stream terminated prematurely"
            else:
                err = None
            tc = cls._parse_single_tool_call(
                call_id=tinfo["id"],
                func_name=tinfo["name"],
                raw_args=tinfo["args"],
            )
            if err and not tc.error:
                tc.error = err
            completed_tools.append(tc)

        return accumulated_text, completed_tools, finish_reason

    def build_tool_continuation(
        self,
        original_response: AIResponse,
        tool_call_id: str | None = None,
        result: str | None = None,
        history: list[ConversationMessage] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Construct a tool result submission payload for subsequent generation turn.

        Supports both single tool result (tool_call_id + result) and batch tool_results list.
        """
        results_list: list[dict[str, str]] = []
        if tool_results:
            for item in tool_results:
                cid = item.get("call_id") or item.get("tool_call_id") or ""
                out = str(item.get("output", item.get("result", "")))
                results_list.append({"call_id": cid, "output": out})
        elif tool_call_id is not None:
            results_list.append({"call_id": tool_call_id, "output": str(result or "")})

        model = original_response.model or self.settings.openai_model
        if model in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra"):
            # Responses API continuation uses previous_response_id and tool result items
            return {
                "endpoint": "responses",
                "model": model,
                "previous_response_id": original_response.response_id,
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": item["call_id"],
                        "output": item["output"],
                    }
                    for item in results_list
                ],
            }
        else:
            # Chat Completions continuation appends assistant tool_calls and tool message
            continuation_messages: list[dict[str, Any]] = []
            if original_response.tool_calls:
                continuation_messages.append(
                    {
                        "role": "assistant",
                        "content": original_response.text or None,
                        "tool_calls": original_response.tool_calls,
                    }
                )
            for item in results_list:
                continuation_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item["call_id"],
                        "content": item["output"],
                    }
                )
            return {
                "endpoint": "chat_completions",
                "model": model,
                "messages": continuation_messages,
            }
