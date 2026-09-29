"""Indexing: a stored file becomes a searchable document.

    read bytes -> extract text -> chunk -> embed (if configured) -> persist

Failure handling is the interesting part. Each stage can fail differently
and the document's recorded state has to say which, because "not indexed"
with no reason is indistinguishable from "indexed but empty" to the person
wondering why the assistant cannot find their SOP:

  UNSUPPORTED  the format holds no readable text here (scanned PDF, .doc,
               image). Retrying will not help until OCR exists.
  FAILED       something that should have worked did not. Retrying may help.
  INDEXED      chunks exist and are searchable.

Embedding failure is deliberately *not* fatal. Lexical retrieval needs no
vectors, so a document whose embedding call timed out is still indexed and
still searchable - it is recorded as lexical-only, and re-indexing later
adds the vectors. Refusing to index at all because a side capability was
unavailable would be the wrong trade.

A document is never left half-indexed: chunks are replaced in one
transaction, so an interrupted run leaves either the old set or the new one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.database.base import utcnow
from app.database.models import Document, DocumentChunk, DocumentStatus
from app.rag import extraction
from app.rag.chunking import chunk_document
from app.rag.embeddings import EmbeddingError, get_embedding_gateway
from app.rag.store import VectorStore, default_store, encode_vector

log = get_logger(__name__)

#: How much of the first chunk becomes the document's preview excerpt.
EXCERPT_CHARS = 400


@dataclass(frozen=True)
class IndexResult:
    document_id: str
    status: str
    chunk_count: int = 0
    extracted_chars: int = 0
    embedded_chunks: int = 0
    embedding_model: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == DocumentStatus.INDEXED


def _stored_bytes(document: Document) -> bytes:
    if not document.storage_path:
        raise extraction.UnsupportedDocument(
            "This document has no stored file. It exists as a catalogue "
            "entry only, so there is nothing to index."
        )

    path = settings.upload_path / document.storage_path
    if not path.is_file():
        raise extraction.ExtractionFailed(
            "The stored file is missing from disk. Upload it again."
        )
    return path.read_bytes()


def _suffix(document: Document) -> str:
    if document.storage_path:
        return Path(document.storage_path).suffix.lower()
    return f".{document.type.lower()}" if document.type else ""


def _finish_failed(
    db: Session, document: Document, status: str, message: str
) -> IndexResult:
    """Record a failure and clear any stale chunks.

    Clearing matters: leaving the previous index in place after a failed
    re-index means the assistant answers from a version of the document that
    no longer exists.
    """
    default_store.replace_document_chunks(db, document.id, [])
    document.status = status
    document.chunk_count = 0
    document.index_error = message
    document.indexed_at = None
    document.is_semantically_indexed = False
    db.flush()
    log.info("Indexing %s -> %s: %s", document.id, status, message)
    return IndexResult(document_id=document.id, status=status, error=message)


def index_document(
    db: Session,
    document: Document,
    *,
    store: VectorStore | None = None,
) -> IndexResult:
    """Extract, chunk, embed and persist. Never raises for a bad document.

    The caller commits. Everything this touches is inside the caller's
    transaction so a failure part-way leaves no partial index behind.
    """
    store = store or default_store

    document.status = DocumentStatus.PROCESSING
    document.index_error = ""
    db.flush()

    # --- extract --------------------------------------------------------
    try:
        data = _stored_bytes(document)
        extracted = extraction.extract(data, _suffix(document))
    except extraction.UnsupportedDocument as exc:
        return _finish_failed(db, document, DocumentStatus.UNSUPPORTED, str(exc))
    except extraction.ExtractionFailed as exc:
        return _finish_failed(db, document, DocumentStatus.FAILED, str(exc))
    except Exception as exc:  # noqa: BLE001 - a parser must not take down the API
        log.exception("Unexpected extraction failure for %s", document.id)
        return _finish_failed(
            db, document, DocumentStatus.FAILED, f"Unexpected error while reading the file: {exc}"
        )

    document.extracted_chars = extracted.total_chars

    if not extracted.has_text:
        return _finish_failed(
            db,
            document,
            DocumentStatus.UNSUPPORTED,
            "No text could be extracted. If this is a scanned document it "
            "needs OCR, which this deployment does not have yet.",
        )

    # --- chunk ----------------------------------------------------------
    try:
        chunks = chunk_document(
            extracted,
            chunk_chars=settings.rag_chunk_chars,
            overlap_chars=settings.rag_chunk_overlap_chars,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Chunking failed for %s", document.id)
        return _finish_failed(
            db, document, DocumentStatus.FAILED, f"Could not split the document: {exc}"
        )

    if not chunks:
        return _finish_failed(
            db,
            document,
            DocumentStatus.UNSUPPORTED,
            "The document produced no usable passages - it appears to be empty.",
        )

    # --- embed (optional) -----------------------------------------------
    gateway = get_embedding_gateway()
    vectors: list[list[float]] = []
    embedding_model = ""
    embedding_note = ""

    if gateway.is_configured:
        try:
            vectors = gateway.embed([c.text for c in chunks])
            embedding_model = gateway.model
        except EmbeddingError as exc:
            # Not fatal. Lexical retrieval carries the document.
            vectors = []
            embedding_note = (
                f"Indexed for keyword search only - the embedding endpoint "
                f"was unavailable ({exc}). Re-index to add semantic search."
            )
            log.warning("Embedding failed for %s: %s", document.id, exc)

    if vectors and len(vectors) != len(chunks):  # pragma: no cover - provider guards this
        vectors = []
        embedding_note = (
            "Indexed for keyword search only - the embedding endpoint "
            "returned the wrong number of vectors."
        )

    # --- persist ---------------------------------------------------------
    rows: list[DocumentChunk] = []
    for position, chunk in enumerate(chunks):
        vector = vectors[position] if vectors else None
        rows.append(
            DocumentChunk(
                id=f"chunk-{uuid.uuid4().hex[:16]}",
                document_id=document.id,
                position=position,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                page=chunk.page,
                section=chunk.section[:200],
                embedding=encode_vector(vector) if vector else None,
                embedding_model=embedding_model if vector else "",
                embedding_dim=len(vector) if vector else 0,
            )
        )

    store.replace_document_chunks(db, document.id, rows)

    first = chunks[0]
    document.status = DocumentStatus.INDEXED
    document.chunk_count = len(rows)
    document.indexed_at = utcnow()
    document.index_error = embedding_note
    document.is_semantically_indexed = bool(vectors)

    # Preview metadata now comes from the real text rather than staying
    # empty or, worse, being authored.
    document.excerpt = first.text[:EXCERPT_CHARS]
    document.page = first.page
    if first.section:
        document.section = first.section[:160]

    db.flush()

    log.info(
        "Indexed %s: %s chunks, %s chars, %s",
        document.id,
        len(rows),
        extracted.total_chars,
        f"embedded with {embedding_model}" if vectors else "lexical only",
    )

    return IndexResult(
        document_id=document.id,
        status=DocumentStatus.INDEXED,
        chunk_count=len(rows),
        extracted_chars=extracted.total_chars,
        embedded_chunks=len(vectors),
        embedding_model=embedding_model,
        error=embedding_note,
    )


def index_document_by_id(document_id: str) -> IndexResult | None:
    """Index in a session of this function's own, for background execution.

    FastAPI closes the request-scoped session when the handler returns,
    which for a background task is before the work starts - the same reason
    the streaming chat route opens its own session.
    """
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None:
            log.warning("Cannot index %s: it no longer exists.", document_id)
            return None
        try:
            result = index_document(db, document)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("Indexing transaction failed for %s", document_id)
            # Record the failure in its own transaction so the document does
            # not sit on PROCESSING for ever.
            failed = db.get(Document, document_id)
            if failed is not None:
                failed.status = DocumentStatus.FAILED
                failed.index_error = (
                    "Indexing failed unexpectedly. See the server log for details."
                )
                failed.chunk_count = 0
                db.commit()
            return None
        return result


__all__ = ["IndexResult", "index_document", "index_document_by_id"]
