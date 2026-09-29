"""API smoke tests for the milestone-1 surface.

These cover the contract the frontend depends on: shape of responses,
server-side document scoping, and the honesty guarantees (nothing reports
itself as indexed, chat does not fabricate a citation).
"""

import io

#: Enough of a PNG header to be a real image file rather than a text file
#: wearing a .png suffix.
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + bytes(32)


# ---------------------------------------------------------------- system
def test_health_reports_capabilities_honestly(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["databaseConnected"] is True

    caps = body["implemented"]
    # These must stay False until the corresponding phase actually lands.
    assert caps["modelInference"] is False

    # Authentication landed in Phase 16.
    assert caps["authentication"] is True
    assert caps["auditTrail"] is True

    # The tool executor landed in Phase 11. This flag was left at False and
    # went on under-claiming a capability that existed - the same class of
    # error as over-claiming, just in the flattering direction.
    assert caps["toolCalling"] is True

    # No vision model is configured in the test environment, so vision must
    # not be claimed even though the catalogue may contain one.
    assert caps["vision"] is False
    assert caps["modelRouting"] is False

    # Retrieval landed in Phase 8. Lexical BM25 needs no model, so indexing
    # and retrieval are available even with no provider configured at all.
    assert caps["documentIndexing"] is True
    assert caps["retrieval"] is True

    # ...but semantic search is a separate claim, and no embedder is
    # configured in the test environment.
    assert caps["semanticRetrieval"] is False
    assert body["retrieval"]["mode"] == "lexical"
    assert body["retrieval"]["embeddingConfigured"] is False


# ------------------------------------------------------------------ auth
def test_requests_without_a_token_are_rejected(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/conversations").status_code == 401


def test_the_old_spoofable_header_no_longer_authenticates_anything(client):
    """The whole point of this phase.

    `X-User-Id` used to be identity. A bypass left in "for development" is a
    bypass in production, so it was removed rather than kept as a fallback.
    """
    response = client.get("/api/documents", headers={"X-User-Id": "user-sanyam"})
    assert response.status_code == 401


def test_a_fabricated_token_is_rejected(client):
    response = client.get(
        "/api/documents", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_login_returns_a_token_and_the_user(client):
    from tests.conftest import DEMO_PASSWORD

    response = client.post(
        "/api/auth/login",
        json={
            "email": "certification@bis-helpdesk.example",
            "password": DEMO_PASSWORD,
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["user"]["id"] == "user-ananya"
    assert body["token"]
    # The token is opaque and carries no claims a client could read or forge.
    assert "user-ananya" not in body["token"]


def test_every_seeded_persona_can_sign_in(client):
    """Every card on the login screen must work."""
    from tests.conftest import DEMO_PASSWORD

    for user in client.get("/api/users").json():
        response = client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": DEMO_PASSWORD},
        )
        assert response.status_code == 200, f"{user['id']} cannot sign in"


def test_a_wrong_password_is_refused(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "certification@bis-helpdesk.example",
            "password": "not-the-password",
        },
    )
    assert response.status_code == 401


def test_an_unknown_account_and_a_wrong_password_are_indistinguishable(client):
    """Telling them apart lets anyone enumerate who has an account.

    On a plant system that is a staff list, so both paths return the same
    status and the same words.
    """
    from tests.conftest import DEMO_PASSWORD

    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": DEMO_PASSWORD},
    )
    wrong = client.post(
        "/api/auth/login",
        json={
            "email": "certification@bis-helpdesk.example",
            "password": "not-the-password",
        },
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_login_without_a_password_is_rejected(client):
    """There is no identifier-only sign-in any more."""
    response = client.post(
        "/api/auth/login", json={"email": "certification@bis-helpdesk.example"}
    )
    assert response.status_code == 422


def test_login_with_no_credentials_at_all_is_rejected(client):
    assert client.post("/api/auth/login", json={}).status_code == 422


# ---------------------------------------------------------------- agents
def test_list_agents_returns_camel_case(client, owner_headers):
    agents = client.get("/api/agents", headers=owner_headers).json()

    assert len(agents) >= 3
    assert "isSystem" in agents[0]
    assert {a["id"] for a in agents} >= {"maint-intel", "sop-assistant", "doc-vision"}


def test_create_agent_persists_and_links_tools(client, owner_headers):
    response = client.post(
        "/api/agents",
        headers=owner_headers,
        json={
            "name": "Heat Exchanger Diagnostics",
            "description": "Shell-and-tube fouling analysis.",
            "tools": ["Document Search", "Calculator"],
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["isSystem"] is False

    fetched = client.get(f"/api/agents/{created['id']}", headers=owner_headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Heat Exchanger Diagnostics"


# ------------------------------------------------------------- documents
def test_seeded_documents_are_genuinely_indexed(client, owner_headers):
    """The demo corpus is real files, extracted and indexed at seed time.

    Before Phase 18 these were catalogue rows with no bytes, so a fresh
    checkout could retrieve nothing. The honest invariant is not "nothing is
    indexed" but "nothing claims an index it does not have" - so a document
    reporting Indexed must have chunks, bytes and extracted characters to
    back the claim.
    """
    docs = {d["id"]: d for d in client.get("/api/documents", headers=owner_headers).json()}

    assert docs, "expected seeded documents"
    for doc_id in ("doc-1", "doc-2", "doc-3", "doc-4", "doc-5"):
        doc = docs[doc_id]
        assert doc["status"] == "Indexed", f"{doc_id} is {doc['status']}"
        assert doc["chunks"] > 0
        assert doc["hasStoredFile"] is True
        assert doc["extractedChars"] > 0
        assert doc["indexError"] == ""
        # No embedder is configured in tests, so nothing may claim semantics.
        assert doc["isSemanticallyIndexed"] is False


def test_a_document_status_is_never_asserted_ahead_of_its_chunks(
    client, owner_headers
):
    """The rule that outlives any particular corpus."""
    for doc in client.get("/api/documents", headers=owner_headers).json():
        if doc["status"] == "Indexed":
            assert doc["chunks"] > 0, f"{doc['name']} claims an index with no chunks"
        else:
            assert doc["chunks"] == 0, f"{doc['name']} has chunks but denies them"


def test_indexing_a_document_with_no_stored_file_is_refused(
    client, owner_headers, db_session
):
    """A catalogue row with no bytes has nothing to index.

    Every seeded document now has a file, so this constructs the state
    directly rather than relying on one being empty.
    """
    from app.database.models import Document

    db_session.add(
        Document(
            id="doc-catalogue-only",
            name="Never Uploaded.pdf",
            type="PDF",
            folder="All Units",
            owner_id="user-sanyam",
            storage_path=None,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/documents/doc-catalogue-only/index", headers=owner_headers
    )
    assert response.status_code == 409
    assert "no stored file" in response.json()["detail"]


def test_document_scope_is_enforced_server_side(
    client, owner_headers, engineer_headers, safety_headers
):
    owner_docs = client.get("/api/documents", headers=owner_headers).json()
    engineer_docs = client.get("/api/documents", headers=engineer_headers).json()
    safety_docs = client.get("/api/documents", headers=safety_headers).json()

    owner_ids = {d["id"] for d in owner_docs}
    engineer_ids = {d["id"] for d in engineer_docs}
    safety_ids = {d["id"] for d in safety_docs}

    # The confidential document reaches the owner only - it is never sent to
    # the other clients at all, not merely hidden by them.
    assert "doc-5" in owner_ids
    assert "doc-5" not in engineer_ids
    assert "doc-5" not in safety_ids

    # Folder scoping.
    assert engineer_ids >= {"doc-1", "doc-2", "doc-4"}   # CDU-II
    assert "doc-3" not in engineer_ids                    # Safety folder
    assert "doc-3" in safety_ids
    assert not safety_ids & {"doc-1", "doc-2", "doc-4"}   # CDU-II is not theirs


def test_personal_uploads_are_not_shared_between_users(
    client, engineer_headers, safety_headers
):
    """"Personal Uploads" is a per-user namespace, not a shared folder.

    Regression: it appeared in more than one user's assigned_folders, which
    made every user's private uploads visible to the others.
    """
    uploaded = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("private-note.txt", io.BytesIO(b"mine"), "text/plain")},
    ).json()
    assert uploaded["folder"] == "Personal Uploads"

    visible_to_other = {
        d["id"] for d in client.get("/api/documents", headers=safety_headers).json()
    }
    assert uploaded["id"] not in visible_to_other

    # Nor by direct fetch.
    assert (
        client.get(f"/api/documents/{uploaded['id']}", headers=safety_headers).status_code
        == 404
    )


def test_direct_fetch_of_out_of_scope_document_is_denied(client, engineer_headers):
    response = client.get("/api/documents/doc-5", headers=engineer_headers)
    # 404 rather than 403: a 403 would confirm the document exists.
    assert response.status_code == 404


def test_upload_queues_indexing_and_reports_processing(client, engineer_headers):
    """The upload response is written before indexing has run.

    It must therefore say "Processing" - never "Indexed", which would be a
    claim about work that has not happened, and never a chunk count.
    """
    response = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("inspection.txt", io.BytesIO(b"synthetic content"), "text/plain")},
    )
    assert response.status_code == 201

    doc = response.json()
    assert doc["status"] == "Processing"
    assert doc["chunks"] == 0
    assert doc["folder"] == "Personal Uploads"
    assert doc["ownerId"] == "user-ananya"
    # The excerpt is written by the indexer from real extracted text, so it
    # is still empty at this point rather than invented.
    assert doc["excerpt"] == ""


def test_uploaded_text_is_indexed_and_becomes_searchable(client, engineer_headers):
    """End to end: upload -> extract -> chunk -> retrievable with a citation."""
    uploaded = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={
            "file": (
                "pump-note.txt",
                io.BytesIO(
                    b"Pump P-991 vibration tolerance is 2.5 mm/s RMS.\n"
                    b"Bearing housing oil must be checked every 500 hours."
                ),
                "text/plain",
            )
        },
    ).json()

    # TestClient runs background tasks before returning, so the follow-up
    # fetch sees the finished index.
    doc = client.get(f"/api/documents/{uploaded['id']}", headers=engineer_headers).json()
    assert doc["status"] == "Indexed"
    assert doc["chunks"] >= 1
    assert doc["indexError"] == ""
    # The excerpt is now real extracted text, not an authored placeholder.
    assert "P-991" in doc["excerpt"]
    # No embedder is configured, so this must not claim to be semantic.
    assert doc["isSemanticallyIndexed"] is False

    hits = client.post(
        "/api/search",
        headers=engineer_headers,
        json={"query": "P-991 vibration tolerance"},
    ).json()
    assert hits["mode"] == "lexical"
    assert any(h["documentId"] == uploaded["id"] for h in hits["results"])


def test_image_upload_is_marked_unsupported_not_indexed(client, engineer_headers):
    """A format with no text layer must say so, not sit silently un-indexed."""
    uploaded = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("scan.png", io.BytesIO(PNG_MAGIC), "image/png")},
    ).json()

    # Not extractable, so it is never queued: it reports "Ready for
    # indexing" and an explicit reason on demand rather than "Processing"
    # for ever.
    assert uploaded["status"] == "Ready for indexing"

    queued = client.post(
        f"/api/documents/{uploaded['id']}/index", headers=engineer_headers
    )
    assert queued.status_code == 202

    doc = client.get(f"/api/documents/{uploaded['id']}", headers=engineer_headers).json()
    assert doc["status"] == "No extractable text"
    assert doc["chunks"] == 0
    assert "OCR" in doc["indexError"] or "vision" in doc["indexError"]


