# Manak Mitra

**SIH 2026 · Problem Statement SIH26107 · Ministry of Consumer Affairs, Food & Public Distribution (Department of Consumer Affairs) · Theme: Smart Automation**

*AI-powered Intelligent Assistant for Indian Standards and BIS Services for
Industries and Consumers.*

A public helpdesk that answers questions about Indian Standards and the
services of the Bureau of Indian Standards (BIS) in plain language, in the
user's own language, with every answer cited to the BIS document it came
from. Anyone can use it without an account; BIS staff sign in to manage the
knowledge base.

*Manak* is the word BIS itself uses for a standard (Manakonline, Manak
Bhawan); *Mitra* is a friend.

---

## What it does - mapped to the problem statement

| The problem statement asks it to... | How Manak Mitra does it |
|---|---|
| Answer questions related to Indian Standards | Retrieval over 19 public BIS documents (schemes, product lists, the BIS Act, standards basics), answers cited as `[1]`, `[2]` with the passage attached |
| Recommend applicable standards from a product description | `find_standard` reads BIS's published product lists (Scheme-I, Scheme-X, CRS - 861 product rows) as tables and returns the matching rows: IS number, Quality Control Order, scheme. It says when nothing matches rather than guessing |
| Guide on certification schemes, explain the process | The Certification Guide specialist, scoped to scheme documents: Scheme-I (ISI mark), CRS (R-number), FMCS, ECO mark, the Conformity Assessment Regulations |
| Answer consumer queries | Consumer complaints, BIS CARE, misuse of the ISI mark, rights under the BIS Act |
| Guide on hallmarking | HUID verification, caratages, mandatory districts by phase, testing your own jewellery, compensation for a purity shortfall |
| Suggest testing laboratories | The Lab Locator specialist over BIS's own labs and the recognised-lab lists (Group-1 and Group-2, by state) |
| Support multilingual interaction | Replies in the language and script the user wrote in. A question in Hindi, Tamil, Bengali or any non-Latin script is translated into English search terms for retrieval (the corpus is English), and the English query is shown in the activity trace |
| Source-backed, authorised sources | Every file in `data/bis/source/` is public BIS or PIB material with its source URL and retrieval date in its header - see [`data/bis/source/MANIFEST.md`](data/bis/source/MANIFEST.md). A citation can only name a passage that was actually retrieved |

**Built on SYNQ.** This is the same team's SIH26117 prototype (an
on-premise agentic AI workbench), remodelled: the retrieval, citation,
agent, tool and security machinery is unchanged in principle; the working
model changed from a private plant tool to a public service. What changed and
why is in [Remodel notes](#remodel-notes-industry-workbench-to-public-helpdesk).

---

## Honest status

This is an early prototype. The table below is the authoritative statement
of what exists; the running application reports the same thing at
`GET /api/health` and shows it in a banner in the UI.

| Capability | Status |
|---|---|
| Frontend (React + Vite) | Working |
| FastAPI backend | Working |
| PostgreSQL schema + persistence | Working |
| Users, agents, tools, documents, conversations, settings via API | Working |
| Server-side document access scoping | Working |
| Document upload, download, rename, foldering, classification | Working |
| Audit logging | Working |
| Model gateway (provider abstraction) | Working |
| Agent configuration, per-agent retrieval scope, lifecycle | Working |
| Chat via an open-weight model, streaming | Working *(needs a provider configured)* |
| On-premise inference via a local runtime | Supported, not yet exercised on real hardware |
| Document parsing / chunking / indexing | Working *(.txt, .md, .csv, .tsv, .pdf, .docx)* |
| Keyword retrieval (BM25) and citations | Working *(no model or extra service needed)* |
| Semantic retrieval (embeddings) | Supported, off unless an embedding endpoint is configured |
| Tool execution (native function calling) | Working *(5 of 6 tools)* |
| Synthetic demo corpus, indexed at seed time | Working |
| Agent builder (retrieval scope, tools, focus areas) | Working |
| Frontend tests | Working |
| Model routing (task -> model) | Working *(needs roles configured)* |
| Multimodal: images in chat | Working *(needs a vision model configured)* |
| Multi-step agentic loop (plan, act, observe) | Working *(bounded by steps, calls and time)* |
| Authentication (hashed passwords, revocable sessions) | Working |
| Audit trail, readable and filterable | Working |
| Public mode: anonymous visitors, one private session each | Working |
| BIS knowledge base (19 public documents, cited) | Working |
| Product description to IS number (`find_standard`) | Working *(over the three published compulsory-certification lists)* |
| Cross-language search (Hindi and other scripts) | Working *(needs a provider configured; falls back to searching as written)* |
| Replies in the user's language | Working *(as good as the configured model's multilingual ability)* |
| Voice input | Browser speech recognition, where the browser supports it |

Two things worth stating plainly:

- **Sovereignty depends on which provider is active.** With
  `MODEL_PROVIDER=groq` the system sends prompts to an external service and
  is *not* sovereign; `GET /api/health` reports `inference.onPremise: false`
  and the UI says so in a banner. Only `MODEL_PROVIDER=local` makes the
  on-premise claim true. That flag is derived from the active provider, never
  asserted.
