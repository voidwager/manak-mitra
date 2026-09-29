"""The two tools that read the knowledge base.

Both go through `app.rag.retrieve`, which means both inherit the Phase 8
scoping for free: the candidate set is filtered by the *calling user's* SQL
permissions, and the agent's folder scope can only narrow it further. There
is no separate permission check here to drift out of sync with the one the
documents API uses - that duplication is how RAG systems end up leaking a
document through a tool that nobody remembered to re-secure.

Why two tools rather than one:

  document_search      "which documents cover this?" - a map of the corpus,
                       titles and one-line matches. Cheap, and it lets the
                       model orient before it commits to reading.
  knowledge_retrieval  "what exactly do they say?" - full passages with
                       citations attached to the reply.

The split matters because the model already receives automatic retrieval on
the user's own question. These tools let it search for something *different*
- a term the user did not use, a follow-up, a second unit - which is the
whole reason tool-calling beats a single up-front retrieval.
"""

from __future__ import annotations

from typing import Any

from app.rag import retrieve
from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult

#: Keeps a tool result from swamping the model's context.
MAX_SNIPPET_CHARS = 260
MAX_PASSAGE_CHARS = 900


def _query(kwargs: dict) -> str:
    query = (kwargs.get("query") or "").strip()
    if not query:
        raise ToolArgumentError("A search query is required.")
    return query


class DocumentSearchTool(Tool):
    id = "doc-search"
    name = "document_search"
    description = (
        "Find which documents in the user's authorised knowledge base mention "
        "a topic. Returns document names with a short matching snippet from "
        "each - use it to discover what exists before reading in detail. "
        "Searches only what this user is cleared to see."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to search for, in English. Include identifiers "
                        "verbatim (IS 2347, IS/IEC 60947, HUID, CRS) - they "
                        "match exactly and are the strongest signal."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "How many documents to return. Default 5.",
                    "minimum": 1,
                    "maximum": 15,
                },
            },
            "required": ["query"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        query = _query(kwargs)
        limit = max(1, min(int(kwargs.get("limit") or 5), 15))

        result = retrieve(
            context.db,
            context.user,
            query,
            top_k=limit * 3,  # over-fetch, then collapse to one row per document
            folder_scope=context.search_scope(),
            conversation_id=context.conversation_id,
        )

        if not result.found:
            return ToolResult(
                content=(
                    f"No document matched '{query}'. {result.reason} "
                    "Do not guess what a document says - tell the user nothing "
                    "was found."
                ),
                ok=True,
            )

        seen: dict[str, str] = {}
        for passage in result.passages:
            if passage.document_id in seen:
                continue
            snippet = " ".join(passage.text.split())[:MAX_SNIPPET_CHARS]
            location = f"page {passage.page}"
            if passage.section:
                location += f", {passage.section}"
            seen[passage.document_id] = (
                f"- {passage.document_name} ({location}): {snippet}..."
            )
            if len(seen) >= limit:
                break

        return ToolResult(
            content=(
                f"{len(seen)} document(s) matched '{query}':\n"
                + "\n".join(seen.values())
                + "\n\nUse knowledge_retrieval to read any of these in full "
                "before quoting them."
            ),
            data={"query": query, "documents": list(seen)},
        )


class KnowledgeRetrievalTool(Tool):
    id = "know-retrieval"
    name = "knowledge_retrieval"
    description = (
        "Read the exact passages from approved documents that answer a "
        "question, with their page and section. Every passage returned is "
        "citable - cite them by their bracketed number. Searches only what "
        "this user is cleared to see."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The question to answer from the documents. Be "
                        "specific; include identifiers verbatim."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "How many passages to return. Default 5.",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        query = _query(kwargs)
        limit = max(1, min(int(kwargs.get("limit") or 5), 10))

        result = retrieve(
            context.db,
            context.user,
            query,
            top_k=limit,
            folder_scope=context.search_scope(),
            conversation_id=context.conversation_id,
        )

        if not result.found:
            return ToolResult(
                content=(
                    f"No passage matched '{query}'. {result.reason} "
                    "Say plainly that the knowledge base does not cover this "
                    "rather than answering from memory."
                ),
                ok=True,
            )

        blocks = []
        for number, passage in enumerate(result.passages, start=1):
            location = f"page {passage.page}"
            if passage.section:
                location += f", {passage.section}"
            text = passage.text[:MAX_PASSAGE_CHARS]
            blocks.append(f"[{number}] {passage.document_name} ({location})\n{text}")

        return ToolResult(
            content="\n\n".join(blocks),
            # Attached to the reply exactly like automatic retrieval, so a
            # tool-sourced answer is as checkable as a directly retrieved one.
            citations=[p.as_citation() for p in result.passages],
            data={"query": query, "mode": result.mode},
        )


__all__ = ["DocumentSearchTool", "KnowledgeRetrievalTool"]
