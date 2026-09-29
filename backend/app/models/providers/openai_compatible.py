"""Provider for any OpenAI-compatible /chat/completions endpoint.

This one class covers both the prototype and the on-premise target, because
Groq, vLLM, Ollama, llama.cpp, LM Studio and TGI all speak the same wire
format. Swapping hosted inference for a local runtime is therefore a change
of base URL and credentials, not a change of code.

That is the whole point of the gateway: the migration to on-premise
inference must be configuration, not a rewrite.
"""

import json
from collections.abc import Iterator

import httpx

from app.core.logging import get_logger
from app.models.base import (
    ChatMessage,
    Completion,
    ModelAuthError,
    ModelProvider,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    Usage,
)

log = get_logger(__name__)


class OpenAICompatibleProvider(ModelProvider):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        on_premise: bool = False,
        default_temperature: float = 0.2,
        default_max_tokens: int = 1024,
    ):
        super().__init__(model=model)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.timeout = timeout
        self.on_premise = on_premise
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

        # A local runtime usually needs no key; a hosted one does. Both need
        # a model name.
        self.configured = bool(self.model) and (self.on_premise or bool(self.api_key))

        # The provider catalogue, fetched once on first use. `None` means
        # "not asked yet"; the accessors below fall back to conservative
        # defaults when the endpoint publishes nothing useful.
        self._catalogue_cache: dict[str, dict] | None = None

    # ------------------------------------------------------------------
    # Capability discovery
    # ------------------------------------------------------------------
    def modalities_for(self, model: str | None = None) -> frozenset[str]:
        """Input modalities of `model`, or of the configured default."""
        entry = self._catalogue().get(model or self.model, {})
        reported = entry.get("input_modalities")
        if isinstance(reported, list) and reported:
            return frozenset(str(m).lower() for m in reported)
        return frozenset({"text"})

    def _catalogue(self) -> dict[str, dict]:
        """The whole provider catalogue, keyed by model id. Cached."""
        if self._catalogue_cache is not None:
            return self._catalogue_cache

        self._catalogue_cache = {}
        try:
            with httpx.Client(timeout=min(self.timeout, 15.0)) as client:
                response = client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
            if response.is_success:
                self._catalogue_cache = {
                    entry.get("id"): entry
                    for entry in response.json().get("data", [])
                    if entry.get("id")
                }
        except Exception:  # noqa: BLE001 - discovery must never break inference
            log.debug("Could not read the model catalogue from %s", self.base_url)

        return self._catalogue_cache

    def _model_entry(self) -> dict:
        """This model's row from the provider catalogue, or {}.

        Cached for the life of the provider. Failure is silent and returns
        {} - capability discovery is an enhancement, and a runtime that does
        not publish metadata (most local ones) must still work.
        """
        if not self.model:
            return {}
        return self._catalogue().get(self.model, {})

    @property
    def modalities(self) -> frozenset[str]:
        """Input modalities the active model accepts.

        Only what the provider actually reports. A runtime that publishes
        nothing gets {"text"}, so the product never claims to accept images
        on the strength of a guess.
        """
        reported = self._model_entry().get("input_modalities")
        if isinstance(reported, list) and reported:
            return frozenset(str(m).lower() for m in reported)
        return frozenset({"text"})

    @property
    def supports_tools(self) -> bool:
        """Whether the model advertises function calling.

        Defaults to True when the provider publishes no feature list. Every
        OpenAI-compatible runtime accepts the `tools` parameter, and one that
        ignores it simply answers without calling anything - a missed
        capability, not a false claim. Refusing to offer tools by default
        would instead disable them for every local runtime, which publishes
        no metadata at all.
        """
        features = self._model_entry().get("supported_features")
        if isinstance(features, list):
            return "tools" in features
        return True

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> dict:
        payload = {
            # Routing selects a model per call; the configured one is the
            # default rather than the only option.
            "model": model or self.model,
            "messages": [m.as_wire() for m in messages],
            "temperature": (
                self.default_temperature if temperature is None else temperature
            ),
            "max_tokens": self.default_max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            # "auto" lets the model answer directly when no tool is needed;
            # forcing a call produces a contrived one followed by the answer
            # it already had.
            #
            # "none" is how a caller says "you have seen these tools, now
            # answer without them". Removing the schemas entirely instead
            # makes some models emit their internal <tool_call> syntax as
            # plain prose, because they still intend to call something and
            # have nowhere to put it. Observed with Qwen; the fix is to keep
            # the schemas and refuse the call explicitly.
            payload["tool_choice"] = tool_choice
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP failures onto the ModelError hierarchy."""
        if response.is_success:
            return

        # Read the body defensively - error shapes vary between runtimes.
        try:
            detail = response.json().get("error", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:  # noqa: BLE001
            message = (response.text or "")[:300]

        message = message or f"HTTP {response.status_code}"
        status = response.status_code

        if status in (401, 403):
            # Never echo the provider's auth text back to the user; it can
            # contain key fragments.
            log.error("Model auth rejected by %s: %s", self.name, message)
            raise ModelAuthError(
                "Inference provider rejected our credentials. Check the API key "
                "configured on the server.",
                provider=self.name,
            )
        if status == 429:
            raise ModelRateLimitError(
                f"Inference provider is rate limiting requests: {message}",
                provider=self.name,
            )
        if status == 404:
            raise ModelResponseError(
                f"Model '{self.model}' was not found on this provider. "
                "Check MODEL_NAME against the provider's current catalogue "
                "(GET /api/models lists what is available).",
                provider=self.name,
            )
        if status >= 500:
            raise ModelUnavailableError(
                f"Inference provider error: {message}", provider=self.name
            )

        raise ModelResponseError(
            f"Inference request rejected ({status}): {message}", provider=self.name
        )

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------
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
        payload = self._payload(
            messages,
            temperature,
            max_tokens,
            stream=False,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(
                f"Inference provider did not respond within {self.timeout:.0f}s.",
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(
                f"Could not reach the inference provider at {self.base_url}.",
                provider=self.name,
            ) from exc

        self._raise_for_status(response)

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            text = message.get("content") or ""
            # Normalised to the OpenAI shape here so nothing above the
            # provider has to know a runtime's dialect.
            tool_calls = [
                {
                    "id": call.get("id") or f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": (call.get("function") or {}).get("name", ""),
                        "arguments": (call.get("function") or {}).get("arguments", "")
                        or "{}",
                    },
                }
                for index, call in enumerate(message.get("tool_calls") or [])
            ]
            usage_raw = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelResponseError(
                "Inference provider returned a response we could not parse.",
                provider=self.name,
            ) from exc

        return Completion(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
            ),
            tool_calls=tool_calls,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        payload = self._payload(
            messages, temperature, max_tokens, stream=True, model=model
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if not response.is_success:
                        # Body must be read before it can be inspected.
                        response.read()
                        self._raise_for_status(response)

                    for line in response.iter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk:
                            yield chunk

        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(
                f"Inference provider stopped responding after {self.timeout:.0f}s.",
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(
                f"Lost connection to the inference provider at {self.base_url}.",
                provider=self.name,
            ) from exc

    @staticmethod
    def _parse_sse_line(line: str) -> str | None:
        """Pull the text delta out of one server-sent-event line."""
        if not line or not line.startswith("data:"):
            return None

        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            return None

        try:
            choices = json.loads(data).get("choices") or []
            if not choices:
                return None
            return choices[0].get("delta", {}).get("content") or None
        except (ValueError, AttributeError, IndexError):
            # A malformed chunk mid-stream should not kill the whole reply.
            log.warning("Skipping unparseable stream chunk")
            return None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=min(self.timeout, 15.0)) as client:
                response = client.get(f"{self.base_url}/models", headers=self._headers())
            if not response.is_success:
                return []
            return sorted(
                item["id"] for item in response.json().get("data", []) if "id" in item
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return []
