"""Find the Indian Standard that applies to a product.

"Which standard applies to my product?" is the question the helpdesk exists
for, and keyword search over prose answers it badly: the answer lives in
BIS's own product lists - one row per product, naming the IS number, the
Quality Control Order that made certification compulsory, and the scheme -
and a 1200-character chunk of such a table holds a dozen unrelated rows that
all get cited together.

So this tool reads those lists as tables. It matches the user's product
description against each row and returns the matching rows themselves,
each one a citation pointing back at the published list it came from.

Which lists it reads is decided the same way retrieval is: documents the
caller may see (`visible_documents_query`), in the standards folder, whose
text holds a table with an "IS number" column. Nothing is hardcoded, so an
administrator publishing an updated list is all it takes to update answers.

What it does not do is decide. A matching row means "this product appears
on a compulsory-certification list", not "your product needs a licence" -
the prompt tells the model to say so, and the licensing branch decides.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.database.models import Document
from app.services.access import visible_documents_query
from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult

#: Where BIS product lists are filed. Read from here rather than from every
#: document so a staff note that happens to contain a table is not mistaken
#: for an official list.
STANDARDS_FOLDER = "Standards & QCOs"

MAX_RESULTS = 12
DEFAULT_RESULTS = 6

#: Share of the description's distinctive weight a row must match, on top
#: of naming the product itself. Low, because the head-word rule does the
#: real filtering; this only stops a one-word coincidence on a long query.
MIN_COVERAGE = 0.35

#: "IS 1293", "IS:2347", "IS/IEC 60947", "IS 1489 (Part 1)".
_IS_NUMBER = re.compile(
    r"\bIS(?:\s*/\s*(?:IEC|ISO))?\s*[:\-]?\s*(\d{2,5})(?:\s*\(\s*Part\s*(\d+)\s*\))?",
    re.I,
)

#: How people describe products versus how BIS lists name them. Small and
#: explicit on purpose: every entry here is a word a user typed that the
#: official list never uses. Keys and values are post-stemming tokens.
SYNONYMS: dict[str, frozenset[str]] = {
    "bulb": frozenset({"lamp"}),
    "light": frozenset({"lamp", "luminaire"}),
    "tv": frozenset({"television"}),
    "fridge": frozenset({"refrigerator", "refrigerating"}),
    "ac": frozenset({"conditioner"}),
    "charger": frozenset({"adaptor", "adapter", "supply"}),
    "phone": frozenset({"mobile", "telephone"}),
    "mobile": frozenset({"phone"}),
    "stove": frozenset({"burner", "hob"}),
    "wire": frozenset({"cable"}),
    "cable": frozenset({"wire"}),
    "panel": frozenset({"module", "photovoltaic"}),
    "solar": frozenset({"photovoltaic"}),
    "mixer": frozenset({"grinder", "blender"}),
    "tyre": frozenset({"tire"}),
    "bottle": frozenset({"container"}),
}
_WORD = re.compile(r"[a-z0-9]+")

#: Words that appear in nearly every row or every question and so carry no
#: signal about *which* product is meant.
_STOPWORDS = frozenset(
    """a an and are as at be by for from i in is it its my of on or our the
    this to we what which with need needs required requirement standard
    standards applicable apply applies product products item items make
    manufacture manufacturing sell selling import importing india indian bis
    specification specifications part type types use used""".split()
)


@dataclass(frozen=True)
class StandardRow:
    """One product line from a published BIS list."""

    document_id: str
    document_name: str
    #: Column name -> cell text, exactly as published.
    cells: dict[str, str]
    #: The row as it appears in the source, for the citation excerpt.
    raw: str
    line_number: int

    @property
    def is_number(self) -> str:
        return self.cells.get("IS number", "")

    def searchable(self) -> str:
        return " ".join(
            v for k, v in self.cells.items() if k.lower() not in ("sr", "scheme")
        )


def _stem(word: str) -> str:
    """Just enough stemming to match "cookers" to "cooker"."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    # "boxes", "switches" drop "es"; "pipes", "cables" drop only the "s".
    if word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [
        _stem(w)
        for w in _WORD.findall(text.lower())
        if w not in _STOPWORDS and len(w) > 1
    ]


#: Words that end the product name and start a modifier: "pipes FOR
#: drinking water", "helmet FOR riders", "cables WITH PVC insulation".
_MODIFIER_START = re.compile(
    r"\b(?:for|of|to|with|without|in|on|used|using|made|meant|applies|apply)\b", re.I
)


def product_phrase(query: str) -> list[str]:
    """The tokens naming the product, without its use or purpose.

    "PVC pipes for drinking water" -> [pvc, pipe]; "cement for house
    construction" -> [cement]. The first segment before a modifying word
    that has any content at all, so "which standard applies to pressure
    cookers" still finds [pressure, cooker].
    """
    for segment in _MODIFIER_START.split(query):
        tokens = _tokens(segment)
        if tokens:
            return tokens
    return []


