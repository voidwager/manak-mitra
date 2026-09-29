import React from 'react';
import { useApp } from '../../state/AppContext';
import { X, ShieldCheck, Mail, Building, Key, FolderLock } from 'lucide-react';

export const UserProfileModal = ({ onClose }) => {
  const { currentUser } = useApp();

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card profile-modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">User Profile & Security Scope</h3>
          <button className="close-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <div className="profile-hero">
            <div 
              className="hero-avatar"
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
            <div className="hero-info">
              <h3 className="hero-name">{currentUser?.name || 'Sanyam Jain'}</h3>
              <p className="hero-role">{currentUser?.role || 'Helpdesk staff'}</p>
              <div className="hero-badge">
                <ShieldCheck size={14} />
                <span>{currentUser?.accessLevel === 'OWNER' ? 'Owner Clearance · Full RAG Scope' : 'Employee Clearance · Restricted Scope'}</span>
              </div>
            </div>
          </div>

          <div className="details-list">
            <div className="detail-row">
              <Mail size={16} className="detail-icon" />
              <div className="detail-text">
                <span className="detail-label">Email Address</span>
                <span className="detail-val">
                  {currentUser?.email || ''}
                </span>
              </div>
            </div>

            <div className="detail-row">
              <Building size={16} className="detail-icon" />
              <div className="detail-text">
                <span className="detail-label">RAG Access Level</span>
                <span className="detail-val">{currentUser?.scopeLabel}</span>
              </div>
            </div>

            <div className="detail-row">
              <FolderLock size={16} className="detail-icon" />
              <div className="detail-text">
                <span className="detail-label">Authorized Folders & Units</span>
                <span className="detail-val">
                  {currentUser?.assignedFolders?.join(' · ')}
                </span>
              </div>
            </div>

            {/*
              * There was an "On-Premise Auth Token" row here showing
              * mrpl-sov-token-94827103847. It was invented - no such token
              * has ever existed - and it described the deployment as
              * on-premise while /api/health reported the opposite two
              * screens away.
              *
              * It is not replaced with the real session token either. That
              * token is a live credential: printing it on a profile page
              * puts it in every screenshot and over every shoulder, and
              * nobody needs to read their own session id.
              *
              * What is shown instead is true and not a secret.
              */}
            <div className="detail-row">
              <Key size={16} className="detail-icon" />
              <div className="detail-text">
                <span className="detail-label">Session</span>
                <span className="detail-val">
                  Signed in. Revoked on sign-out, and verified by the server
                  on every request.
                </span>
              </div>
            </div>
          </div>
        </div>

        <style>{`
          .modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.45);
            backdrop-filter: blur(6px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            padding: 20px;
          }

          .profile-modal-card {
          /* Bounded by the viewport and scrolled internally. Without
             this a form taller than the screen - which is most of them on a
             phone - overflows a centred flex backdrop in both directions,
             putting the heading above the top of the screen where it cannot
             be scrolled to. */
          max-height: calc(100vh - 40px);
          max-height: calc(100dvh - 40px);
          overflow-y: auto;
            width: 100%;
            max-width: 500px;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-rim), var(--shadow-lg);
            overflow: hidden;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-light);
          }

          .modal-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
          }

          .modal-body {
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
          }

          .profile-hero {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 16px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-light);
            border-radius: var(--radius-lg);
          }

          .hero-avatar {
            width: 52px;
            height: 52px;
            border-radius: 50%;
            color: #FFFFFF;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            font-weight: 700;
          }

          .hero-info {
            display: flex;
            flex-direction: column;
          }

          .hero-name {
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .hero-role {
            font-size: 0.825rem;
            color: var(--text-secondary);
          }

          .hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-size: 0.725rem;
            font-weight: 600;
            color: var(--success);
            margin-top: 4px;
          }

          .details-list {
            display: flex;
            flex-direction: column;
            gap: 14px;
          }

          .detail-row {
            display: flex;
            align-items: flex-start;
            gap: 12px;
          }

          .detail-icon {
            color: var(--accent-primary);
            margin-top: 2px;
          }

          .detail-text {
            display: flex;
            flex-direction: column;
          }

          .detail-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 600;
          }

          .detail-val {
            font-size: 0.875rem;
            color: var(--text-primary);
            font-weight: 500;
          }
        `}</style>
      </div>
    </div>
  );
};
