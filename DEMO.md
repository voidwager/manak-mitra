# Demo walkthrough

A scripted run through what Manak Mitra actually does, in the order that
makes the point. About eight minutes at a normal pace.

The knowledge base is **real public BIS material** - scheme pages, the
product lists under compulsory certification, hallmarking rules, the lab
lists, the BIS Act - each file carrying the URL it came from and the date it
was captured (`data/bis/source/MANIFEST.md`). The *staff* accounts and three
short *internal* documents are fictional and labelled so; they exist to show
access control, because no real BIS internal data belongs in a demo. Say
that once at the start.

The access-control and retrieval claims below are checked by
`scripts/verify_demo.py`. If the demo has drifted, that script fails rather
than you finding out in front of an audience. What the *model* writes varies
run to run; the script checks what it is given, not how it phrases it.

---

## Before you start

```bash
python scripts/seed_db.py     # BIS corpus written and indexed
start.bat                     # or: uvicorn + npm run dev
python scripts/verify_demo.py # confirms the walkthrough still holds
```

Open the site. **There is no sign-in screen** - you are straight in as a
visitor, because a consumer asking about a hallmark should not need an
account. Staff sign in from the profile menu (**Staff sign-in**) as
`admin@bis-helpdesk.example`, password `demo1234` (development only - outside
it the seed refuses to run without an explicit `DEMO_PASSWORD`).

Check the pill in the top-right: **External model** with Groq, **On-premise**
with a local runtime. It is derived from the running provider, never asserted.

---

## 1. The knowledge base is real and checkable (1 min)

As a visitor, open **BIS Sources**.

Nineteen documents in six public folders - Certification Schemes, Standards &
QCOs, Hallmarking, Laboratories, Consumer Help, BIS Act & Rules - all
**Indexed**. Preview **Hallmarking for Consumers - HUID, Testing,
Compensation.md**: the first lines are the source URL on bis.gov.in and the
date it was captured.

> **Say:** every answer is built from these. Anyone can open the source a
> citation points at and check it against bis.gov.in.

---

## 2. A consumer question, then the same question in Hindi (2 min)

Click the starter question, or:

> **Ask:** *How can I check that the hallmark on a gold chain is genuine?*

Expect: look for the HUID and verify it with **Verify HUID** in the BIS CARE
app, cited to *Hallmarking for Consumers*.

Now click the Hindi starter question:

> **Ask:** *सोने के गहने पर HUID कैसे जांचें?*

The reply comes back **in Hindi**, citing the same English BIS document. Open
**Agent activity**: the first step reads *Searched in English: "…"* with the
query the question was translated into.

> **Say:** BIS publishes in English, and keyword search matches words - so a
> Hindi question would find nothing. We search with an English rewrite *and*
> the original (so an HUID or IS number typed in survives), then answer in
> the user's language. The translation is shown, so a reader can see whether
> it found the right thing.

On Chrome or Edge, pick **हिन्दी** next to the mic and *speak* the question.
Recognition is the browser's own; the transcript lands in the box to be
checked before sending.

---

## 3. An MSME: "which standard applies to my product?" (2 min)

> **Ask:** *I make stainless steel pressure cookers. Which standard applies
> and is certification compulsory?*

The activity trace shows `find_standard` running. Expect **IS 2347:2017,
Domestic Pressure Cooker**, under a Quality Control Order (Q085, 2020), in
**Scheme-I (ISI Mark)** - cited to the row of *Products under Compulsory
Certification - Scheme-I*.

> **Say:** the answer is a row of BIS's own list, not the model's memory. The
> tool reads the three published lists - 861 products - as tables. It also
> notes the row does not mention "stainless steel", so the answer tells the
> user to confirm the standard's scope rather than overclaiming.

Then:

> **Ask:** *Do I need BIS registration to sell power banks?*

Expect the **Compulsory Registration Scheme (CRS)** - power banks are listed
under **IS 13252(Part 1):2010** - and the Certification Guide's explanation of
what registration involves.

---

## 4. What a visitor can never reach (2 min)

This is the part worth doing slowly.

> **Ask (as a visitor):** *What was the helpdesk query volume last quarter?*

