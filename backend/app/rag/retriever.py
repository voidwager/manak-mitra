"""Retrieval: question -> the passages that answer it, with provenance.

Three properties matter more than ranking quality here.

**Scoping is not optional.** The candidate set comes from
`visible_documents_query`, the same SQL filter the documents API uses. A
user cannot retrieve from a document they cannot open, and there is no code
path that skips the filter - the store takes a scope and has no way to
widen it. Retrieval is the easiest place in a RAG system to leak a
confidential document, because the leak arrives paraphrased inside an answer
where nobody thinks to check permissions.

**Absence is a real answer.** When nothing scores above the floor, this
returns an empty result and says why (`reason`). The caller then prompts the
model with the no-retrieval guardrail. Padding a prompt with the least-bad
passages is how a system ends up citing an irrelevant SOP with confidence.

**The mode is reported, never assumed.** A result knows whether it came from
lexical search, semantic search or both. Nothing downstream may claim
semantic retrieval happened when no embedder answered.

Fusion uses Reciprocal Rank Fusion rather than a weighted score blend. BM25
scores and cosine similarities are on incomparable scales, so any weighted
sum needs corpus-specific normalisation constants that would silently rot;
RRF only reads the rank, so it needs no tuning and cannot be thrown off by
one strategy's scores drifting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Document, User
from app.rag.embeddings import EmbeddingError, get_embedding_gateway
from app.rag.lexical import Bm25Index
from app.rag.store import Candidate, VectorStore, cosine_similarity, default_store
from app.services.access import visible_documents_query

log = get_logger(__name__)

#: RRF damping constant. 60 is the value from the original paper and the de
#: facto default; it flattens the difference between ranks 1 and 2 enough
#: that one strategy cannot dominate on its own.
RRF_K = 60


@dataclass(frozen=True)
class Passage:
    """One retrieved chunk, with everything a citation needs."""

    chunk_id: str
    document_id: str
    document_name: str
    text: str
    page: int
    section: str

    #: Fused score, normalised to 0-1 across this result set. Comparable
    #: within one search only - it is a ranking aid, not a probability.
    score: float

    #: 1-based ranks from each strategy, or None when that strategy did not
    #: return this passage. Shown in the activity trace so the retrieval is
    #: inspectable rather than a black box.
    lexical_rank: int | None = None
    semantic_rank: int | None = None

    def as_citation(self) -> dict[str, object]:
        """The citation shape the UI and the message record share."""
        return {
            "documentId": self.document_id,
            "title": self.document_name,
            # The UI prints this string verbatim next to the title.
            "page": f"Page {self.page}" + (f" · {self.section}" if self.section else ""),
            "pageNumber": self.page,
            "section": self.section,
            "excerpt": self.text,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class RetrievalResult:
    """What one search found, and what it was able to search."""

    passages: list[Passage] = field(default_factory=list)

    #: "lexical" | "semantic" | "hybrid" | "none"
    mode: str = "none"

    #: Documents the user may see, and how many of those are indexed.
    documents_in_scope: int = 0
    indexed_documents_in_scope: int = 0
    chunks_searched: int = 0

    #: Folders the search was restricted to, when an agent narrowed it.
    #: Empty means the search covered everything the user is cleared for.
    scope_folders: list[str] = field(default_factory=list)

    #: Present when nothing was returned. Plain English, shown to the user.
    reason: str = ""

    #: Set when semantic search was configured but did not run.
    semantic_error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.passages)

    @property
    def document_count(self) -> int:
        return len({p.document_id for p in self.passages})


# ---------------------------------------------------------------------------
# Scoring strategies
# ---------------------------------------------------------------------------
def _lexical_ranking(candidates: list[Candidate], query: str) -> list[str]:
    index = Bm25Index()
    for candidate in candidates:
        # The title and heading are what a passage is *about*, and a chunk
        # cut from the middle of "Compulsory Registration Scheme (CRS)" may
        # never repeat those words. Scored with them, "how do I register
        # under CRS" reaches the CRS document rather than any page that
        # happens to say "register". Only the ranking sees this; the passage
        # the model reads and cites is the chunk text alone.
        index.add(
            candidate.chunk_id,
            f"{candidate.document_name}\n{candidate.section}\n{candidate.text}",
        )
    return [chunk_id for chunk_id, _ in index.search(query)]


def _semantic_ranking(
    candidates: list[Candidate], query: str, model: str
) -> tuple[list[str], str]:
    """Rank by cosine similarity. Returns (ranking, error_message)."""
    usable = [
        c
        for c in candidates
        if c.vector is not None and c.vector_model == model
    ]
    if not usable:
        return [], (
            "No chunk in scope carries a vector from the configured embedding "
            f"model ('{model}'). Re-index those documents to enable semantic search."
        )

    gateway = get_embedding_gateway()
    try:
        query_vector = gateway.embed_query(query)
    except EmbeddingError as exc:
        log.warning("Semantic retrieval unavailable: %s", exc)
        return [], str(exc)

    scored = [
        (c.chunk_id, cosine_similarity(query_vector, c.vector or []))
        for c in usable
    ]
    scored = [pair for pair in scored if pair[1] > 0.0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [chunk_id for chunk_id, _ in scored], ""


def _fuse(lexical: list[str], semantic: list[str]) -> dict[str, float]:
    """Reciprocal Rank Fusion over one or both rankings."""
    fused: dict[str, float] = {}
    for ranking in (lexical, semantic):
        for position, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)
    return fused


def _normalise(scores: dict[str, float]) -> dict[str, float]:
    """Rescale to 0-1 so the min-score floor means the same thing in every mode."""
    if not scores:
        return {}
    highest = max(scores.values())
    if highest <= 0.0:
        return {key: 0.0 for key in scores}
    return {key: value / highest for key, value in scores.items()}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def scoped_document_query(
    user: User,
    folder_scope: list[str] | None,
    conversation_id: str | None = None,
    document_ids: list[str] | None = None,
):
    """The caller's own permissions, optionally narrowed to some folders.

    The narrowing is a `.where()` bolted onto `visible_documents_query`, so
    it can only ever remove rows. An agent's folder scope is therefore
    incapable of granting access - if a user cannot see a folder, restricting
    an agent to it yields nothing rather than yielding the folder.
    """
    scope = visible_documents_query(user, conversation_id=conversation_id)
    if folder_scope:
        scope = scope.where(Document.folder.in_(folder_scope))
    if document_ids:
        # Narrowing, like every other clause here. Naming a document the
        # caller cannot see yields nothing rather than yielding the document.
        scope = scope.where(Document.id.in_(document_ids))
    return scope


def retrieve(
    db: Session,
    user: User,
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    store: VectorStore | None = None,
    folder_scope: list[str] | None = None,
    conversation_id: str | None = None,
    document_ids: list[str] | None = None,
) -> RetrievalResult:
    """Find the passages in `user`'s scope that best answer `query`.

    `folder_scope` narrows the search to particular folders - an agent's
    configuration, typically. It intersects with the user's permissions and
    can never widen them.

    `conversation_id` admits the documents attached to that one chat. Without
    it, chat-scoped documents are invisible to retrieval entirely - which is
    the default, so a file attached to one conversation cannot leak into
    another one or into the shared corpus.

    `document_ids` restricts the search to particular documents. Like every
    other narrowing here it intersects with the caller's permissions and can
    never widen them.
    """
    store = store or default_store
    top_k = settings.rag_top_k if top_k is None else top_k
    min_score = settings.rag_min_score if min_score is None else min_score

    if not settings.rag_enabled:
        return RetrievalResult(reason="Retrieval is disabled on this server.")

    query = (query or "").strip()
    if not query:
        return RetrievalResult(reason="No question to search for.")

    documents = list(
        db.scalars(scoped_document_query(user, folder_scope, conversation_id, document_ids))
    )
    indexed = [d for d in documents if d.chunk_count > 0]

    if not documents:
        return RetrievalResult(
            scope_folders=list(folder_scope or []),
            reason=(
                "This agent is restricted to "
                f"{', '.join(folder_scope)}, and you have no documents there."
                if folder_scope
                else "No documents are in your knowledge-base scope."
            ),
        )

    candidates = store.load_candidates(db, scoped_document_query(user, folder_scope))
    if not candidates:
        return RetrievalResult(
            documents_in_scope=len(documents),
            indexed_documents_in_scope=0,
            scope_folders=list(folder_scope or []),
            reason=(
                f"None of the {len(documents)} document(s) in "
                + (
                    f"this agent's scope ({', '.join(folder_scope)}) "
                    if folder_scope
                    else "your scope "
                )
                + "have been indexed yet, so there is nothing to search."
            ),
        )

    by_id = {c.chunk_id: c for c in candidates}

    lexical = _lexical_ranking(candidates, query)

    gateway = get_embedding_gateway()
    semantic: list[str] = []
    semantic_error = ""
    if gateway.is_configured:
        semantic, semantic_error = _semantic_ranking(candidates, query, gateway.model)

    if lexical and semantic:
        mode = "hybrid"
    elif semantic:
        mode = "semantic"
    elif lexical:
        mode = "lexical"
    else:
        mode = "none"

    fused = _normalise(_fuse(lexical, semantic))
    lexical_positions = {chunk_id: i + 1 for i, chunk_id in enumerate(lexical)}
    semantic_positions = {chunk_id: i + 1 for i, chunk_id in enumerate(semantic)}

    ordered = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)

    passages: list[Passage] = []
    for chunk_id, score in ordered:
        if len(passages) >= top_k:
            break
        if score < min_score:
            break  # scores are descending, so the rest are worse
        candidate = by_id.get(chunk_id)
        if candidate is None:  # pragma: no cover - ids come from by_id
            continue
        passages.append(
            Passage(
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                document_name=candidate.document_name,
                text=candidate.text,
                page=candidate.page,
                section=candidate.section,
                score=score,
                lexical_rank=lexical_positions.get(chunk_id),
                semantic_rank=semantic_positions.get(chunk_id),
            )
        )

    reason = ""
    if not passages:
        reason = (
            f"Nothing in the {len(indexed)} indexed document(s) in your scope "
            "matched this question."
        )
        mode = "none"

    return RetrievalResult(
        passages=passages,
        mode=mode,
        documents_in_scope=len(documents),
        indexed_documents_in_scope=len(indexed),
        chunks_searched=len(candidates),
        scope_folders=list(folder_scope or []),
        reason=reason,
        semantic_error=semantic_error,
    )


def build_context_block(
    passages: list[Passage], *, max_chars: int | None = None
) -> str:
    """Render retrieved passages as the CONTEXT section of a prompt.

    Numbered so the model can cite `[1]` and the citation can be resolved
    back to a real document. Truncated at a character budget rather than
    dropped silently at the model's context limit.
    """
    budget = settings.rag_max_context_chars if max_chars is None else max_chars

    blocks: list[str] = []
    used = 0
    for number, passage in enumerate(passages, start=1):
        location = f"page {passage.page}"
        if passage.section:
            location += f", {passage.section}"
        header = f"[{number}] {passage.document_name} ({location})"

        body = passage.text
        remaining = budget - used - len(header) - 2
        if remaining <= 200:  # not enough room for a usable passage
            break
        if len(body) > remaining:
            body = body[:remaining].rsplit(" ", 1)[0] + " ..."

        block = f"{header}\n{body}"
        blocks.append(block)
        used += len(block) + 2

    return "\n\n".join(blocks)


__all__ = [
    "Passage",
    "RetrievalResult",
    "build_context_block",
    "retrieve",
]
