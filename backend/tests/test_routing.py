"""Model routing and image attachments.

The guarantee worth protecting: an image is only ever sent to a model that
accepts images. Sending one to a text-only model does not fail cleanly - the
runtime either errors in a way that looks like a server fault, or drops the
picture and answers as though it had looked. The second is worse, because
the user trusts the answer.

The rest pins routing being *deterministic and explainable*. There is no
"this looks like a hard question" heuristic, and there must never be one: a
router that switches models on a hunch cannot be debugged and makes every
answer irreproducible.
"""

import io

import pytest


def _minimal_pdf(sentence: bytes) -> bytes:
    """A genuinely valid one-page PDF containing `sentence`.

    Built by hand rather than fixtured, so the test proves the real
    extractor reads a real PDF. A stub of bytes merely starting with %PDF
    would satisfy the assertion while proving nothing.
    """
    content = b"BT /F1 12 Tf 72 720 Td (" + sentence + b") Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length "
        + str(len(content)).encode()
        + b">>stream\n"
        + content
        + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


from app.core.config import Settings
from app.models import router as model_router
from tests.conftest import StubProvider

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + bytes(64)


def _settings(**overrides) -> Settings:
    """A Settings instance with the routing fields set explicitly."""
    base = {
        "model_name": "default-model",
        "model_vision": "",
        "model_reasoning": "",
        "model_fast": "",
        "model_transcription": "",
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Route resolution
# ---------------------------------------------------------------------------
def test_an_unconfigured_role_falls_back_and_says_it_degraded():
    route = model_router.resolve(
        model_router.ROLE_REASONING, config=_settings()
    )
    assert route.model == "default-model"
    assert route.degraded is True
    assert "No reasoning model is configured" in route.reason


def test_a_configured_role_is_used_and_explains_itself():
    route = model_router.resolve(
        model_router.ROLE_REASONING,
        config=_settings(model_reasoning="big-model"),
    )
    assert route.model == "big-model"
    assert route.degraded is False
    assert "reasoning" in route.reason


def test_an_agent_pin_outranks_the_role_table():
    route = model_router.resolve(
        model_router.ROLE_CHAT,
        pinned="pinned-model",
        config=_settings(model_fast="fast-model"),
    )
    assert route.model == "pinned-model"
    assert "pinned" in route.reason


def test_a_pin_never_overrides_the_vision_route():
    """A text-only pin must not win a turn that carries a picture.

    Honouring it would send an image to a model that cannot see it, and the
    user would read the result as the image being ignored.
    """
    route = model_router.resolve(
        model_router.ROLE_VISION,
        pinned="text-only-model",
        config=_settings(model_vision="vision-model"),
    )
    assert route.model == "vision-model"


def test_vision_with_no_model_configured_is_reported_as_degraded():
    route = model_router.resolve(model_router.ROLE_VISION, config=_settings())
    assert route.degraded is True
    assert "No vision model is configured" in route.reason


def test_an_unknown_role_degrades_to_chat_rather_than_raising():
    route = model_router.resolve("telepathy", config=_settings())
    assert route.model == "default-model"
    assert route.role == model_router.ROLE_CHAT


# ---------------------------------------------------------------------------
# Role selection for a turn
# ---------------------------------------------------------------------------
def test_an_image_forces_the_vision_role_over_any_preference():
    assert (
        model_router.role_for_turn(has_images=True, agent_role="reasoning")
        == model_router.ROLE_VISION
    )


def test_without_images_an_agent_preference_is_honoured():
    assert (
        model_router.role_for_turn(has_images=False, agent_role="fast")
        == model_router.ROLE_FAST
    )


def test_a_meaningless_preference_falls_back_to_chat():
    assert (
        model_router.role_for_turn(agent_role="nonsense") == model_router.ROLE_CHAT
    )


# ---------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------
def test_a_message_without_images_sends_a_plain_string():
    from app.models.base import ChatMessage

    wire = ChatMessage(role="user", content="hello").as_wire()
    assert wire["content"] == "hello"


def test_a_message_with_images_sends_content_parts():
    from app.models.base import ChatMessage

    wire = ChatMessage(
        role="user", content="what is this?", images=("data:image/png;base64,AAA",)
    ).as_wire()

    assert isinstance(wire["content"], list)
    assert wire["content"][0] == {"type": "text", "text": "what is this?"}
    assert wire["content"][1]["type"] == "image_url"
    assert wire["content"][1]["image_url"]["url"].startswith("data:image/png")


# ---------------------------------------------------------------------------
# Attachments through the API
# ---------------------------------------------------------------------------
def test_an_image_attachment_is_stored_and_reported_unreadable_without_vision(
    client, owner_headers
):
    """No vision model is configured in tests, and that must be said."""
    response = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("gauge.png", io.BytesIO(PNG), "image/png")},
    )
    assert response.status_code == 201

    body = response.json()
    assert body["isImage"] is True
    assert body["readable"] is False
    assert "No vision model is configured" in body["note"]


