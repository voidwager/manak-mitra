# Deploying the workbench

One image, one port. The frontend is built into it and served by the API
process, so there is a single service to run and no cross-origin request to
allow.

Everything lives on `main`. The packaging was developed on a `deploy`
branch so a broken deployment could not take `main` with it; that branch was
merged once the service was confirmed working.

---

## What you need before starting

| | |
|---|---|
| Docker | with Compose v2 (`docker compose`, not `docker-compose`) |
| A `DEMO_PASSWORD` | anything you choose — see below |
| `GROQ_API_KEY` | and/or `GEMINI_API_KEY` |

**`DEMO_PASSWORD` is not optional.** Outside development the seed refuses to
run without it, and the container will not start:

```
DEMO_PASSWORD must be set when APP_ENV is not 'development'.
```

That is deliberate. The built-in default is printed in this repository and
the seeded owner account carries full clearance, so a deployment seeded with
it would hand plant-administrator access — the restricted archive included —
to anyone who found the URL. A container that refuses to start is a problem
you notice; one that starts with a published password is not.

---

## Run it

```bash
# .env is gitignored and is never copied into the image. These are read by
# compose on the host and passed to the container as environment.
cat >> .env <<'EOF'
DEMO_PASSWORD=pick-something-real
EOF

docker compose -f docker-compose.deploy.yml up -d --build
```

Then open <http://localhost:8000>.

Check it came up:

```bash
docker compose -f docker-compose.deploy.yml ps          # healthy?
docker compose -f docker-compose.deploy.yml logs -f app # what it did on boot
curl localhost:8000/api/health
```

### Signing in

The addresses are seeded; the password is the one you set.

| Email | Role | Sees |
|---|---|---|
| `testowner@refinery.example` | Owner | Everything shared, plus the restricted archive |
| `testemployee@refinery.example` | Employee | CDU-II and their own uploads |
| `testemployee2@refinery.example` | Employee | Safety and their own uploads |

The sign-in page fills the address when you click a persona and leaves the
password blank, because outside development there is no password it could
correctly offer.

---

## The volume is the part people forget

```yaml
volumes:
  - workbench_data:/data
```

`/data` holds the SQLite database and every uploaded document. Without the
volume both live in the container's writable layer, and the next
`up --build` throws them away — the app comes back looking fine, seeded and
empty, which is a confusing way to lose a demo.

The seed runs on every boot and is idempotent: it adds what is missing,
migrates what has moved, and leaves everything else alone. So a fresh volume
comes up with the full demo corpus, and an existing one keeps its uploads.

### Using PostgreSQL instead

SQLite on a volume is fine for a demo. For anything longer-lived:

```bash
# in .env
POSTGRES_PASSWORD=...
DATABASE_URL=postgresql+psycopg://synq:...@postgres:5432/synq_workbench

docker compose -f docker-compose.deploy.yml --profile postgres up -d --build
```

Only then is it worth running more than one uvicorn worker. Two workers on
one SQLite file is a corruption waiting to happen, which is why the
entrypoint runs a single worker.

---

## Render

`render.yaml` describes the service, so Render creates it without a form.

1. Render dashboard → **New → Blueprint**.
2. Pick this repository and the **`main`** branch.
3. Render reads `render.yaml` and asks for the three secrets:

   | | |
   |---|---|
   | `DEMO_PASSWORD` | anything you choose — the container will not start without it |
   | `GROQ_API_KEY` | from console.groq.com |
   | `GEMINI_API_KEY` | only if vision or reasoning route to Gemini |

4. **Apply.** First build takes roughly 5–10 minutes — it installs the
   Python dependencies and runs a full Vite build inside the image.

You get `https://synq-workbench.onrender.com` (or whatever name you set).
Sign in with `testowner@refinery.example` and the `DEMO_PASSWORD` you chose.

### Watch the first boot

Render's log tab shows the entrypoint working:

```
=> Preparing the database
... Seed complete (synthetic demo dataset)
=> Serving on port 10000
```

If it stops at the first line, the message says why. A missing
`DEMO_PASSWORD` is by far the most likely cause and it says so explicitly.

### Two things the free plan does

**It sleeps after ~15 minutes idle.** The next request wakes it, and that
takes 30–60 seconds because the container starts cold. A judge clicking a
link that has been idle all morning waits on a blank tab. Load the page
yourself a minute beforehand and it is warm.

**It has no persistent disk.** `/data` is reset on every deploy and every
restart.

That second one matters less here than it usually would: the seed runs on
boot and rebuilds the entire demo corpus, so the service always comes back
complete rather than empty. What is lost is anything uploaded *through the
live site*. If the seeded corpus is the demo, free is genuinely fine.

To keep uploads, move to a paid instance and uncomment the `disk:` block at
the bottom of `render.yaml`.

### Half-way: a free PostgreSQL instance

Render's free tier includes one PostgreSQL instance (1 GB, expires 30 days
after creation, 14-day grace period). Pointing `DATABASE_URL` at it survives
restarts for everything held in the database - accounts, agents, document
records and the indexed chunks.

Ten minutes, and no code change: paste Render's **Internal Database URL**
into `DATABASE_URL` on the web service. The scheme it gives you is rewritten
to the installed driver automatically.

Know what it does *not* fix. Uploaded file *bytes* live on disk, not in the
database, so they still vanish on restart. A document uploaded through the
live site stays listed and stays searchable - the chunks are in PostgreSQL -
but Preview and Download fail on it, because the file behind it is gone.
Seeded documents are unaffected; the seed rewrites those from the image.

That is a real rough edge rather than a cosmetic one, so it is worth doing
only if you want accounts and settings to persist. If the demo is the seeded
corpus, the free plan without a database is simpler and has no such
half-state.

### Why not Vercel

Vercel runs serverless functions: no long-lived process, no writable disk,
and a per-request timeout. This app needs all three — server-sent events for
streaming chat, background indexing that outlives a request, and uploaded
files on disk. The frontend alone would deploy there happily, but then the
backend still needs somewhere like Render, and splitting them puts the CORS
allow-list back that serving both from one process removed.

---

## What the deployment reports about itself

Unchanged by packaging, and worth knowing before a demo:

- `/api/health` reports `inference.onPremise: false` while a hosted provider
  is configured, and the UI badges every agent card accordingly. Running in
  a container does not change where inference happens.
- The activity trace under each answer names the provider and model that
  actually served it.

The models are open-weight — Qwen and GPT-OSS publish to HuggingFace, Gemma 4
is Apache 2.0 — and the deployment says plainly that they are being served by
someone else. Both halves are true at once.

---

## Rolling back

```bash
docker compose -f docker-compose.deploy.yml down   # keeps the volume
```

`down -v` also destroys the volume, and with it every uploaded document.
