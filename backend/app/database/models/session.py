"""Sign-in sessions.

A session is an opaque random token recorded here rather than a JWT. A JWT
cannot be withdrawn before it expires without a blocklist - which is this
table wearing a disguise - and in a plant where access has to end the moment
someone leaves, revocable beats stateless.

Only the token's SHA-256 is stored. A leaked database therefore yields no
live sessions, for the same reason it yields no passwords.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User


class UserSession(Base, TimestampMixin):
    __tablename__ = "user_sessions"

    #: SHA-256 of the token. The token itself is shown to the client once,
    #: at sign-in, and never stored anywhere.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Bumped on every authenticated request, so an idle session ages out.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Hard stop regardless of activity.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Set on sign-out or when an administrator ends a session. A revoked
    #: row is kept rather than deleted so the audit trail still resolves.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Recorded for the governance view - "which device was this?". Not a
    #: security control; a client can claim anything here.
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    user: Mapped["User"] = relationship()
