"""Extensible embedding interface and providers for JARVIS memory subsystem.

Supports:
- GeminiEmbeddingProvider (google-genai)
- OpenAIEmbeddingProvider (openai)
- LocalSemanticEmbeddingProvider (zero-dependency deterministic L2-normalized vector space)
- NoOpEmbeddingProvider (disabled/baseline fallback)
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from infrastructure.logging import get_logger

if TYPE_CHECKING:
    from config import Settings

logger = get_logger("memory.embeddings")


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2, strict=False):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class BaseEmbeddingProvider(ABC):
    """Abstract interface for generating vector embeddings."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True if the embedding provider is configured and operational."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the embedding model."""
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""
        raise NotImplementedError

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate vector embedding for a single text string."""
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a batch of text strings."""
        raise NotImplementedError

    def get_embedding(self, text: str) -> list[float]:
        """Convenience alias for embed_text."""
        return self.embed_text(text)

    def cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        return cosine_similarity(v1, v2)

    @property
    def is_neural(self) -> bool:
        """True if provider employs deep neural network / transformer weights."""
        return False

    @property
    def vector_technique(self) -> str:
        """Categorical vectorization algorithm utilized."""
        return "none"


class NoOpEmbeddingProvider(BaseEmbeddingProvider):
    """Default baseline embedding provider that performs no operations."""

    @property
    def is_available(self) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "noop"

    @property
    def model_name(self) -> str:
        return "none"

    @property
    def dimension(self) -> int:
        return 0

    def embed_text(self, text: str) -> list[float]:
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class LocalSemanticEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic local subword feature hashing vectorizer (non-neural).

    Produces reproducible L2-normalized unit vectors of fixed dimension using
    MD5-hashed subword tokens and n-grams without external APIs or model weights.
    Accurately characterized as an offline subword hash vectorizer, not neural.
    """

    def __init__(self, dimension: int = 128) -> None:
        self._dim = dimension

    @property
    def is_available(self) -> bool:
        return True

    @property
    def is_neural(self) -> bool:
        return False

    @property
    def vector_technique(self) -> str:
        return "subword_feature_hashing"

    @property
    def provider_name(self) -> str:
        return "local_semantic"

    @property
    def model_name(self) -> str:
        return f"deterministic-hash-{self._dim}d"

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self._dim

        vec = [0.0] * self._dim
        clean = text.lower().strip()

        # 1. Word tokens
        words = re.findall(r"\w+", clean)
        for w in words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += 1.5 * sign

        # 2. Word pairs / bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]}_{words[i + 1]}"
            h = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += 2.0 * sign

        # 3. Character trigrams for Persian morphological & subword matching
        for i in range(len(clean) - 2):
            trigram = clean[i : i + 3]
            h = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += 0.5 * sign

        # L2 normalization
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


# Alias for truthful nomenclature
LocalSubwordHashEmbeddingProvider = LocalSemanticEmbeddingProvider


