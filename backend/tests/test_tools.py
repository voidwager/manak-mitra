"""Tool execution tests.

Ordered by how much damage a regression would do.

**Sandbox.** The calculator receives an expression written by a language
model, which is itself influenced by document text and user messages. That
makes it attacker-reachable, so the first group is about what it refuses to
evaluate.

**Gates.** Three of them - the operator's switch, the agent's grant, and the
calling user's own document permissions - and a tool call must satisfy all
three. A model asking for a tool it was not given is a normal event, not an
error, and must be refused rather than honoured.

**Honesty.** A catalogued tool with no implementation must never report
itself as runnable, and a tool that fails must not produce a plausible
answer.
"""

import io

import pytest

from app.tools import ToolContext, registry
from app.tools.base import ToolArgumentError
from app.tools.builtin.calculator import CalculatorTool, evaluate
from tests.conftest import StubProvider

MAINTENANCE_CSV = (
    b"Date,TagID,Equipment,Action,Technician,DowntimeHours\n"
    b"2026-08-27,P-204,Centrifugal Pump,Seal Flush,S. Jain,4.5\n"
    b"2026-08-14,C-101,Compressor,Valve Replacement,A. Roy,12.25\n"
    b"2026-07-02,P-204,Centrifugal Pump,Bearing Change,A. Roy,8\n"
)


def _context(db_session, user_id="user-sanyam", agent_id="maint-intel"):
    from app.database.models import Agent, User

    return ToolContext(
        db=db_session,
        user=db_session.get(User, user_id),
        agent=db_session.get(Agent, agent_id) if agent_id else None,
    )


# ---------------------------------------------------------------------------
# 1. The calculator sandbox
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("47.5 * 18.25", 866.875),
        ("sqrt(16)", 4.0),
        ("round(2.5 * 1.8 + 32, 2)", 36.5),
        ("min(3, 9, 1)", 1),
        ("-5 + 2", -3),
    ],
)
def test_arithmetic_is_evaluated_exactly(expression, expected):
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read()",
        "exec('x=1')",
        "eval('2+2')",
        "[x for x in range(10)]",
        "lambda: 1",
        "globals()",
        "'a' * 100",
        "os.path",
    ],
)
def test_the_calculator_refuses_anything_that_is_not_arithmetic(expression):
    """The input is attacker-reachable, so this is the security boundary."""
    with pytest.raises(ToolArgumentError):
        evaluate(expression)


def test_a_huge_exponent_is_refused_rather_than_computed():
    """`9**9**9` is three characters of denial-of-service."""
    with pytest.raises(ToolArgumentError) as excinfo:
        evaluate("9 ** 9 ** 9")
    assert "Exponent" in str(excinfo.value)


def test_division_by_zero_is_reported_not_raised_as_a_crash():
    with pytest.raises(ToolArgumentError) as excinfo:
        evaluate("1 / 0")
    assert "zero" in str(excinfo.value).lower()


def test_calculator_tool_returns_a_readable_result(db_session):
    result = CalculatorTool().run(_context(db_session), expression="47.5 * 18.25")
    assert result.ok
    assert "866.875" in result.content


# ---------------------------------------------------------------------------
# 2. The three gates
# ---------------------------------------------------------------------------
def test_an_agent_is_only_offered_the_tools_it_was_granted(db_session):
    from app.database.models import Agent

    maintenance = registry.available_for(db_session, db_session.get(Agent, "maint-intel"))
    sop = registry.available_for(db_session, db_session.get(Agent, "sop-assistant"))

    assert "calculator" in {t.name for t in maintenance}
    # SOP Assistant is granted the document-reading tools only - searching
    # inside documents, and reading one end to end. No calculator, no
    # analytics, no report generation.
    assert {t.name for t in sop} == {
        "document_search",
        "knowledge_retrieval",
        "read_document",
    }


def test_an_agentless_turn_is_offered_no_tools(db_session):
    """Tool access is granted, not assumed."""
    assert registry.available_for(db_session, None) == []


