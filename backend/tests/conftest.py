"""Test fixtures.

IMPORTANT: the environment below is configured at *module import* time, not
inside a fixture.

`app.core.config` binds a module-level `settings` object when it is first
imported, and `app.database.session` builds the engine from it immediately.
A test module that imports anything from `app` at collection time therefore
locks in the configuration before any fixture runs. Setting DATABASE_URL in
a fixture was too late, and pointed the whole suite at the developer's real
database.

pytest imports conftest.py before it imports test modules, so this is the
one place that can win the race.
"""

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="manak-mitra-tests-"))

os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_ROOT / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP_ROOT / "uploads")
os.environ["SQL_ECHO"] = "false"

# No inference by default. Tests that need a model install a stub provider.
os.environ["MODEL_PROVIDER"] = "none"
os.environ["MODEL_NAME"] = ""
os.environ["GROQ_API_KEY"] = ""

# Every vendor, not just the default one. The registry builds a provider for
# any vendor whose key is present, so a developer with GEMINI_API_KEY in .env
# would give the suite a working provider it never asked for - and the tests
# that assert "nothing is configured" would fail on their machine and pass in
# CI, which is the worst way for this to break.
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_MODEL"] = ""

# Every routed role too. Without these the suite inherits whatever the
# developer has in .env, so a machine with MODEL_VISION set would report a
# vision capability the test environment does not have - which is the exact
# kind of drift this block exists to prevent.
os.environ["MODEL_VISION"] = ""
os.environ["MODEL_REASONING"] = ""
os.environ["MODEL_FAST"] = ""
os.environ["MODEL_TRANSCRIPTION"] = ""

# Retrieval likewise: a configured embedding endpoint would make the suite
# claim semantic search it never performed.
os.environ["EMBEDDING_PROVIDER"] = "none"
os.environ["EMBEDDING_MODEL"] = ""


@pytest.fixture(scope="session", autouse=True)
def _isolated_database():
    """Assert the isolation actually took, then clean up afterwards."""
    from app.core.config import settings

    resolved = settings.effective_database_url
    assert str(_TMP_ROOT.as_posix()) in resolved, (
        "Tests are not isolated - they would write to the real database "
        f"({resolved}). Check that conftest.py is imported before app.*"
    )

    yield

    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def client(_isolated_database):
    from fastapi.testclient import TestClient

    from app.database.seed import seed
    from app.database.session import SessionLocal, init_db
    from app.main import app

    init_db()
    with SessionLocal() as db:
        seed(db)

    with TestClient(app) as test_client:
        yield test_client


#: The password every seeded demo account carries. Public on purpose - the
#: dataset is fictional - and matched to seed.DEMO_PASSWORD.
DEMO_PASSWORD = "demo1234"

#: Signing in costs a scrypt hash, which is deliberately slow. Doing it once
#: per test would add seconds to the suite for no coverage, so tokens are
#: cached per account and reused. Tests that care about session lifecycle
#: sign in themselves.
_TOKEN_CACHE: dict[str, str] = {}


def sign_in(client, email: str, password: str = DEMO_PASSWORD) -> str:
    """Authenticate for real and return the bearer token."""
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, (
        f"could not sign in as {email}: {response.status_code} {response.text}"
    )
    return response.json()["token"]


def auth_headers(client, user_id: str, email: str) -> dict[str, str]:
    """A live token for this account, signing in again if the cached one died.

    Caching matters because scrypt is deliberately slow and the suite signs
    in constantly. But a cached token is not guaranteed live: tests that
    change a password or revoke sessions kill every token for that account,
    and a stale one would then fail later tests for a reason unrelated to
    what they are checking. So the cache is verified before use.
    """
    token = _TOKEN_CACHE.get(user_id)
    if token:
        probe = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        if probe.status_code != 200:
            token = None

    if not token:
        token = sign_in(client, email)
        _TOKEN_CACHE[user_id] = token

    return {"Authorization": f"Bearer {token}"}


#: The seeded staff accounts (see app/database/seed.py). One place, so a
#: change to the seed is one edit here rather than a hunt through the suite.
OWNER_EMAIL = "admin@bis-helpdesk.example"
ENGINEER_EMAIL = "certification@bis-helpdesk.example"
SAFETY_EMAIL = "hallmarking@bis-helpdesk.example"


@pytest.fixture
def owner_headers(client):
    """Sanyam Jain - owner clearance.

    These went from an asserted `X-User-Id` header to a real sign-in in
    Phase 16. That the whole suite still passes is the evidence that the
    access model was already being enforced server-side rather than relying
    on the client's claim.
    """
    return auth_headers(client, "user-sanyam", OWNER_EMAIL)


@pytest.fixture
def engineer_headers(client):
    """Ananya Roy - Certification Officer: public sources + Certification Desk."""
    return auth_headers(client, "user-ananya", ENGINEER_EMAIL)


@pytest.fixture
def safety_headers(client):
    """Dev Patel - Hallmarking Officer: public sources + Hallmarking Desk."""
    return auth_headers(client, "user-dev", SAFETY_EMAIL)


@pytest.fixture
def db_session(client):
    """A session against the same test database the API uses.

    For the few tests that need to set up a row state the API has no
    endpoint for - promoting a document to owner-confidential, for one.
    """
    from app.database.session import SessionLocal

    with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Model stub
#
# Shared by the chat and retrieval suites: both need a model that records
# the prompt it was handed, and neither should need an API key.
#
# These imports sit here rather than at the top of the file on purpose. The
# environment above must be in place before anything under `app.` is
# imported - see this module's docstring.
# ---------------------------------------------------------------------------
from app.models import gateway as gateway_module  # noqa: E402
from app.models.base import ChatMessage, Completion, ModelProvider  # noqa: E402
from app.models.gateway import ModelGateway  # noqa: E402


class StubProvider(ModelProvider):
    """Records the prompt it was given and returns a fixed reply."""

    name = "stub"
    configured = True

    # The gateway drops tool schemas for a provider that does not advertise
    # function calling. Left at the base class default of False, every
    # stub-driven test would exercise a path where no tools were ever
    # offered - which is not the path production takes, and would hide a
    # regression in the tool plumbing.
    supports_tools = True

    def __init__(self, reply="Stub reply.", *, on_premise=False, error=None):
        super().__init__(model="stub-model")
        self.reply = reply
        self.on_premise = on_premise
        self.error = error
        self.last_prompt: list[ChatMessage] = []

    def complete(self, messages, **kwargs) -> Completion:
        self.last_prompt = messages
        if self.error:
            raise self.error
        return Completion(text=self.reply, model=self.model, provider=self.name)

    def stream(self, messages, **kwargs) -> Iterator[str]:
        self.last_prompt = messages
        if self.error:
            raise self.error
        for word in self.reply.split(" "):
            yield word + " "


@pytest.fixture
def stub_gateway(monkeypatch):
    """Install a stub provider behind the gateway for one test."""

    def install(provider):
        monkeypatch.setattr(
            gateway_module, "get_gateway", lambda: ModelGateway(provider)
        )
        for module in (
            "app.services.chat_service",
            # Rewrites non-English questions for search before retrieval.
            "app.services.language",
            # Derives agent status and capabilities from the live gateway,
            # so it needs the stub too or every agent reports Unavailable.
            "app.services.agents",
            "app.api.routes.chat",
            "app.api.routes.health",
            "app.api.routes.agents",
        ):
            monkeypatch.setattr(
                f"{module}.get_gateway", lambda: ModelGateway(provider)
            )
        return provider

    return install
