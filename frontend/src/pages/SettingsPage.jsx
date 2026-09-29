import React from 'react';
import { useApp } from '../state/AppContext';
import { api } from '../services/api';
import {
  SynqBrand,
  BRAND_VARIANTS,
  useBrandVariant
} from '../components/layout/SynqBrand';
import {
  Sun,
  Moon,
  Laptop,
  Sliders,
  Cpu,
  Check
} from 'lucide-react';

export const SettingsPage = () => {
  const { settings, updateSettingsAction, updateTheme, health } = useApp();
  const [brandVariant, chooseBrandVariant] = useBrandVariant();

  const inference = health?.inference;
  const [available, setAvailable] = React.useState([]);
  const [routes, setRoutes] = React.useState([]);

  // What the configured provider can actually serve. Empty if it cannot be
  // reached or cannot enumerate - never a hardcoded guess.
  React.useEffect(() => {
    let cancelled = false;
    api
      .getModels()
      .then((c) => {
        if (cancelled) return;
        setAvailable(c.available || []);
        setRoutes(c.routes || []);
      })
      .catch(() => {
        if (cancelled) return;
        setAvailable([]);
        setRoutes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [inference?.provider]);

  // Sent by the server so this cannot drift from what the prompt builder
  // honours. It had drifted: three options were listed here against five
  // supported, so the default style was not selectable at all.
  const styleOptions = settings.responseStyleOptions?.length
    ? settings.responseStyleOptions
    : [settings.responseStyle].filter(Boolean);

  const handleThemeChange = (newTheme) => {
    updateTheme(newTheme);
  };

  const handleToggleSetting = (key) => {
    updateSettingsAction({ [key]: !settings[key] });
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Workbench Settings</h1>
          <p className="page-subtitle">Configure theme system, interface layout, and sovereign AI engine preferences.</p>
        </div>
      </div>

      <div className="settings-sections-list">
        {/* Appearance Section */}
        <div className="settings-section-card subtle-card">
          <div className="section-title-group">
            <Sun size={20} className="section-icon" />
            <div>
              <h2 className="section-title">Appearance</h2>
              <p className="section-desc">Customize interface visual theme and display system.</p>
            </div>
          </div>

          <div className="theme-options-grid">
            <button 
              className={`theme-card ${settings.theme === 'light' ? 'selected' : ''}`}
              onClick={() => handleThemeChange('light')}
            >
              <div className="theme-preview-box light">
                <div className="mini-sidebar" />
                <div className="mini-content">
                  <div className="mini-bubble" />
                </div>
              </div>
              <div className="theme-label-row">
                <Sun size={16} />
                <span>Light</span>
                {settings.theme === 'light' && <Check size={16} className="text-accent" />}
              </div>
            </button>

            <button 
              className={`theme-card ${settings.theme === 'dark' ? 'selected' : ''}`}
              onClick={() => handleThemeChange('dark')}
            >
              <div className="theme-preview-box dark">
                <div className="mini-sidebar" />
                <div className="mini-content">
                  <div className="mini-bubble" />
                </div>
              </div>
              <div className="theme-label-row">
                <Moon size={16} />
                <span>Dark</span>
                {settings.theme === 'dark' && <Check size={16} className="text-accent" />}
              </div>
            </button>

            <button 
              className={`theme-card ${settings.theme === 'system' ? 'selected' : ''}`}
              onClick={() => handleThemeChange('system')}
            >
              <div className="theme-preview-box system">
                <div className="mini-sidebar" />
                <div className="mini-content">
                  <div className="mini-bubble" />
                </div>
              </div>
              <div className="theme-label-row">
                <Laptop size={16} />
                <span>System</span>
                {settings.theme === 'system' && <Check size={16} className="text-accent" />}
              </div>
            </button>
          </div>

          {/*
            * The previews are the real component on the real background, so
            * what is shown here is what the sidebar will render - including
            * the light theme's inversion. A mock-up of a logo picker would
            * be the one preview it is not worth faking.
            */}
          <div className="brand-choice">
            <div className="brand-choice-head">
              <h3 className="brand-choice-title">Brand mark</h3>
              <p className="brand-choice-desc">
                Which form of the logo the sidebar shows.
              </p>
            </div>

            <div className="brand-options-grid">
              {Object.values(BRAND_VARIANTS).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={
                    'theme-card brand-option' +
                    (brandVariant === option.id ? ' selected' : '')
                  }
                  onClick={() => chooseBrandVariant(option.id)}
                  aria-pressed={brandVariant === option.id}
                >
                  <div className="brand-option-stage">
                    <SynqBrand variant={option.id} />
                  </div>
                  <div className="theme-label-row">
                    <span>{option.label}</span>
                    {brandVariant === option.id && (
                      <Check size={16} className="text-accent" />
                    )}
                  </div>
                  <p className="brand-option-desc">{option.description}</p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Interface Preferences */}
        <div className="settings-section-card subtle-card">
          <div className="section-title-group">
            <Sliders size={20} className="section-icon" />
            <div>
              <h2 className="section-title">Interface Preferences</h2>
              <p className="section-desc">Toggle workspace display elements and layout options.</p>
            </div>
          </div>

          <div className="settings-toggle-list">
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-name">Compact Mode</span>
                <span className="setting-sub">Reduce spacing and padding for higher information density.</span>
              </div>
              <button 
                className={`toggle-switch ${settings.compactMode ? 'on' : 'off'}`}
                onClick={() => handleToggleSetting('compactMode')}
              >
                <span className="toggle-handle" />
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-name">Show Timestamps</span>
                <span className="setting-sub">Display timestamps above chat message bubbles.</span>
              </div>
              <button 
                className={`toggle-switch ${settings.showTimestamps ? 'on' : 'off'}`}
                onClick={() => handleToggleSetting('showTimestamps')}
              >
                <span className="toggle-handle" />
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-name">Show Agent Activity Trace</span>
                <span className="setting-sub">Show the collapsible record of retrieval and tool steps under each reply.</span>
              </div>
              <button 
                className={`toggle-switch ${settings.showAgentActivity ? 'on' : 'off'}`}
                onClick={() => handleToggleSetting('showAgentActivity')}
              >
                <span className="toggle-handle" />
              </button>
            </div>
          </div>
        </div>

        {/* AI & Sovereign Model Configuration */}
        <div className="settings-section-card subtle-card">
          <div className="section-title-group">
            <Cpu size={20} className="section-icon" />
            <div>
              <h2 className="section-title">AI Engine Settings</h2>
              <p className="section-desc">Active inference engine and generation parameters.</p>
            </div>
          </div>

          <div className="form-grid">
            {/*
              Read-only on purpose: these are server settings (.env), not
              per-user preferences - a browser control that cannot change one
              would be a control that does nothing.

              It used to name a single "Active Model", which stopped being
              true once turns were routed by role. One deployment now runs
              several models across more than one vendor, and naming only the
              chat model described the least of it.
            */}
            <div className="form-group form-group-wide">
              <label className="form-label">Routed models</label>
              {routes.length === 0 ? (
                <div className="active-model-box">
                  <span className="active-model-name font-mono">
                    {inference?.configured ? inference.model : 'No model configured'}
                  </span>
                  <span className={`model-origin-pill ${inference?.onPremise ? 'on-prem' : 'external'}`}>
                    {inference?.configured ? 'Active' : 'Inference disabled'}
                  </span>
                </div>
              ) : (
                <div className="route-table">
                  {routes.map((route) => (
                    <div
                      key={route.role}
                      className={`route-row ${route.configured ? '' : 'fallback'}`}
                      title={route.purpose}
                    >
                      <span className="route-role">{route.role}</span>
                      <span className="route-model font-mono">
                        {route.model || 'not set'}
                      </span>
                      <span className="route-flags">
                        {!route.configured && (
                          <span className="route-flag">falls back to chat</span>
                        )}
                        {route.acceptsImages && (
                          <span className="route-flag images">images</span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <span className="range-sub">
                Set per role in .env (MODEL_NAME, MODEL_VISION, MODEL_REASONING,
                MODEL_FAST, MODEL_TRANSCRIPTION). Inference runs{" "}
                {inference?.onPremise
                  ? "on-premise"
                  : `on an external provider (${inference?.provider ?? "none"})`}
                .
                {available.length > 0 &&
                  ` ${available.length} model(s) available from the default provider.`}
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">Temperature ({settings.temperature})</label>
              <input 
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={settings.temperature}
                onChange={(e) => updateSettingsAction({ temperature: parseFloat(e.target.value) })}
                className="form-range"
              />
              <span className="range-sub font-mono">0.0 (Deterministic / Technical) — 1.0 (Creative)</span>
            </div>

            <div className="form-group">
              <label className="form-label">Response Style</label>
              <select
                className="form-select"
                value={settings.responseStyle}
                onChange={(e) => updateSettingsAction({ responseStyle: e.target.value })}
              >
                {styleOptions.map((style) => (
                  <option key={style} value={style}>
                    {style}
                  </option>
                ))}
              </select>
              <span className="range-sub">
                Balanced is the default and leaves the assistant's own voice
                alone. The others nudge it.
              </span>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .page-container { padding: 18px 16px 28px; }
          .page-title { font-size: 1.25rem; }
          /* The routed-model table is three fixed columns; let the model id
             wrap instead of forcing the row wider than the screen. */
          .route-row {
            grid-template-columns: 1fr;
            gap: 4px;
          }

          .route-flags { justify-content: flex-start; }
        }

        .page-container {
          padding: 32px;
          height: 100%;
          overflow-y: auto;
          background-color: var(--bg-workspace);
        }

        .page-header {
          margin-bottom: 28px;
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

        .settings-sections-list {
          display: flex;
          flex-direction: column;
          gap: 24px;
          max-width: 800px;
        }

        .settings-section-card {
          padding: 24px;
          background: var(--bg-card);
          border-radius: var(--radius-lg);
        }

        .section-title-group {
          display: flex;
          align-items: center;
          gap: 14px;
          margin-bottom: 20px;
        }

        .section-icon {
          color: var(--accent-primary);
        }

        .section-title {
          font-size: 1.1rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .section-desc {
          font-size: 0.825rem;
          color: var(--text-muted);
        }

        .theme-options-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
        }

        .brand-choice {
          margin-top: 24px;
          padding-top: 20px;
          border-top: 1px solid var(--border-light);
        }

        .brand-choice-head {
          margin-bottom: 14px;
        }

        .brand-choice-title {
          font-size: 0.9rem;
          font-weight: 600;
          color: var(--text-primary);
          margin: 0;
        }

        .brand-choice-desc {
          font-size: 0.8rem;
          color: var(--text-secondary);
          margin: 2px 0 0 0;
        }

        .brand-options-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 16px;
        }

        /* The stage is sized to the taller variant so the two cards do not
           change height when the mark inside them changes. */
        .brand-option-stage {
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 78px;
          padding: 8px 12px;
          background: var(--bg-app);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-sm);
          overflow: hidden;
        }

        .brand-option-desc {
          font-size: 0.75rem;
          line-height: 1.4;
          color: var(--text-muted);
          margin: 0;
        }

        @media (max-width: 640px) {
          .brand-options-grid {
            grid-template-columns: 1fr;
          }
        }

        @media (max-width: 640px) {
          .theme-options-grid {
            grid-template-columns: 1fr;
          }
        }

        .theme-card {
          display: flex;
          flex-direction: column;
          gap: 10px;
          padding: 12px;
          background: var(--bg-card-subtle);
          border: 2px solid var(--border-light);
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.2s ease;
          text-align: left;
        }

        .theme-card:hover {
          border-color: var(--border-subtle);
        }

        .theme-card.selected {
          border-color: var(--accent-primary);
          background: var(--bg-active);
        }

        .theme-preview-box {
          height: 70px;
          border-radius: 6px;
          display: flex;
          overflow: hidden;
          border: 1px solid var(--border-light);
        }

        .theme-preview-box.light {
          background: #F6F7F9;
        }

        .theme-preview-box.light .mini-sidebar {
          width: 30%;
          background: #FFFFFF;
          border-right: 1px solid var(--border-subtle);
        }

        .theme-preview-box.light .mini-content {
          flex: 1;
          padding: 8px;
        }

        .theme-preview-box.light .mini-bubble {
          height: 12px;
          background: var(--accent-light);
          border-radius: 4px;
          width: 80%;
        }

        .theme-preview-box.dark {
          background: #0A0B0D;
        }

        .theme-preview-box.dark .mini-sidebar {
          width: 30%;
          background: #0E1013;
          border-right: 1px solid var(--border-subtle);
        }

        .theme-preview-box.dark .mini-content {
          flex: 1;
          padding: 8px;
        }

        .theme-preview-box.dark .mini-bubble {
          height: 12px;
          background: #1F232A;
          border-radius: 4px;
          width: 80%;
        }

        .theme-preview-box.system {
          background: linear-gradient(135deg, #F6F7F9 50%, #0A0B0D 50%);
        }

        .theme-label-row {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .settings-toggle-list {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .setting-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding-bottom: 12px;
          border-bottom: 1px solid var(--border-light);
        }

        .setting-row:last-child {
          border-bottom: none;
          padding-bottom: 0;
        }

        .setting-info {
          display: flex;
          flex-direction: column;
        }

        .setting-name {
          font-size: 0.9rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .setting-sub {
          font-size: 0.775rem;
          color: var(--text-muted);
        }

        .toggle-switch {
          width: 44px;
          height: 24px;
          border-radius: 999px;
          background: var(--border-subtle);
          border: none;
          padding: 2px;
          cursor: pointer;
          transition: background-color 0.2s ease;
          position: relative;
        }

        .toggle-switch.on {
          background: var(--accent-primary);
        }

        /*
         * The knob was a hardcoded #FFFFFF from when the accent was purple.
         * Now that the accent is the text colour, the "on" track is white on
         * the dark theme - so the knob was white on white and the switch
         * read as empty. --accent-contrast is the colour guaranteed legible
         * against the accent whichever way the theme falls.
         */
        .toggle-handle {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: var(--text-secondary);
          display: block;
          transition: transform 0.2s ease, background-color 0.2s ease;
        }

        .toggle-switch.on .toggle-handle {
          background: var(--accent-contrast);
          transform: translateX(20px);
        }

        .toggle-switch:focus-visible {
          outline: 2px solid var(--accent-primary);
          outline-offset: 2px;
        }

        .form-grid {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .form-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .form-label {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .form-group-wide {
          grid-column: 1 / -1;
        }

        .route-table {
          display: flex;
          flex-direction: column;
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          overflow: hidden;
        }

        .route-row {
          display: grid;
          grid-template-columns: 110px 1fr auto;
          align-items: center;
          gap: 10px;
          padding: 9px 12px;
          font-size: 0.8rem;
          border-bottom: 1px solid var(--border-light);
        }

        .route-row:last-child { border-bottom: none; }

        .route-role {
          font-size: 0.68rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--text-muted);
        }

        .route-model { color: var(--text-primary); }

        .route-row.fallback .route-model { color: var(--text-muted); }

        .route-flags {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          justify-content: flex-end;
        }

        .route-flag {
          font-size: 0.66rem;
          font-weight: 600;
          padding: 1px 7px;
          border-radius: 999px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          color: var(--text-muted);
        }

        .route-flag.images {
          color: var(--accent-text);
          background: var(--accent-light);
          border-color: transparent;
        }

        .active-model-box {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          padding: 10px 14px;
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          background: var(--bg-card-subtle);
        }

        .active-model-name {
          font-size: 0.875rem;
          font-weight: 600;
          color: var(--text-primary);
          word-break: break-all;
        }

        .model-origin-pill {
          flex-shrink: 0;
          padding: 3px 10px;
          border-radius: 999px;
          font-size: 0.6875rem;
          font-weight: 600;
          white-space: nowrap;
        }

        .model-origin-pill.on-prem {
          background: var(--success-bg);
          color: var(--success);
        }

        .model-origin-pill.external {
          background: var(--warning-bg);
          color: var(--warning);
        }

        .form-select {
          padding: 10px 14px;
          background: var(--bg-card-subtle);
          border: 1px solid var(--border-light);
          border-radius: var(--radius-md);
          font-size: 0.875rem;
          color: var(--text-primary);
          outline: none;
        }

        .form-range {
          accent-color: var(--accent-primary);
        }

        .range-sub {
          font-size: 0.75rem;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
};