def test_a_globally_disabled_tool_is_not_offered(client, owner_headers, db_session):
    from app.database.models import Agent

    before = {t.name for t in registry.available_for(db_session, db_session.get(Agent, "maint-intel"))}
    assert "calculator" in before

    client.post("/api/tools/calculator/toggle", headers=owner_headers)
    db_session.expire_all()

    after = {t.name for t in registry.available_for(db_session, db_session.get(Agent, "maint-intel"))}
    assert "calculator" not in after

    # Put it back so later tests see the seeded state.
    client.post("/api/tools/calculator/toggle", headers=owner_headers)


def test_calling_an_ungranted_tool_is_refused_not_executed(db_session):
    """A model asking for a tool it does not have is normal, not an error."""
    from app.database.models import Agent

    permitted = registry.available_for(db_session, db_session.get(Agent, "sop-assistant"))
    call = registry.ToolCall(id="c1", name="calculator", arguments={"expression": "2+2"})

    invocation = registry.execute(call, _context(db_session, agent_id="sop-assistant"), permitted)

    assert invocation.ok is False
    assert "not available to this agent" in invocation.result.content
    # The refusal must not leak the answer it would have produced.
    assert "4" not in invocation.result.content.replace("404", "")


def test_a_hallucinated_tool_name_is_refused_gracefully(db_session):
    from app.database.models import Agent

    permitted = registry.available_for(db_session, db_session.get(Agent, "maint-intel"))
    call = registry.ToolCall(id="c1", name="delete_everything", arguments={})

    invocation = registry.execute(call, _context(db_session), permitted)
    assert invocation.ok is False
    assert "not available" in invocation.result.content


def test_retrieval_tools_inherit_the_callers_document_scope(
    client, owner_headers, engineer_headers, db_session
):
    """A tool must not become a way around document permissions."""
    created = client.post(
        "/api/documents",
        headers=owner_headers,
        files={
            "file": (
                "restricted-tool-test.txt",
                io.BytesIO(b"Turbine T-9001 trip setpoint is 3820 rpm."),
                "text/plain",
            )
        },
    ).json()
    client.patch(
        f"/api/documents/{created['id']}",
        headers=owner_headers,
        json={"folder": "BIS Internal"},
    )
    db_session.expire_all()

    tool = registry.by_wire_name("knowledge_retrieval")

    # No agent, so only the *user's* permissions are in play - which is what
    # this test is about. (An agent's folder scope narrows further; that is
    # covered in test_agents.py.)
    owner_result = tool.run(
        _context(db_session, agent_id=None), query="T-9001 trip setpoint"
    )
    assert "3820 rpm" in owner_result.content
    assert owner_result.citations

    # Ananya is not cleared for BIS Internal. The refusal echoes
    # her query back, so assert on the document's actual content - that is
    # what must not cross the boundary.
    # She may legitimately match her *own* documents on similar wording, so
    # the assertion is about this document specifically, not about getting
    # nothing back.
    engineer_result = tool.run(
        _context(db_session, user_id="user-ananya", agent_id=None),
        query="T-9001 trip setpoint",
    )
    assert "3820" not in engineer_result.content
    assert all(
        c["documentId"] != created["id"] for c in engineer_result.citations
    )


# ---------------------------------------------------------------------------
# 3. Honesty
# ---------------------------------------------------------------------------
def test_the_vision_tool_reports_itself_unavailable(client, owner_headers):
    tools = {t["id"]: t for t in client.get("/api/tools", headers=owner_headers).json()}

    assert tools["img-analyzer"]["executable"] is False
    assert "Phase 13" in tools["img-analyzer"]["unavailableReason"]

    # ...while the ones that landed in Phase 8 and 11 report themselves real.
    for tool_id in ("doc-search", "know-retrieval", "calculator", "data-analyzer"):
        assert tools[tool_id]["executable"] is True, tool_id
        assert tools[tool_id]["unavailableReason"] == ""


