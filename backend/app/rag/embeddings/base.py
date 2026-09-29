"""Embedding provider interface.

The same seam as `app/models/base.py`, for the same reason: nothing above
this module may name an embedding vendor or know where vectors are computed.
Retrieval asks the gateway for vectors and is told, honestly, whether it got
any.

Errors map onto a typed hierarchy so a failing embedder degrades retrieval
to lexical-only instead of taking down indexing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingError(Exception):
    """Base class for every embedding failure."""

    http_status = 502

    def __init__(self, message: str, *, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class EmbeddingNotConfiguredError(EmbeddingError):
    """No embedding provider is configured (EMBEDDING_PROVIDER=none)."""

    http_status = 503


class EmbeddingUnavailableError(EmbeddingError):
    """The endpoint could not be reached, or returned a server error."""

    http_status = 503


class EmbeddingTimeoutError(EmbeddingError):
    """The endpoint did not respond within the configured timeout."""

    http_status = 504


class EmbeddingResponseError(EmbeddingError):
    """The endpoint replied with something we could not parse."""

    http_status = 502


class EmbeddingProvider(ABC):
    """One way of turning text into vectors."""

    #: Short identifier reported by /api/health, e.g. "local".
    name: str = "unknown"

    #: True when embedding can actually be attempted right now.
    configured: bool = False

    #: Whether vectors are computed inside the operator's own network.
    #: Derived from the active provider - never hard-coded to True.
    on_premise: bool = False

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of passages. Order of the result matches the input."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query.

        Separate from `embed` because asymmetric models (bge, e5, nomic)
        want a different prefix on the query side. Providers that need one
        override this; the default treats both sides identically.
        """
        vectors = self.embed([text])
        if not vectors:
            raise EmbeddingResponseError(
                "The embedding endpoint returned no vector for the query.",
                provider=self.name,
            )
        return vectors[0]

    def describe(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "model": self.model,
            "configured": self.configured,
            "onPremise": self.on_premise,
        }


__all__ = [
    "EmbeddingError",
    "EmbeddingNotConfiguredError",
    "EmbeddingProvider",
    "EmbeddingResponseError",
    "EmbeddingTimeoutError",
    "EmbeddingUnavailableError",
]
