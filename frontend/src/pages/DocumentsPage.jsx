import React, { useRef, useState } from 'react';
import { useApp } from '../state/AppContext';
import {
  FileText,
  Upload,
  Search,
  CheckCircle2,
  Clock,
  ShieldCheck,
  FolderLock,
  Lock,
  Eye,
  AlertTriangle,
  Ban,
  Loader2,
  Layers,
  RefreshCw,
  Download,
  Settings2,
  Trash2,
  ShieldAlert,
  Share2,
  ChevronDown,
  ChevronRight,
  Folder,
  MessageSquare,
} from 'lucide-react';

/**
 * Indexing status, rendered from the backend's own status string.
 *
 * The five states are distinct on purpose. "Ready for indexing", "No
 * extractable text" and "Indexing failed" all mean the document is not
 * searchable, but only one of them is worth retrying and only one of them
 * is the user's to fix - collapsing them into a single grey badge is how
 * someone ends up wondering why the assistant cannot find their SOP.
 */
const IndexStatus = ({ doc }) => {
  if (doc.status === 'Indexed') {
    return (
      <span
        className="status-badge indexed"
        title={
          doc.isSemanticallyIndexed
            ? 'Searchable by keyword and by meaning.'
            : 'Searchable by keyword. No embedding provider was configured when this was indexed.'
        }
      >
        <CheckCircle2 size={12} />
        Indexed ({doc.chunks} chunks{doc.isSemanticallyIndexed ? ', semantic' : ''})
      </span>
    );
  }

  if (doc.status === 'Processing') {
    return (
      <span className="status-badge processing">
        <Loader2 size={12} className="spin" />
        Indexing…
      </span>
    );
  }

  if (doc.status === 'No extractable text') {
    return (
      <span className="status-badge unsupported" title={doc.indexError}>
        <Ban size={12} />
        No extractable text
      </span>
    );
  }

  if (doc.status === 'Indexing failed') {
    return (
      <span className="status-badge failed" title={doc.indexError}>
        <AlertTriangle size={12} />
        Indexing failed
      </span>
    );
  }

  return (
    <span className="status-badge ready">
      <Clock size={12} />
      Ready for indexing
    </span>
  );
};

/**
 * What each visibility actually means, in the user's terms. Personal is the
 * one worth stating plainly: it is the only place in the system that not
 * even an administrator can read, and a user who does not know that will
 * either over-share or never use it.
 */
const VISIBILITY_HINT = {
  personal:
    'Private to you. Nobody else can open or search this - administrators included.',
  restricted: 'Restricted. Only owner clearance can open or search this.',
  shared:
    'Shared. Everyone assigned to this folder can retrieve its contents in chat.',
  chat:
    'Attached to one chat. Searchable in that conversation only - not in your knowledge base, not in your other chats.',
};

/**
 * Two sections, because there are only two questions a reader has: can
 * anyone else see this, or not.
 *
 * Underneath, Private is still three distinct scopes - a personal file, a
 * chat-scoped file and a restricted one are governed by different rules and
 * are deliberately not merged. Collapsing them into one permission would
 * mean either administrators reading personal uploads again or losing the
 * restricted folder; grouping them under one heading is presentation, and
 * costs nothing.
 */
const PRIVATE_GROUPS = [
  { key: 'personal', name: 'My files' },
  { key: 'chat', name: 'Chat files' },
  { key: 'restricted', name: 'Confidential' },
];

