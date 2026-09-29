"""Database engine and session management."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.database.base import Base

log = get_logger(__name__)

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.effective_database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


#: Columns added after a table already existed in someone's dev database.
#: `create_all` only creates missing *tables*, never missing columns, so a
#: schema change would otherwise break every existing install.
#:
#: This is a deliberate stopgap, not a migration system. It handles additive,
#: nullable/defaulted columns only. Introduce Alembic before doing anything
#: it cannot express (renames, type changes, backfills, drops).
#: SQLite takes 0/1 for a boolean literal; PostgreSQL insists on false/true.
_FALSE = "0" if settings.is_sqlite else "false"
_TRUE = "1" if settings.is_sqlite else "true"

_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "conversations": {
        "pinned": f"BOOLEAN NOT NULL DEFAULT {_FALSE}",
        # Per-chat model override (SI-1 work).
        "model_override": "VARCHAR(160) NOT NULL DEFAULT ''",
    },
    # Phase 8 (retrieval). `document_chunks` itself is a new table, so
    # create_all covers it; these are the columns bolted onto tables that
    # already existed in a developer's database.
    "documents": {
        "indexed_at": "TIMESTAMP NULL",
        "index_error": "TEXT NOT NULL DEFAULT ''",
        "extracted_chars": "INTEGER NOT NULL DEFAULT 0",
        "is_semantically_indexed": f"BOOLEAN NOT NULL DEFAULT {_FALSE}",
        # A document attached to one chat rather than added to the corpus.
        "conversation_id": "VARCHAR(64) NULL",
    },
    # A chat attachment that is a document has one, and is indexed.
    "attachments": {
        "document_id": "VARCHAR(64) NULL",
    },
    # Declared JSON, matching the mapped column, so SQLAlchemy's result
    # processor sees the type it expects on both backends.
    "messages": {
        "sources": "JSON NULL",
        # A generated inspection report attached to this reply.
        "report": "JSON NULL",
    },
    # Phase 16 (authentication). All nullable or defaulted, so a database
    # seeded before auth existed still loads - and a user with no hash
    # simply cannot sign in, which fails closed.
    "users": {
        "password_hash": "VARCHAR(255) NULL",
        "password_updated_at": "TIMESTAMP NULL",
        "failed_logins": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TIMESTAMP NULL",
        "last_login_at": "TIMESTAMP NULL",
    },
    # Phase 10 (agent retrieval configuration).
    "agents": {
        "retrieval_enabled": f"BOOLEAN NOT NULL DEFAULT {_TRUE}",
        "folder_scope": "JSON NULL",
        "retrieval_top_k": "INTEGER NULL",
        # Phase 14 (model routing).
        "model_role": "VARCHAR(32) NOT NULL DEFAULT 'chat'",
        # SI-1, the universal agent.
        "is_universal": f"BOOLEAN NOT NULL DEFAULT {_FALSE}",
    },
}


def _apply_additive_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all just made it, with every column
        present = {c["name"] for c in inspector.get_columns(table)}
        for column, ddl in columns.items():
            if column in present:
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.info("Added missing column %s.%s", table, column)


def init_db() -> None:
    """Create tables if they do not exist, then patch in additive columns.

    Fine for the prototype. Alembic migrations take over once the schema
    starts changing in ways `_ADDITIVE_COLUMNS` cannot express.
    """
    # Import registers the mappers on Base.metadata.
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_additive_columns()

    log.info(
        "Database ready (%s)",
        "sqlite-dev-fallback" if settings.is_sqlite else "postgresql",
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
