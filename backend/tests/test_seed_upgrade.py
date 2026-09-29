"""Seeding an *existing* deployment, not a fresh one.

A fresh install and an upgrade take different branches through
`_seed_agents`, and only one of them was covered. On a fresh install every
agent row is new, so the code flushes the agent before wiring its tools -
and that flush happens to push the pending `Tool` rows out too, which is why
`db.get(Tool, ...)` found them and grants landed.

On an upgrade the agents already exist, that branch never runs, and a tool
added in the same release stayed pending and invisible to the lookup. The
tool was created, enabled, and granted to nobody. It corrected itself on the
*next* seed, so it only ever showed up as "the new tool does nothing" on a
freshly upgraded deployment - the exact case a release is.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Agent, AgentTool, Tool
from app.database import seed as seed_module

OLD_TOOL = dict(
    id="legacy-tool",
    name="Legacy Tool",
    category="Retrieval",
    description="Shipped in the previous release.",
)
NEW_TOOL = dict(
    id="arrived-later",
    name="Arrived Later",
    category="Retrieval",
    description="Introduced in the release under test.",
)
AGENT = dict(
    id="upgrade-agent",
    name="Upgrade Agent",
    description="Exists before the upgrade.",
    model="",
    icon="Wrench",
    capabilities=[],
    folder_scope=[],
)


@pytest.fixture
def upgrade_session():
    """A session configured exactly like the application's.

    `autoflush=False` is the whole point. `SessionLocal` in
    database/session.py sets it, and it is what makes the bug reachable: with
    autoflush on - SQLAlchemy's default, and what a casually written test
    would get - the `db.get()` calls in `_seed_agents` quietly flush the
    pending tool rows and the grant lands anyway. A fixture that forgot this
    passed against the broken code, which is worse than having no test.
    """
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp).as_posix()}/upgrade.db")
        Base.metadata.create_all(bind=engine)
        with Session(engine, autoflush=False) as session:
            yield session
        engine.dispose()


def _seed(db, tools, agents, monkeypatch):
    monkeypatch.setattr(seed_module, "TOOLS", tools)
    monkeypatch.setattr(seed_module, "AGENTS", agents)
    seed_module._seed_tools(db)
    seed_module._seed_agents(db)
    db.commit()


def test_a_tool_added_alongside_its_grants_is_granted_in_one_pass(
    upgrade_session, monkeypatch
):
    db = upgrade_session

    # Release N: the agent exists and is granted the tool of the day.
    _seed(db, [OLD_TOOL], [{**AGENT, "tool_ids": ["legacy-tool"]}], monkeypatch)
    assert db.get(Agent, "upgrade-agent") is not None

    # Release N+1 introduces a tool and grants it to that existing agent,
    # in a single seed run - which is all a deployment gets.
    _seed(
        db,
        [OLD_TOOL, NEW_TOOL],
        [{**AGENT, "tool_ids": ["legacy-tool", "arrived-later"]}],
        monkeypatch,
    )

    assert db.get(Tool, "arrived-later") is not None, "the tool row must exist"

    granted = {
        link.tool_id
        for link in db.scalars(
            select(AgentTool).where(AgentTool.agent_id == "upgrade-agent")
        )
    }
    assert "arrived-later" in granted, (
        "a tool nobody is granted is invisible to the model - the feature "
        "ships switched on and does nothing"
    )
    assert "legacy-tool" in granted, "existing grants must survive the upgrade"


def test_an_operator_revocation_is_not_undone_by_seeding(upgrade_session, monkeypatch):
    """Grants are added by seeding, never restored after a deliberate removal."""
    db = upgrade_session
    _seed(db, [OLD_TOOL], [{**AGENT, "tool_ids": ["legacy-tool"]}], monkeypatch)

    link = db.scalar(
        select(AgentTool).where(AgentTool.agent_id == "upgrade-agent")
    )
    link.enabled = False
    db.commit()

    _seed(db, [OLD_TOOL], [{**AGENT, "tool_ids": ["legacy-tool"]}], monkeypatch)

    refreshed = db.scalar(
        select(AgentTool).where(AgentTool.agent_id == "upgrade-agent")
    )
    assert refreshed.enabled is False, "seeding must not re-enable a revoked tool"
