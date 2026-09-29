"""Inspection report generation.

The report is the most dangerous artefact this product emits. It looks
official, it gets forwarded out of the conversation that produced it, and
nothing downstream re-checks it. The previous implementation was built in the
browser and filled every field it could not compute with a plausible-sounding
constant - including a risk rating of "Moderate Risk" that nothing had
assessed, under a real refinery operator's letterhead, over synthetic data.

So the rules under test are about provenance, not formatting:

  1. The evidence trail comes from the stored reply, never from the model.
     A model that names a document in its findings cannot thereby add it to
     the sources list.
  2. Nothing is invented to fill a gap. No risk rating, and an absent
     evidence trail is stated rather than papered over.
  3. A report is a record. Once generated it is stored and returned as-is,
     not rebuilt against a corpus that may have changed underneath it.
"""

import json

import pytest

from app.database.models import Conversation, Message
from app.models.base import Completion, ModelProvider
from app.services import reports


class DraftingProvider(ModelProvider):
    """A provider that answers with a `generate_report` tool call."""

    name = "stub"
    configured = True
    supports_tools = True

    def __init__(self, arguments: dict, *, on_premise=False):
        super().__init__(model="stub-model")
        self.arguments = arguments
        self.on_premise = on_premise
        self.calls = 0

    def complete(self, messages, **kwargs) -> Completion:
        self.calls += 1
        return Completion(
            text="",
            model=self.model,
            provider=self.name,
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "generate_report",
                        "arguments": json.dumps(self.arguments),
                    },
                }
            ],
        )

    def stream(self, messages, **kwargs):
        yield ""


DRAFT = {
    "title": "Pump P-204 Vibration Assessment",
    "summary": "Vibration must stay at or below 2.5 mm/s RMS.",
    "findings": [
        "Acceptable vibration is 2.5 mm/s RMS in any direction [1].",
        "Above 3.2 mm/s RMS the pump is withdrawn from service [1].",
    ],
    "recommendations": ["Schedule an alignment check within seven days."],
}

REAL_SOURCE = {
    "documentId": "doc-1",
    "title": "Centrifugal Pump Inspection SOP.pdf",
    "page": "Page 4 · 4.2 VIBRATION",
    "excerpt": "Acceptable vibration: 2.5 mm/s RMS.",
}


@pytest.fixture
def drafting_gateway(monkeypatch):
    from app.models.gateway import ModelGateway

    def install(provider):
        monkeypatch.setattr(
            reports, "get_gateway", lambda: ModelGateway(provider)
        )
        return provider

    return install


def _thread(db, *, user_id="user-ananya", text, sources=None, trace=None, suffix=""):
    conversation = Conversation(
        id=f"conv-report{suffix}",
        title="report",
        user_id=user_id,
        agent_id="maint-intel",
        agent_name="Maintenance Intelligence",
    )
    db.add(conversation)
    db.flush()
    db.add(
        Message(
            id=f"msg-report-q{suffix}",
            conversation_id=conversation.id,
            sender="user",
            text="What is the acceptable vibration limit for a CDU-II pump?",
            position=1,
        )
    )
    reply = Message(
        id=f"msg-report-a{suffix}",
        conversation_id=conversation.id,
        sender="assistant",
        text=text,
        position=2,
        sources=sources,
        activity_trace=trace,
    )
    db.add(reply)
    db.flush()
    return conversation, reply


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def test_the_model_cannot_add_a_source_that_was_never_retrieved(
    db_session, drafting_gateway
):
    """The findings may name a document; the evidence trail still cannot."""
    drafting_gateway(
        DraftingProvider(
            {
                **DRAFT,
                "findings": [
                    "Per the Hydrocracker Unit Strategic Audit.pdf, margins are strong.",
                    "Acceptable vibration is 2.5 mm/s RMS [1].",
                ],
            }
        )
    )
    conversation, reply = _thread(
        db_session, text="Vibration limit is 2.5 mm/s RMS.", sources=[REAL_SOURCE]
    )

    report = reports.generate_for_message(
        db_session, db_session.get(type(conversation.user), "user-ananya"), conversation, reply
    )

    titles = {s["title"] for s in report["sources"]}
    assert titles == {"Centrifugal Pump Inspection SOP.pdf"}
    assert "Hydrocracker Unit Strategic Audit.pdf" not in titles

    db_session.rollback()


