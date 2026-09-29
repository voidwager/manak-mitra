"""Reading a document end to end, rather than searching inside it.

`retriever.py` answers "which passages best match this question?". That is
the right shape for a factual lookup and the wrong shape for "summarise this
SOP" or "what topics does this cover?" - questions *about a document as a
whole*. Ranking cannot answer them: a summary request has no distinctive
keywords to match on, so BM25 scores every chunk about equally and returns an
arbitrary five. The user sees an answer built from a random slice of the file
and reasonably concludes the system never read it.

So this module does the other thing. It resolves a document by name, then
returns its chunks **in document order**, paginated into parts that fit a
prompt. No scoring, no selection - the model gets the text.

The access rule is not reimplemented here. Resolution goes through
`scoped_document_query`, the same helper `retrieve()` uses, which is built on
`visible_documents_query`. A document the caller cannot open cannot be named
into existence: an unauthorised title resolves to "no such document", exactly
as it would for a title that does not exist at all. That matters - "you are
not allowed to read X" is itself a disclosure that X exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Document, DocumentChunk, User
from app.rag.retriever import Passage, scoped_document_query

#: Characters of document text per part. Sized so a part plus the system
#: prompt, the history and the answer fit comfortably in a small open-weight
#: model's window - the deployment target is a 7-27B model on plant hardware,
#: not a frontier model with a huge context.
MAX_PART_CHARS = 9000

#: Citations attached to one part. A 40-chunk read would otherwise bury the
#: reply under 40 source cards; one per page, capped, keeps it checkable
#: without making it unreadable.
MAX_CITATIONS = 8


@dataclass(frozen=True)
class DocumentPart:
    """A contiguous, in-order slice of one document's text."""

    document_id: str
    document_name: str
    folder: str
    text: str
    #: 1-based, and `total_parts` is how many there are in all.
    part: int
    total_parts: int
    first_page: int
    last_page: int
    chunks_in_part: int
    total_chunks: int

    @property
    def is_complete(self) -> bool:
        return self.total_parts == 1


@dataclass(frozen=True)
class DocumentReadResult:
    """What a read attempt produced.

    `candidates` is populated when the name was ambiguous or unmatched, so
    the caller can say which documents *are* readable instead of failing
    blankly. Only documents already inside the caller's scope ever appear
    there - it is a narrowing of what they can see, never a listing of what
    they cannot.
    """

    part: DocumentPart | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)
    citations: list[dict[str, object]] = field(default_factory=list)
    #: The part's chunks as retrieval passages, so a read can be fed into the
    #: prompt through exactly the same path as a search result - same context
    #: block, same numbering, same citation record.
    passages: list[Passage] = field(default_factory=list)
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.part is not None


#: Tokens that say nothing about *which* document is meant. File extensions
#: are the dangerous ones: without this, "Completely Invented File.pdf" shares
#: the token "pdf" with "Equipment Safety Guidelines.pdf" and a made-up name
#: resolves to a real document - which then gets read out in full.
_GENERIC_TOKENS = frozenset(
    {
        "pdf",
        "csv",
        "tsv",
        "txt",
        "doc",
        "docx",
        "log",
        "file",
        "files",
        "document",
        "documents",
        "the",
    }
)

#: A single shared token only identifies a document if it is specific enough.
#: "audit" can stand alone; "unit" cannot.
_MIN_SOLO_TOKEN = 5


