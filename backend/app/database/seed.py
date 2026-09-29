"""Seed the database with the synthetic demo dataset.

Everything here is fictional. This project has no access to real SYNQ data;
the refinery, equipment tags, personnel and documents below are invented for
development and demonstration (see Phase 18 of the project plan).

Two honesty rules are enforced by this file:

1. No document claims an index it does not have. Seeded documents now
   carry real files and are genuinely indexed at seed time; the status is
   written by the indexer from what it actually produced, never asserted
   here. A document whose text could not be extracted stays un-indexed and
   says why.
2. Seeded assistant messages carry an explicit first activity-trace entry
   marking them as authored demo content rather than model output.

Idempotent: safe to run repeatedly, skips rows that already exist.
"""

import os
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.database import demo_corpus
from app.services.auth import set_password
from app.database.models import (
    Agent,
    AgentTool,
    Conversation,
    Document,
    DocumentStatus,
    Message,
    Notification,
    Tool,
    User,
    UserSettings,
)

log = get_logger(__name__)

#: Matches the upload route's filename sanitiser, so a seeded file and an
#: uploaded one are stored under the same convention.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

SEED_MARKER = {
    "label": "Seeded demo content - authored example, not model output",
    "status": "info",
}

# Agents do not pin a model. Per-agent model selection is model routing
# (Phase 14); until then every agent runs on whatever the gateway serves,
# and the API reports that actual model rather than a stored guess.
NO_PINNED_MODEL = ""


USERS = [
    dict(
        id="user-sanyam",
        name="Sanyam Jain",
        email="testowner@refinery.example",
        role="Owner / Plant Administrator",
        initials="SJ",
        access_level="OWNER",
        scope_label="Full access - entire knowledge base",
        assigned_folders=[
            "All Units",
            "CDU-II",
            "Hydrocracker",
            "Executive Confidential",
            "Safety",
        ],
        avatar_gradient="linear-gradient(135deg, #4F46E5, #06B6D4)",
    ),
    dict(
        id="user-ananya",
        name="Ananya Roy",
        email="testemployee@refinery.example",
        role="Maintenance Engineer",
        initials="AR",
        access_level="EMPLOYEE",
        scope_label="Restricted - CDU-II unit and personal uploads",
        assigned_folders=["CDU-II", "Personal Uploads"],
        avatar_gradient="linear-gradient(135deg, #10B981, #059669)",
    ),
    dict(
        id="user-dev",
        name="Dev Patel",
        email="testemployee2@refinery.example",
        role="HSE Safety Officer",
        initials="DP",
        access_level="EMPLOYEE",
        scope_label="Restricted - safety protocols and SOPs",
        assigned_folders=["Safety", "Personal Uploads"],
        avatar_gradient="linear-gradient(135deg, #F59E0B, #D97706)",
    ),
]

