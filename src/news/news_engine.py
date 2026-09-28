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

#: NEWS-2 (2026-09-27): ABSENCE OF EVIDENCE IS NOT EVIDENCE OF CALM.
#: NEWS-1 used to turn a missing, unreadable or never-refreshed source into
#: "no active events; risk=normal". A source file older than this is STALE.
DEFAULT_SOURCE_MAX_AGE_HOURS = 24.0
UNKNOWN_RISK = "unknown"


def _source_state(path: str, now_dt, max_age_hours: float) -> dict:
    """ok | missing | unreadable | stale, with the file's own age. Never raises."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    out = {"path": path, "state": "missing", "as_of": None, "age_hours": None}
    try:
        if not path or not os.path.exists(path):
            return out
        with open(path, encoding="utf-8") as fh:
            rows = _json.load(fh)
        if not isinstance(rows, list):
            out["state"] = "unreadable"
            return out
        mtime = _dt.fromtimestamp(os.path.getmtime(path), tz=_tz.utc)
        age_h = round((now_dt - mtime).total_seconds() / 3600.0, 2)
        out.update(as_of=mtime.isoformat(), age_hours=age_h,
                   state="ok" if age_h <= max_age_hours else "stale")
        return out
    except Exception:  # noqa: BLE001
        out["state"] = "unreadable"
        return out


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
    return "; ".join(bits)


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
        from news.calendar_provider import _parse_dt
        from datetime import datetime as _dt, timezone as _tz
        now_dt = _parse_dt(now) or _dt.now(_tz.utc)
        cal_provider = EconomicCalendarProvider(calendar_path)
        brk_provider = BreakingNewsProvider(breaking_path)
        max_age = float(os.getenv("NEWS_SOURCE_MAX_AGE_HOURS",
                                  DEFAULT_SOURCE_MAX_AGE_HOURS))
        sources = {"calendar": _source_state(cal_provider.path, now_dt, max_age),
                   "breaking": _source_state(brk_provider.path, now_dt, max_age)}
        cal = cal_provider.snapshot(now)
        breaking = brk_provider.recent(now)
        assessments = [classify_news(b) for b in breaking]
        risk = assess_event_risk(cal, assessments)

        # Evidence of risk from the data we DO have still stands; but "normal"
        # can only be asserted when every source is present and fresh.
        unproven = sorted(k for k, v in sources.items() if v["state"] != "ok")
        risk_state = risk.risk_state
        data_state = "known" if not unproven else "partial"
        if unproven and risk_state == "normal":
            risk_state = UNKNOWN_RISK
            data_state = "unknown"
        summary = _summary(risk, cal)
        if risk_state == UNKNOWN_RISK:
            summary = ("news state UNKNOWN: "
                       + ", ".join(f"{k} {sources[k]['state']}" for k in unproven))
        elif not summary.replace(f"risk={risk.risk_state}", "").strip("; "):
            summary = (f"no scheduled events in the lookahead window "
                       f"(calendar as of {sources['calendar']['as_of']}); risk=normal")

        return {
            # ── Phase 5 canonical fields ─────────────────────────────────────
            "risk_state": risk_state,
            "active_event": risk.active_event,
            "minutes_to_event": risk.minutes_to_event,
            "breaking_news_active": risk.breaking_news_active,
            "breaking_news_category": risk.breaking_category,
            "summary": summary,
            "data_state": data_state,
            "unproven_sources": unproven,
            "sources": sources,
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
            "risk_state": UNKNOWN_RISK, "data_state": "unknown", "active_event": None,
            "minutes_to_event": None, "breaking_news_active": False,
            "breaking_news_category": None,
            "summary": f"news_context_error:{exc}",
            "scheduled_event_window": False, "impact_level": None,
            "breaking_news_relevance": None, "reasons": [f"error:{exc}"],
            "directional": False,
        }
