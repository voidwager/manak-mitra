"""Declarative base and shared column mixins."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at / updated_at on every table."""

    # `default=` (Python side) rather than relying on server_default alone.
    # SQLite's CURRENT_TIMESTAMP has one-second resolution, so two rows
    # created in the same second got identical timestamps and anything
    # ordered by created_at came back in arbitrary order - visible as chats
    # shuffling in the sidebar when you start two quickly.
    # server_default stays as a fallback for rows inserted outside the ORM.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
