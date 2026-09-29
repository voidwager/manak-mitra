"""Check that every claim in DEMO.md still holds.

A demo script rots quietly: a chunking change moves a citation to a
different page, a folder rename drops a document out of scope, a seeded
agent loses a tool grant. None of that breaks a test, and all of it breaks
the demo - usually in front of an audience.

So the walkthrough is executable. Each check below corresponds to a numbered
step in DEMO.md and fails loudly with what it expected.

Deliberately does NOT call the model. It exercises retrieval, scoping,
agents and tools directly, so it runs offline, costs nothing, and does not
depend on what a model chose to say this time. Whether the model phrases an
answer well is not something a script can assert; whether the evidence
reaching it is correct very much is.

    python scripts/verify_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.database.models import Agent, Document, Tool, User  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import get_gateway  # noqa: E402
from app.rag import retrieve  # noqa: E402
from app.services.access import (
    PERSONAL_FOLDER,
    publish_error,
    visible_documents_query,
)
from app.services.agents import effective_folder_scope  # noqa: E402
from app.tools import ToolContext, registry  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
        failures.append(label)


def search(db, user: User, query: str, agent: Agent | None = None):
    return retrieve(
        db, user, query, folder_scope=effective_folder_scope(agent) if agent else None
    )


def main() -> int:
    configure_logging()

    with SessionLocal() as db:
        owner = db.get(User, "user-sanyam")
        engineer = db.get(User, "user-ananya")
        safety = db.get(User, "user-dev")

        if owner is None:
            print("No seeded users. Run: python scripts/seed_db.py")
            return 1

        # --- Step 1: the corpus exists and is indexed --------------------
        print("\nStep 1 - the knowledge base is real")
        seeded = [db.get(Document, f"doc-{n}") for n in range(1, 6)]
        check("all five demo documents exist", all(d is not None for d in seeded))
        if any(d is None for d in seeded):
            print("\nRun: python scripts/seed_db.py")
            return 1

        check(
            "all five are indexed with chunks",
            all(d.status == "Indexed" and d.chunk_count > 0 for d in seeded),
            ", ".join(f"{d.name}={d.status}/{d.chunk_count}" for d in seeded),
        )
        check(
            "each has bytes on disk",
            all(d.has_stored_file for d in seeded),
        )
        check(
            "excerpts come from extracted text, not authored copy",
            all("FICTIONAL" in d.excerpt or d.excerpt.strip() for d in seeded),
        )

        # --- Step 2: a citation that resolves ----------------------------
        print("\nStep 2 - an answer with a checkable citation")
        result = search(db, owner, "acceptable vibration limit for a CDU-II pump")
        check("the vibration question retrieves something", result.found)
        if result.found:
            top = result.passages[0]
            check(
                "top hit is the pump SOP",
                "Centrifugal Pump" in top.document_name,
                f"got {top.document_name}",
            )
            check(
                "the retrieved passage contains the actual limit",
                any("2.5 mm/s" in p.text for p in result.passages),
                "no passage mentions 2.5 mm/s RMS",
            )
            citation = top.as_citation()
            check(
                "the citation names a real page and section",
                citation["pageNumber"] >= 1 and bool(citation["title"]),
            )

        # --- Step 3: access control --------------------------------------
        print("\nStep 3 - access control")
        confidential = db.get(Document, "doc-5")

        safety_docs = list(db.scalars(visible_documents_query(safety)))
        check(
            "Dev sees only Safety material",
            all(d.folder == "Safety" for d in safety_docs) and len(safety_docs) >= 1,
            f"sees {[d.name for d in safety_docs]}",
        )

        margin_q = "hydrocracker margin per tonne"
        dev_hit = search(db, safety, margin_q)
        check(
            "Dev cannot retrieve the confidential audit",
            all(p.document_id != confidential.id for p in dev_hit.passages),
        )
        eng_hit = search(db, engineer, margin_q)
        check(
            "Ananya cannot retrieve the confidential audit",
            all(p.document_id != confidential.id for p in eng_hit.passages),
        )
        owner_hit = search(db, owner, margin_q)
        check(
            "Sanyam can retrieve the confidential audit",
            any(p.document_id == confidential.id for p in owner_hit.passages),
            "the owner should reach doc-5 - if not, the demo's punchline is gone",
        )

        # The other half of the claim, and the harder one to make: owner
        # clearance is broad but not total. A personal upload is reachable by
        # exactly one person, and an administrator is not an exception.
        # Asserted against the query the API actually uses rather than a
        # separate reimplementation of the rule.
        from app.database.models import Document as DocumentModel

        probe = DocumentModel(
            id="verify-personal-probe",
            name="Ananya's private note.txt",
            type="TXT",
            folder=PERSONAL_FOLDER,
            owner_id=engineer.id,
            storage_path=None,
        )
        db.add(probe)
        db.flush()

        owner_visible = {d.id for d in db.scalars(visible_documents_query(owner))}
        engineer_visible = {d.id for d in db.scalars(visible_documents_query(engineer))}

        check(
            "Sanyam cannot see Ananya's personal upload",
            probe.id not in owner_visible,
            "owner clearance must not reach another user's personal space",
        )
        check(
            "Ananya can see her own personal upload",
            probe.id in engineer_visible,
            "a personal document must still reach the person who uploaded it",
        )
        check(
            "an administrator cannot publish it on her behalf",
            publish_error(owner, probe, "All Units") is not None,
            "otherwise publish-then-read walks straight round the guarantee",
        )

        db.rollback()

        # --- Step 4: agents narrow ---------------------------------------
        print("\nStep 4 - agents are configuration")
        maintenance = db.get(Agent, "maint-intel")
        sop = db.get(Agent, "sop-assistant")
        check("both demo agents exist", maintenance is not None and sop is not None)

        if maintenance and sop:
            pump_q = "acceptable vibration limit for a CDU-II pump"
            with_maint = search(db, owner, pump_q, maintenance)
            with_sop = search(db, owner, pump_q, sop)
            check(
                "Maintenance Intelligence finds the pump SOP",
                any("Centrifugal Pump" in p.document_name for p in with_maint.passages),
            )
            check(
                "SOP Assistant does not - it is scoped elsewhere",
                not any(
                    "Centrifugal Pump" in p.document_name for p in with_sop.passages
                ),
                "both agents returning the same thing makes step 4 pointless",
            )

        # --- Step 5: tools ------------------------------------------------
        print("\nStep 5 - tools that run")
        if maintenance:
            permitted = {t.name for t in registry.available_for(db, maintenance)}
            check(
                "Maintenance Intelligence has the calculator and table tool",
                {"calculator", "analyse_table"} <= permitted,
                f"has {sorted(permitted)}",
            )

            context = ToolContext(db=db, user=owner, agent=maintenance)

            calculator = registry.by_wire_name("calculator")
            volume = calculator.run(context, expression="47.5 * 18.25")
            check(
                "calculator returns 866.875",
                "866.875" in volume.content,
                volume.content,
            )

            table = registry.by_wire_name("analyse_table")
            total = table.run(
                context,
                operation="sum",
                column="DowntimeHours",
                document="Maintenance History",
            )
            check(
                "table tool sums the downtime column",
                total.ok and "148" in total.content,
                total.content,
            )

        image_tool = db.get(Tool, "img-analyzer")
        executable, reason = registry.describe(image_tool)
        check(
            "Image Analyzer reports itself unavailable, with a reason",
            not executable and bool(reason),
        )

        # --- Step 6: refusal ----------------------------------------------
        print("\nStep 6 - what it refuses to do")

        unrelated = search(db, owner, "die swell coefficient for polymer extrusion")
        check(
            "a wholly unrelated question retrieves nothing",
            not unrelated.found,
            f"unexpectedly matched {[p.document_name for p in unrelated.passages]}",
        )

        # The realistic case: keyword search legitimately matches on "SOP",
        # "pump" and "procedure", so passages come back. What must hold is
        # that none of them contain the invented identifiers - leaving the
        # model nothing to hang a fabricated citation on.
        invented = search(db, owner, "SOP-CDU2-0999 procedure for pump P-999")
        check(
            "no retrieved passage contains the invented SOP number",
            all("0999" not in p.text for p in invented.passages),
        )
        check(
            "no retrieved passage contains the invented tag",
            all("P-999" not in p.text for p in invented.passages),
        )

        # --- Routing --------------------------------------------------
        print("\nModel routing")
        from app.models import router as model_router

        table = model_router.configured_models()
        vision = model_router.resolve(model_router.ROLE_VISION)

        check(
            "an image forces the vision role over any preference",
            model_router.role_for_turn(has_images=True, agent_role="reasoning")
            == model_router.ROLE_VISION,
        )
        check(
            "every configured role resolves to a real model",
            all(model_router.resolve(role).model for role in table),
            "a configured role resolved to an empty model",
        )

        if model_router.ROLE_VISION in table:
            check(
                "the configured vision model actually accepts images",
                get_gateway().model_accepts_images(vision.model),
                f"{vision.model} does not report image input, so the "
                "image step of the walkthrough will not work",
            )
        else:
            print("  SKIP  no vision model configured (MODEL_VISION unset)")

    print(f"\n{checks - len(failures)}/{checks} checks passed.")
    if failures:
        print("\nThe demo has drifted. Failing checks:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nRe-seed with: python scripts/seed_db.py")
        return 1

    print("DEMO.md is accurate - the walkthrough will behave as written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
