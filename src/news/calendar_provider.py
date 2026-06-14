"""NEWS-1 Phase 1 — Economic Calendar Intelligence.

Ingests scheduled macroeconomic releases and exposes, relative to a given clock,
the nearest event window the Brain needs: event_name, minutes_to_event,
impact_level, scheduled_event_window. Read-only evidence; never raises; never
trades. Source is a local JSON file (a live feed can replace the loader later
without changing the contract) — offline + deterministic = paper-safe.

Calendar JSON schema (list of objects):
  {"event_name","event_time"(ISO-8601),"impact_level"?,"country"?,
   "actual"?,"forecast"?,"previous"?}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

# Canonical macro events the layer understands (Phase 1 scope).
TRACKED_EVENTS = (
    "CPI", "Core CPI", "PPI", "Core PPI", "NFP", "Unemployment", "FOMC",
    "Powell Speech", "Fed Speaker", "Treasury Auction", "GDP",
    "Retail Sales", "ISM",
)

# Default impact when the calendar row omits impact_level.
_DEFAULT_IMPACT = {
    "CPI": "high", "Core CPI": "high", "PPI": "high", "Core PPI": "high",
    "NFP": "high", "Unemployment": "high", "FOMC": "high",
    "Powell Speech": "high", "GDP": "high",
    "Retail Sales": "medium", "ISM": "medium", "Fed Speaker": "medium",
    "Treasury Auction": "low",
}

# Window (minutes) within which an upcoming event is considered "active context".
DEFAULT_LOOKAHEAD_MIN = 60
# Window (minutes) after an event during which we still surface it (digest).
DEFAULT_DIGEST_MIN = 30


def _parse_dt(value) -> Optional[datetime]:
    """Parse ISO string / datetime to an aware UTC datetime. None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_impact(event_name: str, impact: Optional[str]) -> str:
    if impact and str(impact).lower() in ("high", "medium", "low"):
        return str(impact).lower()
    return _DEFAULT_IMPACT.get(event_name, "medium")


@dataclass
class EconomicEvent:
    event_name: str
    event_time: Optional[str]          # ISO-8601 (UTC)
    impact_level: str = "medium"       # high | medium | low
    country: str = "US"
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "EconomicEvent":
        name = str(d.get("event_name", "")).strip()
        dt = _parse_dt(d.get("event_time"))
        return cls(
            event_name=name,
            event_time=(dt.isoformat() if dt else None),
            impact_level=normalize_impact(name, d.get("impact_level")),
            country=str(d.get("country", "US")),
            actual=d.get("actual"),
            forecast=d.get("forecast"),
            previous=d.get("previous"),
        )

    def minutes_from(self, now: datetime) -> Optional[float]:
        dt = _parse_dt(self.event_time)
        if dt is None:
            return None
        return round((dt - now).total_seconds() / 60.0, 1)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EconomicCalendarSnapshot:
    """The calendar as seen at a moment in time."""
    now: str
    events: list                      # list[EconomicEvent] in the active window
    nearest_upcoming: Optional[EconomicEvent]
    minutes_to_event: Optional[float]
    scheduled_event_window: bool
    recent_event: Optional[EconomicEvent]   # just-passed (within digest window)
    minutes_since_recent: Optional[float]

    def brain_view(self) -> dict:
        """The compact, non-directional view the Brain receives (Phase 1)."""
        ev = self.nearest_upcoming or self.recent_event
        return {
            "scheduled_event_window": self.scheduled_event_window,
            "event_name": (ev.event_name if ev else None),
            "minutes_to_event": self.minutes_to_event,
            "impact_level": (ev.impact_level if ev else None),
        }

    def to_dict(self) -> dict:
        return {
            "now": self.now,
            "events": [e.to_dict() for e in self.events],
            "nearest_upcoming": self.nearest_upcoming.to_dict() if self.nearest_upcoming else None,
            "minutes_to_event": self.minutes_to_event,
            "scheduled_event_window": self.scheduled_event_window,
            "recent_event": self.recent_event.to_dict() if self.recent_event else None,
            "minutes_since_recent": self.minutes_since_recent,
        }


class EconomicCalendarProvider:
    """Loads scheduled events from a local JSON file and produces snapshots."""

    def __init__(self, path: Optional[str] = None,
                 lookahead_min: int = DEFAULT_LOOKAHEAD_MIN,
                 digest_min: int = DEFAULT_DIGEST_MIN):
        self.path = path or os.getenv(
            "NEWS_CALENDAR_PATH",
            os.path.join("data", "news", "economic_calendar.json"))
        self.lookahead_min = lookahead_min
        self.digest_min = digest_min

    def load(self) -> list:
        """Load all known events. Returns [] on any problem (never raises)."""
        try:
            if not os.path.exists(self.path):
                return []
            with open(self.path, encoding="utf-8") as fh:
                rows = json.load(fh)
            return [EconomicEvent.from_dict(r) for r in rows
                    if isinstance(r, dict) and r.get("event_name")]
        except Exception:  # noqa: BLE001
            return []

    def snapshot(self, now=None) -> EconomicCalendarSnapshot:
        now_dt = _parse_dt(now) or datetime.now(timezone.utc)
        events = self.load()

        upcoming = sorted(
            ((e, e.minutes_from(now_dt)) for e in events),
            key=lambda x: (x[1] is None, x[1] if x[1] is not None else 0))
        nearest_upcoming = next(
            (e for e, m in upcoming if m is not None and m >= 0), None)
        mins_to = nearest_upcoming.minutes_from(now_dt) if nearest_upcoming else None

        # most recent event that has just passed (within digest window)
        passed = [(e, e.minutes_from(now_dt)) for e in events]
        passed = [(e, m) for e, m in passed
                  if m is not None and -self.digest_min <= m < 0]
        passed.sort(key=lambda x: x[1], reverse=True)   # closest to now first
        recent_event = passed[0][0] if passed else None
        mins_since = round(-passed[0][1], 1) if passed else None

        in_window = bool(
            (mins_to is not None and mins_to <= self.lookahead_min)
            or recent_event is not None)

        active = [e for e, m in upcoming
                  if m is not None and 0 <= m <= self.lookahead_min]
        if recent_event is not None:
            active = [recent_event] + active

        return EconomicCalendarSnapshot(
            now=now_dt.isoformat(),
            events=active,
            nearest_upcoming=nearest_upcoming,
            minutes_to_event=mins_to,
            scheduled_event_window=in_window,
            recent_event=recent_event,
            minutes_since_recent=mins_since,
        )