def test_upload_rejects_disallowed_file_type(client, engineer_headers):
    response = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert response.status_code == 415


def test_upload_rejects_path_traversal_filename(client, engineer_headers):
    response = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("../../escape.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert response.status_code == 201
    # The stored name is sanitised; the display name keeps only the basename.
    assert "/" not in response.json()["name"]
    assert ".." not in response.json()["name"]


# ----------------------------------------------------------------- tools
def test_toggle_tool_flips_state(client, owner_headers):
    before = client.get("/api/tools", headers=owner_headers).json()
    original = next(t for t in before if t["id"] == "calculator")["enabled"]

    after = client.post("/api/tools/calculator/toggle", headers=owner_headers).json()
    assert next(t for t in after if t["id"] == "calculator")["enabled"] is not original

    # Restore.
    client.post("/api/tools/calculator/toggle", headers=owner_headers)


# --------------------------------------------------------- conversations
def test_conversations_are_scoped_to_their_owner(client, owner_headers, safety_headers):
    owner_convs = client.get("/api/conversations", headers=owner_headers).json()
    assert any(c["id"] == "conv-demo-p204" for c in owner_convs)

    other_convs = client.get("/api/conversations", headers=safety_headers).json()
    assert all(c["id"] != "conv-demo-p204" for c in other_convs)

    # And it cannot be fetched directly either.
    assert client.get("/api/conversations/conv-demo-p204", headers=safety_headers).status_code == 404


def test_seeded_demo_answer_is_labelled_as_seeded(client, owner_headers):
    conv = client.get("/api/conversations/conv-demo-p204", headers=owner_headers).json()
    assistant = next(m for m in conv["messages"] if m["sender"] == "assistant")

    labels = [step["label"] for step in assistant["activityTrace"]]
    assert any("Seeded demo content" in label for label in labels)


def test_conversations_can_be_pinned_and_sort_first(client, owner_headers):
    # Build our own fixtures rather than depending on how many the seed
    # happens to create, or on what earlier tests left behind.
    older = client.post(
        "/api/conversations", headers=owner_headers, json={"title": "Older thread"}
    ).json()
    client.post(
        "/api/conversations", headers=owner_headers, json={"title": "Newer thread"}
    )

    convs = client.get("/api/conversations", headers=owner_headers).json()
    assert convs[0]["id"] != older["id"], "newer thread should lead by default"

    target = older["id"]
    updated = client.patch(
        f"/api/conversations/{target}", headers=owner_headers, json={"pinned": True}
    )
    assert updated.status_code == 200
    assert updated.json()["pinned"] is True

    after = client.get("/api/conversations", headers=owner_headers).json()
    assert after[0]["id"] == target, "pinned conversation should sort first"

    # And unpinning puts it back.
    client.patch(
        f"/api/conversations/{target}", headers=owner_headers, json={"pinned": False}
    )
    restored = client.get("/api/conversations", headers=owner_headers).json()
    assert restored[0]["id"] != target


def test_pinning_someone_elses_conversation_is_denied(client, safety_headers):
    response = client.patch(
        "/api/conversations/conv-demo-p204", headers=safety_headers, json={"pinned": True}
    )
    assert response.status_code == 404


def test_deleting_a_conversation_removes_it_and_its_messages(client, owner_headers):
    created = client.post(
        "/api/conversations", headers=owner_headers, json={"title": "Delete me"}
    ).json()

    assert client.delete(
        f"/api/conversations/{created['id']}", headers=owner_headers
    ).status_code == 204

    assert client.get(
        f"/api/conversations/{created['id']}", headers=owner_headers
    ).status_code == 404


def test_deleting_someone_elses_conversation_is_denied(
    client, owner_headers, safety_headers
):
    response = client.delete(
        "/api/conversations/conv-demo-p204", headers=safety_headers
    )
    assert response.status_code == 404
    # And it still exists for its owner.
    assert client.get(
        "/api/conversations/conv-demo-p204", headers=owner_headers
    ).status_code == 200


# ------------------------------------------------------------------ chat
def test_chat_without_a_provider_fails_loudly(client, safety_headers):
    """With MODEL_PROVIDER=none the API must refuse, not improvise.

    The earlier milestone returned a canned placeholder here. Now that a
    real gateway exists, an unconfigured provider is a 503 - never a
    fabricated assistant turn.
    """
    response = client.post(
        "/api/chat",
        headers=safety_headers,
        json={"message": "What PPE is required in CDU-II?", "agentId": "sop-assistant"},
    )
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert "MODEL_PROVIDER" in detail["message"]

    # The user's message was still persisted, so nothing is lost on retry.
    conv = client.get(
        f"/api/conversations/{detail['conversationId']}", headers=safety_headers
    ).json()
    assert conv["messages"][-1]["sender"] == "user"
    assert conv["messages"][-1]["text"] == "What PPE is required in CDU-II?"
    # No assistant turn was invented.
    assert all(m["sender"] == "user" for m in conv["messages"])


def test_chat_stream_without_a_provider_emits_an_error_event(client, safety_headers):
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=safety_headers,
        json={"message": "Anything at all"},
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())

    assert "event: error" in raw
    assert "event: done" not in raw


