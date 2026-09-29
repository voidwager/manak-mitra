"""Chat endpoint tests.

Exercises /api/chat and /api/chat/stream against a stub provider, so the
full path - persistence, prompt assembly, error handling, streaming - is
covered without an API key or a network call.

`StubProvider` and the `stub_gateway` fixture live in conftest.py because
the retrieval tests need them too.
"""

import json
from datetime import datetime

import pytest

from app.models.base import ModelRateLimitError, ModelTimeoutError
from app.models.providers import UnavailableProvider
from tests.conftest import StubProvider


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------
def test_chat_returns_and_persists_the_model_reply(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider("Check the HUID in the BIS CARE app before you buy."))

    response = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "How do I check a hallmark?", "agentId": "hallmark-helper"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["provider"] == "stub"
    assert body["assistantMessage"]["text"] == "Check the HUID in the BIS CARE app before you buy."

    # Both turns were written to the database.
    conv = client.get(
        f"/api/conversations/{body['conversationId']}", headers=owner_headers
    ).json()
    assert [m["sender"] for m in conv["messages"]] == ["user", "assistant"]


def test_reply_never_carries_a_citation_without_retrieval(
    client, owner_headers, stub_gateway
):
    """The single most important guarantee in this system.

    A citation is built from retrieved passages and from nothing else. When
    retrieval returns nothing, the reply carries no source however
    confidently the model names one - the API does not read citations out of
    model output.
    """
    stub_gateway(StubProvider("See Scheme-I clause 4.2 on page 12."))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "zzqqxx nonexistent terminology"},
    ).json()

    assert body["retrievalMode"] == "none"
    assert body["assistantMessage"]["source"] is None
    assert not body["assistantMessage"]["sources"]


def test_system_prompt_forbids_fabricated_citations(client, owner_headers, stub_gateway):
    stub = stub_gateway(StubProvider())

    client.post("/api/chat", headers=owner_headers, json={"message": "Hello"})

    system = stub.last_prompt[0]
    assert system.role == "system"
    # Nothing was retrieved for this turn, so the unconditional prohibition
    # applies - not the narrower "cite only what is in CONTEXT" form.
    assert "NO access to any document" in system.content
    assert "never cite, quote or reference" in system.content
    assert "CONTEXT" not in system.content


def test_conversation_history_is_sent_as_context(client, owner_headers, stub_gateway):
    stub = stub_gateway(StubProvider())

    first = client.post(
        "/api/chat", headers=owner_headers, json={"message": "First message"}
    ).json()

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "Second message", "conversationId": first["conversationId"]},
    )

    contents = [m.content for m in stub.last_prompt]
    assert "First message" in contents
    assert "Second message" in contents
    # System prompt always leads.
    assert stub.last_prompt[0].role == "system"


def test_attachments_are_declared_as_unreadable(client, owner_headers, stub_gateway):
    stub = stub_gateway(StubProvider())

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": "What is in this report?",
            "attachments": [{"name": "inspection.pdf", "size": "1 MB", "type": "pdf"}],
        },
    )

    # Name-only attachments carry no bytes, so there is nothing to read. The
    # model is told which file it could not read and why, and told not to
    # guess - a confident summary of an unread report is the failure mode.
    joined = " ".join(m.content for m in stub.last_prompt if m.role == "system")
    assert "you cannot read" in joined
    assert "inspection.pdf" in joined
    assert "not uploaded" in joined
    assert "Never guess" in joined


def test_activity_trace_names_the_provider_and_records_only_real_steps(
    client, owner_headers, stub_gateway
):
    stub_gateway(StubProvider())

    body = client.post(
        "/api/chat", headers=owner_headers, json={"message": "Hello"}
    ).json()

    trace = body["assistantMessage"]["activityTrace"]
    labels = [s["label"] for s in trace]
    assert any("stub" in label for label in labels)

    # "Hello" matches nothing, and the trace records the miss as a skipped
    # step rather than implying a search that succeeded.
    miss = next(s for s in trace if "found nothing to cite" in s["label"])
    assert miss["status"] == "skipped"
    assert "without citations" in miss["label"]
    assert body["assistantMessage"]["source"] is None


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
def test_unconfigured_provider_returns_503(client, owner_headers, stub_gateway):
    stub_gateway(UnavailableProvider())

    response = client.post("/api/chat", headers=owner_headers, json={"message": "Hi"})
    assert response.status_code == 503