- **Nothing fabricates evidence.** A citation is built from a passage that
  was actually retrieved and placed in the prompt - never parsed out of the
  model's answer. When retrieval finds nothing, the reply carries no source
  however confidently the model names one, and the system prompt reverts to
  forbidding citation outright. A document reports *"Indexed"* only once
  chunks exist for it; a file whose text could not be extracted says so, with
  the reason.
- **Retrieval cannot cross an access boundary.** Passages are searched
  through the same SQL permission filter the documents API uses, so a user
  cannot retrieve from a document they cannot open. This is the easiest place
  in a RAG system to leak a confidential file, because the leak arrives
  paraphrased inside an answer where nobody thinks to check permissions.
- **Failures are reported, not papered over.** If the provider is down, rate
  limited or misconfigured, the API returns a real error. It never invents an
  assistant reply to hide the failure, and your message is persisted first so
  nothing is lost on retry.

---

## Architecture

Current:

```
Browser (React + Vite)
    |
    |  fetch / SSE, JSON, X-User-Id header
    v
FastAPI  ──  api/routes  ──  services  ──  SQLAlchemy  ──  PostgreSQL
                                 │
                    ┌────────────┴─────────────┐
                    v                          v
             Model Gateway                  app/rag/
                    │                          │
        ┌───────────┴───────────┐    extract → chunk → index
        v                       v              │
  GroqProvider           LocalProvider    document_chunks
(prototype, external)  (on-premise)            │
        └───────────┬───────────┘         retriever
                    v                     ┌────┴─────┐
     OpenAICompatibleProvider           BM25    Embedding Gateway
        (one implementation)         (lexical)   (semantic, optional)
                                       └────┬─────┘
                                        RRF fusion
```

Both providers speak the same OpenAI-compatible wire format, so moving from
hosted to on-premise inference is a change of `MODEL_PROVIDER`,
`MODEL_NAME` and a base URL - not a rewrite. Nothing above
`app/services/chat_service.py` knows where the model runs.

The retrieval side has the same two seams. `app/rag/embeddings/` hides where
vectors are computed, and `app/rag/store.py` hides where chunks live -
today the relational database, later Qdrant or `pgvector`, without the
retriever changing.

Target (later milestones):

```
Frontend -> FastAPI -> Agent Orchestrator -> Model Gateway -> Local open-weight LLM/VLM
                            |                     |
                          Tools                Providers (local | external)
                            |
                       RAG / Qdrant / PostgreSQL
```

The model gateway boundary matters: when an external inference provider is
introduced for prototyping, it must sit behind that seam so it can be
swapped for a local runtime without touching the rest of the application.
`app/services/chat_service.py` is the single place inference will be called
from today.

---

## Project structure

```
AI workbench/
├── frontend/                    React + Vite single-page app
│   └── src/
│       ├── components/
│       │   ├── layout/          Sidebar, Header, StatusBanner
│       │   └── modals/          Document preview, create agent, report, search, profile, login
│       ├── pages/               Chat, Agents, Documents, Tools, Settings, History
│       ├── services/            http.js (fetch client), api.js (all API calls)
│       ├── state/               AppContext.jsx - single source of app state
│       ├── styles/              index.css - design tokens, light/dark themes
│       └── utils/               reports.js
│
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, CORS, router wiring
│   │   ├── api/
│   │   │   ├── routes/          health, users, agents, tools, documents,
│   │   │   │                    search, conversations, chat, notifications
│   │   │   ├── dependencies/    current_user (prototype identity)
│   │   │   └── schemas.py       Pydantic request/response models
│   │   ├── core/                config, logging, security
│   │   ├── database/
│   │   │   ├── models/          SQLAlchemy tables
│   │   │   ├── base.py          Declarative base + timestamp mixin
│   │   │   ├── session.py       Engine, session, init_db
│   │   │   └── seed.py          Synthetic demo dataset
│   │   ├── models/              Inference layer: gateway, router, providers
│   │   ├── rag/                 Retrieval
│   │   │   ├── extraction.py    File bytes -> text, per format
│   │   │   ├── chunking.py      Text -> passages, with page/section
│   │   │   ├── lexical.py       BM25, pure Python
│   │   │   ├── embeddings/      Embedding gateway + providers
│   │   │   ├── store.py         Vector store seam (DB today, Qdrant later)
│   │   │   ├── indexer.py       extract -> chunk -> embed -> persist
│   │   │   └── retriever.py     Scoped hybrid search + RRF fusion
│   │   ├── tools/               Tool execution
│   │   │   ├── base.py          Tool interface, context, result
│   │   │   ├── registry.py      Permission gates + execution
│   │   │   └── builtin/         calculator, retrieval, tables, reporting
│   │   └── services/            access, audit, chat, agents, agent_loop, vision
│   ├── tests/                   pytest API tests
│   └── requirements.txt
│
├── data/
│   ├── demo/
│   │   ├── README.md            Notes on the synthetic dataset
│   │   └── source/              Corpus as plain text; PDFs built from it
│   └── documents/               Uploaded and generated files (gitignored)
│
├── scripts/
│   ├── seed_db.py               Create tables, write the corpus, index it
│   └── verify_demo.py           Check every claim in DEMO.md still holds
├── DEMO.md                      Scripted walkthrough
├── docker-compose.yml           PostgreSQL for local development
├── .env.example
└── README.md
```