export const DocumentsPage = () => {
  const {
    documents,
    uploadDocFile,
    indexDocument,
    downloadDocFile,
    deleteDocFile,
    openDocPreview,
    openDocSettings,
    currentUser,
    health,
  } = useApp();
  const [filterType, setFilterType] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const fileInputRef = useRef(null);

  const retrieval = health?.retrieval;
  const indexedCount = documents.filter((d) => d.status === 'Indexed').length;
  const chunkCount = documents.reduce((total, d) => total + (d.chunks || 0), 0);

  /**
   * Mirrors the server's rule so the UI does not offer an action that will
   * be refused. The server is still the authority - this only decides what
   * to render.
   */
  const canEdit = (doc) =>
    currentUser.accessLevel === 'OWNER' || doc.ownerId === currentUser.id;

  // Documents just uploaded, awaiting a keep-private / share decision.
  const [sharePrompt, setSharePrompt] = useState(null);

  const handleFileSelect = async (e) => {
    // Multi-select uploads one at a time: each file gets its own document
    // row and its own background indexing job, so a large PDF cannot hold
    // up a small text file queued behind it.
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // let the same file be chosen again after a delete

    const uploaded = [];
    for (const file of files) {
      const doc = await uploadDocFile(file);
      if (doc) uploaded.push(doc);
    }

    // Every upload lands private and is indexed there, so the assistant can
    // answer from it immediately - for the uploader alone. Sharing is a
    // separate, deliberate step, offered here rather than buried in a
    // settings modal the user has no particular reason to open.
    if (uploaded.length > 0) setSharePrompt(uploaded);
  };

  const confirmDelete = (doc) => {
    const indexed = doc.chunks
      ? ` Its ${doc.chunks} indexed passage${doc.chunks === 1 ? '' : 's'} will stop being searchable.`
      : '';
    if (window.confirm(`Delete "${doc.name}"?${indexed} This cannot be undone.`)) {
      deleteDocFile(doc.id);
    }
  };

  const filteredDocs = documents.filter(doc => {
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase());
    if (filterType === 'ALL') return matchesSearch;
    if (filterType === 'PDF') return matchesSearch && doc.type === 'PDF';
    if (filterType === 'CSV') return matchesSearch && doc.type === 'CSV';
    if (filterType === 'INDEXED') return matchesSearch && doc.status === 'Indexed';
    return matchesSearch;
  });

  /*
   * Grouped by folder rather than listed flat.
   *
   * The folder is not decoration here - it is the access boundary, and a
   * flat list of forty rows with a small tag on each makes "who can read
   * this" something the reader has to reconstruct row by row. Grouping puts
   * every document under the scope that governs it.
   *
   * Ordering is deliberate: the user's own private space first, because it
   * is the only folder that is theirs alone and the one they came to find;
   * shared folders next, alphabetically; the restricted folder last, since
   * most people never see it at all.
   */
  const sections = React.useMemo(() => {
    const priv = { personal: [], chat: [], restricted: [] };
    const shared = new Map();

    for (const doc of filteredDocs) {
      // A chat file is a personal file with a conversation attached, so the
      // order of these checks matters: it is listed as a chat file rather
      // than disappearing into "My files".
      if (doc.conversationId) priv.chat.push(doc);
      else if (doc.visibility === 'personal') priv.personal.push(doc);
      else if (doc.visibility === 'restricted') priv.restricted.push(doc);
      else {
        const key = doc.folder || 'Global';
        if (!shared.has(key)) shared.set(key, []);
        shared.get(key).push(doc);
      }
    }

    const privateGroups = PRIVATE_GROUPS.filter(
      (g) => priv[g.key].length > 0,
    ).map((g) => ({ id: `private-${g.key}`, name: g.name, kind: g.key, docs: priv[g.key] }));

    const publicGroups = [...shared.keys()]
      .sort((a, b) => a.localeCompare(b))
      .map((name) => ({
        id: `public-${name}`,
        name,
        kind: 'shared',
        docs: shared.get(name),
        // Folder names may be paths. Splitting on "/" is all the nesting
        // there is - folders are free-text strings, not rows, so a real
        // hierarchy would be a schema change rather than a display one.
        depth: name.split('/').length - 1,
        leaf: name.split('/').pop(),
      }));

    return [
      { id: 'private', label: 'Private', groups: privateGroups },
      { id: 'public', label: 'Public', groups: publicGroups },
    ].filter((section) => section.groups.length > 0);
  }, [filteredDocs]);

  const [collapsed, setCollapsed] = useState(() => new Set());

  const toggleFolder = (name) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // A folder is never collapsed while a search is narrowing the list -
  // hiding a match behind a collapsed header reads as "no results".
  const searching = searchQuery.trim().length > 0;

  const shareNow = (doc) => {
    setSharePrompt(null);
    // Reuses the document settings modal rather than duplicating a folder
    // picker: that form already states who gains retrieval access, and two
    // sharing UIs would eventually disagree about what sharing means.
    openDocSettings(doc);
  };

  return (
    <div className="page-container animate-fade-in">
      {sharePrompt && (
        <div className="modal-backdrop animate-fade-in" onClick={() => setSharePrompt(null)}>
          <div className="share-prompt subtle-card" onClick={(e) => e.stopPropagation()}>
            <div className="share-prompt-head">
              <div className="share-prompt-icon">
                <Lock size={18} />
              </div>
              <div>
                <h3 className="share-prompt-title">
                  {sharePrompt.length === 1
                    ? 'Uploaded and private'
                    : `${sharePrompt.length} files uploaded, all private`}
                </h3>
                <p className="share-prompt-sub">
                  Indexed into your personal space. The assistant can answer
                  from {sharePrompt.length === 1 ? 'it' : 'them'} right now -
                  for you only.
                </p>
              </div>
            </div>

            <ul className="share-prompt-list">
              {sharePrompt.map((doc) => (
                <li key={doc.id}>
                  <FileText size={13} />
                  <span>{doc.name}</span>
                </li>
              ))}
            </ul>

            <div className="share-prompt-note">
              <AlertTriangle size={14} />
              <span>
                Sharing a document lets everyone assigned to that folder
                retrieve its contents in chat, quoted and cited. Nobody -
                including administrators - can read it while it stays private.
              </span>
            </div>

            <div className="share-prompt-actions">
              <button className="ghost-btn" onClick={() => setSharePrompt(null)}>
                Keep private
              </button>
              {sharePrompt.length === 1 && (
                <button className="primary-btn" onClick={() => shareNow(sharePrompt[0])}>
                  <Share2 size={15} />
                  <span>Share this file</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileSelect}
        style={{ display: 'none' }}
        accept=".pdf,.csv,.tsv,.doc,.docx,.txt,.md,.png,.jpg"
        multiple
      />

      {/* Page Header */}
      <div className="page-header">
        <div>
          <div className="title-row">
            <h1 className="page-title">Knowledge Base & RAG Scope</h1>
            <span className={`rbac-scope-badge ${currentUser.accessLevel === 'OWNER' ? 'owner' : 'employee'}`}>
              {currentUser.accessLevel === 'OWNER' ? <ShieldCheck size={14} /> : <FolderLock size={14} />}
              <span>{currentUser.scopeLabel}</span>
            </span>
          </div>
          <p className="page-subtitle">
            {currentUser.accessLevel === 'OWNER' 
              ? 'Owner clearance: every shared folder and the restricted archive. Personal uploads stay private to their owner.' 
              : `Employee Clearance (${currentUser.name}): Restricted to assigned unit folders (${currentUser.assignedFolders.join(', ')}).`}
          </p>
        </div>
        <button 
          className="primary-btn"
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload size={16} />
          <span>Upload Document</span>
        </button>
      </div>

      {/*
        * What retrieval can currently do, read from /api/health rather than
        * asserted here. "Hybrid" appears only when an embedding provider is
        * actually configured; otherwise this says keyword-only, which is
        * the truth and still a working search.
        */}
      {retrieval && (
        <div className={`retrieval-strip ${retrieval.mode}`}>
          <Layers size={14} />
          <span className="retrieval-summary">{retrieval.summary}</span>
          <span className="retrieval-counts">
            {indexedCount} of {documents.length} document
            {documents.length === 1 ? '' : 's'} indexed · {chunkCount} passage
            {chunkCount === 1 ? '' : 's'} searchable in your scope
          </span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="doc-controls-bar">
        <div className="search-box">
          <Search size={16} className="search-box-icon" />
          <input 
            type="text" 
            placeholder="Search authorized documents by name..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="filter-pill-group">
          {['ALL', 'PDF', 'CSV', 'INDEXED'].map(f => (
            <button 
              key={f}
              className={`filter-pill ${filterType === f ? 'active' : ''}`}
              onClick={() => setFilterType(f)}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Documents Table View */}
      <div className="doc-table-card subtle-card">
        <table className="doc-table">
          <thead>
            <tr>
              <th>Document Name</th>
              <th>Type</th>
              <th>Size</th>
              <th>Uploaded Date</th>
              <th>Indexing Status</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredDocs.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-table-cell">
                  No matching authorized documents found in your current RAG scope.
                </td>
              </tr>
            ) : (
              sections.flatMap(section => [
                <tr key={`section-${section.id}`} className="scope-section-row">
                  <td colSpan={6}>
                    <span className="scope-section-label">{section.label}</span>
                    <span className="scope-section-count">
                      {section.groups.reduce((n, g) => n + g.docs.length, 0)}
                    </span>
                  </td>
                </tr>,
                ...section.groups.flatMap(group => [
                <tr
                  key={`group-${group.id}`}
                  className="folder-group-row"
                  onClick={() => toggleFolder(group.id)}
                >
                  <td colSpan={6}>
                    <div
                      className="folder-group-head"
                      style={{ paddingLeft: `${(group.depth ?? 0) * 18}px` }}
                    >
                      {!searching && collapsed.has(group.id) ? (
                        <ChevronRight size={15} />
                      ) : (
                        <ChevronDown size={15} />
                      )}
                      {/*
                        * The scope badge sits on the folder rather than on
                        * every row inside it. It reads the server's derived
                        * `visibility` - the rule lives in one place, and a
                        * second copy in the browser is how a badge ends up
                        * claiming privacy about something the API would hand
                        * to somebody else.
                        */}
                      <span
                        className={`folder-tag ${group.kind}`}
                        title={
                          VISIBILITY_HINT[group.kind] ??
                          `Searchable by everyone assigned to ${group.name}.`
                        }
                      >
                        {group.kind === 'personal' ? (
                          <Lock size={11} />
                        ) : group.kind === 'restricted' ? (
                          <ShieldAlert size={11} />
                        ) : group.kind === 'chat' ? (
                          <MessageSquare size={11} />
                        ) : (
                          <Folder size={11} />
                        )}
                        <span>{group.leaf ?? group.name}</span>
                      </span>
                      <span className="folder-group-count">
                        {group.docs.length} document{group.docs.length === 1 ? '' : 's'}
                      </span>
                      <span className="folder-group-scope">
                        {VISIBILITY_HINT[group.kind]}
                      </span>
                    </div>
                  </td>
                </tr>,
                ...(!searching && collapsed.has(group.id) ? [] : group.docs).map(doc => (
                <tr key={doc.id} className="doc-table-row">
                  <td>
                    <div className="doc-name-cell">
                      <div className={`doc-icon-badge ${doc.type.toLowerCase()}`}>
                        <FileText size={18} />
                      </div>
                      <div className="doc-title-info">
                        <span className="doc-title">
                          {doc.name}
                          {doc.isConfidentialOwnerOnly && (
                            <span className="confidential-badge" title="Owner Confidential Document">
                              <Lock size={12} /> Confidential
                            </span>
                          )}
                        </span>
                        {doc.section && <span className="doc-section-tag">{doc.section}</span>}
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="type-tag">{doc.type}</span>
                  </td>
                  <td>
                    <span className="meta-text">{doc.size}</span>
                  </td>
                  <td>
                    <span className="meta-text">{doc.date}</span>
                  </td>
                  <td>
                    <IndexStatus doc={doc} />
                    {doc.indexError && doc.status !== 'Indexed' && (
                      <div className="index-error-note">{doc.indexError}</div>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="doc-row-actions">
                      {/*
                        * Each action is offered only where it can do
                        * something. A catalogue row with no stored file has
                        * nothing to index or download, and the server refuses
                        * both - so the button is absent rather than present
                        * and broken.
                        */}
                      {doc.hasStoredFile && doc.status !== 'Processing' && (
                        <button
                          className="row-action-btn icon-only"
                          onClick={() => indexDocument(doc.id)}
                          title={
                            doc.status === 'Indexed'
                              ? 'Re-index this document (replaces its passages)'
                              : 'Extract, chunk and index this document'
                          }
                          aria-label="Index document"
                        >
                          <RefreshCw size={14} />
                        </button>
                      )}

                      {doc.hasStoredFile && (
                        <button
                          className="row-action-btn icon-only"
                          onClick={() => downloadDocFile(doc)}
                          title="Download the original file"
                          aria-label="Download document"
                        >
                          <Download size={14} />
                        </button>
                      )}

                      {canEdit(doc) && (
                        <button
                          className="row-action-btn icon-only"
                          onClick={() => openDocSettings(doc)}
                          title="Rename, move folder, change access"
                          aria-label="Document settings"
                        >
                          <Settings2 size={14} />
                        </button>
                      )}

                      {canEdit(doc) && (
                        <button
                          className="row-action-btn icon-only danger"
                          onClick={() => confirmDelete(doc)}
                          title="Delete this document and its indexed passages"
                          aria-label="Delete document"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}

                      <button
                        className="preview-doc-btn"
                        onClick={() => openDocPreview(doc)}
                        title="Preview Document Chunks"
                      >
                        <Eye size={14} />
                        <span>Preview</span>
                      </button>
                    </div>
                  </td>
                </tr>
                )),
                ]),
              ])
            )}
          </tbody>
        </table>
      </div>

      <style>{`
        .page-container {
          padding: 32px;
          height: 100%;
          overflow-y: auto;
          background-color: var(--bg-workspace);
        }

        .page-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          margin-bottom: 24px;
        }

        .title-row {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .page-title {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .rbac-scope-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 0.75rem;
          font-weight: 700;
        }

        .rbac-scope-badge.owner {
          background: var(--accent-light);
          color: var(--accent-text);
        }

        .rbac-scope-badge.employee {
          background: var(--warning-bg);
          color: var(--warning);
        }

        .page-subtitle {
          font-size: 0.875rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        .primary-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 18px;
          background-color: var(--accent-primary);
          color: var(--accent-contrast);
          border: none;
          border-radius: var(--radius-md);
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .doc-controls-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 20px;
          gap: 16px;
        }

        .search-box {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 16px;
          background: var(--bg-card);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          /* 340px is wider than a 360px phone once the page padding is
             taken off, so it pushed the whole page sideways. */
          width: min(340px, 100%);
        }

        .search-box-icon {
          color: var(--text-muted);
        }

        .search-box input {
          border: none;
          background: transparent;
          outline: none;
          font-size: 0.875rem;
          color: var(--text-primary);
          width: 100%;
        }

        .filter-pill-group {
          display: flex;
          gap: 6px;
        }

        .filter-pill {
          padding: 6px 14px;
          background: var(--bg-card);
          border: 1px solid var(--border-light);
          border-radius: 999px;
          font-size: 0.775rem;
          font-weight: 600;
          color: var(--text-secondary);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .filter-pill.active {
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border-color: var(--accent-primary);
        }

        .doc-table-card {
          background: var(--bg-card);
          border-radius: var(--radius-lg);
          overflow: hidden;
          /* The table has six columns and cannot shrink below its content.
             Scrolling it inside its own card keeps the page itself from
             scrolling sideways, which is what makes a layout feel broken. */
          overflow-x: auto;
        }

        @media (max-width: 768px) {
          .page-container { padding: 18px 16px 28px; }
          .page-header { gap: 12px; }
          .page-title { font-size: 1.25rem; }

          /* Least useful columns on a phone. Nothing is lost - the size and
             date are still on the document itself - and dropping them lets
             the name, status and actions fit without sideways scrolling. */
          .doc-table th:nth-child(3),
          .doc-table td:nth-child(3),
          .doc-table th:nth-child(4),
          .doc-table td:nth-child(4) {
            display: none;
          }

          .doc-table th,
          .doc-table td { padding: 10px 12px; }

          .row-actions { flex-wrap: wrap; justify-content: flex-end; }
          .share-prompt { padding: 18px; }
        }

        .doc-table {
          width: 100%;
          border-collapse: collapse;
          text-align: left;
        }

        .doc-table th {
          padding: 14px 20px;
          font-size: 0.75rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--text-muted);
          background: var(--bg-card-subtle);
          border-bottom: 1px solid var(--border-light);
        }

        .doc-table td {
          padding: 16px 20px;
          border-bottom: 1px solid var(--border-light);
          font-size: 0.875rem;
          vertical-align: middle;
        }

        .doc-table-row:hover {
          background: var(--bg-hover);
        }

        .doc-name-cell {
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .doc-icon-badge {
          width: 36px;
          height: 36px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .doc-icon-badge.pdf {
          background: var(--danger-bg);
          color: var(--danger);
        }

        .doc-icon-badge.csv {
          background: var(--success-bg);
          color: var(--success);
        }

        .doc-title-info {
          display: flex;
          flex-direction: column;
        }

        .doc-title {
          font-weight: 600;
          color: var(--text-primary);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .confidential-badge {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 0.7rem;
          font-weight: 700;
          color: var(--danger);
          background: var(--danger-bg);
          padding: 2px 6px;
          border-radius: 4px;
        }

        .doc-section-tag {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.45);
          backdrop-filter: blur(6px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 120;
          padding: 20px;
        }

        .share-prompt {
          width: 100%;
          max-width: 460px;
          max-height: calc(100vh - 40px);
          max-height: calc(100dvh - 40px);
          overflow-y: auto;
          padding: 22px;
          border-radius: var(--radius-lg);
          background: var(--bg-card);
        }

        .share-prompt-head {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          margin-bottom: 14px;
        }

        .share-prompt-icon {
          width: 38px;
          height: 38px;
          flex-shrink: 0;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--accent-light);
          color: var(--accent-primary);
        }

        .share-prompt-title {
          font-size: 1rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .share-prompt-sub {
          margin-top: 3px;
          font-size: 0.82rem;
          line-height: 1.45;
          color: var(--text-secondary);
        }

        .share-prompt-list {
          list-style: none;
          margin: 0 0 14px;
          padding: 10px 12px;
          border-radius: var(--radius-md);
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          max-height: 150px;
          overflow-y: auto;
        }

        .share-prompt-list li {
          display: flex;
          align-items: center;
          gap: 7px;
          font-size: 0.8rem;
          color: var(--text-secondary);
          padding: 3px 0;
        }

        .share-prompt-list li span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .share-prompt-note {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 10px 12px;
          margin-bottom: 16px;
          border-radius: var(--radius-md);
          background: var(--warning-bg);
          color: var(--text-secondary);
          font-size: 0.78rem;
          line-height: 1.5;
        }

        .share-prompt-note svg {
          flex-shrink: 0;
          margin-top: 1px;
          color: var(--warning);
        }

        .share-prompt-actions {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
        }

        .ghost-btn {
          padding: 9px 16px;
          border-radius: var(--radius-md);
          border: 1px solid var(--border-light);
          background: transparent;
          color: var(--text-primary);
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
        }

        .ghost-btn:hover { background: var(--bg-hover); }

        .scope-section-row td {
          padding: 14px 16px 6px !important;
          border-top: none;
        }

        .scope-section-label {
          font-size: 0.7rem;
          font-weight: 800;
          letter-spacing: 0.09em;
          text-transform: uppercase;
          color: var(--text-secondary);
        }

        .scope-section-count {
          margin-left: 8px;
          font-size: 0.68rem;
          font-weight: 700;
          padding: 1px 7px;
          border-radius: 999px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          color: var(--text-muted);
        }

        .folder-tag.chat {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          color: var(--accent-text);
        }

        .folder-group-row {
          cursor: pointer;
          user-select: none;
          background: var(--bg-card-subtle);
        }

        .folder-group-row:hover { background: var(--bg-hover); }

        .folder-group-row td {
          padding: 9px 16px !important;
          border-top: 1px solid var(--border-light);
        }

        .folder-group-head {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          color: var(--text-muted);
        }

        .folder-group-count {
          font-size: 0.74rem;
          color: var(--text-muted);
        }

        .folder-group-scope {
          font-size: 0.72rem;
          color: var(--text-muted);
          opacity: 0.75;
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .folder-tag.personal,
        .folder-tag.restricted {
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }

        .folder-tag.restricted {
          color: var(--warning);
        }

        .folder-tag {
          font-size: 0.75rem;
          font-weight: 600;
          color: var(--accent-primary);
          background: var(--accent-light);
          padding: 2px 8px;
          border-radius: 4px;
        }

        /* A shared folder is a grant; the personal namespace is not. They
           should not look identical, because the difference is who else can
           search the document. */
        .folder-tag.private {
          color: var(--text-muted);
          background: var(--bg-card-subtle);
        }

        .type-tag {
          font-size: 0.75rem;
          font-weight: 600;
          padding: 2px 8px;
          background: var(--bg-card-subtle);
          border-radius: 4px;
          color: var(--text-secondary);
        }

        .meta-text {
          color: var(--text-secondary);
          font-size: 0.825rem;
        }

        .status-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 0.75rem;
          font-weight: 600;
        }

        .status-badge.indexed {
          background: var(--success-bg);
          color: var(--success);
        }

        .status-badge.ready {
          background: var(--warning-bg);
          color: var(--warning);
        }

        .status-badge.processing {
          background: var(--bg-card-subtle);
          color: var(--text-secondary);
        }

        /* Not searchable and never will be without OCR - distinct from
           "failed", which is worth retrying. */
        .status-badge.unsupported {
          background: var(--bg-card-subtle);
          color: var(--text-muted);
        }

        .status-badge.failed {
          background: var(--danger-bg);
          color: var(--danger);
        }

        .spin {
          animation: doc-spin 1s linear infinite;
        }

        @keyframes doc-spin {
          to { transform: rotate(360deg); }
        }

        .index-error-note {
          margin-top: 6px;
          max-width: 320px;
          font-size: 0.7rem;
          line-height: 1.4;
          color: var(--text-muted);
        }

        /* Retrieval capability strip */
        .retrieval-strip {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          margin-bottom: 16px;
          padding: 10px 14px;
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          background: var(--bg-card-subtle);
          font-size: 0.775rem;
          color: var(--text-secondary);
        }

        .retrieval-strip.hybrid {
          border-color: var(--success);
          color: var(--text-primary);
        }

        .retrieval-strip.disabled {
          border-color: var(--danger);
          color: var(--danger);
        }

        .retrieval-summary {
          font-weight: 600;
          color: var(--text-primary);
        }

        .retrieval-counts {
          margin-left: auto;
          color: var(--text-muted);
        }

        .doc-row-actions {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          justify-content: flex-end;
        }

        .row-action-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: transparent;
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          font-size: 0.8rem;
          font-weight: 500;
          color: var(--text-secondary);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .row-action-btn:hover {
          color: var(--text-primary);
          border-color: var(--accent-primary);
          background: var(--bg-hover);
        }

        /* Icon-only actions keep the row readable once there are five of
           them; the accessible name lives in aria-label and title. */
        .row-action-btn.icon-only {
          padding: 6px 8px;
        }

        .row-action-btn.danger:hover {
          color: var(--danger);
          border-color: var(--danger);
        }

        .preview-doc-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          font-size: 0.8rem;
          font-weight: 500;
          color: var(--text-primary);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .preview-doc-btn:hover {
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border-color: var(--accent-primary);
        }

        .empty-table-cell {
          text-align: center;
          padding: 40px;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};
