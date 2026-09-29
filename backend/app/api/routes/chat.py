"""Chat endpoints.

Two shapes of the same operation:

  POST /api/chat          - wait for the whole reply
  POST /api/chat/stream   - server-sent events, token by token

Both persist the user message before calling the model, so an inference
failure never loses what the user typed. On failure the API returns a real
error; it does not invent a reply or dress the failure up as an answer.

Retrieval happens once per turn, before generation, and the passages it
returns are carried through to the persisted reply as its citations - see
`chat_service.Turn`.
"""

import json
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import ChatRequest, ChatResponse, MessageOut
from app.core.logging import get_logger
from app.database.models import Agent, Conversation, User
from app.database.session import SessionLocal
from app.models import ModelError, get_gateway
from app.services import audit, chat_service

router = APIRouter(tags=["chat"])
log = get_logger(__name__)


def _attachment_dicts(payload: ChatRequest) -> list[dict]:
    return [a.model_dump(by_alias=False) for a in payload.attachments]


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user: CurrentUser, db: DbSession) -> ChatResponse:
    agent = db.get(Agent, payload.agent_id) if payload.agent_id else None
    attachments = _attachment_dicts(payload)

    conversation = chat_service.get_or_create_conversation(
        db, user, payload.conversation_id, agent
    )
    user_msg = chat_service.append_user_message(
        db, conversation, payload.message, attachments
    )

    # Commit the user's turn before inference so it survives a model failure.
    db.commit()
    db.refresh(user_msg)
    db.refresh(conversation)

    turn = chat_service.prepare_turn(
        db, conversation, user, agent, payload.message, attachments
    )

    try:
        assistant_msg, provider, model = chat_service.generate_reply(
            db, conversation, turn, user
        )
    except ModelError as exc:
        audit.record(
            db,
            user_id=user.id,
            action="chat.message",
            resource_type="conversation",
            resource_id=conversation.id,
            status="failed",
            detail={"provider": exc.provider, "error": type(exc).__name__},
        )
        db.commit()
        log.warning("Inference failed (%s): %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "message": str(exc),
                "conversationId": conversation.id,
                "userMessageId": user_msg.id,
            },
        ) from exc

    audit.record(
        db,
        user_id=user.id,
        action="chat.message",
        resource_type="conversation",
        resource_id=conversation.id,
        detail={
            "agent_id": agent.id if agent else None,
            "attachment_count": len(attachments),
            "provider": provider,
            "model": model,
            # Auditors need to know which documents fed an answer, not just
            # that an answer happened.
            "retrieval_mode": turn.retrieval.mode,
            "retrieved_document_ids": sorted(
                {p.document_id for p in turn.retrieval.passages}
            ),
            # What the agent actually did, not what it was permitted to do.
            "tool_calls": [
                {
                    "name": i.call.name,
                    "arguments": i.call.arguments,
                    "ok": i.ok,
                }
                for i in turn.invocations
            ],
        },
    )
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        conversation_id=conversation.id,
        user_message=user_msg,
        assistant_message=assistant_msg,
        provider=provider,
        model=model,
        retrieval_mode=turn.retrieval.mode,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