def test_an_attachment_is_private_to_its_uploader(
    client, owner_headers, engineer_headers
):
    """There is no case where another person's chat image belongs to you."""
    created = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("private.png", io.BytesIO(PNG), "image/png")},
    ).json()

    assert (
        client.get(f"/api/attachments/{created['id']}", headers=engineer_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/attachments/{created['id']}", headers=owner_headers).status_code
        == 200
    )


def test_an_unsupported_format_is_still_refused_with_a_reason(
    client, owner_headers
):
    """Executables and archives have no business in a prompt or an index."""
    response = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("tool.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert response.status_code == 415
    assert ".exe" in response.json()["detail"]


def test_an_attached_document_is_indexed_for_that_chat_only(
    client, owner_headers, engineer_headers, stub_gateway
):
    """The behaviour this scoping exists for.

    A document attached to a chat is extracted and indexed like any upload,
    so the very next question can cite it - but it is bound to that one
    conversation. It is not in the shared corpus, not in the uploader's
    other chats, and not in anybody else's search.
    """
    stub_gateway(StubProvider())

    body = b"The licence renewal fee for unit LU-9 is 3412 rupees."
    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("renewal-fees.txt", io.BytesIO(body), "text/plain")},
    )
    assert attached.status_code == 201

    # It produced a document, and that document is indexed.
    document_id = attached.json().get("documentId")
    assert document_id, "an attached document should produce a document"

    stored = client.get(f"/api/documents/{document_id}", headers=owner_headers).json()
    assert stored["chunks"] > 0
    assert stored["status"] == "Indexed"

    # Not in the corpus: a plain search finds nothing, because it belongs to
    # a conversation that has not been named yet.
    hits = client.post(
        "/api/search", headers=owner_headers, json={"query": "LU-9 renewal fee"}
    ).json()
    assert all(h["documentId"] != document_id for h in hits["results"])

    # Sent with a message, it binds to that conversation and is retrievable
    # there.
    reply = client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": "What is the renewal fee for LU-9?",
            "attachments": [
                {"id": attached.json()["id"], "name": "renewal-fees.txt"}
            ],
        },
    )
    assert reply.status_code == 200
    conversation_id = reply.json()["conversationId"]

    bound = client.get(f"/api/documents/{document_id}", headers=owner_headers).json()
    assert bound["conversationId"] == conversation_id

    # A different conversation does not see it.
    other = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "What is the renewal fee for LU-9?"},
    )
    assert other.status_code == 200
    assert other.json()["conversationId"] != conversation_id
    cited = other.json()["assistantMessage"].get("sources") or []
    assert all(c.get("documentId") != document_id for c in cited)

    # And another user cannot reach it at all.
    assert (
        client.get(f"/api/documents/{document_id}", headers=engineer_headers).status_code
        == 404
    )


def test_someone_elses_attachment_id_is_ignored_rather_than_used(
    client, owner_headers, engineer_headers, stub_gateway
):
    """An id naming another user's file must not reach your prompt."""
    stub = stub_gateway(StubProvider())

    theirs = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("secret.txt", io.BytesIO(b"classified rotor design"), "text/plain")},
    ).json()

    client.post(
        "/api/chat",
        headers=engineer_headers,
        json={
            "message": "summarise the attachment",
            "attachments": [{"id": theirs["id"], "name": "secret.txt"}],
        },
    )

    prompt = " ".join(m.content for m in stub.last_prompt)
    assert "classified rotor design" not in prompt


def test_a_text_attachment_is_quoted_as_data_not_instructions(
    client, owner_headers, stub_gateway
):
    stub = stub_gateway(StubProvider())

    created = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={
            "file": (
                "reading.txt",
                io.BytesIO(b"Bearing temperature logged at 71 degrees."),
                "text/plain",
            )
        },
    ).json()

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": "what does the reading say?",
            "attachments": [{"id": created["id"], "name": "reading.txt"}],
        },
    )

    system = " ".join(m.content for m in stub.last_prompt if m.role == "system")
    assert "71 degrees" in system
    # Fenced as data, same as a tool result or a retrieved passage.
    assert "not instructions" in system


