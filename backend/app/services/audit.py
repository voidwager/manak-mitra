"""Audit log writer."""

from typing import Any

from sqlalchemy.orm import Session

from app.database.models import AuditLog


def record(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    status: str = "success",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry.

    Caller is responsible for committing. `detail` must never contain
    document contents, credentials or tokens.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        detail=detail,
    )
    db.add(entry)
    return entry
