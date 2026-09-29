"""Document management and indexing.

Upload stores the file on disk, records a row, and - unless auto-indexing is
switched off - queues it for indexing. Indexing is what turns a stored file
into something retrieval can search: text extraction, chunking, and vectors
when an embedding provider is configured (see `app/rag/`).

Indexing runs as a background task rather than inside the upload request. A
200-page PDF sent through an embedding endpoint takes minutes, and blocking
an HTTP worker for that would stall the API. The document therefore reports
`Processing` until the run finishes, and the client polls. Nothing reports
`Indexed` before chunks exist.
"""

import re
import uuid
from datetime import date
from pathlib import Path

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import (
    DocumentChunkOut,
    DocumentOut,
    DocumentUpdate,
    IndexResultOut,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.database.models import Document, DocumentChunk, DocumentStatus, Notification, User
from app.rag import extraction
from app.rag.indexer import index_document_by_id
from app.services import audit
from app.services.access import (
    PERSONAL_FOLDER,
    RESTRICTED_FOLDER,
    publish_error,
    can_access_document,
    can_edit_document,
    confidential_change_error,
    folder_move_error,
    is_administrator,
    owner_change_error,
    visible_documents_query,
)

router = APIRouter(prefix="/documents", tags=["documents"])

#: Where a document goes when its confidential classification is lifted.
#: It cannot return to the uploader's personal space - it has been read by
#: others while classified, and silently un-sharing it would leave people
#: with citations they can no longer open.
GENERAL_FOLDER = "All Units"
log = get_logger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".doc",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _upload_dir() -> Path:
    path = settings.upload_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


@router.get("", response_model=list[DocumentOut])
def list_documents(user: CurrentUser, db: DbSession) -> list[Document]:
    """Only documents this user is scoped to - filtered in SQL, not in the UI.

    Chat-scoped documents are included here, unlike in retrieval. They are
    still the caller's own - the permission rules are unchanged - and this
    is the one place they need to be visible: a file attached to a chat is
    invisible everywhere else, so without this the user could never find it
    to promote it into their knowledge base or delete it.
    """
    return list(db.scalars(visible_documents_query(user, include_chat_scoped=True)))


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, user: CurrentUser, db: DbSession) -> Document:
    return _authorised_document(db, user, document_id, audit_denial=True)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> Document:
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    doc_id = f"doc-{uuid.uuid4().hex[:12]}"

    # Never trust the client-supplied filename as a path.
    safe_stem = _SAFE_NAME.sub("_", Path(original_name).stem)[:80] or "file"
    stored_name = f"{doc_id}__{safe_stem}{suffix}"
    destination = _upload_dir() / stored_name
    destination.write_bytes(contents)

    # Whether this file will ever be searchable is knowable now, from its
    # format alone - so say so at upload time instead of letting the user
    # discover it when the assistant cannot find the document.
    will_index = settings.rag_auto_index and suffix in extraction.extractable_suffixes()

    doc = Document(
        id=doc_id,
        name=original_name,
        type=suffix.lstrip(".").upper(),
        size=_human_size(len(contents)),
        size_bytes=len(contents),
        uploaded_date=date.today(),
        status=DocumentStatus.PROCESSING if will_index else DocumentStatus.READY,
        chunk_count=0,
        # Private by default, for everybody - an administrator's upload
        # included, and anything attached in a chat. Sharing is then an act
        # the uploader takes deliberately rather than a side effect of who
        # happened to upload the file.
        folder=PERSONAL_FOLDER,
        owner_id=user.id,
        is_confidential_owner_only=False,
        storage_path=stored_name,
        section="",
        page=1,
        # Filled in by the indexer from the real extracted text. Left empty
        # until then rather than inventing a preview.
        excerpt="",
    )
    db.add(doc)

    db.add(
        Notification(
            id=f"notif-{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            title="Document uploaded",
            description=(
                f"{original_name} stored. Indexing now."
                if will_index
                else f"{original_name} stored. Ready for indexing."
            ),
            read=False,
        )
    )

    audit.record(
        db,
        user_id=user.id,
        action="document.upload",
        resource_type="document",
        resource_id=doc_id,
        detail={"filename": original_name, "bytes": len(contents), "auto_index": will_index},
    )

    db.commit()
    db.refresh(doc)

    if will_index:
        background.add_task(index_document_by_id, doc_id)

    return doc


