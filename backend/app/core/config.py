"""Application configuration.

Everything environment-driven. No secrets in source - see `.env.example`
at the repository root for the full list of variables.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


#: Schemes that mean PostgreSQL but do not name a driver SQLAlchemy can
#: find here.
#:
#: Hosting providers hand out `postgres://` (Heroku's old form, still used by
#: several) or `postgresql://`. SQLAlchemy maps both to psycopg2, which this
#: project does not install - it uses psycopg 3. The failure is a
#: ModuleNotFoundError for psycopg2 at startup, which says nothing about the
#: URL being the cause, so the fix is to accept what providers actually give
#: you rather than to document a scheme people have to remember to edit.
_PG_SCHEMES = ("postgres://", "postgresql://")


def _normalise_db_url(url: str) -> str:
    """Point a PostgreSQL URL at the driver that is actually installed."""
    url = url.strip()
    for scheme in _PG_SCHEMES:
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Our settings legitimately start with "model_"; that prefix is
        # reserved by pydantic for its own attributes unless we opt out.
        protected_namespaces=(),
    )

    # --- Application ---------------------------------------------------
    app_name: str = "Manak Mitra API"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"

    # --- Database -------------------------------------------------------
    # PostgreSQL is the target database for this project.
    #   postgresql+psycopg://user:password@host:5432/manak_mitra
    #
    # `database_url` is intentionally left empty by default so a developer
    # without a local PostgreSQL server still gets a working backend via
    # the SQLite fallback below. Set DATABASE_URL in .env to use PostgreSQL.
    database_url: str = ""
    sqlite_fallback_path: str = "data/manak_mitra.db"
    sql_echo: bool = False

    # --- Storage --------------------------------------------------------
    # Uploaded documents live on the local filesystem, inside the repo's
    # data/ directory by default. On-premise deployment points this at a
    # plant-controlled volume.
    upload_dir: str = "data/documents"

    # --- CORS -----------------------------------------------------------
    # Vite dev server origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Model layer ----------------------------------------------------
    # Which implementation sits behind the model gateway:
    #   none  - inference disabled (default)
    #   groq  - external provider, PROTOTYPE ONLY, not sovereign
    #   local - on-premise runtime (Ollama / vLLM / TGI), the end goal
    model_provider: str = "none"

    # Model identifier. Provider-specific and it changes over time, so there
    # is deliberately no default - GET /api/models lists what is available.
    model_name: str = ""

    model_temperature: float = 0.2
    model_max_tokens: int = 1024
    model_timeout_seconds: float = 60.0

    # How many previous messages of a conversation to send as context.
    model_history_limit: int = 12

    # Prototype provider. Secret - .env only, never source, never the database.
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # On-premise runtime endpoint (Ollama's default shown).
    local_model_base_url: str = "http://localhost:11434/v1"

    # --- Google Gemini --------------------------------------------------
    # A second hosted vendor, reached through Google's OpenAI-compatible
    # endpoint so it needs no extra dependency. Worth having alongside Groq
    # for two reasons: a separate rate limit, and a far larger context
    # window for document work.
    #
    # SECRET. .env only - never source, never committed, never the database.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"

    # Default Gemini model, used when a route names the vendor but no model.
    #
    # Gemma rather than a Gemini Flash model, deliberately. Gemma 4 is
    # Apache 2.0 with weights on HuggingFace (google/gemma-4-31B-it) and is
    # multimodal, so it satisfies the open-weight requirement while Gemini's
    # own models - which are never released - would not. Serving an
    # open-weight model through a hosted API is a deployment choice that can
    # be reversed; prototyping on closed weights cannot.
    #
    # Note the `models/` prefix: Google's OpenAI-compatible endpoint returns
    # and expects fully-qualified ids, and a bare `gemma-4-31b-it` 404s.
    gemini_model: str = "models/gemma-4-31b-it"

    # --- Model routing --------------------------------------------------
    # One deployment, several models, chosen per turn by what the turn
    # actually needs. All of them are served by whichever provider is
    # configured above - routing selects a model, never a vendor, so it sits
    # inside the gateway seam rather than around it.
    #
    # Every entry is optional. An unset role falls back to MODEL_NAME, and
    # `GET /api/models` reports the resolved table, so a role that silently
    # degraded is visible rather than assumed.
    #
    # Routing is deterministic and explainable on purpose. A turn carrying an
    # image needs a model that accepts images; that is a fact about the turn,
    # not a guess about its difficulty. There is no "this looks complicated"
    # heuristic, because a router that silently picks a different model on a
    # hunch is impossible to debug and impossible to defend.

    # Accepts images. Required for any turn with a picture attached.
    model_vision: str = ""

    # Longer, harder questions where an agent is explicitly configured for it.
    model_reasoning: str = ""

    # Cheap and quick, for short turns where the big model is wasted.
    model_fast: str = ""

    # Speech to text. Powers the microphone; without it the button is
    # disabled rather than faking a transcript.
    model_transcription: str = ""

    # --- Agentic loop ---------------------------------------------------
    # How far an agent may work on its own before it must answer.
    #
    # The loop is bounded in three independent ways, because a model that
    # gets stuck does not get stuck politely: it repeats the same call, or
    # walks a chain of near-identical ones, and each iteration costs a
    # request and burns context. Any one bound alone is escapable.
    #
    #   steps      how many times it may think-act-observe
    #   tool calls total across the turn, however they are distributed
    #   seconds    wall clock, so a slow tool cannot hold a request open
    #
    # Whichever binds first ends the loop, and the reason is reported in the
    # activity trace rather than the answer simply arriving truncated.
    agent_max_steps: int = 6
    agent_max_tool_calls: int = 12
    agent_time_budget_seconds: float = 90.0

    # --- Retrieval (RAG) ------------------------------------------------
    # Retrieval has two independent halves.
    #
    # Lexical (BM25) retrieval is always available: it is pure Python over
    # the chunks table and needs no model, no service and no extra
    # infrastructure. Indexing a document therefore always produces
    # something searchable.
    #
    # Semantic retrieval is additive. It switches on only when an embedding
    # endpoint is configured below, and the two are then fused. Nothing
    # claims to be semantic when no embedder answered.
    rag_enabled: bool = True

    # Index a document automatically once it has been uploaded.
    rag_auto_index: bool = True

    # Chunking is measured in characters, not tokens: the tokenizer belongs
    # to whichever model is loaded, and we refuse to pull in a model-specific
    # tokenizer just to split text. ~1200 chars is roughly 300 tokens.
    rag_chunk_chars: int = 1200
    rag_chunk_overlap_chars: int = 200

    # How many passages are retrieved for a turn, and how much of the prompt
    # they are allowed to occupy.
    rag_top_k: int = 5
    rag_max_context_chars: int = 6000

    # Passages scoring below this (normalised 0-1 within a result set) are
    # dropped rather than padded into the prompt. A weak match is worse than
    # no match: it invites the model to cite something irrelevant.
    rag_min_score: float = 0.05

    # --- Embeddings -----------------------------------------------------
    # EMBEDDING_PROVIDER selects the implementation behind the embedding
    # gateway:
    #   none  - semantic retrieval disabled; lexical BM25 still works
    #   local - on-premise embedding runtime (Ollama / TEI / vLLM / Infinity)
    #
    # All of those speak the OpenAI /embeddings wire format, so switching
    # runtimes is a URL change.
    embedding_provider: str = "none"

    # Provider-specific and it changes over time, so no default.
    # Ollama examples: "nomic-embed-text", "bge-m3", "qwen3-embedding:0.6b".
    embedding_model: str = ""

    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_batch_size: int = 16
    embedding_timeout_seconds: float = 120.0

    # --- Public helpdesk ------------------------------------------------
    # BIS answers the public, so by default anyone may open the assistant
    # without an account: POST /auth/guest mints a throwaway visitor with
    # read access to the public folders and nothing else. Staff still sign in
    # with a password to manage documents, agents and the audit trail.
    # Switch off for a staff-only deployment.
    public_mode: bool = True

    #: Built frontend, relative to the repo root unless absolute. Set by the
    #: container image; unset and non-existent in development.
    frontend_dist: str = "frontend/dist"

    def _anchor(self, value: str) -> Path:
        """Resolve a configured path against the repo root when relative.

        Keeps behaviour identical whether uvicorn is started from the repo
        root or from backend/.
        """
        path = Path(value)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def upload_path(self) -> Path:
        return self._anchor(self.upload_dir)

    @property
    def frontend_dist_path(self) -> Path:
        """Where a built frontend lives, if one was built into the image.

        Absent in development - Vite serves the UI itself - so the app
        checks for it rather than assuming either way.
        """
        return self._anchor(self.frontend_dist)

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return _normalise_db_url(self.database_url)
        db_path = self._anchor(self.sqlite_fallback_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.effective_database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
