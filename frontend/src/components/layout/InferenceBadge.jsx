import React, { useEffect, useRef, useState } from 'react';
import { Cloud, HardDrive, Info } from 'lucide-react';
import { useApp } from '../../state/AppContext';

/**
 * Compact, always-visible statement of where inference runs and what the
 * workbench cannot yet do.
 *
 * This replaces a full-width banner. The honesty requirement is that the
 * claim is never hidden or overstated - not that it occupies a quarter of
 * the screen. So the pill is always present, colour-coded, and expands to
 * the full detail on click.
 *
 * `onPremise` is read from the backend, never assumed here.
 */
export const InferenceBadge = () => {
  const { health } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const inference = health?.inference;
  if (!inference) return null;

  const caps = health?.implemented ?? {};
  const missing = [];
  if (!caps.retrieval) missing.push('Document retrieval');
  if (!caps.documentIndexing) missing.push('Document indexing');
  if (!caps.toolCalling) missing.push('Tool calling');
  if (!caps.authentication) missing.push('Authentication');

  let tone = 'muted';
  let Icon = Info;
  let label = 'No model';

  if (inference.configured && inference.onPremise) {
    tone = 'on-prem';
    Icon = HardDrive;
    label = 'On-premise';
  } else if (inference.configured) {
    tone = 'external';
    Icon = Cloud;
    label = 'External model';
  }

  return (
    <div className="inference-badge-wrapper" ref={ref}>
      <button
        className={`inference-badge ${tone}`}
        onClick={() => setOpen(!open)}
        title="Where inference runs"
      >
        <Icon size={13} />
        <span>{label}</span>
      </button>

      {open && (
        <div className="inference-popover animate-fade-in">
          <div className="pop-row">
            <span className="pop-key">Provider</span>
            <span className="pop-val">{inference.provider}</span>
          </div>
          <div className="pop-row">
            <span className="pop-key">Model</span>
            <span className="pop-val font-mono">{inference.model || '—'}</span>
          </div>
          <div className="pop-row">
            <span className="pop-key">Runs</span>
            <span className="pop-val">
              {inference.onPremise ? 'Inside your network' : 'On an external service'}
            </span>
          </div>

          <p className={`pop-note ${tone}`}>
            {inference.configured && !inference.onPremise
              ? 'Prototype inference. Prompts leave your network, so this is not sovereign yet. Switching to a local runtime is a configuration change.'
              : inference.onPremise
                ? 'Inference runs inside your own infrastructure. No prompt leaves the network.'
                : 'No inference provider is configured, so the workbench cannot answer questions yet.'}
          </p>

          {missing.length > 0 && (
            <>
              <div className="pop-divider" />
              <div className="pop-key">Not implemented yet</div>
              <ul className="pop-missing">
                {missing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      <style>{`
        .inference-badge-wrapper {
          position: relative;
          flex-shrink: 0;
        }

        .inference-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 5px 11px;
          border-radius: 999px;
          border: 1px solid transparent;
          font-size: 0.75rem;
          font-weight: 600;
          cursor: pointer;
          white-space: nowrap;
          transition: filter 0.15s ease;
        }

        .inference-badge:hover { filter: brightness(0.96); }

        .inference-badge.on-prem {
          background: var(--success-bg);
          color: var(--success);
        }

        .inference-badge.external {
          background: var(--warning-bg);
          color: var(--warning);
        }

        .inference-badge.muted {
          background: var(--bg-hover);
          color: var(--text-muted);
        }

        .inference-popover {
          position: absolute;
          top: calc(100% + 8px);
          right: 0;
          z-index: 60;
          width: 290px;
          padding: 14px;
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          background: var(--bg-card);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
          text-align: left;
        }

        .pop-row {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 7px;
          font-size: 0.8125rem;
        }

        .pop-key {
          color: var(--text-muted);
          font-size: 0.75rem;
          font-weight: 600;
        }

        .pop-val {
          color: var(--text-primary);
          text-align: right;
          word-break: break-word;
        }

        .pop-note {
          margin-top: 10px;
          font-size: 0.75rem;
          line-height: 1.5;
          color: var(--text-secondary);
        }

        .pop-note.external { color: var(--warning); }
        .pop-note.on-prem { color: var(--success); }

        .pop-divider {
          height: 1px;
          margin: 12px 0 10px;
          background: var(--border-subtle);
        }

        .pop-missing {
          margin: 6px 0 0;
          padding-left: 16px;
          font-size: 0.75rem;
          line-height: 1.7;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};

export default InferenceBadge;
