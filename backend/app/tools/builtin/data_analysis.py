"""Statistics over indexed tabular documents.

Language models are unreliable at arithmetic over more than a handful of
rows: they lose track, silently skip entries and produce a confident total
that is wrong. For maintenance logs and sensor exports that is precisely the
kind of error nobody catches, so the counting happens here instead.

This reads the *indexed* chunks rather than the original file, which is why
it works at all: extraction already rewrote each CSV row as
`Column: value | Column: value`, so a row is self-describing wherever it
landed and can be parsed back without re-reading the upload.

Scope is inherited from `visible_documents_query` the same way retrieval is
- a table the user cannot open is not analysable by asking an agent nicely.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from sqlalchemy import select

from app.database.models import Document, DocumentChunk
from app.services.access import visible_documents_query
from app.services.agents import effective_folder_scope
from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult

#: Formats extraction produces for tabular files.
TABLE_TYPES = {"CSV", "TSV"}

#: Each extracted row looks like `Date: 2026-08-27 | TagID: P-204 | ...`.
_PAIR = re.compile(r"([^:|]+):\s*([^|]*)")

MAX_ROWS = 20_000

OPERATIONS = ("summary", "count", "sum", "mean", "median", "min", "max", "distinct")


def _rows_for(context: ToolContext, document: Document) -> list[dict[str, str]]:
    chunks = context.db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.position)
    ).all()

    rows: list[dict[str, str]] = []
    for chunk in chunks:
        for line in chunk.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            pairs = {
                key.strip(): value.strip()
                for key, value in _PAIR.findall(line)
                if key.strip()
            }
            if pairs:
                rows.append(pairs)
            if len(rows) >= MAX_ROWS:
                return rows
    return rows


def _numeric(values: list[str]) -> list[float]:
    numbers: list[float] = []
    for value in values:
        # Tolerate units and separators an export might carry: "18.5 barg",
        # "1,240 h". Anything with no leading number is skipped, not zeroed -
        # counting an unparseable cell as 0 would quietly skew every average.
        match = re.match(r"^\s*[-+]?[\d,]*\.?\d+", value.replace(",", ""))
        if match:
            try:
                numbers.append(float(match.group().replace(",", "")))
            except ValueError:
                continue
    return numbers


class DataAnalysisTool(Tool):
    id = "data-analyzer"
    name = "analyse_table"
    description = (
        "Compute statistics over an indexed CSV or spreadsheet in the user's "
        "knowledge base - counts, sums, averages, minimums, maximums and "
        "distinct values of a column. Use this instead of adding numbers "
        "yourself. Call it with operation='summary' first to see which "
        "columns and how many rows a table has."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "document": {
                    "type": "string",
                    "description": (
                        "Part of the table's file name, e.g. 'Maintenance "
                        "History'. Omit to use the only table available."
                    ),
                },
                "operation": {
                    "type": "string",
                    "enum": list(OPERATIONS),
                    "description": (
                        "'summary' lists columns and row count. The rest "
                        "operate on one column."
                    ),
                },
                "column": {
                    "type": "string",
                    "description": "Column name. Required unless operation is 'summary'.",
                },
                "where_column": {
                    "type": "string",
                    "description": "Optional column to filter on before computing.",
                },
                "where_value": {
                    "type": "string",
                    "description": "Value `where_column` must equal (case-insensitive).",
                },
            },
            "required": ["operation"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        operation = (kwargs.get("operation") or "summary").strip().lower()
        if operation not in OPERATIONS:
            raise ToolArgumentError(
                f"'{operation}' is not supported. Use one of: {', '.join(OPERATIONS)}."
            )

        scope = visible_documents_query(context.user)
        folders = effective_folder_scope(context.agent)
        if folders:
            scope = scope.where(Document.folder.in_(folders))

        tables = [
            d
            for d in context.db.scalars(scope)
            if d.type.upper() in TABLE_TYPES and d.chunk_count > 0
        ]
        if not tables:
            return ToolResult(
                content=(
                    "There is no indexed table in this user's knowledge base to "
                    "analyse. Say so rather than estimating."
                ),
                ok=True,
            )

        wanted = (kwargs.get("document") or "").strip().lower()
        if wanted:
            tables = [d for d in tables if wanted in d.name.lower()] or tables
        if len(tables) > 1 and not wanted:
            names = ", ".join(d.name for d in tables[:8])
            return ToolResult(
                content=(
                    f"Several tables are available ({names}). Call again with "
                    "`document` naming the one to use."
                ),
                ok=True,
            )

        table = tables[0]
        rows = _rows_for(context, table)
        if not rows:
            return ToolResult(
                content=f"'{table.name}' has no readable rows.", ok=True
            )

        columns = sorted({key for row in rows for key in row})

        if operation == "summary":
            return ToolResult(
                content=(
                    f"'{table.name}' has {len(rows)} rows and these columns: "
                    f"{', '.join(columns)}."
                ),
                data={"document": table.name, "rows": len(rows), "columns": columns},
            )

        column = (kwargs.get("column") or "").strip()
        if not column:
            raise ToolArgumentError(
                f"`column` is required for '{operation}'. Available columns in "
                f"'{table.name}': {', '.join(columns)}."
            )

        # Tolerate the model's capitalisation drifting from the header's.
        actual = next((c for c in columns if c.lower() == column.lower()), None)
        if actual is None:
            raise ToolArgumentError(
                f"'{column}' is not a column in '{table.name}'. Available: "
                f"{', '.join(columns)}."
            )

        selected = rows
        filter_column = (kwargs.get("where_column") or "").strip()
        filter_value = (kwargs.get("where_value") or "").strip()
        if filter_column and filter_value:
            actual_filter = next(
                (c for c in columns if c.lower() == filter_column.lower()), None
            )
            if actual_filter is None:
                raise ToolArgumentError(
                    f"'{filter_column}' is not a column in '{table.name}'."
                )
            selected = [
                r
                for r in rows
                if r.get(actual_filter, "").strip().lower() == filter_value.lower()
            ]

        values = [r[actual] for r in selected if r.get(actual, "").strip()]
        scoped = (
            f" where {filter_column} = {filter_value}" if filter_column and filter_value else ""
        )

        if operation == "count":
            answer = f"{len(selected)} row(s) in '{table.name}'{scoped}."
            payload: Any = len(selected)
        elif operation == "distinct":
            distinct = sorted({v for v in values})
            answer = (
                f"{len(distinct)} distinct value(s) of {actual}{scoped}: "
                f"{', '.join(distinct[:40])}"
            )
            payload = distinct
        else:
            numbers = _numeric(values)
            if not numbers:
                return ToolResult(
                    content=(
                        f"Column '{actual}' holds no numeric values, so "
                        f"{operation} cannot be computed. Its values look like: "
                        f"{', '.join(values[:5])}"
                    ),
                    ok=True,
                )
            computed = {
                "sum": sum,
                "mean": statistics.fmean,
                "median": statistics.median,
                "min": min,
                "max": max,
            }[operation](numbers)
            answer = (
                f"{operation} of {actual}{scoped} across {len(numbers)} numeric "
                f"value(s) in '{table.name}': {computed:.6g}"
            )
            payload = computed

        return ToolResult(
            content=answer,
            data={
                "document": table.name,
                "operation": operation,
                "column": actual,
                "result": payload,
                "rows_considered": len(selected),
            },
            citations=[
                {
                    "documentId": table.id,
                    "title": table.name,
                    "page": f"Page {table.page}",
                    "pageNumber": table.page,
                    "section": table.section,
                    "excerpt": answer,
                    "score": 1.0,
                }
            ],
        )


__all__ = ["DataAnalysisTool"]
