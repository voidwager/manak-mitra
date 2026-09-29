"""Header notification feed."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.api.dependencies import CurrentUser, DbSession
from app.api.schemas import NotificationOut
from app.database.models import Notification
from app.services.timeutils import relative_time

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialise(rows: list[Notification]) -> list[NotificationOut]:
    return [
        NotificationOut(
            id=n.id,
            title=n.title,
            description=n.description,
            read=n.read,
            time=relative_time(n.created_at),
        )
        for n in rows
    ]


@router.get("", response_model=list[NotificationOut])
def list_notifications(user: CurrentUser, db: DbSession) -> list[NotificationOut]:
    stmt = (
        select(Notification)
        .where(or_(Notification.user_id == user.id, Notification.user_id.is_(None)))
        .order_by(Notification.created_at.desc())
    )
    return _serialise(list(db.scalars(stmt)))


@router.post("/{notification_id}/read", response_model=list[NotificationOut])
def mark_read(notification_id: str, user: CurrentUser, db: DbSession) -> list[NotificationOut]:
    row = db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")

    row.read = True
    db.commit()
    return list_notifications(user, db)