def test_switching_a_tool_off_leaves_it_switchable_back_on(client, owner_headers):
    """The switch has to work in both directions.

    It did not. `executable` means "an agent could call this right now",
    which is false for a tool an operator has switched off - and the UI
    gated the switch itself on that field, so turning a tool off disabled
    its own control. Off was a one-way door, and the only way back was the
    database.

    `implemented` is the half that ignores the switch, and it is what a
    control may be gated on.
    """
    def state(rows):
        row = next(t for t in rows if t["id"] == "calculator")
        return row["enabled"], row["implemented"], row["executable"]

    assert state(client.get("/api/tools", headers=owner_headers).json()) == (
        True,
        True,
        True,
    )

    off = state(client.post("/api/tools/calculator/toggle", headers=owner_headers).json())
    assert off == (False, True, False), (
        "a switched-off tool is not runnable, but it is still built"
    )

    back_on = state(
        client.post("/api/tools/calculator/toggle", headers=owner_headers).json()
    )
    assert back_on == (True, True, True)


def test_an_unbuilt_tool_is_never_reported_as_built(client, owner_headers):
    """The distinction only helps if it survives the switch.

    A control gated on `implemented` must stay disabled for a tool with no
    code behind it, however the operator switch happens to be set - so
    `implemented` has to stay false across a toggle rather than tracking it.
    """
    tools = {t["id"]: t for t in client.get("/api/tools", headers=owner_headers).json()}
    assert tools["img-analyzer"]["implemented"] is False
    assert tools["img-analyzer"]["enabled"] is True  # catalogued and switched on

    rows = client.post("/api/tools/img-analyzer/toggle", headers=owner_headers).json()
    vision = next(t for t in rows if t["id"] == "img-analyzer")
    assert vision["enabled"] is False
    assert vision["implemented"] is False
    assert "Phase 13" in vision["unavailableReason"]


def test_a_failing_tool_returns_an_error_not_a_plausible_answer(db_session):
    from app.database.models import Agent

    permitted = registry.available_for(db_session, db_session.get(Agent, "maint-intel"))
    call = registry.ToolCall(
        id="c1", name="calculator", arguments={"expression": "1 / 0"}
    )

    invocation = registry.execute(call, _context(db_session), permitted)
    assert invocation.ok is False
    assert "zero" in invocation.result.content.lower()


def test_leaked_tool_markup_is_stripped_from_a_reply():
    from app.services.chat_service import strip_tool_markup

    assert strip_tool_markup("Answer.\n<tool_call>\n<function=x") == "Answer."
    assert (
        strip_tool_markup("A <tool_call>junk</tool_call> B").replace("  ", " ")
        == "A B"
    )
    assert strip_tool_markup("Nothing to strip.") == "Nothing to strip."


# ---------------------------------------------------------------------------
# 4. Table analysis
# ---------------------------------------------------------------------------
def test_table_analysis_computes_over_indexed_rows(
    client, owner_headers, db_session
):
    client.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("Tool Test History.csv", io.BytesIO(MAINTENANCE_CSV), "text/csv")},
    )
    db_session.expire_all()

    tool = registry.by_wire_name("analyse_table")
    context = _context(db_session, agent_id=None)

    summary = tool.run(context, operation="summary", document="Tool Test History")
    assert "3 rows" in summary.content or "3 rows" in str(summary.data)

    total = tool.run(
        context,
        operation="sum",
        column="DowntimeHours",
        document="Tool Test History",
    )
    # 4.5 + 12.25 + 8 - computed, not estimated.
    assert "24.75" in total.content

    filtered = tool.run(
        context,
        operation="count",
        column="TagID",
        where_column="TagID",
        where_value="P-204",
        document="Tool Test History",
    )
    assert "2 row" in filtered.content


