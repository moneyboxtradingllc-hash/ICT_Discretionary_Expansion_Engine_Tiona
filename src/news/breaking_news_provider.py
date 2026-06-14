"""NEWS-1 Phase 2 — Breaking News Intelligence.

Ingests market-moving headlines (geopolitical, war, sanctions, tariffs,
central-bank surprises, major AI/tech headlines, SEC actions, exchange/market-
infrastructure failures). NO sentiment trading — the layer only surfaces the
event so the classifier can rate relevance/risk. Read-only; never raises; never
trades. Source is a local JSON file (live feed can replace the loader later).

Breaking JSON schema (list of objects):
  {"headline","source"?,"timestamp"(ISO-8601),"category"?,"importance"?,
   "summary"?}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from news.calendar_provider import _parse_dt

# How long a breaking headline is considered "active" after its timestamp.
DEFAULT_ACTIVE_MIN = 90


@dataclass
class BreakingNewsEvent:
    headline: str
    source: Optional[str] = None
    timestamp: Optional[str] = None       # ISO-8601 (UTC)
    category: Optional[str] = None        # raw hint; classifier is authoritative
    importance: Optional[str] = None      # raw hint: low|medium|high|critical
    summary: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "BreakingNewsEvent":
        dt = _parse_dt(d.get("timestamp"))
        return cls(
            headline=str(d.get("headline", "")).strip(),
            source=d.get("source"),
            timestamp=(dt.isoformat() if dt else None),
            category=d.get("category"),
            importance=d.get("importance"),
            summary=d.get("summary"),
        )

    def minutes_since(self, now: datetime) -> Optional[float]:
        dt = _parse_dt(self.timestamp)
        if dt is None:
            return None
        return round((now - dt).total_seconds() / 60.0, 1)

    def to_dict(self) -> dict:
        return asdict(self)


class BreakingNewsProvider:
    """Loads breaking headlines from a local JSON file."""

    def __init__(self, path: Optional[str] = None,
                 active_min: int = DEFAULT_ACTIVE_MIN):
        self.path = path or os.getenv(
            "NEWS_BREAKING_PATH",
            os.path.join("data", "news", "breaking_news.json"))
        self.active_min = active_min

    def load(self) -> list:
        """Load all headlines. Returns [] on any problem (never raises)."""
        try:
            if not os.path.exists(self.path):
                return []
            with open(self.path, encoding="utf-8") as fh:
                rows = json.load(fh)
            return [BreakingNewsEvent.from_dict(r) for r in rows
                    if isinstance(r, dict) and r.get("headline")]
        except Exception:  # noqa: BLE001
            return []

    def recent(self, now=None) -> list:
        """Headlines whose age is within the active window (most recent first)."""
        now_dt = _parse_dt(now) or datetime.now(timezone.utc)
        out = []
        for ev in self.load():
            mins = ev.minutes_since(now_dt)
            if mins is not None and 0 <= mins <= self.active_min:
                out.append((ev, mins))
        out.sort(key=lambda x: x[1])
        return [ev for ev, _ in out]
