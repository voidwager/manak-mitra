import React, { useState } from 'react';
import { useApp } from '../state/AppContext';
import {
  History,
  Search,
  MessageSquare,
  Clock,
  ArrowRight
} from 'lucide-react';

export const HistoryPage = () => {
  const { conversations, loadConversation, handleNewChat } = useApp();
  const [searchQuery, setSearchQuery] = useState('');

  const filteredConvs = conversations.filter(c => 
    c.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.messages.some(m => m.text.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Conversation History</h1>
          <p className="page-subtitle">Previous industrial diagnostic sessions, SOP lookups, and equipment audits.</p>
        </div>
        <button className="primary-btn" onClick={handleNewChat}>
          <span>+ New Conversation</span>
        </button>
      </div>

      {/* Search Bar */}
      <div className="history-search-bar">
        <Search size={16} className="search-icon" />
        <input 
          type="text" 
          placeholder="Filter conversation history by keyword..." 
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* History Cards List */}
      <div className="history-list">
        {filteredConvs.length === 0 ? (
          <div className="empty-history-state">
            <History size={36} className="text-muted" />
            <p>No conversation history records found.</p>
          </div>
        ) : (
          filteredConvs.map(conv => {
            const msgCount = conv.messages?.length || 0;
            const lastMsg = conv.messages[conv.messages.length - 1];

            return (
              <div 
                key={conv.id} 
                className="history-card subtle-card"
                onClick={() => loadConversation(conv.id)}
              >
                <div className="history-card-icon">
                  <MessageSquare size={20} />
                </div>

                <div className="history-card-body">
                  <div className="history-title-row">
                    <h3 className="history-title">{conv.title}</h3>
                    <span className="history-time-badge">
                      <Clock size={12} />
                      {conv.createdAt ? new Date(conv.createdAt).toLocaleDateString() : 'Today'}
                    </span>
                  </div>

                  <p className="history-preview">
                    {lastMsg ? lastMsg.text.slice(0, 120) + '...' : 'Empty conversation session'}
                  </p>

                  <div className="history-meta-row">
                    <span className="agent-badge">{conv.agentName || 'Maintenance Assistant'}</span>
                    <span className="msg-count">{msgCount} message{msgCount !== 1 ? 's' : ''}</span>
                  </div>
                </div>

                <div className="history-action-col">
                  <button className="open-history-btn">
                    <span>Open</span>
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      <style>{`
        @media (max-width: 768px) {
          .page-container { padding: 18px 16px 28px; }
          .page-title { font-size: 1.25rem; }
        }

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
          margin-bottom: 24px;
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

        .primary-btn {
          padding: 10px 18px;
          background-color: var(--accent-primary);
          color: var(--accent-contrast);
          border: none;
          border-radius: var(--radius-md);
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
        }

        .history-search-bar {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 16px;
          background: var(--bg-card);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          margin-bottom: 20px;
          max-width: 480px;
        }

        .history-search-bar input {
          border: none;
          background: transparent;
          outline: none;
          width: 100%;
          font-size: 0.875rem;
          color: var(--text-primary);
        }

        .history-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .history-card {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 18px 24px;
          border-radius: var(--radius-lg);
          background: var(--bg-card);
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .history-card:hover {
          border-color: var(--accent-primary);
          box-shadow: var(--shadow-md);
        }

        .history-card-icon {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .history-card-body {
          flex: 1;
        }

        .history-title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 4px;
        }

        .history-title {
          font-size: 1rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .history-time-badge {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .history-preview {
          font-size: 0.85rem;
          color: var(--text-secondary);
          margin-bottom: 8px;
          display: -webkit-box;
          -webkit-line-clamp: 1;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .history-meta-row {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .agent-badge {
          font-size: 0.725rem;
          font-weight: 600;
          padding: 2px 8px;
          background: var(--bg-card-subtle);
          border-radius: 4px;
          color: var(--accent-text);
        }

        .msg-count {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .open-history-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 14px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-primary);
          cursor: pointer;
        }

        .history-card:hover .open-history-btn {
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border-color: var(--accent-primary);
        }

        .empty-history-state {
          text-align: center;
          padding: 60px 20px;
          color: var(--text-muted);
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
        }
      `}</style>
    </div>
  );
};
