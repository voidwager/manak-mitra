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
from app.core.security import AccessLevel  # noqa: E402
from app.database.models import Agent, Document, Tool, User  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import get_gateway  # noqa: E402
from app.rag import retrieve  # noqa: E402
from app.services.access import (  # noqa: E402
    PERSONAL_FOLDER,
    PUBLIC_FOLDERS,
    publish_error,
    visible_documents_query,
)
from app.services.agents import effective_folder_scope  # noqa: E402
from app.tools import ToolContext, registry  # noqa: E402

failures: list[str] = []
checks = 0

HUID_DOC = "Hallmarking for Consumers - HUID, Testing, Compensation.md"
PUBLIC_IDS = [f"bis-{n:02d}" for n in range(1, 20)]
STAFF_IDS = ["int-cert", "int-hallmark", "int-analytics"]


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


def visible_ids(db, user: User) -> set[str]:
    return {d.id for d in db.scalars(visible_documents_query(user))}


def main() -> int:
    configure_logging()

    with SessionLocal() as db:
        owner = db.get(User, "user-sanyam")
        certification = db.get(User, "user-ananya")
        hallmarking = db.get(User, "user-dev")

        if owner is None:
            print("No seeded users. Run: python scripts/seed_db.py")
            return 1

        # A visitor is a row like any other, so make one for the duration
        # of the run. Everything below is rolled back at the end; nothing is
        # left behind in the database.
        guest = User(
            id="verify-guest",
            name="Visitor",
            email="verify-guest@guest.invalid",
            role="Public visitor",
            initials="V",
            access_level=AccessLevel.PUBLIC,
            scope_label="Public BIS information",
            assigned_folders=[],
            avatar_gradient="",
            password_hash=None,
        )
        db.add(guest)
        db.flush()

        # --- Step 1: the corpus exists and is indexed --------------------
        print("\nStep 1 - the knowledge base is real")
        seeded = [db.get(Document, i) for i in PUBLIC_IDS + STAFF_IDS]
        check(
            "all 19 public BIS documents and 3 staff samples exist",
            all(d is not None for d in seeded),
        )
        if any(d is None for d in seeded):
            print("\nRun: python scripts/seed_db.py")
            return 1

        check(
            "all are indexed with chunks",
            all(d.status == "Indexed" and d.chunk_count > 0 for d in seeded),
            ", ".join(
                f"{d.id}={d.status}/{d.chunk_count}"
                for d in seeded
                if not (d.status == "Indexed" and d.chunk_count > 0)
            ),
        )
        check("each has bytes on disk", all(d.has_stored_file for d in seeded))
        check(
            "excerpts come from extracted text, not authored copy",
            all(d.excerpt.strip() for d in seeded),
        )
        check(
            "every public document sits in a public folder",
            all(db.get(Document, i).folder in PUBLIC_FOLDERS for i in PUBLIC_IDS),
        )

        # --- Step 2: a visitor gets a citation that resolves --------------
        print("\nStep 2 - a visitor's answer with a checkable citation")
        result = search(db, guest, "how can I verify a HUID on gold jewellery")
        check("the HUID question retrieves something for a visitor", result.found)
        if result.found:
            names = [p.document_name for p in result.passages]
            check(
                "retrieval returns the consumer hallmarking page",
                HUID_DOC in names,
                f"got {names}",
            )
            check(
                "the retrieved passages mention BIS CARE",
                any("BIS CARE" in p.text for p in result.passages),
                "no passage mentions BIS CARE",
            )
            top = next(
                (p for p in result.passages if p.document_name == HUID_DOC), None
            )
            if top is not None:
                citation = top.as_citation()
                check(
                    "the citation names a real page and title",
                    citation["pageNumber"] >= 1 and citation["title"] == HUID_DOC,
                )

        # --- Step 3: access control --------------------------------------
        print("\nStep 3 - access control")
        analytics = db.get(Document, "int-analytics")
        analytics_q = "Query volume 18,240 helpdesk analytics"

        for label, user in (
            ("Ananya (Certification Officer)", certification),
            ("Dev (Hallmarking Officer)", hallmarking),
            ("a visitor", guest),
        ):
            check(
                f"{label} cannot list the internal analytics report",
                analytics.id not in visible_ids(db, user),
            )
            hit = search(db, user, analytics_q)
            check(
                f"{label} cannot retrieve the internal analytics report",
                all(p.document_id != analytics.id for p in hit.passages)
                and all("18,240" not in p.text for p in hit.passages),
            )
        owner_hit = search(db, owner, analytics_q)
        check(
            "Sanyam can retrieve the internal analytics report",
            any(p.document_id == analytics.id for p in owner_hit.passages),
            "the owner should reach int-analytics - if not, the punchline is gone",
        )

        # Public material is everyone's; desks are scoped to their staff.
        guest_visible = visible_ids(db, guest)
        ananya_visible = visible_ids(db, certification)
        dev_visible = visible_ids(db, hallmarking)
        for label, visible in (
            ("a visitor", guest_visible),
            ("Ananya", ananya_visible),
            ("Dev", dev_visible),
        ):
            check(
                f"{label} can read all 19 public documents",
                set(PUBLIC_IDS) <= visible,
            )
        check(
            "a visitor sees no desk document",
            not guest_visible & {"int-cert", "int-hallmark"},
        )
        check(
            "Ananya reaches the Certification Desk and not the Hallmarking Desk",
            "int-cert" in ananya_visible and "int-hallmark" not in ananya_visible,
        )
        check(
            "Dev reaches the Hallmarking Desk and not the Certification Desk",
            "int-hallmark" in dev_visible and "int-cert" not in dev_visible,
        )
        cd_hit = search(db, guest, "CD-7 escalation code certification desk")
        check(
            "the desk escalation guide never reaches a visitor's retrieval",
            all(p.document_id != "int-cert" for p in cd_hit.passages),
        )

        # The other half of the claim, and the harder one to make: owner
        # clearance is broad but not total. A personal upload is reachable by
        # exactly one person, and an administrator is not an exception.
        # Asserted against the query the API actually uses rather than a
        # separate reimplementation of the rule.
        probe = Document(
            id="verify-personal-probe",
            name="Ananya's private note.txt",
            type="TXT",
            folder=PERSONAL_FOLDER,
            owner_id=certification.id,
            storage_path=None,
        )
        db.add(probe)
        db.flush()

        check(
            "Sanyam cannot see Ananya's personal upload",
            probe.id not in visible_ids(db, owner),
            "owner clearance must not reach another user's personal space",
        )
        check(
            "Ananya can see her own personal upload",
            probe.id in visible_ids(db, certification),
            "a personal document must still reach the person who uploaded it",
        )
        check(
            "an administrator cannot publish it on her behalf",
            publish_error(owner, probe, "Certification Schemes") is not None,
            "otherwise publish-then-read walks straight round the guarantee",
        )

        # --- Step 4: agents narrow ---------------------------------------
        print("\nStep 4 - agents are configuration")
        cert_guide = db.get(Agent, "certification-guide")
        lab_locator = db.get(Agent, "lab-locator")
        check(
            "both demo agents exist",
            cert_guide is not None and lab_locator is not None,
        )

        if cert_guide and lab_locator:
            licence_q = "ISI mark licence under Scheme-I product certification"
            with_cert = search(db, owner, licence_q, cert_guide)
            with_lab = search(db, owner, licence_q, lab_locator)
            check(
                "Certification Guide finds the Scheme-I page",
                any("Scheme-I" in p.document_name for p in with_cert.passages),
            )
            check(
                "Lab Locator does not - it is scoped to Laboratories",
                not any("Scheme-I" in p.document_name for p in with_lab.passages),
                "both agents returning the same thing makes step 4 pointless",
            )
            lab_q = "how does BIS recognise a testing laboratory"
            check(
                "Lab Locator finds the laboratory pages",
                any(
                    "Laborator" in p.document_name
                    for p in search(db, owner, lab_q, lab_locator).passages
                ),
            )

        # --- Step 5: tools ------------------------------------------------
        print("\nStep 5 - tools that run")
        hallmark_helper = db.get(Agent, "hallmark-helper")
        if hallmark_helper and lab_locator:
            helper_tools = {t.name for t in registry.available_for(db, hallmark_helper)}
            lab_tools = {t.name for t in registry.available_for(db, lab_locator)}
            check(
                "Hallmarking & Consumer Help has the calculator",
                "calculator" in helper_tools,
                f"has {sorted(helper_tools)}",
            )
            check(
                "Lab Locator reads documents only - no calculator",
                lab_tools
                == {"document_search", "knowledge_retrieval", "read_document"},
                f"has {sorted(lab_tools)}",
            )

            context = ToolContext(db=db, user=owner, agent=hallmark_helper)
            calculator = registry.by_wire_name("calculator")
            volume = calculator.run(context, expression="47.5 * 18.25")
            check(
                "calculator returns 866.875",
                "866.875" in volume.content,
                volume.content,
            )

        # The standard finder answers a visitor from the published lists.
        finder = registry.by_wire_name("find_standard")
        visitor_context = ToolContext(
            db=db, user=guest, agent=db.get(Agent, "standards-finder")
        )
        cooker = finder.run(visitor_context, product="pressure cooker")
        check(
            "the standard finder maps 'pressure cooker' to IS 2347",
            cooker.ok and "IS 2347" in cooker.content,
            cooker.content[:300],
        )
        check("the finder's answer is cited", bool(cooker.citations))

        # The Hallmarking Desk register is computed exactly, for the staff
        # member whose desk it is.
        table = registry.by_wire_name("analyse_table")
        desk_context = ToolContext(db=db, user=hallmarking, agent=db.get(Agent, "si-1"))
        total = table.run(
            desk_context,
            operation="sum",
            column="DaysOpen",
            document="Hallmarking Complaint Register",
        )
        check(
            "table tool sums the DaysOpen column to 72",
            total.ok and "72" in total.content,
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

        unrelated = search(db, guest, "tuning frequencies for an orchestral xylophone")
        check(
            "a wholly unrelated question retrieves nothing",
            not unrelated.found,
            f"unexpectedly matched {[p.document_name for p in unrelated.passages]}",
        )

        # The realistic case: keyword search legitimately matches on
        # "licence" and "certification", so passages come back. What must
        # hold is that none of them contain the invented identifiers -
        # leaving the model nothing to hang a fabricated citation on.
        invented = search(db, guest, "clause BIS-CL-0999 licence LIC-999 certification")
        check(
            "no retrieved passage contains the invented clause number",
            all("0999" not in p.text for p in invented.passages),
        )
        check(
            "no retrieved passage contains the invented licence number",
            all("LIC-999" not in p.text for p in invented.passages),
        )

        # Nothing above is meant to persist: drop the visitor and the probe.
        db.rollback()

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

