"""Users, sign-in, and per-user settings."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.dependencies import CurrentSession, CurrentUser, DbSession
from app.api.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChange,
    SettingsOut,
    SettingsUpdate,
    UserOut,
)
from app.core.config import settings
from app.core.security import AccessLevel, verify_password
from app.database.models import User, UserSettings
from app.services import auth
from app.models import router as model_router
from app.services import prompts

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession) -> list[User]:
    """The sign-in screen's account list.

    Deliberately still unauthenticated, and deliberately narrow: it returns
    display fields only. It never returns a password hash, and knowing an
    account exists gains nobody anything without its password.

    On a real deployment this would be removed - an employee list is worth
    having - but the demo needs its personas visible to be usable at all.
    """
    # Visitors are one row each and would bury the staff personas.
    return list(
        db.scalars(
            select(User)
            .where(User.access_level != AccessLevel.PUBLIC)
            .order_by(User.created_at)
        )
    )


@router.post("/auth/guest", response_model=LoginResponse)
def guest(request: Request, db: DbSession) -> LoginResponse:
    """Start an anonymous helpdesk session - no account, no password.

    Refused when public mode is off, so a staff-only deployment has no
    anonymous way in at all rather than one that is merely unadvertised.
    """
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public access is not enabled on this deployment.",
        )
    signed_in = auth.start_guest_session(
        db, user_agent=request.headers.get("user-agent", "")
    )
    return LoginResponse(
        token=signed_in.token,
        user=UserOut.model_validate(signed_in.user),
        expires_at=signed_in.session.expires_at,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> LoginResponse:
    """Verify credentials and open a session.

    Every failure returns the same message and the same status. "No such
    account" and "wrong password" are different facts, and telling them
    apart lets anyone enumerate who has an account - on a plant system, that
    is a staff list.
    """
    try:
        signed_in = auth.authenticate(
            db,
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent", ""),
        )
    except auth.AuthError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=headers,
        ) from exc

    return LoginResponse(
        token=signed_in.token,
        user=UserOut.model_validate(signed_in.user),
        expires_at=signed_in.session.expires_at,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: CurrentSession, db: DbSession) -> None:
    user, row = session
    auth.sign_out(db, row, user)


@router.get("/auth/me", response_model=UserOut)
def whoami(user: CurrentUser) -> User:
    """Who the current token belongs to. Used to restore a session."""
    return user


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange, session: CurrentSession, db: DbSession
) -> None:
    """Change your own password.

    Every session ends, including this one. Changing a password somebody
    else may know has to end their access - otherwise the change is
    cosmetic and the intruder stays signed in.
    """
    user, _ = session

    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your current password is not correct.",
        )

    auth.set_password(db, user, payload.new_password)
    db.commit()


def _as_settings_out(row: UserSettings) -> SettingsOut:
    """Serialise, attaching the styles the server will honour."""
    return SettingsOut(
        theme=row.theme,
        compact_mode=row.compact_mode,
        show_timestamps=row.show_timestamps,
        show_agent_activity=row.show_agent_activity,
        temperature=row.temperature,
        response_style=row.response_style,
        response_style_options=list(prompts.RESPONSE_STYLES),
        chat_model=row.model or "",
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(user: CurrentUser, db: DbSession) -> SettingsOut:
    return _as_settings_out(_ensure_settings(db, user))


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate, user: CurrentUser, db: DbSession
) -> SettingsOut:
    row = _ensure_settings(db, user)

    # An unrecognised style is rejected rather than stored. The prompt
    # builder falls back to Balanced for anything it does not know, so an
    # unchecked value produced a setting that saved successfully, displayed
    # itself back, and did nothing.
    if payload.response_style is not None:
        if payload.response_style not in prompts.RESPONSE_STYLES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown response style. Choose one of "
                f"{sorted(prompts.RESPONSE_STYLES)}.",
            )

    if payload.chat_model is not None:
        chosen = payload.chat_model.strip()
        if chosen:
            allowed = set(model_router.configured_models().values())
            if chosen not in allowed:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"'{chosen}' is not one of this deployment's configured "
                    f"models ({sorted(allowed)}).",
                )
        row.model = chosen

    for field, value in payload.model_dump(
        exclude_unset=True, exclude={"chat_model"}
    ).items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _as_settings_out(row)


def _ensure_settings(db: DbSession, user: User) -> UserSettings:
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row
