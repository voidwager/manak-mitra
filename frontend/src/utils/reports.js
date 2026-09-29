/**
 * Whether a reply can be turned into a report.
 *
 * This file used to *build* the report as well, and what it built was a lie.
 * Written during an earlier phase, it hardcoded "Not available yet" into
 * equipment, unit and location, and stated in the findings section that the
 * workbench "cannot produce findings until document retrieval and model
 * inference are implemented". Both had been working for phases. It also
 * recommended "Index the knowledge base (Phase 8)" to a user whose knowledge
 * base was indexed, and the modal defaulted the risk level to "Moderate Risk"
 * - a rating nothing had assessed.
 *
 * Assembly now happens on the server (`app/services/reports.py`), where the
 * evidence actually lives: which documents were cited, which tools ran, which
 * model answered, under whose clearance. The browser cannot know any of that
 * without being told, and a report is exactly the artefact that gets forwarded
 * out of context and mistaken for an approved one.
 *
 * What is left here is the one question the client can answer on its own:
 * should the button be offered at all.
 */

/** Below this, a reply is a pleasantry or a one-liner, not an analysis. */
const MIN_REPORTABLE_LENGTH = 200;

const citationsOn = (message) => {
  if (message?.sources?.length) return message.sources;
  return message?.source ? [message.source] : [];
};

/**
 * Is there enough substance in this reply to build a report from?
 *
 * Mirrors `app.services.reports.is_reportable`, deliberately: offering the
 * button and then having the server refuse is worse than not offering it.
 *
 * A citation is sufficient on its own. A short answer backed by a retrieved
 * passage - "2.5 mm/s RMS [1]" - is precisely what a report should carry,
 * and the length rule alone would throw it away. Without one, the reply has
 * to be long enough to plausibly contain findings.
 */
export function isReportable(message) {
  if (!message || message.sender !== 'assistant' || message.streaming) return false;
  if (citationsOn(message).length > 0) return true;

  return (message.text || '').trim().length >= MIN_REPORTABLE_LENGTH;
}

export default isReportable;
