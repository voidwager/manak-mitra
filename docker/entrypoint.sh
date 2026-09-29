#!/bin/sh
# Container start-up: prepare the database, then serve.
#
# Seeding runs on every boot because it is idempotent - it adds what is
# missing and migrates what has moved, and leaves everything else alone.
# That is what makes a fresh volume usable without a manual step, and what
# keeps a long-lived one in step after a deploy.
#
# It also means the demo-password rule is enforced here rather than
# discovered later: with APP_ENV set to anything but development, seeding
# refuses unless DEMO_PASSWORD is set. A container that will not start is a
# problem you fix in one minute; a public deployment carrying a password
# printed in the repository is one you find out about differently.

set -e

cd /app

# A mounted disk shadows whatever the image created at this path, and
# arrives empty. Recreating the upload directory here rather than relying on
# the Dockerfile's mkdir means the first boot after a disk is attached works
# the same as one without.
DATA_DIR="$(dirname "${SQLITE_FALLBACK_PATH:-/data/synq_workbench.db}")"
mkdir -p "${UPLOAD_DIR:-/data/documents}" "$DATA_DIR" 2>/dev/null || true

if [ ! -w "$DATA_DIR" ]; then
    echo "!! $DATA_DIR is not writable by this container."
    echo "!! Uploads and the database both live there. If a disk is mounted,"
    echo "!! check it is owned by the running user."
    exit 1
fi

echo "=> Preparing the database"
if ! python scripts/seed_db.py; then
    echo ""
    echo "!! Database preparation failed. The most common cause is a missing"
    echo "!! DEMO_PASSWORD: outside development the seed refuses to use the"
    echo "!! default, because it is published in the repository and the"
    echo "!! seeded owner account carries full clearance."
    echo "!!"
    echo "!! Set DEMO_PASSWORD in the environment and start again."
    exit 1
fi

# Uvicorn directly rather than gunicorn: one worker keeps the SQLite
# fallback coherent, and the workload here is IO-bound on an upstream model
# rather than CPU-bound. Move to multiple workers alongside PostgreSQL, not
# before - two workers on one SQLite file is a corruption waiting to happen.
echo "=> Serving on port ${PORT:-8000}"
exec python -m uvicorn app.main:app \
    --app-dir backend \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
