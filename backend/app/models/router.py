"""Model routing: which model serves this turn, and why.

One deployment, several models. The router picks between them per turn and
records the reason, so an answer can always be traced back to the model that
produced it and the fact that selected it.

Two rules keep this honest.

**Routing is deterministic.** A turn carrying an image needs a model that
accepts images - that is a property of the turn, not a judgement about its
difficulty. There is deliberately no "this looks like a hard question"
heuristic: a router that silently switches models on a hunch cannot be
debugged, cannot be explained to an auditor, and makes every answer
irreproducible.

**A role that is not configured degrades visibly.** An unset role falls back
to the default model and says so. It never silently pretends the routed
model was used, and it never sends an image to a model that cannot read one.

Routing selects a *model*, never a provider. It therefore lives inside the
gateway seam: switching from a hosted provider to an on-premise runtime
changes which models exist, not how they are chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: What a turn can need. `chat` is the default and always resolves.
ROLE_CHAT = "chat"
ROLE_VISION = "vision"
ROLE_REASONING = "reasoning"
ROLE_FAST = "fast"
ROLE_TRANSCRIPTION = "transcription"

ROLES = (ROLE_CHAT, ROLE_VISION, ROLE_REASONING, ROLE_FAST, ROLE_TRANSCRIPTION)

#: Human-readable purpose, reported by /api/models so the table explains
#: itself rather than needing the documentation open beside it.
ROLE_PURPOSE = {
    ROLE_CHAT: "Default. Serves any turn with no more specific requirement.",
    ROLE_VISION: "Turns with an image attached. Must accept image input.",
    ROLE_REASONING: "Agents explicitly configured for longer analysis.",
    ROLE_FAST: "Short turns where the larger model is wasted.",
    ROLE_TRANSCRIPTION: "Speech to text for the microphone.",
}


@dataclass(frozen=True)
class Route:
    """The model chosen for a turn, and the reason it was chosen."""

    model: str
    role: str

    #: Plain English, shown in the activity trace. An operator reading a
    #: trace should never have to guess why a particular model answered.
    reason: str

    #: True when the requested role had no model configured and the default
    #: was used instead.
    degraded: bool = False

    def describe(self) -> str:
        return f"{self.model} ({self.role})"


def configured_models(config: Settings | None = None) -> dict[str, str]:
    """The role table as configured, with unset roles omitted."""
    config = config or settings
    table = {
        ROLE_CHAT: config.model_name,
        ROLE_VISION: config.model_vision,
        ROLE_REASONING: config.model_reasoning,
        ROLE_FAST: config.model_fast,
        ROLE_TRANSCRIPTION: config.model_transcription,
    }
    return {role: model for role, model in table.items() if model}


def resolve(
    role: str = ROLE_CHAT,
    *,
    pinned: str | None = None,
    config: Settings | None = None,
) -> Route:
    """Choose the model for `role`.

    Priority, highest first:

      1. A model pinned by the agent, when the role permits one. A pin is an
         operator's explicit decision and outranks the role table.
      2. The model configured for the role.
      3. The default model, reported as degraded.

    `vision` deliberately ignores a pin unless the pin *is* the vision model:
    honouring a text-only pin on a turn with an image would send a picture to
    a model that cannot see it, and the failure would look like the image
    being ignored rather than misrouted.
    """
    config = config or settings
    table = configured_models(config)
    default = config.model_name

    if role not in ROLES:
        log.warning("Unknown model role '%s'; using the default model.", role)
        role = ROLE_CHAT

    if role == ROLE_VISION:
        vision = table.get(ROLE_VISION)
        if vision:
            return Route(
                model=vision,
                role=ROLE_VISION,
                reason="This turn includes an image, so it was routed to the vision model.",
            )
        # No vision model configured. The caller must not send the image.
        return Route(
            model=default,
            role=ROLE_VISION,
            reason=(
                "No vision model is configured (MODEL_VISION is unset), so the "
                "image could not be read."
            ),
            degraded=True,
        )

    if pinned:
        return Route(
            model=pinned,
            role=role,
            reason=f"This agent is pinned to {pinned}.",
        )

    chosen = table.get(role)
    if chosen:
        return Route(
            model=chosen,
            role=role,
            reason=f"Routed to the {role} model.",
        )

    if role != ROLE_CHAT:
        return Route(
            model=default,
            role=ROLE_CHAT,
            reason=(
                f"No {role} model is configured, so the default model answered."
            ),
            degraded=True,
        )

    return Route(
        model=default,
        role=ROLE_CHAT,
        reason="Default model.",
    )


def role_for_turn(
    *,
    has_images: bool = False,
    agent_role: str | None = None,
) -> str:
    """What this turn needs.

    An image is a hard requirement and outranks everything: no configured
    preference makes a text-only model able to see a picture.
    """
    if has_images:
        return ROLE_VISION
    if agent_role and agent_role in ROLES:
        return agent_role
    return ROLE_CHAT


__all__ = [
    "ROLES",
    "ROLE_CHAT",
    "ROLE_FAST",
    "ROLE_PURPOSE",
    "ROLE_REASONING",
    "ROLE_TRANSCRIPTION",
    "ROLE_VISION",
    "Route",
    "configured_models",
    "resolve",
    "role_for_turn",
]
