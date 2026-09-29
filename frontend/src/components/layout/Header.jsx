import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../state/AppContext';
import { ChatSettingsMenu } from '../chat/ChatSettingsMenu';
import { InferenceBadge } from './InferenceBadge';
import {
  Sparkles,
  Search,
  Bell,
  ChevronDown,
  Menu,
  Check,
  FileText
} from 'lucide-react';

/** Colour for the derived agent status. Never unconditionally green. */
const statusTone = (status) => {
  if (status === 'Ready') return 'ready';
  if (status === 'Limited') return 'limited';
  if (status === 'Retired') return 'retired';
  return 'unavailable';
};

export const Header = () => {
  const { 
    agents, 
    activeAgent, 
    selectAgent, 
    setActiveModal, 
    notifications, 
    markNotifRead, 
    unreadCount,
    setSidebarCollapsed
  } = useApp();

  // The picker offers SI-1 and nothing else. Listing the specialists here
  // asked the user to choose one before asking their question, which is
  // backwards - you cannot know which specialist you need until you know
  // what you are asking, and SI-1 makes that choice per question anyway.
  //
  // Specialists are still reachable: "Open Workspace" on the Agents page
  // pins a chat to one, and the per-chat menu overrides the model.
  const universalAgents = (agents ?? []).filter((a) => a.isUniversal);

  // Fall back to the full list if nothing is flagged universal, so a
  // deployment that has not seeded SI-1 still gets a usable picker rather
  // than an empty one.
  const baseAgents = universalAgents.length ? universalAgents : (agents ?? []);

  // A specialist opened from the Agents page stays visible while it is
  // active. Hiding the current selection would leave the header naming an
  // agent the menu claims is not selectable.
  const listedAgents =
    activeAgent && !baseAgents.some((a) => a.id === activeAgent.id)
      ? [...baseAgents, activeAgent]
      : baseAgents;

  const [agentDropdownOpen, setAgentDropdownOpen] = useState(false);
  const [notifDropdownOpen, setNotifDropdownOpen] = useState(false);

  const agentRef = useRef(null);
  const notifRef = useRef(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (agentRef.current && !agentRef.current.contains(e.target)) {
        setAgentDropdownOpen(false);
      }
      if (notifRef.current && !notifRef.current.contains(e.target)) {
        setNotifDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="main-header">
      {/* Mobile Toggle Button */}
      <button 
        className="mobile-menu-trigger" 
        onClick={() => setSidebarCollapsed(true)}
      >
        <Menu size={20} />
      </button>

      {/* Left: Agent Selection Selector Pill */}
      <div className="agent-selector-wrapper" ref={agentRef}>
        <button 
          className="agent-selector-pill"
          onClick={() => setAgentDropdownOpen(!agentDropdownOpen)}
        >
          <div className="agent-icon-badge">
            <Sparkles size={14} />
          </div>
          <div className="agent-pill-info">
            <span className="agent-pill-title">{activeAgent?.name || 'Manak Mitra'}</span>
            {/*
              * The server derives this per request from whether a model is
              * configured and whether the agent's tools can run. It used to
              * be a hardcoded "Online", which stayed green while nothing
              * worked.
              */}
            <div
              className={`agent-pill-status ${statusTone(activeAgent?.status)}`}
              title={activeAgent?.statusDetail || ''}
            >
              <span className="status-dot" />
              <span>{activeAgent?.status || 'Unknown'}</span>
            </div>
          </div>
          <ChevronDown size={15} className={`chevron-icon ${agentDropdownOpen ? 'open' : ''}`} />
        </button>

        {agentDropdownOpen && (
          <div className="agent-dropdown-panel animate-fade-in">
            <div className="dropdown-label">Assistant</div>
            {listedAgents.map(agent => (
              <button
                key={agent.id}
                className={`agent-dropdown-item ${activeAgent?.id === agent.id ? 'selected' : ''}`}
                onClick={() => {
                  selectAgent(agent.id);
                  setAgentDropdownOpen(false);
                }}
              >
                <div className="item-icon-circle">
                  <Sparkles size={14} />
                </div>
                <div className="item-details">
                  <div className="item-name">
                    {agent.name}
                    {agent.isUniversal && (
                      <span className="item-badge">Recommended</span>
                    )}
                  </div>
                  <div className="item-desc">{agent.description}</div>
                </div>
                {activeAgent?.id === agent.id && <Check size={16} className="check-icon" />}
              </button>
            ))}
            <div className="dropdown-note">
              SI-1 engages a specialist per question. To pin a chat to one
              directly, open it from Agents.
            </div>
          </div>
        )}
      </div>

      {/* Right Controls: Search Bar & Notification Bell */}
      <div className="header-right-controls">
        {/* Per-chat settings, including which model answers this thread. */}
        <ChatSettingsMenu />

        {/* Where inference runs. Always visible, never overstated. */}
        <InferenceBadge />

        {/* Global Search Button */}
        <button 
          className="header-search-bar"
          onClick={() => setActiveModal({ type: 'search' })}
        >
          <Search size={15} className="search-icon" />
          <span className="search-placeholder">Search...</span>
          <kbd className="search-kbd">⌘K</kbd>
        </button>

        {/* Notifications Button & Dropdown */}
        <div className="notif-wrapper" ref={notifRef}>
          <button 
            className="header-icon-btn"
            onClick={() => setNotifDropdownOpen(!notifDropdownOpen)}
            title="Notifications"
          >
            <Bell size={18} />
            {unreadCount > 0 && <span className="notif-badge-dot" />}
          </button>

          {notifDropdownOpen && (
            <div className="notif-dropdown-panel animate-fade-in">
              <div className="notif-header">
                <span className="notif-title">Notifications</span>
                {unreadCount > 0 && (
                  <span className="unread-count-pill">{unreadCount} new</span>
                )}
              </div>
              <div className="notif-list">
                {notifications.length === 0 ? (
                  <div className="notif-empty">No new notifications</div>
                ) : (
                  notifications.map(n => (
                    <div 
                      key={n.id} 
                      className={`notif-item ${n.read ? 'read' : 'unread'}`}
                      onClick={() => markNotifRead(n.id)}
                    >
                      <div className="notif-item-icon">
                        <FileText size={14} />
                      </div>
                      <div className="notif-item-content">
                        <div className="notif-item-title">{n.title}</div>
                        <div className="notif-item-desc">{n.description}</div>
                        <div className="notif-item-time">{n.time}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .main-header {
          height: 64px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 24px;
          border-bottom: 1px solid var(--border-light);
          background-color: var(--bg-workspace);
          user-select: none;
        }

        .mobile-menu-trigger {
          display: none;
          background: transparent;
          border: none;
          color: var(--text-primary);
          cursor: pointer;
          margin-right: 12px;
        }

        .agent-selector-wrapper {
          position: relative;
        }

        .agent-selector-pill {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 6px 14px 6px 10px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: 999px;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .agent-selector-pill:hover {
          background: var(--bg-hover);
          border-color: var(--border-subtle);
        }

        .agent-icon-badge {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .agent-pill-info {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          line-height: 1.2;
        }

        .agent-pill-title {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .agent-pill-status {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.7rem;
          color: var(--text-muted);
        }

        .agent-pill-status.ready { color: var(--success); }
        .agent-pill-status.limited { color: var(--warning); }
        .agent-pill-status.unavailable { color: var(--danger); }
        .agent-pill-status.retired { color: var(--text-muted); }

        .agent-pill-status .status-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background-color: currentColor;
        }

        .item-badge {
          margin-left: 7px;
          padding: 1px 6px;
          border-radius: 999px;
          background: var(--accent-light);
          color: var(--accent-text);
          font-size: 0.62rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }

        .online-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background-color: var(--success);
          display: inline-block;
        }

        .chevron-icon {
          color: var(--text-muted);
          transition: transform 0.2s ease;
        }

        .chevron-icon.open {
          transform: rotate(180deg);
        }

        .agent-dropdown-panel {
          position: absolute;
          top: 100%;
          left: 0;
          margin-top: 8px;
          /* Never wider than the screen it drops out of. */
          width: min(320px, calc(100vw - 24px));
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
          padding: 8px;
          z-index: 60;
        }

        .dropdown-note {
          padding: 10px 12px 4px;
          margin-top: 4px;
          border-top: 1px solid var(--border-light);
          font-size: 0.72rem;
          line-height: 1.45;
          color: var(--text-muted);
        }

        .dropdown-label {
          font-size: 0.725rem;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--text-muted);
          padding: 6px 8px;
        }

        .agent-dropdown-item {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px;
          background: transparent;
          border: none;
          border-radius: var(--radius-sm);
          cursor: pointer;
          text-align: left;
          transition: background 0.15s ease;
        }

        .agent-dropdown-item:hover {
          background: var(--bg-hover);
        }

        .agent-dropdown-item.selected {
          background: var(--bg-active);
        }

        .item-icon-circle {
          width: 30px;
          height: 30px;
          border-radius: 50%;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .item-details {
          flex: 1;
        }

        .item-name {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .item-desc {
          font-size: 0.75rem;
          color: var(--text-muted);
          display: -webkit-box;
          -webkit-line-clamp: 1;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .check-icon {
          color: var(--accent-primary);
        }

        .header-right-controls {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .header-search-bar {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 14px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: 999px;
          color: var(--text-muted);
          font-size: 0.85rem;
          cursor: pointer;
          transition: all 0.15s ease;
          width: 200px;
        }

        .header-search-bar:hover {
          background: var(--bg-hover);
          border-color: var(--border-subtle);
          color: var(--text-primary);
        }

        .search-placeholder {
          flex: 1;
          text-align: left;
        }

        .search-kbd {
          font-size: 0.7rem;
          padding: 2px 6px;
          border-radius: 4px;
          background: var(--bg-hover);
          border: 1px solid var(--border-light);
          color: var(--text-muted);
        }

        .notif-wrapper {
          position: relative;
        }

        .header-icon-btn {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text-secondary);
          cursor: pointer;
          position: relative;
          transition: all 0.15s ease;
        }

        .header-icon-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .notif-badge-dot {
          position: absolute;
          top: 8px;
          right: 8px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--accent-primary);
          border: 2px solid var(--bg-card);
        }

        .notif-dropdown-panel {
          position: absolute;
          top: 100%;
          right: 0;
          margin-top: 8px;
          /* Never wider than the screen it drops out of. */
          width: min(320px, calc(100vw - 24px));
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
          padding: 12px;
          z-index: 60;
        }

        .notif-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--border-light);
        }

        .notif-title {
          font-weight: 600;
          font-size: 0.875rem;
        }

        .unread-count-pill {
          font-size: 0.7rem;
          padding: 2px 8px;
          border-radius: 999px;
          background: var(--accent-light);
          color: var(--accent-text);
          font-weight: 600;
        }

        .notif-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 280px;
          overflow-y: auto;
        }

        .notif-empty {
          font-size: 0.8rem;
          color: var(--text-muted);
          text-align: center;
          padding: 16px 0;
        }

        .notif-item {
          display: flex;
          gap: 10px;
          padding: 8px;
          border-radius: var(--radius-sm);
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .notif-item:hover {
          background: var(--bg-hover);
        }

        .notif-item.unread {
          background: var(--accent-light);
        }

        .notif-item-icon {
          color: var(--accent-primary);
          margin-top: 2px;
        }

        .notif-item-content {
          flex: 1;
        }

        .notif-item-title {
          font-size: 0.8rem;
          font-weight: 600;
        }

        .notif-item-desc {
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .notif-item-time {
          font-size: 0.7rem;
          color: var(--text-muted);
          margin-top: 2px;
        }

        @media (max-width: 768px) {
          .mobile-menu-trigger {
            display: flex;
          }

          /* The search field is the first thing to give up room: the agent
             pill and the provenance badge both carry information the search
             box does not. */
          .header-search-bar {
            width: 110px;
          }

          .header-right-controls { gap: 6px; }

          .agent-pill-title {
            max-width: 96px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }

        }

        @media (max-width: 460px) {
          /* Below this the search box cannot hold a useful query anyway,
             and the shortcut hint it renders is meaningless on a phone. */
          .header-search-bar { display: none; }
        }
      `}</style>
    </header>
  );
};
