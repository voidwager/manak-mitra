"""Authentication and governance.

Before this phase the workbench had no authentication: identity was an
`X-User-Id` header the client asserted. Everything built on top - document
scoping, agent permissions, the audit trail - was the correct *shape* of a
control without being one, because anyone could claim to be anyone.

These tests cover the properties that make it a control now: passwords are
not recoverable, sessions can be withdrawn, failures do not leak who has an
account, and the old bypass is gone.
"""

import pytest

from app.core.security import (
    SESSION_IDLE_TIMEOUT,
    SESSION_MAX_LIFETIME,
    hash_password,
    hash_token,
    is_session_live,
    needs_rehash,
    new_session_token,
    verify_password,
)
from app.database.base import utcnow
from tests.conftest import DEMO_PASSWORD, sign_in

OWNER_EMAIL = "admin@bis-helpdesk.example"
ENGINEER_EMAIL = "certification@bis-helpdesk.example"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def test_a_hash_does_not_contain_the_password():
    stored = hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in stored
    assert stored.startswith("scrypt$")


def test_the_same_password_hashes_differently_every_time():
    """A shared salt would make identical passwords visibly identical."""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a)
    assert verify_password("same-password", b)


def test_verification_fails_closed_on_anything_malformed():
    assert verify_password("x", None) is False
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "scrypt$bad$params$here$ff$ff") is False
    assert verify_password("", hash_password("x")) is False


def test_an_empty_password_is_refused_at_the_hashing_boundary():
    with pytest.raises(ValueError):
        hash_password("")


def test_a_weaker_stored_hash_is_flagged_for_rehashing():
    assert needs_rehash(None) is True
    assert needs_rehash("bcrypt$whatever") is True
    assert needs_rehash("scrypt$1024$8$1$aa$bb") is True, "n below current"
    assert needs_rehash(hash_password("current")) is False


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------
def test_tokens_are_unique_and_stored_hashed():
    a, b = new_session_token(), new_session_token()
    assert a != b
    assert hash_token(a) != a
    assert len(hash_token(a)) == 64  # sha256 hex


def test_a_revoked_session_is_not_live():
    now = utcnow()
    live, reason = is_session_live(
        created_at=now, last_seen_at=now, revoked_at=now
    )
    assert live is False
    assert "signed out" in reason


def test_an_idle_session_expires():
    now = utcnow()
    live, reason = is_session_live(
        created_at=now,
        last_seen_at=now - SESSION_IDLE_TIMEOUT * 2,
        revoked_at=None,
    )
    assert live is False
    assert "inactivity" in reason


def test_a_session_cannot_outlive_its_maximum_however_active():
    now = utcnow()
    live, reason = is_session_live(
        created_at=now - SESSION_MAX_LIFETIME * 2,
        last_seen_at=now,
        revoked_at=None,
    )
    assert live is False
    assert "maximum lifetime" in reason


# ---------------------------------------------------------------------------
# The API surface
# ---------------------------------------------------------------------------
def test_a_token_grants_access_and_identifies_its_owner(client):
    token = sign_in(client, ENGINEER_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == "user-ananya"


def test_a_malformed_authorization_header_is_rejected(client):
    token = sign_in(client, ENGINEER_EMAIL)

    for header in ("", "Bearer", token, f"Basic {token}", "Bearer "):
        response = client.get("/api/documents", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_signing_out_ends_the_session_immediately(client):
    token = sign_in(client, ENGINEER_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/documents", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    # The same token is now worthless - this is what a JWT could not do
    # without a blocklist.
    assert client.get("/api/documents", headers=headers).status_code == 401


def test_a_password_never_leaves_the_server(client, owner_headers):
    """No endpoint may return a hash, let alone a password."""
    users = client.get("/api/users").json()
    body = str(users)
    assert "password" not in body.lower()
    assert "scrypt" not in body

    me = client.get("/api/auth/me", headers=owner_headers).json()
    assert "passwordHash" not in me
    assert "password" not in str(me).lower()


def test_changing_a_password_ends_every_existing_session(client):
    """A change that leaves old sessions live is cosmetic."""
    first = sign_in(client, ENGINEER_EMAIL)
    second = sign_in(client, ENGINEER_EMAIL)
    headers = {"Authorization": f"Bearer {first}"}

    response = client.post(
        "/api/auth/password",
        headers=headers,
        json={"currentPassword": DEMO_PASSWORD, "newPassword": "a-new-password-123"},
    )
    assert response.status_code == 204

    # Both the session that made the change and the other one are gone.
    assert client.get("/api/documents", headers=headers).status_code == 401
    assert (
        client.get(
            "/api/documents", headers={"Authorization": f"Bearer {second}"}
        ).status_code
        == 401
    )

    # The new password works, the old one does not.
    assert sign_in(client, ENGINEER_EMAIL, "a-new-password-123")
    assert (
        client.post(
            "/api/auth/login",
            json={"email": ENGINEER_EMAIL, "password": DEMO_PASSWORD},
        ).status_code
        == 401
    )

    # Put it back so the cached fixture tokens still work for other tests.
    restore = sign_in(client, ENGINEER_EMAIL, "a-new-password-123")
    client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {restore}"},
        json={"currentPassword": "a-new-password-123", "newPassword": DEMO_PASSWORD},
    )


def test_changing_a_password_requires_the_current_one(client):
    token = sign_in(client, ENGINEER_EMAIL)
    response = client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "wrong", "newPassword": "another-password-123"},
    )
    assert response.status_code == 403


