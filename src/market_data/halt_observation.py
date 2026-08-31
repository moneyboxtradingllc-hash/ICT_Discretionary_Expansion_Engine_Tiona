"""What does a ProjectX historical bar during a CME halt actually mean?

BAR-HALT-OBSERVATION-1 (2026-08-18).

THE CONTRADICTION. CME publishes a daily 16:15-16:30 ET trading halt for Micro
E-mini equity index futures, including MNQ. The canonical store for 2026-08-17
holds a bar for all fifteen of those minutes, with changing OHLC and volume
between 129 and 1155 -- while holding NO bar for any of the sixty
17:00-18:00 ET maintenance minutes. 1380 bars = 1440 - 60. The same file, the
same day and the same timestamp convention corroborate one scheduled break and
contradict the other, which rules out a timezone or bucket-label displacement.

WHAT IS NOT PROVEN. That ProjectX is wrong. `/api/History/retrieveBars` is
documented as returning aggregated bars `t/o/h/l/c/v`; nothing in that contract
promises a bar implies executed trades in the interval. A continuous chart
series through a halt may be entirely intentional on their side.

WHAT WOULD BE OURS. The inference the bot currently makes:

    a historical bar exists  ->  the market had an opportunity to trade

`evidence_continuity` leans on exactly that when it decides whether a zero
observation count is evidence or silence. If a history bar is not a trade
observation, then history-bar presence may not own `opportunity_to_observe`.

HOW THIS SETTLES IT. ProjectX exposes `GatewayTrade` (real-time MARKET TRADE
events) separately from `GatewayQuote` and separately from the history endpoint.
Recording the live trade stream across a halt and then asking the history
endpoint what it thinks happened in those same minutes yields four independent
propositions, and no order is required to obtain any of them.

This module owns the pure half: normalisation that never discards contradictory
evidence, minute-matrix construction, and the adjudication state machine. The
capture runner lives in `tools/topstepx_halt_observer.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

#: Event families. A quote is NOT a trade, and neither is a bar. They are kept
#: apart everywhere because collapsing them is precisely the inference under
#: audit.
TRADE = "trade"
QUOTE = "quote"
DEPTH = "depth"

#: Adjudication outcomes.
CASE_A_BAR_IS_NOT_TRADE_EVIDENCE = "history_bar_is_not_trade_evidence"
CASE_B_QUOTES_ONLY = "quotes_continued_no_trades"
CASE_C_INDEPENDENT_SERIES = "history_series_independent_of_live_stream"
CASE_D_TRADES_DURING_HALT = "trades_observed_during_published_halt"
INCONCLUSIVE = "inconclusive_no_history_bars"
NOT_OBSERVED = "window_not_observed"

#: Calendar annotations. Deliberately our own labels: the venue calendar is the
#: authority on the SCHEDULE, and this module never lets it suppress capture.
PRE_HALT = "pre_halt"
IN_HALT = "scheduled_intraday_trading_halt"
POST_HALT = "post_halt"


def _as_utc(moment) -> datetime | None:
    if moment is None:
        return None
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def minute_key(moment) -> str | None:
    """The 1m bucket a moment belongs to, as an ISO UTC minute."""
    utc = _as_utc(moment)
    return None if utc is None else utc.replace(second=0, microsecond=0).isoformat()


def halt_window(date_et, start=(16, 15), end=(16, 30)) -> tuple:
    """The published CME halt for `date_et`, resolved through America/New_York.

    No hardcoded UTC offset: the window is built in ET and converted, so it is
    correct on both sides of a DST transition.
    """
    lo = datetime(date_et.year, date_et.month, date_et.day, start[0], start[1], tzinfo=ET)
    hi = datetime(date_et.year, date_et.month, date_et.day, end[0], end[1], tzinfo=ET)
    return lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)


def classify_against_halt(moment, window: tuple) -> str:
    """Annotate a moment relative to the halt. ANNOTATION ONLY.

    A trade timestamped inside the halt is labelled `IN_HALT` and KEPT. Evidence
    that contradicts the schedule is the entire point of the exercise; a filter
    that dropped it would guarantee the experiment could only confirm what we
    already believe.
    """
    utc = _as_utc(moment)
    lo, hi = window
    if utc is None:
        return "unknown_timestamp"
    if utc < lo:
        return PRE_HALT
    if utc >= hi:
        return POST_HALT
    return IN_HALT


def normalise_event(*, family: str, payload, received_utc, provider_timestamp,
                    window: tuple) -> dict:
    """One raw event -> one record that keeps the raw payload beside the reading.

    INTENT AND OBSERVATION STAY SEPARATE. The raw provider payload is preserved
    verbatim; the interpretation sits next to it, never on top of it. A missing
    provider timestamp is recorded as missing -- never back-filled from our own
    receive clock, which would manufacture provider truth we do not have.
    """
    provider_utc = _as_utc(provider_timestamp)
    return {
        "event_family": family,
        "local_receive_time_utc": _as_utc(received_utc).isoformat()
        if received_utc is not None else None,
        "provider_timestamp_raw": provider_timestamp,
        "provider_timestamp_utc": provider_utc.isoformat() if provider_utc else None,
        "provider_timestamp_et": provider_utc.astimezone(ET).isoformat()
        if provider_utc else None,
        "calendar_state": classify_against_halt(provider_utc or received_utc, window),
        "minute": minute_key(provider_utc or received_utc),
        "raw": payload,
    }


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def minute_matrix(*, events: list, bars: list, window: tuple,
                  first_minute=None, last_minute=None) -> list:
    """Per-minute: live trades, live quotes, and the history bar. Side by side.

    Three independent columns that are never merged. Resemblance between a
    history bar and a quote is not identity, so nothing here concludes anything
    -- it only lays the propositions next to each other.
    """
    by_minute: dict = {}

    def slot(key):
        if key is None:
            return None
        row = by_minute.setdefault(key, {
            "minute": key, "calendar_state": classify_against_halt(key, window),
            "trade_events": 0, "trade_volume": 0.0,
            "first_trade_price": None, "last_trade_price": None,
            "quote_events": 0, "first_bid": None, "first_ask": None,
            "last_bid": None, "last_ask": None,
            "first_quote_volume": None, "last_quote_volume": None,
            "depth_events": 0,
            "history_bar_present": False, "history_open": None, "history_high": None,
            "history_low": None, "history_close": None, "history_volume": None,
        })
        return row

    for ev in (events or []):
        row = slot(ev.get("minute"))
        if row is None:
            continue
        raw = ev.get("raw") or {}
        fam = ev.get("event_family")
        if fam == TRADE:
            row["trade_events"] += 1
            px = _num(raw.get("price"))
            vol = _num(raw.get("volume"))
            if vol is not None:
                row["trade_volume"] += vol
            if px is not None:
                if row["first_trade_price"] is None:
                    row["first_trade_price"] = px
                row["last_trade_price"] = px
        elif fam == QUOTE:
            row["quote_events"] += 1
            bid, ask = _num(raw.get("bestBid")), _num(raw.get("bestAsk"))
            qv = _num(raw.get("volume"))
            if row["first_bid"] is None:
                row["first_bid"], row["first_ask"] = bid, ask
                row["first_quote_volume"] = qv
            row["last_bid"], row["last_ask"] = bid, ask
            row["last_quote_volume"] = qv
        elif fam == DEPTH:
            row["depth_events"] += 1

    for bar in (bars or []):
        row = slot(minute_key(bar.get("t") or bar.get("timestamp")))
        if row is None:
            continue
        row["history_bar_present"] = True
        row["history_open"] = _num(bar.get("o", bar.get("open")))
        row["history_high"] = _num(bar.get("h", bar.get("high")))
        row["history_low"] = _num(bar.get("l", bar.get("low")))
        row["history_close"] = _num(bar.get("c", bar.get("close")))
        row["history_volume"] = _num(bar.get("v", bar.get("volume")))

    # Fill the requested span so an ABSENT minute is visible as a row rather
    # than as a missing key. Absence must be statable, never inferred.
    lo = _as_utc(first_minute) or _as_utc(window[0])
    hi = _as_utc(last_minute) or _as_utc(window[1])
    if lo and hi:
        cursor = lo.replace(second=0, microsecond=0)
        while cursor < hi:
            slot(cursor.isoformat())
            cursor += timedelta(minutes=1)
    return [by_minute[k] for k in sorted(by_minute)]


def adjudicate(matrix: list) -> dict:
    """The state machine. Mechanical, from counts only -- never from resemblance."""
    halt = [r for r in (matrix or []) if r["calendar_state"] == IN_HALT]
    if not halt:
        return {"case": NOT_OBSERVED, "ruling": "the halt window was not observed",
                "halt_minutes": 0}
    trades = sum(r["trade_events"] for r in halt)
    quotes = sum(r["quote_events"] for r in halt)
    bars = sum(1 for r in halt if r["history_bar_present"])
    common = {"halt_minutes": len(halt), "halt_trade_events": trades,
              "halt_trade_volume": round(sum(r["trade_volume"] for r in halt), 6),
              "halt_quote_events": quotes, "halt_history_bars": bars,
              "halt_history_volume": round(
                  sum(r["history_volume"] or 0.0 for r in halt), 6)}
    if trades > 0:
        return {**common, "case": CASE_D_TRADES_DURING_HALT,
                "ruling": ("live GatewayTrade events were observed inside the published "
                           "CME halt. Raw evidence is preserved and no calendar change "
                           "follows from it; the conflict is reported, not explained.")}
    if bars == 0:
        return {**common, "case": INCONCLUSIVE,
                "ruling": ("no history bars were returned for the halt, so this window "
                           "cannot adjudicate what such a bar would mean")}
    if quotes > 0:
        return {**common, "case": CASE_B_QUOTES_ONLY,
                "ruling": ("zero trades, quotes still flowing, history bars present. "
                           "A history bar is NOT evidence of an executed-trade "
                           "opportunity; whether it derives from quote state is a "
                           "separate question this window does not settle.")}
    return {**common, "case": CASE_C_INDEPENDENT_SERIES,
            "ruling": ("zero trades and zero quotes while history bars exist -- the "
                       "historical series is produced independently of the live "
                       "stream during the halt.")}


def prohibits_trade_opportunity_inference(verdict: dict) -> bool:
    """Does this verdict forbid `history bar -> opportunity to trade`?

    Deliberately narrow. Only an observed window with history bars and ZERO
    trades can retire that inference; an unobserved window proves nothing, and
    trades during the halt are a different (larger) problem.
    """
    return (verdict or {}).get("case") in (CASE_A_BAR_IS_NOT_TRADE_EVIDENCE,
                                           CASE_B_QUOTES_ONLY,
                                           CASE_C_INDEPENDENT_SERIES)
