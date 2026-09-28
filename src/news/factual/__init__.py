"""NEWS-2 — the FACTUAL news layer. Observe-only.

Owner ruling 2026-09-27: separate FACTUAL NEWS STATE from LLM INTERPRETATION.

    Code establishes facts and provenance.
    The future Brain reasons over those facts.
    No lower-tier model may quietly pre-bias the Brain's market judgment.

So this package only ever records WHAT a named source said, WHEN it was
observed and WHEN we retrieved it. It never scores sentiment, never assigns a
bullish/bearish lean, and makes no model call.

THE CONTRACT, enforced by tests:

  * Absence of evidence is not evidence of calm. Missing, stale, failed or
    unparseable data is UNKNOWN / STALE with a reason -- never "normal".
  * Every fact carries its provenance: source, reference, fetched_at, and the
    source's own publication/observation time kept DISTINCT from retrieval.
  * Conflicting sources stay visible as a conflict; nothing is silently
    reconciled, and merging duplicates never erases a source.
  * Delayed data (a daily FRED close) can never present as live.
  * OBSERVE-ONLY: nothing here is imported by the scan, the candidate
    producer, sizing, risk, execution or protection, and nothing here enters
    `brain_input`. It is read by operator tools and post-session audits only.
"""
