"""Text extraction: file bytes -> plain text, page by page.

Scope is stated rather than implied. Every format either extracts real text
or raises `UnsupportedDocument` naming why; nothing returns a plausible
placeholder. A document the pipeline cannot read must end up visibly
un-indexed, because the alternative is an empty document that the assistant
believes it has read.

PDF and DOCX support depend on optional libraries. They are imported lazily
so the API still boots without them, and `describe_support()` reports what
the running install can actually parse - the same reporting rule the model
layer follows.

Not handled, deliberately:
  - scanned / image-only PDFs. Extraction returns no text and the document
    is marked UNSUPPORTED. OCR and vision belong to the multimodal
    milestone, not here.
  - legacy binary .doc. Needs an external converter (LibreOffice), which is
    a deployment dependency rather than a library.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)


class UnsupportedDocument(Exception):
    """The format holds no text this deployment can read."""


class ExtractionFailed(Exception):
    """The format is supported but this particular file could not be read."""


@dataclass(frozen=True)
class Page:
    """One page of extracted text. `number` is 1-based."""

    number: int
    text: str


@dataclass(frozen=True)
class Extracted:
    """The readable content of one file."""

    pages: list[Page] = field(default_factory=list)

    #: "prose" | "table". Chunking treats tables differently, because a row
    #: split away from its header is unreadable.
    kind: str = "prose"

    #: Column header line, for `kind == "table"`.
    header: str = ""

    @property
    def total_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)

    @property
    def has_text(self) -> bool:
        return any(p.text.strip() for p in self.pages)


# ---------------------------------------------------------------------------
# Optional dependency probes
# ---------------------------------------------------------------------------
def _pypdf():
    try:
        import pypdf
    except ImportError:
        return None
    return pypdf


def _docx():
    try:
        import docx  # python-docx
    except ImportError:
        return None
    return docx


#: Suffixes this module knows about.
TEXT_SUFFIXES = {".txt", ".md", ".log"}
TABLE_SUFFIXES = {".csv", ".tsv"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}

_IMAGE_REASON = (
    "Images carry no text layer. Reading one needs OCR or a vision model, "
    "which this deployment does not have yet."
)

#: Accepted for storage, never extractable here. The reason is shown to the
#: user rather than being swallowed into a generic failure.
NO_TEXT_REASON = {
    ".doc": (
        "Legacy .doc is a binary Word format that needs an external "
        "converter. Save it as .docx or .pdf and upload again."
    ),
    ".png": _IMAGE_REASON,
    ".jpg": _IMAGE_REASON,
    ".jpeg": _IMAGE_REASON,
}


def describe_support() -> dict[str, object]:
    """What this install can actually extract. Reported by /api/health."""
    return {
        "text": sorted(TEXT_SUFFIXES | TABLE_SUFFIXES),
        "pdf": _pypdf() is not None,
        "docx": _docx() is not None,
        "images": False,
    }


def extractable_suffixes() -> set[str]:
    suffixes = set(TEXT_SUFFIXES) | set(TABLE_SUFFIXES)
    if _pypdf() is not None:
        suffixes |= PDF_SUFFIXES
    if _docx() is not None:
        suffixes |= DOCX_SUFFIXES
    return suffixes


# ---------------------------------------------------------------------------
# Per-format readers
# ---------------------------------------------------------------------------
def _decode(data: bytes) -> str:
    """Best-effort decode. Industrial exports are rarely tidy UTF-8."""
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 cannot raise, so reaching here means something stranger still.
    return data.decode("utf-8", errors="replace")


def _normalise(text: str) -> str:
    """Tidy whitespace without destroying paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]

    out: list[str] = []
    blank = 0
    for line in lines:
        if line:
            blank = 0
            out.append(line)
        else:
            blank += 1
            if blank <= 1:  # collapse runs of blank lines down to one
                out.append("")
    return "\n".join(out).strip()


def _extract_text(data: bytes) -> Extracted:
    return Extracted(pages=[Page(number=1, text=_normalise(_decode(data)))])


def _extract_table(data: bytes, delimiter: str) -> Extracted:
    """Keep a delimited file readable by preserving its header.

    A CSV chunked as raw text loses its header after the first chunk, and
    every later chunk becomes a wall of unlabelled values. Rows are
    reassembled as `column: value` pairs instead, which both BM25 and the
    model can read on their own.
    """
    text = _decode(data)

    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise ExtractionFailed(f"Could not parse the delimited file: {exc}") from exc

    if not rows:
        return Extracted(pages=[], kind="table")

    header = [h.strip() for h in rows[0]]
    lines: list[str] = []

    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        pairs = []
        for index, cell in enumerate(row):
            if not cell.strip():
                continue
            name = header[index] if index < len(header) else f"column{index + 1}"
            pairs.append(f"{name}: {cell.strip()}")
        if pairs:
            lines.append(" | ".join(pairs))

    return Extracted(
        pages=[Page(number=1, text="\n".join(lines))],
        kind="table",
        header=delimiter.join(header),
    )


def _extract_pdf(data: bytes) -> Extracted:
    pypdf = _pypdf()
    if pypdf is None:
        raise UnsupportedDocument(
            "PDF text extraction needs the 'pypdf' package, which is not "
            "installed. Run: pip install -r requirements.txt"
        )

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide family
        raise ExtractionFailed(f"Could not open the PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        # An empty password unlocks a surprising number of "protected" files.
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedDocument(
                "The PDF is password protected and cannot be read."
            ) from exc

    pages: list[Page] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page must not lose the rest
            log.warning("PDF page %s could not be extracted: %s", number, exc)
            raw = ""
        pages.append(Page(number=number, text=_normalise(raw)))

    return Extracted(pages=pages)


def _extract_docx(data: bytes) -> Extracted:
    docx = _docx()
    if docx is None:
        raise UnsupportedDocument(
            "DOCX text extraction needs the 'python-docx' package, which is "
            "not installed. Run: pip install -r requirements.txt"
        )

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionFailed(f"Could not open the DOCX file: {exc}") from exc

    blocks = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))

    # DOCX has no fixed pagination - where a page breaks depends on the
    # renderer - so reporting page numbers would be inventing them.
    return Extracted(pages=[Page(number=1, text=_normalise("\n\n".join(blocks)))])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def extract(data: bytes, suffix: str) -> Extracted:
    """Extract text from `data`, dispatching on the file suffix.

    Raises `UnsupportedDocument` when the format cannot be read at all, and
    `ExtractionFailed` when it should have been readable but was not.
    """
    suffix = suffix.lower()

    if suffix in TEXT_SUFFIXES:
        return _extract_text(data)
    if suffix in TABLE_SUFFIXES:
        return _extract_table(data, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix in PDF_SUFFIXES:
        return _extract_pdf(data)
    if suffix in DOCX_SUFFIXES:
        return _extract_docx(data)
    if suffix in NO_TEXT_REASON:
        raise UnsupportedDocument(NO_TEXT_REASON[suffix])

    raise UnsupportedDocument(f"No text extractor for '{suffix}' files.")


__all__ = [
    "Extracted",
    "ExtractionFailed",
    "Page",
    "UnsupportedDocument",
    "describe_support",
    "extract",
    "extractable_suffixes",
]
