import React, { useState } from 'react';
import {
  X,
  Lock,
  FolderInput,
  Pencil,
  UserCog,
  AlertTriangle,
  MessageSquare,
} from 'lucide-react';
import { useApp } from '../../state/AppContext';

/**
 * Edit one document's metadata.
 *
 * Three of these four fields are access-control changes rather than
 * cosmetic ones: `folder`, `confidential` and `owner` between them decide
 * who can retrieve this document's contents through the assistant. The form
 * says so, because a folder dropdown that looks like filing but behaves like
 * a permission grant is how people share things they did not mean to.
 *
 * The controls a user is not entitled to use are shown disabled with the
 * reason, rather than hidden. Hiding them makes the product look arbitrary;
 * showing them explains where the boundary is. The server authorises every
 * field regardless of what this form renders.
 */
export const DocumentSettingsModal = ({ docData, onClose }) => {
  const { folders, updateDocument, currentUser, users } = useApp();

  const [name, setName] = useState(docData?.name ?? '');
  const [folder, setFolder] = useState(docData?.folder ?? '');
  const [confidential, setConfidential] = useState(
    docData?.isConfidentialOwnerOnly ?? false,
  );
  const [ownerId, setOwnerId] = useState(docData?.ownerId ?? '');
  const [newFolder, setNewFolder] = useState('');
  // Chat files are searchable in one conversation only. Keeping one moves
  // it into the user's own knowledge base - which is a change of scope, so
  // it is an explicit choice rather than a side effect of any other edit.
  const [keepFromChat, setKeepFromChat] = useState(false);
  const [saving, setSaving] = useState(false);

  if (!docData) return null;

  const isAdmin = currentUser?.accessLevel === 'OWNER';
  const choices = folders?.assignable ?? [];
  const chosenFolder = folder === '__new__' ? newFolder.trim() : folder;

  const isChatFile = Boolean(docData.conversationId);
  const ownsIt = docData.ownerId === currentUser?.id;

  const changed =
    name.trim() !== docData.name ||
    chosenFolder !== docData.folder ||
    confidential !== docData.isConfidentialOwnerOnly ||
    ownerId !== docData.ownerId ||
    keepFromChat;

  // Only send what actually changed, so an unchanged field the user is not
  // allowed to set never triggers a refusal.
  const handleSave = async () => {
    const patch = {};
    if (name.trim() !== docData.name) patch.name = name.trim();
    if (chosenFolder && chosenFolder !== docData.folder) patch.folder = chosenFolder;
    if (confidential !== docData.isConfidentialOwnerOnly) {
      patch.isConfidentialOwnerOnly = confidential;
    }
    if (ownerId && ownerId !== docData.ownerId) patch.ownerId = ownerId;
    if (keepFromChat) patch.promoteFromChat = true;

    setSaving(true);
    const result = await updateDocument(docData.id, patch);
    setSaving(false);
    if (result) onClose();
  };

  const sharingOut =
    chosenFolder && chosenFolder !== 'Personal Uploads' && !confidential;

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card doc-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 className="modal-doc-title">Document settings</h3>
            <span className="modal-doc-meta">{docData.name}</span>
          </div>
          <button className="close-btn" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          {/* Name -------------------------------------------------- */}
          <label className="field">
            <span className="field-label">
              <Pencil size={13} /> Display name
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Document name"
            />
            <span className="field-hint">
              Renaming changes only how the document is listed. The stored file
              is untouched.
            </span>
          </label>

          {/* Chat scope -------------------------------------------- */}
          {isChatFile && (
            <div className={`field toggle-field ${ownsIt ? '' : 'disabled'}`}>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={keepFromChat}
                  disabled={!ownsIt}
                  onChange={(e) => setKeepFromChat(e.target.checked)}
                />
                <span className="field-label">
                  <MessageSquare size={13} /> Keep in my knowledge base
                </span>
              </label>
              <span className="field-hint">
                This file was attached to a chat, so it is searchable in that
                conversation only. Keeping it moves it into your own files,
                where your assistant can use it in any chat. It stays private
                to you until you share it into a folder.
              </span>
            </div>
          )}

          {/* Folder ------------------------------------------------ */}
          <label className="field">
            <span className="field-label">
              <FolderInput size={13} /> Folder
            </span>
            <select value={folder} onChange={(e) => setFolder(e.target.value)}>
              {!choices.includes(docData.folder) && (
                <option value={docData.folder}>{docData.folder} (current)</option>
              )}
              {choices.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
              {folders?.unrestricted && <option value="__new__">New folder…</option>}
            </select>

            {folder === '__new__' && (
              <input
                type="text"
                className="new-folder-input"
                value={newFolder}
                onChange={(e) => setNewFolder(e.target.value)}
                placeholder="New folder name"
              />
            )}

            <span className="field-hint">
              The folder decides who can search this document.{' '}
              <strong>Personal Uploads</strong> is private to you; any other
              folder shares it with everyone assigned to that folder.
            </span>
          </label>

          {sharingOut && chosenFolder !== docData.folder && (
            <div className="access-warning">
              <AlertTriangle size={14} />
              <span>
                Everyone assigned to <strong>{chosenFolder}</strong> will be able
                to retrieve this document's contents in chat, with citations.
              </span>
            </div>
          )}

          {/* Confidential ------------------------------------------ */}
          <div className={`field toggle-field ${isAdmin ? '' : 'disabled'}`}>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={confidential}
                disabled={!isAdmin}
                onChange={(e) => setConfidential(e.target.checked)}
              />
              <span className="field-label">
                <Lock size={13} /> Owner confidential
              </span>
            </label>
            <span className="field-hint">
              {isAdmin
                ? 'Hides the document from every other user, including from their search results, whatever folder it is in.'
                : 'Only owner clearance can classify a document. This is a classification, not a personal privacy setting.'}
            </span>
          </div>

          {/* Owner ------------------------------------------------- */}
          <div className={`field ${isAdmin ? '' : 'disabled'}`}>
            <span className="field-label">
              <UserCog size={13} /> Owner
            </span>
            <select
              value={ownerId ?? ''}
              disabled={!isAdmin}
              onChange={(e) => setOwnerId(e.target.value)}
            >
              {(users ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} — {u.role}
                </option>
              ))}
            </select>
            <span className="field-hint">
              {isAdmin
                ? 'Transfers who may edit and delete this document.'
                : 'Only owner clearance can transfer a document.'}
            </span>
          </div>
        </div>

        <div className="modal-footer">
          <button className="secondary-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary-btn"
            onClick={handleSave}
            disabled={!changed || saving || (folder === '__new__' && !newFolder.trim())}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
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

          .doc-settings-modal {
            width: 100%;
            max-width: 520px;
            max-height: 88vh;
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
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            padding: 18px 22px;
            border-bottom: 1px solid var(--border-light);
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
            padding: 20px 22px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 18px;
          }

          .field {
            display: flex;
            flex-direction: column;
            gap: 6px;
          }

          .field.disabled {
            opacity: 0.6;
          }

          .field-label {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-primary);
          }

          .field input[type='text'],
          .field select {
            padding: 9px 11px;
            border: 1px solid var(--border-light);
            border-radius: var(--radius-sm);
            background: var(--bg-card-subtle);
            color: var(--text-primary);
            font-size: 0.85rem;
            font-family: inherit;
          }

          .field input[type='text']:focus,
          .field select:focus {
            outline: none;
            border-color: var(--accent-primary);
          }

          .new-folder-input {
            margin-top: 6px;
          }

          .field-hint {
            font-size: 0.725rem;
            line-height: 1.5;
            color: var(--text-muted);
          }

          .toggle-row {
            display: flex;
            align-items: center;
            gap: 9px;
            cursor: pointer;
          }

          .toggle-field.disabled .toggle-row {
            cursor: not-allowed;
          }

          .access-warning {
            display: flex;
            align-items: flex-start;
            gap: 9px;
            padding: 11px 13px;
            border: 1px solid var(--warning);
            border-radius: var(--radius-sm);
            background: var(--warning-bg);
            color: var(--warning);
            font-size: 0.75rem;
            line-height: 1.5;
          }

          .modal-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            padding: 16px 22px;
            border-top: 1px solid var(--border-light);
          }

          .secondary-btn {
            padding: 9px 16px;
            border: 1px solid var(--border-light);
            border-radius: var(--radius-sm);
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.825rem;
            font-weight: 600;
            cursor: pointer;
          }

          .secondary-btn:hover {
            color: var(--text-primary);
            background: var(--bg-hover);
          }

          .primary-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }
        `}</style>
      </div>
    </div>
  );
};

export default DocumentSettingsModal;
