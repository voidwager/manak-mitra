import React, { useEffect, useState } from 'react';
import { X, FileText, ShieldCheck, Ban, Loader2, Download, ShieldX } from 'lucide-react';
import { api } from '../../services/api';
import { useApp } from '../../state/AppContext';

/**
 * Document preview - the other end of a citation.
 *
 * This modal used to render an authored SOP: a fixed body paragraph and a
 * table of bearing temperatures and vibration limits for "P-204", shown for
 * whichever document you clicked. Before Phase 8 there was no real text to
 * show, so it was a mockup; now that documents are actually extracted and
 * chunked, showing invented tolerances behind a citation would be the exact
 * failure the rest of the system is built to prevent - the citation would
 * look checkable and be fabricated.
 *
 * So everything here is real or absent:
 *   - the retrieved passage, when opened from a citation
 *   - the document's indexed chunks, fetched from the API
 *   - an explicit "not indexed" state, with the reason, when there are none
 *
 * Accepts either shape: a citation ({documentId, title, page, excerpt}) or
 * a document row ({id, name, ...}).
 */
export const DocumentPreviewModal = ({ docData, onClose }) => {
  const documentId = docData?.documentId ?? docData?.id ?? null;

  // null = still loading. A citation with no document id has nothing to
  // fetch, so it starts resolved rather than spinning for ever.
  const [chunks, setChunks] = useState(documentId ? null : []);
  const [loadError, setLoadError] = useState('');
  // Distinguishes "this document was never indexed" from "you can no longer
  // open it", which are the same empty chunk list but very different facts.
  const [accessRevoked, setAccessRevoked] = useState(false);

  const { documents, downloadDocFile } = useApp();

  useEffect(() => {
    let cancelled = false;
    if (!documentId) return undefined;

    api
      .getDocumentChunks(documentId)
      .then((rows) => {
        if (!cancelled) setChunks(rows);
      })
      .catch((error) => {
        if (cancelled) return;
        setChunks([]);
        // A citation is frozen into the message when the answer is written,
        // so a document can be reclassified or moved out of reach long
        // afterwards. Distinguish that from "never indexed" - they look
        // identical otherwise, and only one of them is something the user
        // can do anything about.
        setLoadError(
          error?.status === 404
            ? 'You no longer have access to this document. It may have been ' +
              'moved to another folder, reclassified, or deleted since this ' +
              'answer was written.'
            : error?.message || 'Could not load the indexed passages.',
        );
        setAccessRevoked(error?.status === 404);
      });

    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (!docData) return null;

  const fileName = docData.title || docData.name || 'Document';
  const citedExcerpt = docData.excerpt || '';
  const sectionTitle = docData.section || '';

  // A citation carries a rendered location string; a document row carries a
  // page number. Neither is invented when absent.
  const locationLabel =
    typeof docData.page === 'string'
      ? docData.page
      : docData.page
        ? `Page ${docData.page}`
        : '';

  const isIndexed = chunks !== null && chunks.length > 0;

  // Only offer a download for a document still in this user's scope that has
  // bytes behind it. A citation carries a title but not a storage flag, so
  // the live document row is the authority.
  const liveDocument = documents.find((d) => d.id === documentId);
  const downloadable =
    !accessRevoked && liveDocument?.hasStoredFile ? liveDocument : null;

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card doc-preview-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="doc-modal-title-group">
            <div className="pdf-badge-circle">
              <FileText size={20} />
            </div>
            <div>
              <h3 className="modal-doc-title">{fileName}</h3>
              <span className="modal-doc-meta">
                {[locationLabel, sectionTitle].filter(Boolean).join(' · ') ||
                  'Indexed document'}
              </span>
            </div>
          </div>

          <div className="modal-actions">
            {downloadable && (
              <button
                className="download-btn"
                onClick={() => downloadDocFile(downloadable)}
                title="Download the original file"
              >
                <Download size={16} />
                <span>Download</span>
              </button>
            )}
            <button className="close-btn" onClick={onClose} title="Close Preview">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="modal-body">
          <div className="preview-toolbar">
            <span className="sovereign-tag">
              <ShieldCheck size={14} />
              Sovereign document reader — extracted text only
            </span>
            {isIndexed && (
              <span className="section-label">
                {chunks.length} indexed passage{chunks.length === 1 ? '' : 's'}
              </span>
            )}
          </div>

          {/* The passage the answer was grounded in, when we arrived from a
              citation. Shown first because it is what the user clicked. */}
          {citedExcerpt && (
            <div className="document-page-sheet">
              <div className="sheet-header-line">
                <span>Cited passage</span>
                <span>{[locationLabel, sectionTitle].filter(Boolean).join(' · ')}</span>
              </div>
              <div className="highlighted-text-box">
                <p>{citedExcerpt}</p>
              </div>
            </div>
          )}

          {/* Everything retrieval can actually search in this document. */}
          <div className="chunk-list">
            {chunks === null && (
              <div className="preview-state">
                <Loader2 size={16} className="spin" />
                <span>Loading indexed passages…</span>
              </div>
            )}

            {chunks !== null && chunks.length === 0 && (
              <div className={`preview-state ${accessRevoked ? 'revoked' : 'muted'}`}>
                {accessRevoked ? <ShieldX size={16} /> : <Ban size={16} />}
                <span>
                  {loadError ||
                    'This document has no indexed passages, so retrieval cannot ' +
                      'search it. Index it from the Documents page.'}
                </span>
              </div>
            )}

            {chunks?.map((chunk) => (
              <div key={chunk.id} className="chunk-card">
                <div className="chunk-meta">
                  <span className="chunk-index">Passage {chunk.position + 1}</span>
                  <span>
                    {[`Page ${chunk.page}`, chunk.section].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <p className="chunk-text">{chunk.text}</p>
              </div>
            ))}
          </div>
        </div>

        <style>{`
          .modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.45);
            backdrop-filter: blur(6px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            padding: 20px;
          }

          .doc-preview-modal {
            width: 100%;
            max-width: 780px;
            max-height: 85vh;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-rim), var(--shadow-lg);
            display: flex;
            flex-direction: column;
            overflow: hidden;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-light);
            background: var(--bg-card);
          }

          .doc-modal-title-group {
            display: flex;
            align-items: center;
            gap: 14px;
          }

          .pdf-badge-circle {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            background: var(--danger-bg);
            color: var(--danger);
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .modal-doc-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .modal-doc-meta {
            font-size: 0.775rem;
            color: var(--text-muted);
          }

          .modal-actions {
            display: flex;
            align-items: center;
            gap: 10px;
          }

          .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            padding: 6px;
            border-radius: 50%;
          }

          .close-btn:hover {
            background: var(--bg-hover);
            color: var(--text-primary);
          }

          .modal-body {
            padding: 24px;
            overflow-y: auto;
            flex: 1;
            background: var(--bg-card-subtle);
          }

          .preview-toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 16px;
          }

          .sovereign-tag {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--success);
          }

          .section-label {
            font-size: 0.775rem;
            color: var(--text-muted);
            font-weight: 600;
          }

          .document-page-sheet {
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: var(--radius-md);
            padding: 24px;
            box-shadow: var(--shadow-sm);
            margin-bottom: 20px;
          }

          .sheet-header-line {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            font-size: 0.725rem;
            color: var(--text-muted);
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-light);
            margin-bottom: 18px;
          }

          .highlighted-text-box {
            padding: 16px;
            background: var(--accent-light);
            border-left: 4px solid var(--accent-primary);
            border-radius: 0 8px 8px 0;
            font-size: 0.9rem;
            color: var(--text-primary);
            line-height: 1.6;
            white-space: pre-wrap;
          }

          .chunk-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
          }

          .chunk-card {
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: var(--radius-md);
            padding: 16px 18px;
          }

          .chunk-meta {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            font-size: 0.7rem;
            color: var(--text-muted);
            margin-bottom: 8px;
          }

          .chunk-index {
            font-weight: 700;
            color: var(--text-secondary);
          }

          .chunk-text {
            font-size: 0.85rem;
            line-height: 1.6;
            color: var(--text-secondary);
            white-space: pre-wrap;
          }

          .preview-state {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 20px;
            border: 1px dashed var(--border-light);
            border-radius: var(--radius-md);
            font-size: 0.825rem;
            color: var(--text-secondary);
          }

          .preview-state.muted {
            color: var(--text-muted);
          }

          .preview-state.revoked {
            border-style: solid;
            border-color: var(--warning);
            background: var(--warning-bg);
            color: var(--warning);
          }

          .download-btn {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: var(--accent-light);
            color: var(--accent-text);
            border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
            border-radius: var(--radius-md);
            font-size: 0.825rem;
            font-weight: 600;
            cursor: pointer;
          }

          .download-btn:hover {
            background: var(--accent-primary);
            color: var(--accent-contrast);
          }

          .spin {
            animation: preview-spin 1s linear infinite;
          }

          @keyframes preview-spin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    </div>
  );
};
