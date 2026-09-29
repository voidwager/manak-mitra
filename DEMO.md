# Demo walkthrough

A scripted run through what the workbench actually does, in the order that
makes the point. Roughly eight minutes at a normal pace.

Everything in the dataset is **fictional** — an invented refinery, invented
equipment, invented figures. Say so once at the start; it is part of the
pitch, not a disclaimer to hide.

Every claim below is checked by `scripts/verify_demo.py`. If the demo has
drifted, that script fails rather than you finding out in front of an
audience.

---

## Before you start

```bash
python scripts/seed_db.py     # corpus is written and indexed
start.bat                     # or: uvicorn + npm run dev
python scripts/verify_demo.py # confirms the walkthrough still holds
```

Sign in as **Sanyam Jain** (`testowner@refinery.example`), password
`demo1234`. Clicking a persona card fills the form; it does not sign
you in - the server verifies the password either way.

That password works in development only. Outside it the seed refuses to run
without an explicit `DEMO_PASSWORD`, and the sign-in page stops offering the
password at all - it fills the address and leaves the rest to whoever
deployed it.

Check the pill in the top-right. It reads **External model** with Groq
configured, and **On-premise** with a local runtime. Do not skip past this —
it is the honesty claim the whole project rests on, and it is derived from
the running provider rather than asserted.

---

## 1. The knowledge base is real (1 min)

Open **Documents** as **Sanyam Jain** (Owner).

Five documents, all **Indexed**, with chunk counts. The strip above the table
reads the retrieval mode from `/api/health` — *"Keyword retrieval (BM25)
only"* unless an embedding endpoint is configured.

> **Say:** these were extracted, chunked and indexed by the pipeline. The
> chunk count is what retrieval actually searches.

Click **Preview** on the pump SOP. You see the *real extracted passages*,
page by page. Nothing here is authored for the demo — it is what the parser
produced.

---

## 2. An answer with a checkable citation (2 min)

Go to **Chat**, agent **Maintenance Intelligence**.

> **Ask:** *What is the acceptable vibration limit for a CDU-II pump, and
> what happens above it?*

Expect an answer citing **Centrifugal Pump Inspection SOP.pdf**, page 4,
section 4.2 — 2.5 mm/s RMS, with the escalation above 3.2 mm/s.

Click the citation. It opens the exact passage the answer came from.

> **Say:** the citation is built from the passage that was retrieved and put
> in the prompt. It is never parsed out of the model's text — so the system
> cannot cite a document it did not read.

Open **Agent activity** underneath. It lists the real steps: how many
passages were searched, in which folders, and what was retrieved.

---

## 3. Access control the model cannot talk its way around (2 min)

This is the part worth doing slowly.

Sign out, sign in as **Dev Patel** (HSE Safety Officer, Safety folder only).

Open **Documents**: one document. The others were never sent to his browser —
they are filtered in SQL, not hidden in the UI.

> **Ask:** *What is the hydrocracker unit's margin per tonne?*

He gets no answer and no citation. The activity trace says nothing matched
in his scope.

Sign back in as **Sanyam** and ask the identical question. He gets the figure
from **Hydrocracker Unit Strategic Audit.pdf**, which is marked owner
confidential.

> **Say:** same question, same model, same corpus — different clearance. The
> filter is the one the documents API uses, so retrieval cannot become a way
> around it. A leak here would arrive paraphrased inside an answer, where
> nobody thinks to check permissions.

---

## 4. Agents are configuration, not costume (1 min)

Open **Agents**.

Each card shows a derived status and a real capability list. **Document
Vision** reads **Limited**, and says its vision capability needs a model this
deployment does not have wired up yet.

> **Say:** that status is computed per request from the running system. It
> used to be a hardcoded string, and the agent advertised OCR it did not have.

Back in **Chat**, ask the *same* question with **SOP Assistant** that you
asked Maintenance Intelligence in step 2 — the CDU-II pump vibration limit.

SOP Assistant is scoped to Safety and All Units, so it finds nothing.

> **Say:** the agent narrows the search. It cannot widen it — an agent scoped
> to a folder you are not cleared for returns nothing, not the folder.

---

## 5. Tools that actually run (2 min)

Still on **Maintenance Intelligence**:

> **Ask:** *From the maintenance history, what is the total downtime across
> all recorded jobs?*

Watch the activity panel. It calls `analyse_table` — first for the schema,
then to sum the column — and answers with the exact figure.

