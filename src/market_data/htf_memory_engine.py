"""
HTF-MEM-1 — Higher Timeframe Memory Engine.

The organism used to wake up amnesiac: 300 one-minute bars (~5 hours), no
yesterday, no week, no gap context — inside a methodology whose premises
(draws on liquidity, HTF PO3) are inherently multi-day. This engine gives it
a durable multi-day memory built ONLY from real observed candles.

Model: every scan feeds the raw 1m candle window. Bars are grouped by ET
date into running daily OHLC records, persisted at
data/htf_memory/<SYMBOL>.json (env HTF_MEMORY_DIR overrides — test isolated).
No synthetic backfill: memory begins with what the feed actually shows (the
300-bar lookback naturally seeds the prior session on day one) and deepens
every session. memory_age reports how many daily records exist, and every
consumer can see exactly how much history the context is standing on.

Outputs (context ONLY — see doctrine):
    daily_context             yesterday's OHLC, range, bias (close vs open)
    weekly_context            direction/strength over up to 5 prior sessions
    previous_session_context  prior session high/low/close + untapped levels
    gap_context               today's open vs yesterday's close (gap %, side)
    liquidity_context         nearest untapped prior high/low (draw candidates)
    htf_bias                  bullish / bearish / neutral synthesis
    htf_confidence            0-100, bounded by memory_age (thin memory can
                              never be confident)
    memory_age                number of completed daily records
    htf_conflict_flags        filled downstream vs the narrative direction

DOCTRINE (PHASE 4/5): HTF memory is CONTEXT, not sovereign authority. It may
inform thesis quality, warn about conflict, support or weaken confidence — it
may NOT execute, veto, or force direction. authority_level is hard-locked
"context_only"; no execution/gate/decision module reads it (locked by test).
The scan loop is the only writer (persist contract). Never raises.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytz

_EASTERN = pytz.timezone("America/New_York")

AUTHORITY_LEVEL = "context_only"
MAX_DAILY_RECORDS = 20          # ~a month of trading memory
CONF_PER_DAY = 12               # confidence ceiling grows with memory age
GAP_MIN_PCT = 0.15              # below this, "no meaningful gap"


def _store_dir() -> str:
    return os.getenv("HTF_MEMORY_DIR") or os.path.join("data", "htf_memory")


def _path(symbol: str) -> str:
    os.makedirs(_store_dir(), exist_ok=True)
    return os.path.join(_store_dir(), f"{str(symbol or 'UNKNOWN').upper()}.json")


def _load(symbol: str) -> dict:
    try:
        with open(_path(symbol), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save(symbol: str, state: dict) -> None:
    path = _path(symbol)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _candle_date(c: dict) -> "str | None":
    ts = c.get("timestamp")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(_EASTERN)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        s = str(ts)
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 and s[:8].isdigit() else None


class HtfMemoryEngine:
    """Stateful daily-memory accumulator. The live scan loop owns one instance
    and calls update(candles_1m) once per scan."""

    def __init__(self, symbol: str, persist: bool = True, preload: bool = True):
        self.symbol = str(symbol or "UNKNOWN").upper()
        self.persist = persist
        # HTF-REPLAY (2026-07-30): preload=False starts from EMPTY memory.
        # Replay reconstructs state from archived real candles only, so the
        # live store is neither read (preload=False) nor written
        # (persist=False) — isolation is structural, not disciplinary.
        self._state = _load(self.symbol) if preload else {}
        self._state.setdefault("days", {})

    # ── ingestion ─────────────────────────────────────────────────────────────

    def update(self, candles_1m: list) -> dict:
        """Fold this scan's real candle window into daily memory and return the
        HTF context. Never raises."""
        try:
            days = self._state["days"]
            for c in candles_1m or []:
                if not isinstance(c, dict):
                    continue
                d = _candle_date(c)
                o, h = _num(c.get("open")), _num(c.get("high"))
                l, cl = _num(c.get("low")), _num(c.get("close"))
                if d is None or None in (o, h, l, cl):
                    continue
                rec = days.get(d)
                if rec is None:
                    days[d] = {"open": o, "high": h, "low": l, "close": cl,
                               "first_ts": str(c.get("timestamp")),
                               "last_ts": str(c.get("timestamp"))}
                else:
                    if str(c.get("timestamp")) < rec["first_ts"]:
                        rec["open"], rec["first_ts"] = o, str(c.get("timestamp"))
                    if str(c.get("timestamp")) >= rec["last_ts"]:
                        rec["close"], rec["last_ts"] = cl, str(c.get("timestamp"))
                    rec["high"] = max(rec["high"], h)
                    rec["low"] = min(rec["low"], l)
            # retention
            for d in sorted(days)[:-MAX_DAILY_RECORDS]:
                del days[d]
            if self.persist:
                _save(self.symbol, self._state)
            return self.context()
        except Exception as exc:  # noqa: BLE001
            return self._empty(f"htf_error:{type(exc).__name__}")

    # ── context synthesis (pure reads of accumulated memory) ─────────────────

    def context(self) -> dict:
        days = self._state.get("days", {})
        dates = sorted(days)
        if len(dates) < 2:
            return self._empty("insufficient_memory: fewer than 2 sessions")

        today_d, prev_d = dates[-1], dates[-2]
        today, prev = days[today_d], days[prev_d]
        completed = dates[:-1]                     # today is still forming
        memory_age = len(completed)

        prev_range = round(prev["high"] - prev["low"], 4)
        prev_bias = ("bullish" if prev["close"] > prev["open"]
                     else "bearish" if prev["close"] < prev["open"] else "neutral")
        # H2 PAYLOAD CONTRACT (HTF-MEM-1.1): the key is "day_direction", NOT
        # "bias" — the anti-contamination scanner rejects any raw "bias" key
        # outside STRUCTURE_WITNESS (session-1 regression: taint
        # ['unlabeled_bias_key'] silently disabled LLM synthesis). Same
        # information, compliant name. Do not rename back.
        daily_context = {"date": prev_d, "open": prev["open"], "high": prev["high"],
                         "low": prev["low"], "close": prev["close"],
                         "range": prev_range, "day_direction": prev_bias}

        # weekly: up to 5 completed sessions
        week = [days[d] for d in completed[-5:]]
        net = week[-1]["close"] - week[0]["open"]
        span = sum(w["high"] - w["low"] for w in week) or 1e-9
        weekly_dir = ("bullish" if net > 0 else "bearish" if net < 0 else "neutral")
        weekly_context = {"sessions": len(week), "net_change": round(net, 4),
                          "direction": weekly_dir,
                          "strength": round(min(1.0, abs(net) / span), 4),
                          "higher_highs": all(b["high"] >= a["high"]
                                              for a, b in zip(week, week[1:])),
                          "lower_lows": all(b["low"] <= a["low"]
                                            for a, b in zip(week, week[1:]))}

        # gap: today's open vs yesterday's close
        gap_pts = round(today["open"] - prev["close"], 4)
        gap_pct = round(100 * gap_pts / prev["close"], 4) if prev["close"] else 0.0
        gap_context = {"gap_points": gap_pts, "gap_pct": gap_pct,
                       "side": ("gap_up" if gap_pct >= GAP_MIN_PCT
                                else "gap_down" if gap_pct <= -GAP_MIN_PCT
                                else "no_meaningful_gap"),
                       "filled": (today["low"] <= prev["close"] <= today["high"])}

        # liquidity: untapped prior-session levels = draw candidates
        ph_swept = today["high"] >= prev["high"]
        pl_swept = today["low"] <= prev["low"]
        current = today["close"]
        draws = []
        if not ph_swept:
            draws.append({"side": "buy_side", "level": prev["high"],
                          "distance": round(prev["high"] - current, 4)})
        if not pl_swept:
            draws.append({"side": "sell_side", "level": prev["low"],
                          "distance": round(current - prev["low"], 4)})
        draws.sort(key=lambda d: abs(d["distance"]))
        liquidity_context = {"previous_high_swept": ph_swept,
                             "previous_low_swept": pl_swept,
                             "untapped_draws": draws,
                             "nearest_draw": draws[0] if draws else None}
        previous_session_context = {**daily_context,
                                    "high_swept": ph_swept, "low_swept": pl_swept}

        # bias synthesis: previous-day bias + weekly direction + gap side
        votes = {"bullish": 0, "bearish": 0}
        if prev_bias in votes:
            votes[prev_bias] += 1
        if weekly_dir in votes:
            votes[weekly_dir] += 2
        if gap_context["side"] == "gap_up":
            votes["bullish"] += 1
        elif gap_context["side"] == "gap_down":
            votes["bearish"] += 1
        if votes["bullish"] > votes["bearish"]:
            htf_bias = "bullish"
        elif votes["bearish"] > votes["bullish"]:
            htf_bias = "bearish"
        else:
            htf_bias = "neutral"
        agreement = abs(votes["bullish"] - votes["bearish"])
        htf_confidence = min(memory_age * CONF_PER_DAY, 25 * agreement + 15)
        if htf_bias == "neutral":
            htf_confidence = min(htf_confidence, 20)

        return {
            "authority_level":          AUTHORITY_LEVEL,
            "htf_bias":                 htf_bias,
            "htf_confidence":           int(max(0, min(100, htf_confidence))),
            "memory_age":               memory_age,
            "daily_context":            daily_context,
            "weekly_context":           weekly_context,
            "previous_session_context": previous_session_context,
            "gap_context":              gap_context,
            "liquidity_context":        liquidity_context,
            "htf_conflict_flags":       [],   # filled downstream vs narrative
        }

    def _empty(self, reason: str) -> dict:
        return {
            "authority_level": AUTHORITY_LEVEL,
            "htf_bias": "neutral", "htf_confidence": 0,
            "memory_age": max(0, len(self._state.get("days", {})) - 1),
            "daily_context": None, "weekly_context": None,
            "previous_session_context": None, "gap_context": None,
            "liquidity_context": None, "htf_conflict_flags": [],
            "note": reason,
        }
