"""Provider for any OpenAI-compatible /embeddings endpoint.

One class covers every runtime worth deploying on-premise - Ollama, vLLM,
Text Embeddings Inference, Infinity, LM Studio - because they all serve the
same wire format:

    POST {base_url}/embeddings   {"model": ..., "input": [...]}
    -> {"data": [{"index": 0, "embedding": [...]}, ...]}

So choosing a different embedding runtime is a base-URL change, exactly as
it is for chat completions. This mirrors
`app/models/providers/openai_compatible.py` rather than sharing code with
it: the two endpoints have different payloads, different failure modes and
different batching rules, and collapsing them would couple the retrieval
layer to the chat layer for the sake of a dozen saved lines.
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.rag.embeddings.base import (
    EmbeddingProvider,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)

log = get_logger(__name__)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        on_premise: bool = False,
        batch_size: int = 16,
    ):
        super().__init__(model=model)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.timeout = timeout
        self.on_premise = on_premise
        self.batch_size = max(1, batch_size)

        # A local runtime usually needs no key; a hosted one does. Both need
        # a model name.
        self.configured = bool(self.model) and (self.on_premise or bool(self.api_key))

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        try:
            detail = response.json().get("error", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:  # noqa: BLE001
            message = (response.text or "")[:300]

        message = message or f"HTTP {response.status_code}"
        status = response.status_code

        if status in (401, 403):
            # Never echo the endpoint's auth text back; it can carry key
            # fragments.
            log.error("Embedding auth rejected by %s: %s", self.name, message)
            raise EmbeddingUnavailableError(
                "The embedding endpoint rejected our credentials. Check the "
                "server configuration.",
                provider=self.name,
            )
        if status == 404:
            raise EmbeddingResponseError(
                f"Embedding model '{self.model}' was not found on this "
                "endpoint. Check EMBEDDING_MODEL against what the runtime "
                "actually serves (for Ollama: `ollama list`).",
                provider=self.name,
            )
        if status >= 500:
            raise EmbeddingUnavailableError(
                f"The embedding endpoint returned an error: {message}",
                provider=self.name,
            )
        raise EmbeddingResponseError(
            f"The embedding endpoint rejected the request: {message}",
            provider=self.name,
        )

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": inputs}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise EmbeddingTimeoutError(
                f"The embedding endpoint did not respond within {self.timeout:.0f}s.",
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"Could not reach the embedding endpoint at {self.base_url}: {exc}",
                provider=self.name,
            ) from exc

        self._raise_for_status(response)

        try:
            body = response.json()
            rows = body["data"]
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingResponseError(
                "The embedding endpoint returned a response we could not parse.",
                provider=self.name,
            ) from exc

        # Order is documented but not guaranteed by every runtime, so sort
        # by the index the endpoint reports rather than trusting position.
        try:
            ordered = sorted(rows, key=lambda row: row.get("index", 0))
            vectors = [[float(v) for v in row["embedding"]] for row in ordered]
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingResponseError(
                "The embedding endpoint returned vectors in an unexpected shape.",
                provider=self.name,
            ) from exc

        if len(vectors) != len(inputs):
            raise EmbeddingResponseError(
                f"Asked for {len(inputs)} embeddings and got {len(vectors)}.",
                provider=self.name,
            )
        return vectors

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._post(batch))
        return vectors


__all__ = ["OpenAICompatibleEmbeddingProvider"]
