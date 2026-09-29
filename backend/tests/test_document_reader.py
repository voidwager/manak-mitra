"""Whole-document reading.

Ranking answers questions *inside* a document. It cannot answer questions
*about* one - "summarise this guide" carries no distinctive terms, so BM25
scores every chunk about equally and returns an arbitrary five. That is the
bug this module fixes, and these tests hold it fixed.

The first group matters most and is not about summarising at all. A reader
that resolves documents by name is a new way to ask "does this file exist?",
so it has to inherit the same scoping the retriever uses. Two properties are
load-bearing:

  1. A document outside the caller's scope cannot be read.
  2. It cannot be *detected* either. "You may not read X" confirms X exists;
     the reader must answer exactly as it would for a name that matches
     nothing at all.
"""

from app.database.models import Agent, Document, User
from app.rag.reader import read_document
from app.tools.base import ToolContext
from app.tools.builtin.document_reader import DocumentReaderTool

RESTRICTED = "Helpdesk Query Analytics Q2 2026 (sample).md"
ASK_RESTRICTED = "Helpdesk Query Analytics Q2 2026"
CERT_GUIDE = "Certification Desk Escalation Guide (sample).md"
HALLMARK_DOC = "Hallmarking Complaint Register (sample).csv"


def _user(db, user_id: str) -> User:
    return db.get(User, user_id)


# ---------------------------------------------------------------------------
# Scoping - a leak here arrives paraphrased inside an answer
# ---------------------------------------------------------------------------
def test_a_restricted_document_cannot_be_read_by_name(db_session):
    """Dev Patel is on the Hallmarking Desk; the analytics report is owner-only."""
    result = read_document(
        db_session, _user(db_session, "user-dev"), name=ASK_RESTRICTED
    )

    assert not result.found
    assert result.part is None


def test_an_unreadable_document_is_indistinguishable_from_a_missing_one(db_session):
    """The refusal must not confirm the document exists.

    "You are not allowed to read the analytics report" tells an
    unauthorised reader that there *is* an analytics report, which is most
    of what they wanted. The answer for an out-of-scope title and for a
    title nobody has ever created must be the same shape.
    """
    dev = _user(db_session, "user-dev")

    restricted = read_document(db_session, dev, name=ASK_RESTRICTED)
    imaginary = read_document(db_session, dev, name="Completely Invented File.pdf")

    assert not restricted.found and not imaginary.found
    # Same wording, modulo the name that was asked for.
    assert restricted.reason.replace(ASK_RESTRICTED, "X") == imaginary.reason.replace(
        "Completely Invented File.pdf", "X"
    )
    for word in ("permission", "denied", "not allowed", "forbidden", "clearance"):
        assert word not in restricted.reason.lower()


def test_the_candidate_list_never_names_a_document_out_of_scope(db_session):
    """The 'here is what you can read' hint is itself a disclosure surface."""
    result = read_document(
        db_session, _user(db_session, "user-dev"), name="something unmatched"
    )

    names = {c["name"] for c in result.candidates}
    assert RESTRICTED not in names
    assert CERT_GUIDE not in names, "the Certification Desk is not in Dev Patel's scope"
    assert HALLMARK_DOC in names, "his own folder should still be offered"


def test_the_owner_can_read_the_restricted_document(db_session):
    """The scoping must actually be scoping, not a blanket refusal."""
    result = read_document(
        db_session, _user(db_session, "user-sanyam"), name=RESTRICTED
    )

    assert result.found
    assert result.part.document_name == RESTRICTED