def test_tools_run_are_read_from_the_stored_trace(db_session, drafting_gateway):
    drafting_gateway(DraftingProvider(DRAFT))
    conversation, reply = _thread(
        db_session,
        text="Vibration limit is 2.5 mm/s RMS.",
        sources=[REAL_SOURCE],
        trace=[
            {"label": "Task received", "status": "done"},
            {"label": "Tool: read_document(document=Centrifugal Pump...)", "status": "done"},
            {"label": "Tool: calculator(expression=2+2)", "status": "done"},
        ],
        suffix="-tools",
    )

    report = reports.generate_for_message(
        db_session, db_session.get(type(conversation.user), "user-ananya"), conversation, reply
    )

    assert report["toolsUsed"] == ["calculator", "read_document"]
    db_session.rollback()


def test_no_risk_rating_is_invented(db_session, drafting_gateway):
    """The old modal defaulted an unset risk level to "Moderate Risk"."""
    drafting_gateway(DraftingProvider(DRAFT))
    conversation, reply = _thread(
        db_session,
        text="Vibration limit is 2.5 mm/s RMS.",
        sources=[REAL_SOURCE],
        suffix="-risk",
    )

    report = reports.generate_for_message(
        db_session, db_session.get(type(conversation.user), "user-ananya"), conversation, reply
    )

    assert "riskLevel" not in report
    assert "Moderate Risk" not in json.dumps(report)
    db_session.rollback()


def test_an_uncited_reply_produces_a_report_with_an_empty_evidence_trail(
    db_session, drafting_gateway
):
    """Stated, not padded. The reader must see which kind of document this is."""
    drafting_gateway(DraftingProvider(DRAFT))
    conversation, reply = _thread(
        db_session,
        text="General guidance on pump vibration. " * 20,
        sources=None,
        suffix="-uncited",
    )

    report = reports.generate_for_message(
        db_session, db_session.get(type(conversation.user), "user-ananya"), conversation, reply
    )

    assert report["sources"] == []
    db_session.rollback()


# ---------------------------------------------------------------------------
# Refusals and storage
# ---------------------------------------------------------------------------
def test_a_trivial_reply_is_refused_rather_than_padded(db_session, drafting_gateway):
    drafting_gateway(DraftingProvider(DRAFT))
    conversation, reply = _thread(db_session, text="Sure thing!", suffix="-short")

    with pytest.raises(reports.ReportError):
        reports.generate_for_message(
            db_session,
            db_session.get(type(conversation.user), "user-ananya"),
            conversation,
            reply,
        )
    db_session.rollback()


def test_a_stored_report_is_returned_rather_than_regenerated(
    db_session, drafting_gateway
):
    """A report is a record of what the system held when it was asked."""
    provider = drafting_gateway(DraftingProvider(DRAFT))
    conversation, reply = _thread(
        db_session,
        text="Vibration limit is 2.5 mm/s RMS.",
        sources=[REAL_SOURCE],
        suffix="-stored",
    )
    user = db_session.get(type(conversation.user), "user-ananya")

    first = reports.generate_for_message(db_session, user, conversation, reply)
    assert provider.calls == 1

    second = reports.generate_for_message(db_session, user, conversation, reply)
    assert provider.calls == 1, "the model must not be asked a second time"
    assert second == first
    assert reply.report == first

    db_session.rollback()


def test_a_report_needs_an_assistant_reply(db_session, drafting_gateway):
    drafting_gateway(DraftingProvider(DRAFT))
    conversation, _ = _thread(db_session, text="Anything", suffix="-user")
    question = db_session.get(Message, "msg-report-q-user")

    with pytest.raises(reports.ReportError):
        reports.generate_for_message(
            db_session,
            db_session.get(type(conversation.user), "user-ananya"),
            conversation,
            question,
        )
    db_session.rollback()


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
def test_another_users_message_is_not_reportable(client, safety_headers, db_session):
    """A thread that is not yours is a 404, not a 403.

    "That is not yours" still confirms it exists.
    """
    conversation, reply = _thread(
        db_session,
        text="Vibration limit is 2.5 mm/s RMS.",
        sources=[REAL_SOURCE],
        suffix="-other",
    )
    db_session.commit()

    response = client.post(
        f"/api/conversations/{conversation.id}/messages/{reply.id}/report",
        headers=safety_headers,
    )
    assert response.status_code == 404

    db_session.delete(conversation)
    db_session.commit()
