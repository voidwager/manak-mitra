"""Small formatting helpers shared by the API layer."""

from datetime import datetime, timezone


def relative_time(then: datetime | None) -> str:
    """Human label like '10 min ago' for notification rows."""
    if then is None:
        return "just now"

    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)

    seconds = (datetime.now(timezone.utc) - then).total_seconds()

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = int(seconds // 86400)
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


# `display_clock` used to live here and rendered "10:24 AM" for chat bubbles
# from the server's naive local clock. Removed: a server cannot know what time
# it is where the reader is sitting. Message bubbles now receive `created_at`
# as timezone-aware UTC and are formatted client-side.