def head_token(query: str) -> str | None:
    """The product word in a description - the head of the noun phrase.

    English puts it last, before any modifying clause: "stainless steel
    pressure COOKER", "PVC PIPES for drinking water", "HELMET for two
    wheeler riders". Material and use words qualify it; they are not it.
    A row that does not name the head is a different product that merely
    shares a qualifier with this one.
    """
    phrase = product_phrase(query)
    return phrase[-1] if phrase else None


def unmatched_words(row: StandardRow, query: str) -> list[str]:
    """Words of the product phrase this row does not contain.

    Reported with every match, because a row for "ductile iron pipes"
    returned for "PVC pipes" is useful only if the reader is told it is not
    about PVC.
    """
    tokens = set(_tokens(row.searchable()))
    return [
        t
        for t in product_phrase(query)
        if not ((frozenset({t}) | SYNONYMS.get(t, frozenset())) & tokens)
    ]


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_number_column(cell: str) -> bool:
    """BIS pages label this column several ways: "IS number", "IS No.",
    "Indian Standard number( IS No.)"."""
    label = re.sub(r"[^a-z]", "", cell.lower())
    return label in ("isnumber", "isno", "indianstandard", "indianstandards") or (
        label.startswith("indianstandard") and ("number" in label or "isno" in label)
    )


def parse_tables(text: str) -> list[tuple[dict[str, str], str, int]]:
    """Every row of every markdown table that has an "IS number" column.

    Returns (cells, raw line, 1-based line number) per row. Tables without
    that column - a fee schedule, a list of districts - are skipped.
    """
    rows: list[tuple[dict[str, str], str, int]] = []
    header: list[str] | None = None

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            continue

        cells = _split_row(stripped)
        if header is None:
            if any(_is_number_column(c) for c in cells):
                header = ["IS number" if _is_number_column(c) else c for c in cells]
            continue

        # The |---|---| divider under the header.
        if all(set(c) <= set("-: ") for c in cells):
            continue

        if len(cells) != len(header):
            continue
        rows.append((dict(zip(header, cells)), stripped, number))

    return rows


#: Parsed lists, keyed by document id and file size so a republished list is
#: re-read and an unchanged one is not parsed on every question.
_CACHE: dict[tuple[str, int], list[StandardRow]] = {}


def _rows_for(document: Document) -> list[StandardRow]:
    if not document.storage_path:
        return []
    key = (document.id, document.size_bytes or 0)
    if key in _CACHE:
        return _CACHE[key]

    path = Path(settings.upload_path) / document.storage_path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    parsed = [
        StandardRow(
            document_id=document.id,
            document_name=document.name,
            cells=cells,
            raw=raw,
            line_number=line,
        )
        for cells, raw, line in parse_tables(text)
    ]
    _CACHE[key] = parsed
    return parsed


def _requested_is_numbers(query: str) -> set[str]:
    """IS numbers the user typed, normalised to "IS 1293" / "IS 1489 (Part 1)"."""
    found = set()
    for number, part in _IS_NUMBER.findall(query):
        found.add(f"IS {number}" + (f" (Part {part})" if part else ""))
        found.add(f"IS {number}")
    return found


def _normalise_is(value: str) -> str:
    match = _IS_NUMBER.search(value)
    if not match:
        return ""
    number, part = match.groups()
    return f"IS {number}" + (f" (Part {part})" if part else "")


def rank(rows: list[StandardRow], query: str, limit: int) -> list[tuple[float, StandardRow]]:
    """Rows most likely to be the product described, best first.

    IDF-weighted token overlap: a word that appears on few rows ("cooker")
    outweighs one on hundreds ("steel"), so "stainless steel pressure cooker"
    lands on pressure cookers rather than on every steel product. An IS
    number the user typed is an exact identifier and outranks any wording.
    """
    if not rows:
        return []

    wanted_is = _requested_is_numbers(query)
    query_tokens = set(_tokens(query))
    if not query_tokens and not wanted_is:
        return []

    row_tokens = [set(_tokens(row.searchable())) for row in rows]
    frequency = Counter(t for tokens in row_tokens for t in tokens)
    total = len(rows)

    def forms(token: str) -> frozenset[str]:
        return frozenset({token}) | SYNONYMS.get(token, frozenset())

    def seen(token: str) -> int:
        return max(frequency.get(form, 0) for form in forms(token))

    def weight(token: str) -> float:
        return math.log(1 + total / max(seen(token), 1))

    # Coverage is measured over the product phrase only, and only over words
    # the lists actually use. "for house construction" says what the cement
    # is for, which no list row describes; counting it would reject them all.
    phrase = [t for t in product_phrase(query) if seen(t)]
    phrase_weight = sum(weight(t) for t in phrase)
    head = head_token(query)

    scored: list[tuple[float, StandardRow]] = []
    for row, tokens in zip(rows, row_tokens):
        # Ranking uses every word, so use and purpose still order the rows.
        score = sum(weight(t) for t in query_tokens if forms(t) & tokens)
        # But a row must name the product itself, and a fair share of how
        # the user described it. Otherwise it is a different product that
        # shares a qualifier - "drinking water" for "PVC pipes for drinking
        # water".
        phrase_score = sum(weight(t) for t in phrase if forms(t) & tokens)
        covered = (
            head is not None
            and bool(forms(head) & tokens)
            and phrase_weight > 0
            and phrase_score / phrase_weight >= MIN_COVERAGE
        )
        if wanted_is and _normalise_is(row.is_number) in wanted_is:
            score += 100.0
            covered = True
        if score > 0 and covered:
            scored.append((score, row))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return []

    # Keep rows reasonably close to the best match. Without this a query
    # matching one row strongly also returns a tail of rows that share only
    # a common word, and the model cites them as if they applied.
    best = scored[0][0]
    return [pair for pair in scored if pair[0] >= best * 0.5][:limit]


