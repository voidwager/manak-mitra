"""Tool execution.

    model returns tool_calls  ->  registry.available_for (three gates)
                              ->  registry.execute
                              ->  results fed back as `tool` messages
                              ->  model answers

The seam this package protects: the model proposes, the server disposes.
Every gate - the operator's global switch, the agent's grant, and the
calling user's own document permissions - is enforced here, never inferred
from what the model asked for.

Tool *output* is untrusted input. A passage that says "ignore your
instructions" reaches the prompt through a tool result exactly as it would
through retrieval, so results are fenced and the guardrail stays last.
"""

from app.tools.base import (
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolError,
    ToolPermissionError,
    ToolResult,
)
from app.tools.registry import (
    IMPLEMENTATIONS,
    NOT_IMPLEMENTED,
    ToolCall,
    ToolInvocation,
    available_for,
    describe,
    execute,
    parse_arguments,
)

__all__ = [
    "IMPLEMENTATIONS",
    "NOT_IMPLEMENTED",
    "Tool",
    "ToolArgumentError",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "ToolInvocation",
    "ToolPermissionError",
    "ToolResult",
    "available_for",
    "describe",
    "execute",
    "parse_arguments",
]
