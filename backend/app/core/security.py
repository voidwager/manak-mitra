"""Password hashing, session tokens, and the access model.

Until this phase the workbench had no authentication: the frontend asserted
identity with an `X-User-Id` header, which anyone could set to anything. The
access scoping built on top of it was the correct *shape* of a control
without being one. This module supplies the missing half.

**Passwords** are hashed with scrypt from the standard library. bcrypt and
argon2 are the more usual choices and either would be fine, but both mean a
compiled wheel; scrypt is a memory-hard KDF, is in `hashlib`, and needs
nothing installed - which matters for an air-gapped deployment where every
dependency is something to justify. Parameters are stored alongside each
hash so they can be raised later without invalidating existing passwords.

**Sessions** are opaque random tokens recorded in the database, not JWTs.
A JWT cannot be withdrawn before it expires without a blocklist, which is
a session table wearing a disguise. In a plant where someone's access has to
end the moment they leave, revocable beats stateless.

Only the *hash* of a token is stored. A leaked database then yields no live
sessions, for the same reason it yields no passwords.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from app.database.base import utcnow

# --- scrypt parameters ------------------------------------------------------
# n=16384 (2**14), r=8, p=1 is the interactive-login parameter set: about
# 16 MB of memory and a few tens of milliseconds per hash. Enough to make
# offline guessing expensive without making a login feel slow.
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

#: Prefix identifying the hash format, so a future change of algorithm can be
#: detected rather than guessed at.
SCHEME = "scrypt"

#: How long a session lasts without use, and at most.
SESSION_IDLE_TIMEOUT = timedelta(hours=12)
SESSION_MAX_LIFETIME = timedelta(days=7)

#: Login attempts allowed per account before it is briefly locked. Not a
#: substitute for a rate limiter at the edge; it exists so a forgotten
#: deployment cannot be brute-forced at leisure.
MAX_FAILED_LOGINS = 8
LOCKOUT_DURATION = timedelta(minutes=15)


class AccessLevel(StrEnum):
    """The enforced authority in this system.

    Two levels, both of which genuinely gate behaviour:

      OWNER     sees every document including confidential material, may
                classify, may move a document into any folder, may edit any
                agent, may read the audit log.
      EMPLOYEE  sees their own uploads plus their assigned folders, and may
                only file into folders they belong to.
      PUBLIC    an anonymous visitor to the helpdesk. Reads the public
                folders, may keep private uploads, and changes nothing that
                anyone else can see - no publishing, no agents, no tools.

    `User.role` is a free-text job title for display ("Maintenance
    Engineer") and grants nothing. A third enum of aspirational roles used
    to sit here, stored and never enforced; it was removed rather than left
    to imply an RBAC system that did not exist.
    """

    OWNER = "OWNER"
    EMPLOYEE = "EMPLOYEE"
    PUBLIC = "PUBLIC"


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a password for storage.

    Returns `scrypt$n$r$p$salt$hash`, all hex. The parameters travel with
    the hash so raising them later does not invalidate existing passwords -
    an old hash still verifies under the parameters it was made with.
    """
    if not password:
        raise ValueError("Refusing to hash an empty password.")

    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return "$".join(
        [SCHEME, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), salt.hex(), derived.hex()]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising for anything malformed: a corrupt or
    absent hash must fail closed, and a caller should not have to
    distinguish "wrong password" from "bad hash" at the call site.
    """
    if not password or not stored:
        return False

    try:
        scheme, n, r, p, salt_hex, expected_hex = stored.split("$")
        if scheme != SCHEME:
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
    except (ValueError, TypeError, MemoryError):
        return False

    # Constant time: a timing difference here leaks how much of the hash
    # matched, which is enough to reconstruct it byte by byte.
    return hmac.compare_digest(derived, bytes.fromhex(expected_hex))


def needs_rehash(stored: str | None) -> bool:
    """Whether a stored hash was made with weaker parameters than current."""
    if not stored:
        return True
    try:
        scheme, n, r, p, _, _ = stored.split("$")
    except ValueError:
        return True
    return (
        scheme != SCHEME
        or int(n) < SCRYPT_N
        or int(r) < SCRYPT_R
        or int(p) < SCRYPT_P
    )


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------
def new_session_token() -> str:
    """A fresh opaque token. 256 bits of entropy, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The stored form of a session token.

    SHA-256 rather than scrypt: a token already has full entropy, so there
    is nothing to brute-force and no reason to make verification expensive.
    The hash exists so a database leak does not hand over live sessions.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(now: datetime | None = None) -> datetime:
    return (now or utcnow()) + SESSION_MAX_LIFETIME


def _as_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    SQLite has no timezone type, so a column declared `DateTime(timezone=True)`
    round-trips through the development database as naive - and comparing it
    with an aware `utcnow()` raises. Everything this application writes is
    UTC, so attaching the zone back on read is correct rather than a guess.
    PostgreSQL returns it aware already and this is a no-op there.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_session_live(
    created_at: datetime,
    last_seen_at: datetime,
    revoked_at: datetime | None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Whether a session is still usable, and why not if it is not."""
    now = now or utcnow()
    created_at = _as_utc(created_at)
    last_seen_at = _as_utc(last_seen_at)

    if revoked_at is not None:
        return False, "This session was signed out."
    if now - created_at > SESSION_MAX_LIFETIME:
        return False, "This session has reached its maximum lifetime."
    if now - last_seen_at > SESSION_IDLE_TIMEOUT:
        return False, "This session expired through inactivity."
    return True, ""


__all__ = [
    "LOCKOUT_DURATION",
    "MAX_FAILED_LOGINS",
    "SESSION_IDLE_TIMEOUT",
    "SESSION_MAX_LIFETIME",
    "AccessLevel",
    "hash_password",
    "hash_token",
    "is_session_live",
    "needs_rehash",
    "new_session_token",
    "session_expiry",
    "verify_password",
]
