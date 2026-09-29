"""The public helpdesk: anonymous visitors, and what they must not be able to do.

A visitor is anyone on the internet. Everything a visitor can change is
something every other visitor sees, so the tests here are mostly refusals:
the read path is covered by the scoping suites, and what matters in addition
is that opening the door to the public did not open the back office too.
"""

import pytest

from app.core.config import settings
from app.services import language
from app.services.access import PUBLIC_FOLDERS, RESTRICTED_FOLDER
from tests.conftest import StubProvider


def _guest(client) -> dict[str, str]:
    response = client.post("/api/auth/guest")
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def test_a_visitor_gets_a_session_without_credentials(client):
    headers = _guest(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["accessLevel"] == "PUBLIC"
    assert me["id"].startswith("guest-")


def test_each_visitor_is_a_separate_person(client):
    """A shared guest account would show every visitor everyone's chats."""
    first = client.get("/api/auth/me", headers=_guest(client)).json()
    second = client.get("/api/auth/me", headers=_guest(client)).json()
    assert first["id"] != second["id"]


def test_a_visitors_conversations_are_their_own(client):
    alice, bob = _guest(client), _guest(client)
    created = client.post(
        "/api/conversations", json={"title": "My pressure cooker"}, headers=alice
    )
    assert created.status_code in (200, 201)

    titles = [c["title"] for c in client.get("/api/conversations", headers=bob).json()]
    assert "My pressure cooker" not in titles


def test_visitors_are_not_listed_on_the_staff_sign_in_screen(client):
    _guest(client)
    listed = client.get("/api/users").json()
    assert all(u["accessLevel"] != "PUBLIC" for u in listed)


def test_a_visitor_account_cannot_be_signed_into_by_password(client):
    me = client.get("/api/auth/me", headers=_guest(client)).json()
    response = client.post(
        "/api/auth/login", json={"email": me["email"], "password": ""}
    )
    assert response.status_code in (401, 422)


def test_guest_entry_is_refused_when_public_mode_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "public_mode", False)
    assert client.post("/api/auth/guest").status_code == 404
    assert client.get("/api/health").json()["publicMode"] is False


def test_health_advertises_public_mode(client):
    assert client.get("/api/health").json()["publicMode"] is True


# ---------------------------------------------------------------------------
# What a visitor can read
# ---------------------------------------------------------------------------
def test_a_visitor_sees_the_public_folders_and_nothing_internal(client):
    documents = client.get("/api/documents", headers=_guest(client)).json()
    folders = {d["folder"] for d in documents}
    assert folders, "the seeded public corpus should be visible to a visitor"
    assert folders <= set(PUBLIC_FOLDERS)
    assert RESTRICTED_FOLDER not in folders


def test_an_internal_document_never_reaches_a_visitors_search(client):
    internal = [
        d
        for d in client.get("/api/documents", headers=_owner(client)).json()
        if d["folder"] == RESTRICTED_FOLDER
    ]
    assert internal, "the seed should include one internal document to test against"

    visitor = _guest(client)
    for document in internal:
        response = client.get(f"/api/documents/{document['id']}", headers=visitor)
        # 404, not 403: the response must not confirm the document exists.
        assert response.status_code == 404


def _owner(client):
    from tests.conftest import OWNER_EMAIL, auth_headers

    return auth_headers(client, "user-sanyam", OWNER_EMAIL)


# ---------------------------------------------------------------------------
# What a visitor must not change
# ---------------------------------------------------------------------------
def test_a_visitor_cannot_switch_a_tool_off_for_everyone(client):
    tool_id = client.get("/api/tools", headers=_owner(client)).json()[0]["id"]
    response = client.post(f"/api/tools/{tool_id}/toggle", headers=_guest(client))
    assert response.status_code == 403


def test_only_an_administrator_can_switch_a_tool(client, engineer_headers):
    """This was open to every signed-in user before the public mode existed."""
    owner = _owner(client)
    tool_id = client.get("/api/tools", headers=owner).json()[0]["id"]

    assert (
        client.post(f"/api/tools/{tool_id}/toggle", headers=engineer_headers).status_code
        == 403
    )

    flipped = client.post(f"/api/tools/{tool_id}/toggle", headers=owner)
    assert flipped.status_code == 200
    # And back, so no other test inherits a disabled tool.
    assert client.post(f"/api/tools/{tool_id}/toggle", headers=owner).status_code == 200


def test_a_visitor_cannot_create_an_agent(client):
    response = client.post(
        "/api/agents",
        json={"name": "Totally Official BIS", "description": "", "instructions": ""},
        headers=_guest(client),
    )
    assert response.status_code == 403


def test_a_visitors_upload_stays_private(client):
    alice, bob = _guest(client), _guest(client)
    uploaded = client.post(
        "/api/documents",
        files={"file": ("my-test-report.txt", b"Sample test report for IS 1293.", "text/plain")},
        headers=alice,
    )
    assert uploaded.status_code == 201, uploaded.text
    doc = uploaded.json()
    assert doc["folder"] == "Personal Uploads"

    assert client.get(f"/api/documents/{doc['id']}", headers=bob).status_code == 404


def test_a_visitor_cannot_publish_into_a_public_folder(client):
    visitor = _guest(client)
    doc = client.post(
        "/api/documents",
        files={"file": ("fake-notice.txt", b"BIS has abolished hallmarking.", "text/plain")},
        headers=visitor,
    ).json()

    response = client.patch(
        f"/api/documents/{doc['id']}",
        json={"folder": PUBLIC_FOLDERS[0]},
        headers=visitor,
    )
    assert response.status_code in (400, 403)


# ---------------------------------------------------------------------------
# Cross-language search
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Which IS applies to pressure cookers?", False),
        ("sone ki hallmarking kaise check kare", False),
        ("सोने की हॉलमार्किंग कैसे जांचें?", True),
        # Mixed: an IS number inside a Hindi question is still Hindi.
        ("IS 1293 के लिए लाइसेंस कैसे लें?", True),
        ("", False),
    ],
)
def test_which_questions_are_rewritten_for_search(text, expected):
    assert language.needs_translation(text) is expected


def test_an_english_question_costs_no_model_call(stub_gateway):
    provider = stub_gateway(StubProvider(reply="should not be used"))
    result = language.search_query("How do I verify a HUID?")
    assert result.text == "How do I verify a HUID?"
    assert result.translated is None
    assert provider.last_prompt == []


def test_a_hindi_question_is_searched_in_english_and_as_written(stub_gateway):
    stub_gateway(StubProvider(reply="gold hallmarking HUID verification"))
    question = "सोने पर HUID कैसे जांचें?"
    result = language.search_query(question)

    assert result.translated == "gold hallmarking HUID verification"
    # The original stays in the query, so an HUID or IS number the user
    # typed survives a translation that dropped it.
    assert question in result.text
    assert result.text.startswith("gold hallmarking")


def test_a_failed_translation_searches_as_written(stub_gateway):
    from app.models import ModelUnavailableError

    stub_gateway(StubProvider(error=ModelUnavailableError("down")))
    question = "सोने पर HUID कैसे जांचें?"
    result = language.search_query(question)

    assert result.text == question
    assert result.translated is None
    assert result.note


def test_a_reply_in_the_source_language_is_not_taken_as_a_translation(stub_gateway):
    stub_gateway(StubProvider(reply="सोना हॉलमार्क"))
    result = language.search_query("सोने पर HUID कैसे जांचें?")
    assert result.translated is None