class LocalNeuralEmbeddingProvider(BaseEmbeddingProvider):
    """Local neural transformer embedding provider using sentence-transformers / ONNX.

    Truthfully reports availability: if local neural runtime packages or model weights
    are missing, it reports is_available=False and provides honest diagnostics,
    never claiming neural capability when only subword hashing is present.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
    ) -> None:
        self._model_name = model_name
        self._dim = dimension
        self._model: Any = None
        self._init_error: str | None = None
        self._attempt_init()

    def _attempt_init(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension() or self._dim)
        except ImportError:
            self._init_error = "sentence-transformers package not installed in environment"
        except Exception as exc:
            self._init_error = f"Failed to load neural model '{self._model_name}': {exc}"

    @property
    def is_available(self) -> bool:
        return self._model is not None

    @property
    def is_neural(self) -> bool:
        return True

    @property
    def vector_technique(self) -> str:
        return "neural_transformer"

    @property
    def provider_name(self) -> str:
        return "local_neural"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def status_reason(self) -> str:
        if self._model is not None:
            return "Local neural transformer operational"
        return self._init_error or "Neural runtime unavailable"

    def embed_text(self, text: str) -> list[float]:
        if not self.is_available:
            raise RuntimeError(f"LocalNeuralEmbeddingProvider is unavailable: {self.status_reason}")
        if not text or not text.strip():
            return [0.0] * self._dim
        vec = self._model.encode(text, convert_to_numpy=True).tolist()
        return [float(x) for x in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.is_available:
            raise RuntimeError(f"LocalNeuralEmbeddingProvider is unavailable: {self.status_reason}")
        if not texts:
            return []
        vecs = self._model.encode(texts, convert_to_numpy=True).tolist()
        return [[float(x) for x in v] for v in vecs]


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini embedding provider using google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-004",
        dimension: int = 768,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model
        self._dim = dimension
        self._client: Any = None
        if self._api_key:
            try:
                import google.genai as genai

                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.debug(f"Failed to initialize google-genai client: {exc}")

    @property
    def is_available(self) -> bool:
        return bool(self._client and self._api_key)

    @property
    def is_neural(self) -> bool:
        return True

    @property
    def vector_technique(self) -> str:
        return "gemini_api_neural"

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        if not self.is_available:
            return []
        try:
            res = self._client.models.embed_content(
                model=self._model,
                contents=text,
            )
            if hasattr(res, "embedding") and hasattr(res.embedding, "values"):
                vals = list(res.embedding.values)
                self._dim = len(vals)
                return vals
            if hasattr(res, "embeddings") and res.embeddings:
                vals = list(res.embeddings[0].values)
                self._dim = len(vals)
                return vals
        except Exception as exc:
            logger.warning(f"Gemini embed_text failed: {exc}")
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.is_available or not texts:
            return [[] for _ in texts]
        results: list[list[float]] = []
        for t in texts:
            results.append(self.embed_text(t))
        return results


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider using official openai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model = model
        self._dim = dimension
        self._client: Any = None
        if self._api_key:
            try:
                import openai

                self._client = openai.OpenAI(api_key=self._api_key)
            except Exception as exc:
                logger.debug(f"Failed to initialize openai client: {exc}")

    @property
    def is_available(self) -> bool:
        return bool(self._client and self._api_key)

    @property
    def is_neural(self) -> bool:
        return True

    @property
    def vector_technique(self) -> str:
        return "openai_api_neural"

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        if not self.is_available:
            return []
        try:
            res = self._client.embeddings.create(
                model=self._model,
                input=text,
            )
            if res.data and len(res.data) > 0:
                vals = list(res.data[0].embedding)
                self._dim = len(vals)
                return vals
        except Exception as exc:
            logger.warning(f"OpenAI embed_text failed: {exc}")
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.is_available or not texts:
            return [[] for _ in texts]
        try:
            res = self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
            return [list(item.embedding) for item in res.data]
        except Exception as exc:
            logger.warning(f"OpenAI embed_batch failed: {exc}")
            return [self.embed_text(t) for t in texts]


def get_embedding_provider(settings: Settings | None = None) -> BaseEmbeddingProvider:
    """Factory creating configured embedding provider with honest availability."""
    from config import get_settings

    cfg = settings or get_settings()

    provider_choice = getattr(cfg, "memory_embedding_provider", "local").lower()
    enabled = getattr(cfg, "memory_embedding_enabled", True)

    if not enabled or provider_choice == "noop":
        return NoOpEmbeddingProvider()

    if provider_choice == "gemini":
        gemini_key = getattr(cfg, "gemini_api_key", None)
        key_str = gemini_key.get_secret_value() if gemini_key else os.getenv("GEMINI_API_KEY", "")
        prov = GeminiEmbeddingProvider(api_key=key_str)
        if prov.is_available:
            return prov
        logger.info("Gemini embedding not configured with valid key, using local fallback.")
        return LocalSemanticEmbeddingProvider()

    if provider_choice == "openai":
        openai_key = getattr(cfg, "openai_api_key", None)
        key_str = openai_key.get_secret_value() if openai_key else os.getenv("OPENAI_API_KEY", "")
        prov = OpenAIEmbeddingProvider(api_key=key_str)
        if prov.is_available:
            return prov
        logger.info("OpenAI embedding not configured with valid key, using local fallback.")
        return LocalSemanticEmbeddingProvider()

    if provider_choice in ("local_neural", "neural"):
        neural_prov = LocalNeuralEmbeddingProvider()
        if neural_prov.is_available:
            return neural_prov
        logger.info(
            f"Local neural provider unavailable ({neural_prov.status_reason}); falling back honestly to deterministic subword hash provider."
        )
        return LocalSemanticEmbeddingProvider()

    if provider_choice in ("local", "auto", "hash", "subword_hash"):
        return LocalSemanticEmbeddingProvider()

    return LocalSemanticEmbeddingProvider()
