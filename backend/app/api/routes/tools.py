"""Tool registry.

A row here and an implementation in `app/tools/builtin/` are two halves of
the same tool, joined by id. Most rows now have both; `img-analyzer` has
only the row, and says so rather than being hidden or pretended into
existence.

The `enabled` toggle is an operator switch and it is load-bearing since
Phase 11: turning a tool off removes it from what agents are offered, so
no model can call it. That is a real gate now, not recorded intent.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import ToolOut
from app.database.models import Tool
from app.services import audit
from app.tools import registry

router = APIRouter(prefix="/tools", tags=["tools"])


def _serialise(tool: Tool) -> ToolOut:
    executable, reason = registry.describe(tool)
    built, _ = registry.implemented(tool)
    implementation = registry.implementation_for(tool.id)
    return ToolOut(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        category=tool.category,
        enabled=tool.enabled,
        executable=executable,
        implemented=built,
        unavailable_reason=reason,
        wire_name=implementation.name if implementation else "",
    )


@router.get("", response_model=list[ToolOut])
def list_tools(user: CurrentUser, db: DbSession) -> list[ToolOut]:
    return [
        _serialise(t) for t in db.scalars(select(Tool).order_by(Tool.created_at))
    ]


@router.post("/{tool_id}/toggle", response_model=list[ToolOut])
def toggle_tool(tool_id: str, user: CurrentUser, db: DbSession) -> list[ToolOut]:
    tool = db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")

    tool.enabled = not tool.enabled

    audit.record(
        db,
        user_id=user.id,
        action="tool.toggle",
        resource_type="tool",
        resource_id=tool.id,
        detail={"enabled": tool.enabled},
    )
    db.commit()
    return [
        _serialise(t) for t in db.scalars(select(Tool).order_by(Tool.created_at))
    ]
