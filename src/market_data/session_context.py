"""CROSS-SESSION CONTEXT — what Asia, London and premarket already did.

LUNA-CROSS-SESSION-PO3-CONTEXT-1 (2026-08-30).

WHAT WAS MISSING. The forensic audit found that `overnight_high`, `london_high`
and their siblings were VOCABULARY WITH NO PRODUCER: valid objective kinds Luna
could name and nothing could price. `session_engine` labels 04:00-20:00 ET and
calls everything else "closed", so Asia and London did not exist as concepts at
all — while the durable tape carried full 23-hour coverage nobody ever read.
The organism looked back 300 minutes and never saw the night it had recorded.

WHAT THIS IS NOT. It is not a phase authority. `session_po3` decides whether a
new entry may exist, and this module has no route into that decision — no
parameter, no import, no callback. That separation is STRUCTURAL, not a promise
enforced by a test: `session_po3.derive()` has no argument through which a prior
session could speak. London delivering hard all morning cannot make New York's
accumulation tradeable, and the code offers no way to express that it could.

    CANONICAL 1M TAPE
           |
     +-----+-----+
     |           |
 SESSION PO3   SESSION CONTEXT
 mechanical    contextual
 authority     evidence
     |           |
     +-----+-----+
           v
         LUNA

EXACT COVERAGE, AND WHY IT COST A WHOLE PREREQUISITE UNIT. A context is
AVAILABLE only when EVERY venue-expected settled 1m bucket in its window is
present — no percentage threshold, no interpolation, no shrinking the window
around whatever history happens to exist. Making that claim provable is why
VENUE-CALENDAR-AUTHORITY-HORIZON-1 had to land first: `expected_buckets` is the
only thing that knows how many minutes the venue was scheduled to print, and
until 2026-08-30 its authority expired on 2026-08-31.

So when this module says "London range available", the word available now means
something a machine checked.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytz

from market_data import venue_calendar as VC

SCHEMA = "session_context.v1"

EASTERN = pytz.timezone("America/New_York")

# ── status vocabulary ─────────────────────────────────────────────────────────
NOT_YET_STARTED = "NOT_YET_STARTED"
IN_PROGRESS = "IN_PROGRESS"
AVAILABLE = "AVAILABLE"
UNAVAILABLE_HISTORY = "UNAVAILABLE_HISTORY"

STATUSES = (NOT_YET_STARTED, IN_PROGRESS, AVAILABLE, UNAVAILABLE_HISTORY)

#: Statuses that may carry derived market facts. The other two publish NOTHING:
#: a window that has not begun has no range, and a window whose history is
#: incomplete must not offer a high/low that looks like the whole story.
_FACT_BEARING = (IN_PROGRESS, AVAILABLE)

# ── the owner-defined strategic windows ───────────────────────────────────────
#
# THESE ARE STRATEGY SEMANTICS, NOT VENUE SEMANTICS. The CME day boundary comes
# from `venue_calendar`; these four windows are the operator's, frozen
# 2026-08-30, and are deliberately NOT derived from any exchange's local hours.
#
# ASIA_CONTEXT is ET-anchored and is NOT "the Tokyo cash session": Japan does not
# observe DST, so this window tracks the Tokyo open during EST and sits an hour
# later during EDT. That drift is accepted and recorded rather than corrected.
#
# LONDON_KILLZONE and LONDON_SESSION ARE NOT SYNONYMS. The killzone is the sharp
# window; the session answers "what has London delivered by now", which is the
# question that matters at the New York open — a London expansion running
# 05:00-08:00 belongs to the session and would be invisible to the killzone.
#
#   name, start (ET), end (ET), starts_on_previous_calendar_day
_WINDOWS = (
    ("ASIA_CONTEXT",    time(20, 0), time(0, 0),  True),
    ("LONDON_KILLZONE", time(2, 0),  time(5, 0),  False),
    ("LONDON_SESSION",  time(3, 0),  time(11, 30), False),
    ("NY_PREMARKET",    time(4, 0),  time(9, 30), False),
)

CONTEXT_NAMES = tuple(name for name, *_ in _WINDOWS)

#: Which context each one measures its excursions against. A fixed chain, so the
#: comparison is a stated relationship rather than "whatever ran before".
_PRIOR = {
    "LONDON_KILLZONE": "ASIA_CONTEXT",
    "LONDON_SESSION": "ASIA_CONTEXT",
    "NY_PREMARKET": "LONDON_SESSION",
}

#: ET spans inside the CME day that belong to NO named strategic context. They
#: are real trading minutes and they are deliberately unassigned — reported so a
#: reader can see the choice, never quietly folded into a neighbour. Adding a
#: fifth context to "cover the gaps" is precisely what this list exists to stop.
EXCLUDED_SPANS = (
    (time(18, 0), time(20, 0)),   # the reopen, before Asia
    (time(0, 0), time(2, 0)),     # after Asia, before the London killzone
)

#: The CME trading day, sourced from the venue calendar's own constants so there
#: is exactly one owner of "when does the day turn over".
DAY_START_HOUR = VC.WEEKLY_OPEN_HOUR      # 18:00 ET
DAY_END_HOUR = VC.WEEKLY_CLOSE_HOUR       # 17:00 ET

#: Deep 1m history the producer needs. PROVEN, not assumed: the earliest bar any
#: context can require is the CME day open at 18:00 ET the previous day, and the
#: latest moment production decides anything is 14:00 ET
#: (`topstepx_session_authorization.PRODUCTION_WINDOW_END`). Measured with
#: `venue_calendar.expected_buckets` on both an ordinary Tuesday and a Monday
#: whose day opens at the Sunday 18:00 reopen: 1199 expected buckets, worst case.
#: 1500 carries a 301-bar margin. See tests/test_cross_session_context.py.
DEEP_HISTORY_BARS = 1500


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _et(value):
    """Any timestamp -> Eastern. Returns None rather than guessing."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime):
        return None
    return (EASTERN.localize(value) if value.tzinfo is None
            else value.astimezone(EASTERN))


