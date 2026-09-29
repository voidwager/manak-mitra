"""Retrieval tests.

Three groups, in order of how much damage a regression would do:

  1. Scoping. Retrieval must never surface a passage from a document the
     caller cannot open. A leak here arrives paraphrased inside an answer,
     where nobody thinks to check permissions.
  2. Grounding. A citation must correspond to a passage that was actually
     retrieved and placed in the prompt, and no citation may appear when
     nothing was.
  3. The pipeline itself - extraction, chunking, BM25, fusion, indexing
     lifecycle.
"""

import io

import pytest

from app.rag.chunking import chunk_document, detect_heading
from app.rag.embeddings import gateway as embedding_gateway_module
from app.rag.embeddings.base import EmbeddingProvider, EmbeddingUnavailableError
from app.rag.embeddings.gateway import EmbeddingGateway
from app.rag.extraction import Extracted, Page, UnsupportedDocument, extract
from app.rag.lexical import Bm25Index, tokenize
from app.rag.retriever import build_context_block
from app.rag.store import cosine_similarity
from tests.conftest import StubProvider

SOP_TEXT = (
    b"Centrifugal Pump Inspection SOP\n"
    b"\n"
    b"Section 4.2 Vibration limits\n"
    b"\n"
    b"Pump P-7781 must be isolated with electrical lock-out tag-out before any\n"
    b"inspection begins. Acceptable vibration tolerance is 2.5 mm/s RMS measured\n"
    b"at the bearing housing. Operating temperature limit is 75 degrees Celsius.\n"
    b"\n"
    b"Section 4.3 Seal flush\n"
    b"\n"
    b"Verify the mechanical seal flush line is clear and that plan 11 flush flow\n"
    b"is established before restart. Record the reading in the maintenance log.\n"
)

