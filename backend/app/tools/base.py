"""Tool interface.

A tool is a function the model may ask us to run. The model does not run
it - it emits a request, and this layer decides whether that request is
allowed, executes it, and hands back a result. Everything the model says
about which tool to call is a *suggestion*; every gate lives on our side.

Three rules the whole layer depends on:

1. **The caller's permissions bound the tool, not the agent's ambitions.**
   A tool that reads documents is handed the signed-in user and searches
   what that user may see. An agent configured to search everything cannot
   read a folder its user is not assigned to.

2. **Results are untrusted input.** A retrieved passage that reads "ignore
   your previous instructions" is a real attack surface once tool output
   flows back into the prompt. Results are fenced and labelled as data, and
   the guardrail stays last in the prompt.

3. **A tool that cannot run says so.** No tool returns a plausible-looking
   placeholder. `available()` reports whether the runtime can honour it, and
   an unavailable tool is never offered to the model in the first place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import Agent, User


class ToolError(Exception):
    """A tool could not complete. The message is shown to the model."""


class ToolPermissionError(ToolError):
    """The caller or agent is not permitted to run this tool."""


class ToolArgumentError(ToolError):
    """The model called the tool with arguments it cannot satisfy."""


@dataclass
class ToolContext:
    """Everything a tool is allowed to know about the turn it runs in.

    Deliberately narrow. A tool gets the database session, the *user* whose
    permissions apply, and the agent that requested it - not the raw request,
    not the conversation history, and no way to reach the model.
    """

    db: Session
    user: User
    agent: Agent | None = None

    #: Provenance accumulated during this turn, filled in by the executor as
    #: tools run. A report tool can then assemble a document from what
    #: actually happened rather than from what the model remembers happening.
    turn_citations: list[dict] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    #: The user's original message, for tools that summarise the turn.
    question: str = ""

    #: Which conversation this turn belongs to. Retrieval tools pass it on
    #: so a file attached to this chat is findable here - and only here.
    #: Without it the tool path and the automatic retrieval path would
    #: disagree about what exists, which is worse than neither seeing it.
    conversation_id: str | None = None

    #: The folder narrowing that applies to this turn, decided once by the
    #: caller. `None` means "work it out from the agent" and is what a tool
    #: invoked outside a turn gets.
    #:
    #: It exists because the agent alone is not enough to answer the
    #: question. When SI-1 routes a question to a specialist on its own, that
    #: specialist's folder scope is a routing artifact rather than a
    #: restriction anyone placed on this user - and applying it turns "you
    #: are cleared for this document" into "this document does not exist".
    #: Whoever builds the turn knows which case it is; a tool does not.
    folder_scope: list[str] | None = None

    def search_scope(self) -> list[str]:
        """Folders this tool may search, honouring the turn's decision."""
        from app.services.agents import effective_folder_scope

        if self.folder_scope is not None:
            return self.folder_scope
        return effective_folder_scope(self.agent)


@dataclass
class ToolResult:
    """What a tool produced.

    `content` is what the model sees. `citations` are attached to the reply
    the same way retrieval citations are, so a tool that reads documents
    produces checkable answers rather than confident prose.
    """

    content: str
    ok: bool = True
    citations: list[dict] = field(default_factory=list)
    #: Structured payload for the UI, when the tool produces more than text.
    data: dict[str, Any] | None = None

    @classmethod
    def failure(cls, message: str) -> "ToolResult":
        return cls(content=message, ok=False)


class Tool(ABC):
    """One callable function."""

    #: Must match the `Tool.id` of the registry row this implements, so the
    #: database toggle and the implementation cannot drift apart.
    id: str = ""

    #: The name the model sees. OpenAI-style: letters, digits, underscores.
    name: str = ""

    #: Shown to the model to help it decide when to call this. Write it for
    #: the model, not for a human reading documentation.
    description: str = ""

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for the arguments, in the function-calling format."""
        return {"type": "object", "properties": {}, "required": []}

    def available(self) -> tuple[bool, str]:
        """Whether this tool can run right now, and why not if it cannot."""
        return True, ""

    @abstractmethod
    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute. Raise `ToolError` for anything the model should see."""

    def as_schema(self) -> dict[str, Any]:
        """The wire format every OpenAI-compatible runtime accepts."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


__all__ = [
    "Tool",
    "ToolArgumentError",
    "ToolContext",
    "ToolError",
    "ToolPermissionError",
    "ToolResult",
]
