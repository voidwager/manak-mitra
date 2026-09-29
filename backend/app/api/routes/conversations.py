"""Conversations and messages."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import ConversationCreate, ConversationOut, ConversationUpdate
from app.database.models import Agent, Conversation, Message
from app.services import audit, reports

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(user: CurrentUser, db: DbSession) -> list[Conversation]:
    """A user only ever receives their own threads."""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages))
        # Pinned threads first, then most recent.
        # id breaks any remaining tie so the order is always stable.
        .order_by(
            Conversation.pinned.desc(),
            Conversation.created_at.desc(),
            Conversation.id.desc(),
        )
    )
    return list(db.scalars(stmt))


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, user: CurrentUser, db: DbSession) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate, user: CurrentUser, db: DbSession
) -> Conversation:
    agent = db.get(Agent, payload.agent_id) if payload.agent_id else None

    conv = Conversation(
        id=f"conv-{uuid.uuid4().hex[:12]}",
        title=payload.title or "New Conversation",
        user_id=user.id,
        agent_id=agent.id if agent else None,
        agent_name=agent.name if agent else payload.agent_name,
    )
    db.add(conv)

    audit.record(
        db,
        user_id=user.id,
        action="conversation.create",
        resource_type="conversation",
        resource_id=conv.id,
    )
    db.commit()
    db.refresh(conv)
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: str, payload: ConversationUpdate, user: CurrentUser, db: DbSession
) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    if payload.title is not None:
        conv.title = payload.title
    if payload.model_override is not None:
        # Empty clears the pin and returns the chat to normal routing.
        conv.model_override = payload.model_override.strip()
        audit.record(
            db,
            user_id=user.id,
            action="conversation.model_override",
            resource_type="conversation",
            resource_id=conv.id,
            detail={"model": conv.model_override or None},
        )
    if payload.pinned is not None:
        conv.pinned = payload.pinned
        audit.record(
            db,
            user_id=user.id,
            action="conversation.pin" if payload.pinned else "conversation.unpin",
            resource_type="conversation",
            resource_id=conv.id,
        )

    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, user: CurrentUser, db: DbSession) -> None:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    audit.record(
        db,
        user_id=user.id,
        action="conversation.delete",
        resource_type="conversation",
        resource_id=conversation_id,
    )
    db.delete(conv)
    db.commit()


@router.post("/{conversation_id}/messages/{message_id}/report")
def generate_message_report(
    conversation_id: str,
    message_id: str,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    """Build the inspection report for one assistant reply.

    Ownership is checked the same way every other route here checks it, and a
    message belonging to somebody else's thread is a 404 rather than a 403 -
    "that is not yours" still confirms it exists.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conv.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")

    try:
        report = reports.generate_for_message(db, user, conv, message)
    except reports.ReportError as exc:
        # A refusal the user can read, not a 500. The reasons are all things
        # they can act on: no provider configured, nothing substantial to
        # report, or the draft came back unusable.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    audit.record(
        db,
        user_id=user.id,
        action="report.generate",
        resource_type="message",
        resource_id=message.id,
        status="ok",
    )
    return {"report": report}
