"""Which tools exist, which may run, and running them.

The registry table in the database and the implementations in `builtin/`
are two halves of the same thing, joined by `Tool.id`. A row with no
implementation is catalogued but not callable - that is how `img-analyzer`
sits honestly in the product until the multimodal phase, rather than being
either hidden or pretended into existence.

Three gates decide whether a call runs, and all three already existed as
data that meant nothing before this phase:

  1. `Tool.enabled`        the operator's global switch
  2. `AgentTool`           whether this agent is permitted this tool
  3. the calling user      applied inside the tool, via the same SQL scoping
                           the documents API uses

They are checked in that order, on our side, every time. The model chooses
*what to ask for*; it never chooses what is allowed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.database.models import Agent, Tool as ToolRow
from app.tools.base import (
    Tool,
    ToolContext,
    ToolError,
    ToolPermissionError,
    ToolResult,
)
from app.tools.builtin.calculator import CalculatorTool
from app.tools.builtin.data_analysis import DataAnalysisTool
from app.tools.builtin.document_reader import DocumentReaderTool
from app.tools.builtin.reporting import ReportGeneratorTool
from app.tools.builtin.retrieval import DocumentSearchTool, KnowledgeRetrievalTool

log = get_logger(__name__)

#: Everything with a working implementation, keyed by registry id.
IMPLEMENTATIONS: dict[str, Tool] = {
    tool.id: tool
    for tool in (
        DocumentSearchTool(),
        KnowledgeRetrievalTool(),
        DocumentReaderTool(),
        CalculatorTool(),
        DataAnalysisTool(),
        ReportGeneratorTool(),
    )
}

#: Registry rows with no implementation, and the honest reason. Keeping this
#: explicit means /api/tools can explain the gap instead of the card simply
#: never doing anything when switched on.
NOT_IMPLEMENTED = {
    "img-analyzer": (
        "Needs the image pipeline: uploading a picture into a turn and "
        "sending it to a vision model. Not built yet (Phase 13)."
    ),
}


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolInvocation:
    """One executed call, for the activity trace and the audit log."""

    call: ToolCall
    result: ToolResult
    tool_id: str = ""

    @property
    def ok(self) -> bool:
        return self.result.ok


def implementation_for(tool_id: str) -> Tool | None:
    return IMPLEMENTATIONS.get(tool_id)


def by_wire_name(name: str) -> Tool | None:
    """Find an implementation by the name the model uses."""
    for tool in IMPLEMENTATIONS.values():
        if tool.name == name:
            return tool
    return None


def implemented(tool_row: ToolRow) -> tuple[bool, str]:
    """Whether code exists behind this row and its dependencies are met.

    Deliberately blind to the operator switch. Switching a tool off is a
    decision someone made and can unmake; having no implementation is a
    fact about the build. Folding the two together makes the switch
    one-way - the UI cannot offer to turn a tool back on if being off is
    itself reported as the tool being unavailable.
    """
    if tool_row.id in NOT_IMPLEMENTED:
        return False, NOT_IMPLEMENTED[tool_row.id]

    implementation = IMPLEMENTATIONS.get(tool_row.id)
    if implementation is None:
        return False, "No implementation is registered for this tool."

    return implementation.available()


def describe(tool_row: ToolRow) -> tuple[bool, str]:
    """Whether an agent could call this right now, and why not if it cannot.

    Capability and permission together - see `implemented` for the half
    that ignores the switch.
    """
    available, reason = implemented(tool_row)
    if not available:
        return False, reason
    if not tool_row.enabled:
        return False, "Switched off by an operator."
    return True, ""


def available_for(db, agent: Agent | None) -> list[Tool]:
    """The tools this agent may actually call, in wire order.

    An agent with no tool links gets nothing - tool access is granted, not
    assumed. That is deliberate: an agent silently gaining every tool the
    moment the executor landed would be the opposite of the explicit
    permission model the rest of the system uses.
    """
    if agent is None:
        return []

    enabled_rows = {
        row.id: row
        for row in db.scalars(select(ToolRow).where(ToolRow.enabled.is_(True)))
    }

    tools: list[Tool] = []
    for link in agent.agent_tools:
        if not link.enabled:
            continue
        row = enabled_rows.get(link.tool_id)
        if row is None:
            continue  # globally disabled
        implementation = IMPLEMENTATIONS.get(row.id)
        if implementation is None:
            continue  # catalogued but not executable
        ok, _ = implementation.available()
        if ok:
            tools.append(implementation)
    return tools


def parse_arguments(raw: str | dict | None) -> dict[str, Any]:
    """Model-supplied arguments arrive as a JSON *string* and may be junk."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def execute(
    call: ToolCall, context: ToolContext, permitted: list[Tool]
) -> ToolInvocation:
    """Run one requested call, if it is allowed.

    Never raises for a tool's own failure: the error is returned as content
    so the model can read it and either correct itself or tell the user. A
    tool blowing up should degrade the answer, not the request.
    """
    implementation = next((t for t in permitted if t.name == call.name), None)

    if implementation is None:
        # Either hallucinated, or real but not granted. Both get the same
        # answer - naming which tools exist but are forbidden would be a way
        # to enumerate the registry through an agent that cannot use it.
        known = ", ".join(sorted(t.name for t in permitted)) or "none"
        log.warning(
            "Refused tool call '%s' for agent %s",
            call.name,
            context.agent.id if context.agent else "-",
        )
        return ToolInvocation(
            call=call,
            result=ToolResult.failure(
                f"The tool '{call.name}' is not available to this agent. "
                f"Available tools: {known}. Answer without it."
            ),
        )

    try:
        result = implementation.run(context, **call.arguments)
    except ToolPermissionError as exc:
        result = ToolResult.failure(f"Not permitted: {exc}")
    except ToolError as exc:
        result = ToolResult.failure(str(exc))
    except Exception as exc:  # noqa: BLE001 - a tool must not take down the turn
        log.exception("Tool %s raised", call.name)
        result = ToolResult.failure(
            f"The tool failed unexpectedly ({type(exc).__name__}). Tell the "
            "user the tool could not run rather than guessing its answer."
        )

    return ToolInvocation(call=call, result=result, tool_id=implementation.id)


__all__ = [
    "IMPLEMENTATIONS",
    "NOT_IMPLEMENTED",
    "ToolCall",
    "ToolInvocation",
    "available_for",
    "by_wire_name",
    "describe",
    "execute",
    "implementation_for",
    "parse_arguments",
]
