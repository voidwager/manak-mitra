"""User and per-user workbench settings."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.agent import Agent
    from app.database.models.audit import AuditLog
    from app.database.models.conversation import Conversation
    from app.database.models.document import Document
    from app.database.models.task import Task


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    initials: Mapped[str] = mapped_column(String(4), nullable=False, default="")

    # Access scope. Enforced server-side today; full RBAC arrives in Phase 16.
    access_level: Mapped[str] = mapped_column(String(32), nullable=False, default="EMPLOYEE")
    scope_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    assigned_folders: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Presentation-only, kept so the existing UI renders unchanged.
    avatar_gradient: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # --- Credentials (Phase 16) ------------------------------------------
    # A scrypt hash, never a plaintext or reversible value. Nullable so a
    # database seeded before authentication existed still loads; a user with
    # no hash simply cannot sign in, which fails closed.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Brute-force resistance. Not a substitute for a rate limiter at the
    # edge - it exists so a forgotten deployment cannot be ground down at
    # leisure. Cleared on a successful sign-in.
    failed_logins: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="owner")
    agents: Mapped[list["Agent"]] = relationship(back_populates="created_by")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    tasks: Mapped[list["Task"]] = relationship(back_populates="user")
    settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserSettings(Base, TimestampMixin):
    """Workbench preferences. Previously held only in browser localStorage."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    compact_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_timestamps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_agent_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    # "Balanced" leaves the tone block in prompts.py to do the work. The old
    # default asked for "the register of an industrial standard operating
    # procedure", which is why every answer read like one.
    response_style: Mapped[str] = mapped_column(
        String(80), nullable=False, default="Balanced"
    )

    user: Mapped["User"] = relationship(back_populates="settings")
