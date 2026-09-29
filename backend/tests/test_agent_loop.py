"""The agentic loop, and the limits that make it safe to run.

An unbounded loop is not a feature. A model that gets stuck does not get
stuck politely - it repeats the same call, or walks a chain of
near-identical ones, and each iteration costs a request and grows the
context. These tests exist for the guards, not for the happy path.

Three bounds, deliberately independent, because any one alone is escapable:
a model can make ten calls inside one step, or one very slow call per step.
"""

import time

import pytest

from app.models.base import Completion
from app.services import chat_service
from app.services.agent_loop import (
    STOP_ANSWERED,
    STOP_CALLS,
    STOP_STEPS,
    STOP_TIME,
    LoopBudget,
    LoopOutcome,
)
from tests.conftest import StubProvider


def _tool_call(index: int, name: str, arguments: str):
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class LoopingStub(StubProvider):
    """Keeps asking for tools until told it may not.

    `arguments_for` decides whether each step repeats the previous call or
    varies it, which is what separates the repeat guard from the step guard.
    """

    def __init__(self, *, vary: bool, reply="Done."):
        super().__init__(reply)
        self.vary = vary
        self.calls = 0
        self.tool_choices: list[str] = []

    def complete(self, messages, **kwargs):
        self.last_prompt = messages
        self.calls += 1
        self.tool_choices.append(kwargs.get("tool_choice"))

        if kwargs.get("tool_choice") == "none" or not kwargs.get("tools"):
            return Completion(text=self.reply, model=self.model, provider=self.name)

        expression = f"1 + {self.calls}" if self.vary else "1 + 1"
        return Completion(
            text="",
            model=self.model,
            provider=self.name,
            tool_calls=[
                _tool_call(self.calls, "calculator", f'{{"expression": "{expression}"}}')
            ],
        )


# ---------------------------------------------------------------------------
# The budget itself
# ---------------------------------------------------------------------------
def test_a_fresh_budget_is_not_exhausted():
    budget = LoopBudget(max_steps=3, max_tool_calls=5, time_budget=10)
    assert budget.exhausted() is None


def test_the_step_limit_binds():
    budget = LoopBudget(max_steps=2, max_tool_calls=99, time_budget=99)
    budget.steps_taken = 2
    assert budget.exhausted() == STOP_STEPS


def test_the_call_limit_binds_independently_of_steps():
    """A model can make many calls inside a single step."""
    budget = LoopBudget(max_steps=99, max_tool_calls=3, time_budget=99)
    for index in range(3):
        budget.record("calculator", {"expression": f"{index}"})
    assert budget.exhausted() == STOP_CALLS


def test_the_time_limit_binds_independently_of_both():
    """One very slow tool per step would escape the other two bounds."""
    budget = LoopBudget(max_steps=99, max_tool_calls=99, time_budget=0.01)
    time.sleep(0.02)
    assert budget.exhausted() == STOP_TIME


def test_identical_calls_are_recognised_regardless_of_argument_order():
    budget = LoopBudget(max_steps=9, max_tool_calls=9, time_budget=9)
    budget.record("analyse_table", {"column": "Hours", "operation": "sum"})

    assert budget.is_repeat("analyse_table", {"operation": "sum", "column": "Hours"})
    assert not budget.is_repeat("analyse_table", {"operation": "mean", "column": "Hours"})
    assert not budget.is_repeat("calculator", {"column": "Hours", "operation": "sum"})


def test_the_outcome_reports_a_limit_distinctly_from_a_clean_finish():
    budget = LoopBudget(max_steps=1, max_tool_calls=1, time_budget=1)
    budget.steps_taken = 1

    assert LoopOutcome(STOP_ANSWERED, budget).hit_a_limit is False
    assert LoopOutcome(STOP_STEPS, budget).hit_a_limit is True
    # A run that hit a limit is marked so it stands out in the trace.
    assert LoopOutcome(STOP_STEPS, budget).trace_step()["status"] == "skipped"
    assert LoopOutcome(STOP_ANSWERED, budget).trace_step()["status"] == "done"


# ---------------------------------------------------------------------------
# The loop, end to end
# ---------------------------------------------------------------------------
def test_the_loop_runs_several_steps_rather_than_stopping_at_two(
    client, owner_headers, stub_gateway, monkeypatch
):
    """Phase 11 capped a turn at search-then-answer. This is the lift."""
    monkeypatch.setattr(chat_service.settings, "agent_max_steps", 4)
    monkeypatch.setattr(chat_service.settings, "agent_max_tool_calls", 20)

    stub = stub_gateway(LoopingStub(vary=True))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "keep working", "agentId": "certification-guide"},
    ).json()

    executed = [
        s for s in body["assistantMessage"]["activityTrace"]
        if s["label"].startswith("Tool: calculator")
    ]
    assert len(executed) == 4, "expected the loop to take its full four steps"
    assert "none" in stub.tool_choices, "the last round must forbid further calls"


