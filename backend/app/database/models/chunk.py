"""Indexed document chunks - the retrieval corpus.

One row per passage of extracted text. This table is the vector store: it
holds the text for lexical (BM25) search and, when an embedding provider is
configured, the vector for semantic search alongside it.

Keeping both in one table is deliberate at this stage. A dedicated vector
database (Qdrant) is the deployment target, but it is a second service to
install, secure and back up on plant hardware, and it buys nothing until the
corpus is large. `app/rag/store.py` defines the seam it slots into, so the
swap is an implementation change rather than a redesign - the same shape as
the model gateway.

Embeddings are stored as JSON rather than a native vector type because the
schema has to work identically on the SQLite development fallback and on
PostgreSQL. `pgvector` is the upgrade path; see `app/rag/store.py`.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.document import Document


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: 0-based order within the document.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: Character offsets into the extracted text. Lets a citation point at
    #: the exact span rather than the whole document.
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Provenance shown in a citation. `page` is the real page for PDFs and
    #: 1 for formats without pagination; `section` is the nearest preceding
    #: heading, or "" when the document has none. Never invented.
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    section: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    #: The vector, as a JSON array of floats. NULL means this chunk is
    #: lexical-only - either no embedder was configured when it was indexed,
    #: or the embedding call failed. Retrieval must treat NULL as "not
    #: searchable semantically", never as a zero vector.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Which model produced `embedding`. Vectors from different models are
    #: not comparable, so retrieval only uses chunks whose model matches the
    #: currently configured one.
    embedding_model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunks_doc_position", "document_id", "position"),
    )
