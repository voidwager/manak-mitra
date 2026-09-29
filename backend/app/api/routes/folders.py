"""The folder namespace.

Folders are what decide retrieval scope, but they are not an entity: a
folder is a free-text string on `Document.folder`, matched against
free-text strings in `User.assigned_folders`. There is no table to list, so
this endpoint derives the set.

It exists so there is exactly one derivation. Without it the Documents page
hard-codes a folder list, the future admin surface hard-codes another, and
the two drift until someone files a document into a folder that grants
access they did not intend. `app.services.access.known_folders` is that one
place; this route is its HTTP face.

Promoting folders to a real entity belongs with RBAC in Phase 16. When that
happens, this route's response shape stays and only the derivation behind it
changes.
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import FolderOut
from app.services.access import assignable_folders, is_administrator, known_folders

router = APIRouter(tags=["documents"])


@router.get("/folders", response_model=FolderOut)
def list_folders(user: CurrentUser, db: DbSession) -> FolderOut:
    """Folders that exist, and which of them this user may file into.

    `all` is the full namespace and is informational - it is not a grant of
    access, and it deliberately does not leak which documents are in each
    folder. `assignable` is the enforceable half, and the server re-checks
    it on every write; a client that ignores it gets a 403, not a silent
    success.
    """
    administrator = is_administrator(user)
    everything = known_folders(db)

    return FolderOut(
        all=everything,
        # Administrators are unrestricted, so the assignable list is the full
        # namespace rather than empty - the UI needs something to show, and
        # `unrestricted` tells it a new name is also allowed.
        assignable=everything if administrator else assignable_folders(user),
        unrestricted=administrator,
    )