COMPRESSOR_TEXT = (
    b"Reciprocating Compressor Manual\n"
    b"\n"
    b"Section 2.1 Suction filters\n"
    b"\n"
    b"Compressor K-3312 requires suction filter differential pressure\n"
    b"verification at every shutdown. Replace the element above 0.35 bar.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _upload(client, headers, name: str, data: bytes) -> dict:
    """Upload and return the indexed document row.

    TestClient runs background tasks before handing back the response, so
    the follow-up fetch already sees the finished index.
    """
    created = client.post(
        "/api/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(data), "text/plain")},
    ).json()
    return client.get(f"/api/documents/{created['id']}", headers=headers).json()


class StubEmbedder(EmbeddingProvider):
    """Deterministic bag-of-words vectors - no network, no model.

    Good enough to prove the semantic half is wired correctly end to end:
    that vectors are stored, that a query is embedded, that cosine ranking
    happens and that fusion combines the two rankings. It is not a claim
    about embedding quality.
    """

    name = "stub"
    configured = True
    on_premise = True

    VOCAB = ["vibration", "seal", "compressor", "filter", "pump", "temperature"]

    def __init__(self, *, error: Exception | None = None):
        super().__init__(model="stub-embed")
        self.error = error
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.error:
            raise self.error
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = [float(lowered.count(word)) for word in self.VOCAB]
            if not any(vector):
                vector[0] = 0.001  # never an all-zero vector
            vectors.append(vector)
        return vectors


@pytest.fixture
def stub_embedder(monkeypatch):
    """Install a stub embedder behind the embedding gateway for one test."""

    def install(provider=None):
        provider = provider or StubEmbedder()
        gateway = EmbeddingGateway(provider)
        monkeypatch.setattr(
            embedding_gateway_module, "get_embedding_gateway", lambda: gateway
        )
        for module in (
            "app.rag.indexer",
            "app.rag.retriever",
            "app.api.routes.health",
        ):
            monkeypatch.setattr(
                f"{module}.get_embedding_gateway", lambda: gateway
            )
        return provider

    return install


# ---------------------------------------------------------------------------
# 1. Scoping - the guarantee that matters most
# ---------------------------------------------------------------------------
def test_retrieval_never_crosses_a_document_scope_boundary(
    client, engineer_headers, safety_headers
):
    """A passage must not reach a user who cannot open its document."""
    private = _upload(
        client, engineer_headers, "engineer-only.txt", b"Turbine T-4409 trip setpoint is 3600 rpm."
    )
    assert private["status"] == "Indexed"

    # The safety user cannot see the document...
    assert (
        client.get(f"/api/documents/{private['id']}", headers=safety_headers).status_code
        == 404
    )

    # ...and cannot reach its content through retrieval either.
    hits = client.post(
        "/api/search",
        headers=safety_headers,
        json={"query": "Turbine T-4409 trip setpoint"},
    ).json()
    assert all(h["documentId"] != private["id"] for h in hits["results"])
    assert all("T-4409" not in h["text"] for h in hits["results"])

    # The owner of the document does get it back, so the query itself is
    # not the reason the other user found nothing.
    own = client.post(
        "/api/search",
        headers=engineer_headers,
        json={"query": "Turbine T-4409 trip setpoint"},
    ).json()
    assert any(h["documentId"] == private["id"] for h in own["results"])


def test_confidential_document_content_is_not_retrievable_by_non_owner(
    client, owner_headers, engineer_headers, db_session
):
    """Owner-confidential material stays out of everyone else's retrieval.

    Uploads land in the uploader's personal folder, so this promotes one to
    the confidential flag directly - the same state a seeded confidential
    document is in.
    """
    from app.database.models import Document

    doc = _upload(
        client, owner_headers, "board-audit.txt", b"Hydrocracker HCU-9 efficiency is 98.4 percent."
    )

    row = db_session.get(Document, doc["id"])
    row.is_confidential_owner_only = True
    db_session.commit()

    hits = client.post(
        "/api/search",
        headers=engineer_headers,
        json={"query": "Hydrocracker HCU-9 efficiency"},
    ).json()
    assert all(h["documentId"] != doc["id"] for h in hits["results"])

    owner_hits = client.post(
        "/api/search", headers=owner_headers, json={"query": "Hydrocracker HCU-9 efficiency"}
    ).json()
    assert any(h["documentId"] == doc["id"] for h in owner_hits["results"])


def test_deleting_a_document_removes_it_from_retrieval(client, engineer_headers):
    doc = _upload(
        client, engineer_headers, "transient.txt", b"Valve V-6620 must be gagged during the test."
    )
    assert doc["chunks"] >= 1

    before = client.post(
        "/api/search", headers=engineer_headers, json={"query": "Valve V-6620 gagged"}
    ).json()
    assert any(h["documentId"] == doc["id"] for h in before["results"])

    client.delete(f"/api/documents/{doc['id']}", headers=engineer_headers)

    after = client.post(
        "/api/search", headers=engineer_headers, json={"query": "Valve V-6620 gagged"}
    ).json()
    assert all(h["documentId"] != doc["id"] for h in after["results"])


# ---------------------------------------------------------------------------
# 2. Grounding
# ---------------------------------------------------------------------------
def test_grounded_reply_cites_only_retrieved_documents(
    client, owner_headers, stub_gateway
):
    doc = _upload(client, owner_headers, "pump-sop.txt", SOP_TEXT)
    stub = stub_gateway(StubProvider("Isolate the pump first [1]."))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "What is the vibration tolerance for pump P-7781?"},
    ).json()

    assert body["retrievalMode"] in ("lexical", "hybrid")

    source = body["assistantMessage"]["source"]
    assert source is not None
    assert source["documentId"] == doc["id"]
    assert source["title"] == "pump-sop.txt"
    # The citation quotes retrieved text, so it is checkable.
    assert "2.5 mm/s" in source["excerpt"]

    # Every cited document is one this user can actually open, and the
    # document we uploaded is among them. (Other tests upload documents with
    # the same content, and the owner sees all of them - more than one
    # citation here is correct, an unauthorised one would not be.)
    cited = {s["documentId"] for s in body["assistantMessage"]["sources"]}
    assert doc["id"] in cited
    for document_id in cited:
        assert (
            client.get(f"/api/documents/{document_id}", headers=owner_headers).status_code
            == 200
        )

    # The prompt carried the passages and the narrowed guardrail.
    system = stub.last_prompt[0].content
    assert "CONTEXT" in system
    assert "2.5 mm/s" in system
    assert "NEVER cite a document" in system