def test_an_image_is_not_sent_when_no_vision_model_exists(
    client, owner_headers, stub_gateway
):
    """The guarantee this whole path exists to protect."""
    stub = stub_gateway(StubProvider())

    created = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("photo.png", io.BytesIO(PNG), "image/png")},
    ).json()

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": "what is in this photo?",
            "attachments": [{"id": created["id"], "name": "photo.png"}],
        },
    ).json()

    # No content parts reached the model.
    assert all(not m.images for m in stub.last_prompt)

    # And the model was told, so it says so instead of guessing.
    system = " ".join(m.content for m in stub.last_prompt if m.role == "system")
    assert "no vision model is configured" in system.lower()
    assert "Never guess" in system

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert any("Could not read photo.png" in label for label in labels)


def test_the_trace_no_longer_claims_attachments_are_never_parsed(
    client, owner_headers, stub_gateway
):
    """That line predates the vision path and became false when it landed."""
    stub_gateway(StubProvider())

    created = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("notes.txt", io.BytesIO(b"licence notes"), "text/plain")},
    ).json()

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": "summarise",
            "attachments": [{"id": created["id"], "name": "notes.txt"}],
        },
    ).json()

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert not any("not parsed" in label for label in labels)
    assert any("Included attached text" in label for label in labels)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def test_the_models_endpoint_reports_the_whole_routing_table(client, owner_headers):
    body = client.get("/api/models").json()

    roles = {r["role"]: r for r in body["routes"]}
    assert set(roles) == set(model_router.ROLES)

    # Nothing is configured in the test environment, so every role but chat
    # must report itself as a fallback rather than as a real route.
    for role, entry in roles.items():
        if role != model_router.ROLE_CHAT:
            assert entry["configured"] is False, role


@pytest.mark.parametrize("capability", ["vision", "modelRouting"])
def test_health_does_not_claim_a_routed_capability_it_lacks(client, capability):
    assert client.get("/api/health").json()["implemented"][capability] is False


def test_health_publishes_exactly_what_attachments_accepts(client, owner_headers):
    """The picker reads this list, so it has to be the enforced one.

    It was hardcoded in the browser and went stale the moment documents
    became attachable: the endpoint accepted a PDF while the file dialog
    greyed it out, so the feature existed and could not be reached.
    """
    from app.api.routes.attachments import (
        ALLOWED_SUFFIXES,
        DOCUMENT_SUFFIXES,
        IMAGE_SUFFIXES,
        MAX_ATTACHMENT_BYTES,
    )

    limits = client.get("/api/health", headers=owner_headers).json()["attachments"]

    assert set(limits["accepted"]) == ALLOWED_SUFFIXES
    assert set(limits["indexed"]) == DOCUMENT_SUFFIXES - IMAGE_SUFFIXES
    assert limits["maxBytes"] == MAX_ATTACHMENT_BYTES

    # And the endpoint really takes each one it advertises.
    assert ".pdf" in limits["accepted"]
    assert ".pdf" in limits["indexed"]


def test_every_advertised_attachment_type_is_actually_accepted(client, owner_headers):
    """A published list that rejects its own entries is the same bug again."""
    import io

    limits = client.get("/api/health", headers=owner_headers).json()["attachments"]

    # A minimal valid-ish body per type; the endpoint gates on the suffix.
    for suffix in limits["accepted"]:
        response = client.post(
            "/api/attachments",
            headers=owner_headers,
            files={
                "file": (
                    f"probe{suffix}",
                    io.BytesIO(b"probe content for an accepted type"),
                    "application/octet-stream",
                )
            },
        )
        assert response.status_code == 201, f"{suffix} was advertised but refused"