---

## Getting started

> **Quick start:** double-click `install.bat` once, then `start.bat`
> (`stop.bat` to stop).
> Day-to-day commands, phone access and troubleshooting live in
> **[RUNNING.md](RUNNING.md)**.

### Prerequisites

- Node.js 20+
- Python 3.10+
- PostgreSQL 15+ *(optional for a first run — see the database section)*

### 1. Environment

```bash
cp .env.example .env
```

Edit `.env`. For a first run you can leave `DATABASE_URL` empty and the
backend will use a local SQLite file instead — see below.

Never commit `.env`. It is gitignored, and `.env.example` contains
placeholders only.

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Create the tables and load the synthetic demo data (run from the repo root):

```bash
python scripts/seed_db.py
```

Start the API:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

### 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and pick one of the demo accounts.

Vite prints a **Network** URL too (e.g. `http://10.0.0.5:5173`) - use that to
open the workbench from a phone or a teammate's laptop on the same network.

The dev server proxies `/api` to the backend, so the browser only ever talks
to one origin. That is what makes network access work: a device loading the
LAN address would otherwise resolve `localhost:8000` to *itself*. It also
means no CORS setup and no LAN address baked into the bundle.

Note that there is no authentication yet, so anyone who can reach that
address can use the workbench. Fine on a home or hotspot network; do not do
it on untrusted Wi-Fi.

---

## Database

PostgreSQL is the target database.

```bash
docker compose up -d       # starts PostgreSQL on :5432
```

Set `POSTGRES_PASSWORD` in `.env` first (the compose file has no default on
purpose), then point the backend at it:

```
DATABASE_URL=postgresql+psycopg://manak:<your-password>@localhost:5432/manak_mitra
```

Then run `python scripts/seed_db.py` again.

### SQLite development fallback

If `DATABASE_URL` is empty, the backend falls back to a SQLite file at
`data/manak_mitra.db`. This exists so a new team member can run the
project before installing PostgreSQL. It is **not** the deployment target,
and anything relying on PostgreSQL-specific behaviour must be tested
against PostgreSQL.

### Schema

```
users ──┬── user_settings (1:1)
        ├── conversations ── messages
        ├── documents
        ├── agents
        ├── tasks
        ├── notifications
        └── audit_logs

agents ── agent_tools ── tools
```

`tasks` and the tool-linking rows exist for the indexing and agent
milestones. Nothing writes to `tasks` yet.

---

## Model layer

### Choosing a provider

```
MODEL_PROVIDER=none    # inference disabled (default)
MODEL_PROVIDER=groq    # external service. PROTOTYPE ONLY - not sovereign
MODEL_PROVIDER=local   # on-premise runtime. The end goal
```

**This project standardises on the Qwen family**, on every provider:

| | Why it decided the choice |
|---|---|
| Apache 2.0 licence | Survives a PSU procurement review; a custom licence invites questions |
| Size ladder (~0.5B - 72B+) | 7B on a laptop for the offline demo, 72B on server hardware, *same family* - so prompts tuned on hosted inference behave the same locally |
| Vision variant in-family | The problem statement says *multimodal*; that becomes a model-id change, not a re-architecture |
| Strong tool calling | Needed once the tool router lands |

**Never prototype on a closed model.** Closed weights cannot run on-premise,
so the final migration stops being a config change and becomes a redesign -
different prompt sensitivity, different output shape, different tool-calling
behaviour.

Planned deployments:

```
Prototype     Groq          Qwen, largest available
Offline demo  Ollama        Qwen ~7B on a laptop (wifi off, still works)
Target        vLLM          Qwen 72B on server hardware
```

### Prototype (external)

```
MODEL_PROVIDER=groq
GROQ_API_KEY=...            # from console.groq.com. .env only, never committed
MODEL_NAME=...
```

Model catalogues change, so `MODEL_NAME` has no default. Ask the running
provider what it serves:

```bash
curl http://localhost:8000/api/models
```

### On-premise

Install a local runtime, then:

```
MODEL_PROVIDER=local
LOCAL_MODEL_BASE_URL=http://localhost:11434/v1    # Ollama default
MODEL_NAME=...
```

vLLM, llama.cpp, LM Studio and TGI work the same way on their own ports.

You do not need a datacentre GPU to prove this path. A quantised 3B-7B
open-weight model under Ollama runs on a laptop with roughly 8 GB of RAM
(faster with any NVIDIA card). Slower and less capable than hosted
inference - but genuinely offline, which is the whole claim.

### How the swap stays honest

`GET /api/health` reports `inference.onPremise`, derived from the active
provider rather than asserted. `GroqProvider` hard-codes it to `False` and
the UI banner reads from it, so while an external provider is active the
application cannot describe itself as sovereign. There is a test that fails
if that ever changes.

### Failure handling

Every transport and vendor error is mapped onto a typed `ModelError`
(`ModelTimeoutError`, `ModelRateLimitError`, `ModelUnavailableError`,
`ModelAuthError`, `ModelResponseError`, `ModelNotConfiguredError`), each
with an appropriate HTTP status. Provider auth messages are never echoed
back to the client, because they can contain key fragments.

---

## Retrieval (RAG)