def test_a_repeated_call_is_refused_with_something_the_model_can_act_on(
    client, owner_headers, stub_gateway, monkeypatch
):
    """A silent retry teaches the model nothing; a reason does."""
    monkeypatch.setattr(chat_service.settings, "agent_max_steps", 4)

    stub = stub_gateway(LoopingStub(vary=False))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "loop forever", "agentId": "certification-guide"},
    ).json()

    # The trace shows the refusal happened. Labels are truncated for display,
    # so the guidance itself is checked where it matters - in the prompt.
    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert any("already called" in label for label in labels), (
        "the identical repeat should have been refused"
    )

    delivered = " ".join(m.content for m in stub.last_prompt if m.role == "tool")
    assert "different arguments" in delivered
    assert "will return the same thing" in delivered


def test_the_loop_stops_at_the_step_limit_and_says_so(
    client, owner_headers, stub_gateway, monkeypatch
):
    monkeypatch.setattr(chat_service.settings, "agent_max_steps", 2)
    monkeypatch.setattr(chat_service.settings, "agent_max_tool_calls", 50)

    stub_gateway(LoopingStub(vary=True))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "work until stopped", "agentId": "certification-guide"},
    ).json()

    loop = next(
        s for s in body["assistantMessage"]["activityTrace"]
        if s["label"].startswith("Agent loop:")
    )
    assert "step limit" in loop["label"]
    # Reaching a limit is not a clean finish, and the trace distinguishes it.
    assert loop["status"] == "skipped"
    assert "2 step(s)" in loop["label"]


def test_the_call_budget_stops_a_model_that_batches_calls(
    client, owner_headers, stub_gateway, monkeypatch
):
    """Many calls in one step must not escape the bound."""
    monkeypatch.setattr(chat_service.settings, "agent_max_steps", 10)
    monkeypatch.setattr(chat_service.settings, "agent_max_tool_calls", 3)

    class BatchingStub(StubProvider):
        def __init__(self):
            super().__init__("Finished.")
            self.rounds = 0

        def complete(self, messages, **kwargs):
            self.last_prompt = messages
            self.rounds += 1
            if kwargs.get("tool_choice") == "none":
                return Completion(
                    text=self.reply, model=self.model, provider=self.name
                )
            return Completion(
                text="",
                model=self.model,
                provider=self.name,
                tool_calls=[
                    _tool_call(
                        f"{self.rounds}-{i}",
                        "calculator",
                        f'{{"expression": "{self.rounds} + {i}"}}',
                    )
                    for i in range(5)
                ],
            )

    stub_gateway(BatchingStub())

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "batch it", "agentId": "certification-guide"},
    ).json()

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    # Three ran; the rest were refused for budget rather than executed.
    executed = [
        label for label in labels
        if label.startswith("Tool: calculator") and "budget" not in label
    ]
    assert len(executed) <= 3

    loop = next(label for label in labels if label.startswith("Agent loop:"))
    assert "tool-call limit" in loop


def test_a_turn_with_no_tool_use_reports_no_loop(
    client, owner_headers, stub_gateway
):
    """A step that says '0 steps' is noise, not information."""
    stub_gateway(StubProvider("Straightforward answer."))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "hello", "agentId": "certification-guide"},
    ).json()

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert not any(label.startswith("Agent loop:") for label in labels)


def test_the_model_is_told_it_ran_out_rather_than_being_truncated(
    client, owner_headers, stub_gateway, monkeypatch
):
    """An answer that says what is missing beats a cut-off one."""
    monkeypatch.setattr(chat_service.settings, "agent_max_steps", 1)

    stub = stub_gateway(LoopingStub(vary=True))

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "work", "agentId": "certification-guide"},
    )

    system = " ".join(m.content for m in stub.last_prompt if m.role == "system")
    assert "used your full working budget" in system
    assert "say what is missing" in system
    assert "do not cite anything you did not retrieve" in system


@pytest.mark.parametrize("setting", ["agent_max_steps", "agent_max_tool_calls"])
def test_a_zero_budget_is_clamped_rather_than_disabling_the_loop(
    monkeypatch, setting
):
    """A misconfigured zero must not mean 'unbounded' or 'never run'."""
    monkeypatch.setattr(chat_service.settings, setting, 0)
    budget = LoopBudget.from_settings()
    assert budget.max_steps >= 1
    assert budget.max_tool_calls >= 1