def trading_day(moment) -> "str | None":
    """The CME trading DATE a moment belongs to.

    The day runs 18:00 ET the previous calendar day to 17:00 ET on its own date,
    so a bar printed at 21:00 on the 3rd belongs to the 4th. The 17:00-18:00
    maintenance hour is assigned forward: no bar exists there, and the next thing
    to happen is the new day opening.
    """
    et = _et(moment)
    if et is None:
        return None
    day = et.date()
    if et.time() >= time(DAY_END_HOUR, 0):
        day = day + timedelta(days=1)
    return day.isoformat()


def _resolve(name: str, start: time, end: time, prev_day: bool, day: str) -> dict:
    """Absolute ET bounds of one window inside trading day `day`."""
    d = datetime.fromisoformat(day).date()
    start_date = d - timedelta(days=1) if prev_day else d
    end_date = d
    lo = EASTERN.localize(datetime.combine(start_date, start))
    hi = EASTERN.localize(datetime.combine(end_date, end))
    return {"name": name, "start_et": start.strftime("%H:%M"),
            "end_et": end.strftime("%H:%M"),
            "starts_previous_day": prev_day,
            "start": lo.isoformat(), "end": hi.isoformat(),
            "_lo": lo, "_hi": hi}


def _expected_slots(lo: datetime, hi: datetime) -> "list | None":
    """Every 1m slot the venue was scheduled to print in [lo, hi].

    None means the calendar has no jurisdiction — a KNOWN_SPECIAL date whose
    exact hours are not encoded, or a date outside verified authority. That is
    NOT an empty schedule, and the caller must not read it as one: it is the
    §9 residue the horizon unit closed elsewhere, and it fails closed here.
    """
    if VC.cadence_authority_over(lo, hi)["authority"] != VC.CADENCE_KNOWN:
        return None
    # `expected_buckets` is exclusive of both endpoints; widen by a minute on
    # each side so the window's own first and last minutes are included.
    return VC.expected_buckets(lo - timedelta(minutes=1),
                               hi + timedelta(minutes=1), 1)


