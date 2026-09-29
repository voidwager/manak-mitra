"""Model provider interface.

This is the seam that keeps the application independent of any particular
inference vendor. Nothing above this module may import a provider directly,
reference a vendor name, or know where inference happens. Everything talks
to `ModelProvider`.

(Note: `app/models/` is the *inference* layer. Database tables live in
`app/database/models/`.)
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str

    #: Set on an assistant turn that requested tools, so the follow-up call
    #: can replay the exchange. Every OpenAI-compatible runtime requires the
    #: original request to be present before its results.
    tool_calls: list[dict] | None = None

    #: Set on a `tool` message, linking the result back to the call.
    tool_call_id: str | None = None
    name: str | None = None

    #: Images attached to this turn, as `data:` URLs. When present the
    #: content is sent as OpenAI content parts rather than a bare string,
    #: which is the wire format every multimodal runtime accepts.
    #:
    #: Only ever set for a turn routed to a vision-capable model - see
    #: `app.models.router`. Sending parts to a text-only model produces a
    #: confusing failure rather than a clear one.
    images: tuple[str, ...] = ()

    def as_wire(self) -> dict[str, object]:
        wire: dict[str, object] = {"role": self.role, "content": self.content}

        if self.images:
            parts: list[dict[str, object]] = []
            if self.content:
                parts.append({"type": "text", "text": self.content})
            for image in self.images:
                parts.append({"type": "image_url", "image_url": {"url": image}})
            wire["content"] = parts

        if self.tool_calls:
            wire["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            wire["tool_call_id"] = self.tool_call_id
        if self.name:
            wire["name"] = self.name
        return wire


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class Completion:
    """A finished model response."""

    text: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)

    #: Tools the model asked to run, in the provider's wire shape. Present
    #: only when the caller offered tools and the model chose to use them.
    #: A request, never an action - the server decides what actually runs.
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Errors
#
# Providers raise these, never raw HTTP or vendor SDK exceptions, so callers
# can handle failure without knowing which provider is behind the gateway.
# ---------------------------------------------------------------------------
class ModelError(Exception):
    """Base class for every inference failure."""

    #: Suggested HTTP status when this surfaces through the API.
    http_status = 502

    def __init__(self, message: str, *, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class ModelNotConfiguredError(ModelError):
    """No inference provider is configured (MODEL_PROVIDER=none)."""

    http_status = 503


class ModelUnavailableError(ModelError):
    """The provider could not be reached, or returned a server error."""

    http_status = 503


class ModelTimeoutError(ModelError):
    """The provider did not respond within the configured timeout."""

    http_status = 504


class ModelRateLimitError(ModelError):
    """The provider rejected the request for rate/quota reasons."""

    http_status = 429


class ModelAuthError(ModelError):
    """Credentials missing, invalid, or lacking permission."""

    http_status = 502  # deliberately not 401: this is our problem, not the user's


class ModelResponseError(ModelError):
    """The provider replied with something we could not parse."""

    http_status = 502


class ModelProvider(ABC):
    """One way of running a model.

    Implementations must map every transport and vendor error onto the
    `ModelError` hierarchy above.
    """

    #: Short identifier reported by /api/health, e.g. "groq" or "local".
    name: str = "unknown"

    #: True when inference can actually be attempted right now.
    configured: bool = False

    #: Whether the model runs inside the operator's own infrastructure.
    #: Drives the honesty reporting - never hard-code this to True.
    on_premise: bool = False

    def __init__(self, model: str):
        self.model = model

    #: Whether this provider can accept tool definitions. Reported, not
    #: assumed: a runtime that ignores `tools` would silently answer without
    #: calling anything, which looks like the tool failing.
    supports_tools: bool = False

    #: Input modalities the active model accepts, e.g. {"text", "image"}.
    #: Drives honest capability reporting - see app/services/agents.py.
    modalities: frozenset[str] = frozenset({"text"})

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> Completion:
        """Return a full response, optionally offering `tools`.

        `model` overrides the provider's configured model for this call
        only - that is how routing selects between models without needing a
        provider instance per model.

        `tool_choice` is "auto" normally, or "none" to present the schemas
        while forbidding a call - see the provider for why removing the
        schemas instead is not equivalent.
        """

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        """Yield response text incrementally."""

    def list_models(self) -> list[str]:
        """Model identifiers this provider can serve.

        Optional: providers that cannot enumerate return an empty list.
        """
        return []

    def describe(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "model": self.model,
            "configured": self.configured,
            "onPremise": self.on_premise,
            "supportsTools": self.supports_tools,
            "modalities": sorted(self.modalities),
        }
