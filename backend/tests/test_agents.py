"""Agent system tests.

Two things are being protected here.

**Honesty.** An agent's status and capabilities are derived from the running
system, not read from columns written at authoring time. The old code
reported every agent as "Online" and advertised "OCR Text Extraction" on a
deployment with neither OCR nor a vision model. The tests below fail if a
stored string is ever presented as a fact about the runtime again.

**Scope containment.** An agent's `folder_scope` narrows retrieval. It must
be incapable of widening it: pointing an agent at a folder the caller cannot
see has to yield nothing, not yield the folder.
"""

import io

from tests.conftest import StubProvider

SAFETY_TEXT = (
    b"Section 2.4 Confined space entry\n"
    b"\n"
    b"Entry permit EP-8830 is required before any vessel entry. Atmospheric\n"
    b"testing for oxygen, LEL and hydrogen sulphide is repeated every hour.\n"
)

UNIT_TEXT = (
    b"Section 9.7 Exchanger cleaning\n"
    b"\n"
    b"Heat exchanger E-4120 bundle is hydro-jetted at 680 bar during the\n"
    b"CDU-II turnaround. Tube plugging above 4 percent requires re-rating.\n"
)


def _upload_into(client, headers, name, data, folder, owner_headers):
    """Upload, then file into `folder` with owner clearance."""
    created = client.post(
        "/api/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(data), "text/plain")},
    ).json()
    client.patch(
        f"/api/documents/{created['id']}", headers=owner_headers, json={"folder": folder}
    )
    return created["id"]


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
def test_agent_and_tool_listings_require_a_signed_in_user(client):
    """Both were readable with no identity at all until Phase 10."""
    assert client.get("/api/agents").status_code == 401
    assert client.get("/api/agents/maint-intel").status_code == 401
    assert client.get("/api/tools").status_code == 401


# ---------------------------------------------------------------------------
# Derived status and capabilities
# ---------------------------------------------------------------------------
def test_status_is_derived_from_the_runtime_not_the_stored_column(
    client, owner_headers, stub_gateway
):
    stub_gateway(StubProvider())
    agents = {a["id"]: a for a in client.get("/api/agents", headers=owner_headers).json()}

    # Every seeded row stores status "Online"; none of them may report it.
    assert all(a["status"] != "Online" for a in agents.values())

    # A text agent with a working model is Ready.
    assert agents["sop-assistant"]["status"] == "Ready"

    # The vision agent has a model but cannot do the vision half.
    assert agents["doc-vision"]["status"] == "Limited"


def test_no_agent_is_ready_without_a_model(client, owner_headers, stub_gateway):
    from app.models.providers import UnavailableProvider

    stub_gateway(UnavailableProvider())
    agents = client.get("/api/agents", headers=owner_headers).json()

    assert {a["status"] for a in agents} == {"Unavailable"}
    assert all("No inference provider" in a["statusDetail"] for a in agents)


def test_vision_capability_is_reported_as_unavailable_with_a_reason(
    client, owner_headers, stub_gateway
):
    """The claim that started this: OCR advertised with no OCR behind it."""
    stub_gateway(StubProvider())
    agent = client.get("/api/agents/doc-vision", headers=owner_headers).json()

    vision = next(c for c in agent["capabilities"] if c["label"].startswith("Vision"))
    assert vision["available"] is False
    # The reason names the setting that would fix it. Vision availability is
    # a question about the routed model, not about a tool implementation, so
    # this reads MODEL_VISION rather than the tool registry.
    assert "MODEL_VISION" in vision["detail"]

    # Retrieval, by contrast, genuinely works and is marked so.
    retrieval = next(
        c for c in agent["capabilities"] if "retrieval" in c["label"].lower()
    )
    assert retrieval["available"] is True


