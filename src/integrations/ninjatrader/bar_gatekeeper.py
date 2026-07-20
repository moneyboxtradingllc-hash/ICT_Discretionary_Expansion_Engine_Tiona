"""Phase 7 — Market-data invariants and health states for MNQ bars.

The gatekeeper stands between the NinjaTrader bridge and the organism's
snapshot builder. It enforces that only trustworthy, correctly-attributed,
ordered, non-duplicate completed 1-minute bars from the EXACT resolved MNQ
expiry ever reach the organism.

Health states:
  CONNECTED_HEALTHY | CONNECTED_STALE | CONNECTED_GAPPED | DISCONNECTED |
  WRONG_INSTRUMENT | WRONG_EXPIRY | UNKNOWN

The gatekeeper NEVER has trade authority. Unhealthy data denies FRESH entries;
it does not (and cannot) disable existing position protection.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

CONNECTED_HEALTHY = "CONNECTED_HEALTHY"
CONNECTED_STALE = "CONNECTED_STALE"
CONNECTED_GAPPED = "CONNECTED_GAPPED"
DISCONNECTED = "DISCONNECTED"
WRONG_INSTRUMENT = "WRONG_INSTRUMENT"
WRONG_EXPIRY = "WRONG_EXPIRY"
UNKNOWN = "UNKNOWN"

_FRESH_ENTRY_OK = frozenset({CONNECTED_HEALTHY})


class BarRejected(ValueError):
    pass


@dataclass
class BarAcceptance:
    accepted: bool
    reason: str
    duplicate: bool = False
    out_of_order: bool = False
    gap: bool = False


@dataclass
class BarGatekeeper:
    """Stateful, single-instrument bar acceptor.

    `expected_instrument` is the exact resolved MNQ expiry name. Bars whose
    instrument/expiry differ are rejected AND flip health to WRONG_*.
    """
    expected_instrument: str
    expected_expiry: str
    stale_seconds: float = 120.0     # a 1m bar older than this = stale
    _last_bar_ts: Optional[_dt.datetime] = field(default=None, init=False)
    _seen_ts: set = field(default_factory=set, init=False)
    health: str = field(default=UNKNOWN, init=False)
    last_reason: str = field(default="", init=False)

    def _coerce_ts(self, ts) -> _dt.datetime:
        if isinstance(ts, _dt.datetime):
            dt = ts
        else:
            dt = _dt.datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            raise BarRejected(f"bar timestamp {ts!r} is timezone-naive")
        return dt

    def accept_bar(self, bar: dict, now: Optional[_dt.datetime] = None) -> BarAcceptance:
        """Validate one completed 1-minute bar. Updates health as a side effect."""
        now = now or _dt.datetime.now(_dt.timezone.utc)

        instrument = str(bar.get("instrument", "")).strip()
        expiry = str(bar.get("expiry", "")).strip()

        if instrument and instrument.upper() != str(self.expected_instrument).upper():
            self.health = WRONG_INSTRUMENT
            self.last_reason = f"bar instrument {instrument!r} != {self.expected_instrument!r}"
            return BarAcceptance(False, self.last_reason)
        if expiry and expiry != str(self.expected_expiry):
            self.health = WRONG_EXPIRY
            self.last_reason = f"bar expiry {expiry!r} != {self.expected_expiry!r}"
            return BarAcceptance(False, self.last_reason)

        try:
            ts = self._coerce_ts(bar.get("timestamp"))
        except BarRejected as exc:
            self.last_reason = str(exc)
            return BarAcceptance(False, self.last_reason)

        # No future timestamp.
        if ts > now + _dt.timedelta(seconds=1):
            self.last_reason = f"future-dated bar {ts.isoformat()} > now {now.isoformat()}"
            return BarAcceptance(False, self.last_reason)

        # No duplicate bar.
        key = ts.astimezone(_dt.timezone.utc).replace(microsecond=0)
        if key in self._seen_ts:
            self.last_reason = f"duplicate bar {ts.isoformat()}"
            return BarAcceptance(False, self.last_reason, duplicate=True)

        # Ordering / gap detection against the last accepted bar.
        out_of_order = False
        gap = False
        if self._last_bar_ts is not None:
            delta = (key - self._last_bar_ts).total_seconds()
            if delta <= 0:
                out_of_order = True
                self.last_reason = (f"out-of-order bar {ts.isoformat()} "
                                    f"<= last {self._last_bar_ts.isoformat()}")
                # Surface, do NOT silently accept.
                return BarAcceptance(False, self.last_reason, out_of_order=True)
            if delta > 60:
                gap = True

        # Accept.
        self._seen_ts.add(key)
        self._last_bar_ts = key

        # Health from freshness/gap.
        age = (now - key).total_seconds()
        if gap:
            self.health = CONNECTED_GAPPED
        elif age > self.stale_seconds:
            self.health = CONNECTED_STALE
        else:
            self.health = CONNECTED_HEALTHY
        self.last_reason = "accepted"
        return BarAcceptance(True, "accepted", gap=gap)

    def mark_disconnected(self):
        self.health = DISCONNECTED
        self.last_reason = "connection lost"

    def mark_gap(self):
        self.health = CONNECTED_GAPPED
        self.last_reason = "reconnection gap surfaced"

    def fresh_entry_ready(self) -> bool:
        """Only CONNECTED_HEALTHY permits fresh entries. Everything else denies."""
        return self.health in _FRESH_ENTRY_OK
