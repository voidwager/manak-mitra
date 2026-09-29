"""Pydantic request/response schemas.

The existing frontend reads camelCase fields, so responses are serialised
with camelCase aliases. That keeps every UI component unchanged while the
database stays conventionally snake_case.
"""

from datetime import date, datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _assume_utc(value: datetime) -> datetime:
    """Stamp UTC onto an instant that lost its offset in storage.

    Every timestamp is written with `utcnow()`, but SQLite has no timezone
    type: SQLAlchemy's `DateTime(timezone=True)` is a no-op there and the
    value comes back naive. Serialised as-is it becomes "2026-09-11T19:21:16"
    with no offset, which `new Date()` in the browser reads as *local* time -
    so a correct UTC instant renders hours off, and further off for readers
    outside the server's zone.

    Naive therefore means UTC here, because that is the only thing this
    application ever writes. PostgreSQL returns the offset itself and this
    leaves those values untouched.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


#: A timestamp that always reaches the client with an explicit offset.
UtcDateTime = Annotated[datetime, AfterValidator(_assume_utc)]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class InferenceStatus(ApiModel):
    """Where inference happens, reported rather than asserted."""

    provider: str
    model: str | None
    configured: bool
    # True only when the model runs inside the operator's own network.
    on_premise: bool
    summary: str


class RetrievalStatus(ApiModel):
    """What the retrieval layer can actually do right now.

    `mode` is derived from the running configuration, never asserted:
      "lexical"  - BM25 only. Always available; needs no model.
      "hybrid"   - BM25 fused with vector search from a live embedder.
      "disabled" - retrieval switched off on the server.
    """

    enabled: bool
    mode: str
    embedding_provider: str
    embedding_model: str | None
    embedding_configured: bool
    # True only when vectors are computed inside the operator's own network.
    embedding_on_premise: bool
    # File formats this install can extract text from.
    extractable: dict[str, Any]
    summary: str


class AttachmentLimits(ApiModel):
    """What a chat attachment may be, according to the server.

    Published because the browser needs it for the file picker's accept
    filter, and a hardcoded copy drifts. It already did: PDFs became
    attachable and the picker went on greying them out, so the feature
    existed and was unreachable.
    """

    #: Extensions the upload endpoint accepts, e.g. [".pdf", ".png"].
    accepted: list[str]
    #: Of those, the ones extracted and indexed rather than sent inline.
    indexed: list[str]
    max_bytes: int


class HealthResponse(ApiModel):
    status: str
    app: str
    environment: str
    database: str
    database_connected: bool
    inference: InferenceStatus
    retrieval: RetrievalStatus
    model_provider: str
    implemented: dict[str, bool]
    attachments: AttachmentLimits | None = None
    #: Whether anyone may open the assistant without an account. The client
    #: reads this to skip the sign-in screen, rather than a build flag.
    public_mode: bool = False


class ModelRoute(ApiModel):
    """One entry of the routing table, as resolved right now."""

    role: str
    model: str
    purpose: str
    # False when the role has no model configured and falls back to the
    # default. Reported so a silently degraded route is visible.
    configured: bool
    accepts_images: bool


class SelectableModel(ApiModel):
    """A model a user may pin a chat to."""

    #: Provider-qualified id, which is what gets stored.
    id: str
    label: str
    provider: str
    # Shown so somebody picking a model knows what they are trading.
    note: str
    accepts_images: bool


class ModelCatalogue(ApiModel):
    provider: str
    configured: bool
    selected: str | None
    available: list[str]
    # How a turn is routed between models. Resolved per request, never a
    # stored copy that could drift from the configuration.
    routes: list[ModelRoute] = Field(default_factory=list)
    # What a chat may be pinned to from its settings menu.
    selectable: list[SelectableModel] = Field(default_factory=list)
    # Which vendors have credentials. Reported so a missing key is visible
    # rather than showing up as a route that quietly fell back.
    providers: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
class UserOut(ApiModel):
    id: str
    name: str
    email: str
    role: str
    initials: str
    access_level: str
    scope_label: str
    assigned_folders: list[str]
    avatar_gradient: str


class LoginRequest(ApiModel):
    """Credentials. Both required - there is no identifier-only sign-in."""

    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(ApiModel):
    """A successful sign-in.

    `token` is shown exactly once and is never stored server-side in a
    recoverable form - only its hash is kept, so a database leak yields no
    live sessions.
    """

    token: str
    user: UserOut
    expires_at: datetime


class PasswordChange(ApiModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class SessionOut(ApiModel):
    """A sign-in session, for the governance view."""

    id: str
    user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    user_agent: str
    current: bool = False


class AuditEntryOut(ApiModel):
    """One audit record. Read-only, owner clearance."""

    id: int
    user_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    status: str
    detail: dict[str, Any] | None
    created_at: datetime


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
class SettingsOut(ApiModel):
    theme: str
    compact_mode: bool
    show_timestamps: bool
    show_agent_activity: bool
    temperature: float
    response_style: str

    # The model this user's chats start on, when they have chosen one. Empty
    # means follow the server's role table, which is the default and the
    # right answer for most people - it moves with the deployment.
    #
    # A per-chat pin still wins over this, and an image still forces the
    # vision route: no preference makes a text-only model able to see one.
    chat_model: str = ""

    # The styles the server will actually honour, sent so the picker cannot
    # drift from them. It already had: the dropdown offered three options
    # while the prompt builder knew five, so "Balanced" - the default every
    # account now gets - was not selectable and the control displayed the
    # wrong value for anyone using it.
    response_style_options: list[str] = Field(default_factory=list)
    # NOTE: `UserSettings.model` still exists as a column but is not exposed.
    # The active model is a server setting (MODEL_NAME), reported by
    # /api/health. A per-user model preference only becomes meaningful with
    # model routing; the column is kept for that, minus a migration.


class SettingsUpdate(ApiModel):
    theme: str | None = None
    compact_mode: bool | None = None
    show_timestamps: bool | None = None
    show_agent_activity: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    response_style: str | None = None
    # "" clears the preference and returns the user to the role table.
    # Validated against the configured routes: a model this deployment has
    # never been set up to use would fail at the provider one turn later,
    # where nothing would connect the failure to this setting.
    chat_model: str | None = None


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------
class AgentCapability(ApiModel):
    """One thing an agent can or cannot do, derived from the live runtime."""

    label: str
    available: bool
    # Why it is unavailable, or how it is configured when it is.
    detail: str


class AgentModelRoute(ApiModel):
    """One model this agent commands, and what it is for.

    An agent is not one model. SI-1 in particular fronts the whole routed
    table - it answers on the chat model, classifies specialists on the fast
    one, and any turn carrying an image is forced to the vision model
    whichever specialist is engaged. Reporting a single id described the
    least interesting part of that.

    `available` is derived like everything else here. A configured route is
    not a working one: MODEL_TRANSCRIPTION can name a real Whisper model
    while nothing in the application can reach it.
    """

    role: str
    model: str
    provider: str
    # What the role is for, in the router's own words.
    purpose: str
    available: bool
    detail: str = ""


class AgentOut(ApiModel):
    id: str
    name: str
    description: str
    instructions: str

    # Derived per request, never the stored column: availability depends on
    # whether a model is configured and whether the agent's declared tools
    # can run, neither of which a stored string can know.
    status: str
    status_detail: str
    model: str
    icon: str

    # What the agent can actually do right now, each entry saying whether it
    # is available and why not.
    capabilities: list[AgentCapability]

    # What the author says the agent is *for*. Free text, unverified - this
    # is the old `capabilities` column, renamed in the API to stop it reading
    # as a claim about the running system.
    specialisations: list[str]

    # Tool display names this agent is permitted to call. A grant, not a
    # guarantee: a tool that is switched off, or has no implementation yet,
    # is still listed here but is never offered to the model.
    tools: list[str]

    # --- Retrieval configuration ---
    retrieval_enabled: bool
    # Empty means "everything the caller is cleared for". Never widens.
    folder_scope: list[str]
    retrieval_top_k: int | None

    # --- Model routing ---
    # The routed role this agent prefers, and why the resolved model was
    # chosen. `model` above reports what; this reports the reason.
    model_role: str = "chat"
    model_role_reason: str = ""

    # The operator's stored choice, as opposed to `model` above which is what
    # the router actually resolved. They differ whenever no pin is set, and
    # the editor needs the pin: showing the resolved model in a dropdown
    # would silently turn "follow the workbench" into a hard pin on save.
    model_pin: str = ""

    # Which vendor serves `model`. Worth naming now that a deployment can run
    # more than one: "qwen/qwen3.8-27b" alone does not say whose GPU it is on.
    model_provider: str = ""

    # An agent that reads images uses two models, not one - its text turns go
    # to the model above and its image turns are forced to the vision route.
    # Reporting only the first made the Document Vision card name a model it
    # never uses for the thing it exists to do.
    vision_model: str = ""
    vision_provider: str = ""

    # Every model this agent commands. One entry for a plain specialist;
    # the whole routed table for SI-1, which fronts all of them.
    model_routes: list[AgentModelRoute] = Field(default_factory=list)

    is_system: bool
    # SI-1. Exposed because the UI treats the universal assistant differently
    # everywhere - it leads the list, it is the default, and it is the only
    # one offered in the assistant picker.
    is_universal: bool = False
    created_by_id: str | None = None


class AgentUpdate(ApiModel):
    """Editable agent configuration. Omitted fields are unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    instructions: str | None = None
    icon: str | None = None
    specialisations: list[str] | None = None
    tools: list[str] | None = None
    retrieval_enabled: bool | None = None
    folder_scope: list[str] | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1, le=25)
    # "chat" | "reasoning" | "fast". Vision is never chosen here - it is
    # forced by a turn that carries an image.
    model_role: str | None = None
    # An explicit model pin, or "" to clear it and follow the role table.
    # Validated against the configured routes on the way in: a pin naming a
    # model this deployment has never been set up to use would fail at the
    # provider, one turn later, as an unexplained error.
    model: str | None = None
    # "Online" or "Offline" - an operator retiring an agent without deleting
    # it. Distinct from derived availability.
    status: str | None = None


class AgentCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    instructions: str = ""
    model: str = ""
    icon: str = "Bot"
    # Tool display names selected in the Create Agent modal.
    tools: list[str] = Field(default_factory=list)
    # Author's stated focus areas. Intent, not capability.
    specialisations: list[str] = Field(default_factory=list)
    retrieval_enabled: bool = True
    folder_scope: list[str] = Field(default_factory=list)
    retrieval_top_k: int | None = Field(default=None, ge=1, le=25)
    model_role: str = "chat"


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
class ToolOut(ApiModel):
    id: str
    name: str
    description: str
    category: str
    # The operator's switch. Distinct from whether the tool can actually run.
    enabled: bool

    # Whether an agent could call this right now. A catalogued tool with no
    # implementation is `false` however the switch is set - the registry row
    # and the code are two halves joined by id, and only one of them exists
    # for a tool whose phase has not landed.
    executable: bool = False

    # Whether code exists behind this tool at all, ignoring the switch above.
    # The two are separate on the wire because a client has to be able to
    # tell "an operator turned this off" from "this was never built": the
    # first is worth offering to undo, the second is not, and conflating
    # them is what made the switch one-way.
    implemented: bool = False

    # Why not, in plain English. Empty when executable.
    unavailable_reason: str = ""
    # The name the model sees, for anyone matching a trace entry to a tool.
    wire_name: str = ""


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
class DocumentOut(ApiModel):
    id: str
    name: str
    type: str
    size: str
    # The UI reads `date` and `chunks`.
    uploaded_date: date | None = Field(default=None, serialization_alias="date")
    status: str
    chunk_count: int = Field(serialization_alias="chunks")
    folder: str
    owner_id: str | None
    is_confidential_owner_only: bool

    # "personal" | "restricted" | "shared", derived from the folder so the
    # UI never has to reimplement the rule. The folder is authoritative.
    visibility: str = "shared"

    # Set when this document was attached to a chat rather than uploaded to
    # the knowledge base. It is retrievable in that conversation and nowhere
    # else, so the UI lists it apart from the corpus.
    conversation_id: str | None = None
    section: str
    page: int
    excerpt: str

    # --- Indexing (Phase 8) ---
    # False for a catalogue-only row: there are no bytes to index, so the
    # UI does not offer the action and the server refuses it.
    has_stored_file: bool = False
    indexed_at: datetime | None = None
    # Why the last indexing attempt did not produce a searchable document.
    # Empty on success. Shown to the user verbatim.
    index_error: str = ""
    extracted_chars: int = 0
    # False on an indexed document means keyword search only.
    is_semantically_indexed: bool = False


