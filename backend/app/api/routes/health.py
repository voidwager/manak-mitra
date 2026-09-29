"""Health, capability and model-provider reporting.

`implemented` and `inference` are deliberately part of the payload: the
frontend labels itself from them, so the UI can never claim a capability the
backend does not have. In particular `inference.onPremise` is derived from
the active provider - it is never asserted.
"""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DbSession
from app.api.schemas import (
    AttachmentLimits,
    HealthResponse,
    InferenceStatus,
    ModelCatalogue,
    ModelRoute,
    SelectableModel,
    RetrievalStatus,
)
from app.core.config import settings
from app.models import get_gateway
from app.models import router as model_router
from app.models.registry import get_registry
from app.rag.embeddings import get_embedding_gateway
from app.rag.extraction import describe_support

router = APIRouter(tags=["system"])


def _inference_status() -> InferenceStatus:
    gateway = get_gateway()

    if not gateway.is_configured:
        summary = "No inference provider configured"
    elif gateway.is_on_premise:
        summary = f"On-premise inference ({gateway.model})"
    else:
        summary = (
            f"External inference provider '{gateway.provider_name}' "
            f"({gateway.model}) - prototype, not sovereign"
        )

    return InferenceStatus(
        provider=gateway.provider_name,
        model=gateway.model or None,
        configured=gateway.is_configured,
        on_premise=gateway.is_on_premise,
        summary=summary,
    )


def _retrieval_status() -> RetrievalStatus:
    """Report what retrieval can do, derived from the running configuration.

    Lexical BM25 needs nothing, so retrieval is available whenever it is not
    switched off. Semantic search is additive and only claimed when an
    embedding provider is actually configured.
    """
    embedder = get_embedding_gateway()

    if not settings.rag_enabled:
        mode = "disabled"
        summary = "Retrieval is disabled on this server"
    elif embedder.is_configured:
        mode = "hybrid"
        where = "on-premise" if embedder.is_on_premise else "external provider"
        summary = (
            f"Hybrid retrieval - keyword (BM25) fused with semantic search "
            f"({embedder.model} via {where})"
        )
    else:
        mode = "lexical"
        summary = (
            "Keyword retrieval (BM25) only - no embedding provider is "
            "configured, so semantic search is off"
        )

    return RetrievalStatus(
        enabled=settings.rag_enabled,
        mode=mode,
        embedding_provider=embedder.provider_name,
        embedding_model=embedder.model or None,
        embedding_configured=embedder.is_configured,
        embedding_on_premise=embedder.is_on_premise,
        extractable=describe_support(),
        summary=summary,
    )


def _attachment_limits() -> AttachmentLimits:
    """Read from the attachment route's own constants, not restated here.

    Two copies of "what can be attached" is what produced the bug this
    exists to prevent, so this reads the same sets the endpoint enforces.
    """
    from app.api.routes.attachments import (
        ALLOWED_SUFFIXES,
        DOCUMENT_SUFFIXES,
        IMAGE_SUFFIXES,
        MAX_ATTACHMENT_BYTES,
    )

    return AttachmentLimits(
        accepted=sorted(ALLOWED_SUFFIXES),
        indexed=sorted(DOCUMENT_SUFFIXES - IMAGE_SUFFIXES),
        max_bytes=MAX_ATTACHMENT_BYTES,
    )


@router.get("/health", response_model=HealthResponse)
def health(db: DbSession) -> HealthResponse:
    connected = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health check must not raise
        connected = False

    inference = _inference_status()
    retrieval = _retrieval_status()

    vision_route = model_router.resolve(model_router.ROLE_VISION)
    gateway_accepts_images = (
        get_gateway().model_accepts_images(vision_route.model)
        if vision_route.model and not vision_route.degraded
        else False
    )

    return HealthResponse(
        status="ok" if connected else "degraded",
        app=settings.app_name,
        environment=settings.app_env,
        database="sqlite (development fallback)" if settings.is_sqlite else "postgresql",
        database_connected=connected,
        inference=inference,
        retrieval=retrieval,
        attachments=_attachment_limits(),
        # Kept for backwards compatibility with the earlier client.
        model_provider=inference.provider,
        implemented={
            "database": connected,
            "conversations": True,
            "documentUpload": True,
            # Indexing and retrieval need no model - BM25 is pure Python -
            # so these are true whenever retrieval is enabled.
            "documentIndexing": retrieval.enabled,
            "retrieval": retrieval.enabled,
            # True only when an embedding provider is configured.
            "semanticRetrieval": retrieval.enabled and retrieval.embedding_configured,
            "citations": retrieval.enabled,
            "modelInference": inference.configured,
            "streaming": inference.configured,
            # Vision is claimed only when a model that accepts images is
            # actually routed to - not because the catalogue contains one.
            "vision": bool(
                model_router.configured_models().get(model_router.ROLE_VISION)
            )
            and gateway_accepts_images,
            "modelRouting": len(model_router.configured_models()) > 1,
            "toolCalling": True,
            # Real now: passwords are hashed, sessions are revocable, and
            # the spoofable identity header is gone.
            "authentication": True,
            "auditTrail": True,
            "onPremiseInference": inference.on_premise,
            "onPremiseEmbeddings": retrieval.embedding_on_premise,
        },
    )


@router.get("/models", response_model=ModelCatalogue)
def list_models() -> ModelCatalogue:
    """Model identifiers the active provider can serve.

    Provider catalogues change over time, so MODEL_NAME has no default in
    config - use this endpoint to find a currently valid identifier instead
    of guessing one.
    """
    gateway = get_gateway()
    configured = model_router.configured_models()

    routes = []
    for role in model_router.ROLES:
        route = model_router.resolve(role)
        routes.append(
            ModelRoute(
                role=role,
                model=route.model or "",
                purpose=model_router.ROLE_PURPOSE.get(role, ""),
                # False when the role fell back to the default rather than
                # having a model of its own.
                configured=role in configured,
                accepts_images=gateway.model_accepts_images(route.model)
                if route.model
                else False,
            )
        )

    # What a chat may be pinned to. Built from the configured routes rather
    # than from a provider's whole catalogue: those are the models this
    # deployment is actually set up to use, and offering the rest would let
    # someone pin a chat to a model that has never been tried.
    registry = get_registry()
    seen: set[str] = set()
    selectable: list[SelectableModel] = []

    for role in model_router.ROLES:
        if role == model_router.ROLE_TRANSCRIPTION:
            continue  # not a chat model
        route = model_router.resolve(role)
        if not route.model or route.model in seen:
            continue
        seen.add(route.model)

        provider, bare = registry.resolve(route.model)
        selectable.append(
            SelectableModel(
                id=route.model,
                label=bare,
                provider=provider.name,
                note=model_router.ROLE_PURPOSE.get(role, ""),
                accepts_images=gateway.model_accepts_images(route.model),
            )
        )

    return ModelCatalogue(
        provider=gateway.provider_name,
        configured=gateway.is_configured,
        selected=gateway.model or None,
        available=gateway.list_models(),
        routes=routes,
        selectable=selectable,
        providers=registry.names,
    )
