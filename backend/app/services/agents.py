"""What an agent can actually do, right now.

The agent catalogue used to describe itself with stored free text. The
"Document Vision" agent advertised *Thermal Image Inspection* and *OCR Text
Extraction* next to a deployment with no vision model and no OCR, and every
agent reported status "Online" because the column was seeded with that
string and never written again.

Both are the same mistake: a claim stored at authoring time, presented later
as a fact about the running system. This module replaces both with values
derived per request from the things that actually decide them - is a model
configured, is retrieval on, can the agent's declared tools run yet.

The split that makes this honest:

  specialisations  what the author says the agent is *for*. Free text,
                   unverified, and labelled as intent in the UI.
  capabilities     what the agent can *do*, derived here, each entry
                   carrying whether it is available and why not.

An unavailable capability is reported rather than hidden, because "vision
arrives in a later phase" is useful and "this agent does nothing" is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.database.models import Agent
from app.models import get_gateway
from app.models import router as model_router

#: Retrieval is answered from configuration rather than the tool registry,
#: because an agent retrieves whenever `retrieval_enabled` is set - it does
#: not need a tool grant to do it.
RETRIEVAL_CATEGORIES = {"Retrieval", "RAG"}

#: Vision is not a tool. A turn carrying an image is routed to the vision
#: model by `app.models.router`, so the question "can this agent see" is a
#: question about the route, not about a registry row.
VISION_CATEGORIES = {"Vision"}


@dataclass(frozen=True)
class Capability:
    """One thing an agent can or cannot do, and why."""

    label: str
    available: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "available": self.available, "detail": self.detail}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
#: Reported agent states. `Ready` is the only one that means "will work".
STATUS_READY = "Ready"
STATUS_LIMITED = "Limited"
STATUS_UNAVAILABLE = "Unavailable"
STATUS_RETIRED = "Retired"


def derive_capabilities(agent: Agent) -> list[Capability]:
    """What this agent can do, from its configuration and the runtime."""
    # Imported here rather than at module scope: the built-in analysis tool
    # imports `effective_folder_scope` from this module, so a top-level
    # import of the registry closes a cycle.
    from app.tools import registry as tool_registry

    gateway = get_gateway()
    capabilities: list[Capability] = []

    # Conversation is the baseline, and it is the model's to provide.
    capabilities.append(
        Capability(
            label="Conversational answers",
            available=gateway.is_configured,
            detail=(
                f"Runs on {gateway.model}."
                if gateway.is_configured
                else "No inference provider is configured on the server."
            ),
        )
    )

    # Retrieval is real, and needs no model of its own.
    categories = {tool.category for tool in agent.tools}
    wants_retrieval = bool(categories & RETRIEVAL_CATEGORIES)

    if wants_retrieval or agent.retrieval_enabled:
        if not settings.rag_enabled:
            detail = "Retrieval is disabled on this server."
            available = False
        elif not agent.retrieval_enabled:
            detail = "Turned off for this agent."
            available = False
        else:
            scope = agent.folder_scope or []
            where = (
                f"Searches {', '.join(scope)}."
                if scope
                else "Searches everything you are cleared for."
            )
            detail = f"{where} Answers are cited to the passages it finds."
            available = True

        capabilities.append(
            Capability(
                label="Document retrieval with citations",
                available=available,
                detail=detail,
            )
        )

    # Everything else the agent declares a tool for. Availability comes from
    # the tool registry, which knows whether an implementation exists and
    # whether an operator has switched it off.
    #
    # This used to be hardcoded to False with "the tool executor is not
    # implemented yet". That was true when it was written and stopped being
    # true when the executor landed, at which point every card understated
    # what its agent could do - the honesty layer failing in the pessimistic
    # direction, which is still failing.
    for category in sorted(categories - RETRIEVAL_CATEGORIES - VISION_CATEGORIES):
        rows = sorted(
            (t for t in agent.tools if t.category == category), key=lambda t: t.name
        )
        results = [(row, *tool_registry.describe(row)) for row in rows]
        blocked = [(row, reason) for row, ok, reason in results if not ok]

        if not blocked:
            detail = "Callable by this agent when a question needs it."
        else:
            detail = "; ".join(f"{row.name}: {reason}" for row, reason in blocked)

        capabilities.append(
            Capability(
                label=f"{category}: {', '.join(row.name for row in rows)}",
                available=not blocked,
                detail=detail,
            )
        )

    # Vision, asked of the router rather than the registry.
    if categories & VISION_CATEGORIES:
        names = sorted(t.name for t in agent.tools if t.category in VISION_CATEGORIES)
        route = model_router.resolve(model_router.ROLE_VISION)
        sees = bool(route.model) and get_gateway().model_accepts_images(route.model)
        capabilities.append(
            Capability(
                label=f"Vision: {', '.join(names)}",
                available=sees,
                detail=(
                    f"Images in a turn are routed to {route.model}."
                    if sees
                    else "No image-capable model is routed. Set MODEL_VISION in .env."
                ),
            )
        )

    return capabilities


def derive_status(agent: Agent, capabilities: list[Capability] | None = None) -> str:
    """Availability, computed rather than stored.

    `Limited` is a real and common state: an agent whose model works but
    whose vision tool does not is neither ready nor broken, and collapsing
    that into "Online" is what made the old status meaningless.
    """
    if agent.status == "Offline":
        return STATUS_RETIRED

    capabilities = capabilities if capabilities is not None else derive_capabilities(agent)

    if not get_gateway().is_configured:
        return STATUS_UNAVAILABLE
    if all(c.available for c in capabilities):
        return STATUS_READY
    return STATUS_LIMITED


def status_detail(agent: Agent, capabilities: list[Capability]) -> str:
    """One line explaining the status, for the tooltip under the pill."""
    unavailable = [c for c in capabilities if not c.available]

    if agent.status == "Offline":
        return "This agent has been retired by an administrator."
    if not get_gateway().is_configured:
        return (
            "No inference provider is configured, so no agent can answer. "
            "Set MODEL_PROVIDER in .env and restart the API."
        )
    if not unavailable:
        return "Everything this agent declares is available."
    return f"{len(unavailable)} of its declared capabilities cannot run yet."


# ---------------------------------------------------------------------------
# Retrieval scope
# ---------------------------------------------------------------------------
def effective_folder_scope(agent: Agent | None) -> list[str]:
    """Folders this agent restricts retrieval to. Empty means no restriction.

    Applied on top of the caller's own permissions, never instead of them -
    see `app.rag.retriever.retrieve`. An agent narrows; it cannot widen.
    """
    if agent is None or not agent.retrieval_enabled:
        return []
    return [f for f in (agent.folder_scope or []) if f]


def retrieval_is_enabled(agent: Agent | None) -> bool:
    if not settings.rag_enabled:
        return False
    if agent is None:
        return True
    return bool(agent.retrieval_enabled)


__all__ = [
    "Capability",
    "STATUS_LIMITED",
    "STATUS_READY",
    "STATUS_RETIRED",
    "STATUS_UNAVAILABLE",
    "derive_capabilities",
    "derive_status",
    "effective_folder_scope",
    "retrieval_is_enabled",
    "status_detail",
]
