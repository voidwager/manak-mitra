import React from 'react';
import { AlertTriangle, RefreshCw, WifiOff, X } from 'lucide-react';
import { useApp } from '../../state/AppContext';

/**
 * Full-width strip for conditions the user must act on: the backend being
 * unreachable, or an operation that failed.
 *
 * Capability and inference provenance are NOT here - they are a quiet pill
 * in the header (see InferenceBadge). Honest reporting should be always
 * visible, not always loud.
 */
export const StatusBanner = () => {
  const { connectionError, retryConnection, errorBanner, clearError } = useApp();

  if (connectionError) {
    return (
      <div className="status-strip status-offline" role="alert">
        <WifiOff size={15} />
        <span className="status-text">
          Backend unreachable. {connectionError}
        </span>
        <button className="status-action" onClick={retryConnection}>
          <RefreshCw size={13} />
          <span>Retry</span>
        </button>
        <StatusStyles />
      </div>
    );
  }

  if (errorBanner) {
    return (
      <div className="status-strip status-error" role="alert">
        <AlertTriangle size={15} />
        <span className="status-text">
          Could not {errorBanner.context}: {errorBanner.message}
        </span>
        <button className="status-action" onClick={clearError} aria-label="Dismiss">
          <X size={14} />
        </button>
        <StatusStyles />
      </div>
    );
  }

  // The capability notice used to live here as a full-width bar on every
  // page. It is now a compact pill in the header (InferenceBadge) - same
  // information, far less shouting. Only conditions the user must act on
  // still get a banner.
  return null;
};

const StatusStyles = () => (
  <style>{`
    .status-strip {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
      padding: 9px 20px;
      font-size: 0.8125rem;
      line-height: 1.4;
      border-bottom: 1px solid var(--border-light);
    }

    .status-strip .status-text {
      flex: 1;
      min-width: 0;
    }

    .status-notice {
      background: var(--bg-card-subtle);
      color: var(--text-secondary);
    }

    .status-offline {
      background: var(--danger-bg);
      color: var(--danger);
    }

    .status-error {
      background: var(--warning-bg);
      color: var(--warning);
    }

    .status-action {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      flex-shrink: 0;
      padding: 4px 9px;
      border: 1px solid currentColor;
      border-radius: var(--radius-sm);
      background: transparent;
      color: inherit;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      opacity: 0.85;
      transition: opacity 0.15s ease;
    }

    .status-action:hover {
      opacity: 1;
    }
  `}</style>
);

export default StatusBanner;
