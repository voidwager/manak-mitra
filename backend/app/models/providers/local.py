"""Local provider - the on-premise target.

Points at an inference runtime running inside the operator's own network:
Ollama, vLLM, llama.cpp, LM Studio or TGI. All of them expose the same
OpenAI-compatible API, so this is the same implementation as the prototype
provider with a different base URL and no external credentials.

Configuration (see .env.example):
    MODEL_PROVIDER=local
    LOCAL_MODEL_BASE_URL=http://localhost:11434/v1     # Ollama default
    MODEL_NAME=...

This is the provider that makes the sovereignty claim true: with it active,
no request leaves the network.
"""

from app.models.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class LocalProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: float = 120.0,
        default_temperature: float = 0.2,
        default_max_tokens: int = 1024,
    ):
        super().__init__(
            name="local",
            base_url=base_url,
            model=model,
            # Most local runtimes ignore auth entirely.
            api_key=api_key,
            # Local inference on modest hardware is slower than a hosted
            # accelerator, so the default timeout is more generous.
            timeout=timeout,
            on_premise=True,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
        )
