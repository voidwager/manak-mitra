"""Google Gemini, through its OpenAI-compatible endpoint.

Google publishes an OpenAI-shaped surface at
`https://generativelanguage.googleapis.com/v1beta/openai/`, which speaks the
same `/chat/completions` and `/models` the rest of this project already
talks. So Gemini needs no bespoke client, no `google-generativeai`
dependency, and no second code path for tool calls or image parts - it is
the same implementation with a different base URL and key.

That is the gateway seam paying for itself: adding a second vendor is a
provider subclass, not a change to anything above it.

Why it is worth having alongside Groq:

  - Separate rate limit. Groq's free tier is 8000 tokens/minute, and a
    tool-heavy turn burns that quickly. Splitting work across two vendors
    means one running out does not stop the other.
  - Long context. Gemini's Flash models take far more input than the
    catalogue Groq serves, which matters for document work where the whole
    point is putting retrieved passages in front of the model.

Note the honest consequence: with Gemini active, inference leaves the
network exactly as it does with Groq. `on_premise` is False for both, and
/api/health reports it.
"""

from app.models.providers.openai_compatible import OpenAICompatibleProvider

#: Google's OpenAI-compatible surface. The trailing path matters - the plain
#: v1beta root speaks Google's own protocol, not this one.
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


class GeminiProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        default_temperature: float = 0.2,
        default_max_tokens: int = 1024,
    ):
        super().__init__(
            name="gemini",
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            # Hosted, so inference leaves the network. Never assert
            # otherwise: /api/health reads this to make the sovereignty
            # claim, and the claim has to stay false while it is false.
            on_premise=False,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
        )

    @property
    def modalities(self) -> frozenset[str]:
        """Gemini's catalogue does not publish modality metadata.

        The OpenAI-compatible `/models` listing returns ids and little else,
        so the discovery that works for Groq finds nothing here. Rather than
        report "text only" - which would make the workbench refuse to send
        an image to a model that handles them perfectly well - every current
        Gemini chat model is treated as multimodal, which they are.

        Stated as an assumption because it is one. If Google ships a
        text-only Gemini chat model, this becomes wrong and the fix is to
        list it below rather than to guess harder.
        """
        if self._looks_like_embedding_model(self.model):
            return frozenset({"text"})
        return frozenset({"text", "image"})

    def modalities_for(self, model: str | None = None) -> frozenset[str]:
        target = model or self.model
        if self._looks_like_embedding_model(target):
            return frozenset({"text"})
        return frozenset({"text", "image"})

    @staticmethod
    def _looks_like_embedding_model(model: str) -> bool:
        return "embedding" in (model or "").lower()

    @property
    def supports_tools(self) -> bool:
        """Gemini supports function calling on its chat models.

        Same situation as modalities: the compatible endpoint publishes no
        feature list, so this is a statement about the vendor rather than a
        discovery. A runtime that ignored `tools` would simply answer
        without calling one, which degrades rather than breaks.
        """
        return not self._looks_like_embedding_model(self.model)