AGENTS = [
    dict(
        id="si-1",
        name="SI-1",
        description=(
            "The general assistant. Handles anything, and draws on the "
            "specialists below when a question needs one."
        ),
        model=NO_PINNED_MODEL,
        icon="Sparkles",
        capabilities=[
            "General assistance",
            "Document search",
            "Calculations",
            "Specialist routing",
        ],
        # Everything, because SI-1 borrows a specialist's grants when it
        # engages one and needs its own set for everything else.
        tool_ids=[
            "doc-search",
            "know-retrieval",
            "doc-reader",
            "data-analyzer",
            "calculator",
            "report-gen",
        ],
        # No scope: SI-1 searches whatever the signed-in user may see, and a
        # specialist narrows that further when one is engaged.
        folder_scope=[],
        is_universal=True,
    ),
    dict(
        id="maint-intel",
        name="Maintenance Intelligence",
        description="Analyse maintenance reports, equipment history and inspection information.",
        model=NO_PINNED_MODEL,
        icon="Wrench",
        # Stated focus areas: what this agent is *for*. Free text, and the
        # API reports it as `specialisations` rather than as capabilities,
        # because nothing verifies it. What the agent can actually do is
        # derived at request time from the runtime.
        capabilities=[
            "Telemetry Analysis",
            "Failure Diagnosis",
            "Predictive Maintenance",
            "Log Sheet Audit",
        ],
        tool_ids=[
            "doc-search",
            "know-retrieval",
            "doc-reader",
            "data-analyzer",
            "calculator",
            "report-gen",
        ],
        # Maintenance work lives in the unit folders, not in Safety or the
        # executive material - so this agent searches those and says so.
        folder_scope=["CDU-II", "Hydrocracker", "All Units"],
    ),
    dict(
        id="sop-assistant",
        name="SOP Assistant",
        description="Answer questions using approved standard operating procedures.",
        model=NO_PINNED_MODEL,
        icon="FileText",
        capabilities=[
            "SOP Lookup",
            "Safety Protocols",
            "Compliance Verification",
            "LOTO Guidance",
        ],
        tool_ids=["doc-search", "know-retrieval", "doc-reader"],
        folder_scope=["Safety", "All Units"],
    ),
    dict(
        id="doc-vision",
        name="Document Vision",
        description=(
            "Intended for industrial images, diagrams and schematics. The "
            "vision model this needs is not part of this deployment yet, so "
            "the agent reports itself as Limited and answers from text only."
        ),
        model=NO_PINNED_MODEL,
        icon="Eye",
        # These were previously presented as working capabilities next to a
        # deployment with no vision model and no OCR. They are the author's
        # intent for the agent, and the derived capability list marks the
        # vision half unavailable until Phase 13.
        capabilities=[
            "Schematic Audit",
            "Thermal Image Inspection",
            "Corrosion Assessment",
            "OCR Text Extraction",
        ],
        tool_ids=["img-analyzer", "doc-search", "doc-reader"],
        folder_scope=[],
    ),
]

TOOLS = [
    dict(
        id="doc-search",
        name="Document Search",
        category="Retrieval",
        description=(
            "Find which documents mention a topic, with a matching snippet "
            "from each. Scoped to what the signed-in user may see."
        ),
    ),
    dict(
        id="know-retrieval",
        name="Knowledge Retrieval",
        category="RAG",
        description=(
            "Read the exact passages that answer a question and attach them "
            "to the reply as citations. Scoped to the signed-in user."
        ),
    ),
    dict(
        id="doc-reader",
        name="Document Reader",
        category="Retrieval",
        description=(
            "Read one document end to end, in order, so questions about a "
            "document as a whole can be answered. Scoped to the signed-in user."
        ),
    ),
    dict(
        id="img-analyzer",
        name="Image Analyzer",
        category="Vision",
        description=(
            "Vision analysis of equipment photos and thermograms. Needs the "
            "image pipeline, which is not built yet (Phase 13)."
        ),
    ),
    dict(
        id="data-analyzer",
        name="Data Analyzer",
        category="Analytics",
        description=(
            "Counts, sums, averages and distinct values over an indexed CSV. "
            "Computed exactly rather than estimated by the model."
        ),
    ),
    dict(
        id="calculator",
        name="Calculator",
        category="Utility",
        description=(
            "Evaluate an arithmetic expression exactly - unit conversions, "
            "pressure drops, flow rates, tolerances."
        ),
    ),
    dict(
        id="report-gen",
        name="Report Generator",
        category="Output",
        description=(
            "Compile a structured inspection report, stamped with the real "
            "evidence trail: sources consulted, tools run, model used."
        ),
    ),
]

PUMP_SOP_EXCERPT = (
    "Section 4.2: Maintenance for Pump P-204 requires electrical lock-out "
    "tag-out (LOTO), mechanical seal flush verification, bearing housing oil "
    "level checks and vibration spectral analysis. Acceptable vibration: "
    "below 2.5 mm/s RMS. Operating temperature limit: 75 C."
)

