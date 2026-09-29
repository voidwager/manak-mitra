"""Model gateway.

The only entry point to inference. Application code calls the gateway; it
never constructs a provider, names a vendor, or knows whether the model runs
locally or remotely.

    chat_service -> ModelGateway -> ModelProvider -> (Groq | local runtime)

Switching to on-premise inference is a change to MODEL_PROVIDER in .env.
Nothing in `app/api`, `app/services` or the frontend changes.
"""

from collections.abc import Iterator
from functools import lru_cache

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.models.base import (
    ChatMessage,
    Completion,
    ModelNotConfiguredError,
    ModelProvider,
)
from app.models.providers import GroqProvider, LocalProvider, UnavailableProvider
from app.models.registry import get_registry

log = get_logger(__name__)


def build_provider(config: Settings) -> ModelProvider:
    """Construct the provider named by MODEL_PROVIDER.

    An unknown or misconfigured provider degrades to `UnavailableProvider`
    rather than raising at import time - a bad setting should surface as a
    clear message in /api/health, not a server that refuses to boot.
    """
    choice = (config.model_provider or "none").strip().lower()

    if choice == "groq":
        if not config.groq_api_key:
            log.warning("MODEL_PROVIDER=groq but GROQ_API_KEY is not set.")
            return UnavailableProvider(model=config.model_name)
        if not config.model_name:
            # Build it anyway. Listing models needs credentials, not a model
            # id - and requiring MODEL_NAME to discover MODEL_NAME would be a
            # dead end. `configured` stays False, so inference still refuses
            # with a clear error while GET /api/models works.
            log.warning(
                "MODEL_PROVIDER=groq but MODEL_NAME is not set. "
                "Inference is disabled; GET /api/models will list what is available."
            )
        return GroqProvider(
            api_key=config.groq_api_key,
            model=config.model_name,
            base_url=config.groq_base_url,
            timeout=config.model_timeout_seconds,
            default_temperature=config.model_temperature,
            default_max_tokens=config.model_max_tokens,
        )

    if choice == "local":
        if not config.model_name:
            log.warning(
                "MODEL_PROVIDER=local but MODEL_NAME is not set. "
                "Inference is disabled; GET /api/models will list what is available."
            )
        return LocalProvider(
            model=config.model_name,
            base_url=config.local_model_base_url,
            timeout=max(config.model_timeout_seconds, 120.0),
            default_temperature=config.model_temperature,
            default_max_tokens=config.model_max_tokens,
        )

    if choice not in ("none", ""):
        log.warning("Unknown MODEL_PROVIDER '%s'; inference disabled.", choice)

    return UnavailableProvider()


class ModelGateway:
    def __init__(self, provider: ModelProvider):
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
        """Whether inference can be attempted at all.

        True when the default provider is usable, or when any other vendor
        is configured - a deployment whose default is unset but which has a
        Gemini key can still serve every route that names Gemini.
        """
        if self.provider.configured:
            return True
        registry = get_registry()
        return any(registry.get(name).configured for name in registry.names)

    @property
    def is_on_premise(self) -> bool:
        """True only when inference runs inside the operator's network.

        Drives the honesty reporting in /api/health and the UI banner. It is
        derived from the active provider, never asserted.
        """
        return self.provider.on_premise

    @property
    def supports_tools(self) -> bool:
        """Whether the active model advertises function calling."""
        return bool(getattr(self.provider, "supports_tools", False))

    @property
    def modalities(self) -> frozenset[str]:
        """Input modalities the active model accepts. Discovered, not assumed."""
        return getattr(self.provider, "modalities", frozenset({"text"}))

    @property
    def supports_vision(self) -> bool:
        return "image" in self.modalities

    def _for(self, model: str | None) -> tuple[ModelProvider, str | None]:
        """The provider that serves `model`, and the id to send it.

        An unqualified model stays with this gateway's own provider, so a
        single-vendor deployment behaves exactly as it did before routing
        learned about vendors.
        """
        from app.models.registry import split_model

        parsed = split_model(model or "")
        if parsed.provider is None:
            return self.provider, (model or None)

        registry = get_registry()
        provider = registry.get(parsed.provider)
        return provider, (parsed.model or provider.model)

    def provider_for(self, model: str | None = None) -> str:
        """Which vendor serves `model`. Reported in the activity trace."""
        provider, _ = self._for(model)
        return provider.name

    def modalities_for(self, model: str | None = None) -> frozenset[str]:
        """Input modalities of a specific model, for routing decisions."""
        provider, resolved = self._for(model)
        probe = getattr(provider, "modalities_for", None)
        if probe is None:
            return getattr(provider, "modalities", frozenset({"text"}))
        return probe(resolved)

    def model_accepts_images(self, model: str | None = None) -> bool:
        """Whether `model` can be sent a picture.

        Asked before any image is attached to a request: sending one to a
        text-only model produces a confusing failure rather than a clear
        refusal, and the user would read it as the image being ignored.
        """
        return "image" in self.modalities_for(model)

    def describe(self) -> dict[str, object]:
        return self.provider.describe()

    def list_models(self) -> list[str]:
        return self.provider.list_models()

    # --- inference -----------------------------------------------------
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
        self._guard()
        log.info(
            "Inference request via %s (%s)", self.provider_name, model or self.model
        )
        # A route may name a vendor as well as a model, so the provider for
        # this call is not necessarily the default one.
        provider, resolved = self._for(model)

        # Offering tools to a model that does not support them wastes a
        # round trip and can confuse some runtimes, so the gateway drops
        # them rather than letting callers guess.
        if tools and not getattr(provider, "supports_tools", False):
            log.info("Provider %s does not support tools; omitting", provider.name)
            tools = None

        return provider.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            model=resolved,
        )

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self._guard()
        log.info(
            "Streaming request via %s (%s)", self.provider_name, model or self.model
        )
        provider, resolved = self._for(model)
        return provider.stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=resolved,
        )

    def _guard(self) -> None:
        if not self.is_configured:
            raise ModelNotConfiguredError(
                "No inference provider is configured. Set MODEL_PROVIDER and the "
                "matching credentials in .env, then restart the API.",
                provider=self.provider_name,
            )


@lru_cache
def get_gateway() -> ModelGateway:
    return ModelGateway(build_provider(settings))


def reset_gateway() -> None:
    """Drop the cached gateway. Used by tests and after a config change."""
    get_gateway.cache_clear()