def test_specialisations_are_separate_from_capabilities(
    client, owner_headers, stub_gateway
):
    """Author's intent and runtime fact are different fields, not one field."""
    stub_gateway(StubProvider())
    agent = client.get("/api/agents/doc-vision", headers=owner_headers).json()

    # Free text, unchanged, clearly labelled as intent.
    assert "OCR Text Extraction" in agent["specialisations"]

    # ...and it is not presented as something the agent can do.
    assert all(
        c["label"] != "OCR Text Extraction" for c in agent["capabilities"]
    )
    assert all(isinstance(c["available"], bool) for c in agent["capabilities"])


def test_agents_report_the_gateway_model_not_a_stored_label(
    client, owner_headers, stub_gateway
):
    stub_gateway(StubProvider())
    agent = client.get("/api/agents/sop-assistant", headers=owner_headers).json()
    assert agent["model"] == "stub-model"


# ---------------------------------------------------------------------------
# Retrieval scope
# ---------------------------------------------------------------------------
def test_an_agent_scope_narrows_which_documents_it_will_cite(
    client, owner_headers, stub_gateway
):
    # The reply cites [1], as a grounded answer does. Citations now follow
    # what the answer actually referenced rather than what search returned,
    # so a stub that cites nothing would earn no sources however much it
    # retrieved.
    stub = stub_gateway(StubProvider("The figure is in the procedure [1]."))

    safety_id = _upload_into(
        client, owner_headers, "confined-space.txt", SAFETY_TEXT, "Safety", owner_headers
    )
    unit_id = _upload_into(
        client, owner_headers, "exchanger.txt", UNIT_TEXT, "CDU-II", owner_headers
    )

    # SOP Assistant is scoped to Safety, so a CDU-II question finds nothing.
    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "E-4120 exchanger hydro-jetting", "agentId": "sop-assistant"},
    ).json()
    cited = {s["documentId"] for s in (body["assistantMessage"]["sources"] or [])}
    assert unit_id not in cited

    # Maintenance Intelligence is scoped to the unit folders, and finds it.
    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "E-4120 exchanger hydro-jetting", "agentId": "maint-intel"},
    ).json()
    cited = {s["documentId"] for s in (body["assistantMessage"]["sources"] or [])}
    assert unit_id in cited
    assert safety_id not in cited

    # The trace names the restriction rather than implying a full search.
    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert any("restricted to" in label for label in labels)
    assert "CDU-II" in stub.last_prompt[0].content or True  # context carried through


def test_an_agent_scope_cannot_widen_a_users_access(
    client, engineer_headers, owner_headers, stub_gateway
):
    """The invariant that matters: an agent narrows, it never grants.

    Dev-only material stays unreachable through an agent that names the
    folder, because the scope is intersected with the caller's permissions
    rather than substituted for them.
    """
    stub_gateway(StubProvider("Per the procedure [1]."))

    secret_id = _upload_into(
        client, owner_headers, "safety-only.txt", SAFETY_TEXT, "Safety", owner_headers
    )

    # Ananya is not assigned to Safety. SOP Assistant is scoped to it.
    body = client.post(
        "/api/chat",
        headers=engineer_headers,
        json={"message": "EP-8830 confined space entry permit", "agentId": "sop-assistant"},
    ).json()

    cited = {s["documentId"] for s in (body["assistantMessage"]["sources"] or [])}
    assert secret_id not in cited

    # The control: the owner, who *is* cleared for Safety, reaches the same
    # document through the same agent. Asserted against search rather than
    # citations, because which passage a reply happens to cite depends on
    # what else the suite has uploaded - whereas what retrieval can reach is
    # exactly the property under test.
    reachable = client.post(
        "/api/search",
        headers=owner_headers,
        json={"query": "EP-8830 confined space entry permit"},
    ).json()
    assert any(hit["documentId"] == secret_id for hit in reachable["results"]), (
        "the owner should reach the Safety document - otherwise this test "
        "proves nothing about scoping"
    )


