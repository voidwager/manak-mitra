import React, { useEffect, useRef, useState } from 'react';
import { MoreVertical, Check, Cpu, Sparkles } from 'lucide-react';
import { useApp } from '../../state/AppContext';

/**
 * Per-chat settings.
 *
 * One setting so far, and it is the one worth having: which model answers
 * this thread. SI-1 routes automatically by default - a question with an
 * image goes to the vision model, an agent configured for analysis goes to
 * the reasoning model - and this is the escape hatch for when somebody wants
 * a specific one regardless.
 *
 * Two scopes, deliberately separate:
 *
 *   this chat    stored on the conversation, so pinning one thread does not
 *                touch any other
 *   my default   stored on the account, and where every new chat starts
 *
 * Both are provider-qualified, so a choice of Gemini stays on Gemini even if
 * the deployment's default vendor changes.
 *
 * The chat pin wins where both are set - it is the narrower instruction, and
 * somebody pinning one thread has not asked to change the rest.
 */
export const ChatSettingsMenu = () => {
  const {
    activeConversation,
    modelCatalogue,
    setChatModel,
    settings,
    updateSettingsAction,
  } = useApp();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [scope, setScope] = useState('chat');
  const ref = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  // Nothing to configure until a thread exists.
  if (!activeConversation) return null;

  const selectable = modelCatalogue?.selectable ?? [];
  const pinnedHere = activeConversation.modelOverride || '';
  const myDefault = settings?.chatModel || '';

  const current = scope === 'chat' ? pinnedHere : myDefault;

  const choose = async (modelId) => {
    setSaving(true);
    if (scope === 'chat') {
      await setChatModel(activeConversation.id, modelId);
    } else {
      // Saved against the account, so it survives this conversation and
      // applies to every new one.
      await updateSettingsAction({ chatModel: modelId });
    }
    setSaving(false);
    setOpen(false);
  };

  return (
    <div className="chat-settings-wrapper" ref={ref}>
      <button
        className={`chat-settings-btn ${current ? 'pinned' : ''}`}
        onClick={() => setOpen(!open)}
        title="Chat settings"
        aria-label="Chat settings"
      >
        <MoreVertical size={17} />
      </button>

      {open && (
        <div className="chat-settings-panel animate-fade-in">
          <div className="scope-switch" role="tablist">
            <button
              role="tab"
              aria-selected={scope === 'chat'}
              className={scope === 'chat' ? 'active' : ''}
              onClick={() => setScope('chat')}
            >
              This chat
            </button>
            <button
              role="tab"
              aria-selected={scope === 'default'}
              className={scope === 'default' ? 'active' : ''}
              onClick={() => setScope('default')}
            >
              My default
            </button>
          </div>

          <div className="panel-label">
            <Cpu size={13} />
            <span>
              {scope === 'chat'
                ? 'Model for this chat only'
                : 'Model every new chat starts on'}
            </span>
          </div>

          <button
            className={`model-choice ${current === '' ? 'active' : ''}`}
            onClick={() => choose('')}
            disabled={saving}
          >
            <Sparkles size={14} className="choice-icon" />
            <div className="choice-body">
              <div className="choice-name">
                {scope === 'chat' && myDefault ? 'Use my default' : 'Automatic (SI-1)'}
              </div>
              <div className="choice-note">
                {scope === 'chat' && myDefault
                  ? myDefault
                  : 'Picks per question - vision for images, reasoning for analysis.'}
              </div>
            </div>
            {current === '' && <Check size={15} className="choice-check" />}
          </button>

          {selectable.map((model) => (
            <button
              key={model.id}
              className={`model-choice ${current === model.id ? 'active' : ''}`}
              onClick={() => choose(model.id)}
              disabled={saving}
            >
              <Cpu size={14} className="choice-icon" />
              <div className="choice-body">
                <div className="choice-name">{model.label}</div>
                <div className="choice-note">
                  {model.provider}
                  {model.acceptsImages ? ' · reads images' : ' · text only'}
                </div>
              </div>
              {current === model.id && <Check size={15} className="choice-check" />}
            </button>
          ))}

          {selectable.length === 0 && (
            <div className="panel-empty">
              No models are configured on the server yet.
            </div>
          )}

          <div className="panel-footer">
            {/*
              * An image always overrides a pin. Said here rather than
              * discovered from an answer that ignored the picture - a pin
              * that silently stopped working would be worse than no pin.
              */}
            A question with an image always uses the vision model, whatever is
            chosen here.
            {scope === 'chat' && pinnedHere && myDefault ? (
              <> This chat overrides your default of {myDefault}.</>
            ) : null}
          </div>
        </div>
      )}

      <style>{`
        .chat-settings-wrapper {
          position: relative;
        }

        .chat-settings-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 7px;
          border: 1px solid transparent;
          border-radius: var(--radius-sm);
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .chat-settings-btn:hover {
          color: var(--text-primary);
          background: var(--bg-hover);
        }

        /* A pinned chat is not the default state, so it is visibly marked. */
        .chat-settings-btn.pinned {
          color: var(--accent-primary);
          border-color: var(--accent-primary);
        }

        .chat-settings-panel {
          position: absolute;
          top: calc(100% + 8px);
          right: 0;
          z-index: 60;
          width: 300px;
          padding: 8px;
          background: var(--bg-card);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
        }

        .scope-switch {
          display: flex;
          gap: 4px;
          padding: 4px;
          margin-bottom: 8px;
          border-radius: var(--radius-md);
          background: var(--bg-card-subtle);
        }

        .scope-switch button {
          flex: 1;
          padding: 6px 8px;
          border: none;
          border-radius: calc(var(--radius-md) - 3px);
          background: transparent;
          color: var(--text-muted);
          font-size: 0.76rem;
          font-weight: 600;
          cursor: pointer;
        }

        .scope-switch button.active {
          background: var(--bg-card);
          color: var(--text-primary);
        }

        .panel-label {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px 8px;
          font-size: 0.7rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--text-muted);
        }

        .model-choice {
          display: flex;
          align-items: flex-start;
          gap: 9px;
          width: 100%;
          padding: 9px 10px;
          border: none;
          border-radius: var(--radius-sm);
          background: transparent;
          text-align: left;
          cursor: pointer;
          color: var(--text-primary);
        }

        .model-choice:hover:not(:disabled) {
          background: var(--bg-hover);
        }

        .model-choice:disabled {
          opacity: 0.6;
          cursor: wait;
        }

        .model-choice.active {
          background: var(--accent-light);
        }

        .choice-icon {
          margin-top: 2px;
          flex-shrink: 0;
          color: var(--accent-primary);
        }

        .choice-body {
          flex: 1;
          min-width: 0;
        }

        .choice-name {
          font-size: 0.825rem;
          font-weight: 600;
        }

        .choice-note {
          font-size: 0.7rem;
          line-height: 1.4;
          color: var(--text-muted);
        }

        .choice-check {
          flex-shrink: 0;
          color: var(--accent-primary);
        }

        .panel-empty {
          padding: 12px 10px;
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .panel-footer {
          margin-top: 6px;
          padding: 9px 10px 4px;
          border-top: 1px solid var(--border-light);
          font-size: 0.68rem;
          line-height: 1.45;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};

export default ChatSettingsMenu;
