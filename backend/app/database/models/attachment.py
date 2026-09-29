"""Files attached to a chat turn.

Distinct from `Document` on purpose. A document is knowledge-base material:
it is indexed, retrievable, folder-scoped and shared. An attachment is a
picture someone pasted into one question - it belongs to that person and
that turn, and putting every screenshot into the searchable corpus would
poison retrieval for everyone in the folder.

So attachments are private to their uploader, never indexed, and never
retrievable. They exist so a turn can carry an image to a vision model.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User


class Attachment(Base, TimestampMixin):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # The uploader. An attachment is readable by nobody else - there is no
    # folder, no sharing and no scope widening, because there is no case
    # where someone else's chat image should reach your prompt.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relative to the attachments directory under the upload root.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Set for attachments that are documents rather than images. The bytes
    #: are extracted, chunked and indexed like any upload, but the resulting
    #: document is bound to one conversation and retrievable only there.
    #: Images have no document: they are sent to the model inline and there
    #: is nothing to search.
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Set once the attachment has been sent with a turn. Kept rather than
    # deleted so an old message's thumbnail still resolves.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship()

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")