def test_models_endpoint_reports_no_provider(client):
    body = client.get("/api/models").json()
    assert body["provider"] == "none"
    assert body["configured"] is False
    assert body["available"] == []


def test_health_reports_inference_provenance(client):
    inference = client.get("/api/health").json()["inference"]
    assert inference["provider"] == "none"
    assert inference["configured"] is False
    # Never claim on-premise inference when there is no inference at all.
    assert inference["onPremise"] is False


# -------------------------------------------------------------- settings
def test_settings_round_trip(client, owner_headers):
    updated = client.patch(
        "/api/settings", headers=owner_headers, json={"theme": "dark", "temperature": 0.5}
    ).json()
    assert updated["theme"] == "dark"
    assert updated["temperature"] == 0.5

    again = client.get("/api/settings", headers=owner_headers).json()
    assert again["theme"] == "dark"

    client.patch("/api/settings", headers=owner_headers, json={"theme": "light"})


def test_settings_rejects_out_of_range_temperature(client, owner_headers):
    response = client.patch(
        "/api/settings", headers=owner_headers, json={"temperature": 5}
    )
    assert response.status_code == 422


def test_settings_publishes_the_styles_the_server_honours(client, owner_headers):
    """The picker reads its options from here rather than hardcoding them.

    It used to hardcode three while the prompt builder knew five, so the
    default style was not selectable and the control displayed a value the
    user had not chosen.
    """
    from app.services import prompts

    body = client.get("/api/settings", headers=owner_headers).json()

    assert body["responseStyleOptions"] == list(prompts.RESPONSE_STYLES)
    assert prompts.DEFAULT_RESPONSE_STYLE in body["responseStyleOptions"]


