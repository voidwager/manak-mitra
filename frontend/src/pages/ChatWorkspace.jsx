import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../state/AppContext';
import { AttachmentImage } from '../components/chat/AttachmentImage';
import { MessageContent } from '../components/chat/MessageContent';
import { isReportable } from '../utils/reports';
import { PreparingState } from '../components/chat/PreparingState';
import { formatClock } from '../utils/time';
import {
  Sparkles,
  Paperclip,
  Mic,
  Send,
  FileText,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Check,
  Copy,
  FileCheck,
  X,
  Activity,
  MicOff,
  Loader2,
  AlertTriangle,
  Image as ImageIcon,
} from 'lucide-react';

/** Whether a persisted attachment record is an image worth rendering. */
const isImageAttachment = (att) =>
  att?.isImage === true ||
  (typeof att?.type === 'string' && att.type.startsWith('image/'));

export const ChatWorkspace = () => {
  const { 
    activeConversation, 
    sendMessage, 
    attachments, 
    addAttachment, 
    removeAttachment, 
    isTyping, 
    openDocPreview, 
    generateReportAction,
    reportPendingFor,
    streamStage,
    activeAgent,
    agents,
    selectAgent,
    settings,
    health
  } = useApp();

  /*
   * Read from the server rather than restated here.
   *
   * This list was hardcoded and went stale the moment documents became
   * attachable: PDFs were accepted by the endpoint while the picker went on
   * greying them out, so the feature existed and could not be reached. The
   * fallback is only for a health response that has not arrived yet.
   */
  const acceptedTypes = (health?.attachments?.accepted ?? [
    '.png',
    '.jpg',
    '.jpeg',
    '.webp',
    '.gif',
    '.txt',
    '.md',
    '.csv',
    '.log',
  ]).join(',');

  // Same rule as the header: the composer offers SI-1, not a menu of
  // specialists to choose between before the question exists. An active
  // specialist stays listed so the control never contradicts the workspace.
  const universalAgents = (agents ?? []).filter((a) => a.isUniversal);
  const baseAgents = universalAgents.length ? universalAgents : (agents ?? []);
  const orderedAgents =
    activeAgent && !baseAgents.some((a) => a.id === activeAgent.id)
      ? [...baseAgents, activeAgent]
      : baseAgents;

  const [inputVal, setInputVal] = useState('');
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [activityOpenMap, setActivityOpenMap] = useState({});
  const [isRecording, setIsRecording] = useState(false);
  const [copiedId, setCopiedId] = useState(null);

  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const scrollAreaRef = useRef(null);
  const modelDropdownRef = useRef(null);
  const lastConversationId = useRef(null);

  const conversationId = activeConversation?.id ?? null;
  const messageCount = activeConversation?.messages?.length ?? 0;

  /*
   * Two different scroll behaviours, which is the whole fix.
   *
   * Switching conversations must land at the bottom *instantly*. The old
   * code always used smooth scrolling, so opening an existing thread
   * animated from the top all the way down - which read as "it scrolled
   * back". Only a new message inside the thread you are already reading
   * should animate.
   */
  useEffect(() => {
    const switched = lastConversationId.current !== conversationId;
    lastConversationId.current = conversationId;

    if (switched) {
      const area = scrollAreaRef.current;
      if (area) area.scrollTop = area.scrollHeight;
      return;
    }

    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversationId, messageCount, isTyping]);

  // Streaming appends to the last message rather than adding one, so it
  // needs its own nudge - and only when the user is already near the end.
  const streamingText = activeConversation?.messages?.at(-1)?.streaming
    ? activeConversation.messages.at(-1).text
    : null;

  useEffect(() => {
    if (streamingText === null) return;
    const area = scrollAreaRef.current;
    if (!area) return;

    const nearBottom =
      area.scrollHeight - area.scrollTop - area.clientHeight < 120;
    if (nearBottom) area.scrollTop = area.scrollHeight;
  }, [streamingText]);

  // Close model dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target)) {
        setModelDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSend = () => {
    if (!inputVal.trim() && attachments.length === 0) return;
    sendMessage(inputVal);
    setInputVal('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileChange = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(file => addAttachment(file));
    e.target.value = '';
  };

  const toggleActivity = (msgId) => {
    setActivityOpenMap(prev => ({
      ...prev,
      [msgId]: !prev[msgId]
    }));
  };

  const handleMicToggle = () => {
    if (isRecording) {
      setIsRecording(false);
    } else {
      setIsRecording(true);
      // Simulate audio transcription after 2.5s
      setTimeout(() => {
        setInputVal('Analyze this inspection report and identify any potential abnormalities.');
        setIsRecording(false);
      }, 2200);
    }
  };

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const messages = activeConversation?.messages || [];

  // True while a streaming placeholder is on screen. The standalone waiting
  // pill defers to it, so the two never render at once - which is exactly the
  // stacked empty-card-plus-spinner this change removes.
  const hasStreamingMessage = messages.some((m) => m.streaming);

  return (
    <div className={`chat-workspace-container ${messages.length === 0 ? "is-empty" : ""}`}>
      {/* Hidden File Input */}
      <input 
        type="file" 
        ref={fileInputRef} 
        onChange={handleFileChange} 
        style={{ display: 'none' }}
        /* Exactly what the attachment endpoint accepts - see above. */
        accept={acceptedTypes}
      />

      {/* Messages Thread Container */}
      <div className="messages-scroll-area" ref={scrollAreaRef}>
        {messages.length === 0 ? (
          <div className="empty-chat-state animate-fade-in">
            <h2>How can I help you today?</h2>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.sender === 'user';
            const isActivityOpen = activityOpenMap[msg.id] ?? false;
            // An inspection report on a greeting is noise - see utils/reports.
            const showReport = isReportable(msg);

            return (
              <div key={msg.id} className="message-wrapper">
                {/* Timestamp header if enabled */}
                {settings.showTimestamps && (index === 0 || messages[index - 1]?.sender !== msg.sender) && (
                  <div className="message-timestamp-divider">
                    <span>{formatClock(msg.createdAt)}</span>
                  </div>
                )}

                {isUser ? (
                  /* User Message Bubble */
                  <div className="user-message-row animate-fade-in">
                    <div className="user-bubble">
                      <p>{msg.text}</p>
                      {msg.attachments && msg.attachments.length > 0 && (
                        <div className="msg-attachments-container">
                          {msg.attachments.map((att, i) => (
                            <div key={i} className="msg-att-chip">
                              <FileText size={14} />
                              <span>{att.name}</span>
                            </div>
                          ))}
                          {msg.attachments
                            .filter((att) => att.id && isImageAttachment(att))
                            .map((att) => (
                              <AttachmentImage
                                key={`img-${att.id}`}
                                attachmentId={att.id}
                                alt={att.name}
                              />
                            ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  /* Assistant Message Row (Reference Image match) */
                  <div className="assistant-message-row animate-fade-in">
                    <div className="assistant-avatar">
                      <Sparkles size={16} />
                    </div>

                    <div className="assistant-content-card">
                      {/*
                        * While the reply is still being prepared this card
                        * carries the waiting state itself. It used to render
                        * an *empty* bubble with a separate "Generating
                        * response..." pill stacked underneath it - an empty
                        * box on top of a spinner, which is most of why the
                        * wait read as broken.
                        */}
                      {msg.streaming && !msg.text ? (
                        <PreparingState
                          stage={streamStage}
                          steps={msg.activityTrace}
                        />
                      ) : (
                      <div
                        className={`assistant-text-body ${msg.streaming ? 'is-streaming' : ''}`}
                      >
                        {/*
                          * Models answer in Markdown whether or not you ask
                          * them to. This used to handle `### ` only, so a
                          * normal reply arrived full of literal asterisks.
                          * The renderer builds React elements, never HTML,
                          * so untrusted model output cannot inject markup.
                          */}
                        <MessageContent
                          text={msg.text}
                          onCitationClick={(n) => {
                            const list = msg.sources?.length
                              ? msg.sources
                              : msg.source
                                ? [msg.source]
                                : [];
                            // Markers are 1-based and refer to the passages
                            // in the order the server retrieved them.
                            const cited = list[n - 1];
                            if (cited) openDocPreview(cited);
                          }}
                        />
                        {msg.streaming && <span className="stream-caret" />}
                      </div>
                      )}

                      {/*
                        * Citations. Every card here corresponds to a passage
                        * the backend actually retrieved and put in the
                        * prompt - the API never derives one from the model's
                        * text - so clicking through always lands on real
                        * source material.
                        */}
                      {(msg.sources?.length ? msg.sources : msg.source ? [msg.source] : []).length > 0 && (
                        <div className="source-section-wrapper">
                          <div className="source-label">
                            {(msg.sources?.length ?? 1) > 1
                              ? `Sources (${msg.sources.length})`
                              : 'Source'}
                          </div>
                          {(msg.sources?.length ? msg.sources : [msg.source]).map(
                            (src, sIdx) => (
                              <div
                                key={src.documentId ?? sIdx}
                                className="source-citation-card"
                                onClick={() => openDocPreview(src)}
                              >
                                <div className="pdf-badge-icon">
                                  <FileText size={18} />
                                </div>
                                <div className="source-details">
                                  <div className="source-title">{src.title}</div>
                                  <div className="source-meta">{src.page}</div>
                                </div>
                                <ExternalLink size={16} className="source-link-icon" />
                              </div>
                            ),
                          )}
                        </div>
                      )}

                      {/* Agent Activity Panel (Requirement #17 & Settings control) */}
                      {settings.showAgentActivity && msg.activityTrace && msg.activityTrace.length > 0 && (
                        <div className={`activity-trace-container ${isActivityOpen ? 'open' : ''}`}>
                          <button 
                            className="activity-trace-header"
                            onClick={() => toggleActivity(msg.id)}
                          >
                            <div className="activity-title-group">
                              <Activity size={14} className="activity-icon" />
                              <span>
                                {isActivityOpen
                                  ? 'Agent activity'
                                  : `Agent activity (${msg.activityTrace.length})`}
                              </span>
                            </div>
                            {isActivityOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </button>

                          {isActivityOpen && (
                            <div className="activity-steps-list animate-fade-in">
                              {msg.activityTrace.map((step, sIdx) => (
                                <div key={sIdx} className="activity-step-item">
                                  <span className="step-check">✓</span>
                                  <span className="step-label">{step.label}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Assistant Card Footer Bar */}
                      {!msg.streaming && (
                      <div className={`assistant-card-footer ${showReport ? '' : 'actions-only'}`}>
                        {showReport && (
                          <button
                            className="action-btn-pill"
                            onClick={() => generateReportAction(msg)}
                            disabled={reportPendingFor === msg.id}
                          >
                            <FileCheck size={14} />
                            <span>
                              {reportPendingFor === msg.id
                                ? 'Compiling report...'
                                : msg.report
                                  ? 'View Report'
                                  : 'Generate Report'}
                            </span>
                          </button>
                        )}
                        
                        <button 
                          className="action-icon-btn"
                          onClick={() => handleCopy(msg.id, msg.text)}
                          title="Copy text"
                        >
                          {copiedId === msg.id ? <Check size={14} className="text-success" /> : <Copy size={14} />}
                        </button>
                      </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/*
          * Only when there is no streaming bubble to carry the waiting state -
          * the brief window before `start` arrives and creates one. Rendering
          * both is what produced the stacked empty-card-plus-spinner.
          */}
        {isTyping && !hasStreamingMessage && (
          <div className="assistant-message-row animate-fade-in">
            <div className="assistant-avatar">
              <Sparkles size={16} />
            </div>
            <div className="assistant-content-card">
              <PreparingState stage={streamStage} steps={null} />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Bottom Input Bar (Matches Reference Image) */}
      <div className="floating-input-wrapper">
        <div className="floating-input-card">
          {/* File Attachment Chips */}
          {attachments.length > 0 && (
            <div className="attachments-chip-bar">
              {attachments.map((att, i) => (
                <div
                  key={att.id ?? i}
                  /*
                   * Three states. An attachment the model cannot read is
                   * marked here rather than discovered from an answer that
                   * quietly ignored it - which reads as the model being
                   * careless instead of the deployment lacking a capability.
                   */
                  className={`att-chip ${att.uploading ? 'uploading' : ''} ${
                    att.readable === false ? 'unreadable' : ''
                  }`}
                  title={att.note || att.name}
                >
                  {att.uploading ? (
                    <Loader2 size={14} className="att-chip-icon spin" />
                  ) : att.readable === false ? (
                    <AlertTriangle size={14} className="att-chip-icon" />
                  ) : att.isImage ? (
                    <ImageIcon size={14} className="att-chip-icon" />
                  ) : (
                    <FileText size={14} className="att-chip-icon" />
                  )}
                  <span className="att-chip-name">{att.name}</span>
                  <button 
                    className="att-chip-remove"
                    onClick={() => removeAttachment(i)}
                    aria-label={`Remove ${att.name}`}
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {attachments.some((a) => a.readable === false) && (
            <div className="att-warning">
              <AlertTriangle size={13} />
              <span>
                {attachments.find((a) => a.readable === false)?.note ||
                  'This attachment cannot be read in this deployment.'}
              </span>
            </div>
          )}

          {/* Recording Banner if mic active */}
          {isRecording && (
            <div className="recording-banner animate-fade-in">
              <span className="rec-dot animate-pulse-dot" />
              <span>Listening to industrial speech query...</span>
            </div>
          )}

          {/* Input Textarea */}
          <textarea
            className="chat-textarea"
            placeholder="Ask anything..."
            rows={1}
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
          />

          {/* Bottom Toolbar */}
          <div className="input-toolbar">
            <div className="toolbar-left">
              {/* Paperclip Attachment Button */}
              <button 
                className="toolbar-btn"
                onClick={() => fileInputRef.current?.click()}
                title="Attach Document or Image"
              >
                <Paperclip size={18} />
              </button>

              {/* Agent/Model Selector Dropdown */}
              <div className="model-selector-wrapper" ref={modelDropdownRef}>
                <button 
                  className="model-selector-btn"
                  onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                >
                  <span>{activeAgent?.name ?? 'SI-1'}</span>
                  <ChevronDown size={14} />
                </button>

                {modelDropdownOpen && (
                  <div className="model-dropdown-menu animate-fade-in">
                    {/*
                      * "Auto" used to set a label and nothing else - the
                      * active agent stayed whatever it already was. It now
                      * selects SI-1, which genuinely does pick a specialist
                      * per question.
                      */}
                    <div className="dropdown-label">Assistant</div>
                    {orderedAgents.map(a => (
                      <button
                        key={a.id}
                        className={`model-option ${activeAgent?.id === a.id ? 'active' : ''}`}
                        onClick={() => {
                          selectAgent(a.id);
                          setModelDropdownOpen(false);
                        }}
                        title={a.description}
                      >
                        <span>{a.isUniversal ? `${a.name} - automatic` : a.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="toolbar-right">
              {/* Microphone Voice Button */}
              <button 
                className={`toolbar-btn ${isRecording ? 'recording-active' : ''}`}
                onClick={handleMicToggle}
                title={isRecording ? 'Stop Recording' : 'Voice Query'}
              >
                {isRecording ? <MicOff size={18} className="text-danger" /> : <Mic size={18} />}
              </button>

              {/* Send Button */}
              <button 
                className="send-message-btn"
                onClick={handleSend}
                disabled={!inputVal.trim() && attachments.length === 0}
                title="Send Message"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .chat-workspace-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          height: 100%;
          background-color: var(--bg-workspace);
          position: relative;
          overflow: hidden;
        }

        .messages-scroll-area {
          flex: 1;
          overflow-y: auto;
          padding: 24px 10%;
          display: flex;
          flex-direction: column;
          gap: 20px;
          padding-bottom: 140px; /* Space for floating input */
        }

        @media (max-width: 1024px) {
          .messages-scroll-area {
            padding: 20px 16px 140px 16px;
          }
        }

        .empty-chat-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          text-align: center;
          margin: auto 0;
          padding: 40px 20px;
        }

        .empty-chat-state h2 {
          font-size: 1.75rem;
          font-weight: 600;
          letter-spacing: -0.015em;
          color: var(--text-primary);
        }

        .message-wrapper {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .message-timestamp-divider {
          text-align: center;
          margin: 8px 0;
        }

        .message-timestamp-divider span {
          font-size: 0.75rem;
          color: var(--text-muted);
          font-weight: 500;
        }

        /* User Message Bubble */
        .user-message-row {
          display: flex;
          justify-content: flex-end;
        }

        .user-bubble {
          max-width: 75%;
          padding: 12px 18px;
          background-color: var(--user-msg-bg);
          color: var(--user-msg-text);
          border-radius: 18px 18px 4px 18px;
          font-size: 0.925rem;
          line-height: 1.5;
          box-shadow: var(--shadow-sm);
        }

        .msg-attachments-container {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 8px;
        }

        .msg-att-chip {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: rgba(255, 255, 255, 0.4);
          border-radius: 6px;
          font-size: 0.775rem;
          font-weight: 500;
        }

        /* Assistant Message Row (Reference Image match) */
        .assistant-message-row {
          display: flex;
          align-items: flex-start;
          gap: 14px;
        }

        .assistant-avatar {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          margin-top: 4px;
        }

        .assistant-content-card {
          flex: 1;
          max-width: 85%;
          background: var(--bg-card);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-lg);
          padding: 20px;
          box-shadow: var(--shadow-sm);
          transition: background-color 0.25s ease;
        }

        .stream-caret {
          display: inline-block;
          width: 2px;
          height: 1em;
          margin-left: 2px;
          vertical-align: text-bottom;
          background-color: var(--accent-primary);
          border-radius: 1px;
          /* Eased rather than a hard two-step blink. Next to text that is
             itself arriving, a square-wave caret reads as a glitch. */
          animation: streamCaret 1.1s ease-in-out infinite;
        }

        @keyframes streamCaret {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.15; }
        }

        /*
         * Text emerging rather than appearing.
         *
         * The fade is on the *bottom edge* of the body while it streams, so
         * the newest line arrives through it. Doing this per token would mean
         * re-animating every element on every chunk - dozens of times a
         * second - and the renderer builds React elements from markdown, so
         * there are no stable per-token nodes to animate anyway. One mask on
         * the container costs nothing and reads better.
         */
        .assistant-text-body.is-streaming {
          -webkit-mask-image: linear-gradient(
            to bottom, #000 0%, #000 calc(100% - 26px), transparent 100%
          );
          mask-image: linear-gradient(
            to bottom, #000 0%, #000 calc(100% - 26px), transparent 100%
          );
        }

        @media (prefers-reduced-motion: reduce) {
          .stream-caret { animation: none; }
          .assistant-text-body.is-streaming {
            -webkit-mask-image: none;
            mask-image: none;
          }
        }

        .assistant-text-body {
          font-size: 0.925rem;
          color: var(--text-primary);
          line-height: 1.6;
        }

        .msg-heading {
          font-size: 1rem;
          font-weight: 700;
          color: var(--text-primary);
          margin: 12px 0 6px 0;
        }

        .att-chip.uploading {
          opacity: 0.7;
        }

        .att-chip.unreadable {
          border-color: var(--warning);
          color: var(--warning);
        }

        .att-warning {
          display: flex;
          align-items: flex-start;
          gap: 7px;
          margin: 0 4px 8px;
          font-size: 0.72rem;
          line-height: 1.45;
          color: var(--warning);
        }

        .msg-att-image-missing {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          margin-top: 8px;
          padding: 10px 12px;
          border: 1px dashed var(--border-light);
          border-radius: var(--radius-sm);
          font-size: 0.72rem;
          color: var(--text-muted);
        }

        .msg-att-image {
          display: block;
          max-width: 260px;
          max-height: 200px;
          margin-top: 8px;
          border-radius: var(--radius-sm);
          border: 1px solid var(--border-light);
          object-fit: contain;
        }

        .spin {
          animation: chat-spin 1s linear infinite;
        }

        @keyframes chat-spin {
          to { transform: rotate(360deg); }
        }

        .msg-paragraph {
          margin-bottom: 12px;
        }

        .msg-paragraph:last-child {
          margin-bottom: 0;
        }

        /* --- Rendered markdown ------------------------------------- */
        .assistant-text-body .msg-heading {
          font-size: 0.95rem;
          font-weight: 700;
          color: var(--text-primary);
          margin: 16px 0 8px;
        }

        .assistant-text-body > .msg-heading:first-child {
          margin-top: 0;
        }

        .msg-list {
          margin: 0 0 12px;
          padding-left: 22px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .msg-list:last-child {
          margin-bottom: 0;
        }

        .msg-list li {
          line-height: 1.6;
        }

        .msg-list li::marker {
          color: var(--text-muted);
        }

        .assistant-text-body strong {
          font-weight: 650;
          color: var(--text-primary);
        }

        .msg-code {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 0.85em;
          padding: 1px 5px;
          border-radius: 4px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
        }

        .msg-pre {
          margin: 0 0 12px;
          padding: 12px 14px;
          border-radius: var(--radius-sm);
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          /* A long line scrolls inside the block rather than widening the
             whole message column. */
          overflow-x: auto;
        }

        .msg-pre code {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 0.8rem;
          line-height: 1.55;
          white-space: pre;
        }

        /* Citation markers. Clickable, because [2] is only useful if it
           takes you to the passage it refers to. */
        .msg-citation-group {
          font-size: 0.7em;
          margin-left: 2px;
        }

        .msg-citation {
          padding: 0 3px;
          border: none;
          background: var(--accent-light);
          color: var(--accent-text);
          border-radius: 3px;
          font: inherit;
          font-weight: 700;
          cursor: pointer;
          line-height: 1.4;
        }

        .msg-citation:hover {
          background: var(--accent-primary);
          color: var(--accent-contrast);
        }

        .msg-citation + .msg-citation {
          margin-left: 2px;
        }

        /* Source Citation Card (Reference Image match) */
        .source-section-wrapper {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid var(--border-light);
        }

        .source-label {
          font-size: 0.8rem;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 8px;
        }

        .source-citation-card {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .source-citation-card + .source-citation-card {
          margin-top: 8px;
        }

        .source-citation-card:hover {
          background: var(--bg-hover);
          border-color: var(--accent-primary);
          box-shadow: var(--shadow-sm);
        }

        .pdf-badge-icon {
          width: 32px;
          height: 32px;
          border-radius: 8px;
          background: var(--danger-bg);
          color: var(--danger);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .source-details {
          flex: 1;
        }

        .source-title {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .source-meta {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .source-link-icon {
          color: var(--text-muted);
        }

        /* Agent Activity Panel */
        /*
         * Collapsed by default: a quiet one-line toggle. It only takes on a
         * card treatment once opened, so a short reply is not buried under a
         * panel the reader did not ask for.
         */
        .activity-trace-container {
          margin-top: 10px;
          border: 1px solid transparent;
          border-radius: var(--radius-md);
          overflow: hidden;
          transition: background-color 0.15s ease, border-color 0.15s ease;
        }

        .activity-trace-container.open {
          margin-top: 14px;
          background: var(--bg-card-subtle);
          border-color: var(--border-light);
        }

        .activity-trace-header {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 6px 4px;
          background: transparent;
          border: none;
          font-size: 0.75rem;
          color: var(--text-muted);
          font-weight: 500;
          cursor: pointer;
          transition: color 0.15s ease;
        }

        .activity-trace-header:hover {
          color: var(--text-secondary);
        }

        .activity-trace-container.open .activity-trace-header {
          padding: 8px 12px;
          font-size: 0.775rem;
          font-weight: 600;
          color: var(--text-secondary);
        }

        .activity-trace-container:not(.open) .activity-icon {
          color: var(--text-muted);
        }

        .activity-title-group {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .activity-icon {
          color: var(--accent-primary);
        }

        .activity-steps-list {
          padding: 8px 12px 12px 12px;
          border-top: 1px solid var(--border-light);
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .activity-step-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.775rem;
          color: var(--text-secondary);
        }

        .step-check {
          color: var(--success);
          font-weight: 700;
        }

        /* Assistant Card Footer Bar */
        .assistant-card-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-top: 14px;
          padding-top: 10px;
        }

        /* Without the report action there is nothing to space against, so
           the remaining icon buttons sit on the right rather than drifting
           to the left edge. */
        .assistant-card-footer.actions-only {
          justify-content: flex-end;
          margin-top: 6px;
        }

        .action-btn-pill {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: var(--accent-light);
          color: var(--accent-text);
          border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
          border-radius: 999px;
          font-size: 0.775rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .action-btn-pill:hover {
          background: var(--accent-primary);
          color: var(--accent-contrast);
        }

        .action-icon-btn {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
          transition: color 0.15s ease;
        }

        .action-icon-btn:hover {
          color: var(--text-primary);
        }

        /*
         * Empty state: the composer joins the heading in the middle of the
         * screen instead of sitting pinned to the bottom. Once there are
         * messages it returns to the bottom so the thread has room.
         */
        .chat-workspace-container.is-empty {
          justify-content: center;
        }

        .chat-workspace-container.is-empty .messages-scroll-area {
          flex: 0 0 auto;
          overflow: visible;
          padding-bottom: 0;
        }

        .chat-workspace-container.is-empty .empty-chat-state {
          margin: 0;
          padding: 0 20px 22px;
        }

        .chat-workspace-container.is-empty .floating-input-wrapper {
          position: relative;
          bottom: auto;
          left: auto;
          right: auto;
          margin: 0 10%;
        }

        @media (max-width: 1024px) {
          .chat-workspace-container.is-empty .floating-input-wrapper {
            margin: 0 16px;
          }
        }

        /* Floating Input Bar (Reference Image match) */
        .floating-input-wrapper {
          position: absolute;
          bottom: 24px;
          left: 10%;
          right: 10%;
          z-index: 30;
        }

        @media (max-width: 1024px) {
          .floating-input-wrapper {
            left: 16px;
            right: 16px;
            /* Clears the home indicator on phones that have one. The inset
               is 0 everywhere else, so this is just 16px on a desktop. */
            bottom: calc(16px + env(safe-area-inset-bottom, 0px));
          }
        }

        /*
         * A scrim behind the composer, so the conversation dissolves into
         * the page as it scrolls under the card instead of stopping dead
         * against its edge. Half of what made the card read as pasted on
         * was this collision; the shadow was only the other half.
         *
         * The insets are exact rather than eyeballed. The wrapper sits at
         * 10% either side, so it is 80% of the chat area wide, and 10/80
         * is 12.5% - which is how far out the scrim has to reach to span
         * the full width. The phone rule below matches its own 16px.
         */
        .floating-input-wrapper::before {
          content: '';
          position: absolute;
          left: -12.5%;
          right: -12.5%;
          top: -44px;
          bottom: -24px;
          background: linear-gradient(
            to bottom,
            transparent,
            var(--bg-app) 44px
          );
          pointer-events: none;
          z-index: -1;
        }

        @media (max-width: 1024px) {
          .floating-input-wrapper::before {
            left: -16px;
            right: -16px;
            bottom: calc(-16px - env(safe-area-inset-bottom, 0px));
          }
        }

        /* Nothing is scrolling underneath on the empty state - the composer
           is in the flow there, not floating over anything. */
        .chat-workspace-container.is-empty .floating-input-wrapper::before {
          display: none;
        }

        .floating-input-card {
          background: var(--bg-input);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-lg);
          padding: 14px 16px 10px 16px;
          box-shadow: var(--shadow-rim), var(--shadow-floating);
          display: flex;
          flex-direction: column;
          gap: 8px;
          transition: background-color 0.25s ease, border-color 0.2s ease;
        }

        .floating-input-card:focus-within {
          border-color: var(--accent-primary);
        }

        .attachments-chip-bar {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-bottom: 4px;
        }

        .att-chip {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: 6px;
          font-size: 0.775rem;
        }

        .att-chip-icon {
          color: var(--accent-primary);
        }

        .att-chip-remove {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          display: flex;
          align-items: center;
        }

        .att-chip-remove:hover {
          color: var(--danger);
        }

        .recording-banner {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.775rem;
          color: var(--danger);
          background: var(--danger-bg);
          padding: 4px 10px;
          border-radius: 6px;
        }

        .rec-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--danger);
        }

        .chat-textarea {
          width: 100%;
          border: none;
          background: transparent;
          outline: none;
          resize: none;
          font-size: 0.925rem;
          color: var(--text-primary);
          max-height: 120px;
          line-height: 1.4;
        }

        .chat-textarea::placeholder {
          color: var(--text-muted);
        }

        .input-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }

        @media (max-width: 560px) {
          /* The heading is sized for a desktop hero; at this width it wraps
             onto three lines and pushes the composer off the screen. */
          .empty-chat-state h2 { font-size: 1.3rem; }

          /* Keep the send button reachable: the agent name is the thing
             that gives up room, not the controls either side of it. */
          .model-selector-btn { max-width: 130px; }
          .model-selector-btn span {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }

          .toolbar-left { gap: 4px; }
        }

        .toolbar-left {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .toolbar-btn {
          width: 32px;
          height: 32px;
          border-radius: 8px;
          background: transparent;
          border: none;
          color: var(--text-muted);
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .toolbar-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .model-selector-wrapper {
          position: relative;
        }

        .model-selector-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: 999px;
          font-size: 0.775rem;
          font-weight: 500;
          color: var(--text-secondary);
          cursor: pointer;
        }

        .model-selector-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .model-dropdown-menu {
          position: absolute;
          bottom: 100%;
          left: 0;
          margin-bottom: 8px;
          width: 220px;
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
          padding: 6px;
          z-index: 60;
        }

        .model-option {
          width: 100%;
          padding: 6px 10px;
          background: transparent;
          border: none;
          border-radius: 4px;
          font-size: 0.775rem;
          color: var(--text-secondary);
          text-align: left;
          cursor: pointer;
        }

        .model-option:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .model-option.active {
          background: var(--bg-active);
          color: var(--accent-primary);
          font-weight: 600;
        }

        .toolbar-right {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .send-message-btn {
          width: 36px;
          height: 36px;
          border-radius: var(--radius-md);
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border: none;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .send-message-btn:hover:not(:disabled) {
          background: var(--accent-primary-hover);
          transform: translateY(-1px);
          box-shadow: var(--shadow-md);
        }

        .send-message-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
};
