"""Document access scoping.

This used to happen in the browser, which meant every user's data was
actually shipped to every client and merely hidden. Filtering now happens
in the SQL query so unauthorised rows never leave the server.

Caveat: without authentication the caller's identity is still asserted by a
header (see app/api/dependencies/current_user.py). This is a correct *shape*
for access control, not yet a security guarantee.
"""

from sqlalchemy import Select, and_, or_, select

from app.core.security import AccessLevel
from app.database.models import Document, User

#: Every document is in exactly one of four places, and the folder alone
#: decides which. There is deliberately no second flag: two mechanisms for
#: one question is how a document ends up visible under one rule and hidden
#: under the other.
#:
#:   PERSONAL_FOLDER    the uploader's own space. Nobody else, including
#:                      administrators. Assigning it to somebody grants
#:                      nothing - ownership is what grants here.
#:   RESTRICTED_FOLDER  owner clearance only. One folder, not a per-document
#:                      flag, so "who can see this" is answerable by looking
#:                      at where it is filed.
#:   PUBLIC_FOLDERS     published BIS material. Everyone, visitors included.
#:   anything else      an internal desk folder. Visible to the staff
#:                      assigned to it.
PERSONAL_FOLDER = "Personal Uploads"
RESTRICTED_FOLDER = "BIS Internal"

#: The published knowledge base: what any member of the public may read and
#: the assistant may cite to them. Everything here is public BIS material.
#: A visitor's access is this list itself, read at request time - not a copy
#: stamped onto their row when they arrived - so adding a folder here
#: reaches every visitor at once, and removing one withdraws it at once.
PUBLIC_FOLDERS = (
    "Certification Schemes",
    "Hallmarking",
    "Standards & QCOs",
    "Laboratories",
    "Consumer Help",
    "BIS Act & Rules",
)


def is_guest(user: User) -> bool:
    """An anonymous helpdesk visitor rather than a member of staff."""
    return user.access_level == AccessLevel.PUBLIC


def _shared_folders(user: User) -> list[str]:
    """Folders that genuinely grant access when assigned to a user.

    Neither special folder can be granted by assignment. Personal access
    comes from ownership and restricted access from clearance, so listing
    either in `assigned_folders` - by an admin's mistake or a typo - must
    hand out nothing.

    The public folders are everyone's: a member of staff never sees less
    than an anonymous visitor. Assignment only matters for the internal desk
    folders on top of them. A visitor's grant is the public set and only the
    public set, whatever their row says, so no stored value can widen it.
    """
    if is_guest(user):
        return list(PUBLIC_FOLDERS)
    assigned = [
        f
        for f in (user.assigned_folders or [])
        if f not in (PERSONAL_FOLDER, RESTRICTED_FOLDER, *PUBLIC_FOLDERS)
    ]
    return [*PUBLIC_FOLDERS, *assigned]


def visible_documents_query(
    user: User,
    *,
    conversation_id: str | None = None,
    include_chat_scoped: bool = False,
) -> Select:
    """Documents `user` is allowed to see.

    Chat-scoped documents are excluded by default, which is the important
    half of the rule. A file attached to one conversation is indexed and
    answerable *there*; it is not part of the corpus, so it must not surface
    in a different chat, in another user's search, or in the knowledge base
    at large. Passing `conversation_id` opts that one chat's documents in;
    `include_chat_scoped` is for listing a user their own files, where the
    point is to show what they have so they can promote it.

    Owner clearance is broad but no longer total. It used to return every
    row, which meant an administrator silently read every engineer's private
    uploads - and, worse, the assistant would quote them back in an answer,
    paraphrased, where nobody thinks to re-check permissions.

    A personal document is now reachable by exactly one person: whoever
    uploaded it. That is what makes "personal" a claim the UI can honestly
    make, and it is checked in SQL so unauthorised rows never leave the
    server.
    """
    stmt = select(Document)

    # Narrowing only: applied on top of the permission rules below, never
    # instead of them. A chat-scoped document is still subject to every
    # ownership and folder check that governs any other document.
    if not include_chat_scoped:
        if conversation_id:
            stmt = stmt.where(
                or_(
                    Document.conversation_id.is_(None),
                    Document.conversation_id == conversation_id,
                )
            )
        else:
            stmt = stmt.where(Document.conversation_id.is_(None))

    if user.access_level == AccessLevel.OWNER:
        # Everything except other people's personal space. A chat-scoped
        # document is personal to whoever attached it, so it is covered by
        # the same rule rather than needing one of its own.
        return stmt.where(
            or_(
                Document.folder != PERSONAL_FOLDER,
                Document.owner_id == user.id,
            )
        ).order_by(Document.created_at.desc())

    folders = _shared_folders(user)

    # Their own uploads, plus anything shared into a folder they are on.
    grants = [Document.owner_id == user.id]
    if folders:
        grants.append(
            and_(
                Document.folder.in_(folders),
                Document.folder != PERSONAL_FOLDER,
            )
        )

    return (
        stmt.where(
            Document.folder != RESTRICTED_FOLDER,
            or_(*grants),
        )
        .order_by(Document.created_at.desc())
    )


def is_personal(document: Document) -> bool:
    return document.folder == PERSONAL_FOLDER


def is_restricted(document: Document) -> bool:
    return document.folder == RESTRICTED_FOLDER


def can_access_document(user: User, document: Document) -> bool:
    """The row-level twin of `visible_documents_query`. Keep them in step."""
    if is_restricted(document):
        return user.access_level == AccessLevel.OWNER

    if is_personal(document):
        # No administrator override. This is the whole point.
        return document.owner_id == user.id

    if user.access_level == AccessLevel.OWNER:
        return True
    if document.owner_id == user.id:
        return True
    return document.folder in _shared_folders(user)


