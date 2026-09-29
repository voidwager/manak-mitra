"""Sign in, sign out, and resolving a session back to a user.

The rule that shapes everything here: a failed sign-in must not say *why* it
failed. "No such account" and "wrong password" are different facts, and
telling them apart lets anyone enumerate who has an account - which on a
plant system is a list of employees. Both return the same message, and the
password is verified even when the account does not exist, so the two paths
take comparable time.

Lockout is per account rather than per address. It is not a substitute for
a rate limiter at the edge; it exists so that a deployment nobody is
watching cannot be ground down at leisure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import (
    AccessLevel,
    LOCKOUT_DURATION,
    _as_utc,
    MAX_FAILED_LOGINS,
    hash_password,
    hash_token,
    is_session_live,
    needs_rehash,
    new_session_token,
    session_expiry,
    verify_password,
)
from app.database.base import utcnow
from app.database.models import User, UserSession
from app.services import audit

log = get_logger(__name__)

#: One message for every failure. Distinguishing them would let anyone
#: enumerate accounts.
GENERIC_FAILURE = "That email and password combination was not recognised."

#: A dummy hash to verify against when the account does not exist, so a
#: missing account and a wrong password take comparable time.
_DUMMY_HASH = hash_password("this-is-not-a-real-password")


class AuthError(Exception):
    """Sign-in refused. The message is safe to show the user."""

    def __init__(self, message: str = GENERIC_FAILURE, *, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class SignedIn:
    """A successful sign-in. The raw token is returned exactly once."""

    user: User
    token: str
    session: UserSession


def _lockout_remaining(user: User) -> int:
    if user.locked_until is None:
        return 0
    # Same naive/aware mismatch as session timestamps - see security._as_utc.
    remaining = (_as_utc(user.locked_until) - utcnow()).total_seconds()
    return max(0, int(remaining))


def authenticate(
    db: Session, email: str, password: str, user_agent: str = ""
) -> SignedIn:
    """Verify credentials and open a session.

    Raises `AuthError` for every failure, with the same message.
    """
    email = (email or "").strip().lower()
    user = db.scalars(select(User).where(User.email == email)).first()

    if user is not None:
        locked = _lockout_remaining(user)
        if locked:
            audit.record(
                db,
                user_id=user.id,
                action="auth.login",
                resource_type="user",
                resource_id=user.id,
                status="denied",
                detail={"reason": "locked"},
            )
            db.commit()
            raise AuthError(
                "This account is temporarily locked after repeated failed "
                f"sign-in attempts. Try again in {locked // 60 + 1} minute(s).",
                retry_after=locked,
            )

    # Verified even when the account does not exist, so a missing account and
    # a wrong password take comparable time.
    stored = user.password_hash if user is not None else _DUMMY_HASH
    correct = verify_password(password, stored)

    if user is None or not correct:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = utcnow() + LOCKOUT_DURATION
                user.failed_logins = 0
                log.warning("Account %s locked after repeated failures", user.id)
            audit.record(
                db,
                user_id=user.id,
                action="auth.login",
                resource_type="user",
                resource_id=user.id,
                status="failed",
                detail={"attempts": user.failed_logins},
            )
            db.commit()
        else:
            # No row to attribute this to, but the attempt is still recorded.
            audit.record(
                db,
                user_id=None,
                action="auth.login",
                status="failed",
                detail={"reason": "unknown_account"},
            )
            db.commit()
        raise AuthError()

    if user.password_hash is None:
        # Belt and braces: verify_password already fails closed on a missing
        # hash, so this is unreachable. Left explicit because "user with no
        # password can sign in" is the kind of bug worth two guards.
        raise AuthError()

    # A correct password under weaker parameters is transparently upgraded.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        user.password_updated_at = utcnow()
        log.info("Rehashed password for %s under current parameters", user.id)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    token = new_session_token()
    now = utcnow()
    session = UserSession(
        id=hash_token(token),
        user_id=user.id,
        last_seen_at=now,
        expires_at=session_expiry(now),
        user_agent=(user_agent or "")[:255],
    )
    db.add(session)

    audit.record(
        db,
        user_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        detail={"user_agent": session.user_agent},
    )
    db.commit()
    db.refresh(user)

    return SignedIn(user=user, token=token, session=session)


def start_guest_session(db: Session, user_agent: str = "") -> SignedIn:
    """Open a session for an anonymous helpdesk visitor.

    Each visitor gets their own row rather than sharing one "guest" account.
    Conversations, uploads and settings are all keyed by user, so a shared
    account would show every visitor everybody else's chats.

    The row has no password hash, so it can never be signed into by
    password - `verify_password` fails closed on a missing hash. The session
    token is the only credential, and when it expires the visitor is gone.
    """
    suffix = uuid.uuid4().hex[:12]
    user = User(
        id=f"guest-{suffix}",
        name="Visitor",
        email=f"visitor-{suffix}@guest.invalid",
        role="Public visitor",
        initials="V",
        access_level=AccessLevel.PUBLIC,
        scope_label="Public BIS information",
        # Informational only: a visitor's grant is read from
        # access.PUBLIC_FOLDERS at request time, never from this column.
        assigned_folders=[],
        avatar_gradient="linear-gradient(135deg, #1E3A8A, #F59E0B)",
        password_hash=None,
    )
    db.add(user)
    db.flush()

    token = new_session_token()
    now = utcnow()
    session = UserSession(
        id=hash_token(token),
        user_id=user.id,
        last_seen_at=now,
        expires_at=session_expiry(now),
        user_agent=(user_agent or "")[:255],
    )
    db.add(session)
    audit.record(
        db,
        user_id=user.id,
        action="auth.guest",
        resource_type="user",
        resource_id=user.id,
        detail={"user_agent": session.user_agent},
    )
    db.commit()
    db.refresh(user)
    return SignedIn(user=user, token=token, session=session)


def resolve_session(db: Session, token: str) -> tuple[User, UserSession] | None:
    """Find the user behind a token, or None if it is not usable.

    Touches `last_seen_at` so an idle session ages out, and refuses a
    revoked or expired one without saying which - a client only needs to
    know it must sign in again.
    """
    if not token:
        return None

    session = db.get(UserSession, hash_token(token))
    if session is None:
        return None

    live, _ = is_session_live(
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        revoked_at=session.revoked_at,
    )
    if not live:
        return None

    user = db.get(User, session.user_id)
    if user is None:
        return None

    session.last_seen_at = utcnow()
    return user, session


def sign_out(db: Session, session: UserSession, user: User) -> None:
    """Revoke one session. The row is kept so the audit trail resolves."""
    session.revoked_at = utcnow()
    audit.record(
        db,
        user_id=user.id,
        action="auth.logout",
        resource_type="user",
        resource_id=user.id,
    )
    db.commit()


def revoke_all_sessions(db: Session, user: User, actor: User) -> int:
    """End every session for `user`. Returns how many were live."""
    live = list(
        db.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        )
    )
    now = utcnow()
    for session in live:
        session.revoked_at = now

    audit.record(
        db,
        user_id=actor.id,
        action="auth.revoke_all",
        resource_type="user",
        resource_id=user.id,
        detail={"sessions": len(live)},
    )
    db.commit()
    return len(live)


def set_password(db: Session, user: User, password: str) -> None:
    """Set or change a password, ending every existing session.

    Changing a password that someone else may know has to end their access;
    leaving old sessions live would make the change cosmetic.
    """
    user.password_hash = hash_password(password)
    user.password_updated_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None

    for session in db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        )
    ):
        session.revoked_at = utcnow()


__all__ = [
    "GENERIC_FAILURE",
    "AuthError",
    "SignedIn",
    "authenticate",
    "resolve_session",
    "revoke_all_sessions",
    "set_password",
    "sign_out",
]
