"""Groq provider - PROTOTYPE INFERENCE ONLY.

Groq is an external, third-party inference service. While this provider is
active the system is NOT sovereign and NOT on-premise, and must not describe
itself as either. `on_premise` is False and /api/health reports it.

It is used because it serves open-weight models over an OpenAI-compatible
API. That matters: the same model family runs on-premise later, so moving
to local inference changes where the model runs, not which model runs.

Configuration (see .env.example):
    MODEL_PROVIDER=groq
    GROQ_API_KEY=...        # never hard-coded, never committed
    MODEL_NAME=...          # check GET /api/models for the live catalogue
"""

from app.models.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAICompatibleProvider):
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
            name="groq",
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            # External service. Never set this True.
            on_premise=False,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
        )
