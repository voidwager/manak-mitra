import React from 'react';
import { X, FileCheck, Download, Printer, CheckCircle2, Cloud, ShieldCheck } from 'lucide-react';
import { formatDateTime } from '../../utils/time';

/**
 * A generated inspection report.
 *
 * Everything here is rendered from what the server assembled - findings the
 * model wrote from its own cited answer, and an evidence trail stamped from
 * the stored reply: the documents actually retrieved, the tools that actually
 * ran, the model that actually answered, under the reader's real clearance.
 *
 * Three things this deliberately no longer does:
 *
 *   - No risk rating. The old version defaulted to "Moderate Risk" whenever
 *     the field was empty, which meant every report carried an assessment
 *     nothing had performed. Nothing here assesses risk, so nothing states one.
 *   - No real company's letterhead. The banner used to read "MANGALORE
 *     REFINERY AND PETROCHEMICALS LIMITED" above entirely synthetic findings.
 *     An inspection report is exactly the artefact that gets forwarded out of
 *     context, and one carrying a real operator's name is a document nobody
 *     should be able to produce by accident.
 *   - No "Sovereign On-Premise" claim. Where inference happened is read from
 *     the report, which the server stamped from the running provider. It says
 *     "external provider" when that is the truth.
 */
export const ReportModal = ({ reportData, onClose }) => {
  if (!reportData) return null;

  const {
    title,
    summary,
    findings = [],
    recommendations = [],
    question,
    generatedAt,
    preparedFor,
    clearance,
    agent,
    model,
    onPremise,
    sources = [],
    toolsUsed = [],
    disclaimer,
  } = reportData;

  const asMarkdown = () => {
    const block = (heading, body) => (body ? `\n## ${heading}\n\n${body}\n` : '');
    const list = (items) => items.map((i) => `- ${i}`).join('\n');

    return [
      `# ${title}`,
      '',
      `Generated: ${formatDateTime(generatedAt) || generatedAt}`,
      `Prepared for: ${preparedFor} (${clearance})`,
      `Agent: ${agent}`,
      `Model: ${model} (${onPremise ? 'on-premise' : 'external provider'})`,
      question ? `\nQuestion asked: ${question}` : '',
      block('Summary', summary),
      block('Findings', list(findings)),
      recommendations.length ? block('Recommended actions', list(recommendations)) : '',
      sources.length
        ? block('Sources consulted', list(sources.map((s) => `${s.title}${s.location ? ` - ${s.location}` : ''}`)))
        : block('Sources consulted', 'No document was cited in this reply.'),
      toolsUsed.length ? block('Tools run', list(toolsUsed)) : '',
      `\n---\n\n${disclaimer}\n`,
    ]
      .filter(Boolean)
      .join('\n');
  };

  /**
   * A real file, not an alert().
   *
   * Markdown rather than PDF: a PDF needs a rendering library, and an export
   * that silently produced nothing was worse than none at all - this one is
   * openable, diffable and pastes into a ticket. Print gives a PDF through
   * the browser for anyone who needs one.
   */
  const handleExport = () => {
    const blob = new Blob([asMarkdown()], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(title || 'inspection-report').replace(/[^\w\d-]+/g, '-').toLowerCase()}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-backdrop animate-fade-in" onClick={onClose}>
      <div className="modal-card report-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="report-title-group">
            <div className="report-badge">
              <FileCheck size={20} />
            </div>
            <div>
              <h3 className="modal-title">{title}</h3>
              <span className="report-id-text">
                Generated {formatDateTime(generatedAt) || generatedAt}
              </span>
            </div>
          </div>
          <div className="modal-actions">
            <button className="download-btn" onClick={handleExport}>
              <Download size={15} />
              <span>Download</span>
            </button>
            <button className="download-btn" onClick={() => window.print()}>
              <Printer size={15} />
              <span>Print</span>
            </button>
            <button className="close-btn" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Report Content */}
        <div className="modal-body">
          <div className="report-paper">
            {/* Provenance banner. No operator's letterhead; the product
                subtitle is restored at the author's request, and where the
                inference actually ran is still reported beside it rather than
                asserted - see the pill. */}
            <div className="report-banner">
              <div className="company-info">
                <h4 className="comp-name">
                  Manak Mitra — Indian Standards Help Desk Summary
                </h4>
                <p className="comp-sub">
                  Compiled from public BIS sources. Information, not a BIS
                  decision; confirm current rules on bis.gov.in.
                </p>
              </div>
              <div className={`risk-pill ${onPremise ? 'onprem' : 'external'}`}>
                {onPremise ? <ShieldCheck size={14} /> : <Cloud size={14} />}
                <span>{onPremise ? 'On-premise inference' : 'External provider'}</span>
              </div>
            </div>

            {/* Meta Grid */}
            <div className="report-meta-grid">
              <div className="meta-item">
                <span className="meta-label">Prepared for</span>
                <span className="meta-val">{preparedFor}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Clearance</span>
                <span className="meta-val">{clearance}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Agent</span>
                <span className="meta-val">{agent}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Model</span>
                <span className="meta-val">{model}</span>
              </div>
            </div>

            {question && (
              <div className="report-section">
                <h4 className="section-heading">Request</h4>
                <p className="report-question">{question}</p>
              </div>
            )}

            <div className="report-section">
              <h4 className="section-heading">1. Summary</h4>
              <div className="findings-box">
                <p>{summary}</p>
              </div>
            </div>

            <div className="report-section">
              <h4 className="section-heading">2. Findings</h4>
              <div className="actions-box">
                {findings.map((finding, idx) => (
                  <div key={idx} className="action-row">
                    <span className="action-num">{idx + 1}.</span>
                    <span>{finding}</span>
                  </div>
                ))}
              </div>
            </div>

            {recommendations.length > 0 && (
              <div className="report-section">
                <h4 className="section-heading">3. Recommended actions</h4>
                <div className="actions-box">
                  {recommendations.map((action, idx) => (
                    <div key={idx} className="action-row">
                      <span className="action-num">{idx + 1}.</span>
                      <span>{action}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* The evidence trail. Empty is stated rather than hidden: a
                report with no citation is a different kind of document, and
                the reader has to be able to see which one they are holding. */}
            <div className="report-section">
              <h4 className="section-heading">
                {recommendations.length > 0 ? '4' : '3'}. Sources consulted
              </h4>
              {sources.length > 0 ? (
                <ul className="evidence-list">
                  {sources.map((source, idx) => (
                    <li key={source.documentId || idx} className="evidence-item">
                      <CheckCircle2 size={16} className="text-accent" />
                      <span>
                        {source.title}
                        {source.location ? ` — ${source.location}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="report-empty">
                  No document was cited in this reply, so this report carries no
                  documentary evidence.
                </p>
              )}
            </div>

            {toolsUsed.length > 0 && (
              <div className="report-section">
                <h4 className="section-heading">
                  {recommendations.length > 0 ? '5' : '4'}. Tools run
                </h4>
                <div className="citation-tags">
                  {toolsUsed.map((tool) => (
                    <div key={tool} className="cite-chip">
                      <span>{tool}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="report-disclaimer">{disclaimer}</p>
          </div>
        </div>

        <style>{`
          .risk-pill.onprem {
            background: var(--success-bg);
            color: var(--success);
          }

          .risk-pill.external {
            background: var(--warning-bg, rgba(217, 119, 6, 0.16));
            color: var(--warning, #D97706);
          }

          .report-question {
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-style: italic;
            line-height: 1.55;
          }

          .report-empty {
            font-size: 0.875rem;
            color: var(--text-secondary);
            line-height: 1.55;
          }

          .report-disclaimer {
            margin-top: 28px;
            padding-top: 16px;
            border-top: 1px solid var(--border-subtle);
            font-size: 0.8rem;
            line-height: 1.5;
            color: var(--text-muted, var(--text-secondary));
          }

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

          .report-modal {
            width: 100%;
            max-width: 780px;
            max-height: 88vh;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-rim), var(--shadow-lg);
            display: flex;
            flex-direction: column;
            overflow: hidden;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-light);
          }

          .report-title-group {
            display: flex;
            align-items: center;
            gap: 12px;
          }

          .report-badge {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: var(--success-bg);
            color: var(--success);
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .modal-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .report-id-text {
            font-size: 0.775rem;
            color: var(--text-muted);
          }

          .modal-actions {
            display: flex;
            align-items: center;
            gap: 10px;
          }

          .download-btn {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: var(--accent-primary);
            color: var(--accent-contrast);
            border: none;
            border-radius: var(--radius-md);
            font-size: 0.825rem;
            font-weight: 600;
            cursor: pointer;
          }

          .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            padding: 6px;
          }

          .modal-body {
            padding: 24px;
            overflow-y: auto;
            flex: 1;
            background: var(--bg-card-subtle);
          }

          .report-paper {
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: var(--radius-md);
            padding: 28px;
            display: flex;
            flex-direction: column;
            gap: 24px;
          }

          .report-banner {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            padding-bottom: 16px;
            border-bottom: 2px solid var(--border-light);
          }

          .comp-name {
            font-size: 0.875rem;
            font-weight: 800;
            color: var(--text-primary);
            letter-spacing: 0.02em;
          }

          .comp-sub {
            font-size: 0.75rem;
            color: var(--text-muted);
          }

          .risk-pill.warning {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: var(--warning-bg);
            color: var(--warning);
            border-radius: 999px;
            font-size: 0.775rem;
            font-weight: 700;
          }

          .report-meta-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            padding: 14px;
            background: var(--bg-card-subtle);
            border-radius: var(--radius-md);
          }

          @media (max-width: 640px) {
            .report-meta-grid {
              grid-template-columns: repeat(2, 1fr);
            }
          }

          .meta-item {
            display: flex;
            flex-direction: column;
          }

          .meta-label {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
          }

          .meta-val {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-primary);
          }

          .section-heading {
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 10px;
          }

          .findings-box {
            padding: 14px 18px;
            background: var(--warning-bg);
            border-left: 4px solid var(--warning);
            border-radius: 0 8px 8px 0;
            font-size: 0.875rem;
            color: var(--text-primary);
            line-height: 1.6;
          }

          .evidence-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 8px;
          }

          .evidence-item {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.85rem;
            color: var(--text-secondary);
          }

          .actions-box {
            display: flex;
            flex-direction: column;
            gap: 8px;
          }

          .action-row {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            font-size: 0.875rem;
            color: var(--text-primary);
            font-weight: 500;
          }

          .action-num {
            font-weight: 700;
            color: var(--accent-primary);
          }

          .citation-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }

          .cite-chip {
            padding: 4px 10px;
            background: var(--bg-card-subtle);
            border: 1px solid var(--border-light);
            border-radius: 6px;
            font-size: 0.75rem;
            color: var(--text-muted);
          }
        `}</style>
      </div>
    </div>
  );
};