def test_grounded_guardrail_replaces_the_no_retrieval_one(
    client, owner_headers, stub_gateway
):
    """The prohibition narrows; it never disappears."""
    _upload(client, owner_headers, "compressor.txt", COMPRESSOR_TEXT)
    stub = stub_gateway(StubProvider())

    client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "suction filter differential pressure on compressor K-3312"},
    )
    grounded = stub.last_prompt[0].content
    assert "NO access to any document" not in grounded
    assert "NEVER cite a document, clause, section, page or circular" in grounded

    client.post(
        "/api/chat", headers=owner_headers, json={"message": "qqzzxx unmatchable token"}
    )
    ungrounded = stub.last_prompt[0].content
    assert "NO access to any document" in ungrounded
    assert "CONTEXT" not in ungrounded


def test_activity_trace_reports_the_real_retrieval(client, owner_headers, stub_gateway):
    _upload(client, owner_headers, "seal-flush.txt", SOP_TEXT)
    stub_gateway(StubProvider())

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "mechanical seal flush plan 11"},
    ).json()

    labels = [s["label"] for s in body["assistantMessage"]["activityTrace"]]
    assert any("Knowledge base retrieval: searched" in label for label in labels)
    assert any("grounded in them and cited" in label for label in labels)
    # No embedder is configured, so the trace must say keyword search.
    assert any("keyword search" in label for label in labels)


def test_streamed_citations_arrive_with_the_finished_answer(
    client, owner_headers, stub_gateway
):
    """Sources are emitted at `done`, not before the first token.

    They used to be sent up front, on the reasoning that retrieval finishes
    before generation starts. That was true but wrong: retrieval runs on
    every turn, so what it *found* and what the answer actually *cites* are
    different sets - a greeting matches something. Announcing retrieved
    passages as sources before the reply exists overstated the evidence in
    exactly the way the citation model is built to prevent.
    """
    _upload(client, owner_headers, "stream-sop.txt", SOP_TEXT)
    stub_gateway(StubProvider("Isolate the pump [1]."))

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=owner_headers,
        json={"message": "vibration tolerance bearing housing"},
    ) as response:
        events = [line for line in response.iter_lines()]

    order = [line.removeprefix("event: ") for line in events if line.startswith("event: ")]
    assert "sources" not in order, "sources must not precede the answer"
    assert order[-1] == "done"

    # The citation still arrives, carried by the persisted message. Which
    # document it names depends on what else the suite has uploaded, so the
    # assertion is that a source arrived at all rather than which one.
    body = "\n".join(events)
    assert '"sources"' in body
    assert '"documentId"' in body


def test_a_reply_that_cites_nothing_carries_no_sources(
    client, owner_headers, stub_gateway
):
    """The bug this rule exists for.

    Retrieval matches something for almost any input, so a greeting used to
    come back with three source cards under it. Sources mean "what this
    answer drew on", not "what the search returned".
    """
    _upload(client, owner_headers, "unused-sop.txt", SOP_TEXT)
    stub_gateway(StubProvider("Hey! Doing well, thanks."))

    body = client.post(
        "/api/chat",
        headers=owner_headers,
        json={"message": "hey how is it going"},
    ).json()

    assert not body["assistantMessage"]["sources"]
    assert body["assistantMessage"]["source"] is None


