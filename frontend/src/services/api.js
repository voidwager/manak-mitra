/**
 * Workbench API surface.
 *
 * Every backend call the application makes lives here. UI components import
 * nothing from this file directly - they read state from AppContext, which
 * is the only caller. That keeps the network boundary in one place when the
 * agent, RAG and model layers land.
 *
 * Field names come back camelCased from FastAPI, so responses drop straight
 * into the existing components.
 */

import { http, setActiveToken } from './http';
import { streamEvents } from './stream';

export { ApiError, API_BASE_URL, setActiveToken, getActiveToken } from './http';

export const api = {
  // ---------------------------------------------------------------- system
  getHealth: () => http.get('/health'),

  /** Model identifiers the configured provider can serve. */
  getModels: () => http.get('/models'),

  // ----------------------------------------------------------------- users
  getUsers: () => http.get('/users'),

  /**
   * Sign in with real credentials.
   *
   * The server verifies the password and returns a session token, which is
   * held for subsequent requests. Every failure returns the same message,
   * so this cannot be used to discover which accounts exist.
   */
  async login({ email, password }) {
    const { token, user } = await http.post('/auth/login', { email, password });
    setActiveToken(token);
    return user;
  },

  /** End the session server-side, not just locally. */
  async logout() {
    try {
      await http.post('/auth/logout');
    } catch {
      // A token that is already invalid is the state we wanted anyway.
    }
    setActiveToken(null);
  },

  /** Who the stored token belongs to. Used to restore a session. */
  getCurrentUser: () => http.get('/auth/me'),

  changePassword: (currentPassword, newPassword) =>
    http.post('/auth/password', { currentPassword, newPassword }),

  // ----------------------------------------------------------- governance
  /** The audit trail. Owner clearance only; the read is itself audited. */
  getAuditLog: (params) => http.get('/audit', { params }),
  getAuditActions: () => http.get('/audit/actions'),

  /** Sessions: your own, or everyone's with owner clearance. */
  getSessions: () => http.get('/sessions'),
  revokeSessions: (userId) => http.post(`/sessions/${userId}/revoke`),

  // -------------------------------------------------------------- settings
  getSettings: () => http.get('/settings'),
  updateSettings: (patch) => http.patch('/settings', patch),

  // ---------------------------------------------------------------- agents
  getAgents: () => http.get('/agents'),
  getAgent: (agentId) => http.get(`/agents/${agentId}`),
  createAgent: (agent) => http.post('/agents', agent),

  /**
   * Change an agent's configuration.
   *
   * `folderScope` and `retrievalEnabled` decide what the agent searches.
   * They narrow whoever uses it - the server intersects the scope with each
   * caller's own permissions - so naming a folder here grants nobody access.
   */
  updateAgent: (agentId, patch) => http.patch(`/agents/${agentId}`, patch),

  deleteAgent: (agentId) => http.del(`/agents/${agentId}`),

  // ----------------------------------------------------------------- tools
  getTools: () => http.get('/tools'),
  toggleTool: (toolId) => http.post(`/tools/${toolId}/toggle`),

  // ------------------------------------------------------------- documents
  /** Scoped server-side to what the signed-in user may see. */
  getDocuments: () => http.get('/documents'),
  getDocument: (documentId) => http.get(`/documents/${documentId}`),

  uploadDocument(file) {
    const form = new FormData();
    form.append('file', file);
    return http.upload('/documents', form);
  },

  /**
   * Change document metadata: name, folder, confidentiality, ownership.
   *
   * `folder`, `isConfidentialOwnerOnly` and `ownerId` are access-control
   * changes - between them they decide who can retrieve this document. The
   * server authorises each one and rejects the whole call with a reason, so
   * a 403 here is informative and worth surfacing verbatim.
   */
  updateDocument: (documentId, patch) => http.patch(`/documents/${documentId}`, patch),

  deleteDocument: (documentId) => http.del(`/documents/${documentId}`),

  /**
   * The folder namespace, and which folders this user may file into.
   *
   * `assignable` is advisory for the UI only - the server re-checks it on
   * every write, so a stale list produces a clear 403 rather than a silent
   * privilege escalation.
   */
  getFolders: () => http.get('/folders'),

  /**
   * Download the original uploaded file.
   *
   * Fetched rather than linked to: identity travels in the `X-User-Id`
   * header, and a plain `<a href>` navigation cannot set one, so a link
   * would arrive unauthenticated and 401. The bytes come back as a blob and
   * are handed to the browser through a temporary object URL.
   */
  async downloadDocument(documentId, fallbackName = 'document') {
    const { blob, filename } = await http.file(`/documents/${documentId}/download`);

    const url = URL.createObjectURL(blob);
    try {
      const link = window.document.createElement('a');
      link.href = url;
      link.download = filename || fallbackName;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      // Revoking immediately can cancel the download in some browsers, so
      // give the click a tick to be picked up first.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    }
    return filename || fallbackName;
  },

  /**
   * Queue a document for indexing. Returns immediately with the document in
   * `Processing`; indexing runs in the background, so the caller polls
   * `getDocument` until the status changes.
   *
   * Re-indexing an already-indexed document is how vectors are added after
   * an embedding provider is configured.
   */
  indexDocument: (documentId) => http.post(`/documents/${documentId}/index`),

  /** The indexed passages of a document - what retrieval actually searches. */
  getDocumentChunks: (documentId) => http.get(`/documents/${documentId}/chunks`),

  // ----------------------------------------------------------- attachments
  /**
   * Upload a file to attach to a chat turn.
   *
   * Separate from documents on purpose: an attachment is private to the
   * uploader and never indexed, whereas a document is shared, indexed and
   * retrievable by everyone in its folder.
   *
   * The response says whether the model can actually read it - an image is
   * only useful with a vision model configured, and the user should learn
   * that when attaching rather than from an answer that ignored the picture.
   */
  uploadAttachment(file) {
    const form = new FormData();
    form.append('file', file);
    return http.upload('/attachments', form);
  },

  /**
   * The attachment's bytes, as a Blob.
   *
   * Fetched rather than exposed as a URL: identity is a header, and an
   * `<img src>` cannot set one, so a plain link arrives unauthenticated and
   * 401s. A helper returning such a URL was worse than none - it looked
   * usable and produced a silently broken image.
   */
  async fetchAttachmentBlob(attachmentId) {
    const { blob } = await http.file(`/attachments/${attachmentId}`);
    return blob;
  },

  // ------------------------------------------------------------- retrieval
  /**
   * Search the knowledge base directly, with no model involved.
   *
   * Scoped server-side to the signed-in user, exactly like getDocuments -
   * there is no parameter that widens it.
   */
  searchKnowledgeBase: (query, topK = 5) =>
    http.post('/search', { query, topK }),

  // --------------------------------------------------------- conversations
  getConversations: () => http.get('/conversations'),
  getConversation: (conversationId) => http.get(`/conversations/${conversationId}`),

  createConversation: ({ agentId, agentName, title } = {}) =>
    http.post('/conversations', { agentId, agentName, title }),

  renameConversation: (conversationId, title) =>
    http.patch(`/conversations/${conversationId}`, { title }),

  setConversationPinned: (conversationId, pinned) =>
    http.patch(`/conversations/${conversationId}`, { pinned }),

  /**
   * Pin a chat to one model, or pass '' to return it to normal routing.
   *
   * The id is provider-qualified, so a chat pinned to Gemini stays on
   * Gemini even if the deployment's default provider changes.
   */
  setConversationModel: (conversationId, modelOverride) =>
    http.patch(`/conversations/${conversationId}`, { modelOverride }),

  deleteConversation: (conversationId) => http.del(`/conversations/${conversationId}`),

  /**
   * Build the inspection report for one assistant reply.
   *
   * The report is assembled and stored server-side, because its value is the
   * evidence trail - which documents were actually cited, which tools ran,
   * which model answered - and the browser holds none of that reliably. The
   * previous client-side version invented the lot.
   */
  generateReport: (conversationId, messageId) =>
    http.post(`/conversations/${conversationId}/messages/${messageId}/report`),

  // ------------------------------------------------------------------ chat
  /**
   * Sends a message and returns { conversationId, userMessage,
   * assistantMessage, provider, model }.
   *
   * `provider` is 'none' until a model gateway is wired up - the UI uses it
   * to avoid presenting the placeholder reply as a model answer.
   */
  sendMessage: ({ message, conversationId, agentId, attachments = [] }) =>
    http.post('/chat', { message, conversationId, agentId, attachments }),

  /**
   * Streaming variant. Calls handlers as tokens arrive:
   *   onStart({ conversationId, userMessage })
   *   onTool({ name, arguments, ok })
   *   onSources([{ documentId, title, page, section, excerpt, score }])
   *   onDelta(textChunk)
   *   onDone({ assistantMessage, provider, model })
   *   onError({ message })
   *
   * `onSources` fires once, before the first token, and only when retrieval
   * found something. No event means no sources.
   */
  streamMessage(
    { message, conversationId, agentId, attachments = [] },
    handlers,
    signal,
  ) {
    return streamEvents(
      '/chat/stream',
      { message, conversationId, agentId, attachments },
      handlers,
      signal,
    );
  },

  // --------------------------------------------------------- notifications
  getNotifications: () => http.get('/notifications'),
  markNotificationRead: (notificationId) =>
    http.post(`/notifications/${notificationId}/read`),
};

export default api;
