"""SI-1: one assistant, several specialists behind it.

Before this the user picked an agent from a dropdown before asking anything,
which is backwards - you have to know which specialist you need before you
know what you are asking. SI-1 is a universal agent that takes the question
first and engages the right specialist itself.

**What "engaging a specialist" means.** It is not a second model call
answering the question. SI-1 borrows the specialist's *configuration* - its
folder scope, its tool grants, its instructions - and answers the turn with
those applied. So dispatch changes what the assistant can see and do, not
who is speaking.

**Why the classifier is small and separate.** Picking a specialist is a
one-word decision made from the question alone, so it uses the fast model
and a tiny prompt rather than the model that will answer. That keeps the
cost of dispatch close to nothing and means the choice cannot be influenced
by retrieved documents - which are untrusted input, and which would
otherwise get a vote in what permissions apply.

**Dispatch never widens access.** A specialist's folder scope is intersected
with the caller's own permissions exactly as it is when the specialist is
chosen by hand. Being routed to the SOP specialist does not grant Safety
folder access to somebody who lacks it; it narrows their search, or finds
nothing.

**Every dispatch is explained.** The activity trace names the specialist and
the reason. A user who cannot tell why an answer was scoped the way it was
cannot trust the scoping.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import Agent
from app.models import ChatMessage, ModelError, get_gateway
from app.models import router as model_router

log = get_logger(__name__)

#: The id of the universal agent. Seeded, and the default for a new chat.
UNIVERSAL_AGENT_ID = "si-1"

#: Cap on how much of the question the classifier sees. A dispatch decision
#: does not need the whole essay, and a long one costs tokens for nothing.
MAX_CLASSIFIER_CHARS = 600

#: Output budget for the classifier.
#:
#: Generous for a one-word answer, because the models in this catalogue
#: reason before they speak. At 16 tokens gpt-oss-20b spent the whole
#: budget thinking and returned an empty string with
#: finish_reason="length" - which was read as "no specialist needed" and
#: made dispatch look like it was deciding when it was failing. It needs
#: about 60.
CLASSIFIER_MAX_TOKENS = 256

CLASSIFIER_PROMPT = """You route a question to one specialist.

Specialists:
{options}

Reply with the id of the best fit and nothing else. If none clearly fits, or
the message is small talk, a greeting, or a general question needing no
plant documents, reply: general

Question:
{question}"""


@dataclass(frozen=True)
class Dispatch:
    """Which specialist is handling this turn, and why."""

    #: The agent whose configuration applies. None means SI-1 answers with
    #: its own unrestricted configuration.
    specialist: Agent | None

    #: Plain English, shown in the activity trace.
    reason: str

    #: False when the classifier could not run and SI-1 answered directly.
    dispatched: bool = False

    @property
    def note(self) -> str | None:
        """A line for the system prompt, so the model knows its remit."""
        if self.specialist is None:
            return None
        return (
            f"For this question you are drawing on your {self.specialist.name} "
            f"specialism. {self.specialist.description}"
        )


def is_universal(agent: Agent | None) -> bool:
    return agent is not None and agent.id == UNIVERSAL_AGENT_ID


def selectable_specialists(db: Session) -> list[Agent]:
    """Agents SI-1 may dispatch to.

    Itself excluded, obviously, and retired agents excluded - an operator
    who has taken an agent out of service does not expect it to keep being
    used because a router liked the look of it.
    """
    return [
        agent
        for agent in db.scalars(
            select(Agent).where(
                Agent.id != UNIVERSAL_AGENT_ID,
                Agent.status == "Online",
            )
        )
        if agent.is_system
    ]


def choose(db: Session, agent: Agent | None, question: str) -> Dispatch:
    """Pick the specialist for this turn.

    Only runs for the universal agent. When the user has explicitly chosen a
    specialist, that choice stands - an override the system second-guesses
    is not an override.
    """
    if not is_universal(agent):
        return Dispatch(specialist=None, reason="", dispatched=False)

    question = (question or "").strip()
    if not question:
        return Dispatch(
            specialist=None,
            reason="Nothing to route.",
            dispatched=False,
        )

    specialists = selectable_specialists(db)
    if not specialists:
        return Dispatch(
            specialist=None,
            reason="No specialists are available, so Manak Mitra answered directly.",
            dispatched=False,
        )

    options = "\n".join(
        f"- {a.id}: {a.name}. {a.description}" for a in specialists
    )
    prompt = CLASSIFIER_PROMPT.format(
        options=options, question=question[:MAX_CLASSIFIER_CHARS]
    )

    gateway = get_gateway()
    # The fast model, and no tools: this is a one-word decision, and letting
    # it retrieve or calculate would make dispatch cost more than the answer.
    route = model_router.resolve(model_router.ROLE_FAST)

    try:
        completion = gateway.complete(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            model=route.model or None,
        )
    except ModelError as exc:
        # Dispatch failing must not fail the turn. SI-1 answers with its own
        # unrestricted configuration, which is a worse answer, not no answer.
        log.warning("Specialist routing unavailable: %s", exc)
        return Dispatch(
            specialist=None,
            reason="Specialist routing was unavailable, so Manak Mitra answered directly.",
            dispatched=False,
        )

    choice = (completion.text or "").strip().lower().strip(".\"'` \n")

    if not choice:
        # Empty is a failure, not a verdict. Reporting it as "no specialist
        # needed" made a broken classifier look like a working one, which
        # is how it went unnoticed until a live run.
        log.warning(
            "Specialist router returned nothing (finish_reason=%s); "
            "Manak Mitra answering directly.",
            completion.finish_reason,
        )
        return Dispatch(
            specialist=None,
            reason="Specialist routing returned no answer, so Manak Mitra answered directly.",
            dispatched=False,
        )

    if choice.startswith("general"):
        return Dispatch(
            specialist=None,
            reason="No specialist was needed, so Manak Mitra answered directly.",
            dispatched=True,
        )

    # Match on id, then on name, because a model asked for an id will
    # sometimes return the name anyway.
    chosen = next((a for a in specialists if a.id.lower() == choice), None)
    if chosen is None:
        chosen = next(
            (a for a in specialists if a.name.lower() in choice or choice in a.name.lower()),
            None,
        )

    if chosen is None:
        log.info("Specialist router returned %r, which matched nothing", choice)
        return Dispatch(
            specialist=None,
            reason="No specialist matched, so Manak Mitra answered directly.",
            dispatched=True,
        )

    return Dispatch(
        specialist=chosen,
        reason=f"Engaged the {chosen.name} specialist for this question.",
        dispatched=True,
    )


def effective_agent(agent: Agent | None, dispatch: Dispatch) -> Agent | None:
    """The configuration that applies to this turn.

    The specialist's scope and tools when one was engaged; otherwise
    whatever the user chose. Note this returns the *specialist* record, so
    everything downstream - retrieval scope, tool grants, model role - reads
    from it exactly as it would had the user picked it by hand. Dispatch
    adds no new code path, which is why it cannot introduce a new way to
    widen access.
    """
    if dispatch.specialist is not None:
        return dispatch.specialist
    return agent


__all__ = [
    "UNIVERSAL_AGENT_ID",
    "Dispatch",
    "choose",
    "effective_agent",
    "is_universal",
    "selectable_specialists",
]
