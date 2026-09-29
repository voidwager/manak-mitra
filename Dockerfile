# Manak Mitra - one image, one port, both halves.
#
# The frontend is built here and served by the API process, which is why
# there is a single service rather than two. Same origin means no CORS
# allow-list to keep in step with a hostname somebody changes later, and one
# container means one thing to deploy, scale and roll back.
#
#   docker build -t manak-mitra .
#   docker run --rm -p 8000:8000 --env-file .env -v manak-data:/data manak-mitra
#
# The volume matters. Without it, uploaded documents and the SQLite database
# live inside the container's writable layer and vanish on the next deploy -
# see /data below.

# ---------------------------------------------------------------------------
# Stage 1: build the frontend
# ---------------------------------------------------------------------------
FROM node:24-alpine AS frontend

WORKDIR /build

# Manifests first, so `npm ci` is only re-run when dependencies actually
# change rather than on every source edit.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: the runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# - PYTHONDONTWRITEBYTECODE: the layer is read-only in practice; .pyc files
#   would only add size.
# - PYTHONUNBUFFERED: without it, logs sit in a buffer and a crash loses the
#   lines explaining why - which is exactly when they are needed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY data/demo/ ./data/demo/

# The built UI, from stage 1. FRONTEND_DIST points the API at it; without
# this the same image still runs, serving the API alone.
COPY --from=frontend /build/dist ./frontend/dist

# Writable state lives here and nowhere else, so a single volume covers it.
# Everything above this line is rebuilt by the image; everything below it has
# to survive one.
ENV FRONTEND_DIST=/app/frontend/dist \
    UPLOAD_DIR=/data/documents \
    SQLITE_FALLBACK_PATH=/data/manak_mitra.db \
    APP_ENV=production \
    DEBUG=false \
    PORT=8000

RUN mkdir -p /data/documents

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Non-root. The app writes only to /data, which is handed over explicitly.
RUN useradd --create-home --uid 10001 workbench \
    && chown -R workbench:workbench /data /app
USER workbench

EXPOSE 8000

# Reports what /api/health reports, so an orchestrator's idea of healthy and
# the application's own cannot drift apart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url=f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/api/health\"; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
