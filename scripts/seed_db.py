"""Create tables and load the synthetic demo dataset.

Run from the repository root:

    python scripts/seed_db.py

Idempotent - existing rows are left alone.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.database.seed import seed  # noqa: E402
from app.database.session import SessionLocal, init_db  # noqa: E402


def main() -> int:
    configure_logging()

    target = "SQLite development fallback" if settings.is_sqlite else "PostgreSQL"
    print(f"Database target : {target}")
    print(f"URL             : {_redact(settings.effective_database_url)}")

    init_db()

    with SessionLocal() as db:
        seed(db)

    print("Done. Seeded users: sanyam / ananya / dev (fictional accounts).")
    return 0


def _redact(url: str) -> str:
    """Hide the password if one is present in the connection string."""
    if "@" not in url or "//" not in url:
        return url
    scheme, rest = url.split("//", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        creds = f"{user}:***"
    return f"{scheme}//{creds}@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