# ---------------------------------------------------------------------------
# Mutation rules
#
# Reading a document and changing it are different questions, and since
# Phase 8 the second one is the dangerous half. Filing a document into a
# folder grants everyone assigned to that folder the ability to retrieve its
# contents through the assistant - paraphrased into an answer, where nobody
# thinks to re-check permissions. So "may this user file a document here?"
# is an access-control decision, and it belongs next to the read rules
# rather than inline in a route handler.
#
# Because `Personal Uploads` is a per-user namespace rather than a shared
# folder, moving *out* of it is the act of sharing a document and moving
# back into it is the act of withdrawing it. That is the entire sharing
# mechanism, and it falls out of the existing model rather than needing one
# of its own.
#
# These return a reason string rather than a bare bool wherever a refusal is
# possible, because the API has to tell the user why. A silent no is how
# people conclude a feature is broken.
# ---------------------------------------------------------------------------
def is_administrator(user: User) -> bool:
    """Owner clearance - the stand-in for an admin role until Phase 16."""
    return user.access_level == AccessLevel.OWNER


def can_edit_document(user: User, document: Document) -> bool:
    """Whether `user` may change this document's metadata at all.

    An administrator cannot edit somebody else's personal document. They
    cannot read it either, so in practice the lookup 404s first - but the
    rule is stated here rather than left to depend on that, because a future
    caller that fetches a document some other way would otherwise inherit an
    override this model does not grant.
    """
    if is_personal(document) and document.owner_id != user.id:
        return False
    return is_administrator(user) or document.owner_id == user.id


def assignable_folders(user: User) -> list[str]:
    """Folders `user` may file a document into.

    Administrators are unrestricted and get an empty list; callers check
    `is_administrator` first. Everyone else may file into a folder they are
    already a member of, or back into their personal namespace. They cannot
    invent a folder and cannot push a document at a team they are not on.
    """
    if is_administrator(user):
        return []
    # A visitor may keep their own files, but filing into a public folder
    # would publish to every other visitor through the assistant's answers.
    if is_guest(user):
        return [PERSONAL_FOLDER]
    # Reading the public folders is everyone's; publishing into them puts a
    # document in front of every visitor as an authoritative BIS source, so
    # that stays with administrator clearance. Staff file into their desks.
    return [
        PERSONAL_FOLDER,
        *(f for f in _shared_folders(user) if f not in PUBLIC_FOLDERS),
    ]


def publish_error(user: User, document: Document, folder: str) -> str | None:
    """Why `user` may not move this document into `folder`, or None.

    Publishing is the act that matters here: filing a document out of a
    personal space into a shared folder is what lets everyone assigned to
    that folder retrieve its contents through the assistant, paraphrased
    into an answer where nobody re-checks permissions.

    So only the uploader may publish their own personal document. An
    administrator may withdraw a shared document - back to the uploader's
    personal space, or into the restricted folder - but may not publish one
    on somebody's behalf. Without that rule "an administrator cannot read
    your personal files" would be true only until they published one and
    read it in the next request.
    """
    if is_personal(document) and folder != PERSONAL_FOLDER:
        if document.owner_id != user.id:
            return (
                "Only the person who uploaded a personal document can share "
                "it. Ask them to publish it."
            )
    return None


def folder_move_error(user: User, folder: str) -> str | None:
    """Why `user` may not file a document into `folder`, or None if they may."""
    if not folder or not folder.strip():
        return "A folder name cannot be empty."

    # Administrators may file anywhere, including into a folder that does not
    # exist yet - that is how a new folder comes into being while folders are
    # still strings rather than rows.
    if is_administrator(user):
        return None

    allowed = assignable_folders(user)
    if folder not in allowed:
        return (
            f"You are not assigned to '{folder}', so you cannot file a document "
            f"there. Folders available to you: {', '.join(allowed)}."
        )
    return None


def confidential_change_error(user: User) -> str | None:
    """Only owner clearance may hide a document from everyone else.

    Retained because callers still speak in terms of a confidential flag.
    The flag is now a mirror of the folder - see `documents.py` - and the
    folder is what access decisions read.
    """
    if is_administrator(user):
        return None
    return (
        "Only owner clearance can mark a document confidential. Marking one "
        "removes it from every other user's search results."
    )


def owner_change_error(user: User) -> str | None:
    """Only owner clearance may hand a document to a different user."""
    if is_administrator(user):
        return None
    return "Only owner clearance can transfer ownership of a document."


def known_folders(session) -> list[str]:
    """Every folder currently in use, plus the personal namespace.

    Folders are free-text strings on documents and on users rather than rows
    in a table, so the set has to be derived. This is the single place that
    derivation happens - the Documents page and any later admin surface read
    it from here instead of each hard-coding a list that drifts out of sync.

    Known limitation while folders remain strings: a typo creates a new
    folder silently rather than erroring, which quietly changes who can
    retrieve the document. Promoting folders to a real entity (Phase 16,
    alongside RBAC) means rewriting this function and nothing else.
    """
    from app.database.models import User as UserModel  # local import: cycle

    folders: set[str] = {PERSONAL_FOLDER, RESTRICTED_FOLDER, *PUBLIC_FOLDERS}
    folders.update(f for f in session.scalars(select(Document.folder)) if f)
    for assigned in session.scalars(select(UserModel.assigned_folders)):
        folders.update(f for f in (assigned or []) if f)
    return sorted(folders)
