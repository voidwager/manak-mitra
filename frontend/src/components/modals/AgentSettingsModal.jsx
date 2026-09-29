import React, { useState } from 'react';
import { X, FolderSearch, Sparkles, Wrench, Power, Cpu } from 'lucide-react';
import { useApp } from '../../state/AppContext';

/**
 * Configure an existing agent.
 *
 * The retrieval half is the substance: before Phase 10 every agent searched
 * the same corpus in the same way, so the only thing separating one from
 * another was the wording of its prompt. Folder scope and the retrieval
 * toggle are what make an agent actually specialised.
 *
 * Scope narrows and never widens. Restricting an agent to a folder does not
 * grant anyone access to it - the server intersects the scope with each
 * caller's own permissions at query time - so this form is safe to expose
 * without it becoming a privilege-escalation surface. The hint says so,
 * because a folder picker that looks like a permission grant invites people
 * to treat it as one.
 */
export const AgentSettingsModal = ({ agent, onClose }) => {
  const { folders, tools, updateAgentConfig, modelCatalogue } = useApp();

  const [name, setName] = useState(agent?.name ?? '');
  const [description, setDescription] = useState(agent?.description ?? '');
  const [instructions, setInstructions] = useState(agent?.instructions ?? '');
  const [specialisations, setSpecialisations] = useState(
    (agent?.specialisations ?? []).join(', '),
  );
  const [retrievalEnabled, setRetrievalEnabled] = useState(
    agent?.retrievalEnabled ?? true,
  );
  const [scope, setScope] = useState(agent?.folderScope ?? []);
  const [topK, setTopK] = useState(agent?.retrievalTopK ?? '');
  const [selectedTools, setSelectedTools] = useState(agent?.tools ?? []);
  const [modelRole, setModelRole] = useState(agent?.modelRole ?? 'chat');
  // The stored pin, not the resolved model. Seeding this from `agent.model`
  // would show whatever the router happened to pick and then save it as a
  // hard pin the moment anything else on the form changed.
  const [modelPin, setModelPin] = useState(agent?.modelPin ?? '');
  const [retired, setRetired] = useState(agent?.status === 'Retired');
  const [saving, setSaving] = useState(false);

  if (!agent) return null;

  const toggle = (list, value) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  const handleSave = async () => {
    setSaving(true);
    const result = await updateAgentConfig(agent.id, {
      name: name.trim(),
      description,
      instructions,
      specialisations: specialisations
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      tools: selectedTools,
      retrievalEnabled,
      folderScope: scope,
      retrievalTopK: topK === '' ? null : Number(topK),
      modelRole,
      model: modelPin,
      status: retired ? 'Offline' : 'Online',
    });
    setSaving(false);
    if (result) onClose();
  };

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card agent-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 className="modal-title">Configure agent</h3>
            <span className="modal-sub">{agent.name}</span>
          </div>
          <button className="close-btn" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <label className="field">
            <span className="field-label">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>

          <label className="field">
            <span className="field-label">Description</span>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="field">
            <span className="field-label">
              <Sparkles size={13} /> Instructions
            </span>
            <textarea
              rows={4}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="How this agent should behave."
            />
            <span className="field-hint">
              Prepended to every prompt. The safety guardrail is always
              appended after it, so instructions cannot override it.
            </span>
          </label>

          <label className="field">
            <span className="field-label">Focus areas</span>
            <input
              value={specialisations}
              onChange={(e) => setSpecialisations(e.target.value)}
              placeholder="Failure Diagnosis, LOTO Guidance"
            />
            <span className="field-hint">
              Comma separated. These describe what the agent is <em>for</em>;
              they are not checked, and are shown separately from what it can
              actually do.
            </span>
          </label>

          {/* Model routing ------------------------------------------- */}
          <label className="field">
            <span className="field-label">
              <Cpu size={13} /> Model
            </span>
            <select value={modelRole} onChange={(e) => setModelRole(e.target.value)}>
              <option value="chat">Default</option>
              <option value="reasoning">Reasoning - longer analysis</option>
              <option value="fast">Fast - short turns</option>
            </select>
            <span className="field-hint">
              {agent.modelRoleReason || 'Which routed model serves this agent.'}{' '}
              A turn with an image always goes to the vision model regardless,
              since no preference makes a text-only model able to see one.
            </span>
          </label>

          {/* An explicit pin, which outranks the role above. Separate from
              the role on purpose: a role is intent that survives a change of
              provider, a pin is a specific model that does not. */}
          <label className="field">
            <span className="field-label">
              <Cpu size={13} /> Pinned model
            </span>
            <select value={modelPin} onChange={(e) => setModelPin(e.target.value)}>
              <option value="">Follow the server default (recommended)</option>
              {(modelCatalogue?.selectable ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} - {m.provider}
                </option>
              ))}
            </select>
            <span className="field-hint">
              {modelPin
                ? 'Pinned. This agent keeps this model even when the server routes elsewhere.'
                : 'Unpinned. The agent follows the role above, so changing .env moves it with everything else.'}
            </span>
          </label>

          {/* Retrieval ---------------------------------------------- */}
          <div className="field">
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={retrievalEnabled}
                onChange={(e) => setRetrievalEnabled(e.target.checked)}
              />
              <span className="field-label">
                <FolderSearch size={13} /> Search the knowledge base
              </span>
            </label>
            <span className="field-hint">
              When off, this agent answers from general knowledge only and
              never cites a document.
            </span>
          </div>

          {retrievalEnabled && (
            <>
              <div className="field">
                <span className="field-label">Folder scope</span>
                <div className="chip-grid">
                  {(folders?.all ?? []).map((folder) => (
                    <button
                      key={folder}
                      type="button"
                      className={`chip ${scope.includes(folder) ? 'on' : ''}`}
                      onClick={() => setScope(toggle(scope, folder))}
                    >
                      {folder}
                    </button>
                  ))}
                </div>
                <span className="field-hint">
                  {scope.length === 0
                    ? 'Nothing selected: searches everything each user is cleared for.'
                    : `Searches only ${scope.join(', ')}.`}{' '}
                  Scope <strong>narrows</strong> a search — it is combined with
                  each user's own access, so it never grants anyone a folder
                  they could not already open.
                </span>
              </div>

              <label className="field">
                <span className="field-label">Passages per answer</span>
                <input
                  type="number"
                  min={1}
                  max={25}
                  value={topK}
                  onChange={(e) => setTopK(e.target.value)}
                  placeholder="Server default"
                />
              </label>
            </>
          )}

          {/* Tools -------------------------------------------------- */}
          <div className="field">
            <span className="field-label">
              <Wrench size={13} /> Tools
            </span>
            <div className="chip-grid">
              {(tools ?? []).map((tool) => (
                <button
                  key={tool.id}
                  type="button"
                  className={`chip ${selectedTools.includes(tool.name) ? 'on' : ''}`}
                  onClick={() => setSelectedTools(toggle(selectedTools, tool.name))}
                  title={tool.description}
                >
                  {tool.name}
                </button>
              ))}
            </div>
            <span className="field-hint">
              Retrieval tools work today. The rest are recorded but cannot run
              until the tool executor lands, and the agent card says so
              rather than implying otherwise.
            </span>
          </div>

          {!agent.isSystem && (
            <div className="field">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={retired}
                  onChange={(e) => setRetired(e.target.checked)}
                />
                <span className="field-label">
                  <Power size={13} /> Retire this agent
                </span>
              </label>
              <span className="field-hint">
                Keeps it and its history, but marks it unavailable for new
                conversations.
              </span>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="secondary-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" onClick={handleSave} disabled={saving || !name.trim()}>
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

          .agent-settings-modal {
            width: 100%;
            max-width: 560px;
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
            padding: 18px 22px;
            border-bottom: 1px solid var(--border-light);
          }

          .modal-title {
            font-size: 1.05rem;
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

          .field-label {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-primary);
          }

          .field input,
          .field textarea {
            padding: 9px 11px;
            border: 1px solid var(--border-light);
            border-radius: var(--radius-sm);
            background: var(--bg-card-subtle);
            color: var(--text-primary);
            font-size: 0.85rem;
            font-family: inherit;
            resize: vertical;
          }

          .field input:focus,
          .field textarea:focus {
            outline: none;
            border-color: var(--accent-primary);
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

          .chip-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 7px;
          }

          .chip {
            padding: 5px 11px;
            border: 1px solid var(--border-light);
            border-radius: 999px;
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
          }

          .chip:hover {
            border-color: var(--accent-primary);
          }

          .chip.on {
            background: var(--accent-light);
            color: var(--accent-text);
            border-color: var(--accent-primary);
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

export default AgentSettingsModal;
