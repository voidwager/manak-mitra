"""Document management tests.

The read-side scoping is covered in test_api.py and test_rag.py. This file
covers the write side, which since Phase 8 is the more dangerous half:
`folder`, `is_confidential_owner_only` and `owner_id` between them decide
who can retrieve a document's contents through the assistant.

So the tests that matter most here are not "does PATCH work" but "does a
metadata change propagate to retrieval, and can a user make a change that
grants access they were not entitled to give away".
"""

import io
import re

import pytest

LICENCE_TEXT = (
    b"Section 6.1 Licence renewal\n"
    b"\n"
    b"Licence L-3140 renewal is verified with an inspection after any change\n"
    b"of premises. A marking fee discrepancy above 0.05 percent of turnover\n"
    b"requires re-rating before the licence is renewed.\n"
)


def _unique_text(marker: str) -> bytes:
    """Body text no other test will upload.

    Retrieval returns a ranked top-k, so "is this id in the results" is only
    a question about permissions when nothing else competes for the same
    query. Sharing LICENCE_TEXT across every upload made that assertion depend
    on how many other tests had run first.
    """
    return (
        f"Section 6.1 {marker} renewal\n"
        f"\n"
        f"Licence {marker} renewal is verified with an inspection after any\n"
        f"change of premises. A marking fee discrepancy above 0.05 percent of\n"
        f"turnover requires re-rating before the licence is renewed.\n"
    ).encode()


def _upload(client, headers, name: str, data: bytes = LICENCE_TEXT) -> dict:
    created = client.post(
        "/api/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(data), "text/plain")},
    ).json()
    return client.get(f"/api/documents/{created['id']}", headers=headers).json()


def _search(client, headers, query: str) -> list[str]:
    body = client.post("/api/search", headers=headers, json={"query": query}).json()
    return [hit["documentId"] for hit in body["results"]]


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
def test_folders_lists_the_namespace_and_what_the_user_may_use(
    client, engineer_headers
):
    body = client.get("/api/folders", headers=engineer_headers).json()

    assert body["unrestricted"] is False
    # Ananya is assigned to the Certification Desk, plus her personal
    # namespace. The public folders are hers to read but not to file into.
    assert set(body["assignable"]) == {"Personal Uploads", "Certification Desk"}
    # The full namespace is informational and is wider than her grant.
    assert set(body["all"]) >= {
        "Certification Desk",
        "Hallmarking Desk",
        "BIS Internal",
        "Hallmarking",
    }
    assert set(body["assignable"]) <= set(body["all"])


def test_owner_clearance_is_unrestricted(client, owner_headers):
    body = client.get("/api/folders", headers=owner_headers).json()
    assert body["unrestricted"] is True
    assert body["assignable"] == body["all"]


# ---------------------------------------------------------------------------
# Moving a document is an access-control change
# ---------------------------------------------------------------------------
def test_publishing_a_document_changes_who_can_retrieve_it(
    client, owner_headers, engineer_headers, safety_headers
):
    """The behaviour the whole feature exists for.

    Ananya's upload starts in her personal space, where nobody else can
    reach it. Filing it into a folder she is on makes its *contents*
    retrievable by the others on that folder - not just its title - and no
    re-index is needed, because chunks are reached through their document.
    """
    doc = _upload(
        client,
        engineer_headers,
        "licence-renewal.txt",
        _unique_text("PUBLISH-4417"),
    )
    query = "PUBLISH-4417 licence renewal"
    assert doc["folder"] == "Personal Uploads"
    assert doc["visibility"] == "personal"
    assert doc["status"] == "Indexed"

    # Personal means personal: not the owner, not another employee.
    assert doc["id"] not in _search(client, safety_headers, query)
    assert doc["id"] not in _search(client, owner_headers, query)

    # Ananya may not file into the Hallmarking Desk - she is not assigned to it.
    refused = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Hallmarking Desk"},
    )
    assert refused.status_code == 403
    assert "not assigned to 'Hallmarking Desk'" in refused.json()["detail"]

    # Nor into a public folder: that would publish to every visitor, and
    # only an administrator may do that.
    refused_public = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Schemes"},
    )
    assert refused_public.status_code == 403

    # She publishes into a folder she is actually on.
    moved = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Desk"},
    )
    assert moved.status_code == 200
    assert moved.json()["folder"] == "Certification Desk"
    assert moved.json()["visibility"] == "shared"

    # Now it is shared, the owner can retrieve it. Dev still cannot - he is
    # not on the Certification Desk, and publishing is not the same as publishing to all.
    assert doc["id"] in _search(client, owner_headers, query)
    assert doc["id"] not in _search(client, safety_headers, query)


