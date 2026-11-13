"""Provider Manager orchestrating AI provider selection, routing, and dual fallback."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ai.base import (
    AIResponse,
    BaseAIProvider,
    CapabilityNotSupportedError,
    ConnectionTestResult,
    ModelCapabilities,
    ModelInfo,
    ModelNotFoundError,
    NetworkError,
    PrivacyViolationError,
    ProviderCancelledError,
    ProviderStatus,
    RateLimitError,
    ServiceUnavailableError,
    UnknownProviderError,
)
from ai.base import (
    TimeoutError as NormalizedTimeoutError,
)
from ai.catalog import ModelCatalog
from ai.registry import ProviderRegistry, create_default_registry
from config import Settings, get_settings
from core.execution_context import CancellationToken
from infrastructure.logging import get_logger
from memory.base import ConversationMessage

logger = get_logger("ai.manager")


@dataclass
class FallbackEvent:
    """Record of a fallback attempt and outcome."""

    original_provider: str
    target_provider: str
    reason: str
    timestamp: float = field(default_factory=time.time)
    is_success: bool = False


class ProviderManager(BaseAIProvider):
    """Facade orchestrating provider selection, session routing, and automatic/manual fallback."""

    def __init__(
        self,
        settings: Settings | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or create_default_registry(self.settings)
        self._session_providers: dict[str, str] = {}
        self._last_fallback_events: list[FallbackEvent] = []
        self._model_cooldowns: dict[tuple[str, str], float] = {}
        self._provider_cooldowns: dict[str, float] = {}
        self._failover_listeners: list[Callable[[dict[str, Any]], None]] = []

    def add_failover_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback to receive real-time model failover events."""
        if listener not in self._failover_listeners:
            self._failover_listeners.append(listener)

    def remove_failover_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Unregister a failover event callback."""
        if listener in self._failover_listeners:
            self._failover_listeners.remove(listener)

    def _notify_failover(self, event_type: str, **kwargs: Any) -> None:
        """Emit failover lifecycle event to all registered listeners."""
        payload = {"event": event_type, "timestamp": time.time(), **kwargs}
        for listener in list(self._failover_listeners):
            try:
                listener(payload)
            except Exception as exc:
                logger.debug(f"Error notifying failover listener: {exc}")

    def mark_model_cooldown(
        self, provider_id: str, model_id: str, duration_seconds: float | None = None
    ) -> None:
        """Mark a specific model in cooldown to prevent repeated failure loops."""
        duration = duration_seconds or getattr(self.settings, "failover_cooldown_seconds", 60.0)
        expires_at = time.time() + duration
        self._model_cooldowns[(provider_id.lower().strip(), model_id.strip())] = expires_at
        logger.info(
            f"Marked model '{provider_id}:{model_id}' in cooldown for {duration:.0f}s (until {expires_at:.1f})"
        )

    def is_model_in_cooldown(self, provider_id: str, model_id: str) -> bool:
        """Check if a model is currently within its cooldown period."""
        expires_at = self._model_cooldowns.get((provider_id.lower().strip(), model_id.strip()), 0.0)
        return time.time() < expires_at

    def mark_provider_cooldown(
        self, provider_id: str, duration_seconds: float | None = None
    ) -> None:
        """Mark an entire provider in cooldown."""
        duration = duration_seconds or getattr(self.settings, "failover_cooldown_seconds", 60.0)
        expires_at = time.time() + duration
        self._provider_cooldowns[provider_id.lower().strip()] = expires_at
        logger.info(
            f"Marked provider '{provider_id}' in cooldown for {duration:.0f}s (until {expires_at:.1f})"
        )

    def is_provider_in_cooldown(self, provider_id: str) -> bool:
        """Check if a provider is currently within its cooldown period."""
        expires_at = self._provider_cooldowns.get(provider_id.lower().strip(), 0.0)
        return time.time() < expires_at

    def reset_cooldowns(self) -> None:
        """Clear all active model and provider cooldowns."""
        self._model_cooldowns.clear()
        self._provider_cooldowns.clear()
        logger.info("Cleared all model and provider cooldowns.")

    @property
    def provider_name(self) -> str:
        active = self.get_active_provider()
        return f"managed({active.provider_name})"

    @property
    def provider_id(self) -> str:
        return self.get_active_provider_id()

    @property
    def default_model(self) -> str:
        return self.get_active_provider().default_model

    def list_supported_models(self) -> list[ModelInfo]:
        return self.get_active_provider().list_supported_models()

    def get_model_capabilities(self, model_id: str) -> ModelCapabilities:
        return self.get_active_provider().get_model_capabilities(model_id)

    def get_active_provider_id(self, session_id: str | None = None) -> str:
        """Resolve active provider for the given session or global default."""
        if session_id and session_id in self._session_providers:
            return self._session_providers[session_id]

        configured_default = self.settings.default_provider.lower().strip()
        if self.registry.has_provider(configured_default):
            return configured_default

        # Fallback to gemini if default invalid
        return "gemini"

    def set_session_provider(self, session_id: str, provider_id: str) -> None:
        """Explicitly route requests for a specific conversation session to a provider."""
        pid = provider_id.lower().strip()
        if not self.registry.has_provider(pid):
            raise UnknownProviderError(
                f"Cannot route to unknown provider: '{provider_id}'.", provider_id=pid
            )
        self._session_providers[session_id] = pid
        logger.info(f"Routed session {session_id} to provider: {pid}")

    def clear_session_provider(self, session_id: str) -> None:
        """Clear session-specific provider routing."""
        self._session_providers.pop(session_id, None)

    def get_active_provider(self, session_id: str | None = None) -> BaseAIProvider:
        """Return the active provider instance for session or global default."""
        pid = self.get_active_provider_id(session_id)
        return self.registry.get_provider(pid)

    def is_ready(self) -> bool:
        """Return True if the current active provider is configured and ready."""
        active = self.get_active_provider()
        return active.is_ready()

    def get_status(self) -> ProviderStatus:
        active = self.get_active_provider()
        return active.get_status()

    def validate_capability(
        self,
        capability: str,
        model_id: str | None = None,
        provider_id: str | None = None,
    ) -> None:
        """Validate whether the specified or active provider and model support the required capability."""
        pid = provider_id or self.get_active_provider_id()
        provider = self.registry.get_provider(pid)
        provider.validate_capability(capability, model_id=model_id)

    def test_connection(self, provider_id: str | None = None) -> ConnectionTestResult:
        """Test connectivity of specified or active provider."""
        pid = provider_id or self.get_active_provider_id()
        provider = self.registry.get_provider(pid)
        return provider.test_connection()

    def _is_retryable_error(self, exc: Exception) -> bool:
        """Determine whether an error is transient or model-specific and eligible for automatic fallback."""
        if isinstance(
            exc,
            (
                ServiceUnavailableError,
                RateLimitError,
                NetworkError,
                NormalizedTimeoutError,
                ModelNotFoundError,
                CapabilityNotSupportedError,
            ),
        ):
            return True
        # Check by class name or substring
        err_str = str(exc).lower()
        return bool(
            any(
                term in err_str
                for term in (
                    "503",
                    "504",
                    "502",
                    "500",
                    "overloaded",
                    "high demand",
                    "rate limit",
                    "timeout",
                    "timed out",
                    "connect error",
                    "connection error",
                    "model not found",
                    "not found",
                    "model_not_found",
                    "model unavailable",
                    "does not exist",
                    "unsupported model",
                )
            )
        )

    def _get_intra_provider_candidates(
        self, current_provider_id: str, current_model: str
    ) -> list[str]:
        """Compute ordered list of alternative active models for the same provider, filtering out cooled-down models."""
        if not self.settings.allow_intra_provider_fallback:
            return []

        candidates: list[str] = []
        # First check documented replacement model if available
        replacement = ModelCatalog.get_replacement_model(current_provider_id, current_model)
        if (
            replacement
            and replacement != current_model
            and ModelCatalog.is_model_eligible(current_provider_id, replacement)
            and not self.is_model_in_cooldown(current_provider_id, replacement)
        ):
            candidates.append(replacement)

        # Then add remaining verified active models for this provider
        for m in ModelCatalog.list_models(
            current_provider_id, include_deprecated=False, public_only=True
        ):
            if (
                m.model_id != current_model
                and m.model_id not in candidates
                and ModelCatalog.is_model_eligible(current_provider_id, m.model_id)
                and not self.is_model_in_cooldown(current_provider_id, m.model_id)
            ):
                candidates.append(m.model_id)

        return candidates

    def _get_fallback_candidates(self, current_provider_id: str) -> list[str]:
        """Compute ordered list of alternative enabled and configured providers, filtering out cooled-down providers."""
        if not self.settings.allow_cross_provider_fallback:
            return []

        order = self.settings.fallback_provider_order or [
            "gemini",
            "groq",
            "openai",
            "anthropic",
            "deepseek",
            "openrouter",
        ]
        candidates: list[str] = []
        for pid in order:
            norm_id = pid.lower().strip()
            if norm_id == current_provider_id:
                continue
            if not self.registry.has_provider(norm_id):
                continue
            if not self.registry.is_provider_enabled(norm_id):
                continue
            if not self.registry.is_provider_configured(norm_id):
                continue
            if self.is_provider_in_cooldown(norm_id):
                continue
            candidates.append(norm_id)
        return candidates

    def generate_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate text with automatic fallback across configured models and providers."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError("Generation cancelled before invocation.")

        session_id = kwargs.get("session_id")
        primary_id = kwargs.get("provider_id") or self.get_active_provider_id(session_id)
        current_id = primary_id

        # Resolve initial model
        primary_provider = self.registry.get_provider(primary_id)
        current_model = kwargs.get("model") or primary_provider.default_model

        tried_configs: list[tuple[str, str]] = [(current_id, current_model)]
        tried_providers: list[str] = [current_id]

        max_attempts = getattr(self.settings, "max_fallback_attempts", 3)

        while True:
            if cancellation_token and cancellation_token.is_cancelled():
                raise ProviderCancelledError("Generation cancelled.")

            # Capability pre-validation
            required_caps = kwargs.get("required_capabilities") or []
            if isinstance(required_caps, str):
                required_caps = [required_caps]
            for cap in required_caps:
                self.validate_capability(cap, model_id=current_model, provider_id=current_id)

            provider = self.registry.get_provider(current_id)

            # Strict privacy enforcement for cross-provider transfer
            is_cross_provider = current_id != primary_id
            if is_cross_provider and not self.settings.allow_cross_provider_fallback:
                raise PrivacyViolationError(
                    f"Cross-provider dispatch to '{current_id}' is prohibited by privacy settings "
                    "(allow_cross_provider_fallback is disabled).",
                    provider_id=current_id,
                )

            if is_cross_provider and not self.settings.allow_cross_provider_prompt_transfer:
                raise PrivacyViolationError(
                    f"Transmitting prompt to alternative provider '{current_id}' is prohibited by "
                    "privacy settings (allow_cross_provider_prompt_transfer is disabled).",
                    provider_id=current_id,
                )

            effective_history = (
                history
                if (not is_cross_provider or self.settings.allow_cross_provider_history_transfer)
                else None
            )
            if effective_history is None and history and is_cross_provider:
                logger.info(
                    f"Privacy guard: omitting conversation history for fallback provider '{current_id}'"
                )

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = current_model

            # Privacy boundary: Strip long-term memories if cloud memory transmission is prohibited
            effective_prompt = prompt
            if (
                not getattr(self.settings, "memory_allow_cloud_transmission", False)
                and "[RELEVANT USER MEMORY]" in effective_prompt
            ):
                effective_prompt = re.sub(
                    r"\[RELEVANT USER MEMORY\].*?\[END USER MEMORY\]\s*",
                    "",
                    effective_prompt,
                    flags=re.DOTALL,
                ).strip()

            try:
                response = provider.generate_text(
                    prompt=effective_prompt,
                    history=effective_history,
                    cancellation_token=cancellation_token,
                    **call_kwargs,
                )
                initial_model = kwargs.get("model") or primary_provider.default_model
                if current_id != primary_id or current_model != initial_model:
                    response.metadata["fallback"] = True
                    response.metadata["original_provider"] = primary_id
                    response.metadata["original_model"] = initial_model
                    response.metadata["actual_provider"] = current_id
                    response.metadata["actual_model"] = current_model
                    self._notify_failover(
                        "failover_success",
                        original_provider=primary_id,
                        original_model=initial_model,
                        actual_provider=current_id,
                        actual_model=current_model,
                    )
                return response

            except Exception as exc:
                if cancellation_token and cancellation_token.is_cancelled():
                    raise ProviderCancelledError("Operation cancelled.") from exc

                # Mark the failed model in cooldown
                self.mark_model_cooldown(current_id, current_model)

                if (
                    not self.settings.enable_auto_fallback
                    or not self._is_retryable_error(exc)
                    or len(tried_configs) >= max_attempts + 1
                ):
                    if len(tried_configs) >= max_attempts + 1:
                        logger.error(
                            f"Max fallback attempts ({max_attempts}) reached for request. Halting."
                        )
                        self._notify_failover(
                            "failover_exhausted",
                            reason=f"Maximum fallback attempts ({max_attempts}) exceeded.",
                            last_error=str(exc),
                        )
                    else:
                        logger.error(
                            f"Non-fallbackable or fatal error on provider '{current_id}:{current_model}': {exc}"
                        )
                    raise

                # 1. Attempt intra-provider model fallback first if allowed
                provider_attempts = sum(1 for p_id, _ in tried_configs if p_id == current_id)
                has_cross_candidates = self.settings.allow_cross_provider_fallback and any(
                    c not in tried_providers for c in self._get_fallback_candidates(current_id)
                )
                can_try_intra = self.settings.allow_intra_provider_fallback and (
                    provider_attempts < 2 or not has_cross_candidates
                )

                if can_try_intra:
                    intra_candidates = [
                        m
                        for m in self._get_intra_provider_candidates(current_id, current_model)
                        if (current_id, m) not in tried_configs
                    ]
                    if intra_candidates:
                        next_model = intra_candidates[0]
                        logger.warning(
                            f"Intra-provider fallback: switching model on '{current_id}' from '{current_model}' to '{next_model}' ({exc})"
                        )
                        self._notify_failover(
                            "failover_attempt",
                            original_provider=current_id,
                            original_model=current_model,
                            target_provider=current_id,
                            target_model=next_model,
                            reason=str(exc),
                        )
                        self._last_fallback_events.append(
                            FallbackEvent(
                                original_provider=f"{current_id}:{current_model}",
                                target_provider=f"{current_id}:{next_model}",
                                reason=str(exc),
                            )
                        )
                        current_model = next_model
                        tried_configs.append((current_id, current_model))
                        continue

                # 2. Attempt cross-provider fallback
                logger.warning(
                    f"Provider '{current_id}:{current_model}' failed ({exc}). Evaluating cross-provider fallback..."
                )
                if not self.settings.allow_cross_provider_fallback:
                    self._notify_failover(
                        "failover_blocked",
                        reason="allow_cross_provider_fallback is disabled by user policy.",
                        original_provider=primary_id,
                    )
                    raise PrivacyViolationError(
                        f"Cross-provider fallback from '{primary_id}' is blocked by privacy settings "
                        "(allow_cross_provider_fallback is disabled).",
                        provider_id=primary_id,
                    ) from exc

                candidates = [
                    c for c in self._get_fallback_candidates(current_id) if c not in tried_providers
                ]
                if not candidates:
                    logger.error("No further fallback providers available.")
                    self._notify_failover(
                        "failover_exhausted",
                        reason="No further healthy fallback providers configured or available.",
                        last_error=str(exc),
                    )
                    raise

                next_provider_id = candidates[0]
                if not self.settings.allow_cross_provider_prompt_transfer:
                    self._notify_failover(
                        "failover_blocked",
                        reason="allow_cross_provider_prompt_transfer is disabled.",
                        target_provider=next_provider_id,
                    )
                    raise PrivacyViolationError(
                        f"Cross-provider prompt transfer from '{primary_id}' to '{next_provider_id}' "
                        "is blocked by privacy settings (allow_cross_provider_prompt_transfer is disabled).",
                        provider_id=next_provider_id,
                    ) from exc

                next_provider = self.registry.get_provider(next_provider_id)
                next_model = next_provider.default_model

                self._notify_failover(
                    "failover_attempt",
                    original_provider=current_id,
                    original_model=current_model,
                    target_provider=next_provider_id,
                    target_model=next_model,
                    reason=str(exc),
                )
                self._last_fallback_events.append(
                    FallbackEvent(
                        original_provider=f"{current_id}:{current_model}",
                        target_provider=f"{next_provider_id}:{next_model}",
                        reason=str(exc),
                    )
                )
                logger.info(
                    f"Auto-fallback: routing request from '{current_id}' to '{next_provider_id}'"
                )
                current_id = next_provider_id
                current_model = next_model
                tried_providers.append(current_id)
                tried_configs.append((current_id, current_model))

    def stream_text(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream text tokens with automatic fallback to secondary model or provider on initial failure."""
        if cancellation_token and cancellation_token.is_cancelled():
            raise ProviderCancelledError("Stream cancelled before invocation.")

        session_id = kwargs.get("session_id")
        primary_id = kwargs.get("provider_id") or self.get_active_provider_id(session_id)
        current_id = primary_id

        primary_provider = self.registry.get_provider(primary_id)
        current_model = kwargs.get("model") or primary_provider.default_model

        tried_configs: list[tuple[str, str]] = [(current_id, current_model)]
        tried_providers: list[str] = [current_id]

        max_attempts = getattr(self.settings, "max_fallback_attempts", 3)

        while True:
            if cancellation_token and cancellation_token.is_cancelled():
                raise ProviderCancelledError("Stream cancelled.")

            # Capability pre-validation
            required_caps = kwargs.get("required_capabilities") or []
            if isinstance(required_caps, str):
                required_caps = [required_caps]
            for cap in required_caps:
                self.validate_capability(cap, model_id=current_model, provider_id=current_id)

            provider = self.registry.get_provider(current_id)

            # Strict privacy enforcement for cross-provider transfer
            is_cross_provider = current_id != primary_id
            if is_cross_provider and not self.settings.allow_cross_provider_fallback:
                raise PrivacyViolationError(
                    f"Cross-provider streaming to '{current_id}' is prohibited by privacy settings "
                    "(allow_cross_provider_fallback is disabled).",
                    provider_id=current_id,
                )

            if is_cross_provider and not self.settings.allow_cross_provider_prompt_transfer:
                raise PrivacyViolationError(
                    f"Transmitting prompt to alternative provider '{current_id}' is prohibited by "
                    "privacy settings (allow_cross_provider_prompt_transfer is disabled).",
                    provider_id=current_id,
                )

            effective_history = (
                history
                if (not is_cross_provider or self.settings.allow_cross_provider_history_transfer)
                else None
            )
            if effective_history is None and history and is_cross_provider:
                logger.info(
                    f"Privacy guard: omitting conversation history for fallback provider '{current_id}'"
                )

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = current_model

            # Privacy boundary: Strip long-term memories if cloud memory transmission is prohibited
            effective_prompt = prompt
            if (
                not getattr(self.settings, "memory_allow_cloud_transmission", False)
                and "[RELEVANT USER MEMORY]" in effective_prompt
            ):
                effective_prompt = re.sub(
                    r"\[RELEVANT USER MEMORY\].*?\[END USER MEMORY\]\s*",
                    "",
                    effective_prompt,
                    flags=re.DOTALL,
                ).strip()

            stream_started = False
            try:
                stream = provider.stream_text(
                    prompt=effective_prompt,
                    history=effective_history,
                    cancellation_token=cancellation_token,
                    **call_kwargs,
                )
                for chunk in stream:
                    stream_started = True
                    if cancellation_token and cancellation_token.is_cancelled():
                        raise ProviderCancelledError("Stream cancelled by user.")
                    yield chunk
                return

            except Exception as exc:
                if cancellation_token and cancellation_token.is_cancelled():
                    raise ProviderCancelledError("Stream cancelled by user.") from exc

                # Mark the failed model in cooldown
                self.mark_model_cooldown(current_id, current_model)

                # If tokens were already partially yielded to UI, do not switch mid-stream to avoid garbled text
                if (
                    stream_started
                    or not self.settings.enable_auto_fallback
                    or not self._is_retryable_error(exc)
                    or len(tried_configs) >= max_attempts + 1
                ):
                    if stream_started:
                        logger.error(
                            f"Provider '{current_id}:{current_model}' failed mid-stream after tokens yielded; halting cleanly without corrupting text: {exc}"
                        )
                    elif len(tried_configs) >= max_attempts + 1:
                        logger.error(
                            f"Max stream fallback attempts ({max_attempts}) reached for request. Halting."
                        )
                        self._notify_failover(
                            "failover_exhausted",
                            reason=f"Maximum fallback attempts ({max_attempts}) exceeded.",
                            last_error=str(exc),
                        )
                    else:
                        logger.error(
                            f"Provider '{current_id}:{current_model}' failed during streaming: {exc}"
                        )
                    raise

                # 1. Attempt intra-provider model fallback first if allowed
                provider_attempts = sum(1 for p_id, _ in tried_configs if p_id == current_id)
                has_cross_candidates = self.settings.allow_cross_provider_fallback and any(
                    c not in tried_providers for c in self._get_fallback_candidates(current_id)
                )
                can_try_intra = self.settings.allow_intra_provider_fallback and (
                    provider_attempts < 2 or not has_cross_candidates
                )

                if can_try_intra:
                    intra_candidates = [
                        m
                        for m in self._get_intra_provider_candidates(current_id, current_model)
                        if (current_id, m) not in tried_configs
                    ]
                    if intra_candidates:
                        next_model = intra_candidates[0]
                        logger.warning(
                            f"Intra-provider stream fallback: switching model on '{current_id}' from '{current_model}' to '{next_model}' ({exc})"
                        )
                        self._notify_failover(
                            "failover_attempt",
                            original_provider=current_id,
                            original_model=current_model,
                            target_provider=current_id,
                            target_model=next_model,
                            reason=str(exc),
                        )
                        self._last_fallback_events.append(
                            FallbackEvent(
                                original_provider=f"{current_id}:{current_model}",
                                target_provider=f"{current_id}:{next_model}",
                                reason=str(exc),
                            )
                        )
                        current_model = next_model
                        tried_configs.append((current_id, current_model))
                        continue

                # 2. Attempt cross-provider fallback
                logger.warning(
                    f"Streaming provider '{current_id}:{current_model}' failed before tokens ({exc}). Evaluating cross-provider fallback..."
                )
                if not self.settings.allow_cross_provider_fallback:
                    self._notify_failover(
                        "failover_blocked",
                        reason="allow_cross_provider_fallback is disabled by user policy.",
                        original_provider=primary_id,
                    )
                    raise PrivacyViolationError(
                        f"Cross-provider fallback from '{primary_id}' is blocked by privacy settings "
                        "(allow_cross_provider_fallback is disabled).",
                        provider_id=primary_id,
                    ) from exc

                candidates = [
                    c for c in self._get_fallback_candidates(current_id) if c not in tried_providers
                ]
                if not candidates:
                    logger.error("No further fallback providers available for streaming.")
                    self._notify_failover(
                        "failover_exhausted",
                        reason="No further healthy fallback providers configured or available.",
                        last_error=str(exc),
                    )
                    raise

                next_provider_id = candidates[0]
                if not self.settings.allow_cross_provider_prompt_transfer:
                    self._notify_failover(
                        "failover_blocked",
                        reason="allow_cross_provider_prompt_transfer is disabled.",
                        target_provider=next_provider_id,
                    )
                    raise PrivacyViolationError(
                        f"Cross-provider prompt transfer from '{primary_id}' to '{next_provider_id}' "
                        "is blocked by privacy settings (allow_cross_provider_prompt_transfer is disabled).",
                        provider_id=next_provider_id,
                    ) from exc

                next_provider = self.registry.get_provider(next_provider_id)
                next_model = next_provider.default_model

                self._notify_failover(
                    "failover_attempt",
                    original_provider=current_id,
                    original_model=current_model,
                    target_provider=next_provider_id,
                    target_model=next_model,
                    reason=str(exc),
                )
                self._last_fallback_events.append(
                    FallbackEvent(
                        original_provider=f"{current_id}:{current_model}",
                        target_provider=f"{next_provider_id}:{next_model}",
                        reason=str(exc),
                    )
                )
                logger.info(
                    f"Stream auto-fallback: transferring from '{current_id}' to '{next_provider_id}'"
                )
                current_id = next_provider_id
                current_model = next_model
                tried_providers.append(current_id)
                tried_configs.append((current_id, current_model))
