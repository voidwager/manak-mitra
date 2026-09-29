"""Vector store seam.

`VectorStore` is the interface the retriever talks to. `DatabaseVectorStore`
is the implementation shipped today: chunks and their vectors live in the
`document_chunks` table, and similarity is brute-force cosine in Python.

That is a deliberate choice, not an oversight:

  - It adds no service to install, secure, patch and back up on plant
    hardware, which matters for an air-gapped deployment.
  - It keeps access scoping in one place. Permissions live in SQL, and
    filtering vectors through a second datastore means keeping two
    permission models in sync - the classic way a RAG system leaks a
    document someone was not cleared for.
  - Brute-force cosine over a few thousand chunks is a few milliseconds.

Its limit is real and worth naming: cost is linear in corpus size, so this
stops being appropriate somewhere in the hundreds of thousands of chunks.
Qdrant is the intended replacement, and the seam is here so that swap is an
implementation of this interface plus a config flag - not a redesign of the
retriever. Whatever replaces it must reproduce the permission filter, not
bolt one on afterwards.

Vectors are stored as JSON arrays so the schema is identical on the SQLite
development fallback and on PostgreSQL. On PostgreSQL, `pgvector` with an
HNSW index is the cheaper upgrade than a separate service, and needs only a
new implementation here.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.database.models import Document, DocumentChunk


@dataclass(frozen=True)
class Candidate:
    """A chunk the current user is allowed to see, ready for scoring."""

    chunk_id: str
    document_id: str
    document_name: str
    position: int
    text: str
    page: int
    section: str
    vector: list[float] | None

    #: Which model produced `vector`. Vectors from different models are not
    #: comparable, so the retriever matches on this before scoring.
    vector_model: str = ""


class VectorStore(ABC):
    """Where chunks and their vectors live."""

    @abstractmethod
    def replace_document_chunks(
        self, db: Session, document_id: str, chunks: list[DocumentChunk]
    ) -> None:
        """Atomically swap a document's chunks for a new set."""

    @abstractmethod
    def load_candidates(self, db: Session, scope: Select) -> list[Candidate]:
        """Every chunk belonging to a document in `scope`.

        `scope` is a SELECT over `Document` that already encodes the calling
        user's permissions. Implementations must not widen it.
        """

    @abstractmethod
    def count_chunks(self, db: Session, scope: Select) -> int:
        """How many chunks are searchable within `scope`."""


class DatabaseVectorStore(VectorStore):
    """Chunks in the relational database; cosine similarity in Python."""

    def replace_document_chunks(
        self, db: Session, document_id: str, chunks: list[DocumentChunk]
    ) -> None:
        db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        db.flush()
        for chunk in chunks:
            db.add(chunk)
        db.flush()

    def load_candidates(self, db: Session, scope: Select) -> list[Candidate]:
        scoped_ids = scope.with_only_columns(Document.id).order_by(None).subquery()

        rows = db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.name,
                DocumentChunk.position,
                DocumentChunk.text,
                DocumentChunk.page,
                DocumentChunk.section,
                DocumentChunk.embedding,
                DocumentChunk.embedding_model,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id.in_(select(scoped_ids.c.id)))
            .order_by(DocumentChunk.document_id, DocumentChunk.position)
        ).all()

        return [
            Candidate(
                chunk_id=row[0],
                document_id=row[1],
                document_name=row[2],
                position=row[3],
                text=row[4],
                page=row[5],
                section=row[6],
                vector=_decode_vector(row[7]),
                vector_model=row[8] or "",
            )
            for row in rows
        ]

    def count_chunks(self, db: Session, scope: Select) -> int:
        scoped_ids = scope.with_only_columns(Document.id).order_by(None).subquery()
        return int(
            db.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_id.in_(select(scoped_ids.c.id))
                )
            )
            or 0
        )


def _decode_vector(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(values, list) or not values:
        return None
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return None


def encode_vector(vector: list[float]) -> str:
    # Six decimals is well past what cosine similarity can distinguish here
    # and roughly halves the stored size against full float repr.
    return json.dumps([round(float(v), 6) for v in vector])


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity, or 0.0 when the vectors cannot be compared.

    Mismatched dimensions mean the two vectors came from different models.
    Returning 0.0 rather than raising keeps one stale chunk from breaking a
    whole search; the retriever filters by model name before it gets here,
    so this is a backstop.
    """
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b

    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


#: The store the application uses. Swapping in Qdrant means replacing this
#: binding, not editing the retriever.
default_store = DatabaseVectorStore()


__all__ = [
    "Candidate",
    "DatabaseVectorStore",
    "VectorStore",
    "cosine_similarity",
    "default_store",
    "encode_vector",
]
