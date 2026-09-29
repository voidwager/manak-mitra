import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '../../state/AppContext';
import { Search, X, MessageSquare, Bot, FileText, Wrench, ArrowRight } from 'lucide-react';

export const SearchModal = ({ onClose }) => {
  const { conversations, agents, documents, tools, loadConversation, selectAgent, setActiveTab, openDocPreview } = useApp();
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Search logic across conversations, agents, documents, and tools
  const lower = query.toLowerCase();

  const matchingConvs = query ? conversations.filter(c => 
    c.title.toLowerCase().includes(lower) || 
    c.messages.some(m => m.text.toLowerCase().includes(lower))
  ) : [];

  const matchingAgents = query ? agents.filter(a => 
    a.name.toLowerCase().includes(lower) || 
    a.description.toLowerCase().includes(lower)
  ) : [];

  const matchingDocs = query ? documents.filter(d => 
    d.name.toLowerCase().includes(lower) || 
    d.excerpt.toLowerCase().includes(lower)
  ) : [];

  const matchingTools = query ? tools.filter(t => 
    t.name.toLowerCase().includes(lower) || 
    t.description.toLowerCase().includes(lower)
  ) : [];

  const hasResults = matchingConvs.length > 0 || matchingAgents.length > 0 || matchingDocs.length > 0 || matchingTools.length > 0;

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card search-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Command Search Input Bar */}
        <div className="search-input-header">
          <Search size={18} className="search-icon" />
          <input 
            ref={inputRef}
            type="text" 
            placeholder="Search conversations, agents, documents, and tools..." 
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button className="clear-btn" onClick={() => setQuery('')}>
              <X size={16} />
            </button>
          )}
        </div>

        {/* Results Body */}
        <div className="search-results-body">
          {!query ? (
            <div className="search-hint-state">
              <p>Type keywords to search across sovereign workspace index.</p>
              <div className="quick-tags">
                <button onClick={() => setQuery('Pump')}>"Pump"</button>
                <button onClick={() => setQuery('Inspection')}>"Inspection"</button>
                <button onClick={() => setQuery('SOP')}>"SOP"</button>
                <button onClick={() => setQuery('Compressor')}>"Compressor"</button>
              </div>
            </div>
          ) : !hasResults ? (
            <div className="no-results-state">
              <p>No matching items found for "{query}".</p>
            </div>
          ) : (
            <div className="results-groups">
              {/* Conversations */}
              {matchingConvs.length > 0 && (
                <div className="result-group">
                  <div className="group-label">Conversations ({matchingConvs.length})</div>
                  {matchingConvs.map(c => (
                    <button 
                      key={c.id} 
                      className="result-item"
                      onClick={() => {
                        loadConversation(c.id);
                        onClose();
                      }}
                    >
                      <MessageSquare size={16} className="item-icon" />
                      <div className="item-text-info">
                        <span className="item-title">{c.title}</span>
                        <span className="item-sub">{c.messages[0]?.text.slice(0, 60)}...</span>
                      </div>
                      <ArrowRight size={14} className="hover-arrow" />
                    </button>
                  ))}
                </div>
              )}

              {/* Agents */}
              {matchingAgents.length > 0 && (
                <div className="result-group">
                  <div className="group-label">Agents ({matchingAgents.length})</div>
                  {matchingAgents.map(a => (
                    <button 
                      key={a.id} 
                      className="result-item"
                      onClick={() => {
                        selectAgent(a.id);
                        setActiveTab('chat');
                        onClose();
                      }}
                    >
                      <Bot size={16} className="item-icon" />
                      <div className="item-text-info">
                        <span className="item-title">{a.name}</span>
                        <span className="item-sub">{a.description}</span>
                      </div>
                      <ArrowRight size={14} className="hover-arrow" />
                    </button>
                  ))}
                </div>
              )}

              {/* Documents */}
              {matchingDocs.length > 0 && (
                <div className="result-group">
                  <div className="group-label">Documents ({matchingDocs.length})</div>
                  {matchingDocs.map(d => (
                    <button 
                      key={d.id} 
                      className="result-item"
                      onClick={() => {
                        openDocPreview(d);
                        onClose();
                      }}
                    >
                      <FileText size={16} className="item-icon" />
                      <div className="item-text-info">
                        <span className="item-title">{d.name}</span>
                        <span className="item-sub">{d.size} · {d.status}</span>
                      </div>
                      <ArrowRight size={14} className="hover-arrow" />
                    </button>
                  ))}
                </div>
              )}

              {/* Tools */}
              {matchingTools.length > 0 && (
                <div className="result-group">
                  <div className="group-label">Tools ({matchingTools.length})</div>
                  {matchingTools.map(t => (
                    <button 
                      key={t.id} 
                      className="result-item"
                      onClick={() => {
                        setActiveTab('tools');
                        onClose();
                      }}
                    >
                      <Wrench size={16} className="item-icon" />
                      <div className="item-text-info">
                        <span className="item-title">{t.name}</span>
                        <span className="item-sub">{t.description}</span>
                      </div>
                      <ArrowRight size={14} className="hover-arrow" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <style>{`
          .modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.45);
            backdrop-filter: blur(6px);
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding-top: 80px;
            z-index: 100;
          }

          .search-modal-card {
            width: 100%;
            max-width: 600px;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-rim), var(--shadow-lg);
            overflow: hidden;
          }

          .search-input-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-light);
          }

          .search-icon {
            color: var(--text-muted);
          }

          .search-input-header input {
            flex: 1;
            border: none;
            background: transparent;
            outline: none;
            font-size: 1rem;
            color: var(--text-primary);
          }

          .clear-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
          }

          .search-results-body {
            max-height: 380px;
            overflow-y: auto;
            padding: 16px 20px;
          }

          .search-hint-state {
            text-align: center;
            padding: 20px;
            font-size: 0.85rem;
            color: var(--text-muted);
          }

          .quick-tags {
            display: flex;
            justify-content: center;
            gap: 8px;
            margin-top: 12px;
          }

          .quick-tags button {
            padding: 4px 10px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-light);
            border-radius: 999px;
            font-size: 0.775rem;
            color: var(--text-secondary);
            cursor: pointer;
          }

          .no-results-state {
            text-align: center;
            padding: 30px;
            color: var(--text-muted);
            font-size: 0.875rem;
          }

          .results-groups {
            display: flex;
            flex-direction: column;
            gap: 16px;
          }

          .group-label {
            font-size: 0.725rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 6px;
          }

          .result-item {
            width: 100%;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            background: transparent;
            border: none;
            border-radius: var(--radius-md);
            text-align: left;
            cursor: pointer;
            transition: background 0.15s ease;
          }

          .result-item:hover {
            background: var(--bg-hover);
          }

          .item-icon {
            color: var(--accent-primary);
          }

          .item-text-info {
            flex: 1;
            display: flex;
            flex-direction: column;
          }

          .item-title {
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-primary);
          }

          .item-sub {
            font-size: 0.75rem;
            color: var(--text-muted);
          }

          .hover-arrow {
            color: var(--text-muted);
            opacity: 0;
            transition: opacity 0.15s ease;
          }

          .result-item:hover .hover-arrow {
            opacity: 1;
          }
        `}</style>
      </div>
    </div>
  );
};
