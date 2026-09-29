"""SYNQ Workbench - API entrypoint.

Application data (users, agents, documents, tools, conversations,
settings) is served from PostgreSQL or the SQLite development fallback,
inference goes through the model gateway, and uploaded documents are
indexed and retrieved through `app/rag/`. `GET /api/health` reports
exactly which capabilities exist, and the UI labels itself from that
response rather than asserting anything.

In a packaged deployment this process also serves the built frontend, so
the two are one origin and one container. In development they stay
separate - Vite serves the UI with hot reload and calls this across CORS.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    agents,
    attachments,
    chat,
    conversations,
    documents,
    folders,
    governance,
    health,
    notifications,
    search,
    tools,
    users,
)
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.database.session import init_db

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    log.info("Starting %s (%s)", settings.app_name, settings.app_env)
    init_db()
    yield
    log.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Backend for the SYNQ Workbench (SIH 2026 / SIH26117). "
        "Prototype - see /api/health for the authoritative list of "
        "implemented capabilities."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    health,
    users,
    agents,
    tools,
    documents,
    attachments,
    folders,
    governance,
    search,
    conversations,
    chat,
    notifications,
):
    app.include_router(module.router, prefix=settings.api_prefix)


# ---------------------------------------------------------------------------
# The frontend, when one has been built into the image
# ---------------------------------------------------------------------------
# Mounted only if the directory exists, so development is untouched: there
# is no build there, Vite serves the UI itself, and this block does nothing.
#
# Serving both from one process is what removes CORS from the deployment
# entirely - same origin, so there is no allow-list to keep in step with a
# hostname somebody changes later. It also means one container and one port
# to expose rather than two services that have to find each other.
_FRONTEND_DIR = settings.frontend_dist_path


def _index_file() -> Path | None:
    candidate = _FRONTEND_DIR / "index.html"
    return candidate if candidate.is_file() else None


if _index_file() is not None:
    # Hashed asset filenames, so they are safe to cache hard. index.html is
    # served by the route below and is deliberately not cached, or a
    # redeploy leaves browsers pinned to the previous build's asset names.
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        """Hand every non-API path to the single-page app.

        The router lives in the browser, so a deep link like /documents is
        not a path this server knows - it has to return the shell and let
        the app route it. Only reached for paths no API route matched,
        because routers are registered first.

        An unknown path under the API prefix is refused rather than handed
        the shell. Returning HTML for a mistyped endpoint gives the caller a
        parse error somewhere else entirely, instead of the 404 that would
        have told them what was actually wrong.
        """
        if f"/{full_path}".startswith(f"{settings.api_prefix}/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

        # A real file (favicon.svg, robots.txt) is served as itself.
        direct = (_FRONTEND_DIR / full_path).resolve()
        if (
            full_path
            and direct.is_file()
            and _FRONTEND_DIR.resolve() in direct.parents
        ):
            return FileResponse(direct)

        index = _index_file()
        if index is None:  # pragma: no cover - checked at import
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

        return FileResponse(
            index,
            headers={"Cache-Control": "no-cache"},
        )

else:

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        """No frontend in this process - report where the API lives."""
        return {
            "service": settings.app_name,
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health",
            "frontend": "not bundled; run the Vite dev server",
        }