DOCUMENTS = [
    dict(
        id="doc-1",
        source="centrifugal-pump-inspection-sop.txt",
        name="Centrifugal Pump Inspection SOP.pdf",
        type="PDF",
        folder="CDU-II",
        owner_id="user-sanyam",
        section="Section 4.2",
        page=12,
        excerpt=PUMP_SOP_EXCERPT,
    ),
    dict(
        id="doc-2",
        source="compressor-inspection-procedure.txt",
        name="Compressor Inspection Procedure.pdf",
        type="PDF",
        folder="CDU-II",
        owner_id="user-sanyam",
        section="Section 2.1",
        page=5,
        excerpt=(
            "Section 2.1: Multi-stage reciprocating compressor C-101 inspection "
            "requires suction filter differential pressure verification and "
            "intercooler condensation blowdown checks."
        ),
    ),
    dict(
        id="doc-3",
        source="equipment-safety-guidelines.txt",
        name="Equipment Safety Guidelines.pdf",
        type="PDF",
        folder="Safety",
        owner_id="user-sanyam",
        section="Section 1.4",
        page=18,
        excerpt=(
            "Section 1.4: PPE mandatory zones include crude distillation unit "
            "CDU-II, the hydrogen generation unit and high-pressure steam headers."
        ),
    ),
    dict(
        id="doc-4",
        source="maintenance-history.csv",
        name="Maintenance History.csv",
        type="CSV",
        folder="CDU-II",
        owner_id="user-ananya",
        section="Logs 2024-2026",
        page=1,
        excerpt=(
            "Date,TagID,Equipment,Action,Technician,Status\n"
            "2026-08-27,P-204,Centrifugal Pump,Seal Flush Cleaning,S. Jain,Completed\n"
            "2026-08-14,C-101,Compressor,Valve Replacement,A. Roy,Completed"
        ),
    ),
    dict(
        id="doc-5",
        source="hydrocracker-strategic-audit.txt",
        name="Hydrocracker Unit Strategic Audit.pdf",
        type="PDF",
        folder="Executive Confidential",
        owner_id="user-sanyam",
        is_confidential_owner_only=True,
        section="Section 1.0",
        page=1,
        excerpt=(
            "Strategic audit (fictional): demo refinery capacity 15 MMTPA. "
            "Hydrocracker unit HCU-I operating at 98.4 percent efficiency. "
            "Restricted to executive clearance."
        ),
    ),
]


#: Demo accounts ship with a known password so the workbench is usable out
#: of the box. That is fine on a developer's machine with a fictional
#: dataset, and unacceptable anywhere reachable: the seeded owner account
#: has full clearance, so a public deployment on a documented default
#: password hands every visitor plant-administrator access.
#:
#: So the default holds only in development. Everywhere else DEMO_PASSWORD
#: must be set explicitly, and seeding refuses rather than quietly shipping
#: credentials that are printed in this file.
DEFAULT_DEMO_PASSWORD = "demo1234"

#: Defaults this project has shipped before. A seeded account still carrying
#: one of these is moved to the current default.
#:
#: Without this, changing the default only affects machines seeded after the
#: change: an existing database keeps the old password while a fresh install
#: gets the new one, and the documented credentials are wrong on exactly one
#: of them. That is the drift `doctor.bat` exists to diagnose, and it is
#: avoidable here.
#:
#: Only a password that still matches a published default is replaced. One
#: somebody actually chose is left alone - the point is to retire credentials
#: nobody selected, not to overwrite a deliberate one.
SUPERSEDED_DEMO_PASSWORDS = ("workbench-demo",)


def _demo_password() -> str:
    configured = os.environ.get("DEMO_PASSWORD", "").strip()
    if configured:
        return configured

    if settings.app_env != "development":
        raise RuntimeError(
            "DEMO_PASSWORD must be set when APP_ENV is not 'development'. "
            "The built-in default is published in the source, and the seeded "
            "owner account has full clearance - seeding with it outside "
            "development would leave the deployment open to anyone who finds "
            "the URL."
        )
    return DEFAULT_DEMO_PASSWORD


#: Resolved when seeding runs rather than at import, so merely importing
#: this module cannot fail. The check belongs at the moment credentials are
#: about to be written, which is also where the error is actionable.