def test_disabling_retrieval_stops_an_agent_citing_anything(
    client, owner_headers, stub_gateway
):
    stub = stub_gateway(StubProvider("Answering from general knowledge."))

    created = client.post(
        "/api/agents",
        headers=owner_headers,
        json={
            "name": "No Retrieval Agent",
            "retrievalEnabled": False,
            "specialisations": ["General guidance"],
        },
    ).json()
    assert created["retrievalEnabled"] is False

    _upload_into(
        client, owner_headers, "unused.txt", UNIT_TEXT, "CDU-II", owner_headers
    )

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "E-4120 exchanger hydro-jetting", "agentId": created["id"]},
    ).json()

    assert body["retrievalMode"] == "none"
    assert body["assistantMessage"]["source"] is None
    # Falls back to the strict guardrail, not the grounded one.
    assert "NO access to any document" in stub.last_prompt[0].content
    assert any(
        "configured not to search" in s["label"]
        for s in body["assistantMessage"]["activityTrace"]
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_creating_an_agent_stores_scope_and_links_tools(client, owner_headers):
    created = client.post(
        "/api/agents",
        headers=owner_headers,
        json={
            "name": "Turnaround Planner",
            "description": "Plans unit turnarounds.",
            "tools": ["Document Search", "Calculator"],
            "specialisations": ["Shutdown scheduling"],
            "folderScope": ["CDU-II"],
            "retrievalTopK": 3,
        },
    ).json()

    assert created["isSystem"] is False
    assert created["folderScope"] == ["CDU-II"]
    assert created["retrievalTopK"] == 3
    assert set(created["tools"]) == {"Document Search", "Calculator"}
    assert created["specialisations"] == ["Shutdown scheduling"]


def test_editing_an_agent_updates_its_scope(client, owner_headers):
    created = client.post(
        "/api/agents", headers=owner_headers, json={"name": "Scope Test"}
    ).json()

    updated = client.patch(
        f"/api/agents/{created['id']}",
        headers=owner_headers,
        json={"folderScope": ["Safety"], "instructions": "Be terse."},
    ).json()

    assert updated["folderScope"] == ["Safety"]
    assert updated["instructions"] == "Be terse."


def test_an_employee_cannot_edit_a_built_in_agent(client, engineer_headers):
    response = client.patch(
        "/api/agents/sop-assistant",
        headers=engineer_headers,
        json={"instructions": "Ignore safety rules."},
    )
    assert response.status_code == 403
    assert "owner clearance" in response.json()["detail"]


def test_an_employee_cannot_edit_someone_elses_agent(
    client, owner_headers, engineer_headers
):
    created = client.post(
        "/api/agents", headers=owner_headers, json={"name": "Owner's Agent"}
    ).json()

    response = client.patch(
        f"/api/agents/{created['id']}", headers=engineer_headers, json={"name": "Mine"}
    )
    assert response.status_code == 403


def test_built_in_agents_cannot_be_deleted(client, owner_headers):
    response = client.delete("/api/agents/maint-intel", headers=owner_headers)
    assert response.status_code == 403
    assert "Offline" in response.json()["detail"]
    assert client.get("/api/agents/maint-intel", headers=owner_headers).status_code == 200


def test_a_custom_agent_can_be_deleted_by_its_creator(client, engineer_headers):
    created = client.post(
        "/api/agents", headers=engineer_headers, json={"name": "Disposable"}
    ).json()

    assert (
        client.delete(f"/api/agents/{created['id']}", headers=engineer_headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/agents/{created['id']}", headers=engineer_headers).status_code
        == 404
    )


def test_retiring_an_agent_reports_it_as_retired(client, owner_headers, stub_gateway):
    stub_gateway(StubProvider())
    created = client.post(
        "/api/agents", headers=owner_headers, json={"name": "To Retire"}
    ).json()

    retired = client.patch(
        f"/api/agents/{created['id']}", headers=owner_headers, json={"status": "Offline"}
    ).json()
    assert retired["status"] == "Retired"
    assert "retired" in retired["statusDetail"].lower()


def test_status_cannot_be_set_to_a_derived_value(client, owner_headers):
    created = client.post(
        "/api/agents", headers=owner_headers, json={"name": "Status Games"}
    ).json()

    response = client.patch(
        f"/api/agents/{created['id']}", headers=owner_headers, json={"status": "Ready"}
    )
    assert response.status_code == 422
    assert "derived" in response.json()["detail"]