def _normalise(value: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace for matching."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _tokens(value: str) -> set[str]:
    """Meaningful words in a name, with extensions and filler removed."""
    return {
        token
        for token in _normalise(value).split()
        if len(token) > 2 and token not in _GENERIC_TOKENS
    }


def _match_documents(documents: list[Document], wanted: str) -> list[Document]:
    """Documents whose name matches `wanted`, best tier first.

    Tiered rather than fuzzy-scored: the model usually passes a title it read
    from `document_search` output or from the user's own words, so exact and
    substring matching covers nearly everything. Falling through to token
    overlap catches "the pump SOP" for "Centrifugal Pump Inspection SOP.pdf".
    """
    target = _normalise(wanted)
    if not target:
        return []

    exact = [d for d in documents if _normalise(d.name) == target]
    if exact:
        return exact

    # Everything below here is fuzzy, so it needs a query specific enough to
    # be meant. "unit" is a substring of half the corpus and identifies
    # nothing; without this guard it silently resolves to whichever document
    # happens to contain the word.
    wanted_tokens = _tokens(wanted)
    if not wanted_tokens:
        return []
    if len(wanted_tokens) == 1 and len(next(iter(wanted_tokens))) < _MIN_SOLO_TOKEN:
        return []

    # Either direction: "pump inspection" inside the title, or a title the
    # user quoted in full inside a longer phrase.
    substring = [
        d
        for d in documents
        if target in _normalise(d.name) or _normalise(d.name) in target
    ]
    if substring:
        return substring

    scored: list[tuple[int, Document]] = []
    for document in documents:
        shared = wanted_tokens & _tokens(document.name)
        if not shared:
            continue
        # One shared word is only enough when that word is distinctive.
        # Otherwise a name sharing nothing but "unit" - or, before the
        # generic list above, nothing but "pdf" - would resolve to a real
        # document and be read out in full.
        if len(shared) == 1 and len(next(iter(shared))) < _MIN_SOLO_TOKEN:
            continue
        scored.append((len(shared), document))

    if not scored:
        return []

    best = max(score for score, _ in scored)
    return [document for score, document in scored if score == best]


def _paginate(chunks: list[DocumentChunk], max_chars: int) -> list[list[DocumentChunk]]:
    """Pack chunks into parts without splitting a chunk across a boundary.

    Greedy and deterministic, so "part 2 of 4" means the same thing on every
    call. A single chunk longer than `max_chars` still gets its own part
    rather than being dropped.
    """
    parts: list[list[DocumentChunk]] = []
    current: list[DocumentChunk] = []
    size = 0

    for chunk in chunks:
        length = len(chunk.text)
        if current and size + length > max_chars:
            parts.append(current)
            current = []
            size = 0
        current.append(chunk)
        size += length

    if current:
        parts.append(current)
    return parts or [[]]


def _passages(document: Document, chunks: list[DocumentChunk]) -> list[Passage]:
    """The part's chunks as passages, in document order.

    `score` descends very slightly rather than sitting flat at 1.0 so that
    anything sorting by score preserves reading order instead of reordering
    the document arbitrarily. Nothing was ranked here - the passage is
    present because it is part of the document, not because it won a search.
    """
    return [
        Passage(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.name,
            text=chunk.text,
            page=chunk.page,
            section=chunk.section,
            score=max(0.0, 1.0 - index * 1e-6),
        )
        for index, chunk in enumerate(chunks)
    ]


def _citations(document: Document, chunks: list[DocumentChunk]) -> list[dict[str, object]]:
    """One citation per distinct page, capped.

    Same shape as `Passage.as_citation()` so a read-sourced answer is
    checkable in the UI exactly like a retrieved one. `score` is 1.0 because
    nothing was ranked - the passage is present because it is part of the
    document, not because it won a search.
    """
    seen: set[int] = set()
    out: list[dict[str, object]] = []

    for chunk in chunks:
        if chunk.page in seen:
            continue
        seen.add(chunk.page)
        out.append(
            {
                "documentId": document.id,
                "title": document.name,
                "page": f"Page {chunk.page}"
                + (f" · {chunk.section}" if chunk.section else ""),
                "pageNumber": chunk.page,
                "section": chunk.section,
                "excerpt": chunk.text,
                "score": 1.0,
            }
        )
        if len(out) >= MAX_CITATIONS:
            break

    return out


def read_document(
    db: Session,
    user: User,
    *,
    name: str,
    part: int = 1,
    folder_scope: list[str] | None = None,
    conversation_id: str | None = None,
    max_chars: int = MAX_PART_CHARS,
) -> DocumentReadResult:
    """Return one part of `name`'s text, in document order.

    `folder_scope` narrows to an agent's folders and, like every other clause
    here, can only remove rows - an agent restricted to a folder the user
    cannot see reads nothing rather than reading the folder.
    """
    documents = list(db.scalars(scoped_document_query(user, folder_scope, conversation_id)))

    if not documents:
        return DocumentReadResult(
            reason=(
                "This agent is restricted to "
                f"{', '.join(folder_scope)}, and you have no documents there."
                if folder_scope
                else "No documents are in your knowledge-base scope."
            )
        )

    visible = [{"id": d.id, "name": d.name, "folder": d.folder} for d in documents]
    matches = _match_documents(documents, name)

    if not matches:
        return DocumentReadResult(
            candidates=visible,
            reason=f"No document in scope is named '{name}'.",
        )

    if len(matches) > 1:
        return DocumentReadResult(
            candidates=[{"id": d.id, "name": d.name, "folder": d.folder} for d in matches],
            reason=f"'{name}' matches {len(matches)} documents; name one exactly.",
        )

    document = matches[0]
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.position)
        )
    )

    if not chunks:
        return DocumentReadResult(
            reason=(
                f"'{document.name}' is in scope but has not been indexed, so "
                "there is no text to read."
            )
        )

    pages = _paginate(chunks, max_chars)
    index = max(1, min(int(part or 1), len(pages)))
    selected = pages[index - 1]

    return DocumentReadResult(
        part=DocumentPart(
            document_id=document.id,
            document_name=document.name,
            folder=document.folder,
            text="\n\n".join(c.text for c in selected),
            part=index,
            total_parts=len(pages),
            first_page=min(c.page for c in selected),
            last_page=max(c.page for c in selected),
            chunks_in_part=len(selected),
            total_chunks=len(chunks),
        ),
        citations=_citations(document, selected),
        passages=_passages(document, selected),
    )


__all__ = [
    "MAX_PART_CHARS",
    "DocumentPart",
    "DocumentReadResult",
    "read_document",
]
