"""Tools available to agents."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.agent import AgentTool


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="Utility")

    # Global on/off switch. None of these are executable yet - Phase 11.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    agent_tools: Mapped[list["AgentTool"]] = relationship(
        back_populates="tool", cascade="all, delete-orphan"
    )
