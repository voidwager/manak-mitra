# Synthetic demo dataset

Everything in this project's demo data is **fictional**.

This is not real plant data. The refinery, its units, equipment tags, personnel,
procedures and commercial figures are invented for development and
demonstration. Do not describe any of it as real plant information, and do
not use any procedure in it to carry out work.

## The fictional environment

    Demo Refinery                       15 MMTPA nameplate
      CDU-II    Crude distillation unit
        P-204   Centrifugal pump (crude charge)
        P-205   Centrifugal pump (crude charge)
        P-206   Centrifugal pump (installed spare)
        C-101   Reciprocating compressor, two stage
      HCU-I     Hydrocracker unit
        E-302   Heat exchanger

    Sanyam Jain    Owner / Plant Administrator   full access
    Ananya Roy     Maintenance Engineer          CDU-II + own uploads
    Dev Patel      HSE Safety Officer            Safety + own uploads

## The corpus

`source/` holds the documents as plain text. They are committed as text
rather than as PDFs so they stay diffable and reviewable; the PDFs are
generated from them at seed time by `backend/app/database/demo_corpus.py`,
which builds genuine text PDFs with real pages using `pypdf` alone.

| Source | Becomes | Folder | Notes |
|---|---|---|---|
| `centrifugal-pump-inspection-sop.txt` | `Centrifugal Pump Inspection SOP.pdf` | CDU-II | 5 pages. Holds the vibration limits |
| `compressor-inspection-procedure.txt` | `Compressor Inspection Procedure.pdf` | CDU-II | 4 pages. Filter differentials, trip settings |
| `equipment-safety-guidelines.txt` | `Equipment Safety Guidelines.pdf` | Safety | 4 pages. PPE zones, confined space entry |
| `maintenance-history.csv` | `Maintenance History.csv` | CDU-II | 15 rows. Numeric columns for the table tool |
| `hydrocracker-strategic-audit.txt` | `Hydrocracker Unit Strategic Audit.pdf` | Executive Confidential | 3 pages. **Owner clearance only** |

The last one earns its place: it is the document used to demonstrate that a
user without executive clearance cannot reach a file's contents - not in the
document list, not through search, and not paraphrased into an assistant's
answer.

### Editing the corpus

Edit the text in `source/`, then re-seed. A line containing only `---PAGE---`
forces a page break, which is how a section stays on the page a citation
points at.

Seeding only fills in what is missing, so an already-indexed document is left
alone. To rebuild one, delete it through the UI (or drop the row) and re-seed.

## Loading it

```bash
python scripts/seed_db.py
```

This creates the rows, writes the files into `data/documents/` (gitignored -
they are generated, not source), and indexes them. A fresh checkout is
therefore searchable immediately, with no manual upload.

Generated files are ignored by git on purpose: committing binary PDFs that
are reproducible from the text beside them would just make the history
heavier and the diffs unreadable.

## What it demonstrates

Sign in as each persona and ask the same question to see access scoping
applied to retrieval rather than to the UI:

- **Ananya** can reach the pump SOP, the compressor procedure and the
  maintenance history. She cannot reach the safety guidelines or the audit.
- **Dev** can reach the safety guidelines only.
- **Sanyam** reaches everything, including the confidential audit.

`DEMO.md` at the repository root is the full walkthrough, and
`scripts/verify_demo.py` checks that every claim it makes still holds.
