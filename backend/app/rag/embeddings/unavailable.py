"""Null embedding provider, used when EMBEDDING_PROVIDER=none.

Keeps the gateway total: callers always get a provider object. This is not
an error state - it is the default one. Retrieval falls back to lexical
BM25, which needs no model at all, and reports itself as lexical-only.
"""

from app.rag.embeddings.base import EmbeddingNotConfiguredError, EmbeddingProvider

MESSAGE = (
    "No embedding provider is configured, so semantic retrieval is off. "
    "Lexical (BM25) retrieval still works. To enable semantic search set "
    "EMBEDDING_PROVIDER=local and EMBEDDING_MODEL in .env, then restart."
)


class UnavailableEmbeddingProvider(EmbeddingProvider):
    name = "none"
    configured = False
    on_premise = False

    def __init__(self, model: str = ""):
        super().__init__(model=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingNotConfiguredError(MESSAGE, provider=self.name)