def _seed_users(db: Session) -> None:
    password = _demo_password()

    for payload in USERS:
        existing = db.get(User, payload["id"])
        if existing is not None:
            # Backfill: a database seeded before authentication existed has
            # users with no hash, and a user with no hash cannot sign in.
            if not existing.password_hash:
                set_password(db, existing, password)
                log.info("Set the demo password for %s", existing.id)

            # Retire a superseded default. Checked by verifying rather than
            # by comparing hashes, because the hash is salted - two hashes of
            # the same password never match as strings.
            elif any(
                verify_password(old, existing.password_hash)
                for old in SUPERSEDED_DEMO_PASSWORDS
            ):
                set_password(db, existing, password)
                log.info(
                    "Moved %s off a superseded demo password", existing.id
                )

            # Migrate the old default response style. It was never a choice
            # anyone made - it was what every account was seeded with, and it
            # is why answers read like a procedure manual. A style somebody
            # actually picked is left alone.
            row = db.scalars(
                select(UserSettings).where(UserSettings.user_id == existing.id)
            ).first()
            if row is not None and row.response_style == "Precise & Technical":
                row.response_style = "Balanced"
                log.info("Moved %s to the Balanced response style", existing.id)

            # Migrate the demo address. These are seeded accounts identified
            # by a fixed id, so the address is product configuration rather
            # than anything a person chose - and leaving it behind would mean
            # two machines running the same seed disagree about how to sign
            # in, which is exactly the drift the doctor script exists to
            # diagnose.
            if existing.email != payload["email"]:
                log.info(
                    "Updated the demo address for %s to %s",
                    existing.id,
                    payload["email"],
                )
                existing.email = payload["email"]
            continue
        user = User(password_hash=hash_password(password), **payload)
        db.add(user)
        db.flush()
        db.add(
            UserSettings(
                user_id=user.id,
                theme="system",
                model=NO_PINNED_MODEL,
                temperature=0.2,
                response_style="Balanced",
            )
        )


def _seed_tools(db: Session) -> None:
    for payload in TOOLS:
        existing = db.get(Tool, payload["id"])
        if existing is not None:
            # Name, category and description are product copy, not operator
            # data, so they are refreshed. The `enabled` flag is the
            # operator's and is never touched.
            existing.name = payload["name"]
            existing.category = payload["category"]
            existing.description = payload["description"]
            continue
        db.add(Tool(enabled=True, **payload))

    # Flush before agents are seeded. `_seed_agents` decides whether to grant
    # a tool with `db.get(Tool, tool_id)`, and a row still pending in this
    # session is not found by that lookup - so a tool introduced in the same
    # run as its grants was created and then granted to nobody. It corrected
    # itself on the *next* seed, which meant a fresh deployment shipped the
    # tool switched on and wired to no agent, and the model never saw it.
    db.flush()


def _seed_agents(db: Session) -> None:
    for payload in AGENTS:
        fields = {k: v for k, v in payload.items() if k != "tool_ids"}

        existing = db.get(Agent, fields["id"])
        if existing is not None:
            # Backfill only. `folder_scope` arrived in Phase 10, so a
            # database seeded before then has built-in agents with no scope
            # and they would all silently search everything. Filling an
            # *empty* scope is safe; anything already set is an operator's
            # decision and is left alone.
            if not existing.folder_scope and fields.get("folder_scope"):
                existing.folder_scope = fields["folder_scope"]
                log.info("Backfilled retrieval scope for agent %s", existing.id)

            # Tool grants shipped with a built-in agent are product
            # configuration. Adding a newly granted one is safe; nothing is
            # ever removed here, so an operator's revocation stands.
            # SI-1 arrived after these rows existed, so the flag needs
            # backfilling; everything else about a built-in agent is left
            # alone.
            if fields.get("is_universal") and not existing.is_universal:
                existing.is_universal = True
                log.info("Marked %s as the universal agent", existing.id)

            linked = {link.tool_id for link in existing.agent_tools}
            for tool_id in payload["tool_ids"]:
                if tool_id in linked or db.get(Tool, tool_id) is None:
                    continue
                db.add(AgentTool(agent_id=existing.id, tool_id=tool_id, enabled=True))
                log.info("Granted tool %s to agent %s", tool_id, existing.id)
            continue

        agent = Agent(
            status="Online",
            instructions="",
            is_system=True,
            retrieval_enabled=True,
            **fields,
        )
        db.add(agent)
        db.flush()

        for tool_id in payload["tool_ids"]:
            if db.get(Tool, tool_id):
                db.add(AgentTool(agent_id=agent.id, tool_id=tool_id, enabled=True))