def test_settings_rejects_a_style_the_prompt_builder_does_not_know(
    client, owner_headers
):
    """An unknown style used to save happily and then do nothing.

    `build_system_prompt` falls back to Balanced for anything unrecognised,
    so storing one produced a setting that persisted, displayed itself back,
    and had no effect on a single answer.
    """
    response = client.patch(
        "/api/settings", headers=owner_headers, json={"responseStyle": "Shakespearean"}
    )
    assert response.status_code == 422

    unchanged = client.get("/api/settings", headers=owner_headers).json()
    assert unchanged["responseStyle"] != "Shakespearean"


def test_every_published_style_is_actually_accepted(client, owner_headers):
    """Whatever the picker offers must round-trip. Otherwise the list lies."""
    options = client.get("/api/settings", headers=owner_headers).json()[
        "responseStyleOptions"
    ]
    assert options, "the server published no styles at all"

    for style in options:
        saved = client.patch(
            "/api/settings", headers=owner_headers, json={"responseStyle": style}
        )
        assert saved.status_code == 200, f"{style} was offered but rejected"
        assert saved.json()["responseStyle"] == style

    client.patch(
        "/api/settings",
        headers=owner_headers,
        json={"responseStyle": options[0]},
    )


# --------------------------------------------------------- notifications
def test_marking_a_notification_read_updates_it(client, owner_headers):
    notifications = client.get("/api/notifications", headers=owner_headers).json()
    target = notifications[0]

    updated = client.post(
        f"/api/notifications/{target['id']}/read", headers=owner_headers
    ).json()
    assert next(n for n in updated if n["id"] == target["id"])["read"] is True


