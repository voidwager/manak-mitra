"""Splitting extracted text into retrievable passages.

Two rules drive the design.

**A chunk must be readable on its own.** It is quoted into the prompt
without its surroundings, so a fragment that starts mid-sentence, or a table
row separated from its header, is worse than useless - it is misleading. So
splitting happens on paragraph and sentence boundaries, never mid-word, and
each chunk carries a small overlap with the previous one so a fact spanning
a boundary survives in at least one of them.

**A chunk must know where it came from.** Page number and the nearest
preceding heading are tracked during the walk. That provenance is what makes
a citation checkable, and it is recorded here - not guessed later from the
model's output.

Sizes are in characters, not tokens. The tokenizer belongs to whichever
model is loaded, and pulling in a model-specific tokenizer purely to measure
a split would put a vendor dependency below the gateway seam. Roughly four
characters per token is close enough for a budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.extraction import Extracted

#: Headings we can recognise without a document-specific parser. Anything
#: else leaves `section` empty rather than guessing.
#:
#: Every pattern excludes sentence punctuation (`[^.!?]`) after the label.
#: Without that guard, a body line beginning with a measurement - "3.2 mm/s
#: RMS the pump is taken out of service immediately." - parses as clause
#: 3.2, which both mislabels the section and splits the paragraph away from
#: the clause it belongs to. A wrong section on a citation is worse than no
#: section, so these are deliberately strict: prose that looks slightly like
#: a heading is treated as prose.
_HEADING_PATTERNS = (
    # Markdown: "## 4.2 Pump inspection"
    re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$"),
    # Numbered clause: "4.2 Pump inspection", "4.2. Pump inspection".
    # The capital after the number is what separates a clause title from a
    # sentence that opens with a figure.
    re.compile(r"^(?P<title>\d+(?:\.\d+){0,3}\.?\s+[A-Z][^.!?]{0,100})$"),
    # Named clause: "Section 4.2 - Pump inspection", "Appendix B: Torques"
    re.compile(
        r"^(?P<title>(?:section|clause|appendix|annexure|annex|part|chapter|table)"
        r"\s+[\w.\-]+\s*[-:–]?[^.!?]{0,100})$",
        re.IGNORECASE,
    ),
    # ALL CAPS line used as a heading.
    re.compile(r"^(?P<title>[A-Z][A-Z0-9 ,'()/&\-]{4,90})$"),
)

#: Chunks shorter than this are merged into a neighbour. A title line or a
#: stray sentence left on its own is noise: it competes for a retrieval slot
#: it cannot fill, because there is not enough of it to answer anything.
MIN_CHUNK_CHARS = 160

#: Sentence end followed by whitespace. Deliberately conservative: it does
#: not try to handle abbreviations, because a wrong split only costs a few
#: characters of overlap.
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage."""

    position: int
    text: str
    char_start: int
    char_end: int
    page: int
    section: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def detect_heading(line: str) -> str | None:
    """Return the heading title on `line`, or None if it is body text."""
    stripped = line.strip()
    if not stripped or len(stripped) > 130:
        return None
    # A line ending in a sentence full stop is prose, not a heading - except
    # for the numbered form, where "4.2." is the numbering, not punctuation.
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(stripped)
        if match:
            title = match.group("title").strip().rstrip(".").strip()
            return title or None
    return None


def _split_oversize(block: str, limit: int) -> list[str]:
    """Break a single over-long block on sentence, then word, boundaries."""
    if len(block) <= limit:
        return [block]

    pieces: list[str] = []
    current = ""

    for sentence in _SENTENCE_END.split(block):
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # A single sentence longer than the limit (dense tables, no
        # punctuation) still has to be cut. Cut on whitespace, never
        # mid-word.
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        current = sentence

    if current:
        pieces.append(current)
    return [p for p in pieces if p]


