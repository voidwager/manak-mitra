import React, { useEffect, useState } from 'react';
import { useApp } from '../../state/AppContext';
import { api } from '../../services/api';
import { ShieldCheck, Lock, User, ArrowRight, Sparkles, AlertCircle } from 'lucide-react';

/**
 * The password every seeded demo account carries in development, matching
 * `DEFAULT_DEMO_PASSWORD` in backend/app/database/seed.py.
 *
 * Only ever filled in when the server reports it is running in
 * development. Anywhere else the seed refuses to use this password at all,
 * so pre-filling it would offer a credential that cannot work - and, worse,
 * would print a password on the sign-in page of a deployed site.
 */
const DEV_DEMO_PASSWORD = 'demo1234';

export const LoginModal = () => {
  const { login, connectionError, retryConnection, health } = useApp();

  // The server's own answer, not a build flag: whoever deployed it decides,
  // and the browser cannot be wrong about someone else's environment.
  const isDevelopment = health?.environment === 'development';

  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Accounts come from the backend, not a hardcoded list in the bundle.
  useEffect(() => {
    let cancelled = false;
    api
      .getUsers()
      .then((list) => !cancelled && setUsers(list))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [connectionError]);

  const attempt = async (payload) => {
    setBusy(true);
    setError(null);
    try {
      await login(payload);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  /*
   * Picking a persona fills the form; it does not sign you in. The server
   * verifies a password either way - a card that logged you in as anyone
   * with one click would make the authentication decorative.
   *
   * The demo password is public because the whole dataset is fictional. A
   * deployment carrying real data has to change it, and the note below the
   * form says so.
   */
  const handlePersonaSelect = (userObj) => {
    setEmail(userObj.email);
    // Development only. Elsewhere the account is still selectable - it
    // fills the address and leaves the password to whoever deployed it.
    setPassword(isDevelopment ? DEV_DEMO_PASSWORD : '');
    setError(null);
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    if (!email.trim()) {
      setError('Enter your email address.');
      return;
    }
    if (!password) {
      setError('Enter your password.');
      return;
    }
    attempt({ email: email.trim(), password });
  };

  return (
    <div className="login-screen-overlay animate-fade-in">
      <div className="login-card subtle-card">
        {/* Brand Header */}
        <div className="login-header">
          <div className="login-spark-icon">
            <Sparkles size={28} />
          </div>
          <h2 className="login-title">
            <span className="brand-green">SYNQ</span> Workbench
          </h2>
          <p className="login-subtitle">Prototype sign-in. Pick an account below - the password is in the presentation.</p>
        </div>

        {(connectionError || error) && (
          <div className="login-alert" role="alert">
            <AlertCircle size={16} />
            <div className="login-alert-text">
              <span>{connectionError || error}</span>
              {connectionError && (
                <button type="button" className="login-retry" onClick={retryConnection}>
                  Retry
                </button>
              )}
            </div>
          </div>
        )}

        {/* Quick Persona Selector */}
        <div className="persona-selector-section">
          <div className="section-label">
            {isDevelopment ? 'Select a demo account' : 'Accounts'}
          </div>

          <div className="personas-list">
            {users.length === 0 && !connectionError && (
              <div className="personas-empty">Loading accounts...</div>
            )}
            {users.map(u => (
              <button 
                key={u.id}
                type="button"
                className={`persona-card ${u.accessLevel === 'OWNER' ? 'owner-card' : ''}`}
                onClick={() => handlePersonaSelect(u)}
              >
                <div 
                  className="persona-avatar"
                  style={{ background: u.avatarGradient }}
                >
                  <span>{u.initials}</span>
                </div>

                <div className="persona-info">
                  <div className="persona-name-row">
                    <span className="persona-name">{u.name}</span>
                    <span className={`access-badge ${u.accessLevel === 'OWNER' ? 'badge-owner' : 'badge-emp'}`}>
                      {u.accessLevel === 'OWNER' ? 'Owner / Admin' : 'Employee'}
                    </span>
                  </div>
                  <span className="persona-role">{u.role}</span>
                  <span className="persona-scope">{u.scopeLabel}</span>
                </div>

                <ArrowRight size={16} className="persona-arrow" />
              </button>
            ))}
          </div>
        </div>

        <div className="divider-row">
          <span>OR ENTER CREDENTIALS</span>
        </div>

        {/* Custom Login Form */}
        <form onSubmit={handleFormSubmit} className="login-form">
          <div className="form-group">
            <label className="form-label">Work Email</label>
            <div className="input-with-icon">
              <User size={16} className="input-icon" />
              {/*
                * The placeholder is a reserved .example domain matching the
                * seeded accounts. It previously showed a real person at a
                * real company's live domain, which implies an affiliation
                * that does not exist - and would not have signed anyone in.
                */}
              <input
                type="email"
                placeholder="testowner@refinery.example"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <div className="label-row">
              <label className="form-label">Password</label>
              {/*
                * Shown only where the password is not filled in for you.
                * In development a persona click fills it, so pointing at the
                * deck there would send people looking for something already
                * in the box.
                */}
              {!isDevelopment && (
                <span className="label-hint">given in the presentation</span>
              )}
            </div>
            <div className="input-with-icon">
              <Lock size={16} className="input-icon" />
              <input
                type="password"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button type="submit" className="login-submit-btn" disabled={busy}>
            <ShieldCheck size={16} />
            <span>{busy ? 'Signing in...' : 'Sign in to the workbench'}</span>
          </button>
        </form>
      </div>

      <style>{`
        .login-screen-overlay {
          position: fixed;
          inset: 0;
          background: var(--bg-app);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 200;
          padding: 20px;
        }

        .login-card {
          /* Bounded by the viewport and scrolled internally. Without
             this a form taller than the screen - which is most of them on a
             phone - overflows a centred flex backdrop in both directions,
             putting the heading above the top of the screen where it cannot
             be scrolled to. */
          max-height: calc(100vh - 40px);
          max-height: calc(100dvh - 40px);
          overflow-y: auto;
          width: 100%;
          max-width: 520px;
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-xl);
          padding: 32px;
          box-shadow: var(--shadow-rim), var(--shadow-floating);
        }

        .login-header {
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
          margin-bottom: 24px;
        }

        .login-spark-icon {
          width: 52px;
          height: 52px;
          border-radius: 50%;
          background: var(--accent-light);
          color: var(--accent-primary);
          display: flex;
          align-items: center;
          justify-content: center;
          margin-bottom: 12px;
        }

        .login-title {
          font-size: 1.35rem;
          font-weight: 800;
          color: var(--text-primary);
          line-height: 1.2;
        }

        .label-row {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 10px;
        }

        .label-hint {
          font-size: 0.72rem;
          color: var(--text-muted);
        }

        .brand-green {
          color: var(--text-primary);
        }

        .login-subtitle {
          font-size: 0.825rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        .persona-selector-section {
          display: flex;
          flex-direction: column;
          gap: 10px;
          margin-bottom: 20px;
        }

        .section-label {
          font-size: 0.725rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--text-muted);
        }

        .personas-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .persona-card {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 14px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.2s ease;
          text-align: left;
        }

        .persona-card:hover {
          background: var(--bg-hover);
          border-color: var(--accent-primary);
          transform: translateY(-1px);
        }

        .persona-card.owner-card {
          border-color: color-mix(in srgb, var(--accent-primary) 30%, transparent);
        }

        .persona-avatar {
          width: 38px;
          height: 38px;
          border-radius: 50%;
          color: #FFFFFF;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 0.85rem;
          font-weight: 700;
          flex-shrink: 0;
        }

        .persona-info {
          flex: 1;
          display: flex;
          flex-direction: column;
        }

        .persona-name-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .persona-name {
          font-size: 0.9rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .access-badge {
          font-size: 0.675rem;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 999px;
        }

        .badge-owner {
          background: var(--accent-light);
          color: var(--accent-text);
        }

        .badge-emp {
          background: var(--success-bg);
          color: var(--success);
        }

        .persona-role {
          font-size: 0.775rem;
          color: var(--text-secondary);
        }

        .persona-scope {
          font-size: 0.7rem;
          color: var(--text-muted);
        }

        .persona-arrow {
          color: var(--text-muted);
          transition: transform 0.15s ease;
        }

        .persona-card:hover .persona-arrow {
          color: var(--accent-primary);
          transform: translateX(3px);
        }

        .divider-row {
          text-align: center;
          margin: 16px 0;
          position: relative;
        }

        .divider-row span {
          font-size: 0.7rem;
          font-weight: 700;
          color: var(--text-muted);
          background: var(--bg-card);
          padding: 0 10px;
        }

        .login-form {
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        .form-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .form-label {
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .input-with-icon {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 12px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
        }

        .input-icon {
          color: var(--text-muted);
        }

        .input-with-icon input {
          flex: 1;
          border: none;
          background: transparent;
          outline: none;
          font-size: 0.875rem;
          color: var(--text-primary);
        }

        .login-submit-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 10px 18px;
          background: var(--accent-primary);
          color: var(--accent-contrast);
          border: none;
          border-radius: var(--radius-md);
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          margin-top: 4px;
        }

        .login-submit-btn:hover:not(:disabled) {
          background: var(--accent-primary-hover);
        }

        .login-submit-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .login-alert {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          padding: 12px 14px;
          margin-bottom: 18px;
          border: 1px solid var(--danger);
          border-radius: var(--radius-md);
          background: var(--danger-bg);
          color: var(--danger);
          font-size: 0.8125rem;
          line-height: 1.45;
        }

        .login-alert-text {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
        }

        .login-retry {
          background: none;
          border: none;
          padding: 0;
          color: var(--danger);
          font-size: 0.8125rem;
          font-weight: 600;
          text-decoration: underline;
          cursor: pointer;
        }

        .personas-empty {
          padding: 18px;
          text-align: center;
          font-size: 0.8125rem;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};