def test_a_pdf_attachment_is_retrieved_not_pasted_into_the_prompt(
    client, owner_headers, db_session
):
    """The bug this guards: a PDF reaching the model as raw bytes.

    Every non-image attachment used to be read with `read_text` and inlined.
    That was correct while only text files were accepted; when PDFs became
    attachable the model started receiving "%PDF-1.7" and compressed
    streams, and reported - accurately - that it could not read the file,
    while the very same document sat indexed and searchable beside it.
    """
    import io

    from app.database.models import User
    from app.services.vision import describe_for_prompt, resolve_attachments

    pdf = _minimal_pdf(b"Assessment is 50 marks ICA and 100 marks TEE.")
    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("policy.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()

    assert attached["documentId"], "a PDF attachment should produce a document"

    user = db_session.query(User).filter(User.id == "user-sanyam").one()
    resolved = resolve_attachments(
        db_session, user, [{"id": attached["id"], "name": "policy.pdf"}]
    )

    # Nothing inlined, and specifically no PDF header anywhere in the prompt.
    assert resolved.texts == []
    assert all(b"%PDF" not in text.encode() for _, text in resolved.texts)

    # It is reported as indexed rather than unreadable - the distinction the
    # model needs in order not to claim the attachment failed.
    assert "policy.pdf" in resolved.indexed
    assert resolved.unreadable == []
    assert resolved.anything_readable

    # Whether it is *in context* is settled after retrieval, not here.
    from app.services.vision import reconcile_with_retrieval

    reconcile_with_retrieval(
        db_session,
        resolved,
        {"policy.pdf": attached["documentId"]},
        {attached["documentId"]},
    )
    assert resolved.contributed == ["policy.pdf"]

    note = describe_for_prompt(resolved)
    assert note and "Passages from it appear" in note
    # Not listed among files it cannot read - that list is what makes a model
    # announce the attachment failed.
    assert "files you cannot read" not in note


def test_an_indexed_attachment_that_matched_nothing_is_not_claimed_as_context(
    client, owner_headers, db_session
):
    """The bug behind a summary of the wrong document.

    An attached PDF was indexed and bound correctly, but the question -
    "summarise the attached pdf" - shares no rare terms with it, so a longer
    unrelated document out-scored it on BM25. The prompt note nonetheless
    told the model the attachment was in context, so it summarised whatever
    was in context and attributed it to the attachment, by name, confidently.

    The note must distinguish "its passages are above" from "it was read but
    nothing in it matched".
    """
    import io

    from app.database.models import User
    from app.services.vision import (
        describe_for_prompt,
        reconcile_with_retrieval,
        resolve_attachments,
    )

    pdf = _minimal_pdf(b"Attendance register for the autumn term.")
    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("attendance.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()

    user = db_session.query(User).filter(User.id == "user-sanyam").one()
    resolved = resolve_attachments(
        db_session, user, [{"id": attached["id"], "name": "attendance.pdf"}]
    )

    # Retrieval returned passages, but none of them from the attachment.
    reconcile_with_retrieval(
        db_session,
        resolved,
        {"attendance.pdf": attached["documentId"]},
        {"bis-01", "bis-02"},
    )

    assert resolved.contributed == []
    assert resolved.indexed_not_matched == ["attendance.pdf"]

    note = describe_for_prompt(resolved)
    assert note
    assert "nothing in it matched" in note
    # The instruction that prevents the failure outright.
    assert "Do not describe any other document as though it were this one" in note
    assert "Passages from it appear" not in note


def test_a_text_attachment_is_still_inlined(client, owner_headers, db_session):
    """Small text files stay inline - retrieval is not an upgrade for them."""
    import io

    from app.database.models import User
    from app.services.vision import resolve_attachments

    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("note.txt", io.BytesIO(b"Bearing runs at 92 degrees."), "text/plain")},
    ).json()

    user = db_session.query(User).filter(User.id == "user-sanyam").one()
    resolved = resolve_attachments(
        db_session, user, [{"id": attached["id"], "name": "note.txt"}]
    )

    assert any("92 degrees" in text for _, text in resolved.texts)


