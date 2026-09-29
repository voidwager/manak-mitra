"""Build the seed corpus as real files on disk.

Two kinds of source live under `data/`:

  data/bis/source/    public BIS material - scheme pages, product lists,
                      hallmarking rules, lab directories, the Act - each
                      file headed with the URL it was captured from and the
                      date. This is what the helpdesk answers from.
  data/bis/internal/  three short staff-only samples, fictional and labelled
                      as such in their first lines, which exist only to
                      demonstrate that desk material never reaches a public
                      answer.

Why files rather than database rows: before this, the seeded documents were
catalogue entries with no bytes behind them, so a fresh checkout had nothing
to retrieve and the assistant could not cite anything until someone uploaded
a file by hand. The pipeline built in Phase 8 was real but had nothing to
work on.

Why generated rather than committed: the source text lives in
`data/demo/source/` as plain text, which is diffable and reviewable in a way
a binary PDF is not. The PDFs are built from it at seed time.

The PDF writer below uses pypdf alone - already a dependency for *reading*
PDFs - rather than pulling in a reporting library to write five demo files.
It emits a genuine text PDF: real pages, real extractable text, real page
numbers, which is what makes the citations point at something checkable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from app.core.config import REPO_ROOT
from app.core.logging import get_logger

log = get_logger(__name__)

#: Where the human-readable source text lives. Seed entries name a path
#: relative to this, e.g. "bis/source/01_....md".
SOURCE_DIR = REPO_ROOT / "data"

#: A line of this alone starts a new page in the generated PDF.
PAGE_BREAK = "---PAGE---"

# --- Page geometry (US Letter, in points) ----------------------------------
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_LEFT = 64
MARGIN_TOP = 728
FONT_SIZE = 10.5
LEADING = 14.5
#: Helvetica at 10.5pt averages ~5.2pt per character, so this keeps a line
#: inside the right margin without needing font metrics.
WRAP_COLUMNS = 88
LINES_PER_PAGE = int((MARGIN_TOP - 56) / LEADING)


@dataclass(frozen=True)
class GeneratedFile:
    """A demo file written to disk, ready to be indexed."""

    path: Path
    size_bytes: int


def _escape(text: str) -> str:
    """Escape the three characters that terminate a PDF string literal."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(line: str, columns: int = WRAP_COLUMNS) -> list[str]:
    """Wrap on whitespace, never mid-word. Blank lines are preserved."""
    if not line.strip():
        return [""]

    words = line.split()
    wrapped: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= columns:
            current = candidate
            continue
        if current:
            wrapped.append(current)
        # A single word longer than the column (a long tag or URL) is placed
        # on its own line rather than being cut.
        current = word
    if current:
        wrapped.append(current)
    return wrapped


def paginate(text: str) -> list[list[str]]:
    """Turn source text into pages of already-wrapped lines.

    Explicit `---PAGE---` markers win; beyond them, pages fill to
    `LINES_PER_PAGE`. Keeping the break explicit in the source means a
    section that a citation points at stays on the page the author intended.
    """
    pages: list[list[str]] = []
    current: list[str] = []

    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.strip() == PAGE_BREAK:
            pages.append(current)
            current = []
            continue

        for line in _wrap(raw.rstrip()):
            if len(current) >= LINES_PER_PAGE:
                pages.append(current)
                current = []
            current.append(line)

    if current or not pages:
        pages.append(current)
    return pages


def write_pdf(text: str, destination: Path) -> GeneratedFile:
    """Write `text` as a real, text-extractable PDF."""
    import pypdf
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = pypdf.PdfWriter()

    # One shared font object for the whole document.
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )

    for lines in paginate(text):
        page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

        commands = [
            "BT",
            f"/F1 {FONT_SIZE} Tf",
            f"{MARGIN_LEFT} {MARGIN_TOP} Td",
            f"{LEADING} TL",
        ]
        for line in lines:
            # An empty Tj still advances the line via T*, which is how blank
            # lines survive into the extracted text as paragraph breaks.
            commands.append(f"({_escape(line)}) Tj T*")
        commands.append("ET")

        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("latin-1", errors="replace"))

        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font}
                ),
                NameObject("/ProcSet"): ArrayObject(
                    [NameObject("/PDF"), NameObject("/Text")]
                ),
            }
        )

    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return GeneratedFile(path=destination, size_bytes=len(data))


def write_text(text: str, destination: Path) -> GeneratedFile:
    """Write a source file through unchanged (CSV, TXT, MD)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    destination.write_bytes(data)
    return GeneratedFile(path=destination, size_bytes=len(data))


def read_source(name: str) -> str | None:
    """Read one source document, or None when the corpus is not present."""
    path = (SOURCE_DIR / name).resolve()
    # Seed entries are product configuration, but a path that climbs out of
    # data/ is a mistake worth refusing rather than following.
    if SOURCE_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def build(name: str, destination: Path) -> GeneratedFile | None:
    """Generate one demo file from its source. Returns None if absent.

    Dispatches on the *destination* suffix, so a source text file becomes a
    PDF or stays plain text according to what the catalogue row claims it
    is - a document reported as a PDF must actually be one, or extraction
    would fail in a way that looks like a pipeline bug.
    """
    text = read_source(name)
    if text is None:
        log.warning("Demo source %s is missing; skipping", name)
        return None

    suffix = destination.suffix.lower()
    if suffix == ".pdf":
        return write_pdf(text, destination)
    return write_text(text, destination)


def human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


__all__ = [
    "PAGE_BREAK",
    "SOURCE_DIR",
    "GeneratedFile",
    "build",
    "human_size",
    "paginate",
    "read_source",
    "write_pdf",
    "write_text",
]
