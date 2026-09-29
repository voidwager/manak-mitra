"""Agents and the tools attached to them."""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.conversation import Conversation
    from app.database.models.tool import Tool
    from app.database.models.user import User


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # NOT the status the API reports. Availability depends on whether a model
    # is configured and whether the agent's declared tools can actually run,
    # neither of which a stored string can know - so the API derives status
    # per request (see app/services/agents.py) and this column is only a
    # manual off switch for an agent an operator wants retired.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Online")

    # Optional per-agent model pin, reserved for model routing (Phase 14).
    # Nothing sets it yet; the API reports the gateway's actual model instead.
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="")

    icon: Mapped[str] = mapped_column(String(64), nullable=False, default="Bot")

    # The author's stated focus areas - "Failure Diagnosis", "LOTO Guidance".
    # These are intent, not capability: they are free text and nothing checks
    # them. The API exposes this column as `specialisations` and reports a
    # separately *derived* `capabilities` list for what the agent can really
    # do, because a chip claiming "OCR Text Extraction" next to a deployment
    # with no OCR is exactly the kind of claim this project does not make.
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # --- Retrieval configuration (Phase 10) -----------------------------
    # What actually differentiates one agent from another now that retrieval
    # exists. Without this every agent searches the same corpus identically
    # and only the prompt wording differs.
    retrieval_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # Folders this agent may search. Empty means "everything the user can
    # see". This can only ever NARROW the caller's own access - it is
    # intersected with their permissions, never unioned - so an agent can
    # never become a way to read a folder you are not assigned to.
    folder_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Per-agent passage count. NULL uses the server default (RAG_TOP_K).
    retrieval_top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Model routing (Phase 14) ---------------------------------------
    # Which routed role this agent's turns prefer: "chat", "reasoning" or
    # "fast". A role rather than a model id, so it survives a provider
    # renaming its catalogue and so the intent stays readable.
    #
    # A turn carrying an image ignores this. No preference makes a text-only
    # model able to see a picture.
    model_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="chat", server_default="chat"
    )

    # Built-in agents ship with the product; user-built ones do not.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # SI-1. The universal assistant that dispatches to the specialists rather
    # than being one of them, so a user does not have to know which
    # specialist they need before they know what they are asking.
    is_universal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_by: Mapped["User | None"] = relationship(back_populates="agents")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent")
    agent_tools: Mapped[list["AgentTool"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    @property
    def tools(self) -> list["Tool"]:
        return [at.tool for at in self.agent_tools if at.tool is not None]


class AgentTool(Base, TimestampMixin):
    """Join table: which tools an agent is permitted to call."""

    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Per-agent override. Phase 11 (tool router) reads this.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    agent: Mapped["Agent"] = relationship(back_populates="agent_tools")
    tool: Mapped["Tool"] = relationship(back_populates="agent_tools")
