"""Resolve the acting user for a request.

Identity now comes from a session token in the `Authorization` header,
verified against the database on every request. Before Phase 16 it came from
an `X-User-Id` header the client simply asserted, which anyone could set to
anything - the access scoping built on top of it was the correct *shape* of
a control without being one.

That header is gone rather than kept as a fallback. A bypass left in "for
development" is a bypass in production, and the whole point of this phase is
that there is no longer a way to claim an identity without proving it.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import User, UserSession
from app.database.session import get_db
from app.services import auth

DbSession = Annotated[Session, Depends(get_db)]

UNAUTHENTICATED = "Not signed in. Sign in to the workbench first."
EXPIRED = "Your session is no longer valid. Sign in again."


def _bearer(header: str | None) -> str:
    """Pull the token out of an Authorization header."""
    if not header:
        return ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def get_current_session(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, UserSession]:
    """The signed-in user and the session that authenticated them."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    resolved = auth.resolve_session(db, token)
    if resolved is None:
        # Deliberately one message for every reason a token is unusable -
        # unknown, revoked, idle, expired. A client only needs to know it
        # must sign in again, and distinguishing them tells an attacker
        # whether a token was ever real.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=EXPIRED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return resolved


def get_current_user(
    session: Annotated[tuple[User, UserSession], Depends(get_current_session)],
) -> User:
    return session[0]


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSession = Annotated[tuple[User, UserSession], Depends(get_current_session)]
