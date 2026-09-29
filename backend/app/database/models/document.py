"""Documents in the knowledge base."""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.chunk import DocumentChunk
    from app.database.models.user import User


class DocumentStatus:
    """Document lifecycle.

        READY -> PROCESSING -> INDEXED
                              -> FAILED
                              -> UNSUPPORTED

    A document reaches INDEXED only once text has actually been extracted
    and chunks exist in `document_chunks`. The two terminal failure states
    are distinct on purpose:

      FAILED       - extraction or chunking raised. Worth retrying.
      UNSUPPORTED  - the format holds no extractable text in this
                     deployment (scanned images, legacy .doc). Retrying
                     changes nothing until OCR or vision lands (Phase 13).

    Neither is reported as INDEXED, and neither leaves stale chunks behind.
    """

    READY = "Ready for indexing"
    PROCESSING = "Processing"
    INDEXED = "Indexed"
    FAILED = "Indexing failed"
    UNSUPPORTED = "No extractable text"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="PDF")
    size: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    uploaded_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.READY
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Access scoping.
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="Personal Uploads")
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_confidential_owner_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    #: Set when the document was attached to a chat rather than uploaded to
    #: the knowledge base. It is indexed and retrievable exactly like any
    #: other document, but only inside that one conversation - not in the
    #: shared corpus, not in the uploader's other chats.
    #:
    #: This is what makes "ask a question about this PDF" possible without
    #: the file becoming part of what the assistant answers from for
    #: everyone. Clearing it is how such a document is promoted into the
    #: knowledge base later.
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    @property
    def visibility(self) -> str:
        """Where this document sits: personal, restricted, or shared.

        Derived from the folder rather than stored, because the folder is
        what the access rules read. A stored copy could disagree with it,
        and a visibility label that disagrees with the actual permission is
        worse than no label.
        """
        # Local import: app.services.access imports this module.
        from app.services.access import PERSONAL_FOLDER, RESTRICTED_FOLDER

        if self.folder == PERSONAL_FOLDER:
            return "personal"
        if self.folder == RESTRICTED_FOLDER:
            return "restricted"
        return "shared"

    # Where the bytes live on disk, relative to the configured upload dir.
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Preview metadata used by the citation/preview UI. For seeded demo
    # documents this is authored content; for uploads it stays empty until
    # the document is indexed, at which point it is overwritten with the
    # real opening passage of the extracted text.
    section: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- Indexing -------------------------------------------------------
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Why the last indexing attempt did not produce a searchable document.
    # Surfaced to the user verbatim - a document that silently failed to
    # index is a document the assistant will silently fail to cite.
    index_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # How many characters of text extraction actually recovered. Zero on an
    # INDEXED document is impossible by construction; zero elsewhere is the
    # honest answer to "why did this not index?".
    extracted_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # True when every chunk carries a vector from the active embedding
    # model. False means the document is searchable lexically only.
    is_semantically_indexed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    @property
    def has_stored_file(self) -> bool:
        """Whether there are bytes on disk behind this row.

        Seeded catalogue entries have none, so there is nothing to index.
        The API exposes this rather than the storage path, which is a server
        detail the client has no business knowing.
        """
        return bool(self.storage_path)

    owner: Mapped["User | None"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.position",
    )