Retrieval has two independent halves, and only one of them needs a model.

**Lexical (BM25) is always on.** Pure Python over the indexed passages - no
model, no GPU, no second service, no network. Upload a document and it is
searchable immediately, on a laptop, offline. This is not a placeholder for
the "real" retrieval: BIS questions are full of exact tokens
(`IS 1293`, `IS/IEC 60947`, `HUID`, `R-41000000`) and embeddings are notoriously
weak on exactly those, so BM25 is the half that gets tag numbers right.

**Semantic search is additive.** Configure an embedding endpoint and vectors
are stored alongside the text, then fused with the lexical ranking. It fixes
the case BM25 misses - paraphrase, "can I check if my gold is real" against
text that says "verify HUID".

```
EMBEDDING_PROVIDER=local
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL=nomic-embed-text      # ollama pull nomic-embed-text
```

Then re-index (`POST /api/documents/{id}/index`): existing passages have no
vectors, and vectors from different models are not comparable, so retrieval
only uses chunks whose stored model matches the configured one and quietly
falls back to keyword search for the rest.

`GET /api/health` reports `retrieval.mode` as `lexical` or `hybrid` from the
running configuration. It is never asserted, and semantic search is never
claimed when no embedder answered.

### The pipeline

```
upload → extract → chunk → embed (optional) → document_chunks
                                                     │
question ──────────────────────────────────► retriever
                                              │        │
                                            BM25    cosine
                                              └── RRF ──┘
                                                   │
                                          top-k passages
                                          │              │
                                   prompt CONTEXT    citations
```

Fusion is Reciprocal Rank Fusion rather than a weighted score blend: BM25
scores and cosine similarities are on incomparable scales, so a weighted sum
needs corpus-specific constants that silently rot. RRF reads only the rank,
so it needs no tuning.

### What it will not do

- **Cite what it did not retrieve.** Citations are built from the passages
  placed in the prompt. Nothing parses a citation out of the model's answer,
  so the model cannot talk a source into existence.
- **Pad a prompt with weak matches.** Below `RAG_MIN_SCORE` a passage is
  dropped and the turn falls back to the no-retrieval prompt, which forbids
  citation outright. "The retrieved documents do not cover this" is a correct
  answer; an irrelevant SOP cited with confidence is not.
- **Cross an access boundary.** Candidate passages come from
  `visible_documents_query` - the same filter `GET /documents` uses. There is
  no parameter that widens it and no code path that skips it.
- **Read a scanned PDF or an image.** No OCR and no vision model, so those
  documents are marked *"No extractable text"* with the reason, rather than
  indexed as empty.

### Who can retrieve what

A document's **folder** is what decides retrieval scope, so changing it is an
access-control action rather than filing:

- `Personal Uploads` is a per-user namespace, not a shared folder. Two users
  "in" it never see each other's files.
- Any other folder is a grant: everyone assigned to it can retrieve that
  document's contents through the assistant, with citations.
- So moving a document *out* of `Personal Uploads` is the act of sharing it,
  and moving it back is the act of withdrawing it. There is no separate
  sharing mechanism.
- `is_confidential_owner_only` overrides all of that and hides the document
  from everyone but owner clearance, whatever folder it sits in.

`PATCH /documents/{id}` enforces this: an employee may only file into a
folder they are already assigned to, and only owner clearance may classify a
document or transfer it. Every change is audited with before/after values,
because "who moved this into a shared folder" is exactly the question an
auditor asks. A move takes effect on retrieval immediately - chunks are
reached through their document, so nothing needs re-indexing.

### Agents narrow retrieval

An agent's `folder_scope` restricts what it searches. It is intersected with
the caller's own permissions and can never widen them - pointing an agent at
a folder you are not assigned to returns nothing rather than returning the
folder. This is what makes agents genuinely different from one another
rather than differently-worded: ask the same question of two agents and you
get different sources, or no sources at all.

`retrieval_enabled: false` turns an agent into a general-knowledge assistant
that never cites anything, and the strict no-retrieval guardrail applies to
its every turn.

### Storage