def test_a_generic_question_still_puts_the_attachment_in_context(
    client, owner_headers, db_session
):
    """The failure this exists to prevent.

    "Summarise the attached PDF" shares no rare terms with the PDF, so BM25
    scores every one of its chunks at zero. The attachment was absent from
    its own turn, a longer unrelated document filled the context, and the
    model summarised that instead - under the attachment's name.

    Searching is the wrong model for the question. The user did not ask what
    the document says about something; they asked about the document. Its
    opening passages are therefore included because it was attached, which
    is a fact about the turn rather than a guess about the question.
    """
    import io

    from app.database.models import User
    from app.rag import RetrievalResult
    from app.services.chat_service import _lead_with_attachments

    pdf = _minimal_pdf(
        b"Attendance register autumn term. Roll 41 present 88 percent."
    )
    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("attendance.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()
    document_id = attached["documentId"]

    user = db_session.query(User).filter(User.id == "user-sanyam").one()

    # Not one content word in common with the file. This is what people type.
    question = "summarize the whole attached pdf and give a short explanation"

    # Whatever general retrieval found - here, nothing relevant.
    general = RetrievalResult(passages=[], mode="lexical")

    merged = _lead_with_attachments(
        db_session, user, question, general, [document_id]
    )

    assert merged.passages, "the attachment should be in its own turn's context"
    assert any(p.document_id == document_id for p in merged.passages)
    assert any("Attendance register" in p.text for p in merged.passages)


def test_attachment_passages_do_not_claim_a_relevance_score(
    client, owner_headers, db_session
):
    """They were included for being attached, not for matching.

    The score is a ranking aid within one result set. Inventing one for a
    passage that no search returned would misreport how it was found, which
    is the same class of dishonesty as a hardcoded status.
    """
    import io

    from app.database.models import User
    from app.rag import RetrievalResult
    from app.services.chat_service import _lead_with_attachments

    pdf = _minimal_pdf(b"Quarterly figures for the eastern depot.")
    attached = client.post(
        "/api/attachments",
        headers=owner_headers,
        files={"file": ("figures.pdf", io.BytesIO(pdf), "application/pdf")},
    ).json()

    user = db_session.query(User).filter(User.id == "user-sanyam").one()
    merged = _lead_with_attachments(
        db_session,
        user,
        "summarise this",
        RetrievalResult(passages=[], mode="lexical"),
        [attached["documentId"]],
    )

    included = [p for p in merged.passages if p.document_id == attached["documentId"]]
    assert included
    assert all(p.score == 0.0 for p in included)
    assert all(p.lexical_rank is None for p in included)


# ---------------------------------------------------------------------------
# Which model answers: three scopes, narrowest first
# ---------------------------------------------------------------------------
@pytest.fixture
def two_models(monkeypatch):
    """Give this deployment two models to choose between.

    The suite runs with none configured on purpose - a test that inherits a
    developer's .env is a test that passes for the wrong reason - so a test
    about *choosing* a model has to say which models exist.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "model_name", "model-alpha")
    monkeypatch.setattr(settings, "model_fast", "model-beta")
    return "model-alpha", "model-beta"


def test_a_saved_default_model_applies_to_new_chats(
    client, owner_headers, stub_gateway, two_models
):
    """Set once, remembered - the point of it being on the account."""
    stub_gateway(StubProvider())
    _, other = two_models

    saved = client.patch(
        "/api/settings", headers=owner_headers, json={"chatModel": other}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["chatModel"] == other

    reply = client.post("/api/chat", headers=owner_headers, json={"message": "hello"})
    assert reply.status_code == 200

    trace = " ".join(
        e["label"] for e in reply.json()["assistantMessage"]["activityTrace"]
    )
    assert "Your default model is" in trace
    assert other in trace

    client.patch("/api/settings", headers=owner_headers, json={"chatModel": ""})


def test_a_chat_pin_beats_the_saved_default(
    client, owner_headers, stub_gateway, two_models
):
    """The narrower instruction wins.

    Pinning one thread is not a request to change every other one, so the
    account default has to stay put underneath it.
    """
    stub_gateway(StubProvider())
    default_model, pinned_model = two_models

    client.patch(
        "/api/settings", headers=owner_headers, json={"chatModel": default_model}
    )

    started = client.post(
        "/api/chat", headers=owner_headers, json={"message": "first"}
    ).json()
    conversation_id = started["conversationId"]

    pinned = client.patch(
        f"/api/conversations/{conversation_id}",
        headers=owner_headers,
        json={"modelOverride": pinned_model},
    )
    assert pinned.status_code == 200, pinned.text

    reply = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "second", "conversationId": conversation_id},
    )
    trace = " ".join(
        e["label"] for e in reply.json()["assistantMessage"]["activityTrace"]
    )
    assert "pinned to" in trace
    assert pinned_model in trace
    assert "Your default model is" not in trace

    client.patch("/api/settings", headers=owner_headers, json={"chatModel": ""})


def test_an_unconfigured_default_model_is_refused(client, owner_headers, two_models):
    """Otherwise it fails at the provider a turn later, where nothing
    connects the failure back to this setting."""
    response = client.patch(
        "/api/settings", headers=owner_headers, json={"chatModel": "model-gamma"}
    )
    assert response.status_code == 422
    assert client.get("/api/settings", headers=owner_headers).json()["chatModel"] == ""