# ---------------------------------------------------------------------------
# 3. Pipeline
# ---------------------------------------------------------------------------
def test_csv_rows_keep_their_column_names(client, engineer_headers):
    """A row split from its header is unreadable, so rows are self-describing."""
    csv_bytes = (
        b"Date,TagID,Equipment,Action,Technician\n"
        b"2026-08-27,P-5150,Centrifugal Pump,Seal Flush Cleaning,S. Jain\n"
        b"2026-08-14,C-2210,Compressor,Valve Replacement,A. Roy\n"
    )
    created = client.post(
        "/api/documents",
        headers=engineer_headers,
        files={"file": ("history.csv", io.BytesIO(csv_bytes), "text/csv")},
    ).json()

    chunks = client.get(
        f"/api/documents/{created['id']}/chunks", headers=engineer_headers
    ).json()
    assert chunks
    text = "\n".join(c["text"] for c in chunks)
    assert "TagID: P-5150" in text
    assert "Technician: S. Jain" in text

    hits = client.post(
        "/api/search", headers=engineer_headers, json={"query": "P-5150 seal flush"}
    ).json()
    assert any(h["documentId"] == created["id"] for h in hits["results"])


def test_reindexing_replaces_chunks_rather_than_appending(client, engineer_headers):
    doc = _upload(client, engineer_headers, "reindex.txt", SOP_TEXT)
    first = doc["chunks"]
    assert first >= 1

    client.post(f"/api/documents/{doc['id']}/index", headers=engineer_headers)

    again = client.get(f"/api/documents/{doc['id']}", headers=engineer_headers).json()
    assert again["chunks"] == first


def test_chunks_endpoint_is_scope_checked(client, engineer_headers, safety_headers):
    doc = _upload(client, engineer_headers, "scoped-chunks.txt", SOP_TEXT)
    assert (
        client.get(
            f"/api/documents/{doc['id']}/chunks", headers=safety_headers
        ).status_code
        == 404
    )


def test_search_explains_an_empty_result(client, safety_headers):
    body = client.post(
        "/api/search",
        headers=safety_headers,
        json={"query": "wholly unmatchable qqzzxx token"},
    ).json()
    assert body["results"] == []
    assert body["reason"]
    assert body["mode"] == "none"


def test_chunks_carry_their_section_and_page(client, engineer_headers):
    doc = _upload(client, engineer_headers, "sectioned.txt", SOP_TEXT)
    chunks = client.get(
        f"/api/documents/{doc['id']}/chunks", headers=engineer_headers
    ).json()

    sections = {c["section"] for c in chunks}
    assert any("4.2" in s or "4.3" in s for s in sections)
    assert all(c["page"] >= 1 for c in chunks)


# --- semantic half ---------------------------------------------------------
def test_semantic_indexing_stores_vectors_and_reports_it(
    client, engineer_headers, stub_embedder
):
    stub_embedder()

    doc = _upload(client, engineer_headers, "semantic.txt", SOP_TEXT)
    assert doc["status"] == "Indexed"
    assert doc["isSemanticallyIndexed"] is True

    chunks = client.get(
        f"/api/documents/{doc['id']}/chunks", headers=engineer_headers
    ).json()
    assert all(c["embeddingModel"] == "stub-embed" for c in chunks)

    hits = client.post(
        "/api/search", headers=engineer_headers, json={"query": "vibration"}
    ).json()
    assert hits["mode"] == "hybrid"
    assert any(h["semanticRank"] is not None for h in hits["results"])


def test_embedding_failure_still_produces_a_searchable_document(
    client, engineer_headers, stub_embedder
):
    """A dead embedder must not cost the document its lexical index."""
    stub_embedder(StubEmbedder(error=EmbeddingUnavailableError("endpoint down")))

    doc = _upload(client, engineer_headers, "degraded.txt", SOP_TEXT)

    assert doc["status"] == "Indexed"
    assert doc["chunks"] >= 1
    assert doc["isSemanticallyIndexed"] is False
    # The degradation is reported, not hidden.
    assert "keyword search only" in doc["indexError"]

    hits = client.post(
        "/api/search", headers=engineer_headers, json={"query": "lock-out tag-out P-7781"}
    ).json()
    assert hits["mode"] == "lexical"
    assert any(h["documentId"] == doc["id"] for h in hits["results"])


