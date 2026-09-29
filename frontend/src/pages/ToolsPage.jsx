import React from 'react';
import { useApp } from '../state/AppContext';
import {
  Wrench,
  Search,
  Database,
  Eye,
  BarChart2,
  Calculator,
  FileCheck,
  Power,
  Ban,
} from 'lucide-react';

export const ToolsPage = () => {
  const { tools, toggleToolState } = useApp();

  const getToolIcon = (toolId) => {
    switch (toolId) {
      case 'doc-search': return Search;
      case 'know-retrieval': return Database;
      case 'img-analyzer': return Eye;
      case 'data-analyzer': return BarChart2;
      case 'calculator': return Calculator;
      case 'report-gen': return FileCheck;
      default: return Wrench;
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Agent Tools & Plugins</h1>
          <p className="page-subtitle">
            Functions an agent may call during a turn. Switching one off removes it
            from every agent immediately - the model is never offered a tool it
            is not permitted to use.
          </p>
        </div>
      </div>

      <div className="tools-grid">
        {tools.map(tool => {
          const IconComp = getToolIcon(tool.id);
          return (
            <div key={tool.id} className={`tool-card subtle-card ${tool.enabled ? 'enabled' : 'disabled'}`}>
              <div className="tool-card-header">
                <div className={`tool-icon-circle ${tool.enabled ? 'active' : ''}`}>
                  <IconComp size={20} />
                </div>
                
                {/* Toggle Switch */}
                <button
                  className={`toggle-switch ${tool.enabled ? 'on' : 'off'}`}
                  onClick={() => toggleToolState(tool.id)}
                  /*
                   * Gated on whether the tool was built, not on whether it
                   * can run right now. Those came to the same thing until
                   * the switch was accounted for, and a switched-off tool
                   * reporting itself unrunnable disabled its own control -
                   * off, and no way back on.
                   */
                  disabled={!tool.implemented}
                  aria-pressed={tool.enabled}
                  title={
                    tool.implemented
                      ? tool.enabled
                        ? 'Stop agents calling this tool'
                        : 'Let agents call this tool'
                      : tool.unavailableReason
                  }
                >
                  <span className="toggle-handle" />
                </button>
              </div>

              <h3 className="tool-name">{tool.name}</h3>
              <span className="tool-category-badge">{tool.category}</span>
              <p className="tool-desc">{tool.description}</p>

              {/*
                * Three states, and all three are now reachable. The test
                * has to be "was this built" rather than "can it run",
                * because a switched-off tool cannot run - so keying on that
                * sent every disabled tool down the "not available yet"
                * branch and left "switched off" dead code, telling the
                * operator their own switch was an unbuilt feature.
                */}
              <div className="tool-status-footer">
                {!tool.implemented ? (
                  <span className="status-indicator text-muted" title={tool.unavailableReason}>
                    <Ban size={12} />
                    Not available yet
                  </span>
                ) : tool.enabled ? (
                  <span className="status-indicator text-success">
                    <Power size={12} />
                    Callable by agents
                  </span>
                ) : (
                  <span className="status-indicator text-muted">
                    <Power size={12} />
                    Switched off
                  </span>
                )}
                {tool.wireName && tool.implemented && (
                  <code className="wire-name" title="The name the model sees">
                    {tool.wireName}
                  </code>
                )}
              </div>

              {!tool.implemented && tool.unavailableReason && (
                <p className="tool-unavailable-note">{tool.unavailableReason}</p>
              )}
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
          margin-bottom: 28px;
        }

        .page-title {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .page-subtitle {
          font-size: 0.875rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        .tools-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
          gap: 20px;
        }

        .tool-card {
          padding: 24px;
          display: flex;
          flex-direction: column;
          border-radius: var(--radius-lg);
          background: var(--bg-card);
        }

        .tool-card.enabled {
          border-color: var(--border-subtle);
        }

        .tool-card.disabled {
          opacity: 0.75;
          background: var(--bg-card-subtle);
        }

        .tool-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }

        .tool-icon-circle {
          width: 42px;
          height: 42px;
          border-radius: 12px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .tool-icon-circle.active {
          background: var(--accent-light);
          color: var(--accent-primary);
          border-color: color-mix(in srgb, var(--accent-primary) 20%, transparent);
        }

        .toggle-switch {
          width: 44px;
          height: 24px;
          border-radius: 999px;
          background: var(--border-subtle);
          border: none;
          padding: 2px;
          cursor: pointer;
          transition: background-color 0.2s ease;
          position: relative;
        }

        .toggle-switch.on {
          background: var(--accent-primary);
        }

        /*
         * The knob was a hardcoded #FFFFFF from when the accent was purple.
         * Now that the accent is the text colour, the "on" track is white on
         * the dark theme - so the knob was white on white and the switch
         * looked empty. It takes --accent-contrast on, which is the colour
         * guaranteed to be legible against the accent whichever way the
         * theme falls, and a muted grey off.
         */
        .toggle-handle {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: var(--text-secondary);
          display: block;
          transition: transform 0.2s ease, background-color 0.2s ease;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
        }

        .toggle-switch.on .toggle-handle {
          background: var(--accent-contrast);
          transform: translateX(20px);
        }

        .toggle-switch:not(:disabled):hover {
          background: var(--border-strong);
        }

        .toggle-switch.on:not(:disabled):hover {
          background: var(--accent-primary-hover);
        }

        .toggle-switch:focus-visible {
          outline: 2px solid var(--accent-primary);
          outline-offset: 2px;
        }

        .tool-name {
          font-size: 1.05rem;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 4px;
        }

        .tool-category-badge {
          font-size: 0.725rem;
          font-weight: 600;
          color: var(--accent-primary);
          margin-bottom: 12px;
          display: inline-block;
        }

        .tool-desc {
          font-size: 0.85rem;
          color: var(--text-secondary);
          line-height: 1.5;
          margin-bottom: 20px;
          flex: 1;
        }

        .tool-status-footer {
          padding-top: 12px;
          border-top: 1px solid var(--border-light);
        }

        .wire-name {
          margin-left: auto;
          font-size: 0.7rem;
          color: var(--text-muted);
          background: var(--bg-card-subtle);
          padding: 2px 6px;
          border-radius: 4px;
        }

        .tool-unavailable-note {
          margin-top: 8px;
          font-size: 0.7rem;
          line-height: 1.45;
          color: var(--text-muted);
        }

        .toggle-switch:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }

        .status-indicator {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.75rem;
          font-weight: 600;
        }
      `}</style>
    </div>
  );
};