@pytest.mark.parametrize(
    "error,status",
    [
        (ModelTimeoutError("slow"), 504),
        (ModelRateLimitError("quota"), 429),
    ],
)
def test_inference_failures_surface_as_errors_not_fake_replies(
    client, owner_headers, stub_gateway, error, status
):
    stub_gateway(StubProvider(error=error))

    response = client.post(
        "/api/chat", headers=owner_headers, json={"message": "Anything"}
    )
    assert response.status_code == status
    # No fabricated assistant turn was invented to paper over the failure.
    assert "assistantMessage" not in response.json()


def test_user_message_survives_an_inference_failure(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider(error=ModelTimeoutError("slow")))

    response = client.post(
        "/api/chat", headers=owner_headers, json={"message": "Do not lose me"}
    )
    detail = response.json()["detail"]

    conv = client.get(
        f"/api/conversations/{detail['conversationId']}", headers=owner_headers
    ).json()
    assert conv["messages"][-1]["text"] == "Do not lose me"
    assert conv["messages"][-1]["sender"] == "user"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
def _events(raw: str) -> list[tuple[str, str]]:
    parsed = []
    for frame in raw.split("\n\n"):
        if not frame.strip():
            continue
        event, data = "message", ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        parsed.append((event, data))
    return parsed


def test_stream_emits_start_deltas_and_done(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider("Check the seal first"))

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=owner_headers,
        json={"message": "Where do I start?"},
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())

    events = _events(raw)
    names = [name for name, _ in events]

    assert names[0] == "start"
    assert names[-1] == "done"
    assert names.count("delta") == 4  # one per word


def test_streamed_reply_is_persisted(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider("Persisted streamed text"))

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=owner_headers,
        json={"message": "Stream please"},
    ) as response:
        raw = "".join(response.iter_text())

    done = [data for name, data in _events(raw) if name == "done"]
    assert done

    import json

    payload = json.loads(done[0])
    conv = client.get(
        f"/api/conversations/{payload['conversationId']}", headers=owner_headers
    ).json()

    assistant = conv["messages"][-1]
    assert assistant["sender"] == "assistant"
    assert assistant["text"] == "Persisted streamed text"
    assert assistant["source"] is None


def test_stream_reports_failure_as_an_error_event(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider(error=ModelRateLimitError("quota")))

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=owner_headers,
        json={"message": "Anything"},
    ) as response:
        raw = "".join(response.iter_text())

    names = [name for name, _ in _events(raw)]
    assert "error" in names
    assert "done" not in names


# ---------------------------------------------------------------------------
# User settings actually reach the model
# ---------------------------------------------------------------------------
def test_response_style_reaches_the_system_prompt(client, owner_headers, stub_gateway):
    stub = stub_gateway(StubProvider())

    client.patch(
        "/api/settings", headers=owner_headers, json={"responseStyle": "Concise Summary"}
    )
    client.post("/api/chat", headers=owner_headers, json={"message": "Style check"})

    system = stub.last_prompt[0].content
    assert "at most a short paragraph" in system

    client.patch(
        "/api/settings",
        headers=owner_headers,
        json={"responseStyle": "Precise & Technical"},
    )


def test_guardrail_stays_last_in_the_prompt(client, owner_headers, stub_gateway):
    """Nothing configurable may be appended after the constraints."""
    stub = stub_gateway(StubProvider())
    client.post("/api/chat", headers=owner_headers, json={"message": "Order check"})

    system = stub.last_prompt[0].content
    assert system.rstrip().endswith("Give the answer.")

    # The tone block is friendly, but it must sit *before* the constraints -
    # anything appended after them could talk its way past them.
    assert system.index("HOW TO TALK") < system.index("WHAT YOU MAY CLAIM")


