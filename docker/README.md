# Docker

Currently holds nothing but this note.

`docker-compose.yml` at the repository root starts PostgreSQL for local
development. Dockerfiles for the backend and frontend, and a compose file
that runs the whole stack, arrive with the deployment milestone (Phase 17)
alongside the local model runtime.

No vector database service is needed. Retrieval stores its chunks and
vectors in the `document_chunks` table of the same PostgreSQL instance, so
the deployment stays one database rather than two - see the "Storage" note
under Retrieval in the root README for when that stops being the right
trade, and `backend/app/rag/store.py` for the seam Qdrant would slot into.

Adding half-finished Dockerfiles now would only be scaffolding nobody runs.