def _materialise(document: Document, source: str) -> bool:
    """Write this document's file to the upload directory.

    Returns True when there are bytes on disk afterwards. The stored name
    follows the same `<id>__<safe stem><suffix>` convention uploads use, so
    nothing downstream has to special-case a seeded file.
    """
    suffix = Path(document.name).suffix.lower() or ".txt"
    stored_name = f"{document.id}__{_SAFE_NAME.sub('_', Path(document.name).stem)[:80]}{suffix}"
    destination = settings.upload_path / stored_name

    generated = demo_corpus.build(source, destination)
    if generated is None:
        return False

    document.storage_path = stored_name
    document.size_bytes = generated.size_bytes
    document.size = demo_corpus.human_size(generated.size_bytes)
    return True


def _seed_documents(db: Session) -> None:
    """Create the catalogue rows, write their files, and index them.

    Before Phase 18 these were rows with no bytes behind them, so a fresh
    checkout had nothing to retrieve and the assistant could cite nothing
    until somebody uploaded a file by hand. The pipeline was real; it just
    had no corpus.

    Indexing happens here rather than in the background: seeding is a
    command someone waits on, and a seeded database that is not searchable
    would defeat the point.
    """
    from app.rag.indexer import index_document  # local: avoids an import cycle

    today = date.today()

    for offset, payload in enumerate(DOCUMENTS):
        fields = {k: v for k, v in payload.items() if k != "source"}
        source = payload["source"]

        document = db.get(Document, fields["id"])
        if document is None:
            document = Document(
                status=DocumentStatus.READY,
                chunk_count=0,
                uploaded_date=today - timedelta(days=offset * 3),
                storage_path=None,
                size="",
                size_bytes=0,
                **fields,
            )
            db.add(document)
            db.flush()

        # Backfill: a database seeded before Phase 18 has these rows with no
        # file. Only fill in what is missing - a document someone has since
        # replaced or re-indexed is left alone.
        if document.storage_path and document.chunk_count:
            continue

        if not _materialise(document, source):
            continue

        db.flush()
        result = index_document(db, document)
        if result.ok:
            log.info(
                "Seeded and indexed %s (%s chunks)", document.id, result.chunk_count
            )
        else:
            log.warning(
                "Seeded %s but indexing did not succeed: %s",
                document.id,
                result.error or result.status,
            )


def _seed_conversations(db: Session) -> None:
    if db.scalars(select(Conversation).limit(1)).first():
        return

    conv = Conversation(
        id="conv-demo-p204",
        title="Pump P-204 inspection procedure",
        user_id="user-sanyam",
        agent_id="maint-intel",
        agent_name="Maintenance Intelligence",
    )
    db.add(conv)
    db.flush()

    db.add(
        Message(
            id="msg-demo-1",
            conversation_id=conv.id,
            sender="user",
            text="What is the recommended inspection procedure for centrifugal pump P-204?",
            position=1,
        )
    )
    db.add(
        Message(
            id="msg-demo-2",
            conversation_id=conv.id,
            sender="assistant",
            text=(
                "The inspection procedure for centrifugal pump P-204 is:\n\n"
                "1. Verify isolation and safety clearance (LOTO locks applied)\n"
                "2. Check for leaks around seals and gaskets\n"
                "3. Inspect bearing temperature and vibration "
                "(limits: below 75 C, below 2.5 mm/s RMS)\n"
                "4. Validate alignment and coupling condition\n"
                "5. Record all observations in the log sheet"
            ),
            position=2,
            source={
                "title": "Centrifugal Pump Inspection SOP.pdf",
                "page": "Page 12 - Section 4.2",
                "section": "Section 4.2",
                "excerpt": PUMP_SOP_EXCERPT,
            },
            activity_trace=[
                SEED_MARKER,
                {"label": "Task received", "status": "done"},
                {"label": "Retrieved SOP Section 4.2", "status": "done"},
                {"label": "Generated evidence-backed response", "status": "done"},
            ],
        )
    )


def _seed_notifications(db: Session) -> None:
    if db.scalars(select(Notification).limit(1)).first():
        return

    db.add(
        Notification(
            id="notif-welcome",
            user_id=None,
            title="Workbench connected to the database",
            description=(
                "Agents, documents, tools and conversations are served from the API. "
                "Model inference and document indexing are not implemented yet."
            ),
            read=False,
        )
    )


def seed(db: Session) -> None:
    _seed_users(db)
    _seed_tools(db)
    _seed_agents(db)
    _seed_documents(db)
    _seed_conversations(db)
    _seed_notifications(db)
    db.commit()
    log.info("Seed complete (synthetic demo dataset)")
