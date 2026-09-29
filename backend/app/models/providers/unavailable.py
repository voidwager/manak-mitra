"""Null provider used when MODEL_PROVIDER=none.

Keeps the gateway total: callers always get a provider object, and the
absence of inference is reported as a typed error rather than a crash or,
worse, a fabricated answer.
"""

from collections.abc import Iterator

from app.models.base import (
    ChatMessage,
    Completion,
    ModelNotConfiguredError,
    ModelProvider,
)

MESSAGE = (
    "No inference provider is configured. Set MODEL_PROVIDER and the matching "
    "credentials in .env, then restart the API."
)


class UnavailableProvider(ModelProvider):
    name = "none"
    configured = False
    on_premise = False

    def __init__(self, model: str = ""):
        super().__init__(model=model)

    def complete(self, messages: list[ChatMessage], **kwargs) -> Completion:
        raise ModelNotConfiguredError(MESSAGE, provider=self.name)

    def stream(self, messages: list[ChatMessage], **kwargs) -> Iterator[str]:
        raise ModelNotConfiguredError(MESSAGE, provider=self.name)
        yield  # pragma: no cover - unreachable, marks this a generator
