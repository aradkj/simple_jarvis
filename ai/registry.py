"""Central registry for discovering, registering, and instantiating AI providers."""

from collections.abc import Callable

from ai.base import BaseAIProvider, ModelCapabilities, ModelInfo, UnknownProviderError
from ai.catalog import ModelCatalog
from config import Settings, get_settings
from infrastructure.logging import get_logger

logger = get_logger("ai.registry")


class ProviderRegistrationError(Exception):
    """Raised when registering an invalid or duplicate provider."""


class ProviderRegistry:
    """Central registry managing AI provider implementations and lifecycles."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._provider_factories: dict[str, Callable[[Settings], BaseAIProvider]] = {}
        self._instantiated_providers: dict[str, BaseAIProvider] = {}

    def register_factory(
        self,
        provider_id: str,
        factory: Callable[[Settings], BaseAIProvider],
        overwrite: bool = False,
    ) -> None:
        """Register a provider factory under a unique provider_id."""
        pid = provider_id.lower().strip()
        if not overwrite and pid in self._provider_factories:
            raise ProviderRegistrationError(f"Provider '{pid}' is already registered.")

        self._provider_factories[pid] = factory
        # Clear any cached instance for this provider
        self._instantiated_providers.pop(pid, None)
        logger.debug(f"Registered AI provider factory for: {pid}")

    def register(self, provider_id: str, provider: BaseAIProvider) -> None:
        """Register an instantiated provider directly."""
        pid = provider_id.lower().strip()
        self._provider_factories[pid] = lambda _: provider
        self._instantiated_providers[pid] = provider
        logger.debug(f"Registered AI provider instance for: {pid}")

    def unregister(self, provider_id: str) -> None:
        """Unregister a provider."""
        pid = provider_id.lower().strip()
        if pid not in self._provider_factories:
            raise UnknownProviderError(f"Provider '{pid}' is not registered.")
        del self._provider_factories[pid]
        self._instantiated_providers.pop(pid, None)
        logger.debug(f"Unregistered AI provider: {pid}")

    def list_registered_ids(self) -> list[str]:
        """Return all registered provider identifiers."""
        return list(self._provider_factories.keys())

    def has_provider(self, provider_id: str) -> bool:
        """Check whether a provider identifier is registered."""
        pid = provider_id.lower().strip().replace("google-", "")
        return pid in self._provider_factories

    def is_provider_configured(self, provider_id: str) -> bool:
        """Check if the provider has necessary API credentials configured."""
        pid = provider_id.lower().strip().replace("google-", "")
        if pid in self._instantiated_providers:
            return self._instantiated_providers[pid].is_ready()
        if self.settings.is_provider_configured(pid):
            return True
        if pid in self._provider_factories:
            instance = self.get_provider(pid)
            return instance.is_ready()
        return False

    def is_provider_enabled(self, provider_id: str) -> bool:
        """Check if provider is enabled in configuration."""
        pid = provider_id.lower().strip().replace("google-", "")
        return self.settings.is_provider_enabled(pid)

    def get_provider(self, provider_id: str) -> BaseAIProvider:
        """Obtain a singleton provider instance for the specified identifier."""
        pid = provider_id.lower().strip().replace("google-", "")
        if pid in self._instantiated_providers:
            return self._instantiated_providers[pid]

        if pid not in self._provider_factories:
            raise UnknownProviderError(
                f"Unknown or unregistered provider: '{provider_id}'.", provider_id=pid
            )

        factory = self._provider_factories[pid]
        instance = factory(self.settings)
        self._instantiated_providers[pid] = instance
        return instance

    def list_available_providers(self) -> list[str]:
        """Return provider IDs that are both registered, enabled, and configured."""
        available: list[str] = []
        for pid in self._provider_factories:
            if self.is_provider_enabled(pid) and self.is_provider_configured(pid):
                available.append(pid)
        return available

    def get_model_capabilities(self, provider_id: str, model_id: str) -> ModelCapabilities:
        """Query capabilities for a model from catalog or provider instance."""
        return ModelCatalog.get_capabilities(provider_id, model_id)

    def list_models_for_provider(self, provider_id: str) -> list[ModelInfo]:
        """Return model metadata for specified provider."""
        return ModelCatalog.list_models(provider_id)


def create_default_registry(settings: Settings | None = None) -> ProviderRegistry:
    """Create and populate a ProviderRegistry with all built-in providers."""
    s = settings or get_settings()
    registry = ProviderRegistry(settings=s)

    from ai.providers.anthropic import AnthropicProvider
    from ai.providers.deepseek import DeepSeekProvider
    from ai.providers.gemini import GeminiProvider
    from ai.providers.groq import GroqProvider
    from ai.providers.openai import OpenAIProvider
    from ai.providers.openrouter import OpenRouterProvider

    registry.register_factory("gemini", lambda cfg: GeminiProvider(settings=cfg))
    registry.register_factory("openai", lambda cfg: OpenAIProvider(settings=cfg))
    registry.register_factory("anthropic", lambda cfg: AnthropicProvider(settings=cfg))
    registry.register_factory("deepseek", lambda cfg: DeepSeekProvider(settings=cfg))
    registry.register_factory("openrouter", lambda cfg: OpenRouterProvider(settings=cfg))
    registry.register_factory("groq", lambda cfg: GroqProvider(settings=cfg))

    return registry