def test_an_administrator_cannot_read_a_personal_document(
    client, owner_headers, engineer_headers
):
    """The guarantee the word "personal" has to earn.

    Owner clearance used to return every row, so an administrator silently
    read every officer's private uploads - and the assistant would quote
    them back in an answer, paraphrased, where nobody re-checks permissions.
    """
    doc = _upload(client, engineer_headers, "private-notes.txt")
    assert doc["visibility"] == "personal"

    assert client.get(f"/api/documents/{doc['id']}", headers=owner_headers).status_code == 404
    listed = client.get("/api/documents", headers=owner_headers).json()
    assert doc["id"] not in {d["id"] for d in listed}
    assert doc["id"] not in _search(client, owner_headers, "P-3140 licence renewal")

    # And the uploader still has it.
    assert client.get(f"/api/documents/{doc['id']}", headers=engineer_headers).status_code == 200


def test_an_administrator_cannot_publish_someone_elses_personal_document(
    client, owner_headers, engineer_headers
):
    """Otherwise the previous guarantee lasts exactly one request.

    Publish-then-read would be a two-step way round it, so publishing a
    personal document is reserved to the person who uploaded it.
    """
    doc = _upload(client, engineer_headers, "not-yours-to-share.txt")

    response = client.patch(
        f"/api/documents/{doc['id']}",
        headers=owner_headers,
        json={"folder": "Certification Schemes"},
    )
    # 404 rather than 403: confirming it exists would itself leak something.
    assert response.status_code == 404

    unchanged = client.get(f"/api/documents/{doc['id']}", headers=engineer_headers).json()
    assert unchanged["folder"] == "Personal Uploads"


def test_moving_back_to_personal_uploads_withdraws_the_document(
    client, owner_headers, engineer_headers
):
    """`Personal Uploads` is a namespace, not a folder - moving in un-shares."""
    doc = _upload(
        client, engineer_headers, "withdraw-me.txt", _unique_text("WITHDRAW-2280")
    )
    query = "WITHDRAW-2280 licence renewal"

    client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Desk"},
    )
    assert doc["id"] in _search(client, owner_headers, query)

    # Ananya owns it, and Personal Uploads is always assignable to her.
    withdrawn = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Personal Uploads"},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["visibility"] == "personal"

    assert doc["id"] not in _search(client, owner_headers, query)
    # ...but the uploader still has it.
    assert doc["id"] in _search(client, engineer_headers, query)


def test_an_administrator_can_withdraw_a_shared_document(
    client, owner_headers, engineer_headers
):
    """Demotion is allowed where promotion is not.

    An administrator taking something out of circulation is governance;
    putting somebody's private file into circulation is not theirs to do.
    """
    doc = _upload(client, engineer_headers, "published-then-pulled.txt")
    client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Desk"},
    )

    pulled = client.patch(
        f"/api/documents/{doc['id']}",
        headers=owner_headers,
        json={"folder": "Personal Uploads"},
    )
    assert pulled.status_code == 200
    assert pulled.json()["visibility"] == "personal"

    # It went back to its uploader, who still has it, and left the owner.
    assert client.get(f"/api/documents/{doc['id']}", headers=engineer_headers).status_code == 200
    assert client.get(f"/api/documents/{doc['id']}", headers=owner_headers).status_code == 404


def test_a_user_cannot_file_a_document_into_a_folder_they_invented(
    client, engineer_headers
):
    doc = _upload(client, engineer_headers, "invented-folder.txt")

    response = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Board Papers"},
    )
    assert response.status_code == 403
    assert "Folders available to you" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Confidentiality
# ---------------------------------------------------------------------------
def test_marking_confidential_removes_a_document_from_other_users_retrieval(
    client, owner_headers, engineer_headers
):
    doc = _upload(
        client, owner_headers, "board-only.txt", _unique_text("BOARDONLY-9931")
    )
    # Every upload starts personal now, an administrator's included. Put it
    # somewhere Ananya can reach.
    client.patch(
        f"/api/documents/{doc['id']}", headers=owner_headers, json={"folder": "Certification Desk"}
    )
    query = "BOARDONLY-9931 licence renewal"
    assert doc["id"] in _search(client, engineer_headers, query)

    client.patch(
        f"/api/documents/{doc['id']}",
        headers=owner_headers,
        json={"isConfidentialOwnerOnly": True},
    )

    assert doc["id"] not in _search(client, engineer_headers, query)
    assert (
        client.get(f"/api/documents/{doc['id']}", headers=engineer_headers).status_code
        == 404
    )
    assert doc["id"] in _search(client, owner_headers, query)

    # Classifying files it into the one restricted folder, because that is
    # what the access rules actually read.
    classified = client.get(f"/api/documents/{doc['id']}", headers=owner_headers).json()
    assert classified["folder"] == "BIS Internal"
    assert classified["visibility"] == "restricted"