def _tail_overlap(text: str, overlap: int) -> str:
    """The last `overlap` characters of `text`, trimmed to a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    cut = tail.find(" ")
    return tail[cut + 1 :].strip() if cut != -1 else tail.strip()


def chunk_document(
    extracted: Extracted,
    *,
    chunk_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Split `extracted` into overlapping, provenance-tagged passages."""
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    overlap_chars = max(0, min(overlap_chars, chunk_chars // 2))

    if extracted.kind == "table":
        return _chunk_table(extracted, chunk_chars=chunk_chars)

    chunks = _chunk_prose(
        extracted, chunk_chars=chunk_chars, overlap_chars=overlap_chars
    )
    return _merge_undersized(chunks, chunk_chars=chunk_chars)


def _merge_undersized(chunks: list[Chunk], *, chunk_chars: int) -> list[Chunk]:
    """Fold too-small chunks into the neighbour they belong with.

    Merging is forward (a heading joins the text under it) and only within a
    page, so a merged chunk's page citation stays correct. A chunk that
    cannot merge without breaking either rule is kept as it is - a slightly
    small chunk is a much smaller problem than a citation pointing at the
    wrong page.
    """
    if len(chunks) < 2:
        return chunks

    merged: list[Chunk] = []
    pending: Chunk | None = None

    for chunk in chunks:
        if pending is not None:
            joinable = (
                pending.page == chunk.page
                and len(pending.text) + len(chunk.text) + 2 <= chunk_chars
            )
            if joinable:
                chunk = Chunk(
                    position=0,  # renumbered below
                    text=f"{pending.text}\n\n{chunk.text}",
                    char_start=pending.char_start,
                    char_end=chunk.char_end,
                    page=pending.page,
                    # The heading the small chunk introduced wins, since it
                    # is what the following text sits under.
                    section=pending.section or chunk.section,
                )
            else:
                merged.append(pending)
            pending = None

        if len(chunk.text) < MIN_CHUNK_CHARS:
            pending = chunk
            continue
        merged.append(chunk)

    if pending is not None:
        # A trailing runt merges backwards instead, same page rule.
        if merged and merged[-1].page == pending.page:
            last = merged.pop()
            merged.append(
                Chunk(
                    position=0,
                    text=f"{last.text}\n\n{pending.text}",
                    char_start=last.char_start,
                    char_end=pending.char_end,
                    page=last.page,
                    section=last.section or pending.section,
                )
            )
        else:
            merged.append(pending)

    return [
        Chunk(
            position=index,
            text=chunk.text,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page=chunk.page,
            section=chunk.section,
        )
        for index, chunk in enumerate(merged)
    ]


# ---------------------------------------------------------------------------
# Prose
# ---------------------------------------------------------------------------
def _chunk_prose(
    extracted: Extracted, *, chunk_chars: int, overlap_chars: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = ""
    offset = 0  # running character offset across the whole document

    # Buffered chunk under construction.
    buffer = ""
    buffer_start = 0
    buffer_page = 1
    buffer_section = ""

    def flush() -> None:
        nonlocal buffer, buffer_start, buffer_section, buffer_page
        text = buffer.strip()
        if text:
            chunks.append(
                Chunk(
                    position=len(chunks),
                    text=text,
                    char_start=buffer_start,
                    char_end=buffer_start + len(text),
                    page=buffer_page,
                    section=buffer_section,
                )
            )
        buffer = ""

    for page in extracted.pages:
        if not page.text.strip():
            offset += len(page.text) + 1
            continue

        for block in _blocks(page.text):
            heading = detect_heading(block)
            if heading:
                # A heading belongs with the text beneath it, so close the
                # previous chunk before starting the new section.
                flush()
                section = heading

            for piece in _split_oversize(block, chunk_chars):
                candidate = f"{buffer}\n\n{piece}" if buffer else piece

                if len(candidate) > chunk_chars and buffer:
                    flush()
                    carry = _tail_overlap(chunks[-1].text, overlap_chars) if chunks else ""
                    buffer = f"{carry}\n\n{piece}".strip() if carry else piece
                    buffer_start = offset
                    buffer_page = page.number
                    buffer_section = section
                else:
                    if not buffer:
                        buffer_start = offset
                        buffer_page = page.number
                        buffer_section = section
                    buffer = candidate

                offset += len(piece) + 2

        # Page boundaries close a chunk: mixing two pages into one passage
        # would make its page citation wrong for half its content.
        flush()

    flush()
    return chunks


def _blocks(text: str) -> list[str]:
    """Paragraphs, with each heading line isolated as its own block."""
    out: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        lines = paragraph.split("\n")
        pending: list[str] = []
        for line in lines:
            if detect_heading(line):
                if pending:
                    out.append("\n".join(pending).strip())
                    pending = []
                out.append(line.strip())
            else:
                pending.append(line)
        if pending:
            out.append("\n".join(pending).strip())
    return [b for b in out if b]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def _chunk_table(extracted: Extracted, *, chunk_chars: int) -> list[Chunk]:
    """Pack whole rows into chunks. A row is never split across chunks.

    Extraction has already rewritten each row as `column: value` pairs, so a
    row remains self-describing wherever it lands. Overlap is pointless here
    - rows are independent records - so it is not applied.
    """
    chunks: list[Chunk] = []
    offset = 0
    buffer: list[str] = []
    buffer_start = 0

    def flush() -> None:
        nonlocal buffer, buffer_start
        if not buffer:
            return
        text = "\n".join(buffer)
        chunks.append(
            Chunk(
                position=len(chunks),
                text=text,
                char_start=buffer_start,
                char_end=buffer_start + len(text),
                page=1,
                # Delimited files have no sections. Leave it empty rather
                # than manufacturing a label the file does not contain.
                section="",
            )
        )
        buffer = []

    for page in extracted.pages:
        for row in page.text.split("\n"):
            row = row.strip()
            if not row:
                continue
            projected = sum(len(r) + 1 for r in buffer) + len(row)
            if buffer and projected > chunk_chars:
                flush()
                buffer_start = offset
            if not buffer:
                buffer_start = offset
            buffer.append(row)
            offset += len(row) + 1
        flush()

    flush()
    return chunks


__all__ = ["Chunk", "chunk_document", "detect_heading"]
