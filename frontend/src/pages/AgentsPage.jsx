import React from 'react';
import { useApp } from '../state/AppContext';
import {
  Bot,
  Wrench,
  FileText,
  Eye,
  Plus,
  ArrowRight,
  ShieldCheck,
  Cloud,
  Check,
  Minus,
  FolderSearch,
  Settings2,
  Trash2,
} from 'lucide-react';

/**
 * Status pill colour follows the derived state, not a stored string.
 * `Limited` is its own colour because it is a real and common state - an
 * agent whose model works but whose vision tool does not is neither ready
 * nor broken, and painting it green was the old lie.
 */
const STATUS_TONE = {
  Ready: 'ready',
  Limited: 'limited',
  Unavailable: 'unavailable',
  Retired: 'retired',
};

export const AgentsPage = () => {
  const {
    agents,
    activeAgent,
    selectAgent,
    setActiveTab,
    setActiveModal,
    deleteAgent,
    updateAgentConfig,
    currentUser,
    isGuest,
    health,
  } = useApp();

  // Where inference runs is a property of the deployment, read from
  // /api/health. It used to be a hardcoded "On-Premise" badge on every
  // card, which was simply false whenever an external provider was active.
  const onPremise = health?.inference?.onPremise ?? false;

  const canEdit = (agent) =>
    currentUser?.accessLevel === 'OWNER' ||
    (!agent.isSystem && agent.createdById === currentUser?.id);

  const confirmDelete = (agent) => {
    if (window.confirm(`Delete the agent "${agent.name}"? This cannot be undone.`)) {
      deleteAgent(agent.id);
    }
  };

  const getAgentIcon = (iconName) => {
    switch (iconName) {
      case 'Wrench': return Wrench;
      case 'FileText': return FileText;
      case 'Eye': return Eye;
      default: return Bot;
    }
  };

  /*
   * Turning a specialist off stores status "Offline"; the API reports that
   * back as the derived status "Retired". It is a real switch rather than a
   * cosmetic one: `selectable_specialists` on the server only considers
   * agents whose stored status is "Online", so an agent switched off here
   * stops being a destination SI-1 can dispatch to.
   *
   * SI-1 itself has no switch. It is the default assistant and the router
   * for every other agent, so turning it off would leave a workbench with
   * nothing to answer a question.
   */
  const toggleAgent = (agent) => {
    const enabled = agent.status !== 'Retired';
    updateAgentConfig(agent.id, { status: enabled ? 'Offline' : 'Online' });
  };

  const handleOpenAgent = (agentId) => {
    selectAgent(agentId);
    setActiveTab('chat');
  };

  return (
    <div className="page-container animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Specialists</h1>
          <p className="page-subtitle">Each one searches its own part of the published BIS material and cites what it finds.</p>
        </div>
        {/* Visitors cannot create agents - the API refuses them, because a
            new agent is listed for every user. */}
        {!isGuest && (
          <button
            className="primary-btn"
            onClick={() => setActiveModal({ type: 'createAgent' })}
          >
            <Plus size={16} />
            <span>Create Agent</span>
          </button>
        )}
      </div>

      {/* Agents Grid */}
      <div className="agents-grid">
        {agents.map((agent) => {
          const IconComp = getAgentIcon(agent.icon);
          const isActive = activeAgent?.id === agent.id;

          return (
            <div key={agent.id} className={`agent-card subtle-card ${isActive ? 'active-card' : ''}`}>
              <div className="card-top-row">
                <div className="agent-card-icon-box">
                  <IconComp size={22} />
                </div>
                <div className="agent-card-badges">
                  {canEdit(agent) && !agent.isUniversal && (
                    <button
                      role="switch"
                      aria-checked={agent.status !== 'Retired'}
                      aria-label={`${agent.status !== 'Retired' ? 'Disable' : 'Enable'} ${agent.name}`}
                      className={`agent-switch ${agent.status !== 'Retired' ? 'on' : 'off'}`}
                      onClick={() => toggleAgent(agent)}
                      title={
                        agent.status !== 'Retired'
                          ? 'On. SI-1 can engage this specialist.'
                          : 'Off. SI-1 will not engage this specialist.'
                      }
                    >
                      <span className="agent-switch-knob" />
                    </button>
                  )}
                  <span
                    className={`status-pill ${STATUS_TONE[agent.status] ?? 'unavailable'}`}
                    title={agent.statusDetail}
                  >
                    <span className="status-dot" />
                    {agent.status}
                  </span>
                  {isActive && <span className="badge-active">Active Agent</span>}
                </div>
              </div>

              <h3 className="agent-card-name">{agent.name}</h3>

              {/*
                * An agent is not one model. SI-1 fronts the whole routed
                * table - it answers on the chat model, picks specialists on
                * the fast one, and any image is forced to the vision model
                * whichever specialist it engaged. Naming only the first
                * described the least interesting part of that, and on the
                * Document Vision card it named a model that never handles
                * an image.
                *
                * A route that is configured but unreachable is shown struck
                * through with the reason, exactly like a capability. The
                * alternative - hiding it - is how a card ends up implying
                * the microphone works.
                */}
              <div className="agent-card-models">
                {(agent.modelRoutes ?? []).map((route) => (
                  <div
                    key={route.role}
                    className={`model-line ${route.available ? '' : 'off'}`}
                    title={route.detail || route.purpose}
                  >
                    {agent.modelRoutes.length > 1 && (
                      <span className="model-role">{route.role}</span>
                    )}
                    <span className="model-id">{route.model}</span>
                    <span className="model-vendor">{route.provider}</span>
                  </div>
                ))}
              </div>
              <p className="agent-card-desc">{agent.description}</p>

              {/*
                * What the agent can actually do, derived by the server from
                * the live runtime. Unavailable entries are shown struck
                * through with the reason rather than hidden, because "vision
                * arrives in a later phase" is useful information and a
                * silently shorter list is not.
                */}
              <div className="capabilities-group">
                <div className="caps-label">Capabilities</div>
                <div className="caps-list">
                  {agent.capabilities?.map((cap, i) => (
                    <div
                      key={i}
                      className={`cap-row ${cap.available ? 'on' : 'off'}`}
                      title={cap.detail}
                    >
                      {cap.available ? <Check size={12} /> : <Minus size={12} />}
                      <span>{cap.label}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Author's stated focus. Intent, not capability - and labelled
                  so it cannot be mistaken for one. */}
              {agent.specialisations?.length > 0 && (
                <div className="capabilities-group">
                  <div className="caps-label">Focus areas (author's intent)</div>
                  <div className="caps-tags">
                    {agent.specialisations.map((spec, i) => (
                      <span key={i} className="cap-tag">{spec}</span>
                    ))}
                  </div>
                </div>
              )}

              <div className="scope-line" title="Folders this agent searches, intersected with your own access">
                <FolderSearch size={13} />
                <span>
                  {!agent.retrievalEnabled
                    ? 'Does not search the knowledge base'
                    : agent.folderScope?.length
                      ? `Searches ${agent.folderScope.join(', ')}`
                      : 'Searches everything you are cleared for'}
                </span>
              </div>

              {/* Card Footer */}
              <div className="agent-card-footer">
                <div className={`sovereign-badge ${onPremise ? '' : 'external'}`}>
                  {onPremise ? <ShieldCheck size={14} /> : <Cloud size={14} />}
                  <span>{onPremise ? 'On-Premise' : 'External model'}</span>
                </div>

                <div className="agent-card-actions">
                  {canEdit(agent) && (
                    <button
                      className="agent-icon-btn"
                      onClick={() => setActiveModal({ type: 'editAgent', data: agent })}
                      title="Configure this agent"
                      aria-label="Configure agent"
                    >
                      <Settings2 size={14} />
                    </button>
                  )}
                  {canEdit(agent) && !agent.isSystem && (
                    <button
                      className="agent-icon-btn danger"
                      onClick={() => confirmDelete(agent)}
                      title="Delete this agent"
                      aria-label="Delete agent"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                  <button
                    className={`open-agent-btn ${isActive ? 'btn-active' : ''}`}
                    onClick={() => handleOpenAgent(agent.id)}
                  >
                    <span>{isActive ? 'Current Workspace' : 'Open Workspace'}</span>
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
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
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          flex-wrap: wrap;
          margin-bottom: 28px;
        }

        @media (max-width: 768px) {
          .page-container { padding: 18px 16px 28px; }
          .agents-grid { gap: 14px; }
          .agent-card { padding: 18px; }
          .page-title { font-size: 1.25rem; }
          /* The action row wraps rather than squeezing the button to an
             unreadable width. */
          .agent-card-footer { gap: 10px; }
          .agent-card-actions { flex-wrap: wrap; }
        }

        .page-title {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text-primary);
          letter-spacing: -0.02em;
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

        .primary-btn:hover {
          background-color: var(--accent-primary-hover);
          box-shadow: var(--shadow-md);
        }

        .agents-grid {
          display: grid;
          /* min() rather than a bare 320px: on a 360px phone the column
             minimum exceeded the available width, so the grid overflowed
             its own container and the page scrolled sideways. */
          grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
          gap: 20px;
        }

        .agent-card {
          padding: 24px;
          display: flex;
          flex-direction: column;
          border-radius: var(--radius-lg);
          background: var(--bg-card);
          position: relative;
        }

        .agent-card.active-card {
          border-color: var(--accent-primary);
          box-shadow: var(--shadow-md);
        }

        .card-top-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 16px;
        }

        .agent-card-badges {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
          justify-content: flex-end;
        }

        .agent-card-icon-box {
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .agent-card-badges {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .status-pill {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.75rem;
          color: var(--text-muted);
          background: var(--bg-card-subtle);
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid var(--border-light);
        }

        /* Colour follows the derived state. Green used to be unconditional,
           which made the pill decorative. */
        .status-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background-color: currentColor;
        }

        .status-pill.ready { color: var(--success); }
        .status-pill.limited { color: var(--warning); }
        .status-pill.unavailable { color: var(--danger); }
        .status-pill.retired { color: var(--text-muted); }

        .cap-row {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          font-size: 0.775rem;
          line-height: 1.45;
          margin-bottom: 4px;
        }

        .cap-row.on {
          color: var(--text-secondary);
        }

        /* An unavailable capability stays visible and struck through: the
           reason it cannot run is more useful than its absence. */
        .cap-row.off {
          color: var(--text-muted);
        }

        .cap-row.off span {
          text-decoration: line-through;
          text-decoration-thickness: 1px;
        }

        .cap-row svg {
          flex-shrink: 0;
          margin-top: 3px;
        }

        .caps-list {
          display: flex;
          flex-direction: column;
        }

        .scope-line {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          font-size: 0.75rem;
          color: var(--text-muted);
          padding: 8px 0 16px;
          border-top: 1px solid var(--border-light);
        }

        .agent-card-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .agent-icon-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 7px;
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          background: transparent;
          color: var(--text-secondary);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .agent-icon-btn:hover {
          color: var(--text-primary);
          border-color: var(--accent-primary);
          background: var(--bg-hover);
        }

        .agent-icon-btn.danger:hover {
          color: var(--danger);
          border-color: var(--danger);
        }

        .sovereign-badge.external {
          color: var(--warning);
        }

        .agent-switch {
          position: relative;
          width: 34px;
          height: 19px;
          flex-shrink: 0;
          padding: 0;
          border: 1px solid var(--border-light);
          border-radius: 999px;
          background: var(--bg-card-subtle);
          cursor: pointer;
          transition: background 0.18s ease, border-color 0.18s ease;
        }

        .agent-switch.on {
          background: var(--accent-primary);
          border-color: var(--accent-primary);
        }

        /*
         * The knob was a hardcoded #FFFFFF from when the accent was purple.
         * Now that the accent is the text colour, the "on" track is white on
         * the dark theme - so the knob was white on white and the switch
         * read as empty. --accent-contrast is the colour guaranteed legible
         * against the accent whichever way the theme falls.
         */
        .agent-switch-knob {
          position: absolute;
          top: 2px;
          left: 2px;
          width: 13px;
          height: 13px;
          border-radius: 50%;
          background: var(--text-secondary);
          transition: transform 0.18s ease, background-color 0.18s ease;
        }

        .agent-switch.on .agent-switch-knob {
          background: var(--accent-contrast);
          transform: translateX(15px);
        }

        .agent-switch:focus-visible {
          outline: 2px solid var(--accent-primary);
          outline-offset: 2px;
        }

        .agent-switch:focus-visible {
          outline: 2px solid var(--accent-primary);
          outline-offset: 2px;
        }

        .badge-active {
          font-size: 0.725rem;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 999px;
          background: var(--accent-light);
          color: var(--accent-text);
        }

        .agent-card-name {
          font-size: 1.1rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .agent-card-models {
          display: flex;
          flex-direction: column;
          gap: 3px;
          margin-bottom: 10px;
        }

        .model-line {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          font-size: 0.775rem;
        }

        .model-line.off .model-id {
          color: var(--text-muted);
          text-decoration: line-through;
          text-decoration-thickness: 1px;
        }

        .model-line.off .model-vendor {
          opacity: 0.6;
        }

        .model-role {
          min-width: 78px;
          font-size: 0.68rem;
          font-weight: 600;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }

        .model-id {
          font-weight: 600;
          color: var(--accent-primary);
        }

        .model-vendor {
          font-size: 0.68rem;
          font-weight: 600;
          padding: 1px 6px;
          border-radius: 999px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          color: var(--text-muted);
          text-transform: lowercase;
        }

        .model-for {
          font-size: 0.68rem;
          color: var(--text-muted);
        }

        /*
         * No flex-grow here. Grid rows stretch every card to the height of
         * the tallest one, and a growable description absorbed all of that
         * slack - so a card with fewer capabilities pushed its own headings
         * far down the card and none of the sections lined up across the
         * row. The slack belongs above the footer instead.
         */
        .agent-card-desc {
          font-size: 0.85rem;
          color: var(--text-secondary);
          line-height: 1.5;
          margin-bottom: 20px;
        }

        .capabilities-group {
          margin-bottom: 20px;
        }

        .caps-label {
          font-size: 0.75rem;
          font-weight: 600;
          color: var(--text-muted);
          margin-bottom: 6px;
        }

        .caps-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .cap-tag {
          font-size: 0.725rem;
          padding: 3px 8px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: 6px;
          color: var(--text-secondary);
        }

        .agent-card-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          padding-top: 14px;
          border-top: 1px solid var(--border-light);
          /* Takes the leftover height, so footers align across the row. */
          margin-top: auto;
        }

        .sovereign-badge {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.725rem;
          color: var(--success);
          font-weight: 600;
        }

        .open-agent-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-primary);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .open-agent-btn:hover {
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border-color: var(--accent-primary);
        }

        .open-agent-btn.btn-active {
          background: var(--accent-light);
          color: var(--accent-text);
          border-color: color-mix(in srgb, var(--accent-primary) 20%, transparent);
        }
      `}</style>
    </div>
  );
};