No answer and no citation. The figure exists - in *Helpdesk Query Analytics
Q2 2026 (sample)*, filed in **BIS Internal** - but a visitor's search never
sees that folder. It is filtered in SQL, not hidden in the UI.

Sign in as staff (`admin@bis-helpdesk.example`) and ask the identical
question. The administrator gets **18,240**, cited.

Sign in as `certification@bis-helpdesk.example` (Certification Officer) and
ask about the *Hallmarking Desk's* complaint register. Nothing: officers see
every public source plus their own desk, and no other desk.

> **Say:** same question, same model, same corpus - different clearance. A
> leak here would arrive paraphrased inside an answer, where nobody thinks to
> check permissions, which is why retrieval uses the same filter as the
> documents API.

As a visitor, the site also offers no **Create Agent** and no **Tools** page -
and the API refuses both (403) whatever the UI shows, because an agent is
listed for everyone and a tool switch is global.

---

## 5. Specialists narrow the search (1 min)

Open **Specialists**. Each card shows what it searches: the Standards Finder
reads *Standards & QCOs*, the Lab Locator reads *Laboratories*, and so on.
**Mark & Label Reader** reads **Limited** - it needs a vision model this
deployment may not have, and says so.

> **Ask the Lab Locator:** *Which BIS-recognised labs are in Maharashtra?*

Expect recognised labs listed with their state, cited to *BIS Recognised
Laboratories (Group-1 and Group-2)*. The list carries its own warning that
suspension history was omitted, and the answer should say to confirm current
status.

---

## 6. Tools that compute rather than guess (1 min)

> **Ask:** *I want 7 pieces of my old jewellery tested at a hallmarking
> centre. What will it cost?*

Expect **Rs 315** - Rs 45 per article, over the Rs 200 minimum per lot -
with the calculator in the activity trace and the charge cited to the
consumer testing guidelines.

As `hallmarking@bis-helpdesk.example`:

> **Ask:** *From the complaint register, what is the average number of days a
> complaint stays open?*

`analyse_table` computes **12** from the six rows exactly.

> **Say:** the model does not do the arithmetic. It asks the server to.

---

## 7. What it refuses to do (1 min)

**The product is not on any compulsory list.**

> **Ask:** *Which IS applies to PVC pipes for drinking water?*

The tool finds iron water pipes but notes none of the rows mention PVC. The
answer says PVC pipes do not appear on the compulsory-certification lists in
the knowledge base, and does not name a standard from memory.

**Something matches, but does not answer.** The realistic case.

> **Ask:** *What is the GST rate on gold jewellery?*

Keyword search *does* return passages - BIS fee pages say "GST as applicable
will be charged". None gives a rate for jewellery, because GST is not BIS's
to set. The answer says the BIS documents do not cover it, instead of
attaching a plausible percentage to a fee page it did retrieve.

**Nothing is related at all.**

> **Ask:** *Who won the last cricket world cup?*

No passage, no citation; the strict no-retrieval guardrail applies.

> **Say:** a wrong IS number costs a manufacturer a licence application. So
> IS numbers, fees and timelines come from a retrieved passage or not at all.

---

## 8. Real access control, not a shape (1 min)

In devtools, any request carries an `Authorization: Bearer` token, checked
against a session row server-side. A visitor's token belongs to a throwaway
account of their own - two visitors never see each other's chats.

As the administrator, `GET /api/audit` returns the trail - uploads, folder
moves, tool calls, sign-ins and visitor sessions. As a visitor or officer,
403.

---

## If something goes wrong

**The site shows a sign-in screen instead of letting you in** - public mode is
off (`PUBLIC_MODE=false`) or the backend is unreachable; the banner says which.

**The old refinery documents appear** - an old database. The default file is
now `data/manak_mitra.db`; delete a stale one and run `scripts/seed_db.py`.

**Chat returns 503** - no model configured. Check `MODEL_PROVIDER`,
`MODEL_NAME` and the key in `.env`, then restart the backend.

**A Hindi question gets no citation** - the translation step needs a model;
the activity trace says *Could not translate the question for search* when it
was unavailable. Semantic search (`EMBEDDING_MODEL=bge-m3`, multilingual)
removes the dependency.

**Nothing retrieves** - run `python scripts/verify_demo.py`. It reports which
step broke.