def test_health_reports_hybrid_only_when_an_embedder_exists(client, stub_embedder):
    stub_embedder()
    body = client.get("/api/health").json()
    assert body["retrieval"]["mode"] == "hybrid"
    assert body["implemented"]["semanticRetrieval"] is True
    assert body["retrieval"]["embeddingOnPremise"] is True


# --- units -----------------------------------------------------------------
def test_tokenizer_keeps_industrial_identifiers_whole():
    tokens = tokenize("Pump P-204 at CDU-II runs below 2.5 mm/s per API 610.")
    assert "p-204" in tokens
    assert "cdu-ii" in tokens
    assert "2.5" in tokens
    # Stopwords go; "p" alone must not appear, or every pump would match.
    assert "the" not in tokens
    assert "p" not in tokens


def test_bm25_ranks_the_passage_containing_the_query_terms_first():
    index = Bm25Index()
    index.add("a", "Routine housekeeping and general site cleanliness guidance.")
    index.add("b", "Pump P-204 vibration tolerance is 2.5 mm/s RMS at the bearing.")
    index.add("c", "Compressor C-101 suction filter differential pressure checks.")

    ranked = index.search("P-204 vibration tolerance")
    assert ranked[0][0] == "b"
    # Non-matching passages are absent rather than returned with score zero.
    assert "a" not in [key for key, _ in ranked]


def test_bm25_matches_a_differently_punctuated_identifier():
    index = Bm25Index()
    index.add("a", "Pump P 204 was overhauled in March.")
    ranked = index.search("P-204 overhaul")
    assert ranked and ranked[0][0] == "a"


def test_heading_detection_accepts_real_headings_and_rejects_prose():
    assert detect_heading("Section 4.2 Vibration limits")
    assert detect_heading("## 4.2 Vibration limits")
    assert detect_heading("4.2 Vibration limits")
    assert detect_heading("APPENDIX B TORQUE VALUES")
    assert detect_heading(
        "The pump must be isolated before inspection begins in earnest."
    ) is None


def test_chunking_splits_on_boundaries_and_keeps_provenance():
    body = "\n\n".join(f"Paragraph {i} about pump maintenance work." for i in range(40))
    extracted = Extracted(pages=[Page(number=1, text="Section 1.0 Overview\n\n" + body)])

    chunks = chunk_document(extracted, chunk_chars=300, overlap_chars=60)

    assert len(chunks) > 1
    assert all(len(c.text) <= 400 for c in chunks), "no chunk grossly overruns the budget"
    assert all(c.section == "Section 1.0 Overview" for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))
    # Splits land on whitespace, never mid-word.
    assert all(not c.text.startswith(" ") for c in chunks)


def test_chunking_does_not_merge_two_pages_into_one_passage():
    extracted = Extracted(
        pages=[Page(number=1, text="Short page one."), Page(number=2, text="Short page two.")]
    )
    chunks = chunk_document(extracted, chunk_chars=2000, overlap_chars=100)
    assert {c.page for c in chunks} == {1, 2}


def test_images_are_rejected_with_an_actionable_reason():
    with pytest.raises(UnsupportedDocument) as excinfo:
        extract(b"\x89PNG", ".png")
    assert "OCR" in str(excinfo.value)


def test_cosine_similarity_refuses_mismatched_vectors():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    # Different models produce different dimensions; comparing them is
    # meaningless, so it scores zero rather than raising.
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_context_block_is_numbered_and_budget_bounded():
    from app.rag.retriever import Passage

    passages = [
        Passage(
            chunk_id=f"c{i}",
            document_id=f"d{i}",
            document_name=f"Doc {i}.pdf",
            text="x" * 2000,
            page=i + 1,
            section=f"Section {i}",
            score=1.0,
        )
        for i in range(5)
    ]
    block = build_context_block(passages, max_chars=2500)

    assert block.startswith("[1] Doc 0.pdf (page 1, Section 0)")
    assert len(block) <= 2600
    # The budget stops it before every passage is included.
    assert "[5]" not in block