@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    user: CurrentUser,
    db: DbSession,
) -> Document:
    """Change a document's metadata.

    Three of the four editable fields decide who can retrieve this document,
    so each is authorised separately and a refusal names the field. The
    request is all-or-nothing: a caller who may rename but not reclassify
    gets a 403 for the whole call rather than a silent partial write that
    leaves them believing the reclassification took.
    """
    doc = _authorised_document(db, user, document_id)

    if not can_edit_document(user, doc):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only edit your own uploads.",
        )

    # Every field that `changes` can name has to appear here: the audit entry
    # is built as {k: before[k] for k in changes}, so a field changed but not
    # snapshotted raises rather than logging.
    before = {
        "name": doc.name,
        "folder": doc.folder,
        "is_confidential_owner_only": doc.is_confidential_owner_only,
        "owner_id": doc.owner_id,
        "conversation_id": doc.conversation_id,
    }
    changes: dict[str, object] = {}

    if payload.name is not None and payload.name.strip() != doc.name:
        name = payload.name.strip()
        if not name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "A document name cannot be empty."
            )
        # Display name only. The file on disk keeps the storage name it was
        # written under, so renaming can never orphan the bytes.
        changes["name"] = name

    if payload.folder is not None and payload.folder != doc.folder:
        error = folder_move_error(user, payload.folder)
        if error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, error)
        # Separate from the folder rule above: an administrator may file a
        # shared document anywhere, but may not publish somebody's personal
        # one on their behalf. Without this, "an administrator cannot read
        # your personal files" would hold only until they published one.
        error = publish_error(user, doc, payload.folder)
        if error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, error)
        changes["folder"] = payload.folder

    if (
        payload.is_confidential_owner_only is not None
        and payload.is_confidential_owner_only != doc.is_confidential_owner_only
    ):
        error = confidential_change_error(user)
        if error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, error)
        changes["is_confidential_owner_only"] = payload.is_confidential_owner_only

        # Access decisions read the folder, so the flag has to move the
        # document rather than sit beside it. Two mechanisms answering "who
        # can see this" is how a file ends up visible under one rule and
        # hidden under the other.
        if "folder" not in changes:
            changes["folder"] = (
                RESTRICTED_FOLDER
                if payload.is_confidential_owner_only
                else GENERAL_FOLDER
            )

    if payload.promote_from_chat and doc.conversation_id:
        # The uploader's call alone. An administrator cannot see a personal
        # document to begin with, and promoting somebody's chat file into a
        # searchable corpus is exactly the kind of decision that has to stay
        # with the person who attached it.
        if doc.owner_id != user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the person who attached a file can keep it in their "
                "knowledge base.",
            )
        changes["conversation_id"] = None

    if payload.owner_id is not None and payload.owner_id != doc.owner_id:
        error = owner_change_error(user)
        if error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, error)
        if db.get(User, payload.owner_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"No user '{payload.owner_id}' to transfer this document to.",
            )
        changes["owner_id"] = payload.owner_id

    if not changes:
        return doc  # nothing to do; not an error

    for field, value in changes.items():
        setattr(doc, field, value)

    # Chunks are reached through their document, so a move or a
    # reclassification takes effect on retrieval immediately. No re-index.
    audit.record(
        db,
        user_id=user.id,
        action="document.update",
        resource_type="document",
        resource_id=document_id,
        detail={
            "fields": sorted(changes),
            "before": {k: before[k] for k in changes},
            "after": {k: changes[k] for k in changes},
        },
    )
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/download")
def download_document(document_id: str, user: CurrentUser, db: DbSession) -> FileResponse:
    """Return the original uploaded file.

    Always as an attachment, never inline. Uploaded files are untrusted
    content, and serving one inline from the API origin turns any document a
    user can upload into stored XSS against everyone who opens it. The
    generic content type stops a browser sniffing its way to the same
    outcome.
    """
    doc = _authorised_document(db, user, document_id)

    if not doc.storage_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This document is a catalogue entry with no stored file behind it.",
        )

    path = _upload_dir() / doc.storage_path
    if not path.is_file():
        raise HTTPException(
            status.HTTP_410_GONE,
            "The stored file is missing from disk. Upload it again.",
        )

    audit.record(
        db,
        user_id=user.id,
        action="document.download",
        resource_type="document",
        resource_id=document_id,
        detail={"filename": doc.name},
    )
    db.commit()

    # RFC 5987 encoding: a document name can contain quotes, newlines or
    # non-ASCII, all of which would otherwise let the name break out of the
    # header it is embedded in.
    ascii_fallback = _SAFE_NAME.sub("_", doc.name) or "document"
    disposition = (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(doc.name, safe='')}"
    )

    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{document_id}/index",
    response_model=IndexResultOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def index_document_endpoint(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
) -> IndexResultOut:
    """Queue a document for (re-)indexing.

    Re-indexing an already-indexed document is supported and is the way to
    add vectors after an embedding provider is configured, or to pick up a
    chunking change. The old chunks are replaced rather than appended to.
    """
    doc = _authorised_document(db, user, document_id)

    if not can_edit_document(user, doc):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only index your own uploads.",
        )

    if not doc.storage_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document has no stored file - it is a catalogue entry only, "
            "so there is nothing to index.",
        )

    doc.status = DocumentStatus.PROCESSING
    doc.index_error = ""

    audit.record(
        db,
        user_id=user.id,
        action="document.index",
        resource_type="document",
        resource_id=document_id,
        detail={"filename": doc.name},
    )
    db.commit()
    db.refresh(doc)

    background.add_task(index_document_by_id, document_id)

    return IndexResultOut(
        document=DocumentOut.model_validate(doc),
        queued=True,
        status=DocumentStatus.PROCESSING,
        message=(
            "Indexing started. Poll this document until its status leaves "
            "'Processing'."
        ),
    )


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkOut])
def list_document_chunks(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentChunk]:
    """The indexed passages of a document - what retrieval actually searches.

    Exposed so the corpus is inspectable. "The assistant did not find it" and
    "the text was never extracted" look identical from the chat window, and
    only one of them is a retrieval problem.
    """
    _authorised_document(db, user, document_id)

    limit = max(1, min(limit, 200))
    return list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.position)
            .offset(max(0, offset))
            .limit(limit)
        )
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, user: CurrentUser, db: DbSession) -> None:
    doc = db.get(Document, document_id)
    if doc is None or not can_access_document(user, doc):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    if not can_edit_document(user, doc):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own uploads.")

    if doc.storage_path:
        stored = _upload_dir() / doc.storage_path
        if stored.is_file():
            stored.unlink()

    audit.record(
        db,
        user_id=user.id,
        action="document.delete",
        resource_type="document",
        resource_id=document_id,
        detail={"filename": doc.name, "chunks": doc.chunk_count},
    )
    # Chunks go with the document (cascade), so a deleted document cannot be
    # retrieved from afterwards.
    db.delete(doc)
    db.commit()


def _authorised_document(
    db: DbSession, user, document_id: str, *, audit_denial: bool = False
) -> Document:
    """Fetch a document the user may see, or 404.

    Deliberately 404 and not 403: a 403 would confirm the document exists.
    """
    doc = db.get(Document, document_id)
    if doc is not None and can_access_document(user, doc):
        return doc

    if doc is not None and audit_denial:
        audit.record(
            db,
            user_id=user.id,
            action="document.access_denied",
            resource_type="document",
            resource_id=document_id,
            status="denied",
        )
        db.commit()

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
