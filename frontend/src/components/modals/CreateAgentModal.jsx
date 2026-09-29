import React, { useState } from 'react';
import { useApp } from '../../state/AppContext';
import { X, Bot, Plus, Check } from 'lucide-react';

export const CreateAgentModal = ({ onClose }) => {
  const { createAgentSubmit, health, tools, folders, modelCatalogue } = useApp();
  const inference = health?.inference;

  // What this deployment is actually configured to serve, from /api/models.
  // Not the provider's whole catalogue: those are models nobody has set up,
  // and the server rejects a pin naming one.
  const selectableModels = modelCatalogue?.selectable ?? [];

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [specialisations, setSpecialisations] = useState('');
  const [selectedTools, setSelectedTools] = useState(['Document Search', 'Knowledge Retrieval']);
  const [retrievalEnabled, setRetrievalEnabled] = useState(true);
  const [scope, setScope] = useState([]);
  // "" means follow the workbench's role table, which is the right default:
  // an agent pinned at creation time keeps its model when .env changes, and
  // most agents should move with the deployment instead.
  const [model, setModel] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Read from the registry rather than a hardcoded list. The old array named
  // six tools regardless of what the server had, which meant it offered
  // Image Analyzer as though selecting it would do something.
  const availableToolsList = tools ?? [];

  const toggleToolSelect = (tool) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    );
  };

  const toggleScope = (folder) => {
    setScope((prev) =>
      prev.includes(folder) ? prev.filter((f) => f !== folder) : [...prev, folder],
    );
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || submitting) return;

    setSubmitting(true);
    await createAgentSubmit({
      name,
      description,
      instructions,
      tools: selectedTools,
      specialisations: specialisations
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      retrievalEnabled,
      folderScope: scope,
      model,
    });
    setSubmitting(false);
  };

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card create-agent-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="title-group">
            <div className="agent-icon-box">
              <Bot size={20} />
            </div>
            <div>
              <h3 className="modal-title">Create Autonomous Agent</h3>
              <p className="modal-sub">Build a new specialist that searches a chosen part of the BIS knowledge base.</p>
            </div>
          </div>
          <button className="close-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body">
          <div className="form-group">
            <label className="form-label">Agent Name *</label>
            <input 
              type="text" 
              className="form-input" 
              placeholder="e.g. Heat Exchanger Diagnostic Assistant"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">Short Description</label>
            <input 
              type="text" 
              className="form-input" 
              placeholder="Analyze shell-and-tube thermal efficiency and fouling."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {/*
            A real control now that routing exists. The empty option is the
            default and the recommended one: it leaves the agent following
            the workbench's role table, so changing .env moves every agent
            at once. A pin is for the exception - an agent that must keep a
            particular model whatever the deployment does.
          */}
          <div className="form-group">
            <label className="form-label">Model</label>
            <select
              className="form-input"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={!inference?.configured}
            >
              <option value="">
                {inference?.configured
                  ? `Follow the server default (${inference.model})`
                  : 'No model configured'}
              </option>
              {selectableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} - {m.provider}
                </option>
              ))}
            </select>
            <div className="agent-model-note">
              {inference?.configured
                ? model
                  ? 'Pinned. This agent keeps this model even if the server default changes.'
                  : "Recommended. The agent uses whichever model the server routes its turns to."
                : 'Connect a provider before this agent can answer.'}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Instructions</label>
            <textarea 
              className="form-textarea"
              placeholder="You help MSMEs with CRS registration. Always cite the scheme document and list the documents they must prepare..."
              rows={3}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
          </div>

          {/* Focus areas ------------------------------------------- */}
          <div className="form-group">
            <label className="form-label">Focus Areas</label>
            <input
              type="text"
              className="form-input"
              placeholder="Fouling analysis, Thermal efficiency"
              value={specialisations}
              onChange={(e) => setSpecialisations(e.target.value)}
            />
            <p className="form-hint">
              Comma separated. These describe what the agent is <em>for</em>.
              They are shown separately from what it can actually do, which
              the server derives from its configuration.
            </p>
          </div>

          {/* Retrieval --------------------------------------------- */}
          <div className="form-group">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={retrievalEnabled}
                onChange={(e) => setRetrievalEnabled(e.target.checked)}
              />
              <span className="form-label no-margin">Search the knowledge base</span>
            </label>
            <p className="form-hint">
              When off, this agent answers from general knowledge only and
              never cites a document.
            </p>
          </div>

          {retrievalEnabled && (
            <div className="form-group">
              <label className="form-label">Folder Scope</label>
              <div className="tools-selection-grid">
                {(folders?.all ?? []).map((folder) => {
                  const isSelected = scope.includes(folder);
                  return (
                    <button
                      type="button"
                      key={folder}
                      className={`tool-select-chip ${isSelected ? 'selected' : ''}`}
                      onClick={() => toggleScope(folder)}
                    >
                      {isSelected && <Check size={14} />}
                      <span>{folder}</span>
                    </button>
                  );
                })}
              </div>
              <p className="form-hint">
                {scope.length === 0
                  ? 'Nothing selected: searches everything each user is cleared for.'
                  : `Searches only ${scope.join(', ')}.`}{' '}
                Scope <strong>narrows</strong> a search - it combines with each
                user's own access, so it never grants a folder they could not
                already open.
              </p>
            </div>
          )}

          {/* Tools -------------------------------------------------- */}
          <div className="form-group">
            <label className="form-label">Equipped Tools</label>
            <div className="tools-selection-grid">
              {availableToolsList.map((tool) => {
                const isSelected = selectedTools.includes(tool.name);
                return (
                  <button
                    type="button"
                    key={tool.id}
                    className={`tool-select-chip ${isSelected ? 'selected' : ''} ${
                      tool.executable ? '' : 'unavailable'
                    }`}
                    onClick={() => toggleToolSelect(tool.name)}
                    title={
                      tool.executable ? tool.description : tool.unavailableReason
                    }
                  >
                    {isSelected && <Check size={14} />}
                    <span>{tool.name}</span>
                  </button>
                );
              })}
            </div>
            <p className="form-hint">
              Greyed tools can be granted, but cannot run yet - the agent card
              will say so rather than implying otherwise.
            </p>
          </div>

          <div className="modal-footer">
            <button type="button" className="cancel-btn" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="submit-btn"
              disabled={!name.trim() || submitting}
            >
              <Plus size={16} />
              <span>{submitting ? 'Creating...' : 'Create Agent'}</span>
            </button>
          </div>
        </form>

        <style>{`
          .form-hint {
            margin-top: 6px;
            font-size: 0.725rem;
            line-height: 1.5;
            color: var(--text-muted);
          }

          .checkbox-row {
            display: flex;
            align-items: center;
            gap: 9px;
            cursor: pointer;
          }

          .form-label.no-margin {
            margin: 0;
          }

          /* Grantable, but it cannot run yet - so it does not look like the
             tools that can. */
          .tool-select-chip.unavailable {
            opacity: 0.55;
            border-style: dashed;
          }

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

          /*
           * This form is taller than a laptop viewport, and the card had
           * overflow: hidden with no max-height. A flex item centred in a
           * full-height backdrop overflows equally in both directions, so
           * the header ran off the top of the screen while the footer was
           * clipped at the bottom - and because the overflow was hidden
           * rather than scrollable, neither could be reached at all.
           *
           * The card is now bounded by the viewport and scrolls internally:
           * the header and footer stay put, the fields move.
           */
          .create-agent-modal {
            width: 100%;
            max-width: 580px;
            max-height: calc(100vh - 40px);
            max-height: calc(100dvh - 40px);
            display: flex;
            flex-direction: column;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-rim), var(--shadow-lg);
            overflow: hidden;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-light);
            flex-shrink: 0;
          }

          .title-group {
            display: flex;
            align-items: center;
            gap: 12px;
          }

          .agent-icon-box {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: var(--accent-light);
            color: var(--accent-primary);
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .modal-title {
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .modal-sub {
            font-size: 0.775rem;
            color: var(--text-muted);
          }

          .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
          }

          .modal-body {
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            /* min-height: 0 is what actually lets a flex child shrink below
               its content height and scroll. Without it the body keeps its
               natural size and pushes the card past the viewport again. */
            flex: 1;
            min-height: 0;
            overflow-y: auto;
          }

          .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
          }

          .form-label {
            font-size: 0.825rem;
            font-weight: 600;
            color: var(--text-primary);
          }

          .form-input, .form-select, .form-textarea {
            padding: 10px 14px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-light);
            border-radius: var(--radius-md);
            font-size: 0.875rem;
            color: var(--text-primary);
            outline: none;
            transition: border-color 0.15s ease;
          }

          .form-input:focus, .form-select:focus, .form-textarea:focus {
            border-color: var(--accent-primary);
          }

          .tools-selection-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }

          .tool-select-chip {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-light);
            border-radius: 999px;
            font-size: 0.775rem;
            color: var(--text-secondary);
            cursor: pointer;
          }

          .tool-select-chip.selected {
            background: var(--accent-light);
            color: var(--accent-text);
            border-color: var(--accent-primary);
            font-weight: 600;
          }

          /* Sticky rather than merely last: the submit button has to stay
             reachable without scrolling to the bottom of a long form. It
             lives inside the <form>, so it cannot be lifted out of the
             scroll container without losing the submit. */
          .modal-footer {
            position: sticky;
            bottom: 0;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 12px;
            margin-top: 12px;
            padding: 16px 0 0;
            border-top: 1px solid var(--border-light);
            background: var(--bg-card);
          }

          .cancel-btn {
            padding: 8px 16px;
            background: transparent;
            border: 1px solid var(--border-light);
            border-radius: var(--radius-md);
            font-size: 0.85rem;
            color: var(--text-secondary);
            cursor: pointer;
          }

          .submit-btn {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 18px;
            background: var(--accent-primary);
            color: var(--accent-contrast);
            border: none;
            border-radius: var(--radius-md);
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
          }

          .submit-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }
        `}</style>
      </div>
    </div>
  );
};
