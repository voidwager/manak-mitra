"""Retrieval-augmented generation.

    documents.py  ──►  indexer  ──►  extraction ─► chunking ─► embeddings
                                          │
                                          ▼
                                    document_chunks  (store.py)
                                          │
    chat_service  ──►  retriever  ◄───────┘
                          │
                          └─► lexical BM25  +  semantic cosine  ──► RRF

Two seams are load-bearing and mirror the model gateway:

  `embeddings/`  nothing above it names an embedding vendor or knows where
                 vectors are computed.
  `store.py`     nothing above it knows whether chunks live in PostgreSQL or
                 in a dedicated vector database.

Two invariants the rest of the application relies on:

  1. Retrieval is scoped by `visible_documents_query`. A user can never
     retrieve a passage from a document they cannot open.
  2. A citation is only ever built from a passage that was actually
     retrieved and placed in the prompt. Nothing parses citations out of
     model output.
"""

from app.rag.indexer import IndexResult, index_document, index_document_by_id
from app.rag.retriever import (
    Passage,
    RetrievalResult,
    build_context_block,
    retrieve,
)

__all__ = [
    "IndexResult",
    "Passage",
    "RetrievalResult",
    "build_context_block",
    "index_document",
    "index_document_by_id",
    "retrieve",
]
