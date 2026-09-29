import React, { useState } from 'react';
import { useApp } from '../state/AppContext';
import { BarChart3, Wrench, ArrowLeft, ArrowRight, Clock } from 'lucide-react';

/**
 * Performance reporting - the shell, ahead of the reports themselves.
 *
 * Both panels say plainly that they are not built yet. That is the whole
 * point of shipping the shell first: an empty section a user can find and
 * understand is useful, and a section that renders invented figures to look
 * finished is the one thing this project does not do. Nothing here reads
 * from the database, and nothing here draws a chart of made-up numbers.
 */
const PANELS = [
  {
    id: 'employee',
    label: 'Employee Performance',
    icon: BarChart3,
    blurb:
      'Per-user activity: questions asked, documents contributed, and which agents they rely on.',
    // What it would genuinely take, rather than a date nobody committed to.
    needs:
      'Needs the audit trail aggregated per user. The events are already being recorded; nothing reads them back yet.',
  },
  {
    id: 'demand',
    label: 'Public Demand',
    icon: Wrench,
    blurb:
      'What the public asks about - top topics, languages, and questions the knowledge base could not answer, so gaps in published guidance show up.',
    needs:
      'Needs visitor questions aggregated by topic and language. Each turn is already audited; nothing rolls them up yet.',
  },
];

export const PerformancePage = () => {
  const { currentUser } = useApp();
  const [openPanel, setOpenPanel] = useState(null);

  // Mirrors the sidebar, which does not offer this to anyone else. The
  // server is not involved because there is nothing here to protect yet -
  // when these panels read real data they will need a scoped endpoint, and
  // this check will not be what stops anyone.
  if (currentUser?.accessLevel !== 'OWNER') {
    return (
      <div className="page-container animate-fade-in">
        <div className="perf-empty">
          <h2>Performance</h2>
          <p>This section is available to helpdesk administrators.</p>
        </div>
        <style>{styles}</style>
      </div>
    );
  }

  const panel = PANELS.find((p) => p.id === openPanel);

  if (panel) {
    const Icon = panel.icon;
    return (
      <div className="page-container animate-fade-in">
        <button className="perf-back" onClick={() => setOpenPanel(null)}>
          <ArrowLeft size={15} />
          <span>Performance</span>
        </button>

        <div className="perf-soon">
          <div className="perf-soon-icon">
            <Icon size={26} />
          </div>
          <h2 className="perf-soon-title">{panel.label}</h2>
          <span className="perf-soon-badge">
            <Clock size={12} />
            Coming soon
          </span>
          <p className="perf-soon-blurb">{panel.blurb}</p>
          <p className="perf-soon-needs">{panel.needs}</p>
        </div>

        <style>{styles}</style>
      </div>
    );
  }

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Performance</h1>
          <p className="page-subtitle">
            Reporting across people and equipment. Both panels are shells for
            now and say so when opened.
          </p>
        </div>
      </div>

      <div className="perf-grid">
        {PANELS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className="perf-card subtle-card"
              onClick={() => setOpenPanel(item.id)}
            >
              <div className="perf-card-top">
                <div className="perf-card-icon">
                  <Icon size={20} />
                </div>
                <span className="perf-soon-badge">
                  <Clock size={12} />
                  Coming soon
                </span>
              </div>
              <h3 className="perf-card-title">{item.label}</h3>
              <p className="perf-card-blurb">{item.blurb}</p>
              <span className="perf-card-open">
                Open <ArrowRight size={14} />
              </span>
            </button>
          );
        })}
      </div>

      <style>{styles}</style>
    </div>
  );
};

const styles = `
  .page-container {
    padding: 32px;
    height: 100%;
    overflow-y: auto;
    background-color: var(--bg-workspace);
  }

  .page-header { margin-bottom: 28px; }

  .page-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }

  .page-subtitle {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-top: 4px;
    max-width: 62ch;
  }

  .perf-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
  }

  .perf-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 22px;
    text-align: left;
    border-radius: var(--radius-lg);
    background: var(--bg-card);
    cursor: pointer;
    transition: border-color 0.15s ease, transform 0.15s ease;
  }

  .perf-card:hover {
    border-color: var(--accent-primary);
    transform: translateY(-2px);
  }

  .perf-card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .perf-card-icon {
    width: 42px;
    height: 42px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--accent-light);
    color: var(--accent-primary);
  }

  .perf-card-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-primary);
  }

  .perf-card-blurb {
    font-size: 0.85rem;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .perf-card-open {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--accent-primary);
  }

  .perf-soon-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 9px;
    border-radius: 999px;
    background: var(--bg-card-subtle);
    border: 1px solid var(--border-light);
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
  }

  .perf-back {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    margin-bottom: 22px;
    padding: 7px 13px;
    border: 1px solid var(--border-light);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.83rem;
    font-weight: 600;
    cursor: pointer;
  }

  .perf-back:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .perf-soon {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 12px;
    max-width: 540px;
    margin: 6vh auto 0;
    padding: 40px 28px;
    border-radius: var(--radius-lg);
    background: var(--bg-card);
    border: 1px solid var(--border-light);
  }

  .perf-soon-icon {
    width: 58px;
    height: 58px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--accent-light);
    color: var(--accent-primary);
  }

  .perf-soon-title {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--text-primary);
  }

  .perf-soon-blurb {
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--text-secondary);
  }

  .perf-soon-needs {
    font-size: 0.82rem;
    line-height: 1.6;
    color: var(--text-muted);
    padding-top: 12px;
    border-top: 1px solid var(--border-light);
    width: 100%;
  }

  .perf-empty {
    max-width: 460px;
    margin: 10vh auto 0;
    text-align: center;
    color: var(--text-muted);
  }

  .perf-empty h2 {
    font-size: 1.2rem;
    color: var(--text-primary);
    margin-bottom: 6px;
  }

  @media (max-width: 720px) {
    .page-container { padding: 18px 16px 28px; }
    .perf-grid { grid-template-columns: 1fr; gap: 14px; }
    .perf-soon { margin-top: 2vh; padding: 30px 20px; }
  }
`;

export default PerformancePage;