class FindStandardTool(Tool):
    id = "standard-finder"
    name = "find_standard"
    description = (
        "Find which Indian Standard (IS number), Quality Control Order and "
        "certification scheme apply to a product, by searching BIS's "
        "published lists of products under compulsory certification. Use it "
        "whenever the user describes a product and asks which standard, "
        "licence or registration applies, or gives an IS number and asks "
        "what it covers. Returns the matching rows exactly as published, "
        "each citable by its bracketed number. A product that is not on any "
        "list may still have a voluntary standard - say so rather than "
        "guessing one."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": (
                        "The product in plain English, as specific as the "
                        "user was: material, use, type (\"stainless steel "
                        "pressure cooker\", \"USB power bank\", \"PVC pipes "
                        "for drinking water\"). Or an IS number such as "
                        "IS 2347. Translate to English first if needed."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": f"How many rows to return. Default {DEFAULT_RESULTS}.",
                    "minimum": 1,
                    "maximum": MAX_RESULTS,
                },
            },
            "required": ["product"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        product = (kwargs.get("product") or "").strip()
        if not product:
            raise ToolArgumentError("Describe the product to look up.")
        limit = max(1, min(int(kwargs.get("limit") or DEFAULT_RESULTS), MAX_RESULTS))

        lists = context.db.scalars(
            visible_documents_query(context.user).where(
                Document.folder == STANDARDS_FOLDER
            )
        ).all()

        rows = [row for document in lists for row in _rows_for(document)]
        if not rows:
            return ToolResult(
                content=(
                    "No BIS product list is available in the knowledge base, so "
                    "the applicable standard cannot be looked up. Say so, and "
                    "point the user to bis.gov.in rather than naming a standard "
                    "from memory."
                ),
                ok=True,
            )

        matches = rank(rows, product, limit)
        if not matches:
            return ToolResult(
                content=(
                    f"'{product}' does not appear on the BIS compulsory "
                    f"certification lists in the knowledge base ({len(rows)} "
                    "products searched). That can mean certification is not "
                    "compulsory for it, or that it is listed under another "
                    "name. Say exactly that; suggest describing the product "
                    "differently, and do not name a standard from memory."
                ),
                ok=True,
                data={"product": product, "searched": len(rows), "matches": 0},
            )

        blocks: list[str] = []
        citations: list[dict] = []
        for number, (_, row) in enumerate(matches, start=1):
            fields = "; ".join(
                f"{k}: {v}" for k, v in row.cells.items() if v and k.lower() != "sr"
            )
            missing = unmatched_words(row, product)
            caveat = (
                f"\nNOTE: this row does not mention: {', '.join(missing)}. Say "
                "so, and tell the user to check the standard's scope covers "
                "their product rather than presenting it as a certain match."
                if missing
                else ""
            )
            blocks.append(
                f"[{number}] {row.document_name} (line {row.line_number})\n{fields}{caveat}"
            )
            citations.append(
                {
                    "documentId": row.document_id,
                    "title": row.document_name,
                    "page": f"Line {row.line_number} · {row.is_number}",
                    "pageNumber": 1,
                    "section": row.is_number,
                    "excerpt": fields,
                    "score": 1.0,
                }
            )

        return ToolResult(
            content=(
                f"{len(matches)} matching product row(s) from BIS lists of "
                f"products under compulsory certification ({len(rows)} "
                "searched):\n\n"
                + "\n\n".join(blocks)
                + "\n\nA row means the product is on a compulsory list; confirm "
                "the exact product scope in the standard and the current order "
                "before telling the user a licence is required."
            ),
            citations=citations,
            data={"product": product, "searched": len(rows), "matches": len(matches)},
        )


__all__ = ["FindStandardTool", "STANDARDS_FOLDER", "parse_tables", "rank"]