def test_an_agent_folder_scope_narrows_and_cannot_widen(db_session):
    """An agent restricted to a folder its user cannot see reads nothing."""
    ananya = _user(db_session, "user-ananya")  # Certification Desk only

    in_scope = read_document(db_session, ananya, name=CERT_GUIDE)
    assert in_scope.found

    # Point the same read at a folder she has no access to.
    narrowed = read_document(
        db_session, ananya, name=HALLMARK_DOC, folder_scope=["Hallmarking Desk"]
    )
    assert not narrowed.found

    # And an agent scoped to the Hallmarking Desk cannot hand her the
    # Certification Desk guide either.
    wrong_folder = read_document(
        db_session, ananya, name=CERT_GUIDE, folder_scope=["Hallmarking Desk"]
    )
    assert not wrong_folder.found


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def test_reading_returns_the_document_in_order_not_a_ranked_selection(db_session):
    result = read_document(db_session, _user(db_session, "user-ananya"), name=CERT_GUIDE)

    assert result.found
    part = result.part
    assert part.total_chunks > 0
    assert part.chunks_in_part > 0
    assert part.text.strip()

    # Order is document order. The chunks were concatenated in position
    # order, so the text of the first chunk must appear before the last.
    from sqlalchemy import select

    from app.database.models import DocumentChunk

    document = db_session.scalar(select(Document).where(Document.name == CERT_GUIDE))
    chunks = list(
        db_session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.position)
        )
    )
    if len(chunks) >= 2 and part.chunks_in_part >= 2:
        first_seen = part.text.find(chunks[0].text[:40])
        second_seen = part.text.find(chunks[1].text[:40])
        assert first_seen != -1 and second_seen != -1
        assert first_seen < second_seen


def test_a_partial_name_resolves_to_the_right_document(db_session):
    result = read_document(
        db_session, _user(db_session, "user-ananya"), name="certification desk escalation"
    )
    assert result.found
    assert result.part.document_name == CERT_GUIDE


def test_reading_produces_citations_so_the_answer_stays_checkable(db_session):
    result = read_document(db_session, _user(db_session, "user-ananya"), name=CERT_GUIDE)

    assert result.citations
    for citation in result.citations:
        assert citation["title"] == CERT_GUIDE
        assert citation["documentId"] == result.part.document_id
        assert citation["excerpt"]


def test_long_documents_split_into_stable_numbered_parts(db_session):
    """Part numbering must mean the same thing on every call."""
    ananya = _user(db_session, "user-ananya")

    first = read_document(db_session, ananya, name=CERT_GUIDE, max_chars=200)
    assert first.found
    assert first.part.part == 1
    assert first.part.total_parts >= 1

    again = read_document(db_session, ananya, name=CERT_GUIDE, max_chars=200)
    assert again.part.text == first.part.text
    assert again.part.total_parts == first.part.total_parts

    if first.part.total_parts > 1:
        second = read_document(db_session, ananya, name=CERT_GUIDE, part=2, max_chars=200)
        assert second.part.part == 2
        assert second.part.text != first.part.text

    # An out-of-range part clamps rather than erroring or inventing content.
    clamped = read_document(db_session, ananya, name=CERT_GUIDE, part=999, max_chars=200)
    assert clamped.found
    assert clamped.part.part == clamped.part.total_parts


# ---------------------------------------------------------------------------
# The tool wrapper
# ---------------------------------------------------------------------------
def test_the_tool_reports_remaining_parts_so_the_model_keeps_reading(db_session):
    tool = DocumentReaderTool()
    context = ToolContext(
        db=db_session,
        user=_user(db_session, "user-ananya"),
        agent=db_session.get(Agent, "si-1"),
    )

    result = tool.run(context, document=CERT_GUIDE)

    assert result.ok
    assert CERT_GUIDE in result.content
    assert result.citations
    # Either it is the whole document, or it says how to continue.
    assert (
        "This is the entire document." in result.content
        or "read_document again with part=" in result.content
    )


def test_the_tool_offers_readable_documents_instead_of_failing_blankly(db_session):
    """A dead end the model can act on beats 'I do not have access'."""
    tool = DocumentReaderTool()
    context = ToolContext(
        db=db_session,
        user=_user(db_session, "user-dev"),
        agent=db_session.get(Agent, "si-1"),
    )

    result = tool.run(context, document="a document that does not exist")

    assert result.ok, "a miss is information, not a failure"
    assert "Documents you can read:" in result.content
    assert HALLMARK_DOC in result.content
    assert RESTRICTED not in result.content