# ---------------------------------------------------------------------------
# Database URL handling
# ---------------------------------------------------------------------------
def test_a_hosting_provider_database_url_points_at_the_installed_driver():
    """Providers hand out `postgres://` or `postgresql://`.

    SQLAlchemy maps both to psycopg2, which this project does not install -
    it uses psycopg 3. Left alone, the container dies at startup with a
    ModuleNotFoundError naming psycopg2, which says nothing about the URL
    being the cause.
    """
    from app.core.config import _normalise_db_url

    render_style = "postgresql://u:p@dpg-x.singapore-postgres.render.com/wb"
    heroku_style = "postgres://u:p@host:5432/wb"

    for url in (render_style, heroku_style):
        assert _normalise_db_url(url).startswith("postgresql+psycopg://")
        # The rest of the URL is untouched - only the scheme is rewritten.
        assert url.split("://", 1)[1] == _normalise_db_url(url).split("://", 1)[1]


def test_normalising_leaves_everything_else_alone():
    from app.core.config import _normalise_db_url

    already = "postgresql+psycopg://u:p@host/wb"
    assert _normalise_db_url(already) == already

    sqlite = "sqlite:////data/synq_workbench.db"
    assert _normalise_db_url(sqlite) == sqlite

    assert _normalise_db_url("") == ""
