"""Why does the workbench look wrong on this machine?

Run from the repository root:

    backend\\.venv\\Scripts\\python.exe scripts\\doctor.py

Checks the four things that actually differ between two machines running the
same code - the checkout, the .env, the database, and the installed packages
- and prints the specific command that fixes whatever is wrong.

Prints no secrets. Keys are reported as present or missing, never by value,
so the output is safe to paste into a chat when asking for help.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

OK = "  OK "
BAD = " FAIL"
WARN = " WARN"

problems: list[str] = []


def report(state: str, label: str, detail: str = "") -> None:
    print(f"[{state}] {label}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")


def fail(label: str, detail: str, fix: str) -> None:
    report(BAD, label, detail)
    problems.append(fix)


def run(*args: str) -> str:
    try:
        out = subprocess.run(
            args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=20
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
print()
print("  SYNQ Workbench - doctor")
print("  ==========================")
print(f"  repo: {REPO_ROOT}")
print()

# --- 1. the checkout -------------------------------------------------------
print("1. Checkout")

commit = run("git", "rev-parse", "--short", "HEAD")
branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
if commit:
    report(OK, f"on {branch or '?'} at {commit}")
else:
    report(WARN, "not a git checkout", "Downloaded as a ZIP? Prefer 'git clone' so you can pull updates.")

# The single most common cause of "my screen looks different": running code
# from before a feature landed. Check for the files rather than the commit,
# because a ZIP download has no history to compare against.
MARKERS = {
    "SI-1 specialist routing": REPO_ROOT / "backend/app/services/dispatch.py",
    "multi-provider registry": REPO_ROOT / "backend/app/models/registry.py",
    "Gemini provider": REPO_ROOT / "backend/app/models/providers/gemini.py",
    "per-chat model menu": REPO_ROOT / "frontend/src/components/chat/ChatSettingsMenu.jsx",
}
missing = [name for name, path in MARKERS.items() if not path.exists()]
if missing:
    fail(
        "checkout is out of date",
        "Missing: " + ", ".join(missing),
        "git pull            # then re-run install.bat",
    )
else:
    report(OK, "all current features are present in this checkout")

if commit:
    behind = run("git", "rev-list", "--count", "HEAD..@{u}")
    if behind.isdigit() and int(behind) > 0:
        fail(
            f"{behind} commit(s) behind the remote",
            "Someone has pushed work this checkout does not have.",
            "git pull",
        )

print()

# --- 2. configuration ------------------------------------------------------
print("2. Configuration (.env)")

env_file = REPO_ROOT / ".env"
if not env_file.exists():
    fail(
        ".env is missing",
        "The app falls back to defaults and cannot reach any model.",
        "copy .env.example .env      # then add your API keys",
    )
else:
    report(OK, ".env exists")
    # Names only. Never print a value - this output gets pasted into chats.
    present, empty = [], []
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        (present if value.strip() else empty).append(key.strip())

    for key in ("MODEL_PROVIDER", "MODEL_NAME"):
        if key not in present:
            fail(
                f"{key} is not set",
                "Without it the workbench runs with inference disabled.",
                f"Set {key} in .env",
            )

    if "GROQ_API_KEY" not in present and "GEMINI_API_KEY" not in present:
        fail(
            "no provider API key is set",
            "Agents will appear but every question fails.",
            "Add GROQ_API_KEY (and optionally GEMINI_API_KEY) to .env",
        )
    else:
        keys = [k for k in ("GROQ_API_KEY", "GEMINI_API_KEY") if k in present]
        report(OK, f"provider key present: {', '.join(keys)}")

    if empty:
        report(WARN, f"set but empty: {', '.join(sorted(empty))}")

print()

# --- 3. the database -------------------------------------------------------
print("3. Database")

try:
    from app.core.config import settings

    url = settings.effective_database_url
except Exception as exc:  # configuration itself is broken
    fail(
        "could not read configuration",
        f"{type(exc).__name__}: {exc}",
        "Re-run install.bat",
    )
    url = ""

if url.startswith("sqlite:///"):
    db_path = Path(url.replace("sqlite:///", ""))
    print(f"       {db_path}")

    if not db_path.exists():
        fail(
            "database file does not exist",
            "Nothing has been seeded, so the app has no agents, users or documents.",
            r"backend\.venv\Scripts\python.exe scripts\seed_db.py",
        )
    else:
        db = sqlite3.connect(db_path)
        try:
            tables = {
                r[0] for r in db.execute("select name from sqlite_master where type='table'")
            }
            if "agents" not in tables:
                fail(
                    "tables are missing",
                    "The database file exists but was never initialised.",
                    r"backend\.venv\Scripts\python.exe scripts\seed_db.py",
                )
            else:
                agents = list(
                    db.execute("select id, name, status, is_universal from agents")
                )
                users = db.execute("select count(*) from users").fetchone()[0]
                docs = db.execute("select count(*) from documents").fetchone()[0]

                if not agents:
                    fail(
                        "no agents in the database",
                        "The database was created but never seeded.",
                        r"backend\.venv\Scripts\python.exe scripts\seed_db.py",
                    )
                else:
                    report(OK, f"{len(agents)} agent(s), {users} user(s), {docs} document(s)")
                    for agent_id, name, status, universal in agents:
                        tag = "  <- SI-1, the universal assistant" if universal else ""
                        print(f"        {name} ({agent_id}, {status}){tag}")

                    if not any(u for _, _, _, u in agents):
                        fail(
                            "SI-1 is missing",
                            "This database was seeded by an older version, before SI-1\n"
                            "existed. Re-seeding adds it and leaves your data alone.",
                            r"backend\.venv\Scripts\python.exe scripts\seed_db.py",
                        )
                if users == 0:
                    fail(
                        "no users - you cannot sign in",
                        "",
                        r"backend\.venv\Scripts\python.exe scripts\seed_db.py",
                    )
        finally:
            db.close()
else:
    report(OK, "using an external database (not SQLite)")

print()

# --- 4. installed packages -------------------------------------------------
print("4. Packages")

venv_python = REPO_ROOT / "backend/.venv/Scripts/python.exe"
if not venv_python.exists():
    venv_python = REPO_ROOT / "backend/.venv/bin/python"

if not venv_python.exists():
    fail("backend virtualenv is missing", "", "install.bat")
else:
    report(OK, "backend virtualenv exists")
    try:
        import fastapi  # noqa: F401
        import sqlalchemy  # noqa: F401

        report(OK, "backend packages import")
    except ImportError as exc:
        fail(
            "backend packages are missing",
            str(exc),
            r"backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt",
        )

if not (REPO_ROOT / "frontend/node_modules").exists():
    fail(
        "frontend packages are missing",
        "The UI will not start.",
        "cd frontend && npm install",
    )
else:
    report(OK, "frontend packages installed")

print()

# --- verdict ---------------------------------------------------------------
print("  ==========================================================")
if not problems:
    print("  Everything checks out.")
    print()
    print("  If the UI still looks wrong:")
    print("    - hard-refresh the browser (Ctrl+Shift+R)")
    print("    - make sure you are signed in; agents require a session")
    print("    - restart with stop.bat then start.bat")
else:
    # install.bat is the umbrella fix - it creates the venv, installs both
    # sides, writes .env and seeds. When it is on the list at all it belongs
    # first, or the reader works through steps it would have done for them.
    ordered = list(dict.fromkeys(problems))
    ordered.sort(key=lambda fix: 0 if fix.strip() == "install.bat" else 1)

    print(f"  {len(ordered)} problem(s) found. Fix in this order:")
    print()
    for i, fix in enumerate(ordered, 1):
        print(f"    {i}. {fix}")
print("  ==========================================================")
print()

sys.exit(1 if problems else 0)