def test_a_shared_file_extension_is_not_a_match(db_session):
    """Regression: ".pdf" is not evidence about which document is meant.

    The first version of the matcher fell back to token overlap without
    excluding extensions, so "Completely Invented File.pdf" shared the token
    "pdf" with a real ".pdf" document and resolved to it. A
    fabricated name then returned a real document's full text - the worst
    possible outcome for a tool whose whole job is reading files out.
    """
    dev = _user(db_session, "user-dev")

    for invented in (
        "Completely Invented File.pdf",
        "Completely Invented File.md",
        "Nonexistent Thing.csv",
        "Some Other Document.docx",
    ):
        assert not read_document(db_session, dev, name=invented).found, invented


def test_a_single_weak_token_does_not_resolve_a_document(db_session):
    """"hallmarking" is shared by half a dozen documents and identifies none."""
    owner = _user(db_session, "user-sanyam")
    assert not read_document(db_session, owner, name="hallmarking").found


def test_a_single_distinctive_token_still_resolves(db_session):
    """Tightening the matcher must not break ordinary shorthand."""
    owner = _user(db_session, "user-sanyam")

    result = read_document(db_session, owner, name="analytics")
    assert result.found
    assert result.part.document_name == RESTRICTED


# ---------------------------------------------------------------------------
# The prompt has to admit the tool exists
# ---------------------------------------------------------------------------
def test_the_guardrail_stops_claiming_the_passages_are_all_there_is(db_session):
    """A guardrail that states a falsehood teaches the model to refuse.

    Rule 1 used to end "That is the whole of your document access." With a
    whole-document reader offered that is simply untrue, and the model acted
    on it: asked to summarise a guide it reported that it could not see the
    rest of the document while holding the tool that returns it.
    """
    from app.services.prompts import build_system_prompt

    with_reader = build_system_prompt(None, None, None, None, ["read_document"])
    assert "whole of your document access" not in with_reader
    assert "READING A WHOLE DOCUMENT" in with_reader

    without = build_system_prompt(None, None, None, None, ["calculator"])
    assert "READING A WHOLE DOCUMENT" not in without


def test_the_prompt_names_the_reader_only_when_it_is_offered(db_session):
    """Never advertise a tool the executor would refuse to run."""
    from app.services.prompts import build_system_prompt

    assert "read_document" in build_system_prompt(None, None, None, None, ["read_document"])
    assert "read_document" not in build_system_prompt(None, None, None, None, None)


# ---------------------------------------------------------------------------
# Who is allowed to narrow the search
# ---------------------------------------------------------------------------
def test_an_automatic_dispatch_does_not_hide_the_users_own_documents(db_session):
    """Manak Mitra's routing choice is not a restriction on the user.

    The reported bug. Asked to summarise a Certification Desk guide she is
    fully cleared for, Ananya was routed by the universal agent to a
    specialist scoped to other folders and told the document was not in the
    knowledge base at all. The narrowing came from a classifier picking a specialist,
    not from anyone deciding she should not see the file.
    """
    from app.database.models import Conversation
    from app.services import chat_service

    ananya = _user(db_session, "user-ananya")
    conversation = Conversation(
        id="conv-dispatch-scope",
        title="scope",
        user_id=ananya.id,
        agent_id="si-1",
        agent_name="Manak Mitra",
    )
    db_session.add(conversation)
    db_session.flush()

    si1 = db_session.get(Agent, "si-1")
    turn = chat_service.prepare_turn(
        db_session,
        conversation,
        ananya,
        si1,
        "Summarise the Certification Desk Escalation Guide and list its sections.",
        None,
    )

    # Whatever specialist was chosen, the turn searches her own scope.
    assert turn.folder_scope == []

    # And the reader can therefore actually reach the document.
    tool = DocumentReaderTool()
    context = ToolContext(
        db=db_session,
        user=ananya,
        agent=turn.agent,
        folder_scope=turn.folder_scope,
    )
    result = tool.run(context, document=CERT_GUIDE)
    assert CERT_GUIDE in result.content
    assert "part 1 of" in result.content

    db_session.rollback()