Chunks and vectors live in the `document_chunks` table, and similarity is
brute-force cosine in Python. That is a deliberate trade: no extra service
to install, secure and back up on the server, and one place where access
scoping lives. Cost is linear in corpus size, so it stops being appropriate
somewhere in the hundreds of thousands of chunks - `app/rag/store.py` is the
seam Qdrant or `pgvector` slots into, and whatever replaces it must reproduce
the permission filter rather than bolt one on afterwards.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Environment label |
| `DEBUG` | `true` | Verbose logging |
| `DATABASE_URL` | *(empty)* | PostgreSQL connection string. Empty = SQLite fallback |
| `SQLITE_FALLBACK_PATH` | `data/manak_mitra.db` | Development database file |
| `SQL_ECHO` | `false` | Log every SQL statement |
| `UPLOAD_DIR` | `data/documents` | Where uploaded files are written |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |
| `MODEL_PROVIDER` | `none` | `none` \| `groq` \| `local` |
| `MODEL_NAME` | *(empty)* | Provider-specific model id. See `/api/models` |
| `MODEL_TEMPERATURE` | `0.2` | Sampling temperature |
| `MODEL_MAX_TOKENS` | `1024` | Response cap |
| `MODEL_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `MODEL_HISTORY_LIMIT` | `12` | Previous messages sent as context |
| `GROQ_API_KEY` | *(empty)* | **Secret.** `.env` only |
| `LOCAL_MODEL_BASE_URL` | `http://localhost:11434/v1` | On-premise runtime endpoint |
| `RAG_ENABLED` | `true` | Master switch for retrieval |
| `RAG_AUTO_INDEX` | `true` | Index a document as soon as it is uploaded |
| `RAG_CHUNK_CHARS` | `1200` | Passage size, in characters |
| `RAG_CHUNK_OVERLAP_CHARS` | `200` | Overlap between adjacent passages |
| `RAG_TOP_K` | `5` | Passages retrieved per turn |
| `RAG_MAX_CONTEXT_CHARS` | `6000` | Prompt budget for retrieved context |
| `RAG_MIN_SCORE` | `0.05` | Below this (normalised) a passage is dropped, not padded in |
| `EMBEDDING_PROVIDER` | `none` | `none` \| `local`. `none` = keyword search only |
| `EMBEDDING_MODEL` | *(empty)* | e.g. `nomic-embed-text`, `bge-m3` |
| `EMBEDDING_BASE_URL` | `http://localhost:11434/v1` | On-premise embedding endpoint |
| `EMBEDDING_BATCH_SIZE` | `16` | Passages per embedding request |
| `EMBEDDING_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Set in `frontend/.env` |

Secrets (API keys, database passwords) belong in `.env` only — never in
source, and never in the database.

---

## API

All routes are under `/api`. Every route except `/health`, `/users` and
`/auth/login` requires an `Authorization: Bearer <token>` header.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Status plus the implemented-capability map |
| `GET` | `/users` | Demo accounts for the login screen |
| `POST` | `/auth/login` | Sign in. Returns a session token |
| `POST` | `/auth/logout` | End this session server-side |
| `GET` | `/auth/me` | Who the current token belongs to |
| `POST` | `/auth/password` | Change your password. Ends every session |
| `GET` | `/audit` | The audit trail. Owner clearance; filterable |
| `GET` | `/sessions` | Your sessions, or everyone's with owner clearance |
| `POST` | `/sessions/{id}/revoke` | End a user's sessions |
| `GET` | `/settings` | Current user's preferences |
| `PATCH` | `/settings` | Update preferences |
| `GET` | `/agents` | List agents, with derived status and capabilities |
| `GET` | `/agents/{id}` | Single agent |
| `POST` | `/agents` | Create an agent, links selected tools |
| `PATCH` | `/agents/{id}` | Configure: instructions, retrieval scope, tools, retire |
| `DELETE` | `/agents/{id}` | Delete a custom agent. Built-ins cannot be deleted |
| `GET` | `/tools` | Tool registry, with real executability per tool |
| `POST` | `/tools/{id}/toggle` | Enable/disable a tool |
| `GET` | `/documents` | Scoped to what the user may see |
| `GET` | `/documents/{id}` | 404 if out of scope |
| `POST` | `/documents` | Upload. Stores the file and queues indexing |
| `PATCH` | `/documents/{id}` | Rename, move folder, classify, transfer ownership |
| `GET` | `/documents/{id}/download` | The original file, as an attachment |
| `POST` | `/documents/{id}/index` | (Re-)index. Returns 202; poll the document for the outcome |
| `GET` | `/documents/{id}/chunks` | The indexed passages - what retrieval actually searches |
| `DELETE` | `/documents/{id}` | Delete own upload, and its passages |
| `GET` | `/folders` | Folder namespace, and what this user may file into |
| `POST` | `/search` | Search the knowledge base directly, no model involved |
| `GET` | `/conversations` | Current user's threads |
| `GET` | `/conversations/{id}` | With messages |
| `POST` | `/conversations` | Create a thread |
| `PATCH` | `/conversations/{id}` | Rename |
| `DELETE` | `/conversations/{id}` | Delete |
| `POST` | `/chat` | Persists both messages, returns the model's reply |
| `POST` | `/chat/stream` | Same, as SSE (`start`/`tool`/`sources`/`delta`/`done`/`error`) |
| `GET` | `/models` | Available models, plus the resolved routing table |
| `POST` | `/attachments` | Attach a file to a chat turn. Private, never indexed |
| `GET` | `/attachments/{id}` | The attachment's bytes, for its thumbnail |
| `GET` | `/notifications` | Notification feed |
| `POST` | `/notifications/{id}/read` | Mark read |

Responses are camelCase so they drop straight into the React components.

---

## How the frontend talks to the backend

One path, no exceptions:

```
component  ->  useApp()  ->  services/api.js  ->  services/http.js  ->  fetch
```

Components never call `fetch` and never import `http.js` directly. Adding a
new backend call means adding a function to `services/api.js` and exposing
an action from `AppContext`.

When the API is unreachable the app says so in a banner with a retry button,
rather than rendering an empty workspace with no explanation.

---

## Agents

An agent is a saved configuration - a persona, a retrieval scope, and a set
of tools it is permitted to call. What it can actually *do* with that
configuration depends on the running system, so two fields are derived per
request rather than stored:

- **`status`** is `Ready`, `Limited`, `Unavailable` or `Retired`, computed
  from whether a model is configured and whether the agent's declared tools
  can run. It used to be a column seeded with `"Online"` and never written
  again, which made the green pill in the UI decorative.
- **`capabilities`** is a list of what the agent can do *now*, each entry
  carrying `available` and a reason. The "Document Vision" agent advertised
  *Thermal Image Inspection* and *OCR Text Extraction* next to a deployment
  with neither; it now reports those as unavailable, naming the missing
  vision model, and shows itself as `Limited`.

The author's free-text labels still exist as **`specialisations`** and are
shown separately as intent. The distinction is the point: what an agent is
*for* and what it can *do* are different claims, and only one of them is
checkable.

Built-in agents cannot be deleted (retire them with `status: "Offline"`
instead) and can only be edited with owner clearance. Custom agents belong
to whoever created them.

---

## Model routing

One deployment, several models, chosen per turn by what the turn actually
needs. Routing selects a *model*, never a provider, so it lives inside the
gateway seam - moving to a different provider changes which models exist,
not how they are chosen.

| Role | Serves |
|---|---|
| `chat` | The default. Any turn with no more specific requirement |
| `vision` | Turns with an image attached. Must accept image input |
| `reasoning` | Agents explicitly configured for longer analysis |
| `fast` | Short turns where the larger model is wasted |
| `transcription` | Speech to text |

Priority is: an image forces `vision`; otherwise an agent's configured role
wins; otherwise the default. An unset role falls back to `MODEL_NAME` and
reports itself as degraded rather than pretending the routed model answered.
`GET /api/models` shows the resolved table.

**Routing is deterministic.** A turn carrying an image needs a model that
accepts images - a fact about the turn, not a judgement about its difficulty.
There is deliberately no "this looks like a hard question" heuristic: a
router that switches models on a hunch cannot be debugged, cannot be
explained to an auditor, and makes every answer irreproducible. Every turn's
activity trace names the model that answered and the reason it was chosen.

### Images

An image is only ever sent to a model that accepts images. The check happens
before the request is built, because the failure mode otherwise is silent:
the runtime either errors in a way that looks like a server fault, or drops
the picture and answers as though it had looked. The second is worse - the
user trusts the answer.

So with no `MODEL_VISION` configured, an attached image is refused with a
reason at upload time, the model is told it could not read the file, and the
activity trace records it. Nothing pretends to have seen a picture.

Chat attachments are separate from documents on purpose: an attachment is
private to its uploader and never indexed, whereas a document is shared,
folder-scoped and retrievable. Routing screenshots into the corpus would
degrade retrieval for everyone in the folder.

---

## Tools

A tool is a function the model may ask the server to run. It asks; the
server decides. Every gate is enforced here, never inferred from what the
model requested:

1. `Tool.enabled` - the operator's global switch. Turning a tool off removes
   it from what every agent is offered, so no model can call it.
2. `AgentTool` - whether *this* agent was granted *this* tool. An agent with
   no grants is offered nothing; tool access is granted, not assumed.
3. The calling user's own document permissions, applied inside the tool via
   the same SQL scoping the documents API uses - so a retrieval tool cannot
   become a way around access control.

A request for a tool the agent does not hold is refused and recorded, not
honoured. The refusal deliberately does not name which other tools exist,
since that would let an agent enumerate the registry it cannot use.

| Tool | State |
|---|---|
| `document_search` | Find which documents mention a topic |
| `knowledge_retrieval` | Read exact passages, attached to the reply as citations |
| `calculator` | Exact arithmetic, AST-evaluated |
| `analyse_table` | Counts, sums, averages over an indexed CSV |
| `generate_report` | Structured report stamped with the real evidence trail |
| `img-analyzer` | **Catalogued only** - needs the image pipeline (Phase 13) |

### Why the calculator does not use `eval()`

Its input is written by a language model, which is in turn influenced by
document text and user messages. That makes it attacker-reachable, and
`eval()` on attacker-reachable input is remote code execution. Expressions
are parsed to an AST and walked; only numbers, arithmetic operators and a
whitelist of pure functions are honoured. A name, call, attribute,
subscript or comprehension is refused rather than evaluated, and huge
exponents are rejected before they burn a CPU.

### Tool output is untrusted input

A retrieved passage that reads "ignore your previous instructions" reaches
the prompt through a tool result exactly as it would through retrieval. Tool
results are therefore fenced and labelled as data, and the guardrail stays
last in the prompt.

### The agentic loop

The model reads each tool result and decides what to do next, until it
answers or a budget binds. What makes this safe to run is the bounds, not
the loop - an unbounded loop is not a feature.

Three limits, deliberately independent, because any one alone is escapable:
a model can make ten calls inside one step, or one very slow call per step.

| Limit | Default | Guards against |
|---|---|---|
| `AGENT_MAX_STEPS` | 6 | Wandering across many think-act cycles |
| `AGENT_MAX_TOOL_CALLS` | 12 | Batching many calls into few steps |
| `AGENT_TIME_BUDGET_SECONDS` | 90 | One slow tool holding a request open |

**Repeats are refused, not retried.** A model that did not get the answer it
expected will often ask the identical question again, indefinitely.
Identical calls are detected and refused with an explanation - information
it can act on, unlike a silent retry, which teaches it nothing.

**Running out is reported, not truncated.** When a budget binds, the model
is told it is out of room and asked to answer with what it has. An answer
that says what is missing is useful; a cut-off one is not. The trace records
which limit bound and what the turn cost.

On the final round the tool schemas stay in the request but `tool_choice`
becomes `"none"`. Removing the schemas instead makes some models emit their
internal `<tool_call>` markup as prose, because they still intend to call
something and have nowhere to put it. Observed with Qwen; there is a
backstop that strips such markup from a reply, and a test that pins it.

---

## Security

Identity is a session token the server verifies on every request. Until
Phase 16 it was an `X-User-Id` header the client asserted - anyone could
claim to be anyone, so everything built on top was the correct *shape* of a
control without being one. That header no longer authenticates anything, and
was removed rather than kept as a development fallback: a bypass left in for
convenience is a bypass in production.

**Passwords** are hashed with scrypt from the standard library. bcrypt and
argon2 are the more usual choices and either would be fine, but both mean a
compiled wheel - and for an air-gapped deployment every dependency is
something to justify. Parameters travel with each hash, so they can be
raised later without invalidating existing passwords, and a correct password
stored under weaker parameters is transparently upgraded on sign-in.

**Sessions are rows, not JWTs.** A JWT cannot be withdrawn before it expires
without a blocklist, which is a session table wearing a disguise. At BIS
where access has to end the moment someone leaves, revocable beats
stateless - `POST /sessions/{id}/revoke` is the control that makes "someone
left" actionable. Only the token's hash is stored, so a leaked database
yields no live sessions for the same reason it yields no passwords.

**A failed sign-in does not say why.** "No such account" and "wrong
password" are different facts, and telling them apart lets anyone enumerate
who has an account - on a staff system, a staff list. Both return the same
status and the same words, and the password is verified even when the
account does not exist so the two paths take comparable time.

**Changing a password ends every session**, including the one that made the
change. Leaving old sessions live would make the change cosmetic while an
intruder stayed signed in.

### Demo credentials

The seeded accounts share the password `demo1234` **in development
only**, which is public here on purpose: the dataset is fictional and a demo
nobody can sign into is not a demo.

Outside development it fails closed. With `APP_ENV` set to anything else,
seeding raises unless `DEMO_PASSWORD` is set explicitly:

```
DEMO_PASSWORD must be set when APP_ENV is not 'development'.
```

That is deliberate rather than merely tidy. The seeded owner account carries
full clearance, so a deployment seeded with a password printed in this
repository would hand administrator access - the internal folder
included - to anyone who found the URL. A deployment that refuses to seed is
obvious; one that seeds a published password is not.

The sign-in page follows the same rule, from the server's own
`/api/health` rather than a build flag: outside development it fills the
address and leaves the password blank.

### The access model

`AccessLevel` is the enforced authority, and has two values that genuinely
gate behaviour:

- **OWNER** - every document including confidential material; may classify,
  move a document into any folder, edit any agent, read the audit trail, and
  end anyone's sessions.
- **EMPLOYEE** - own uploads plus assigned folders; may only file into
  folders they belong to.

`User.role` is a free-text job title for display and grants nothing. A third
enum of aspirational roles (engineer / supervisor / admin) used to sit in
`core/security.py`, stored and never enforced; it was deleted rather than
left to imply an RBAC system that did not exist.

### Governance

The audit trail has recorded every meaningful action since early on -
uploads, folder moves, reclassifications, tool calls, sign-ins - and until
now none of it was readable. A log nobody can read is a log, not governance.
`GET /audit` exposes it to owner clearance, filterable by action, subject
and outcome, because the useful questions are narrow ones. Reading it is
itself audited.

What was already done properly before this phase:

- Document scoping is evaluated in SQL on the server, so out-of-scope rows
  never reach the browser. Client-side filtering is not a security control.
- Out-of-scope document requests return 404 rather than 403, so the response
  does not confirm that a document exists.
- Uploads are extension-restricted, size-limited, and filenames are
  sanitised before touching the filesystem.
- Every mutating operation writes an audit log row.
- No passwords, tokens or secrets are stored in the database.

Real authentication, RBAC enforcement, tool permissions and human-in-the-loop
approval are a later milestone.

---

## Testing

```bash
cd backend
.venv\Scripts\activate          # or: source .venv/bin/activate
pytest
```

The suite uses a throwaway SQLite database and needs no API key, no model
and no embedding endpoint - stubs stand in for both. It covers the API
contract, document scoping, upload validation, the indexing lifecycle, and
the two guarantees worth breaking a build over:

- retrieval never returns a passage from a document the caller cannot open
  (`tests/test_rag.py`, scoping group)
- a citation only ever names a document that was actually retrieved, and no
  citation appears when retrieval found nothing
- a metadata change propagates to retrieval, and nobody can grant access they
  do not hold (`tests/test_documents.py`)
- the calculator refuses everything that is not arithmetic, and a tool call
  satisfies all three gates before it runs (`tests/test_tools.py`)
- the agentic loop is bounded three independent ways, and a repeated call is
  refused rather than retried (`tests/test_agent_loop.py`)
- an image never reaches a model that cannot read one (`tests/test_routing.py`)
- a password is never recoverable, a session can be withdrawn, and a failed
  sign-in does not reveal whether the account exists (`tests/test_auth.py`)

```bash
cd frontend
npm run lint
npm run test      # vitest, jsdom
npm run build
```

The frontend suite covers the claims the UI is responsible for, since those
are the ones that drift silently: a tool with no implementation must never
read as callable, an agent's status must come from the server rather than a
constant, and a document must not display an index it does not have.

There is also an executable version of the demo:

```bash
python scripts/verify_demo.py
```

It checks every claim in `DEMO.md` - the citation resolves to the right
page, the confidential document stays out of the wrong hands, the two agents
return different results, the tools compute the right numbers. A demo script
rots quietly, and finding out in front of an audience is the wrong time.

---

## Development rules

1. **Do not over-engineer.** Simple, modular and working beats complex and
   unfinished.
2. **Preserve the working UI.** The existing design is the visual baseline —
   polish it, do not redesign it.
3. **No fake functionality.** If it is not implemented, the UI must say so.
4. **No fake AI reasoning.** Show high-level execution events only, never
   invented chain-of-thought.
5. **Never hard-code secrets.** Environment variables only.
6. **Keep providers replaceable.** No hard dependency on any single model,
   embedding model, vector database or inference vendor.
7. **Build vertically.** Finish complete slices — UI through API through
   database — before starting new features.

---

## Remodel notes: industry workbench to public helpdesk

SYNQ answered confidential documents for people inside one plant. BIS
answers public rules for anyone in the country. Same machinery, opposite
working model - so what changed is mostly *who may do what*, not how
retrieval works.

| | SYNQ (SIH26117) | Manak Mitra (SIH26107) |
|---|---|---|
| Users | Plant staff, all signed in | Anyone; staff sign in only to administer |
| Corpus | Fictional refinery SOPs | 19 real public BIS documents, source URL and date on each |
| Folders | Unit folders, scoped per user | Six public folders everyone reads; desk folders scoped per officer; `BIS Internal` owner-only |
| Language | English | Replies in the user's language; non-Latin questions searched through an English rewrite |
| Key question | "What does our SOP say?" | "Which standard applies to my product?" - answered by a dedicated tool over BIS's product lists |

### What was added

- **Public mode** (`PUBLIC_MODE`, default on). `POST /api/auth/guest` mints a
  throwaway visitor (`AccessLevel.PUBLIC`) with one session. One account per
  visitor, because conversations and uploads are keyed by user - a shared
  guest account would show everyone everyone's chats. Visitor rows have no
  password hash, so they can never be signed into by password.
- **Visitor limits, enforced server-side**: read the public folders and
  their own uploads; cannot publish into a public folder, create an agent,
  or switch a tool. The UI hides those controls, but the API is what refuses.
- **`find_standard`** (`app/tools/builtin/standards.py`): parses every table
  with an IS-number column in the *Standards & QCOs* folder and matches a
  product description by its head noun ("PVC **pipes** for drinking water"),
  IDF-weighted, with a small synonym map for how people say things versus
  how BIS lists them (bulb/lamp, TV/television). Every match reports which
  of the user's words it does *not* cover, so a near match is never
  presented as an exact one.
- **Cross-language search** (`app/services/language.py`): a question mostly
  in a non-Latin script is rewritten into English search terms by the fast
  model, and searched together with the original.
- **Retrieval tuning for this corpus**: BM25 now scores a passage together
  with its document title and section heading (the passage the model cites
  is unchanged), and folds plurals on plain words ("laboratories" matches
  "labs"). Identifiers are never stemmed.
- **Real voice input** in ten Indian languages through the browser's speech
  recognition, hidden where the browser has none.

### Found and fixed along the way

- **Any signed-in user could switch a tool off for everyone.**
  `POST /tools/{id}/toggle` had no permission check. On a public site that
  would have let any visitor disable the service. Now administrator-only.
- **The microphone button was simulated** - it waited two seconds and typed
  a canned sentence. Replaced with real recognition, per the rule that the UI
  must not pretend.

### Knowledge-base gaps

From [`data/bis/source/MANIFEST.md`](data/bis/source/MANIFEST.md): marking-fee
tables per IS number, the ISI application checklist and forms, per-lab
testing scope and charges (only on the dynamic LIMS portal), lists of A&H
centres and licensed jewellers, and the amended text of the Conformity
Assessment Regulations were not captured from a static public source. The
assistant says so when asked rather than filling the gap from memory. The
next step is scheduled re-capture of these pages, and
`EMBEDDING_MODEL=bge-m3` for multilingual semantic search.
---

## Credits

- **SYNQ Workbench** - the original SIH 2026 prototype for SIH26117 by team
  **Avengers6**. The retrieval, citation, agent, tool and security machinery
  this project stands on is theirs. The first commit in this repository is
  their code as received.
- **Manak Mitra remodel** for SIH26107 - [voidwager](https://github.com/voidwager).
- **Knowledge base** - public material of the Bureau of Indian Standards and
  the Press Information Bureau, Government of India, with source links in
  [`data/bis/source/MANIFEST.md`](data/bis/source/MANIFEST.md).

No licence file is included: the original SYNQ code belongs to its team.
Ask before reusing it.