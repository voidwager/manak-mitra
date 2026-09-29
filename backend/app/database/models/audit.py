"""Audit log.

Append-only record of who did what. Written today for the mutating
operations the API exposes; expanded to cover tool calls and retrieval
in Phase 16.
"""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # e.g. "document.upload", "agent.create", "conversation.create"
    action: Mapped[str] = mapped_column(String(96), nullable=False, index=True)

    # What was acted on: "document" / "agent" / "conversation" / "tool"
    resource_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="success")

    # Non-sensitive supporting context only. Never store document contents,
    # credentials or tokens here.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")