def _sse(event: str, data: dict) -> str:
    # `default=` rather than pre-converting at each call site: message
    # payloads carry timezone-aware datetimes (Message.created_at), and a
    # stream event that cannot serialise is a 500 in the middle of an
    # answer rather than anything a type checker would catch. isoformat()
    # keeps the offset, which is what the client needs to render the time
    # in the viewer's own timezone.
    return f"event: {event}\ndata: {json.dumps(data, default=_json_default)}\n\n"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, user: CurrentUser, db: DbSession):
    """Stream the reply as server-sent events.

    Events: `start`, `tool`, `delta`, `done`, `error`.
    `tool` is emitted once per executed call, before generation begins.
    Citations arrive with `done`, because only the finished answer says
    which passages it actually used.

    The generator opens its own database session. The request-scoped one is
    closed when the handler returns, which for a StreamingResponse happens
    before the body has been produced.
    """
    agent = db.get(Agent, payload.agent_id) if payload.agent_id else None
    attachments = _attachment_dicts(payload)

    conversation = chat_service.get_or_create_conversation(
        db, user, payload.conversation_id, agent
    )
    user_msg = chat_service.append_user_message(
        db, conversation, payload.message, attachments
    )
    db.commit()
    db.refresh(user_msg)

    conversation_id = conversation.id
    agent_id = agent.id if agent else None
    user_id = user.id
    user_message_payload = MessageOut.model_validate(user_msg).model_dump(by_alias=True)
    conversation_title = conversation.title

    def event_stream() -> Iterator[str]:
        yield _sse(
            "start",
            {
                "conversationId": conversation_id,
                "conversationTitle": conversation_title,
                "userMessage": user_message_payload,
            },
        )

        gateway = get_gateway()
        collected: list[str] = []

        with SessionLocal() as session:
            conv = session.get(Conversation, conversation_id)
            agent_row = session.get(Agent, agent_id) if agent_id else None
            actor = session.get(User, user_id)

            turn = chat_service.prepare_turn(
                session, conv, actor, agent_row, payload.message, attachments
            )

            # Tools run before the first token: a call arrives as a
            # structured field rather than as prose, so it cannot be
            # streamed, and the user would otherwise watch an empty bubble
            # while it happened.
            chat_service.resolve_tools_for_stream(session, actor, turn)
            for invocation in turn.invocations:
                yield _sse(
                    "tool",
                    {
                        "name": invocation.call.name,
                        "arguments": invocation.call.arguments,
                        "ok": invocation.ok,
                    },
                )

            # Sources are deliberately NOT emitted here any more. Retrieval
            # runs on every turn, so what it found and what the answer
            # actually cites are different sets - a greeting matches
            # something, and showing those as sources before the reply
            # exists is the same overstatement, just earlier. The `done`
            # event carries the citations the finished answer really used.

            # Scratchpad blocks are suppressed as they stream, not after.
            # Stripping only the finished reply still puts the model's
            # deliberation on screen first and then deletes it, which reads
            # as a bug even though the stored message is clean.
            scratchpad = chat_service.ScratchpadFilter()

            try:
                for chunk in chat_service.stream_reply(turn):
                    visible = scratchpad.feed(chunk)
                    if visible:
                        collected.append(visible)
                        yield _sse("delta", {"text": visible})

                tail = scratchpad.flush()
                if tail:
                    collected.append(tail)
                    yield _sse("delta", {"text": tail})

            except ModelError as exc:
                audit.record(
                    session,
                    user_id=user_id,
                    action="chat.message",
                    resource_type="conversation",
                    resource_id=conversation_id,
                    status="failed",
                    detail={"provider": exc.provider, "error": type(exc).__name__},
                )
                session.commit()
                log.warning("Streaming inference failed (%s): %s", type(exc).__name__, exc)
                yield _sse("error", {"message": str(exc), "status": exc.http_status})
                return

            text = chat_service.strip_tool_markup("".join(collected))
            if not text:
                yield _sse(
                    "error",
                    {"message": "The model returned an empty response.", "status": 502},
                )
                return

            stream_provider, stream_model, _ = chat_service.streamed_provenance(turn)
            assistant_msg = chat_service.persist_streamed_reply(
                session, conv, turn, text
            )

            audit.record(
                session,
                user_id=actor.id if actor else None,
                action="chat.message",
                resource_type="conversation",
                resource_id=conversation_id,
                detail={
                    "agent_id": agent_id,
                    "attachment_count": len(attachments),
                    # Same source as the activity trace. Reading these off
                    # the gateway reported the default provider rather than
                    # the routed one, so the badge and the trace could
                    # disagree about who generated the reply.
                    "provider": stream_provider,
                    "model": stream_model,
                    "streamed": True,
                    "retrieval_mode": turn.retrieval.mode,
                    "retrieved_document_ids": sorted(
                        {p.document_id for p in turn.retrieval.passages}
                    ),
                    "tool_calls": [
                        {
                            "name": i.call.name,
                            "arguments": i.call.arguments,
                            "ok": i.ok,
                        }
                        for i in turn.invocations
                    ],
                },
            )
            session.commit()
            session.refresh(assistant_msg)

            yield _sse(
                "done",
                {
                    "conversationId": conversation_id,
                    "assistantMessage": MessageOut.model_validate(
                        assistant_msg
                    ).model_dump(by_alias=True),
                    # Same source as the activity trace. Reading these off
                    # the gateway reported the default provider rather than
                    # the routed one, so the badge and the trace could
                    # disagree about who generated the reply.
                    "provider": stream_provider,
                    "model": stream_model,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Stops nginx buffering the stream into one lump.
            "X-Accel-Buffering": "no",
        },
    )
