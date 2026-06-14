"""NEWS-1 Phase 6 — News Memory (storage only, NO learning logic yet).

Persists how the market responded to past events so a FUTURE phase can let the
Brain ask "have I seen this type of event before?". NEWS-1 only stores and
recalls — there is deliberately no inference, scoring, or learning here.
Read/write only; never raises; never trades.

Record schema:
  {"event","timestamp","direction_before","direction_after",
   "market_response","volatility_profile","recorded_at"}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional


def _store_path() -> str:
    base = os.getenv("NEWS_MEMORY_DIR", os.path.join("data", "news"))
    return os.path.join(base, "news_memory.jsonl")


@dataclass
class NewsMemoryRecord:
    event: str
    timestamp: Optional[str] = None        # when the event occurred (ISO)
    direction_before: Optional[str] = None
    direction_after: Optional[str] = None
    market_response: Optional[str] = None  # free text, e.g. "rallied 140 pts"
    volatility_profile: Optional[str] = None
    recorded_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class NewsMemory:
    """Append-only JSONL store of event→response observations."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _store_path()

    def record(self, record: NewsMemoryRecord) -> bool:
        """Append one observation. Returns True on success (never raises)."""
        try:
            if not record.recorded_at:
                record.recorded_at = datetime.now(timezone.utc).isoformat()
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), default=str) + "\n")
            return True
        except Exception:  # noqa: BLE001
            return False

    def all(self) -> list:
        """Return every stored record. [] on any problem (never raises)."""
        try:
            if not os.path.exists(self.path):
                return []
            out = []
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
            return out
        except Exception:  # noqa: BLE001
            return []

    def by_event(self, event_name: str) -> list:
        """Recall prior observations for an event type (exact, case-insensitive).
        Storage/recall only — NO learning/inference (deferred to a later phase)."""
        name = (event_name or "").lower().strip()
        return [r for r in self.all()
                if str(r.get("event", "")).lower().strip() == name]
