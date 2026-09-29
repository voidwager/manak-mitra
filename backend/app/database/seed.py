"""Seed the database with the BIS helpdesk dataset.

The knowledge base is real: public BIS material captured from bis.gov.in and
pib.gov.in, each file carrying its source URL and retrieval date (see
data/bis/source/MANIFEST.md). The staff accounts and the three internal desk
documents are fictional and say so - they exist to demonstrate access
control, since no real BIS internal data belongs in a demo.

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
        email="admin@bis-helpdesk.example",
        role="Helpdesk Administrator",
        initials="SJ",
        access_level="OWNER",
        scope_label="Full access - public sources, every desk, internal reports",
        assigned_folders=[
            "Certification Desk",
            "Hallmarking Desk",
            "BIS Internal",
        ],
        avatar_gradient="linear-gradient(135deg, #1E3A8A, #0EA5E9)",
    ),
    dict(
        id="user-ananya",
        name="Ananya Roy",
        email="certification@bis-helpdesk.example",
        role="Certification Officer",
        initials="AR",
        access_level="EMPLOYEE",
        scope_label="Public sources + Certification Desk",
        assigned_folders=["Certification Desk", "Personal Uploads"],
        avatar_gradient="linear-gradient(135deg, #10B981, #059669)",
    ),
    dict(
        id="user-dev",
        name="Dev Patel",
        email="hallmarking@bis-helpdesk.example",
        role="Hallmarking Officer",
        initials="DP",
        access_level="EMPLOYEE",
        scope_label="Public sources + Hallmarking Desk",
        assigned_folders=["Hallmarking Desk", "Personal Uploads"],
        avatar_gradient="linear-gradient(135deg, #F59E0B, #D97706)",
    ),
]

#: Every retrieval tool, for agents that should be able to read anything
#: their scope allows.
_READING_TOOLS = ["doc-search", "know-retrieval", "doc-reader"]

AGENTS = [
    dict(
        id="si-1",
        name="Manak Mitra",
        description=(
            "The general helpdesk. Answers anything about Indian Standards and "
            "BIS services, and draws on the specialists below when a question "
            "needs one."
        ),
        model=NO_PINNED_MODEL,
        icon="Sparkles",
        capabilities=[
            "Plain-language answers",
            "Hindi and regional languages",
            "Cited BIS sources",
            "Specialist routing",
        ],
        # Everything, because the universal agent borrows a specialist's
        # grants when it engages one and needs its own set for everything else.
        tool_ids=[
            *_READING_TOOLS,
            "standard-finder",
            "data-analyzer",
            "calculator",
            "report-gen",
        ],
        # No scope: searches whatever the caller may see, and a specialist
        # narrows that further when one is engaged.
        folder_scope=[],
        is_universal=True,
    ),
    dict(
        id="standards-finder",
        name="Standards Finder",
        description=(
            "Finds which Indian Standard, Quality Control Order and scheme apply "
            "to a product from BIS's published lists, and explains what an IS "
            "number means."
        ),
        model=NO_PINNED_MODEL,
        icon="Search",
        # Stated focus areas: what this agent is *for*. Free text, reported
        # as `specialisations`; what it can actually do is derived at
        # request time from the runtime.
        capabilities=[
            "Product to IS number",
            "Compulsory certification (QCO) check",
            "CRS electronics list",
            "Standard lookup by IS number",
        ],
        tool_ids=[*_READING_TOOLS, "standard-finder"],
        folder_scope=["Standards & QCOs"],
    ),
    dict(
        id="certification-guide",
        name="Certification Guide",
        description=(
            "Explains BIS certification schemes - the ISI mark (Scheme-I), the "
            "Compulsory Registration Scheme, the Foreign Manufacturers scheme - "
            "and walks through documents, fees, timelines and licence rules."
        ),
        model=NO_PINNED_MODEL,
        icon="FileText",
        capabilities=[
            "ISI mark licensing",
            "CRS registration (R-number)",
            "Foreign manufacturers (FMCS)",
            "Fees and timelines",
        ],
        tool_ids=[*_READING_TOOLS, "standard-finder", "calculator"],
        folder_scope=["Certification Schemes", "BIS Act & Rules", "Standards & QCOs"],
    ),
    dict(
        id="hallmark-helper",
        name="Hallmarking & Consumer Help",
        description=(
            "Helps consumers with hallmarked gold and silver - HUID, caratage, "
            "testing your own jewellery, compensation - and with complaints "
            "about a fake ISI mark or hallmark."
        ),
        model=NO_PINNED_MODEL,
        icon="Gem",
        capabilities=[
            "Verify a HUID",
            "Mandatory hallmarking districts",
            "Purity shortfall compensation",
            "Filing a complaint",
        ],
        tool_ids=[*_READING_TOOLS, "calculator"],
        folder_scope=["Hallmarking", "Consumer Help", "BIS Act & Rules"],
    ),
    dict(
        id="lab-locator",
        name="Lab Locator",
        description=(
            "Finds BIS laboratories and BIS-recognised testing labs by state, "
            "and explains how BIS recognises a lab."
        ),
        model=NO_PINNED_MODEL,
        icon="FlaskConical",
        capabilities=[
            "Recognised labs by state",
            "BIS's own laboratories",
            "Labs for CRS products",
            "Lab recognition process",
        ],
        tool_ids=[*_READING_TOOLS],
        folder_scope=["Laboratories"],
    ),
    dict(
        id="doc-vision",
        name="Mark & Label Reader",
        description=(
            "Intended for photos of product labels, ISI marks and hallmarks. "
            "The vision model this needs is not part of every deployment, so "
            "without one the agent reports itself as Limited and answers from "
            "text only."
        ),
        model=NO_PINNED_MODEL,
        icon="Eye",
        # The author's intent; the derived capability list marks the vision
        # half unavailable until a vision model is configured.
        capabilities=[
            "Read an ISI mark and licence number",
            "Read a HUID from a photo",
            "Read a CRS R-number",
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
            "Find which BIS documents mention a topic, with a matching snippet "
            "from each. Scoped to what the caller may see."
        ),
    ),
    dict(
        id="know-retrieval",
        name="Knowledge Retrieval",
        category="RAG",
        description=(
            "Read the exact passages that answer a question and attach them "
            "to the reply as citations. Scoped to the caller."
        ),
    ),
    dict(
        id="doc-reader",
        name="Document Reader",
        category="Retrieval",
        description=(
            "Read one document end to end, in order, so questions about a "
            "document as a whole can be answered. Scoped to the caller."
        ),
    ),
    dict(
        id="standard-finder",
        name="Standard Finder",
        category="Standards",
        description=(
            "Match a product description to the rows of BIS's published lists "
            "of products under compulsory certification - IS number, Quality "
            "Control Order and scheme - each row cited."
        ),
    ),
    dict(
        id="img-analyzer",
        name="Image Analyzer",
        category="Vision",
        description=(
            "Read marks and labels from a photo. Needs a vision model, which "
            "is not configured on every deployment."
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
            "Evaluate an arithmetic expression exactly - fees, testing "
            "charges, purity shortfall compensation."
        ),
    ),
    dict(
        id="report-gen",
        name="Report Generator",
        category="Output",
        description=(
            "Compile a structured compliance summary, stamped with the real "
            "evidence trail: sources consulted, tools run, model used."
        ),
    ),
]

#: Quoted in the seeded example conversation. Taken verbatim from the
#: Hallmarking consumer-protection page captured in file 09.
HUID_EXCERPT = (
    "BIS CARE- The Official mobile application of BIS now has the provision "
    "for the common consumers to verify the authenticity of Hallmarked gold "
    "jewellery items bearing a HUID number. The “Verify HUID” "
    "feature can be utilised to verify the purity of the jewellery articles "
    "before purchase."
)

#: Owner of the published corpus: public material is filed by the
#: administrator, the one clearance allowed to publish into public folders.
_PUBLISHER = "user-sanyam"


def _public(doc_id: str, source: str, name: str, folder: str) -> dict:
    return dict(
        id=doc_id,
        source=f"bis/source/{source}",
        name=name,
        type="MD",
        folder=folder,
        owner_id=_PUBLISHER,
        section="",
        page=1,
        excerpt="",
    )


#: The published knowledge base. Every file under data/bis/source is public
#: BIS material, with its source URL and retrieval date in its own header.
DOCUMENTS = [
    _public("bis-01", "01_scheme-I_ISI-mark_product-certification.md",
            "Scheme-I (ISI Mark) Product Certification.md", "Certification Schemes"),
    _public("bis-02", "02_fmcs_foreign-manufacturers-certification-scheme.md",
            "Foreign Manufacturers Certification Scheme (FMCS).md", "Certification Schemes"),
    _public("bis-03", "03_crs_compulsory-registration-scheme.md",
            "Compulsory Registration Scheme (CRS).md", "Certification Schemes"),
    _public("bis-04", "04_crs_product-list_IS-numbers.md",
            "CRS Product List with IS Numbers.md", "Standards & QCOs"),
    _public("bis-05", "05_qco_compulsory_certification_scheme-I_product-IS-list.md",
            "Products under Compulsory Certification - Scheme-I.md", "Standards & QCOs"),
    _public("bis-06", "06_qco_compulsory_certification_scheme-X_product-IS-list.md",
            "Products under Compulsory Certification - Scheme-X.md", "Standards & QCOs"),
    _public("bis-07", "07_eco-mark_scheme.md",
            "ECO Mark Scheme.md", "Certification Schemes"),
    _public("bis-08", "08_hallmarking_overview_faq_HUID_grades_charges.md",
            "Hallmarking Overview and FAQ.md", "Hallmarking"),
    _public("bis-09", "09_hallmarking_consumer_verify-HUID_test-own-jewellery_fees.md",
            "Hallmarking for Consumers - HUID, Testing, Compensation.md", "Hallmarking"),
    _public("bis-10", "10_hallmarking_mandatory-districts_by-phase.md",
            "Mandatory Hallmarking Districts by Phase.md", "Hallmarking"),
    _public("bis-11", "11_hallmarking_PIB-press-releases_HUID_fake-hallmark.md",
            "Hallmarking Press Releases (PIB).md", "Hallmarking"),
    _public("bis-12", "12_lab-recognition-scheme_how-BIS-recognises-labs.md",
            "Laboratory Recognition Scheme.md", "Laboratories"),
    _public("bis-13", "13_lab-directory_BIS-labs_and_CRS-recognised-lab-IS-list.md",
            "BIS Laboratories Directory.md", "Laboratories"),
    _public("bis-14", "14_lab-directory_BIS-recognised-labs_Group1_Group2_lists.md",
            "BIS Recognised Laboratories (Group-1 and Group-2).md", "Laboratories"),
    _public("bis-15", "15_consumer_complaints_BIS-CARE_fake-ISI-mark_misuse.md",
            "Consumer Complaints and BIS CARE.md", "Consumer Help"),
    _public("bis-16", "16_bis-act-2016_key-sections_offences-penalties-standard-mark.md",
            "BIS Act 2016 - Key Sections.md", "BIS Act & Rules"),
    _public("bis-17", "17_bis-conformity-assessment-regulations-2018_licence-conditions_scheme-I_scheme-II.md",
            "BIS Conformity Assessment Regulations 2018.md", "BIS Act & Rules"),
    _public("bis-18", "18_standards-basics_IS-number_Know-Your-Standard_buying-standards.md",
            "Standards Basics - IS Numbers and Buying Standards.md", "Standards & QCOs"),
    _public("bis-19", "19_standards-clubs_PIB.md",
            "Standards Clubs (PIB).md", "Standards & QCOs"),
    # --- Staff-only samples. Fictional, and each file says so in its first
    # lines. They exist to demonstrate that desk and internal material never
    # reaches a public answer; there is no real BIS internal data here.
    dict(
        id="int-cert",
        source="bis/internal/certification-desk-escalation-guide.md",
        name="Certification Desk Escalation Guide (sample).md",
        type="MD",
        folder="Certification Desk",
        owner_id="user-ananya",
        section="",
        page=1,
        excerpt="",
    ),
    dict(
        id="int-hallmark",
        source="bis/internal/hallmarking-desk-complaint-register.csv",
        name="Hallmarking Complaint Register (sample).csv",
        type="CSV",
        folder="Hallmarking Desk",
        owner_id="user-dev",
        section="",
        page=1,
        excerpt="",
    ),
    dict(
        id="int-analytics",
        source="bis/internal/helpdesk-analytics-q2-2026.md",
        name="Helpdesk Query Analytics Q2 2026 (sample).md",
        type="MD",
        folder="BIS Internal",
        owner_id="user-sanyam",
        is_confidential_owner_only=True,
        section="",
        page=1,
        excerpt="",
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
        id="conv-demo-huid",
        title="Checking a gold hallmark",
        user_id="user-sanyam",
        agent_id="hallmark-helper",
        agent_name="Hallmarking & Consumer Help",
    )
    db.add(conv)
    db.flush()

    db.add(
        Message(
            id="msg-demo-1",
            conversation_id=conv.id,
            sender="user",
            text="How can I check that the hallmark on a gold chain is genuine before I buy it?",
            position=1,
        )
    )
    db.add(
        Message(
            id="msg-demo-2",
            conversation_id=conv.id,
            sender="assistant",
            text=(
                "Look for the HUID number in the hallmark and check it in the "
                "BIS CARE app before you pay. Its \"Verify "
                "HUID\" feature lets any consumer confirm the authenticity and "
                "purity of a hallmarked gold article [1].\n\n"
                "If the jewellery later tests below the purity it is marked "
                "with, you are entitled to compensation of two times the "
                "difference for the shortfall, plus the testing charges [1]."
            ),
            position=2,
            source={
                "title": "Hallmarking for Consumers - HUID, Testing, Compensation.md",
                "page": "Page 1 · Hallmarking - Consumer Protection",
                "section": "Hallmarking - Consumer Protection",
                "excerpt": HUID_EXCERPT,
            },
            activity_trace=[
                SEED_MARKER,
                {"label": "Task received", "status": "done"},
                {"label": "Retrieved Hallmarking - Consumer Protection", "status": "done"},
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
            title="Welcome to Manak Mitra",
            description=(
                "Answers come from published BIS material, each one cited. "
                "Ask in English, Hindi or your own language."
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
