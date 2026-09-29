"""Files attached to a chat turn.

Separate from `/documents` deliberately. Attaching a file to ask about it is
not the same act as adding it to the knowledge base: the second is shared,
retrievable by everyone in the folder, and permanent. Routing every
screenshot into the corpus would degrade retrieval for the whole team.

Two kinds, handled differently:

  images      sent to the model inline and never indexed. There is nothing
              to search in a screenshot, and a vision model reads it
              directly.
  documents   extracted, chunked and indexed like any upload - but the
              resulting document is bound to the conversation it was sent
              in and is retrievable only there. Not in the shared corpus,
              not in the uploader's other chats.

That second case is what makes "here is a PDF, what does section 4 say"
work without the PDF becoming something the assistant answers everyone
else from. The uploader can promote it into the knowledge base afterwards,
which is a deliberate act with its own confirmation.

Either way an attachment is private to its uploader and unreachable by
another user - not through a listing, not by guessing an id.
"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from datetime import date

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import AttachmentOut
from app.core.config import settings
from app.database.models import Attachment, Document
from app.database.models.document import DocumentStatus
from app.rag.indexer import index_document_by_id
from app.services.access import PERSONAL_FOLDER
from app.models import get_gateway
from app.models.router import ROLE_VISION, resolve
from app.services import audit

router = APIRouter(prefix="/attachments", tags=["chat"])

#: Smaller than the document limit. These are pasted into a prompt as
#: base64, which inflates them by a third and counts against the model's
#: context - a 20 MB photograph is not a question.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log"}

#: Attachments that get extracted and indexed rather than pasted into the
#: prompt. The same extractors the Documents page uses, so a PDF behaves the
#: same way in both places - it was previously refused here outright, which
#: sent people to the knowledge base to ask a one-off question.
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".log"}

ALLOWED_SUFFIXES = IMAGE_SUFFIXES | TEXT_SUFFIXES | DOCUMENT_SUFFIXES

#: A chat-scoped document exists before its conversation does - the file is
#: uploaded while the user is still typing, and a brand new chat has no id
#: until the message is sent. It is parked under this prefix until then, so
#: it is never in the corpus and never matches a real conversation.
PENDING_PREFIX = "pending:"

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def attachment_dir() -> Path:
    path = settings.upload_path / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def owned_attachment(db, user, attachment_id: str) -> Attachment:
    """Fetch an attachment belonging to `user`, or 404.

    Ownership is the whole access model here. A 404 rather than a 403 so an
    id cannot be probed for existence.
    """
    row = db.get(Attachment, attachment_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return row


def _human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.1f} KB"


def _chat_document(
    db,
    user,
    *,
    attachment_id: str,
    name: str,
    suffix: str,
    size_bytes: int,
    contents: bytes,
) -> Document:
    """Store an attached document so it can be indexed and asked about.

    The bytes are written into the documents area rather than the
    attachments area, because from here on this is a document: the same
    extractor reads it, the same chunker splits it, and the same retriever
    finds it. What differs is the scope, and that is one column.

    It is parked under a pending conversation id. The upload happens while
    the user is still typing and a new chat has no id yet, so binding waits
    until the message is actually sent. Until then it matches no
    conversation, which means it is retrievable by nobody - including its
    own uploader.
    """
    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    safe_stem = _SAFE_NAME.sub("_", Path(name).stem)[:80] or "file"
    stored_name = f"{document_id}__{safe_stem}{suffix}"

    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / stored_name).write_bytes(contents)

    doc = Document(
        id=document_id,
        name=name,
        type=suffix.lstrip(".").upper(),
        size=_human_size(size_bytes),
        size_bytes=size_bytes,
        uploaded_date=date.today(),
        status=DocumentStatus.PROCESSING,
        chunk_count=0,
        folder=PERSONAL_FOLDER,
        owner_id=user.id,
        is_confidential_owner_only=False,
        conversation_id=f"{PENDING_PREFIX}{attachment_id}",
        storage_path=stored_name,
        section="",
        page=1,
        excerpt="",
    )
    db.add(doc)
    return doc


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> AttachmentOut:
    original_name = Path(file.filename or "attachment").name
    suffix = Path(original_name).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Cannot attach '{suffix}' files. Allowed: "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))}. To add a PDF or Word "
            "document to the knowledge base, upload it on the Documents page.",
        )

    contents = await file.read()
    if len(contents) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB "
            "limit. Images are sent to the model inline, so they have to be small.",
        )

    attachment_id = f"att-{uuid.uuid4().hex[:12]}"
    safe_stem = _SAFE_NAME.sub("_", Path(original_name).stem)[:80] or "file"
    stored_name = f"{attachment_id}__{safe_stem}{suffix}"
    (attachment_dir() / stored_name).write_bytes(contents)

    content_type = CONTENT_TYPES.get(suffix, file.content_type or "text/plain")

    row = Attachment(
        id=attachment_id,
        user_id=user.id,
        name=original_name,
        content_type=content_type,
        size_bytes=len(contents),
        storage_path=stored_name,
    )
    db.add(row)

    # A document gets extracted and indexed; an image does not. Both are
    # stored either way, so the thumbnail and the download keep working.
    indexable = suffix in DOCUMENT_SUFFIXES and suffix not in IMAGE_SUFFIXES
    if indexable:
        doc = _chat_document(
            db,
            user,
            attachment_id=attachment_id,
            name=original_name,
            suffix=suffix,
            size_bytes=len(contents),
            contents=contents,
        )
        row.document_id = doc.id

    audit.record(
        db,
        user_id=user.id,
        action="attachment.upload",
        resource_type="attachment",
        resource_id=attachment_id,
        detail={"filename": original_name, "bytes": len(contents)},
    )
    db.commit()
    db.refresh(row)

    # Indexed inline rather than in the background, because the very next
    # thing the user does is ask a question about it. A background job would
    # race the first turn and the answer would be "I could not find that in
    # your documents", which is worse than a moment's wait on upload.
    if row.document_id:
        index_document_by_id(row.document_id)
        db.expire_all()

    return _serialise(row)


@router.get("/{attachment_id}")
def download_attachment(attachment_id: str, user: CurrentUser, db: DbSession):
    """Return the attachment's bytes, for the thumbnail in a message."""
    row = owned_attachment(db, user, attachment_id)

    path = attachment_dir() / row.storage_path
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "The attachment is no longer stored.")

    # Inline is safe only because the type is constrained to images and
    # plain text at upload; anything else is served as a download.
    inline = row.is_image
    return FileResponse(
        path,
        media_type=row.content_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'inline; filename="{_SAFE_NAME.sub("_", row.name)}"'
                if inline
                else f'attachment; filename="{_SAFE_NAME.sub("_", row.name)}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _serialise(row: Attachment) -> AttachmentOut:
    """Report whether this attachment can actually be read by the model.

    An image is only useful if a vision-capable model is configured, and the
    user should learn that when they attach it rather than from an answer
    that quietly ignores the picture.
    """
    gateway = get_gateway()
    readable = True
    note = ""

    if row.is_image:
        route = resolve(ROLE_VISION)
        if route.degraded or not gateway.model_accepts_images(route.model):
            readable = False
            note = (
                "No vision model is configured, so this image cannot be read. "
                "Set MODEL_VISION in .env to a model that accepts images."
            )
        else:
            note = f"Will be read by {route.model}."
    elif row.document_id:
        note = (
            "Indexed for this chat only. It is searchable here, and not in "
            "the knowledge base or your other chats."
        )
    else:
        note = "Text attachments are included in the prompt as-is."

    return AttachmentOut(
        id=row.id,
        name=row.name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        is_image=row.is_image,
        readable=readable,
        note=note,
        document_id=row.document_id,
    )