> **Say:** the model did not add those up. It asked the server to, and the
> server computed it exactly. Language models are unreliable at arithmetic
> over more than a handful of rows, and a quietly wrong total is the kind of
> error nobody catches.

Then:

> **Ask:** *A pump moves 47.5 m3/h for 18.25 hours. What total volume?*

It calls `calculator` and returns 866.875 m³.

Open **Tools**. Five are **Callable by agents**; **Image Analyzer** reads
**Not available yet** with the reason.

> **Say:** the toggle is a real gate. Switch a tool off and no agent is
> offered it — the model is never given the option.

---

## 6. One deployment, several models (1 min)

Open **Agents** → the gear on **Maintenance Intelligence**. The **Model**
field is a *role*, not a model id: Default, Reasoning, or Fast. The hint
underneath names the model that role currently resolves to.

> **Say:** the router picks a model per turn and records why. Every answer's
> activity trace names the model that produced it and the reason it was
> chosen — routing is deterministic, so an answer is reproducible.

Now attach an image. Click the paperclip and add a photo of a gauge, a
nameplate, a schematic — anything with a number or text in it.

> **Ask:** *What reading is shown here?*

The chip shows which model will read it. The answer comes back, and the
activity trace reads:

```
Read 1 image(s) with a vision model
Model routing: This turn includes an image, so it was routed to the vision model.
Generated response (qwen/qwen3.8-27b via groq, external provider)
```

> **Say:** an image is only ever sent to a model that accepts images. With no
> vision model configured the attachment is refused at upload with a reason,
> and the assistant is told it could not read the file — because the
> alternative is a model that silently ignores the picture and answers
> anyway, which the user would trust.

Chat attachments are separate from the knowledge base on purpose: a photo you
paste into one question is private to you and never indexed. Routing every
screenshot into the shared corpus would degrade retrieval for the whole team.

---

## 7. What it refuses to do (1 min)

Close on this. It is the strongest part, and there are two distinct cases —
the second is the one that matters.

**Nothing matches at all.**

> **Ask:** *What is the die swell coefficient for polymer extrusion?*

No passage in the corpus is related. Retrieval returns nothing, the strict
guardrail applies, and the reply carries no citation.

**Something matches, but does not answer.** This is the realistic one.

> **Ask:** *What does SOP-CDU2-0999 say about pump P-999?*

Keyword search *does* return five passages — "SOP", "pump" and "procedure"
all appear in the corpus. But no passage mentions SOP-CDU2-0999 or P-999,
because neither exists.

The assistant tells you that, instead of writing a plausible clause number
onto the pump SOP it *did* retrieve.

> **Say:** this is the failure mode the product is built against. Retrieval
> handing over related-but-irrelevant material is normal — that is what
> keyword search does. The guarantee is that a citation is only ever built
> from a passage that was actually retrieved, so the model has nothing to
> attach a fabricated SOP number to. It cannot cite its way into a document
> it did not read.

---

## 8. It is a real access control, not a shape (1 min)

Worth thirty seconds if anyone asks whether the personas are just a UI toggle.

Open the browser devtools network tab and look at any request: identity is an
`Authorization: Bearer` token, verified against a session row server-side.
Until Phase 16 it was an `X-User-Id` header the client asserted - anyone
could type another user's id and become them. That header no longer
authenticates anything.

As **Sanyam**, `GET /api/audit` returns the trail - every upload, folder
move, reclassification, tool call and sign-in, including failed ones. As
**Dev**, the same request returns 403.

> **Say:** the audit log existed from early on and nothing could read it. A
> log nobody reads is a log, not governance. And sessions are rows rather
> than tokens-that-expire, so an administrator can end someone's access the
> moment they leave - which a JWT cannot do without a blocklist, and a
> blocklist is just this table with extra steps.

---

## If something goes wrong

**A document says "Processing" forever** — indexing runs in the background;
check the backend log. It ends as *Indexing failed* with a reason.

**Everything returns 401** — the session expired or was revoked. Sign in
again; sessions idle out after 12 hours and last at most 7 days.

**Chat returns 503** — no model configured. Check `MODEL_PROVIDER`,
`MODEL_NAME` and the key in `.env`, then restart the backend.

**Chat returns 429** — Groq rate limit (8000 tokens/minute). Tool-heavy
questions burn tokens quickly. Wait a minute; do not retry in a loop.

**A tool never gets called** — check the agent has it granted (Agents → the
gear icon) and that the tool is switched on in **Tools**.

**Nothing retrieves** — run `python scripts/verify_demo.py`. It reports which
step broke.
