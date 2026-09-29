"""Agent catalogue, configuration and lifecycle.

An agent is a saved configuration: a persona (name, description,
instructions), a retrieval scope, and a set of tools it is permitted to
call. What it can actually *do* with that configuration depends on the
running system, so the API derives `status` and `capabilities` per request
rather than reporting stored strings - see `app/services/agents.py` for why
that distinction is load-bearing.

Access: an agent is a shared object, so everyone signed in can list and use
one. Editing is restricted to its creator or owner clearance, and system
agents cannot be deleted at all - they ship with the product, and a demo
that has had its built-in agents deleted is not recoverable without a
reseed.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import AgentCreate, AgentModelRoute, AgentOut, AgentUpdate
from app.database.models import Agent, AgentTool, Tool, User
from app.models import get_gateway
from app.models import router as model_router
from app.models.registry import get_registry
from app.services import agents as agent_service
from app.services import audit
from app.services.access import is_administrator, is_guest

router = APIRouter(prefix="/agents", tags=["agents"])

#: The only two values the stored `status` column may take. Availability is
#: derived; this is just an operator's on/off switch.
STORED_STATUSES = {"Online", "Offline"}


def _transcription_is_wired() -> bool:
    """Whether anything in the application can actually transcribe audio.

    Derived rather than asserted, and deliberately so: the last hardcoded
    "not implemented yet" in this codebase stayed false for three phases
    after it became true, and every agent card understated itself as a
    result. This flips on its own the moment a transcription service module
    exists.
    """
    try:
        import app.services.transcription  # noqa: F401
    except ImportError:
        return False
    return True


def _model_routes(db: Session, agent: Agent) -> list[AgentModelRoute]:
    """Every model this agent commands, and whether each really works.

    SI-1 gets the whole table because it fronts the whole table. A
    specialist gets the role it answers on, plus vision when it holds a
    vision tool - an image turn ignores an agent's preference, so a vision
    agent genuinely runs on two models.
    """
    gateway = get_gateway()
    registry = get_registry()
    configured = model_router.configured_models()

    if agent.is_universal:
        roles = [r for r in model_router.ROLES if r in configured]
    else:
        roles = [agent.model_role or model_router.ROLE_CHAT]
        if {t.category for t in agent.tools} & agent_service.VISION_CATEGORIES:
            if model_router.ROLE_VISION in configured:
                roles.append(model_router.ROLE_VISION)

    out: list[AgentModelRoute] = []
    for role in dict.fromkeys(roles):  # de-duplicate, keep order
        route = model_router.resolve(
            role, pinned=(agent.model or None) if role != model_router.ROLE_VISION else None
        )
        if not route.model:
            continue
        provider, bare = registry.resolve(route.model)

        available, detail = True, ""
        if not gateway.is_configured:
            available, detail = False, "No inference provider is configured."
        elif role == model_router.ROLE_TRANSCRIPTION and not _transcription_is_wired():
            available, detail = (
                False,
                "Configured, but nothing reaches it yet - there is no "
                "transcription endpoint, so the microphone does not use this.",
            )
        elif role == model_router.ROLE_VISION and not gateway.model_accepts_images(
            route.model
        ):
            available, detail = False, f"{bare} does not accept image input."

        out.append(
            AgentModelRoute(
                role=role,
                model=bare,
                provider=provider.name,
                purpose=model_router.ROLE_PURPOSE.get(role, ""),
                available=available,
                detail=detail,
            )
        )
    return out


def _validated_pin(value: str) -> str:
    """Check a model pin against what this deployment is configured to serve.

    An empty string clears the pin, which is the normal case: most agents
    should follow the role table so that changing .env changes every agent
    at once.

    A pin naming something not in the configured routes is rejected here
    rather than accepted and left to fail at the provider on the user's next
    question, where it would surface as an opaque 404 with no hint that an
    agent setting caused it.
    """
    pin = (value or "").strip()
    if not pin:
        return ""

    allowed = set(model_router.configured_models().values())
    if pin not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{pin}' is not one of this deployment's configured models "
            f"({sorted(allowed)}). Add it to .env before pinning an agent to it.",
        )
    return pin


def _serialise(db: Session, agent: Agent) -> AgentOut:
    """Build the response, deriving everything that depends on the runtime.

    `Agent.model` is an optional pin reserved for model routing (Phase 14).
    Nothing sets one, so the honest answer for "what model serves this
    agent" is whatever the gateway is configured with - not a label stored
    months ago.
    """
    capabilities = agent_service.derive_capabilities(agent)
    gateway = get_gateway()

    # Resolve the route now rather than reporting a stored model id, for the
    # same reason status is derived: what will actually serve this agent
    # depends on the running configuration.
    route = model_router.resolve(
        agent.model_role or model_router.ROLE_CHAT,
        pinned=agent.model or None,
    )

    registry = get_registry()
    primary_provider, primary_bare = (
        registry.resolve(route.model) if route.model else (None, "")
    )

    # Only when the agent actually reads images, and only when that lands
    # somewhere different - repeating the same id twice tells nobody anything.
    vision_model = vision_provider = ""
    if {t.category for t in agent.tools} & agent_service.VISION_CATEGORIES:
        vision_route = model_router.resolve(model_router.ROLE_VISION)
        if vision_route.model and vision_route.model != route.model:
            provider, bare = registry.resolve(vision_route.model)
            vision_model, vision_provider = bare, provider.name

    return AgentOut(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        status=agent_service.derive_status(agent, capabilities),
        status_detail=agent_service.status_detail(agent, capabilities),
        # The router resolves against configuration; the gateway is what
        # actually serves. When a role has no model of its own the route is
        # empty, and the honest answer is whatever the gateway will use.
        model=(primary_bare or gateway.model) if gateway.is_configured else "No model configured",
        model_role=agent.model_role or model_router.ROLE_CHAT,
        model_role_reason=route.reason,
        icon=agent.icon,
        capabilities=[c.as_dict() for c in capabilities],
        specialisations=list(agent.capabilities or []),
        tools=sorted(t.name for t in agent.tools),
        retrieval_enabled=agent.retrieval_enabled,
        folder_scope=list(agent.folder_scope or []),
        retrieval_top_k=agent.retrieval_top_k,
        model_pin=agent.model or "",
        model_provider=primary_provider.name if primary_provider else "",
        vision_model=vision_model,
        vision_provider=vision_provider,
        model_routes=_model_routes(db, agent),
        is_system=agent.is_system,
        is_universal=agent.is_universal,
        created_by_id=agent.created_by_id,
    )


def _can_edit(user: User, agent: Agent) -> bool:
    """Creator or owner clearance. System agents are administrator-only."""
    if is_administrator(user):
        return True
    if agent.is_system:
        return False
    return agent.created_by_id == user.id


def _link_tools(db: Session, agent: Agent, tool_names: list[str]) -> None:
    """Replace an agent's tool links with the named set.

    Display names are mapped onto real rows so the link is a foreign key
    rather than a string we hope matches later. An unknown name is dropped
    rather than stored, since a dangling tool reference would show up as a
    capability the agent does not have.
    """
    agent.agent_tools.clear()
    db.flush()

    if not tool_names:
        return

    for tool in db.scalars(select(Tool).where(Tool.name.in_(tool_names))).all():
        db.add(AgentTool(agent_id=agent.id, tool_id=tool.id, enabled=True))
    db.flush()


@router.get("", response_model=list[AgentOut])
def list_agents(user: CurrentUser, db: DbSession) -> list[AgentOut]:
    agents = list(
        db.scalars(select(Agent).order_by(Agent.is_system.desc(), Agent.created_at.desc()))
    )
    return [_serialise(db, a) for a in agents]


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, user: CurrentUser, db: DbSession) -> AgentOut:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return _serialise(db, agent)


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, user: CurrentUser, db: DbSession) -> AgentOut:
    # Every agent is listed for every user, so a visitor's agent would be
    # published to the whole public - persona, instructions and all.
    if is_guest(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Visitors can use the assistants but not create new ones.",
        )
    agent = Agent(
        id=f"agent-{uuid.uuid4().hex[:12]}",
        name=payload.name.strip(),
        description=payload.description.strip() or "Custom agent.",
        instructions=payload.instructions.strip(),
        model=_validated_pin(payload.model),
        icon=payload.icon,
        # Stated focus areas. Previously this column was filled with the tool
        # names, which made one field mean two different things depending on
        # whether the agent was seeded or user-built.
        capabilities=payload.specialisations,
        retrieval_enabled=payload.retrieval_enabled,
        folder_scope=payload.folder_scope,
        retrieval_top_k=payload.retrieval_top_k,
        model_role=payload.model_role,
        is_system=False,
        created_by_id=user.id,
    )
    db.add(agent)
    db.flush()

    _link_tools(db, agent, payload.tools)

    audit.record(
        db,
        user_id=user.id,
        action="agent.create",
        resource_type="agent",
        resource_id=agent.id,
        detail={"name": agent.name, "folder_scope": payload.folder_scope},
    )
    db.commit()
    db.refresh(agent)
    return _serialise(db, agent)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str, payload: AgentUpdate, user: CurrentUser, db: DbSession
) -> AgentOut:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    if not _can_edit(user, agent):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            (
                "Built-in agents can only be changed with owner clearance."
                if agent.is_system
                else "You can only edit agents you created."
            ),
        )

    if payload.status is not None and payload.status not in STORED_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of {sorted(STORED_STATUSES)}. Availability is "
            "derived from the running system and cannot be set by hand.",
        )

    before = {
        "name": agent.name,
        "folder_scope": list(agent.folder_scope or []),
        "retrieval_enabled": agent.retrieval_enabled,
        "status": agent.status,
        "model": agent.model,
    }

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "An agent name cannot be empty."
            )
        agent.name = name
    if payload.description is not None:
        agent.description = payload.description.strip()
    if payload.instructions is not None:
        agent.instructions = payload.instructions.strip()
    if payload.icon is not None:
        agent.icon = payload.icon
    if payload.specialisations is not None:
        agent.capabilities = payload.specialisations
    if payload.retrieval_enabled is not None:
        agent.retrieval_enabled = payload.retrieval_enabled
    if payload.folder_scope is not None:
        # Not validated against the editor's own folders on purpose: a scope
        # narrows whoever *uses* the agent, and is intersected with that
        # caller's permissions at query time. Naming a folder here grants
        # nobody anything.
        agent.folder_scope = [f for f in payload.folder_scope if f.strip()]
    if payload.retrieval_top_k is not None:
        agent.retrieval_top_k = payload.retrieval_top_k
    if payload.model_role is not None:
        # Vision is excluded on purpose: it is forced by a turn that carries
        # an image, never chosen ahead of time.
        selectable = {
            model_router.ROLE_CHAT,
            model_router.ROLE_REASONING,
            model_router.ROLE_FAST,
        }
        if payload.model_role not in selectable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"model_role must be one of {sorted(selectable)}. Vision is "
                "selected automatically for turns that include an image.",
            )
        agent.model_role = payload.model_role
    if payload.model is not None:
        agent.model = _validated_pin(payload.model)
    if payload.status is not None:
        agent.status = payload.status
    if payload.tools is not None:
        _link_tools(db, agent, payload.tools)

    audit.record(
        db,
        user_id=user.id,
        action="agent.update",
        resource_type="agent",
        resource_id=agent.id,
        detail={
            "before": before,
            "after": {
                "name": agent.name,
                "folder_scope": list(agent.folder_scope or []),
                "retrieval_enabled": agent.retrieval_enabled,
                "status": agent.status,
                "model": agent.model,
            },
        },
    )
    db.commit()
    db.refresh(agent)
    return _serialise(db, agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: str, user: CurrentUser, db: DbSession) -> None:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    if agent.is_system:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Built-in agents cannot be deleted. Set status to 'Offline' to "
            "retire one instead.",
        )
    if not _can_edit(user, agent):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only delete agents you created."
        )

    # Conversations keep their agent_name (denormalised for exactly this),
    # so history still reads correctly once the agent is gone.
    audit.record(
        db,
        user_id=user.id,
        action="agent.delete",
        resource_type="agent",
        resource_id=agent.id,
        detail={"name": agent.name},
    )
    db.delete(agent)
    db.commit()
