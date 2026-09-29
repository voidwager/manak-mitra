import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../state/AppContext';
import { SynqBrand, useBrandVariant } from './SynqBrand';
import {
  BarChart3,
  ChevronDown,
  ExternalLink,
  FileText,
  History,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  Pin,
  PinOff,
  Plus,
  Sliders,
  Trash2,
  User,
  Users,
  Wrench,
  X,
} from 'lucide-react';

export const Sidebar = () => {
  const { 
    currentUser,
    logout,
    activeTab, 
    setActiveTab, 
    handleNewChat, 
    conversations,
    activeConversationId,
    loadConversation,
    toggleConversationPin,
    deleteConversation,
    sidebarCollapsed, 
    setSidebarCollapsed,
    setActiveModal
  } = useApp();

  /*
   * Which brand mark to draw - the wordmark alone, or the lockup with the
   * tagline. Both are traced from the brand artwork and filled white; the
   * light theme inverts them in CSS, because currentColor cannot cross an
   * <img> boundary and reach into the file. See .brand-logo below.
   *
   * The choice lives in localStorage and is shared with the picker in
   * Settings; SynqBrand owns both ends of that.
   */
  const [brandVariant] = useBrandVariant();

  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef(null);

  // Which conversation's "..." menu is open, and the row awaiting delete
  // confirmation. Deleting a thread is not undoable, so it asks first.
  const [menuOpenFor, setMenuOpenFor] = useState(null);
  const [confirmDeleteFor, setConfirmDeleteFor] = useState(null);
  const historyRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false);
      }
      if (historyRef.current && !historyRef.current.contains(e.target)) {
        setMenuOpenFor(null);
        setConfirmDeleteFor(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const onEscape = (e) => {
      if (e.key !== 'Escape') return;
      setMenuOpenFor(null);
      setConfirmDeleteFor(null);
    };
    document.addEventListener('keydown', onEscape);
    return () => document.removeEventListener('keydown', onEscape);
  }, []);

  // Performance is administrator-only, so it is filtered out rather than
  // shown disabled: an item that is visible but refuses to open reads as a
  // fault, and there is nothing here for a non-administrator to act on.
  const mainNavItems = [
    { id: 'chat', label: 'Chat', icon: MessageSquare },
    { id: 'agents', label: 'Agents', icon: Users },
    { id: 'documents', label: 'Documents', icon: FileText },
    { id: 'tools', label: 'Tools', icon: Wrench },
    ...(currentUser?.accessLevel === 'OWNER'
      ? [{ id: 'performance', label: 'Performance', icon: BarChart3 }]
      : []),
  ];

  const handleNavClick = (tabId) => {
    setActiveTab(tabId);
    setSidebarCollapsed(false);
  };

  return (
    <>
      {sidebarCollapsed && (
        <div 
          className="mobile-overlay" 
          onClick={() => setSidebarCollapsed(false)}
        />
      )}

      <aside className={`sidebar-container ${sidebarCollapsed ? 'mobile-open' : ''}`}>
        {/* Top Logo & Branding */}
        <div className="sidebar-header">
          {/*
            * Each variant carries its own height, because the lockup is not
            * the wordmark plus a line - the tagline is set small enough that
            * matching the wordmark's height would reduce it to a smudge. See
            * SynqBrand for the numbers.
            */}
          <div className="brand-title-group">
            <SynqBrand variant={brandVariant} />
          </div>
          <button 
            className="brand-action-btn"
            onClick={handleNewChat}
            title="Open workbench in new view"
          >
            <ExternalLink size={16} />
          </button>
          
          <button 
            className="mobile-close-btn"
            onClick={() => setSidebarCollapsed(false)}
          >
            <X size={18} />
          </button>
        </div>

        {/* Action Button: + New Chat */}
        <div className="new-chat-container">
          <button 
            className="new-chat-btn"
            onClick={() => {
              handleNewChat();
              setSidebarCollapsed(false);
            }}
          >
            <Plus size={18} />
            <span>New Chat</span>
          </button>
        </div>

        {/* Main Navigation List (History removed from tabs) */}
        <nav className="sidebar-nav">
          {mainNavItems.map(item => {
            const IconComponent = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                className={`nav-item-btn ${isActive ? 'active' : ''}`}
                onClick={() => handleNavClick(item.id)}
              >
                <IconComponent size={18} className="nav-icon" />
                <span className="nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Embedded Chat History List Directly inside Sidebar */}
        <div className="sidebar-history-section">
          <div className="history-section-header">
            <History size={13} className="text-muted" />
            <span>Recent Chats</span>
          </div>

          <div className="sidebar-history-list" ref={historyRef}>
            {conversations.length === 0 ? (
              <div className="empty-history-text">No recent chats</div>
            ) : (
              conversations.map(conv => {
                const isActive = activeTab === 'chat' && activeConversationId === conv.id;
                const menuOpen = menuOpenFor === conv.id;
                const confirming = confirmDeleteFor === conv.id;

                return (
                  <div
                    key={conv.id}
                    className={`history-row ${isActive ? 'active' : ''} ${menuOpen ? 'menu-open' : ''}`}
                  >
                    <button
                      className="sidebar-history-item"
                      onClick={() => {
                        loadConversation(conv.id);
                        setSidebarCollapsed(false);
                      }}
                    >
                      {conv.pinned ? (
                        <Pin size={13} className="history-item-icon pinned" />
                      ) : (
                        <MessageSquare size={14} className="history-item-icon" />
                      )}
                      <span className="history-item-title">{conv.title}</span>
                    </button>

                    <button
                      className="history-menu-trigger"
                      aria-label="Conversation options"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteFor(null);
                        setMenuOpenFor(menuOpen ? null : conv.id);
                      }}
                    >
                      <MoreHorizontal size={15} />
                    </button>

                    {menuOpen && (
                      <div className="history-menu animate-fade-in">
                        {confirming ? (
                          <>
                            <div className="history-menu-confirm">Delete this chat?</div>
                            <button
                              className="history-menu-item danger"
                              onClick={() => {
                                deleteConversation(conv.id);
                                setMenuOpenFor(null);
                                setConfirmDeleteFor(null);
                              }}
                            >
                              <Trash2 size={14} />
                              <span>Yes, delete</span>
                            </button>
                            <button
                              className="history-menu-item"
                              onClick={() => setConfirmDeleteFor(null)}
                            >
                              <span>Cancel</span>
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              className="history-menu-item"
                              onClick={() => {
                                toggleConversationPin(conv.id);
                                setMenuOpenFor(null);
                              }}
                            >
                              {conv.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                              <span>{conv.pinned ? 'Unpin' : 'Pin'}</span>
                            </button>
                            <button
                              className="history-menu-item danger"
                              onClick={() => setConfirmDeleteFor(conv.id)}
                            >
                              <Trash2 size={14} />
                              <span>Delete</span>
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* User Profile & Settings Section at Bottom Left */}
        <div className="sidebar-footer" ref={profileRef}>
          {profileOpen && (
            <div className="profile-dropdown-menu animate-fade-in">
              <div className="profile-user-summary">
                <span className="summary-name">{currentUser?.name}</span>
                <span className="summary-role">{currentUser?.role}</span>
                <span className="summary-scope">{currentUser?.accessLevel === 'OWNER' ? '👑 Owner RAG Access' : '🔒 Restricted RAG Scope'}</span>
              </div>
              <div className="menu-divider" />
              <button 
                className="profile-menu-item"
                onClick={() => {
                  setProfileOpen(false);
                  setActiveModal({ type: 'profile' });
                }}
              >
                <User size={15} />
                <span>Profile & Security</span>
              </button>
              <button 
                className="profile-menu-item"
                onClick={() => {
                  setProfileOpen(false);
                  setActiveTab('settings');
                }}
              >
                <Sliders size={15} />
                <span>Settings & Preferences</span>
              </button>
              <div className="menu-divider" />
              <button 
                className="profile-menu-item text-danger"
                onClick={() => {
                  setProfileOpen(false);
                  logout();
                }}
              >
                <LogOut size={15} />
                <span>Sign Out / Switch User</span>
              </button>
            </div>
          )}

          <button 
            className="user-profile-card"
            onClick={() => setProfileOpen(!profileOpen)}
          >
            <div 
              className="user-avatar"
              /*
              * A fixed gradient, not the accent. The initials on top are
              * white, and the accent is white on the dark theme - so the
              * fallback used to render white on white for any account
              * without a gradient of its own. A real colour here keeps
              * the one hardcoded white in this file correct.
              */
              style={{ background: currentUser?.avatarGradient || 'linear-gradient(135deg, #4B4B57, #2E2E38)' }}
            >
              <span>{currentUser?.initials || 'SJ'}</span>
            </div>
            <div className="user-info">
              <span className="user-name">{currentUser?.name || 'Sanyam Jain'}</span>
              <span className="user-role">{currentUser?.role || 'Owner / Admin'}</span>
            </div>
            <ChevronDown size={16} className={`profile-chevron ${profileOpen ? 'open' : ''}`} />
          </button>
        </div>
      </aside>

      <style>{`
        .mobile-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.4);
          backdrop-filter: blur(4px);
          z-index: 40;
        }

        .sidebar-container {
          width: 260px;
          height: 100vh;
          height: 100dvh;
          background-color: var(--bg-sidebar);
          border-right: 1px solid var(--border-light);
          display: flex;
          flex-direction: column;
          padding: 20px 16px;
          user-select: none;
          z-index: 50;
          transition: transform 0.25s ease, background-color 0.25s ease;
        }

        .sidebar-header {
          display: flex;
          /* Centred, not top-aligned: the two variants are different
             heights, and flex-start left the buttons hanging off the top of
             the taller one. */
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          min-height: 46px;
          padding: 4px 8px 16px 8px;
        }

        /* One item now that the subtitle is gone, so it just centres the
           mark rather than stacking two lines. */
        .brand-title-group {
          display: flex;
          align-items: center;
          min-width: 0;
        }

        /*
         * Named "green" because it used to be. It is not any more: --success
         * means "this is working", and spending that colour on a wordmark
         * left the actual status pills competing with the logo for the same
         * meaning. The mark is now text-coloured, like the mark it stands in
         * for, which is white.
         */
        .brand-title-green {
          font-size: 1.2rem;
          font-weight: 800;
          color: var(--text-primary);
          letter-spacing: 0.02em;
          line-height: 1.1;
        }


        .brand-action-btn {
          background: transparent;
          border: 1px solid var(--border-light);
          border-radius: 8px;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text-muted);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .brand-action-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .mobile-close-btn {
          display: none;
          background: transparent;
          border: none;
          color: var(--text-secondary);
          cursor: pointer;
        }

        .new-chat-container {
          margin-bottom: 16px;
        }

        .new-chat-btn {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 16px;
          background-color: var(--accent-light);
          color: var(--accent-text);
          border: 1px solid color-mix(in srgb, var(--accent-primary) 15%, transparent);
          border-radius: var(--radius-md);
          font-weight: 600;
          font-size: 0.9rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .new-chat-btn:hover {
          background-color: var(--accent-primary);
          color: var(--accent-contrast);
          border-color: var(--accent-primary);
          box-shadow: var(--shadow-md);
        }

        .sidebar-nav {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin-bottom: 16px;
        }

        .nav-item-btn {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 9px 14px;
          background: transparent;
          border: none;
          border-radius: var(--radius-md);
          color: var(--text-secondary);
          font-size: 0.9rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s ease;
          text-align: left;
        }

        .nav-item-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .nav-item-btn.active {
          background: var(--bg-active);
          color: var(--accent-primary);
          font-weight: 600;
        }

        /* Sidebar Embedded Chat History */
        .sidebar-history-section {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          padding-top: 12px;
          border-top: 1px solid var(--border-light);
          margin-bottom: 12px;
        }

        .history-section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.725rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--text-muted);
          padding: 0 8px 8px 8px;
        }

        .sidebar-history-list {
          display: flex;
          flex-direction: column;
          gap: 2px;
          overflow-y: auto;
          overflow-x: hidden;
          flex: 1;
        }

        .empty-history-text {
          font-size: 0.775rem;
          color: var(--text-muted);
          padding: 8px;
          font-style: italic;
        }

        .history-row {
          position: relative;
          display: flex;
          align-items: center;
          border-radius: var(--radius-sm);
        }

        .history-row:hover,
        .history-row.menu-open {
          background-color: var(--bg-hover);
        }

        .history-row.active {
          background-color: var(--bg-active);
        }

        .history-menu-trigger {
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          width: 26px;
          height: 26px;
          margin-right: 4px;
          border: none;
          border-radius: 6px;
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
          opacity: 0;
          transition: opacity 0.15s ease, color 0.15s ease;
        }

        .history-row:hover .history-menu-trigger,
        .history-row.menu-open .history-menu-trigger,
        .history-menu-trigger:focus-visible {
          opacity: 1;
        }

        .history-menu-trigger:hover {
          color: var(--text-primary);
        }

        .history-menu {
          position: absolute;
          top: calc(100% - 4px);
          right: 4px;
          z-index: 40;
          min-width: 160px;
          padding: 5px;
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          background-color: var(--bg-card);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
        }

        .history-menu-confirm {
          padding: 7px 10px 5px;
          font-size: 0.75rem;
          font-weight: 600;
          color: var(--text-secondary);
        }

        .history-menu-item {
          display: flex;
          align-items: center;
          gap: 9px;
          width: 100%;
          padding: 7px 10px;
          border: none;
          border-radius: var(--radius-sm);
          background: transparent;
          color: var(--text-primary);
          font-size: 0.8125rem;
          text-align: left;
          cursor: pointer;
        }

        .history-menu-item:hover {
          background-color: var(--bg-hover);
        }

        .history-menu-item.danger {
          color: var(--danger);
        }

        .history-item-icon.pinned {
          color: var(--accent-primary);
        }

        .sidebar-history-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 7px 10px;
          background: transparent;
          border: none;
          border-radius: var(--radius-sm);
          color: var(--text-secondary);
          font-size: 0.825rem;
          cursor: pointer;
          text-align: left;
          transition: background 0.15s ease;
          flex: 1;
          min-width: 0;
        }

        .sidebar-history-item:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .sidebar-history-item.active {
          background: var(--bg-active);
          color: var(--accent-primary);
          font-weight: 600;
        }

        .history-item-icon {
          flex-shrink: 0;
          color: var(--text-muted);
        }

        .sidebar-history-item.active .history-item-icon {
          color: var(--accent-primary);
        }

        .history-item-title {
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .sidebar-footer {
          position: relative;
          padding-top: 12px;
          border-top: 1px solid var(--border-light);
        }

        .user-profile-card {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .user-profile-card:hover {
          background: var(--bg-hover);
          border-color: var(--border-subtle);
        }

        .user-avatar {
          width: 34px;
          height: 34px;
          border-radius: 50%;
          color: #FFFFFF;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 0.8rem;
          font-weight: 700;
          flex-shrink: 0;
        }

        .user-info {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          flex: 1;
          overflow: hidden;
        }

        .user-name {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
          white-space: nowrap;
          text-overflow: ellipsis;
          overflow: hidden;
          line-height: 1.2;
        }

        .user-role {
          font-size: 0.725rem;
          color: var(--text-muted);
          line-height: 1.2;
          white-space: nowrap;
          text-overflow: ellipsis;
          overflow: hidden;
        }

        .profile-chevron {
          color: var(--text-muted);
          transition: transform 0.2s ease;
        }

        .profile-chevron.open {
          transform: rotate(180deg);
        }

        .profile-dropdown-menu {
          position: absolute;
          bottom: 100%;
          left: 0;
          right: 0;
          margin-bottom: 8px;
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-rim), var(--shadow-lg);
          padding: 8px;
          z-index: 60;
        }

        .profile-user-summary {
          padding: 6px 8px;
          display: flex;
          flex-direction: column;
        }

        .summary-name {
          font-size: 0.85rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .summary-role {
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .summary-scope {
          font-size: 0.7rem;
          color: var(--success);
          font-weight: 600;
          margin-top: 2px;
        }

        .profile-menu-item {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 12px;
          background: transparent;
          border: none;
          border-radius: var(--radius-sm);
          font-size: 0.85rem;
          color: var(--text-secondary);
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .profile-menu-item:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }

        .profile-menu-item.text-danger:hover {
          background: var(--danger-bg);
          color: var(--danger);
        }

        .menu-divider {
          height: 1px;
          background: var(--border-light);
          margin: 4px 0;
        }

        @media (max-width: 768px) {
          .sidebar-container {
            position: fixed;
            top: 0;
            left: 0;
            bottom: 0;
            transform: translateX(-100%);
          }

          .sidebar-container.mobile-open {
            transform: translateX(0);
          }

          .mobile-close-btn {
            display: flex;
          }
        }
      `}</style>
    </>
  );
};
