"""Model gateway and provider tests.

These run without any API key: the OpenAI-compatible provider is exercised
against a mocked HTTP transport, so every failure mode the brief calls for
(provider down, timeout, malformed response, unavailable model) is covered
deterministically.
"""

import httpx
import pytest

from app.core.config import Settings
from app.models.base import (
    ChatMessage,
    ModelAuthError,
    ModelNotConfiguredError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.models.gateway import ModelGateway, build_provider
from app.models.providers import (
    GroqProvider,
    LocalProvider,
    OpenAICompatibleProvider,
    UnavailableProvider,
)

MESSAGES = [ChatMessage(role="user", content="What is a centrifugal pump?")]


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
def test_provider_none_by_default():
    provider = build_provider(Settings(model_provider="none", _env_file=None))
    assert isinstance(provider, UnavailableProvider)
    assert provider.configured is False
    assert provider.on_premise is False


def test_groq_without_api_key_degrades_instead_of_crashing():
    provider = build_provider(
        Settings(model_provider="groq", model_name="some-model", groq_api_key="", _env_file=None)
    )
    assert isinstance(provider, UnavailableProvider)


def test_groq_without_model_name_allows_discovery_but_not_inference():
    """Requiring MODEL_NAME to discover MODEL_NAME would be a dead end.

    With credentials but no model chosen, the provider is built so
    GET /api/models works, but `configured` stays False so inference still
    refuses with a clear error.
    """
    provider = build_provider(
        Settings(model_provider="groq", model_name="", groq_api_key="k", _env_file=None)
    )
    assert isinstance(provider, GroqProvider)
    assert provider.configured is False

    with pytest.raises(ModelNotConfiguredError):
        ModelGateway(provider).complete(MESSAGES)


def test_unknown_provider_degrades():
    provider = build_provider(Settings(model_provider="wat", _env_file=None))
    assert isinstance(provider, UnavailableProvider)


def test_groq_is_selected_and_is_never_on_premise():
    provider = build_provider(
        Settings(
            model_provider="groq", model_name="open-weight-model", groq_api_key="k", _env_file=None
        )
    )
    assert isinstance(provider, GroqProvider)
    assert provider.configured is True
    # The sovereignty claim must never be true for an external provider.
    assert provider.on_premise is False


def test_local_provider_is_on_premise_and_needs_no_key():
    provider = build_provider(
        Settings(model_provider="local", model_name="open-weight-model", _env_file=None)
    )
    assert isinstance(provider, LocalProvider)
    assert provider.configured is True
    assert provider.on_premise is True
    assert provider.api_key is None


def test_groq_and_local_share_one_implementation():
    """The swap must be configuration, not a reimplementation."""
    assert issubclass(GroqProvider, OpenAICompatibleProvider)
    assert issubclass(LocalProvider, OpenAICompatibleProvider)


# ---------------------------------------------------------------------------
# Gateway guard
# ---------------------------------------------------------------------------
def test_gateway_refuses_when_unconfigured():
    gateway = ModelGateway(UnavailableProvider())

    with pytest.raises(ModelNotConfiguredError):
        gateway.complete(MESSAGES)

    with pytest.raises(ModelNotConfiguredError):
        list(gateway.stream(MESSAGES))


def test_gateway_reports_provenance_from_the_provider():
    gateway = ModelGateway(
        LocalProvider(model="open-weight-model", base_url="http://localhost:11434/v1")
    )
    assert gateway.is_on_premise is True
    assert gateway.describe()["onPremise"] is True

    gateway = ModelGateway(GroqProvider(api_key="k", model="open-weight-model"))
    assert gateway.is_on_premise is False


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------
def test_successful_completion_is_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {"message": {"content": "A pump moves fluid."}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            },
        )

    provider = _patched(monkeypatch, handler)
    result = provider.complete(MESSAGES)

    assert result.text == "A pump moves fluid."
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 16


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ModelAuthError),
        (403, ModelAuthError),
        (429, ModelRateLimitError),
        (404, ModelResponseError),
        (400, ModelResponseError),
        (500, ModelUnavailableError),
        (503, ModelUnavailableError),
    ],
)
def test_http_errors_map_to_typed_model_errors(monkeypatch, status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    provider = _patched(monkeypatch, handler)
    with pytest.raises(expected):
        provider.complete(MESSAGES)


def test_auth_errors_do_not_leak_provider_text(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Invalid API Key: gsk_SECRETVALUE"}}
        )

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelAuthError) as exc:
        provider.complete(MESSAGES)

    assert "SECRET" not in str(exc.value)


def test_timeout_maps_to_model_timeout_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelTimeoutError):
        provider.complete(MESSAGES)


def test_unreachable_provider_maps_to_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelUnavailableError):
        provider.complete(MESSAGES)


def test_malformed_response_maps_to_response_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelResponseError):
        provider.complete(MESSAGES)


def test_missing_model_error_points_at_the_models_endpoint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelResponseError) as exc:
        provider.complete(MESSAGES)

    assert "/api/models" in str(exc.value)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
def _sse_body(*chunks: str) -> bytes:
    lines = []
    for chunk in chunks:
        lines.append(
            'data: {"choices":[{"delta":{"content":"%s"}}]}\n\n' % chunk
        )
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def test_stream_yields_text_deltas(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_body("Hello", " ", "world"),
            headers={"Content-Type": "text/event-stream"},
        )

    provider = _patched(monkeypatch, handler)
    assert "".join(provider.stream(MESSAGES)) == "Hello world"


def test_stream_skips_malformed_chunks(monkeypatch):
    body = (
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        b"data: {not json}\n\n"
        b'data: {"choices":[{"delta":{"content":"!"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/event-stream"}
        )

    provider = _patched(monkeypatch, handler)
    # One bad frame must not destroy the whole reply.
    assert "".join(provider.stream(MESSAGES)) == "ok!"


def test_stream_error_status_maps_to_typed_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    provider = _patched(monkeypatch, handler)
    with pytest.raises(ModelRateLimitError):
        list(provider.stream(MESSAGES))


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------
def test_list_models_returns_sorted_ids(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": "zeta"}, {"id": "alpha"}, {"no_id": True}]}
        )

    provider = _patched(monkeypatch, handler)
    assert provider.list_models() == ["alpha", "zeta"]


def test_list_models_is_soft_on_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    provider = _patched(monkeypatch, handler)
    # Discovery failing must not break the app.
    assert provider.list_models() == []


# ---------------------------------------------------------------------------
# Helper: route the provider's httpx.Client through a mock transport
# ---------------------------------------------------------------------------
def _patched(monkeypatch, handler) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        name="test",
        base_url="https://example.invalid/v1",
        model="test-model",
        api_key="test-key",
        timeout=5.0,
    )

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.models.providers.openai_compatible.httpx.Client", factory)
    return provider
