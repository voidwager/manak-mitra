"""Conversations and messages."""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.agent import Agent
    from app.database.models.user import User


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Conversation")

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Denormalised so a conversation still reads correctly if its agent is
    # later deleted or renamed.
    agent_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")

    # Pinned threads sort above the rest in the sidebar.
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    # Per-chat model override, set from the thread's own settings. Empty
    # means "route normally" - the usual role-based selection applies.
    #
    # Stored provider-qualified ("gemini:gemini-2.5-flash") so a chat pinned
    # to one vendor stays there even if the default provider changes.
    model_override: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    agent: Mapped["Agent | None"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.position",
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 'user' | 'assistant' | 'system'
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Ordering within the thread; created_at alone is not reliable because
    # a user message and its reply can land in the same clock tick.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # DEPRECATED, write-only, never served. Was a pre-rendered "10:24 AM"
    # built from the server's naive local clock, which showed every viewer the
    # server's timezone and let seeded rows carry a hardcoded time. The API now
    # serves `created_at` and the client formats it in the viewer's own
    # timezone. Nothing writes this any more; the Python-side default fills it
    # so inserts stay valid on databases created before the change.
    #
    # The column is not dropped here because `_ADDITIVE_COLUMNS` in
    # database/session.py is an additive-only stopgap - it cannot express a
    # drop. Remove it with the first real Alembic migration.
    display_timestamp: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    # Primary citation for the assistant answer, when one exists. Always
    # the highest-scoring retrieved passage, and always a real one: this is
    # written from the retrieval result, never parsed out of model output.
    # Shape: {documentId, title, page, section, excerpt, score}
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Every passage that was placed in the prompt, in rank order. `source`
    # is sources[0]; both are kept because the UI shows one prominently and
    # the rest in a list.
    # Shape: [{documentId, title, page, section, excerpt, score}]
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # High-level execution events only - never chain-of-thought.
    # Shape: [{label, status}]
    activity_trace: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Files attached by the user. Shape: [{id, name, size, type}]
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # A generated inspection report, when one was produced from this reply.
    # Stored rather than rebuilt on demand: a report is a record of what the
    # system held at the moment it was asked, and regenerating it later
    # against a changed corpus would quietly produce a different document
    # under the same heading.
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
