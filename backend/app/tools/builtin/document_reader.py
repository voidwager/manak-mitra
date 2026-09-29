"""The tool that reads a document end to end.

`knowledge_retrieval` answers questions *inside* documents. This answers
questions *about* one: summarise it, list its sections, say what it covers.
Those cannot be served by ranking, because a summary request carries no
distinctive terms to rank on - BM25 scores every chunk about equally and
returns an arbitrary handful, which is how "summarise this SOP" ended up
producing either a random paragraph or a flat refusal.

Scoping is inherited, not re-checked: `rag.read_document` resolves names
through the same `scoped_document_query` the retriever uses. Naming a
document the caller cannot open returns "no such document in scope" rather
than a denial, because a denial would confirm the document exists.
"""

from __future__ import annotations

from typing import Any

from app.rag.reader import read_document
from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult


class DocumentReaderTool(Tool):
    id = "doc-reader"
    name = "read_document"
    description = (
        "Read one document from start to finish, in order. Use this whenever "
        "the question is about a document as a whole - summarise it, what is "
        "in it, what are its main topics or sections, what does it cover, "
        "give an overview. Keyword search returns only scattered passages and "
        "cannot answer those questions; this returns the actual text. Long "
        "documents arrive in numbered parts - read part 1, and if it says "
        "more parts remain, call again with the next part number before "
        "summarising. Reads only what this user is cleared to see."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "document": {
                    "type": "string",
                    "description": (
                        "The document's name, as exactly as you know it "
                        "(for example 'Compulsory Registration Scheme (CRS).md')."
                    ),
                },
                "part": {
                    "type": "integer",
                    "description": (
                        "Which part to read, 1-based. Defaults to 1. Only "
                        "needed for documents long enough to be split."
                    ),
                    "minimum": 1,
                },
            },
            "required": ["document"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        name = (kwargs.get("document") or "").strip()
        if not name:
            raise ToolArgumentError("A document name is required.")

        try:
            part = int(kwargs.get("part") or 1)
        except (TypeError, ValueError):
            part = 1

        result = read_document(
            context.db,
            context.user,
            name=name,
            part=part,
            folder_scope=context.search_scope(),
            conversation_id=context.conversation_id,
        )

        if not result.found:
            # Listing what *is* readable turns a dead end into a usable next
            # step: the model can name a real document instead of guessing
            # again or telling the user it has no access.
            lines = [result.reason]
            if result.candidates:
                lines.append("Documents you can read:")
                lines.extend(
                    f"- {c['name']}" + (f" ({c['folder']})" if c.get("folder") else "")
                    for c in result.candidates
                )
            else:
                lines.append(
                    "Say plainly that this document is not in the knowledge "
                    "base rather than answering from memory."
                )
            return ToolResult(content="\n".join(lines), ok=True)

        page = result.part
        assert page is not None  # guarded by `found`

        header = (
            f"{page.document_name} - part {page.part} of {page.total_parts} "
            f"(pages {page.first_page}-{page.last_page}, "
            f"{page.chunks_in_part} of {page.total_chunks} passages)"
        )
        if page.is_complete:
            header += "\nThis is the entire document."
        elif page.part < page.total_parts:
            header += (
                f"\n{page.total_parts - page.part} further part(s) remain. Call "
                f"read_document again with part={page.part + 1} before "
                "summarising the document as a whole."
            )
        else:
            header += "\nThis is the final part."

        return ToolResult(
            content=f"{header}\n\n{page.text}",
            citations=result.citations,
            data={
                "document": page.document_name,
                "documentId": page.document_id,
                "part": page.part,
                "totalParts": page.total_parts,
            },
        )


__all__ = ["DocumentReaderTool"]
