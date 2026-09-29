"""Embedding layer.

`base` defines the provider interface, `gateway` is the single entry point,
and the concrete providers sit alongside. Nothing outside this package may
import a provider directly.
"""

from app.rag.embeddings.base import (
    EmbeddingError,
    EmbeddingNotConfiguredError,
    EmbeddingProvider,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app.rag.embeddings.gateway import (
    EmbeddingGateway,
    build_embedding_provider,
    get_embedding_gateway,
    reset_embedding_gateway,
)
from app.rag.embeddings.local import LocalEmbeddingProvider
from app.rag.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.rag.embeddings.unavailable import UnavailableEmbeddingProvider

__all__ = [
    "EmbeddingError",
    "EmbeddingGateway",
    "EmbeddingNotConfiguredError",
    "EmbeddingProvider",
    "EmbeddingResponseError",
    "EmbeddingTimeoutError",
    "EmbeddingUnavailableError",
    "LocalEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "UnavailableEmbeddingProvider",
    "build_embedding_provider",
    "get_embedding_gateway",
    "reset_embedding_gateway",
]
