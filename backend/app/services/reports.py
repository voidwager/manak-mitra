"""Generating an inspection report from a reply that already exists.

The "Generate Report" action used to be built entirely in the browser, by
`frontend/src/utils/reports.js`, and it had rotted into a liability. Written
during an earlier phase, it hardcoded "Not available yet" into every field and
stated that the workbench "cannot produce findings until document retrieval
and model inference are implemented" - both of which have been working for
several phases. The one field it did fill in confidently was a risk level the
UI defaulted to "Moderate Risk". A report that invents a risk rating is the
single worst artefact this product could emit.

So the report is assembled here instead, and the split is deliberate:

  the model      writes the prose - title, summary, findings - from the reply
                 it already produced. It is restructuring text, not sourcing
                 new claims.
  this layer     stamps the evidence trail from the stored message: which
                 documents were actually cited, which tools actually ran,
                 which model actually answered, under whose clearance.

Neither half can forge the other's. The model cannot add a source that was
never retrieved, because the source list is read from the persisted message
rather than from the model's account of itself - the same rule the rest of
the application follows for citations.

`ReportGeneratorTool` already implements the stamping, so this calls it rather
than reimplementing it. One definition of "what a report contains", used both
when the model asks for one mid-conversation and when the user clicks the
button afterwards.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import Agent, Conversation, Message, User
from app.models import ChatMessage, ModelError, get_gateway
from app.tools.base import ToolContext
from app.tools.builtin.reporting import ReportGeneratorTool

log = get_logger(__name__)

#: Activity-trace labels record tool runs as "Tool: name(args...)".
_TOOL_STEP = re.compile(r"^Tool:\s*([a-z0-9_]+)\s*\(", re.IGNORECASE)

#: Enough of a reply to be worth reporting on. Below this it is a greeting.
MIN_REPORTABLE_CHARS = 200

_DRAFT_INSTRUCTION = (
    "You are preparing a structured compliance summary from an answer that has "
    "already been given. Call generate_report exactly once.\n\n"
    "Use only what the answer below states. Do not add findings it does not "
    "contain, do not invent IS numbers, fees, timelines, dates or risk "
    "ratings, and do not soften or strengthen a limit. If the answer cites "
    "passages with bracketed numbers, keep those markers on the findings they "
    "belong to. Recommendations are optional - include them only where the "
    "answer actually recommends something."
)


class ReportError(Exception):
    """A report could not be produced. The message is shown to the user."""


def _question_for(db: Session, message: Message) -> str:
    """The user message this reply answered."""
    previous = db.scalars(
        select(Message)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.position < message.position,
            Message.sender == "user",
        )
        .order_by(Message.position.desc())
        .limit(1)
    ).first()
    return previous.text if previous else ""


def _tools_used(message: Message) -> list[str]:
    """Tool names from the stored trace, not from the model's recollection."""
    names: list[str] = []
    for step in message.activity_trace or []:
        found = _TOOL_STEP.match(str(step.get("label", "")))
        if found:
            names.append(found.group(1))
    return names


def _citations(message: Message) -> list[dict]:
    if message.sources:
        return list(message.sources)
    return [message.source] if message.source else []


def is_reportable(message: Message) -> bool:
    """Whether this reply has enough substance to report on.

    A citation counts on its own - a short answer backed by a retrieved
    passage is exactly what a report should carry. Otherwise the reply has to
    be long enough to contain findings at all.
    """
    if message.sender != "assistant":
        return False
    if _citations(message):
        return True
    return len((message.text or "").strip()) >= MIN_REPORTABLE_CHARS


def _draft(answer: str, question: str) -> dict:
    """Ask the model to structure the reply into report fields.

    Returned through the tool-call interface rather than by asking for JSON in
    prose: the arguments then arrive already conforming to the schema the
    report is built from, instead of needing to be parsed out of a reply that
    may or may not have wrapped them in a code fence.
    """
    gateway = get_gateway()
    if not gateway.is_configured:
        raise ReportError(
            "No model provider is configured, so the findings cannot be "
            "drafted. The answer itself is still on screen."
        )

    schema = ReportGeneratorTool().as_schema()
    messages = [
        ChatMessage(role="system", content=_DRAFT_INSTRUCTION),
        ChatMessage(
            role="user",
            content=(
                f"The question asked was:\n{question or '(not recorded)'}\n\n"
                f"The answer given was:\n{answer}"
            ),
        ),
    ]

    try:
        completion = gateway.complete(messages, temperature=0.0, tools=[schema])
    except ModelError as exc:
        raise ReportError(f"The model could not draft the report: {exc}") from exc

    for call in completion.tool_calls or []:
        function = call.get("function", {})
        if function.get("name") != ReportGeneratorTool.name:
            continue
        raw = function.get("arguments") or "{}"
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError) as exc:
            raise ReportError("The drafted report was not readable.") from exc

    raise ReportError(
        "The model did not return a structured report. Nothing has been "
        "written rather than filling the document with placeholder text."
    )


def generate_for_message(
    db: Session,
    user: User,
    conversation: Conversation,
    message: Message,
) -> dict:
    """Build, store and return the report for one assistant reply.

    Stored on the message so reopening the conversation shows the document
    that was produced. A report is a record of what the system held when it
    was asked; silently regenerating it later against a changed corpus would
    put a different document under the same heading.
    """
    if message.sender != "assistant":
        raise ReportError("Only an assistant reply can be turned into a report.")
    if not (message.text or "").strip():
        raise ReportError("This reply has no content to report on.")
    if not is_reportable(message):
        raise ReportError(
            "This reply is too short to build a report from, and no document "
            "was cited in it."
        )

    if message.report:
        return message.report

    question = _question_for(db, message)
    drafted = _draft(message.text, question)

    agent: Agent | None = conversation.agent
    context = ToolContext(
        db=db,
        user=user,
        agent=agent,
        # Provenance comes from the stored reply, never from the draft. The
        # model cannot list a document that was not actually retrieved.
        turn_citations=_citations(message),
        tools_used=_tools_used(message),
        question=question,
    )

    result = ReportGeneratorTool().run(
        context,
        title=drafted.get("title") or (question[:80] or "Compliance summary"),
        summary=drafted.get("summary") or "",
        findings=drafted.get("findings") or [],
        recommendations=drafted.get("recommendations") or [],
    )

    report = (result.data or {}).get("report")
    if not report:
        raise ReportError("The report could not be assembled.")

    message.report = report
    db.commit()
    return report


__all__ = ["ReportError", "generate_for_message", "is_reportable"]