def test_explicitly_choosing_an_agent_still_narrows(db_session):
    """The specialist scoping demo must keep working.

    Picking Lab Locator from the dropdown is a deliberate choice, and it
    still restricts the search to that agent's folders. Only the universal
    agent's own automatic routing is exempt.
    """
    ananya = _user(db_session, "user-ananya")
    lab_locator = db_session.get(Agent, "lab-locator")

    tool = DocumentReaderTool()
    context = ToolContext(db=db_session, user=ananya, agent=lab_locator)

    # No folder_scope passed, so the tool falls back to the agent's own -
    # Laboratories, where the guide is not filed.
    assert context.search_scope() == lab_locator.folder_scope
    result = tool.run(context, document=CERT_GUIDE)
    assert not result.citations
    assert "part 1 of" not in result.content
    assert CERT_GUIDE not in result.content.split("Documents you can read:")[-1]


# ---------------------------------------------------------------------------
# The automatic path - not left to the model to choose
# ---------------------------------------------------------------------------
def test_document_level_questions_are_recognised():
    from app.services.chat_service import _is_document_level_question as asks

    for question in (
        "Summarise the Certification Desk Escalation Guide",
        "Give me an overview of the hallmarking guidelines",
        "What are the main topics of the licensing procedure?",
        "list its sections",
        "read the whole complaint register",
        "what is in the escalation guide",
        "Walk me through the guide end to end",
    ):
        assert asks(question), question

    # Questions *inside* a document must not trigger a whole-document read.
    for question in (
        "What is the testing charge for a hallmarked article?",
        "What documents do I need for an ISI licence?",
        "hello",
        "what's 47.5 times 18.25?",
    ):
        assert not asks(question), question


def test_a_document_level_question_reads_the_document_into_the_prompt(db_session):
    """The fix, end to end at the turn level.

    Left to the model this is unreliable - a 27B model with five plausible
    passages already in context answers from them and reports that it cannot
    see the rest of the file. The read happens server-side so the common case
    is deterministic.
    """
    from app.database.models import Conversation
    from app.services import chat_service

    ananya = _user(db_session, "user-ananya")
    conversation = Conversation(
        id="conv-doc-level",
        title="doc level",
        user_id=ananya.id,
        agent_id="si-1",
        agent_name="Manak Mitra",
    )
    db_session.add(conversation)
    db_session.flush()

    turn = chat_service.prepare_turn(
        db_session,
        conversation,
        ananya,
        db_session.get(Agent, "si-1"),
        "Summarise the Certification Desk Escalation Guide and list its sections.",
        None,
    )

    assert turn.document_read is not None
    assert turn.document_read.document_name == CERT_GUIDE
    # The whole document, in order - not five ranked fragments of it.
    assert turn.document_read.chunks_in_part == turn.document_read.total_chunks
    assert len(turn.retrieval.passages) >= turn.document_read.chunks_in_part

    db_session.rollback()


def test_a_factual_question_is_left_to_ranking(db_session):
    """Reading a whole document to answer a one-line lookup is waste."""
    from app.database.models import Conversation
    from app.services import chat_service

    ananya = _user(db_session, "user-ananya")
    conversation = Conversation(
        id="conv-factual",
        title="factual",
        user_id=ananya.id,
        agent_id="si-1",
        agent_name="Manak Mitra",
    )
    db_session.add(conversation)
    db_session.flush()

    turn = chat_service.prepare_turn(
        db_session,
        conversation,
        ananya,
        db_session.get(Agent, "si-1"),
        "What is the testing charge for a hallmarked article?",
        None,
    )

    assert turn.document_read is None
    db_session.rollback()


def test_the_automatic_read_cannot_reach_a_document_out_of_scope(db_session):
    """The new path must not become a way around the access rule.

    Dev Patel is on the Hallmarking Desk. Asking for a summary of the
    owner-only analytics report must read nothing, whatever the question looks like.
    """
    from app.database.models import Conversation
    from app.services import chat_service

    dev = _user(db_session, "user-dev")
    conversation = Conversation(
        id="conv-doc-level-denied",
        title="denied",
        user_id=dev.id,
        agent_id="si-1",
        agent_name="Manak Mitra",
    )
    db_session.add(conversation)
    db_session.flush()

    turn = chat_service.prepare_turn(
        db_session,
        conversation,
        dev,
        db_session.get(Agent, "si-1"),
        "Summarise the Helpdesk Query Analytics Q2 2026 report end to end.",
        None,
    )

    assert turn.document_read is None
    for passage in turn.retrieval.passages:
        assert passage.document_name != RESTRICTED

    db_session.rollback()
