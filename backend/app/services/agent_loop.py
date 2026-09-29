"""The agentic loop: think, act, observe, repeat - within limits.

Phase 11 allowed one round of tool calling: search, then answer. This lifts
that cap so an agent can read a result and decide what to do next, which is
what makes it an agent rather than a function with a search step.

Everything here is about the limits, because an unbounded loop is not a
feature. Three things go wrong in practice and each has its own guard:

**It repeats itself.** A model that does not get the answer it expected will
often ask the identical question again, forever. Identical calls are
detected and refused with an explanation, which is information the model can
act on - unlike a silent retry, which teaches it nothing.

**It wanders.** Each step costs a request and grows the context. Steps, total
tool calls and wall-clock time are bounded independently, because any one
bound alone is escapable: a model can make ten calls in one step, or one
very slow call per step.

**It runs out mid-thought.** When a budget binds, the loop does not simply
stop - the model is told, and asked to answer with what it has. An answer
that acknowledges it ran out of room is useful; a truncated one is not.

Nothing here narrates invented reasoning. The trace records what was
actually called and what came back; the model's own deliberation is not
reconstructed for display.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: Why a loop ended. Reported, never guessed.
STOP_ANSWERED = "answered"
STOP_STEPS = "step_limit"
STOP_CALLS = "call_limit"
STOP_TIME = "time_limit"
STOP_NO_TOOLS = "no_tools"

STOP_REASON_TEXT = {
    STOP_ANSWERED: "The agent finished and answered.",
    STOP_STEPS: "The agent reached its step limit and answered with what it had.",
    STOP_CALLS: "The agent reached its tool-call limit and answered with what it had.",
    STOP_TIME: "The agent ran out of time and answered with what it had.",
    STOP_NO_TOOLS: "No tools were available, so the agent answered directly.",
}


def _signature(name: str, arguments: dict) -> str:
    """A stable identity for a call, so repeats can be spotted.

    Sorted keys so argument order does not disguise a repeat.
    """
    try:
        rendered = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        rendered = repr(sorted(arguments.items()))
    return f"{name}:{rendered}"


@dataclass
class LoopBudget:
    """What the loop is allowed to spend, and what it has spent."""

    max_steps: int = 0
    max_tool_calls: int = 0
    time_budget: float = 0.0

    steps_taken: int = 0
    calls_made: int = 0
    started_at: float = field(default_factory=time.monotonic)

    #: Signatures already executed this turn, for repeat detection.
    seen: set[str] = field(default_factory=set)

    @classmethod
    def from_settings(cls) -> "LoopBudget":
        return cls(
            max_steps=max(1, settings.agent_max_steps),
            max_tool_calls=max(1, settings.agent_max_tool_calls),
            time_budget=max(1.0, settings.agent_time_budget_seconds),
        )

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def calls_remaining(self) -> int:
        return max(0, self.max_tool_calls - self.calls_made)

    def exhausted(self) -> str | None:
        """The binding limit, if any has been reached."""
        if self.steps_taken >= self.max_steps:
            return STOP_STEPS
        if self.calls_made >= self.max_tool_calls:
            return STOP_CALLS
        if self.elapsed >= self.time_budget:
            return STOP_TIME
        return None

    def is_repeat(self, name: str, arguments: dict) -> bool:
        return _signature(name, arguments) in self.seen

    def record(self, name: str, arguments: dict) -> None:
        self.seen.add(_signature(name, arguments))
        self.calls_made += 1

    def describe(self) -> str:
        return (
            f"{self.steps_taken} step(s), {self.calls_made} tool call(s), "
            f"{self.elapsed:.1f}s"
        )


REPEAT_REFUSAL = (
    "You already called {name} with exactly these arguments and got a result "
    "above. Calling it again will return the same thing. Either use what you "
    "have, try different arguments, or tell the user what you could not find."
)


FINAL_ROUND_NOTE = (
    "You have used your full working budget for this turn ({budget}). Answer "
    "now with what you have gathered. If it is incomplete, say what is missing "
    "rather than guessing - and do not cite anything you did not retrieve."
)


@dataclass
class LoopOutcome:
    """How the loop ended, for the activity trace and the audit entry."""

    stop_reason: str
    budget: LoopBudget

    @property
    def hit_a_limit(self) -> bool:
        return self.stop_reason in (STOP_STEPS, STOP_CALLS, STOP_TIME)

    def trace_step(self) -> dict:
        text = STOP_REASON_TEXT.get(self.stop_reason, self.stop_reason)
        return {
            "label": f"Agent loop: {text} ({self.budget.describe()})",
            # A loop that ran out of room is not a failure, but it is not a
            # clean finish either - it is shown as skipped so it stands out.
            "status": "skipped" if self.hit_a_limit else "done",
        }


__all__ = [
    "FINAL_ROUND_NOTE",
    "REPEAT_REFUSAL",
    "STOP_ANSWERED",
    "STOP_CALLS",
    "STOP_NO_TOOLS",
    "STOP_REASON_TEXT",
    "STOP_STEPS",
    "STOP_TIME",
    "LoopBudget",
    "LoopOutcome",
]