# ---------------------------------------------------------------------------
# Agents report the model that will really run
# ---------------------------------------------------------------------------
def test_agents_report_the_active_model(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider())

    agents = client.get("/api/agents", headers=owner_headers).json()
    assert all(a["model"] == "stub-model" for a in agents)


def test_agents_report_no_model_when_unconfigured(client, owner_headers, stub_gateway):
    stub_gateway(UnavailableProvider())

    agents = client.get("/api/agents", headers=owner_headers).json()
    assert all(a["model"] == "No model configured" for a in agents)


def test_effective_model_is_not_written_back_to_the_database(
    client, owner_headers, stub_gateway
):
    """The decoration is presentation-only.

    If it leaked into the row, a later run with a different provider would
    keep reporting a stale model.
    """
    stub_gateway(StubProvider())
    client.get("/api/agents", headers=owner_headers)

    stub_gateway(UnavailableProvider())
    agents = client.get("/api/agents", headers=owner_headers).json()
    assert all(a["model"] == "No model configured" for a in agents)


# ---------------------------------------------------------------------------
# Honesty reporting
# ---------------------------------------------------------------------------
def test_health_reports_external_provider_as_not_on_premise(
    client, owner_headers, stub_gateway
):
    stub_gateway(StubProvider(on_premise=False))

    body = client.get("/api/health").json()
    assert body["inference"]["configured"] is True
    assert body["inference"]["onPremise"] is False
    assert body["implemented"]["onPremiseInference"] is False
    assert "not sovereign" in body["inference"]["summary"]


def test_health_reports_local_provider_as_on_premise(client, stub_gateway):
    stub_gateway(StubProvider(on_premise=True))

    body = client.get("/api/health").json()
    assert body["inference"]["onPremise"] is True
    assert body["implemented"]["onPremiseInference"] is True
    assert "not sovereign" not in body["inference"]["summary"]


def test_messages_carry_an_instant_not_a_prerendered_clock(
    client, owner_headers, stub_gateway
):
    """The API sends `createdAt`; formatting belongs to the viewer's browser.

    Regression. Messages used to ship `timestamp` as a string the server had
    already rendered ("10:24 AM") from its own naive local clock, and seeded
    rows carried that value hardcoded. Every viewer therefore saw the server's
    timezone, and a single thread could show 1:43 AM, 2:05 AM and 10:24 AM at
    once. A server cannot know what time it is where the reader is sitting, so
    it sends the instant and says nothing about how to display it.
    """
    stub_gateway(StubProvider("Timed reply"))

    created = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "What time is it there?"},
    )
    assert created.status_code == 200

    conversation_id = created.json()["conversationId"]
    conv = client.get(
        f"/api/conversations/{conversation_id}", headers=owner_headers
    ).json()

    assert len(conv["messages"]) >= 2
    for message in conv["messages"]:
        # No pre-rendered clock string in the payload at all.
        assert "timestamp" not in message
        assert "displayTimestamp" not in message

        # A parseable, timezone-aware instant instead.
        moment = datetime.fromisoformat(message["createdAt"])
        assert moment.tzinfo is not None, "instant must carry an offset"


def test_stream_start_event_serialises_the_message_instant(
    client, owner_headers, stub_gateway
):
    """A datetime in a stream payload must not blow up the SSE encoder.

    `_sse` json-encodes each event; adding `created_at` to MessageOut put a
    datetime inside the `start` event's `userMessage`. Without a default
    encoder that raises mid-answer, which surfaces as a dead stream rather
    than a tidy error.
    """
    stub_gateway(StubProvider("Streamed"))

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=owner_headers,
        json={"message": "Stream with a clock"},
    ) as response:
        raw = "".join(response.iter_text())

    starts = [data for name, data in _events(raw) if name == "start"]
    assert starts

    user_message = json.loads(starts[0])["userMessage"]
    moment = datetime.fromisoformat(user_message["createdAt"])
    assert moment.tzinfo is not None