def test_a_short_new_password_is_refused(client):
    token = sign_in(client, ENGINEER_EMAIL)
    response = client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": DEMO_PASSWORD, "newPassword": "short"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------
def test_the_audit_trail_is_owner_clearance_only(client, engineer_headers):
    response = client.get("/api/audit", headers=engineer_headers)
    assert response.status_code == 403
    assert "owner clearance" in response.json()["detail"]


def test_the_audit_trail_records_sign_ins(client, owner_headers):
    sign_in(client, ENGINEER_EMAIL)

    entries = client.get(
        "/api/audit", headers=owner_headers, params={"action": "auth.login"}
    ).json()

    assert entries, "a sign-in should be recorded"
    assert all(e["action"] == "auth.login" for e in entries)


def test_a_failed_sign_in_is_recorded_as_failed(client, owner_headers):
    client.post(
        "/api/auth/login",
        json={"email": ENGINEER_EMAIL, "password": "definitely-wrong"},
    )

    failures = client.get(
        "/api/audit",
        headers=owner_headers,
        params={"action": "auth.login", "outcome": "failed"},
    ).json()
    assert failures, "a failed sign-in should be recorded"


def test_reading_the_audit_trail_is_itself_audited(client, owner_headers):
    client.get("/api/audit", headers=owner_headers)

    reads = client.get(
        "/api/audit", headers=owner_headers, params={"action": "audit.read"}
    ).json()
    assert reads, "looking through the log is an event worth recording"


def test_a_user_sees_only_their_own_sessions(client, engineer_headers):
    body = client.get("/api/sessions", headers=engineer_headers).json()
    assert body
    assert all(s["userId"] == "user-ananya" for s in body)
    assert any(s["current"] for s in body), "the session in use must be marked"


def test_owner_clearance_sees_every_session(client, owner_headers, engineer_headers):
    client.get("/api/documents", headers=engineer_headers)  # ensure one exists
    body = client.get("/api/sessions", headers=owner_headers).json()
    assert len({s["userId"] for s in body}) > 1


def test_an_employee_cannot_revoke_someone_elses_sessions(client, engineer_headers):
    response = client.post("/api/sessions/user-dev/revoke", headers=engineer_headers)
    assert response.status_code == 403


def test_owner_clearance_can_end_a_users_sessions(client, owner_headers):
    """The control that makes "someone left" actionable."""
    token = sign_in(client, "hallmarking@bis-helpdesk.example")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/documents", headers=headers).status_code == 200

    response = client.post("/api/sessions/user-dev/revoke", headers=owner_headers)
    assert response.status_code == 200
    assert response.json()["revoked"] >= 1

    assert client.get("/api/documents", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# The seeded demo password
# ---------------------------------------------------------------------------
def test_the_demo_password_default_holds_only_in_development(monkeypatch):
    """Outside development it must be set explicitly, or seeding refuses.

    The default is printed in the source and the seeded owner account has
    full clearance, so a deployment seeded with it hands plant-administrator
    access to anyone who finds the URL. Failing closed is the only safe
    behaviour: a deployment that will not seed is obvious, and one that
    seeds a published password is not.
    """
    import pytest

    from app.core.config import settings
    from app.database import seed as seed_module

    monkeypatch.delenv("DEMO_PASSWORD", raising=False)

    monkeypatch.setattr(settings, "app_env", "development")
    assert seed_module._demo_password() == seed_module.DEFAULT_DEMO_PASSWORD

    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError) as excinfo:
        seed_module._demo_password()

    # The message has to say what to do, not just that something is wrong.
    assert "DEMO_PASSWORD" in str(excinfo.value)


def test_an_explicit_demo_password_is_used_in_any_environment(monkeypatch):
    from app.core.config import settings
    from app.database import seed as seed_module

    monkeypatch.setenv("DEMO_PASSWORD", "a-real-one")
    monkeypatch.setattr(settings, "app_env", "production")

    assert seed_module._demo_password() == "a-real-one"
    assert seed_module._demo_password() != seed_module.DEFAULT_DEMO_PASSWORD
