"""Every configured provider, and resolving a route to one of them.

Until now the gateway bound a single provider and routing chose a model
within it. Running Groq and Gemini together needs one more step: a route has
to name a *vendor* as well as a model.

A configured model id may therefore be provider-qualified:

    qwen/qwen3.8-27b          the default provider
    gemini:gemini-2.5-flash   explicitly Gemini
    groq:qwen/qwen3.8-27b     explicitly Groq

The prefix is optional, so every existing configuration keeps working. It
uses `:` rather than `/` because model ids contain slashes
(`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`) and a separator that appears
inside the value it separates is a bug waiting to happen.

This is still inside the gateway seam. Nothing above it names a vendor;
callers ask for a role and get a provider back.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.models.base import ModelProvider
from app.models.providers import (
    GeminiProvider,
    GroqProvider,
    LocalProvider,
    UnavailableProvider,
)

log = get_logger(__name__)

#: Separates a provider from a model id.
QUALIFIER = ":"


@dataclass(frozen=True)
class Qualified:
    """A model id split into the vendor that serves it and the id itself."""

    provider: str | None
    model: str

    @property
    def qualified(self) -> str:
        return f"{self.provider}{QUALIFIER}{self.model}" if self.provider else self.model


def split_model(value: str) -> Qualified:
    """Split `provider:model`, tolerating an unqualified id."""
    value = (value or "").strip()
    if not value:
        return Qualified(provider=None, model="")

    provider, separator, model = value.partition(QUALIFIER)
    if not separator:
        return Qualified(provider=None, model=value)

    provider = provider.strip().lower()
    if provider not in KNOWN_PROVIDERS:
        # Not a qualifier - probably part of the id itself. Treat the whole
        # string as a model rather than silently dropping half of it.
        return Qualified(provider=None, model=value)
    return Qualified(provider=provider, model=model.strip())


KNOWN_PROVIDERS = {"groq", "gemini", "local"}


def _build(name: str, config: Settings) -> ModelProvider | None:
    """Construct one provider, or None when it is not configured."""
    if name == "groq":
        if not config.groq_api_key:
            return None
        return GroqProvider(
            api_key=config.groq_api_key,
            model=config.model_name,
            base_url=config.groq_base_url,
            timeout=config.model_timeout_seconds,
            default_temperature=config.model_temperature,
            default_max_tokens=config.model_max_tokens,
        )

    if name == "gemini":
        if not config.gemini_api_key:
            return None
        return GeminiProvider(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
            base_url=config.gemini_base_url,
            timeout=config.model_timeout_seconds,
            default_temperature=config.model_temperature,
            default_max_tokens=config.model_max_tokens,
        )

    if name == "local":
        return LocalProvider(
            model=config.model_name,
            base_url=config.local_model_base_url,
            timeout=max(config.model_timeout_seconds, 120.0),
            default_temperature=config.model_temperature,
            default_max_tokens=config.model_max_tokens,
        )

    return None


class ProviderRegistry:
    """The providers this deployment can reach.

    Built once from configuration. A provider with no credentials is simply
    absent rather than present-and-broken, so "is Gemini available" is a
    membership test rather than a guess.
    """

    def __init__(self, config: Settings):
        self._config = config
        self._providers: dict[str, ModelProvider] = {}

        for name in sorted(KNOWN_PROVIDERS):
            built = _build(name, config)
            if built is not None:
                self._providers[name] = built

        #: Which provider serves a route that names none. This is the
        #: existing MODEL_PROVIDER setting, so nothing changes for a
        #: single-vendor deployment.
        self.default_name = (config.model_provider or "none").strip().lower()

        if self.default_name in ("none", ""):
            self._default: ModelProvider = UnavailableProvider()
        elif self.default_name in self._providers:
            self._default = self._providers[self.default_name]
        else:
            log.warning(
                "MODEL_PROVIDER=%s but it is not configured; inference disabled.",
                self.default_name,
            )
            self._default = UnavailableProvider()

    @property
    def default(self) -> ModelProvider:
        return self._default

    @property
    def names(self) -> list[str]:
        return sorted(self._providers)

    def has(self, name: str) -> bool:
        return name in self._providers

    def get(self, name: str | None) -> ModelProvider:
        """The named provider, or the default when it is absent.

        Falling back rather than failing is deliberate: a route pointing at
        a vendor whose key is missing should degrade to something that
        works and say so, not take down every turn that touches it.
        """
        if not name:
            return self._default
        provider = self._providers.get(name)
        if provider is None:
            log.warning(
                "Route names provider '%s', which is not configured; using %s.",
                name,
                self.default_name,
            )
            return self._default
        return provider

    def resolve(self, model: str | None) -> tuple[ModelProvider, str]:
        """Turn a possibly-qualified model id into (provider, bare model).

        The returned model is always unqualified, because that is what goes
        on the wire - a provider must never be sent `gemini:` as part of a
        model name.
        """
        parsed = split_model(model or "")
        provider = self.get(parsed.provider)
        return provider, (parsed.model or provider.model)


@lru_cache
def get_registry() -> ProviderRegistry:
    return ProviderRegistry(settings)


def reset_registry() -> None:
    """Drop the cached registry. Used by tests and after a config change."""
    get_registry.cache_clear()


__all__ = [
    "KNOWN_PROVIDERS",
    "ProviderRegistry",
    "Qualified",
    "get_registry",
    "reset_registry",
    "split_model",
]