def _facts(bars: list) -> dict:
    """Descriptive facts over the bars inside a window. No opinion, no verdict."""
    opens = [b for b in bars if _num(b.get("open")) is not None]
    if not opens:
        return {}
    highs = [_num(b.get("high")) for b in bars if _num(b.get("high")) is not None]
    lows = [_num(b.get("low")) for b in bars if _num(b.get("low")) is not None]
    first_open = _num(opens[0].get("open"))
    last_close = _num(opens[-1].get("close"))
    hi, lo = max(highs), min(lows)
    rng = round(hi - lo, 4)
    net = round((last_close - first_open), 4) if last_close is not None else None
    # DELIVERY IS NET TRAVEL AGAINST THE RANGE IT PAID FOR. A session that
    # travelled 40 points to close 2 from where it opened delivered nothing,
    # however wide it looks.
    delivery, share = "balanced", None
    if net is not None and rng > 0:
        share = round(abs(net) / rng, 3)
        if share >= 0.5:
            delivery = "bullish" if net > 0 else "bearish"
    return {"open": first_open, "high": hi, "low": lo, "range": rng,
            "last_close": last_close, "net_travel": net,
            "directional_delivery": delivery, "delivery_share_of_range": share,
            "balanced_or_expanded": "expanded" if (share or 0) >= 0.5 else "balanced",
            "bars": len(bars)}


def _expansion(bars: list) -> dict:
    """The EXISTING expansion ontology, applied to this window's bars.

    Deliberately reuses `detect_expansion` rather than defining a second notion
    of expansion. Timeframe is 1m because these are 1m bars, so the VECTOR-3
    magnitude floor for 1m applies unchanged.
    """
    try:
        from volatility.atr_engine import calculate_atr
        from volatility.expansion_detector import detect_expansion
        atr = calculate_atr(bars)
        out = detect_expansion(bars, atr, "1m")
        return {"state": out.get("state"),
                "displacement_detected": bool(out.get("displacement_detected")),
                "directional_efficiency": out.get("directional_efficiency"),
                "magnitude_gated": bool(out.get("magnitude_gated"))}
    except Exception as exc:  # noqa: BLE001 — evidence must not break the scan
        return {"state": None, "error": f"{type(exc).__name__}"}


def _excursion(name: str, facts: dict, done: dict) -> dict:
    """Did this context take the prior context's high or low?"""
    prior_name = _PRIOR.get(name)
    if not prior_name:
        return {"prior_context": None, "comparable": False,
                "reason": "no prior context in the chain"}
    prior = done.get(prior_name) or {}
    pf = prior.get("facts") or {}
    if prior.get("status") not in _FACT_BEARING or not pf:
        return {"prior_context": prior_name, "comparable": False,
                "reason": f"{prior_name} is {prior.get('status', 'absent')}"}
    return {"prior_context": prior_name, "comparable": True,
            "prior_high": pf.get("high"), "prior_low": pf.get("low"),
            "took_prior_high": bool(facts.get("high") is not None
                                    and facts["high"] > pf["high"]),
            "took_prior_low": bool(facts.get("low") is not None
                                   and facts["low"] < pf["low"])}


def _excluded(bars_by_min: dict, day: str) -> list:
    """The trading minutes that belong to no named context, named out loud."""
    d = datetime.fromisoformat(day).date()
    out = []
    for lo_t, hi_t in EXCLUDED_SPANS:
        start_date = d - timedelta(days=1) if lo_t >= time(DAY_START_HOUR, 0) else d
        lo = EASTERN.localize(datetime.combine(start_date, lo_t))
        hi = EASTERN.localize(datetime.combine(start_date if lo_t < hi_t else d, hi_t))
        observed = sum(1 for k in bars_by_min if lo <= k < hi)
        out.append({"start_et": lo_t.strftime("%H:%M"),
                    "end_et": hi_t.strftime("%H:%M"),
                    "start": lo.isoformat(), "end": hi.isoformat(),
                    "observed_bars": observed,
                    "assigned_to": None})
    return out


