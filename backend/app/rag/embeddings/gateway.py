"""Embedding gateway.

The only entry point to vector generation, and the counterpart to
`app/models/gateway.py`:

    indexer / retriever -> EmbeddingGateway -> EmbeddingProvider -> runtime

An unconfigured gateway is a normal, supported state, not an error. Lexical
retrieval carries the system on its own, so indexing and search continue
without vectors; they simply report that they are lexical-only. Nothing in
this system claims semantic search it did not perform.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.rag.embeddings.base import (
    EmbeddingNotConfiguredError,
    EmbeddingProvider,
)
from app.rag.embeddings.local import LocalEmbeddingProvider
from app.rag.embeddings.unavailable import UnavailableEmbeddingProvider

log = get_logger(__name__)


def build_embedding_provider(config: Settings) -> EmbeddingProvider:
    """Construct the provider named by EMBEDDING_PROVIDER.

    An unknown or half-configured provider degrades to
    `UnavailableEmbeddingProvider` rather than raising at import time - the
    same rule the model gateway follows.
    """
    choice = (config.embedding_provider or "none").strip().lower()

    if choice == "local":
        if not config.embedding_model:
            log.warning(
                "EMBEDDING_PROVIDER=local but EMBEDDING_MODEL is not set. "
                "Semantic retrieval is disabled; lexical retrieval still works."
            )
        return LocalEmbeddingProvider(
            model=config.embedding_model,
            base_url=config.embedding_base_url,
            timeout=config.embedding_timeout_seconds,
            batch_size=config.embedding_batch_size,
        )

    if choice not in ("none", ""):
        log.warning(
            "Unknown EMBEDDING_PROVIDER '%s'; semantic retrieval disabled.", choice
        )

    return UnavailableEmbeddingProvider()


class EmbeddingGateway:
    def __init__(self, provider: EmbeddingProvider):
        self.provider = provider

    # --- introspection -------------------------------------------------
    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str:
        return self.provider.model

    @property
    def is_configured(self) -> bool:
        return self.provider.configured

    @property
    def is_on_premise(self) -> bool:
        return self.provider.on_premise

    def describe(self) -> dict[str, object]:
        return self.provider.describe()

    # --- embedding -----------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        self._guard()
        return self.provider.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        self._guard()
        return self.provider.embed_query(text)

    def _guard(self) -> None:
        if not self.is_configured:
            raise EmbeddingNotConfiguredError(
                "No embedding provider is configured. Set EMBEDDING_PROVIDER "
                "and EMBEDDING_MODEL in .env, then restart the API. Lexical "
                "retrieval works without one.",
                provider=self.provider_name,
            )


@lru_cache
def get_embedding_gateway() -> EmbeddingGateway:
    return EmbeddingGateway(build_embedding_provider(settings))


def reset_embedding_gateway() -> None:
    """Drop the cached gateway. Used by tests and after a config change."""
    get_embedding_gateway.cache_clear()


__all__ = [
    "EmbeddingGateway",
    "build_embedding_provider",
    "get_embedding_gateway",
    "reset_embedding_gateway",
]
