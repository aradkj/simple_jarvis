"""Extensible embedding interface for JARVIS memory subsystem.

Baseline implementation is zero-dependency and disabled by default.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract interface for generating vector embeddings."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True if the embedding provider is configured and available."""
        raise NotImplementedError

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate vector embedding for a single text string."""
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a batch of text strings."""
        raise NotImplementedError


class NoOpEmbeddingProvider(BaseEmbeddingProvider):
    """Default baseline embedding provider that performs no operations."""

    @property
    def is_available(self) -> bool:
        return False

    def embed_text(self, text: str) -> list[float]:
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]
