"""NEWS-1 Phase 4 — Event Risk Engine.

Translates the calendar snapshot + breaking-news assessments into a single
event-RISK state. This is risk AWARENESS, not a trade decision: it tells the
Brain how dangerous the information environment is, never which way to trade.
Read-only; never raises; never trades; touches no risk-engine code.

Risk states: normal, caution, high_risk, stand_down, post_event_digest

Reference behaviour (from the NEWS-1 spec):
  CPI in 10 minutes      → high_risk
  FOMC in 5 minutes      → stand_down
  5 minutes after CPI    → post_event_digest
  no event               → normal
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from news.calendar_provider import EconomicCalendarSnapshot
from news.news_classifier import NewsAssessment, _REL_RANK

RISK_STATES = ("normal", "caution", "high_risk", "stand_down", "post_event_digest")
_RISK_RANK = {s: i for i, s in enumerate(
    ("normal", "post_event_digest", "caution", "high_risk", "stand_down"))}

# Events that command a full stand_down inside the blackout window.
_BLACKOUT_TIER = {"FOMC", "Powell Speech", "NFP", "CPI", "Core CPI"}

# minutes thresholds
STAND_DOWN_MIN = 5      # high-impact / blackout event imminent
HIGH_RISK_MIN = 15      # high-impact event approaching
CAUTION_MIN = 60        # any tracked event on the horizon


def _higher(a: str, b: str) -> str:
    return a if _RISK_RANK.get(a, 0) >= _RISK_RANK.get(b, 0) else b


@dataclass
class EventRiskAssessment:
    risk_state: str
    active_event: Optional[str]
    minutes_to_event: Optional[float]
    impact_level: Optional[str]
    breaking_news_active: bool
    breaking_category: Optional[str]
    breaking_relevance: Optional[str]
    reasons: list

    def to_dict(self) -> dict:
        return asdict(self)


def _calendar_risk(cal: EconomicCalendarSnapshot) -> tuple:
    """Return (risk_state, reasons) from the scheduled calendar alone."""
    reasons = []

    # just-passed event → digest window
    if cal.recent_event is not None:
        reasons.append(
            f"{cal.recent_event.event_name} released "
            f"{cal.minutes_since_recent}m ago")
        # an upcoming higher-risk event can still override below
        digest = "post_event_digest"
    else:
        digest = None

    state = "normal"
    ev = cal.nearest_upcoming
    mins = cal.minutes_to_event
    if ev is not None and mins is not None and mins >= 0:
        impact = ev.impact_level
        if impact == "high" and (mins <= STAND_DOWN_MIN or ev.event_name in _BLACKOUT_TIER and mins <= STAND_DOWN_MIN):
            state = "stand_down"
            reasons.append(f"{ev.event_name} in {mins}m (high impact, blackout)")
        elif impact == "high" and mins <= HIGH_RISK_MIN:
            state = "high_risk"
            reasons.append(f"{ev.event_name} in {mins}m (high impact)")
        elif mins <= CAUTION_MIN:
            state = "caution"
            reasons.append(f"{ev.event_name} in {mins}m ({impact} impact)")

    if digest and _RISK_RANK[digest] > _RISK_RANK[state]:
        state = digest
    return state, reasons


def _breaking_risk(assessments: list) -> tuple:
    """Return (risk_state, top_assessment, reasons) from breaking news."""
    if not assessments:
        return "normal", None, []
    top = max(assessments, key=lambda a: _REL_RANK.get(a.relevance_to_nasdaq, 0))
    rel = top.relevance_to_nasdaq
    reasons = [f"breaking {top.category}={rel}: {top.headline[:80]}"]
    if rel == "critical":
        return "stand_down", top, reasons
    if rel == "high":
        return "high_risk", top, reasons
    if rel == "medium":
        return "caution", top, reasons
    return "normal", top, reasons


def assess_event_risk(cal: EconomicCalendarSnapshot,
                      assessments: Optional[list] = None) -> EventRiskAssessment:
    """Combine calendar + breaking-news risk into one assessment. Never raises."""
    try:
        assessments = assessments or []
        cal_state, cal_reasons = _calendar_risk(cal)
        brk_state, top, brk_reasons = _breaking_risk(assessments)

        risk_state = _higher(cal_state, brk_state)
        ev = cal.nearest_upcoming or cal.recent_event
        return EventRiskAssessment(
            risk_state=risk_state,
            active_event=(ev.event_name if ev else None),
            minutes_to_event=cal.minutes_to_event,
            impact_level=(ev.impact_level if ev else None),
            breaking_news_active=bool(top and top.relevance_to_nasdaq != "none"),
            breaking_category=(top.category if top else None),
            breaking_relevance=(top.relevance_to_nasdaq if top else None),
            reasons=cal_reasons + brk_reasons,
        )
    except Exception as exc:  # noqa: BLE001
        return EventRiskAssessment(
            risk_state="normal", active_event=None, minutes_to_event=None,
            impact_level=None, breaking_news_active=False,
            breaking_category=None, breaking_relevance=None,
            reasons=[f"risk_error:{exc}"])
