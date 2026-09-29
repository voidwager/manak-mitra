import React from 'react';

/**
 * The waiting state, shown inside the assistant card before the first token.
 *
 * What it replaced: an *empty* assistant bubble with a separate
 * "••• Generating response..." pill stacked underneath it. Two dead cards and
 * a fixed string, for however long the model took. Nothing moved, nothing
 * said what was happening, and people left.
 *
 * The rule this follows, and the reason it looks the way it does: **every
 * stage after the first is something the server actually reported.** The
 * stream already emits `tool` and `sources` events before the first token, so
 * "Running read_document" names a tool that really ran and "Reading 5
 * passages from 2 documents" counts passages that were really retrieved.
 *
 * It would have been easy - and more impressive-looking - to script a fixed
 * sequence on a timer: Analysing, Cross-referencing, Verifying. That would be
 * a lie told by a progress indicator, and this product's entire claim is that
 * its activity trace is derived from the running system rather than asserted.
 * A spinner that invents progress undercuts the thing being demonstrated.
 *
 * Only the opening line is generic, because at that instant nothing has
 * happened yet.
 */

/** Steps worth showing mid-flight. The trace carries bookkeeping too. */
const INTERESTING = /^(SI-1:|Tool:|Knowledge base retrieval|Retrieved|Read ')/;

export const PreparingState = ({ stage, steps }) => {
  const label = stage?.label || 'Getting your answer ready';

  // The tail, not the head: the most recent work is the informative part, and
  // the first two lines are always "Task received" / "Message stored".
  const live = (steps || []).filter((s) => INTERESTING.test(s?.label || '')).slice(-2);

  return (
    <div className="preparing-state" role="status" aria-live="polite">
      <div className="preparing-head">
        <span className="preparing-orb" aria-hidden="true" />
        {/*
          * Keyed on the stage so React remounts the span and the entrance
          * animation replays. Without the key the text swaps in place and the
          * transition between phrases is lost.
          */}
        <span key={stage?.key || 'start'} className="preparing-label">
          {label}
        </span>
      </div>

      {live.length > 0 && (
        <div className="preparing-steps">
          {live.map((step) => (
            <div key={step.label} className="preparing-step">
              <span className="preparing-tick" aria-hidden="true">
                ✓
              </span>
              <span className="preparing-step-text">{step.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Weight in the card, so it is not an empty box with a caption. */}
      <div className="preparing-skeleton" aria-hidden="true">
        <span className="skeleton-line" />
        <span className="skeleton-line short" />
      </div>

      <style>{`
        .preparing-state {
          display: flex;
          flex-direction: column;
          gap: 12px;
          min-width: 260px;
        }

        .preparing-head {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .preparing-orb {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--accent-primary);
          flex: none;
          animation: preparingPulse 1.4s ease-in-out infinite;
        }

        @keyframes preparingPulse {
          0%, 100% { opacity: 0.35; transform: scale(0.82); }
          50%      { opacity: 1;    transform: scale(1); }
        }

        .preparing-label {
          font-size: 0.875rem;
          color: var(--text-secondary);
          animation: preparingLabelIn 0.42s cubic-bezier(0.22, 1, 0.36, 1) both;
        }

        /* Rise + fade, so one phrase hands over to the next rather than
           snapping. The distance is small on purpose: this sits next to text
           the user is about to read, not on a splash screen. */
        @keyframes preparingLabelIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        .preparing-steps {
          display: flex;
          flex-direction: column;
          gap: 5px;
          padding-left: 19px;
        }

        .preparing-step {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          font-size: 0.8rem;
          color: var(--text-muted, var(--text-secondary));
          animation: preparingLabelIn 0.42s cubic-bezier(0.22, 1, 0.36, 1) both;
        }

        .preparing-tick {
          color: var(--success);
          flex: none;
          line-height: 1.4;
        }

        .preparing-step-text {
          line-height: 1.4;
          /* A retrieval step can run long; one line each keeps the waiting
             state from reflowing the card on every event. */
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 46ch;
        }

        .preparing-skeleton {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding-left: 19px;
        }

        .skeleton-line {
          height: 9px;
          border-radius: 5px;
          width: 100%;
          background: linear-gradient(
            90deg,
            var(--bg-card-subtle) 25%,
            var(--border-subtle) 37%,
            var(--bg-card-subtle) 63%
          );
          background-size: 400% 100%;
          animation: skeletonSweep 1.6s ease-in-out infinite;
        }

        .skeleton-line.short { width: 62%; }

        @keyframes skeletonSweep {
          from { background-position: 100% 50%; }
          to   { background-position: 0 50%; }
        }

        /* Movement here is decoration, not information - the label already
           says everything. Anyone who has asked for less motion loses nothing. */
        @media (prefers-reduced-motion: reduce) {
          .preparing-orb,
          .skeleton-line {
            animation: none;
          }
          .preparing-label,
          .preparing-step {
            animation: none;
          }
          .preparing-orb { opacity: 1; }
        }
      `}</style>
    </div>
  );
};

export default PreparingState;
