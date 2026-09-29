# Running the workbench

Commands are PowerShell (Windows).

The workbench is two processes - a Python API and a Vite dev server. They
run separately on purpose: each reloads on its own file changes, and keeping
their logs in separate windows makes errors far easier to find. `start.ps1`
launches both for you.

---

## The quick way: double-click

**`start.bat`** - starts both servers
**`stop.bat`**  - stops both

Double-click either from Explorer, or run from a terminal:

```
start.bat
stop.bat
```

`start.bat` frees the ports, opens each server in its own window, waits
until both answer, then opens the browser. It checks your virtualenv,
`node_modules` and `.env` first and tells you what to run if one is missing.

> Batch, not PowerShell: Windows blocks `.ps1` files by default
> ("running scripts is disabled on this system"). `.bat` has no such
> restriction, so it works on a fresh machine with no setup.

---

## The manual way: two terminals

### Terminal 1 — backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — frontend

```powershell
cd frontend
npm run dev
```

Then open **http://localhost:5173**

| | URL |
|---|---|
| App | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs (interactive) | http://localhost:8000/docs |
| Health / capability report | http://localhost:8000/api/health |

Stop either with **Ctrl+C** in its terminal.

---

## Why `.\.venv\Scripts\python.exe` and not `activate`

Calling the venv's Python directly always works. `activate` can fail on
Windows with *"running scripts is disabled on this system"* (PowerShell
execution policy).

If you prefer activating:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

and if that is blocked, allow it once for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Opening it from your phone

`npm run dev` prints a **Network** URL, e.g.

```
Network: http://10.130.67.188:5173/
```

Open that on any device on the same Wi-Fi. Nothing else to configure — the
dev server proxies `/api` to the backend, so the browser only ever talks to
one origin.

The IP changes when you switch networks. Read the current one from the Vite
output, or:

```powershell
ipconfig | Select-String "IPv4"
```

> There is **no authentication yet**, so anyone on that network can use the
> workbench. Fine on your own Wi-Fi or a hotspot; do not leave it running on
> college or public Wi-Fi.

---

## Moving it to another machine

The scripts resolve their own folder, so the project runs from any path on
any drive. Two things must **not** be copied:

| Do not copy | Why |
|---|---|
| `backend/.venv/` | A virtualenv hard-codes absolute paths. Copied, it points at directories that do not exist on the other machine and breaks. |
| `frontend/node_modules/` | Large, and can contain platform-specific binaries. |

Also leave `.env` behind - it holds your API key. Your friend uses their own.

### Option A - zip it (no git needed)

On your machine, zip the project **excluding** those three, then on theirs:

1. Unzip anywhere - Desktop, `C:\projects`, any folder. Spaces are fine.
2. Double-click **`install.bat`**
3. Open `.env` and add a `GROQ_API_KEY`
4. Double-click **`start.bat`**

### Option B - git (better for a team)

```powershell
git init
git add .
git commit -m "SYNQ Workbench"
```

`.gitignore` already excludes `.venv`, `node_modules` and `.env`, so a clone
is automatically clean. Push to GitHub, then on their machine:

```powershell
git clone <your-repo-url>
cd <repo>
install.bat
```

Then send them your `.env` separately - git does not carry it, by design.
If anything looks wrong afterwards, `doctor.bat` says why.

When you push new work, they need `git pull` **and** `install.bat` again:
the pull brings the code, and the installer applies anything new to their
own database, which git does not carry either.

This is worth doing anyway - you are a team, and right now this project
exists in exactly one folder on one laptop.

---

## First time on a new machine

**Double-click `install.bat`** (or run it from a terminal).

It installs everything: the Python virtualenv and backend packages, the
frontend packages, a `.env` from the template, and the database with its
demo data. Safe to re-run - it skips what is already done and never
overwrites an existing `.env` or database.

You need these on PATH first; the installer checks and tells you if not:

- **Python 3.10+** - <https://python.org> (tick *"Add python.exe to PATH"*)
- **Node.js 20+** - <https://nodejs.org>

Afterwards, open `.env` and set your model provider:

```
MODEL_PROVIDER=groq
GROQ_API_KEY=...        # from console.groq.com
MODEL_NAME=...          # run start.bat, then GET /api/models
```

Document search needs none of that. Upload a `.txt`, `.md`, `.csv`, `.pdf`
or `.docx` on the Documents page and it is indexed straight away - keyword
retrieval is pure Python, so it works with no model, no key and no internet.

To add semantic search on top, point it at a local embedding runtime:

```
EMBEDDING_PROVIDER=local
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL=nomic-embed-text     # ollama pull nomic-embed-text
```

Restart the backend, then re-index existing documents (the **Re-index**
button on the Documents page) - passages indexed before this have no
vectors.

### Doing it by hand instead

Open a terminal **in the project folder**, then:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..

cd frontend
npm install
cd ..

copy .env.example .env
backend\.venv\Scripts\python.exe scripts\seed_db.py
```

---

## Something is wrong and you do not know what: run the doctor

**Double-click `doctor.bat`.**

Two people running the same code see different things for exactly four
reasons - the checkout, `.env`, the database, or the installed packages.
The doctor checks all four and prints the command that fixes whichever is
at fault:

```
[  OK ] on main at 50b5d4c
[  OK ] all current features are present in this checkout
[  OK ] .env exists
[ FAIL] SI-1 is missing
        This database was seeded by an older version, before SI-1
        existed. Re-seeding adds it and leaves your data alone.

  1 problem(s) found. Fix in this order:

    1. backend\.venv\Scripts\python.exe scripts\seed_db.py
```

It prints no API keys - only whether each one is set - so the output is safe
to paste into a chat when asking a teammate for help.

### "My teammate cloned it and the agents are missing"

Almost always one of two things, and the doctor tells you which:

- **Their checkout predates the feature.** `git pull`, then `install.bat`.
- **Their database was seeded by an older version.** The database is not in
  git - each machine builds its own - so a clone made before SI-1 existed
  has a database without it. Re-run the seed:

  ```powershell
  backend\.venv\Scripts\python.exe scripts\seed_db.py
  ```

  It is idempotent: it adds what is missing and leaves existing documents,
  users and agent settings alone.

Sharing your `.env` with them is fine and usually necessary - it is the one
file git deliberately does not carry - but it is not the fix for missing
agents. `.env` holds keys; the agents live in the database.

---

## Common problems

**Port already in use** — an old process is still holding it:

```powershell
netstat -ano | Select-String ":8000|:5173"
Stop-Process -Id <PID> -Force
```

**Frontend loads but everything is empty** — the backend is not running.
The app shows a red "Backend unreachable" bar with a Retry button.

**Chat replies with a 503** — no model configured. Check `.env` has
`MODEL_PROVIDER`, `MODEL_NAME` and `GROQ_API_KEY` set, then restart the
backend. `.env` is read at startup, so changes need a restart.

**A document sits on "Indexing…"** — indexing runs in the background and the
page polls for the result. If it never settles, check the backend log; the
document ends up as *"Indexing failed"* with the reason shown in the row.

**"No extractable text"** — the file has no text layer. Scanned PDFs and
images need OCR, which this deployment does not have. Legacy `.doc` needs
converting to `.docx` or `.pdf` first.

**The assistant will not cite my document** — check the Documents page says
*Indexed* with a chunk count. If it does, try the query against
`POST /api/search`, which searches the same passages without a model in the
way, and shows why an empty result was empty.

**A colleague cannot find my document** — check its folder. Uploads land in
**Personal Uploads**, which is private to you: nobody else can search it,
whatever their clearance. Open the document's settings (the gear on its row)
and move it into a shared folder you both belong to. The change takes effect
straight away; there is no need to re-index.

**"You are not assigned to X"** — you can only file a document into a folder
you are a member of. Ask someone with owner clearance to move it, since they
are unrestricted.

**Which model am I on?** — the pill in the top-right of the app, or:

```powershell
curl http://localhost:8000/api/health
curl http://localhost:8000/api/models   # what the provider can serve
```

---

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest

cd frontend
npm run lint
npm run build
```

Tests use a throwaway database — they never touch `data\synq_workbench.db`.