def test_an_employee_cannot_mark_their_own_upload_confidential(
    client, engineer_headers
):
    """Confidentiality is a classification, not a personal privacy toggle."""
    doc = _upload(client, engineer_headers, "not-mine-to-classify.txt")

    response = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"isConfidentialOwnerOnly": True},
    )
    assert response.status_code == 403
    assert "owner clearance" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Ownership and editing rights
# ---------------------------------------------------------------------------
def test_ownership_transfer_is_owner_clearance_only(client, owner_headers, engineer_headers):
    doc = _upload(client, engineer_headers, "handover.txt")

    refused = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"ownerId": "user-dev"},
    )
    assert refused.status_code == 403

    # Published first: an administrator cannot act on a personal document at
    # all, so there is nothing to transfer until its uploader shares it.
    client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Desk"},
    )

    accepted = client.patch(
        f"/api/documents/{doc['id']}", headers=owner_headers, json={"ownerId": "user-dev"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["ownerId"] == "user-dev"


def test_transfer_to_an_unknown_user_is_rejected(client, owner_headers):
    doc = _upload(client, owner_headers, "nowhere-to-go.txt")
    response = client.patch(
        f"/api/documents/{doc['id']}", headers=owner_headers, json={"ownerId": "user-nope"}
    )
    assert response.status_code == 422


def test_editing_someone_elses_document_is_refused(client, owner_headers, engineer_headers, safety_headers):
    """Dev can see it once it is shared, but seeing is not editing."""
    doc = _upload(client, owner_headers, "read-only-to-dev.txt")
    client.patch(
        f"/api/documents/{doc['id']}",
        headers=owner_headers,
        json={"folder": "Hallmarking Desk"},
    )

    assert client.get(f"/api/documents/{doc['id']}", headers=safety_headers).status_code == 200

    response = client.patch(
        f"/api/documents/{doc['id']}", headers=safety_headers, json={"name": "Mine now.txt"}
    )
    assert response.status_code == 403


def test_editing_an_invisible_document_is_a_404_not_a_403(client, engineer_headers):
    """A 403 would confirm int-analytics exists. Same rule as the read path."""
    response = client.patch(
        "/api/documents/int-analytics", headers=engineer_headers, json={"name": "peek.md"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------
def test_rename_changes_the_display_name_but_not_the_stored_file(
    client, engineer_headers
):
    doc = _upload(client, engineer_headers, "before-rename.txt")

    renamed = client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"name": "Licence Renewal Guide.txt"},
    ).json()
    assert renamed["name"] == "Licence Renewal Guide.txt"

    # The bytes are still reachable, so the rename did not orphan the file.
    assert client.get(
        f"/api/documents/{doc['id']}/download", headers=engineer_headers
    ).status_code == 200


def test_an_empty_patch_is_a_no_op_not_an_error(client, engineer_headers):
    doc = _upload(client, engineer_headers, "unchanged.txt")
    response = client.patch(
        f"/api/documents/{doc['id']}", headers=engineer_headers, json={}
    )
    assert response.status_code == 200
    assert response.json()["name"] == doc["name"]


@pytest.mark.parametrize("name", ["", "   "])
def test_a_blank_rename_is_rejected(client, engineer_headers, name):
    doc = _upload(client, engineer_headers, f"blank-{len(name)}.txt")
    response = client.patch(
        f"/api/documents/{doc['id']}", headers=engineer_headers, json={"name": name}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def test_download_returns_the_original_bytes_as_an_attachment(
    client, engineer_headers
):
    doc = _upload(client, engineer_headers, "download-me.txt")

    response = client.get(
        f"/api/documents/{doc['id']}/download", headers=engineer_headers
    )
    assert response.status_code == 200
    assert response.content == LICENCE_TEXT

    # Never inline: an uploaded file rendered in the API's own origin is
    # stored XSS against everyone who opens it.
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "download-me.txt" in disposition
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_is_scope_checked(client, engineer_headers, safety_headers):
    doc = _upload(client, engineer_headers, "private-download.txt")
    assert (
        client.get(
            f"/api/documents/{doc['id']}/download", headers=safety_headers
        ).status_code
        == 404
    )


def test_downloading_a_catalogue_entry_explains_there_is_no_file(
    client, owner_headers, db_session
):
    """Seeded documents now have real files, so this builds the empty case."""
    from app.database.models import Document

    db_session.add(
        Document(
            id="doc-no-bytes",
            name="Catalogue Only.pdf",
            type="PDF",
            folder="Certification Desk",
            owner_id="user-sanyam",
            storage_path=None,
        )
    )
    db_session.commit()

    response = client.get("/api/documents/doc-no-bytes/download", headers=owner_headers)
    assert response.status_code == 404
    assert "no stored file" in response.json()["detail"]


def test_a_seeded_document_can_be_downloaded(client, owner_headers):
    """The demo corpus is real bytes, so the download path works on it."""
    response = client.get("/api/documents/bis-01/download", headers=owner_headers)
    assert response.status_code == 200
    assert b"Scheme-I" in response.content, "expected the captured BIS page"


def test_a_document_name_cannot_break_out_of_the_download_header(
    client, engineer_headers
):
    """A crafted name must not inject a header or a second filename.

    The attacker's text surviving *inside* one filename is fine - it is just
    a filename. What must not happen is it becoming structure: a second
    `filename=` parameter that a browser might prefer, or a line break that
    starts a header of its own.
    """
    doc = _upload(client, engineer_headers, "quoted.txt")
    client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"name": 'evil"; filename="pwned.exe'},
    )

    response = client.get(
        f"/api/documents/{doc['id']}/download", headers=engineer_headers
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]

    # Exactly one plain `filename=` (the starred form is a distinct token).
    assert len(re.findall(r"(?<!\*)filename=", disposition)) == 1
    # The quoted value holds no quote of its own to close it early.
    quoted = re.search(r'(?<!\*)filename="([^"]*)"', disposition)
    assert quoted and '"' not in quoted.group(1)
    # No CR/LF, so no injected header.
    assert "\r" not in disposition and "\n" not in disposition


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def test_a_folder_move_is_audited_with_before_and_after(
    client, owner_headers, engineer_headers, db_session
):
    """Governance needs to see who moved what, and out of which folder."""
    from app.database.models import AuditLog

    doc = _upload(client, engineer_headers, "audited-move.txt")
    client.patch(
        f"/api/documents/{doc['id']}",
        headers=engineer_headers,
        json={"folder": "Certification Desk"},
    )

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.resource_id == doc["id"], AuditLog.action == "document.update")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.detail["fields"] == ["folder"]
    assert entry.detail["before"]["folder"] == "Personal Uploads"
    assert entry.detail["after"]["folder"] == "Certification Desk"


