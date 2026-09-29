"""Knowledge-base search.

Retrieval without the model in the way. Two reasons this endpoint exists
rather than retrieval being reachable only through chat:

  - It makes the retrieval layer testable and demonstrable on its own. You
    can show that the right passage comes back for "vibration limit for
    P-204" with no LLM configured at all, which separates "retrieval works"
    from "the model wrote a good answer".
  - It makes the access scoping visible. Sign in as a restricted user and
    the same query returns fewer passages - the filter is in the results,
    not buried in a prompt.

Results are scoped identically to `GET /documents`. There is no parameter
that widens the scope, by design.
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import SearchHit, SearchRequest, SearchResponse
from app.rag import retrieve
from app.services import audit

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search_knowledge_base(
    payload: SearchRequest, user: CurrentUser, db: DbSession
) -> SearchResponse:
    result = retrieve(db, user, payload.query, top_k=payload.top_k)

    audit.record(
        db,
        user_id=user.id,
        action="knowledge_base.search",
        resource_type="document",
        resource_id=None,
        detail={
            "mode": result.mode,
            "hits": len(result.passages),
            "documents": sorted({p.document_id for p in result.passages}),
        },
    )
    db.commit()

    return SearchResponse(
        query=payload.query,
        mode=result.mode,
        results=[
            SearchHit(
                document_id=p.document_id,
                document_name=p.document_name,
                chunk_id=p.chunk_id,
                text=p.text,
                page=p.page,
                section=p.section,
                score=round(p.score, 4),
                lexical_rank=p.lexical_rank,
                semantic_rank=p.semantic_rank,
            )
            for p in result.passages
        ],
        documents_in_scope=result.documents_in_scope,
        indexed_documents_in_scope=result.indexed_documents_in_scope,
        chunks_searched=result.chunks_searched,
        reason=result.reason,
        semantic_error=result.semantic_error,
    )
