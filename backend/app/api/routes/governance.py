"""Reading the audit trail, and managing sessions.

The workbench has recorded an audit entry for every meaningful action since
early on - uploads, folder moves, reclassifications, tool calls, sign-ins.
None of it was readable. An audit log nobody can read is a log, not
governance: it satisfies the letter of "we record everything" while
answering no actual question.

Owner clearance only, and the read is itself audited. Somebody looking
through who accessed what is an event worth recording.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import CurrentSession, CurrentUser, DbSession
from app.api.schemas import AuditEntryOut, SessionOut
from app.database.models import AuditLog, User, UserSession
from app.services import audit, auth
from app.services.access import is_administrator

router = APIRouter(tags=["governance"])


def _require_administrator(user: User) -> None:
    if not is_administrator(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The audit trail is restricted to owner clearance.",
        )


@router.get("/audit", response_model=list[AuditEntryOut])
def read_audit_log(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = None,
    subject: str | None = Query(default=None, description="Filter by user id"),
    outcome: str | None = Query(default=None, description="success | failed | denied"),
) -> list[AuditLog]:
    """The audit trail, newest first.

    Filters exist because the useful questions are narrow ones: "who moved
    documents into Safety", "which sign-ins failed", "what did this account
    do". An unfilterable log of everything is unreadable in practice.
    """
    _require_administrator(user)

    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if subject:
        stmt = stmt.where(AuditLog.user_id == subject)
    if outcome:
        stmt = stmt.where(AuditLog.status == outcome)

    entries = list(db.scalars(stmt.offset(offset).limit(limit)))

    # Reading the trail is itself an event. Recorded without the filters'
    # values, which could contain a name someone searched for.
    audit.record(
        db,
        user_id=user.id,
        action="audit.read",
        resource_type="audit",
        detail={"returned": len(entries), "filtered": bool(action or subject or outcome)},
    )
    db.commit()
    return entries


@router.get("/audit/actions", response_model=list[str])
def list_audit_actions(user: CurrentUser, db: DbSession) -> list[str]:
    """Every action name present in the log, for the filter control."""
    _require_administrator(user)
    return sorted(a for a in db.scalars(select(AuditLog.action).distinct()) if a)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    session: CurrentSession,
    db: DbSession,
    include_revoked: bool = False,
) -> list[SessionOut]:
    """Sessions for the current user, or for everyone with owner clearance.

    "Where am I signed in?" is a question a user should be able to answer
    about themselves, and one an administrator should be able to answer
    about the deployment.
    """
    user, current = session

    stmt = select(UserSession).order_by(UserSession.last_seen_at.desc())
    if not is_administrator(user):
        stmt = stmt.where(UserSession.user_id == user.id)
    if not include_revoked:
        stmt = stmt.where(UserSession.revoked_at.is_(None))

    return [
        SessionOut(
            id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            user_agent=row.user_agent,
            # So a client never offers to revoke the session it is using
            # without saying that is what it will do.
            current=row.id == current.id,
        )
        for row in db.scalars(stmt)
    ]


@router.post("/sessions/{user_id}/revoke", status_code=status.HTTP_200_OK)
def revoke_user_sessions(
    user_id: str, session: CurrentSession, db: DbSession
) -> dict[str, int]:
    """End every session for a user.

    Yourself always; anyone with owner clearance. This is the control that
    makes "someone left" actionable - and the reason sessions are rows
    rather than self-contained tokens, which cannot be withdrawn.
    """
    actor, _ = session

    if user_id != actor.id and not is_administrator(actor):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only end your own sessions.",
        )

    subject = db.get(User, user_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    return {"revoked": auth.revoke_all_sessions(db, subject, actor)}