class DocumentUpdate(ApiModel):
    """Editable document metadata. Every field optional; omitted = unchanged.

    `folder`, `is_confidential_owner_only` and `owner_id` are access-control
    changes rather than cosmetic ones - between them they decide who can
    retrieve the document's contents. The route checks each against
    `app.services.access` and refuses the whole request with a reason,
    rather than silently dropping a field the caller was not allowed to set.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    folder: str | None = Field(default=None, min_length=1, max_length=120)
    # Owner clearance only. Removes the document from every other user's
    # listing *and* from their retrieval results.
    is_confidential_owner_only: bool | None = None

    # Lift a document out of its chat and into the caller's knowledge base.
    # A boolean rather than a writable `conversation_id`, deliberately: only
    # clearing is ever allowed. Letting a caller *set* a conversation would
    # be a way to push a file into somebody else's chat, where the assistant
    # would then answer from it.
    promote_from_chat: bool | None = None
    # Owner clearance only.
    owner_id: str | None = None


class FolderOut(ApiModel):
    """The folder namespace, derived rather than stored.

    A folder is currently a free-text string on documents and on users, so
    there is no folders table to list. `assignable` is what this user may
    file into; when `unrestricted` is true they may also name a new folder.
    """

    all: list[str]
    assignable: list[str]
    unrestricted: bool


class DocumentChunkOut(ApiModel):
    id: str
    position: int
    text: str
    page: int
    section: str
    char_start: int
    char_end: int
    # Which embedding model produced this chunk's vector, or "" for a
    # lexical-only chunk.
    embedding_model: str


class IndexResultOut(ApiModel):
    """Outcome of an indexing run, alongside the updated document."""

    document: DocumentOut
    queued: bool
    status: str
    chunk_count: int = 0
    embedded_chunks: int = 0
    embedding_model: str = ""
    message: str = ""


# --------------------------------------------------------------------------
# Knowledge-base search
# --------------------------------------------------------------------------
class SearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=25)


class SearchHit(ApiModel):
    document_id: str
    document_name: str
    chunk_id: str
    text: str
    page: int
    section: str
    score: float
    # 1-based rank from each strategy; null when that strategy did not
    # return this passage. Makes the fusion inspectable.
    lexical_rank: int | None = None
    semantic_rank: int | None = None


class SearchResponse(ApiModel):
    query: str
    # "lexical" | "semantic" | "hybrid" | "none"
    mode: str
    results: list[SearchHit]
    documents_in_scope: int
    indexed_documents_in_scope: int
    chunks_searched: int
    # Plain-English explanation when `results` is empty.
    reason: str = ""
    semantic_error: str = ""


# --------------------------------------------------------------------------
# Conversations & messages
# --------------------------------------------------------------------------
class AttachmentIn(ApiModel):
    """An attachment referenced by a chat request.

    `id` is the one field that matters: it names a stored attachment whose
    bytes the server loads. The rest is display metadata the client already
    has. An id belonging to another user is ignored - see the chat route.
    """

    id: str | None = None
    name: str
    size: str = ""
    type: str = ""


class AttachmentOut(ApiModel):
    """A stored chat attachment.

    `readable` is the honest bit: an image is only useful if a vision model
    is configured, and the user should learn that when they attach it rather
    than from an answer that quietly ignored the picture.
    """

    id: str
    name: str
    content_type: str
    size_bytes: int
    is_image: bool

    # Set when the attachment is a document rather than an image: it was
    # extracted and indexed, and this is the document it produced. The
    # client uses it to offer "keep this in my files" afterwards.
    document_id: str | None = None
    readable: bool
    note: str


class MessageOut(ApiModel):
    id: str
    sender: str
    text: str
    # The instant the message was stored, timezone-aware UTC. The client
    # formats it in the *viewer's* timezone and locale.
    #
    # This used to ship a pre-rendered "10:24 AM" string built from the
    # server's naive local clock. That is wrong twice over: every viewer saw
    # the server's timezone rather than their own, and seeded rows carried a
    # literal hardcoded time, so one thread could show 1:43 AM, 2:05 AM and
    # 10:24 AM side by side. Send the instant; let the client render it.
    created_at: UtcDateTime
    # Primary citation, and the full list. Both are built from retrieved
    # passages; neither is ever parsed out of the model's own text.
    source: dict[str, Any] | None = None
    sources: list[dict[str, Any]] | None = None
    activity_trace: list[dict[str, Any]] | None = None
    attachments: list[dict[str, Any]] | None = None
    # Present once a report has been generated from this reply, so reopening
    # the conversation shows the document that was produced rather than
    # offering to build a new one.
    report: dict[str, Any] | None = None


class ConversationOut(ApiModel):
    id: str
    title: str
    user_id: str
    agent_id: str | None
    agent_name: str
    pinned: bool = False
    # Empty means this chat routes normally.
    model_override: str = ""
    created_at: UtcDateTime
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationCreate(ApiModel):
    agent_id: str | None = None
    agent_name: str = ""
    title: str = "New Conversation"


class ConversationUpdate(ApiModel):
    title: str | None = None
    pinned: bool | None = None
    # Pin this thread to a specific model. Empty string clears it and
    # returns the chat to normal routing. Provider-qualified
    # ("gemini:gemini-2.5-flash") so a pinned chat stays with its vendor
    # even if the deployment default changes.
    model_override: str | None = None


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
class ChatRequest(ApiModel):
    message: str = ""
    conversation_id: str | None = None
    agent_id: str | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list)


class ChatResponse(ApiModel):
    conversation_id: str
    user_message: MessageOut
    assistant_message: MessageOut
    # Honest provenance marker. "none" when no model is configured.
    provider: str
    model: str | None = None
    # How this turn's context was retrieved: "lexical", "semantic",
    # "hybrid", or "none" when nothing was retrieved.
    retrieval_mode: str = "none"


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
class NotificationOut(ApiModel):
    id: str
    title: str
    description: str
    read: bool
    # UI shows a relative label like "10 min ago".
    time: str
