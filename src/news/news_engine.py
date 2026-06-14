"""NEWS-1 — Market Intelligence assembler + Brain-integration entry point.

Ties Phases 1-4 together into the single `news_context` block the Brain
receives (Phase 5). Gated by NEWS_LAYER_ENABLED (default false): when off the
caller skips this entirely and the pipeline is bit-for-bit unchanged.

CONTRACT (the hard guarantees of NEWS-1):
  • news_context is CONTEXT ONLY — it carries risk/awareness, never a direction
    and never a trade. There is no "buy"/"sell"/side field anywhere in it.
  • The Brain remains the ECU; news is just another evidence source it weighs.
Read-only; never raises.
"""
from __future__ import annotations

import os
from typing import Optional

from news.calendar_provider import EconomicCalendarProvider
from news.breaking_news_provider import BreakingNewsProvider
from news.news_classifier import classify_news
from news.event_risk_engine import assess_event_risk


def news_enabled() -> bool:
    return os.getenv("NEWS_LAYER_ENABLED", "false").lower().strip() == "true"


def _summary(risk, cal) -> str:
    bits = []
    if risk.active_event:
        if risk.minutes_to_event is not None and risk.minutes_to_event >= 0:
            bits.append(f"{risk.active_event} in {risk.minutes_to_event:.0f}m "
                        f"({risk.impact_level} impact)")
        elif cal.recent_event is not None:
            bits.append(f"{cal.recent_event.event_name} released "
                        f"{cal.minutes_since_recent:.0f}m ago")
    if risk.breaking_news_active:
        bits.append(f"breaking {risk.breaking_category} "
                    f"(relevance {risk.breaking_relevance})")
    bits.append(f"risk={risk.risk_state}")
    return "; ".join(bits) if bits else "no active events; risk=normal"


def build_news_context(now=None,
                       calendar_path: Optional[str] = None,
                       breaking_path: Optional[str] = None) -> dict:
    """Assemble the Brain-facing news_context. Never raises.

    Returns the canonical Phase-5 shape (plus a few non-directional extras):
      {risk_state, active_event, minutes_to_event, breaking_news_active,
       breaking_news_category, summary, scheduled_event_window, impact_level,
       breaking_news_relevance, reasons}
    """
    try:
        cal = EconomicCalendarProvider(calendar_path).snapshot(now)
        breaking = BreakingNewsProvider(breaking_path).recent(now)
        assessments = [classify_news(b) for b in breaking]
        risk = assess_event_risk(cal, assessments)

        return {
            # ── Phase 5 canonical fields ─────────────────────────────────────
            "risk_state": risk.risk_state,
            "active_event": risk.active_event,
            "minutes_to_event": risk.minutes_to_event,
            "breaking_news_active": risk.breaking_news_active,
            "breaking_news_category": risk.breaking_category,
            "summary": _summary(risk, cal),
            # ── non-directional extras (still context-only) ──────────────────
            "scheduled_event_window": cal.scheduled_event_window,
            "impact_level": risk.impact_level,
            "breaking_news_relevance": risk.breaking_relevance,
            "reasons": risk.reasons,
            # explicit contract marker the Brain prompt relies on
            "directional": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "risk_state": "normal", "active_event": None,
            "minutes_to_event": None, "breaking_news_active": False,
            "breaking_news_category": None,
            "summary": f"news_context_error:{exc}",
            "scheduled_event_window": False, "impact_level": None,
            "breaking_news_relevance": None, "reasons": [f"error:{exc}"],
            "directional": False,
        }
