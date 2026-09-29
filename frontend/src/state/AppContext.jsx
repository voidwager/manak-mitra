import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { api, ApiError, getActiveToken, setActiveToken } from '../services/api';

const AppContext = createContext();

/** Applied before any data loads so the UI never flashes the wrong theme. */
const applyTheme = (themeMode) => {
  let effective = themeMode;
  if (themeMode === 'system') {
    effective = window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }
  document.documentElement.setAttribute('data-theme', effective);
};

const DEFAULT_SETTINGS = {
  theme: 'system',
  compactMode: false,
  showTimestamps: true,
  showAgentActivity: true,
  temperature: 0.2,
  responseStyle: 'Balanced',
};


/**
 * Placeholder id for the assistant bubble that is being streamed into.
 * Replaced by the persisted message once the stream completes.
 */
const STREAMING_ID = '__streaming__';

export const AppProvider = ({ children }) => {
  // --- session -------------------------------------------------------
  const [currentUser, setCurrentUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(true);

  // --- backend connection --------------------------------------------
  const [health, setHealth] = useState(null);
  const [connectionError, setConnectionError] = useState(null);

  // --- data ----------------------------------------------------------
  const [agents, setAgents] = useState([]);
  const [activeAgent, setActiveAgent] = useState(null);
  // Models a chat may be pinned to, and which vendors have credentials.
  // Read from /api/models so the picker offers what this deployment is
  // actually configured for rather than a hardcoded list.
  const [modelCatalogue, setModelCatalogue] = useState({
    selectable: [],
    providers: [],
    routes: [],
  });
  const [documents, setDocuments] = useState([]);
  // The persona roster. Loaded for the login screen already; kept here so
  // ownership transfer can name a real user rather than ask for an id.
  const [users, setUsers] = useState([]);
  // Folder namespace plus what this user may file into. Advisory for the
  // UI only - the server re-checks every write, so a stale list produces a
  // clear 403 rather than an unintended grant.
  const [folders, setFolders] = useState({ all: [], assignable: [], unrestricted: false });
  const [tools, setTools] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);

  // --- ui ------------------------------------------------------------
  const [activeTab, setActiveTab] = useState('chat');
  const [attachments, setAttachments] = useState([]);
  const [isTyping, setIsTyping] = useState(false);

  /**
   * What the server is doing right now, for the waiting state.
   *
   * Every stage after the opening one is reported by the stream - a real tool
   * name, a real passage count - rather than scripted on a timer. A spinner
   * that invents progress would undercut the one claim this product actually
   * makes: that the activity trace is derived from the running system rather
   * than asserted.
   */
  const [streamStage, setStreamStage] = useState(null);
  const [activeModal, setActiveModal] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [errorBanner, setErrorBanner] = useState(null);

  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.read).length,
    [notifications],
  );

  const activeConversation = useMemo(
    () =>
      conversations.find((c) => c.id === activeConversationId) ||
      conversations[0] ||
      null,
    [conversations, activeConversationId],
  );

  /** Surface a failure rather than silently swallowing it. */
  const reportError = useCallback((error, context) => {
    console.error(`[${context}]`, error);
    if (error instanceof ApiError && error.isOffline) {
      setConnectionError(error.message);
    }
    setErrorBanner({
      context,
      message: error?.message || 'Something went wrong.',
    });
  }, []);

  const clearError = useCallback(() => setErrorBanner(null), []);

  // ------------------------------------------------------------------
  // Data loading
  // ------------------------------------------------------------------
  const loadWorkspace = useCallback(async () => {
    const [
      loadedAgents,
      loadedDocs,
      loadedTools,
      loadedConvs,
      loadedSettings,
      loadedNotifs,
      loadedFolders,
      loadedUsers,
      loadedModels,
    ] = await Promise.all([
      api.getAgents(),
      api.getDocuments(),
      api.getTools(),
      api.getConversations(),
      api.getSettings(),
      api.getNotifications(),
      api.getFolders(),
      api.getUsers(),
      api.getModels(),
    ]);

    setAgents(loadedAgents);
    setModelCatalogue(loadedModels);
    setActiveAgent((prev) => {
      const stillExists = prev && loadedAgents.find((a) => a.id === prev.id);
      // SI-1 by default: it dispatches to a specialist itself, so nobody has
      // to know which specialist they need before they know what they are
      // asking. A specialist is still selectable by hand.
      const universal = loadedAgents.find((a) => a.isUniversal);
      return stillExists || universal || loadedAgents[0] || null;
    });

    setDocuments(loadedDocs);
    setFolders(loadedFolders);
    setUsers(loadedUsers);
    setTools(loadedTools);
    setConversations(loadedConvs);
    setActiveConversationId(loadedConvs[0]?.id ?? null);
    setSettings(loadedSettings);
    setNotifications(loadedNotifs);

    applyTheme(loadedSettings.theme);
  }, []);

  // While the theme is "system", follow the OS as it changes rather than
  // only reading it once at load.
  useEffect(() => {
    if (settings.theme !== 'system') return undefined;

    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const sync = () => applyTheme('system');
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, [settings.theme]);

  // Restore a previous session and check the backend on first mount.
  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const status = await api.getHealth();
        if (cancelled) return;
        setHealth(status);
        setConnectionError(null);
      } catch (error) {
        if (cancelled) return;
        setConnectionError(error.message);
        setBootstrapping(false);
        return;
      }

      // A stored token is a claim, not proof. The server decides whether it
      // is still live - it may have been revoked, expired, or idled out
      // since this browser last used it.
      if (!getActiveToken()) {
        if (!cancelled) setBootstrapping(false);
        return;
      }

      try {
        const user = await api.getCurrentUser();
        if (!cancelled) {
          setCurrentUser(user);
          setIsAuthenticated(true);
          await loadWorkspace();
        }
      } catch (error) {
        // 401 means the session is simply over - that is an ordinary
        // outcome, not a failure worth putting a banner in front of.
        setActiveToken(null);
        if (!cancelled && !(error instanceof ApiError && error.status === 401)) {
          reportError(error, 'restore session');
        }
      } finally {
        if (!cancelled) setBootstrapping(false);
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [loadWorkspace, reportError]);

  // ------------------------------------------------------------------
  // Auth
  // ------------------------------------------------------------------
  const login = useCallback(
    async ({ email, password }) => {
      try {
        const user = await api.login({ email, password });
        setCurrentUser(user);
        setIsAuthenticated(true);
        setActiveTab('chat');
        await loadWorkspace();
        return user;
      } catch (error) {
        reportError(error, 'sign in');
        throw error;
      }
    },
    [loadWorkspace, reportError],
  );

  const logout = useCallback(async () => {
    // Ends the session server-side, so the token is dead everywhere rather
    // than just forgotten by this browser.
    await api.logout();
    setCurrentUser(null);
    setIsAuthenticated(false);
    setAgents([]);
    setDocuments([]);
    setTools([]);
    setConversations([]);
    setNotifications([]);
    setActiveConversationId(null);
    setActiveAgent(null);
    setAttachments([]);
  }, []);

  // ------------------------------------------------------------------
  // Settings
  // ------------------------------------------------------------------
  const updateSettingsAction = useCallback(
    async (patch) => {
      const previous = settings;
      // Optimistic: toggles should feel instant.
      setSettings((s) => ({ ...s, ...patch }));
      if (patch.theme) applyTheme(patch.theme);

      try {
        const saved = await api.updateSettings(patch);
        setSettings(saved);
        applyTheme(saved.theme);
      } catch (error) {
        setSettings(previous);
        applyTheme(previous.theme);
        reportError(error, 'save settings');
      }
    },
    [settings, reportError],
  );

  const updateTheme = useCallback(
    (theme) => updateSettingsAction({ theme }),
    [updateSettingsAction],
  );

  // ------------------------------------------------------------------
  // Agents & tools
  // ------------------------------------------------------------------
  const selectAgent = useCallback(
    (agentId) => {
      const agent = agents.find((a) => a.id === agentId);
      if (agent) setActiveAgent(agent);
    },
    [agents],
  );

  const createAgentSubmit = useCallback(
    async (agentData) => {
      try {
        const created = await api.createAgent(agentData);
        setAgents((prev) => [created, ...prev]);
        setActiveAgent(created);
        setActiveModal(null);
      } catch (error) {
        reportError(error, 'create agent');
      }
    },
    [reportError],
  );

  const toggleToolState = useCallback(
    async (toolId) => {
      try {
        setTools(await api.toggleTool(toolId));
      } catch (error) {
        reportError(error, 'toggle tool');
      }
    },
    [reportError],
  );

  // ------------------------------------------------------------------
  // Conversations & chat
  // ------------------------------------------------------------------
  const handleNewChat = useCallback(async () => {
    try {
      const conv = await api.createConversation({
        agentId: activeAgent?.id,
        agentName: activeAgent?.name,
      });
      setConversations((prev) => [{ ...conv, messages: [] }, ...prev]);
      setActiveConversationId(conv.id);
      setAttachments([]);
      setActiveTab('chat');
    } catch (error) {
      reportError(error, 'start conversation');
    }
  }, [activeAgent, reportError]);

  const loadConversation = useCallback((convId) => {
    setActiveConversationId(convId);
    setActiveTab('chat');
  }, []);

  /** Pinned threads sort above the rest; the server owns the ordering. */
  const toggleConversationPin = useCallback(
    async (convId) => {
      const conv = conversations.find((c) => c.id === convId);
      if (!conv) return;
      const next = !conv.pinned;

      // Optimistic, with the same ordering rule the API uses.
      setConversations((prev) =>
        [...prev.map((c) => (c.id === convId ? { ...c, pinned: next } : c))].sort(
          (a, b) =>
            Number(b.pinned ?? false) - Number(a.pinned ?? false) ||
            new Date(b.createdAt) - new Date(a.createdAt),
        ),
      );

      try {
        await api.setConversationPinned(convId, next);
      } catch (error) {
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? { ...c, pinned: !next } : c)),
        );
        reportError(error, next ? 'pin conversation' : 'unpin conversation');
      }
    },
    [conversations, reportError],
  );

  const deleteConversation = useCallback(
    async (convId) => {
      const previous = conversations;
      const remaining = conversations.filter((c) => c.id !== convId);

      setConversations(remaining);
      if (activeConversationId === convId) {
        setActiveConversationId(remaining[0]?.id ?? null);
      }

      try {
        await api.deleteConversation(convId);
      } catch (error) {
        setConversations(previous);
        reportError(error, 'delete conversation');
      }
    },
    [conversations, activeConversationId, reportError],
  );

  /** Add or replace messages on a conversation, creating it if needed. */
  const upsertConversation = useCallback(
    (conversationId, updater, seed = {}) => {
      setConversations((prev) => {
        const exists = prev.some((c) => c.id === conversationId);
        if (exists) {
          return prev.map((c) => (c.id === conversationId ? updater(c) : c));
        }
        return [
          updater({
            id: conversationId,
            title: 'New Conversation',
            userId: currentUser?.id,
            agentId: activeAgent?.id ?? null,
            agentName: activeAgent?.name ?? '',
            createdAt: new Date().toISOString(),
            messages: [],
            ...seed,
          }),
          ...prev,
        ];
      });
    },
    [currentUser, activeAgent],
  );

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() && attachments.length === 0) return;

      const sentAttachments = attachments;
      setAttachments([]);
      setIsTyping(true);

      let streamingConvId = activeConversationId;
      let receivedAnyToken = false;

      const finish = () => {
      setIsTyping(false);
      setStreamStage(null);
    };

      try {
        await api.streamMessage(
          {
            message: text,
            conversationId: activeConversationId,
            agentId: activeAgent?.id,
            attachments: sentAttachments,
          },
          {
            onStart: ({ conversationId, conversationTitle, userMessage }) => {
              setStreamStage({ key: 'start', label: 'Getting your answer ready' });
              streamingConvId = conversationId;
              setActiveConversationId(conversationId);
              upsertConversation(conversationId, (conv) => ({
                ...conv,
                title: conversationTitle || conv.title,
                messages: [
                  ...conv.messages,
                  userMessage,
                  // Empty assistant bubble that fills in as tokens arrive.
                  {
                    id: STREAMING_ID,
                    sender: 'assistant',
                    // The real row gets its createdAt from the server on
                    // `done`; until then the bubble is timed from this client
                    // so it sorts and renders like any other message instead
                    // of showing a blank slot.
                    createdAt: new Date().toISOString(),
                    text: '',
                    streaming: true,
                  },
                ],
              }));
            },

            // Tools run before the first token, so their steps appear in
            // the activity panel while the answer is still being written.
            // Replaced wholesale by the persisted trace on `done`.
            onTool: ({ name, arguments: args, ok }) => {
              setStreamStage({ key: `tool:${name}`, label: `Running ${name}` });
              const rendered = Object.entries(args ?? {})
                .map(([k, v]) => `${k}=${String(v).slice(0, 60)}`)
                .join(', ');
              setConversations((prev) =>
                prev.map((c) =>
                  c.id !== streamingConvId
                    ? c
                    : {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === STREAMING_ID
                            ? {
                                ...m,
                                activityTrace: [
                                  ...(m.activityTrace ?? []),
                                  {
                                    label: `Tool: ${name}(${rendered})`,
                                    status: ok ? 'done' : 'skipped',
                                  },
                                ],
                              }
                            : m,
                        ),
                      },
                ),
              );
            },

            // Retrieval completes before generation starts, so the sources
            // appear under the answer while it is still being written.
            onSources: (sources) => {
              if (!sources?.length) return;
              const documents = new Set(sources.map((src) => src.documentId)).size;
              setStreamStage({
                key: 'sources',
                label:
                  `Reading ${sources.length} passage${sources.length === 1 ? '' : 's'}` +
                  ` from ${documents} document${documents === 1 ? '' : 's'}`,
              });
              setConversations((prev) =>
                prev.map((c) =>
                  c.id !== streamingConvId
                    ? c
                    : {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === STREAMING_ID
                            ? { ...m, source: sources[0], sources }
                            : m,
                        ),
                      },
                ),
              );
            },

            onDelta: (chunk) => {
              if (!chunk) return;
              if (!receivedAnyToken) {
                receivedAnyToken = true;
                setIsTyping(false);
                setStreamStage(null);
              }
              setConversations((prev) =>
                prev.map((c) =>
                  c.id !== streamingConvId
                    ? c
                    : {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === STREAMING_ID ? { ...m, text: m.text + chunk } : m,
                        ),
                      },
                ),
              );
            },

            onDone: ({ assistantMessage }) => {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id !== streamingConvId
                    ? c
                    : {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === STREAMING_ID ? assistantMessage : m,
                        ),
                      },
                ),
              );
              finish();
            },

            onError: ({ message }) => {
              // Drop the empty bubble; the user's message stays.
              setConversations((prev) =>
                prev.map((c) =>
                  c.id !== streamingConvId
                    ? c
                    : { ...c, messages: c.messages.filter((m) => m.id !== STREAMING_ID) },
                ),
              );
              setErrorBanner({ context: 'generate a reply', message });
              finish();
            },
          },
        );
      } catch (error) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id !== streamingConvId
              ? c
              : { ...c, messages: c.messages.filter((m) => m.id !== STREAMING_ID) },
          ),
        );
        // The user message was persisted server-side before inference ran,
        // so only re-offer the attachments.
        setAttachments(sentAttachments);
        reportError(error, 'send message');
      } finally {
        finish();
      }
    },
    [
      attachments,
      activeConversationId,
      activeAgent,
      upsertConversation,
      reportError,
    ],
  );

  // ------------------------------------------------------------------
  // Attachments & documents
  // ------------------------------------------------------------------
  /**
   * Attach a file to the next message.
   *
   * The bytes are uploaded immediately rather than at send time, so the user
   * learns straight away whether the model can read it - an image with no
   * vision model configured is worth saying out loud before they ask their
   * question, not after.
   *
   * A placeholder appears first so the chip does not pop in late on a slow
   * connection, and is replaced by the stored attachment.
   */
  const addAttachment = useCallback(
    async (file) => {
      const placeholderId = `pending-${Date.now()}`;
      setAttachments((prev) => [
        ...prev,
        {
          id: placeholderId,
          name: file.name,
          size: `${(file.size / 1024).toFixed(1)} KB`,
          type: file.type || file.name.split('.').pop(),
          uploading: true,
        },
      ]);

      try {
        const stored = await api.uploadAttachment(file);
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === placeholderId
              ? {
                  id: stored.id,
                  name: stored.name,
                  size: `${(stored.sizeBytes / 1024).toFixed(1)} KB`,
                  type: stored.contentType,
                  isImage: stored.isImage,
                  readable: stored.readable,
                  note: stored.note,
                }
              : a,
          ),
        );
        return stored;
      } catch (error) {
        setAttachments((prev) => prev.filter((a) => a.id !== placeholderId));
        reportError(error, 'attach file');
        return null;
      }
    },
    [reportError],
  );

  const removeAttachment = useCallback((index) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  /**
   * Poll one document until indexing finishes.
   *
   * Indexing runs as a background task on the server, so the upload/index
   * response says "Processing" and the real outcome - Indexed, or a named
   * failure - arrives afterwards. Polling stops on any terminal status, and
   * gives up after a bounded number of attempts rather than looping for
   * ever on a stuck job.
   */
  const watchIndexing = useCallback(async (documentId, { attempts = 40 } = {}) => {
    for (let i = 0; i < attempts; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, i < 5 ? 700 : 2000));

      let doc;
      try {
        doc = await api.getDocument(documentId);
      } catch {
        return null; // deleted, or the backend went away - nothing to report
      }

      setDocuments((prev) => prev.map((d) => (d.id === doc.id ? doc : d)));
      if (doc.status !== 'Processing') return doc;
    }
    return null;
  }, []);

  const uploadDocFile = useCallback(
    async (file) => {
      try {
        const doc = await api.uploadDocument(file);
        setDocuments((prev) => [doc, ...prev]);
        setNotifications(await api.getNotifications());
        // Indexing was queued server-side; follow it so the row stops
        // saying "Processing" without the user reloading.
        if (doc.status === 'Processing') watchIndexing(doc.id);
        return doc;
      } catch (error) {
        reportError(error, 'upload document');
        return null;
      }
    },
    [reportError, watchIndexing],
  );

  /** (Re-)index a stored document. */
  const indexDocument = useCallback(
    async (documentId) => {
      try {
        const { document: doc } = await api.indexDocument(documentId);
        setDocuments((prev) => prev.map((d) => (d.id === doc.id ? doc : d)));
        return watchIndexing(documentId);
      } catch (error) {
        reportError(error, 'index document');
        return null;
      }
    },
    [reportError, watchIndexing],
  );

  const deleteDocFile = useCallback(
    async (documentId) => {
      try {
        await api.deleteDocument(documentId);
        setDocuments((prev) => prev.filter((d) => d.id !== documentId));
        return true;
      } catch (error) {
        reportError(error, 'delete document');
        return false;
      }
    },
    [reportError],
  );

  /**
   * Change document metadata.
   *
   * Returns the updated document, or null on failure. Refuses are reported
   * with the server's own wording, because a folder move is refused for a
   * specific reason ("you are not assigned to Safety") that a generic
   * "could not update" would throw away.
   *
   * A move can change which documents this user sees at all - filing one
   * out of reach removes it - so the list is reloaded rather than patched
   * in place.
   */
  const updateDocument = useCallback(
    async (documentId, patch) => {
      try {
        const updated = await api.updateDocument(documentId, patch);
        const [docs, loadedFolders] = await Promise.all([
          api.getDocuments(),
          // A move may have created a folder that did not exist before.
          api.getFolders(),
        ]);
        setDocuments(docs);
        setFolders(loadedFolders);
        return updated;
      } catch (error) {
        reportError(error, 'update document');
        return null;
      }
    },
    [reportError],
  );

  /** Save the original file to the user's machine. */
  const downloadDocFile = useCallback(
    async (doc) => {
      try {
        return await api.downloadDocument(doc.id, doc.name);
      } catch (error) {
        reportError(error, 'download document');
        return null;
      }
    },
    [reportError],
  );

  /**
   * Search the knowledge base without involving the model.
   *
   * Returns the raw response so a caller can show the mode and the reason
   * an empty result was empty, rather than a bare "no results".
   */
  const searchKnowledgeBase = useCallback(
    async (query, topK) => {
      try {
        return await api.searchKnowledgeBase(query, topK);
      } catch (error) {
        reportError(error, 'search the knowledge base');
        return null;
      }
    },
    [reportError],
  );

  const openDocPreview = useCallback((docOrSource) => {
    setActiveModal({ type: 'docPreview', data: docOrSource });
  }, []);

  const updateAgentConfig = useCallback(
    async (agentId, patch) => {
      try {
        const updated = await api.updateAgent(agentId, patch);
        setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
        setActiveAgent((prev) => (prev?.id === updated.id ? updated : prev));
        return updated;
      } catch (error) {
        reportError(error, 'update agent');
        return null;
      }
    },
    [reportError],
  );

  const deleteAgent = useCallback(
    async (agentId) => {
      try {
        await api.deleteAgent(agentId);
        const remaining = await api.getAgents();
        setAgents(remaining);
        // Never leave the workspace pointing at an agent that is gone.
        setActiveAgent((prev) =>
          prev?.id === agentId ? remaining[0] ?? null : prev,
        );
        return true;
      } catch (error) {
        reportError(error, 'delete agent');
        return false;
      }
    },
    [reportError],
  );

  /**
   * Pin the active chat to one model, or pass '' to return it to routing.
   *
   * The chat is reloaded rather than patched in place so what the UI shows
   * is what the server stored - the two disagreeing about which model a
   * thread uses would be worse than a moment's delay.
   */
  const setChatModel = useCallback(
    async (conversationId, modelOverride) => {
      try {
        const updated = await api.setConversationModel(
          conversationId,
          modelOverride,
        );
        setConversations((prev) =>
          prev.map((c) =>
            c.id === updated.id ? { ...c, modelOverride: updated.modelOverride } : c,
          ),
        );
        return updated;
      } catch (error) {
        reportError(error, 'change the model for this chat');
        return null;
      }
    },
    [reportError],
  );

  const openDocSettings = useCallback((doc) => {
    setActiveModal({ type: 'docSettings', data: doc });
  }, []);

  // ------------------------------------------------------------------
  // Reports
  // ------------------------------------------------------------------
  const [reportPendingFor, setReportPendingFor] = useState(null);

  /**
   * Build the report for one reply, on the server.
   *
   * Takes the message rather than the conversation: a report is about a
   * specific answer and the evidence behind *it*. The old version assembled
   * something from the whole thread in the browser, which is why it could
   * only ever produce placeholders - the browser does not know which tools
   * ran or which model answered.
   *
   * A stored report is returned as-is rather than rebuilt. Regenerating it
   * later against a changed corpus would put a different document under the
   * same heading.
   */
  const generateReportAction = useCallback(
    async (message) => {
      if (!message?.id || !activeConversationId) return;

      if (message.report) {
        setActiveModal({ type: 'report', data: message.report });
        return;
      }

      setReportPendingFor(message.id);
      try {
        const { report } = await api.generateReport(activeConversationId, message.id);

        // Keep it on the message so reopening the thread shows this document
        // rather than generating a second one.
        setConversations((prev) =>
          prev.map((c) =>
            c.id !== activeConversationId
              ? c
              : {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === message.id ? { ...m, report } : m,
                  ),
                },
          ),
        );
        setActiveModal({ type: 'report', data: report });
      } catch (err) {
        setErrorBanner({
          context: 'generate a report',
          message: err?.message || 'The report could not be generated.',
        });
      } finally {
        setReportPendingFor(null);
      }
    },
    [activeConversationId],
  );

  // ------------------------------------------------------------------
  // Notifications
  // ------------------------------------------------------------------
  const markNotifRead = useCallback(
    async (id) => {
      try {
        setNotifications(await api.markNotificationRead(id));
      } catch (error) {
        reportError(error, 'update notification');
      }
    },
    [reportError],
  );

  const retryConnection = useCallback(async () => {
    setConnectionError(null);
    try {
      setHealth(await api.getHealth());
      if (isAuthenticated) await loadWorkspace();
    } catch (error) {
      setConnectionError(error.message);
    }
  }, [isAuthenticated, loadWorkspace]);

  const value = {
    // session
    currentUser,
    isAuthenticated,
    bootstrapping,
    login,
    logout,

    // backend status
    health,
    connectionError,
    retryConnection,
    errorBanner,
    clearError,

    // navigation
    activeTab,
    setActiveTab,

    // data
    agents,
    activeAgent,
    selectAgent,
    modelCatalogue,
    setChatModel,
    createAgentSubmit,
    updateAgentConfig,
    deleteAgent,
    users,
    documents,
    folders,
    uploadDocFile,
    indexDocument,
    updateDocument,
    deleteDocFile,
    downloadDocFile,
    searchKnowledgeBase,
    tools,
    toggleToolState,
    conversations,
    activeConversation,
    activeConversationId,
    loadConversation,
    toggleConversationPin,
    deleteConversation,
    handleNewChat,
    sendMessage,
    notifications,
    markNotifRead,
    unreadCount,
    settings,
    updateSettingsAction,
    updateTheme,

    // ui
    attachments,
    addAttachment,
    removeAttachment,
    isTyping,
    activeModal,
    setActiveModal,
    openDocPreview,
    openDocSettings,
    generateReportAction,
    reportPendingFor,
    streamStage,
    sidebarCollapsed,
    setSidebarCollapsed,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
};

export const useApp = () => useContext(AppContext);
