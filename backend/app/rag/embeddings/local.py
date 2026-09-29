"""Local embedding provider - the on-premise target.

Points at an embedding runtime inside the operator's own network. Ollama,
Text Embeddings Inference, vLLM and Infinity all serve the OpenAI
`/embeddings` shape, so this is the shared implementation with a different
base URL and no external credentials.

Configuration (see .env.example):
    EMBEDDING_PROVIDER=local
    EMBEDDING_BASE_URL=http://localhost:11434/v1     # Ollama default
    EMBEDDING_MODEL=...

With this active, document text never leaves the network - which matters
more for embeddings than for chat: indexing sends the *entire* corpus to
whatever endpoint is configured, not just the parts a user asks about.
"""

from app.rag.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class LocalEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: float = 120.0,
        batch_size: int = 16,
    ):
        super().__init__(
            name="local",
            base_url=base_url,
            model=model,
            # Most local runtimes ignore auth entirely.
            api_key=api_key,
            timeout=timeout,
            on_premise=True,
            batch_size=batch_size,
        )