def test_analysing_a_missing_column_names_the_real_ones(client, owner_headers, db_session):
    client.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("Column Test.csv", io.BytesIO(MAINTENANCE_CSV), "text/csv")},
    )
    db_session.expire_all()

    tool = registry.by_wire_name("analyse_table")
    with pytest.raises(ToolArgumentError) as excinfo:
        tool.run(
            _context(db_session, agent_id=None),
            operation="sum",
            column="NotAColumn",
            document="Column Test",
        )
    assert "TagID" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 5. End to end through chat
# ---------------------------------------------------------------------------
class ToolCallingStub(StubProvider):
    """Asks for one tool on the first call, then answers with its result."""

    def __init__(self, tool_name: str, arguments: str, reply: str = "Done."):
        super().__init__(reply)
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0
        self.saw_tools: list[str] = []
        self.saw_tool_choice: list[str] = []

    def complete(self, messages, **kwargs):
        from app.models.base import Completion

        self.last_prompt = messages
        self.calls += 1
        self.saw_tools.append([
            t["function"]["name"] for t in (kwargs.get("tools") or [])
        ])
        self.saw_tool_choice.append(kwargs.get("tool_choice"))

        if self.calls == 1:
            return Completion(
                text="",
                model=self.model,
                provider=self.name,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": self.tool_name,
                            "arguments": self.arguments,
                        },
                    }
                ],
            )
        return Completion(text=self.reply, model=self.model, provider=self.name)


def test_chat_runs_a_tool_and_answers_with_its_result(
    client, owner_headers, stub_gateway
):
    stub = stub_gateway(
        ToolCallingStub(
            "calculator", '{"expression": "47.5 * 18.25"}', "The total is 866.875 m3."
        )
    )

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "47.5 m3/h for 18.25 hours?", "agentId": "maint-intel"},
    ).json()

    assert stub.calls == 2, "expected a tool round then an answer"
    assert body["assistantMessage"]["text"] == "The total is 866.875 m3."

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert any("Tool: calculator" in label for label in labels)

    # The tool result reached the model as a `tool` message, fenced.
    roles = [m.role for m in stub.last_prompt]
    assert "tool" in roles
    fenced = next(m for m in stub.last_prompt if m.role == "tool")
    assert "not instructions" in fenced.content
    assert "866.875" in fenced.content


def test_a_second_tool_round_is_refused_rather_than_looping(
    client, owner_headers, stub_gateway
):
    """MAX_TOOL_ROUNDS is what separates Phase 11 from the Phase 12 loop."""

    class AlwaysCalls(ToolCallingStub):
        def complete(self, messages, **kwargs):
            from app.models.base import Completion

            self.last_prompt = messages
            self.calls += 1
            self.saw_tool_choice.append(kwargs.get("tool_choice"))
            if kwargs.get("tool_choice") == "none":
                return Completion(
                    text="Answering without more tools.",
                    model=self.model,
                    provider=self.name,
                )
            return Completion(
                text="",
                model=self.model,
                provider=self.name,
                tool_calls=[
                    {
                        "id": f"call_{self.calls}",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
                    }
                ],
            )

    stub = stub_gateway(AlwaysCalls("calculator", '{"expression": "1+1"}'))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "loop please", "agentId": "maint-intel"},
    ).json()

    # Bounded, and the last call explicitly forbids further tool use rather
    # than dropping the schemas - which made Qwen emit raw markup as prose.
    assert "none" in stub.saw_tool_choice
    assert body["assistantMessage"]["text"] == "Answering without more tools."


def test_an_agent_without_tool_grants_is_offered_none(
    client, owner_headers, stub_gateway
):
    stub = stub_gateway(StubProvider("Plain answer."))

    created = client.post(
        "/api/agents", headers=owner_headers, json={"name": "Toolless"}
    ).json()
    assert created["tools"] == []

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "hello", "agentId": created["id"]},
    )
    # Nothing to offer, so no tool round happened at all.
    assert stub.last_prompt is not None