# ---------------------------------------------------------------------------
# Chat-scoped documents
# ---------------------------------------------------------------------------
def test_promoting_a_chat_file_puts_it_in_the_knowledge_base(
    client, owner_headers, engineer_headers
):
    """A file attached in chat is searchable there, and nowhere, until kept."""
    import io

    attached = client.post(
        "/api/attachments",
        headers=engineer_headers,
        files={
            "file": (
                "desk-notes.txt",
                io.BytesIO(b"Enquiry ENQ-77 was answered within 92 minutes by the evening desk."),
                "text/plain",
            )
        },
    ).json()
    document_id = attached["documentId"]

    # Bound to no conversation yet, so retrieval finds nothing.
    query = "ENQ-77 evening desk"
    assert document_id not in _search(client, engineer_headers, query)

    promoted = client.patch(
        f"/api/documents/{document_id}",
        headers=engineer_headers,
        json={"promoteFromChat": True},
    )
    assert promoted.status_code == 200
    assert promoted.json()["conversationId"] is None
    # It lands in her personal space, not shared - promotion is not publishing.
    assert promoted.json()["visibility"] == "personal"

    # Now it is part of her corpus.
    assert document_id in _search(client, engineer_headers, query)
    # And still nobody else's.
    assert document_id not in _search(client, owner_headers, query)


def test_only_the_uploader_can_promote_their_chat_file(
    client, owner_headers, engineer_headers
):
    import io

    attached = client.post(
        "/api/attachments",
        headers=engineer_headers,
        files={
            "file": (
                "not-yours.txt",
                io.BytesIO(b"Licence L-101 renewal margin notes."),
                "text/plain",
            )
        },
    ).json()

    response = client.patch(
        f"/api/documents/{attached['documentId']}",
        headers=owner_headers,
        json={"promoteFromChat": True},
    )
    # 404: it is personal, so an administrator cannot see it to act on it.
    assert response.status_code == 404