def derive(*, settled_1m: list, as_of=None) -> dict:
    """Cross-session context over the canonical settled 1m tape. PURE.

    No wall clock decides anything: `as_of` defaults to the newest settled bar,
    so live, a restart rebuild and a replay reading the same bars produce the
    same answer. Nothing here reads a position, an order, a risk number or a
    Brain output.
    """
    bars = [b for b in (settled_1m or []) if isinstance(b, dict)]
    by_min = {}
    for b in bars:
        k = _et(b.get("timestamp"))
        if k is not None:
            by_min[k.replace(second=0, microsecond=0)] = b

    at = _et(as_of) if as_of is not None else (max(by_min) if by_min else None)
    day = trading_day(at) if at is not None else None

    out = {"schema": SCHEMA, "trading_day": day,
           "as_of": at.isoformat() if at else None,
           "cme_trading_day": None, "contexts": {}, "excluded_spans": [],
           "settled_bars": len(bars)}
    if day is None:
        out["reason"] = "no settled history: no trading day can be established"
        return out

    d = datetime.fromisoformat(day).date()
    out["cme_trading_day"] = {
        "date": day,
        "start": EASTERN.localize(datetime.combine(
            d - timedelta(days=1), time(DAY_START_HOUR, 0))).isoformat(),
        "end": EASTERN.localize(datetime.combine(
            d, time(DAY_END_HOUR, 0))).isoformat(),
        "source": "market_data.venue_calendar",
    }

    for name, start, end, prev_day in _WINDOWS:
        win = _resolve(name, start, end, prev_day, day)
        lo, hi = win.pop("_lo"), win.pop("_hi")
        block = {"name": name, "window": win, "status": None,
                 "coverage": None, "facts": None, "expansion": None,
                 "excursions_vs_prior_context": None}

        if at < lo:
            block["status"] = NOT_YET_STARTED
            block["reason"] = "the window has not begun in this trading day"
            out["contexts"][name] = block
            continue

        complete = at >= hi
        edge = hi if complete else at
        slots = _expected_slots(lo, edge)
        if slots is None:
            block["status"] = UNAVAILABLE_HISTORY
            block["reason"] = ("venue cadence authority is unavailable for this "
                               "window; expected coverage cannot be established")
            block["coverage"] = {"expected_bars": None, "observed_bars": None,
                                 "missing_bars": None, "as_of": at.isoformat()}
            out["contexts"][name] = block
            continue

        expected = {s.replace(second=0, microsecond=0) for s in slots}
        observed = {k for k in expected if k in by_min}
        missing = sorted(expected - observed)
        block["coverage"] = {
            "expected_bars": len(expected), "observed_bars": len(observed),
            "missing_bars": len(missing),
            "first_missing": missing[0].isoformat() if missing else None,
            "first_bar": min(observed).isoformat() if observed else None,
            "last_bar": max(observed).isoformat() if observed else None,
            "as_of": at.isoformat(),
            "window_complete": complete,
        }

        # EXACT COVERAGE. One missing expected minute is enough: a range built
        # from a window with a hole in it is a different window wearing this
        # one's name.
        if missing or not expected:
            block["status"] = UNAVAILABLE_HISTORY
            block["reason"] = (
                f"{len(missing)} of {len(expected)} expected settled minutes are "
                f"absent" if expected else
                "the venue was scheduled to print nothing in this window")
            out["contexts"][name] = block
            continue

        window_bars = [by_min[k] for k in sorted(observed)]
        block["status"] = AVAILABLE if complete else IN_PROGRESS
        block["facts"] = _facts(window_bars)
        block["expansion"] = _expansion(window_bars)
        block["excursions_vs_prior_context"] = _excursion(
            name, block["facts"], out["contexts"])
        block["reason"] = (
            f"every one of {len(expected)} expected settled minutes is present"
            + ("" if complete else f", causal through {at.isoformat()}"))
        out["contexts"][name] = block

    out["excluded_spans"] = _excluded(by_min, day)
    return out


def brain_block(context: dict) -> dict:
    """The compact form published to Luna. Absence is stated, never faked."""
    ctx = (context or {}).get("contexts") or {}
    if not ctx:
        return {"available": False, "trading_day": None, "contexts": {}}
    out = {}
    for name, block in ctx.items():
        status = block.get("status")
        row = {"status": status}
        if status in _FACT_BEARING:
            f = block.get("facts") or {}
            e = block.get("excursions_vs_prior_context") or {}
            row.update(high=f.get("high"), low=f.get("low"), range=f.get("range"),
                       delivery=f.get("directional_delivery"),
                       balanced_or_expanded=f.get("balanced_or_expanded"),
                       expansion=(block.get("expansion") or {}).get("state"),
                       took_prior_high=e.get("took_prior_high"),
                       took_prior_low=e.get("took_prior_low"),
                       as_of=(block.get("coverage") or {}).get("as_of"))
        else:
            # NO FACTS. Not zeroes, not nulls that read as values -- the reason.
            row["reason"] = block.get("reason")
        out[name] = row
    return {"available": True, "trading_day": (context or {}).get("trading_day"),
            "as_of": (context or {}).get("as_of"), "contexts": out,
            "note": "prior-session context. Interpretation only; it does not "
                    "authorize entries and never sets the session PO3 phase."}
