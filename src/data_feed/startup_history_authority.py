"""Is the canonical 1m record fit to author production reasoning YET?

STARTUP-HISTORY-AUTHORITY (2026-08-12, after PROD-20260812).

The warm-up call already reported its own failure and nobody asked. But the
obvious repair -- refuse when `added == 0` -- is the wrong question twice over:

  * a warm-up may legitimately add nothing because the canonical store already
    holds every minute the venue offered, which is health, not failure; and
  * a warm-up may add hundreds of bars from last Tuesday and still leave the
    session with no coherent recent history at all.

`added` is an accounting detail about one request. The question that actually
gates an armed session is whether the record it will reason FROM is complete
enough to be reasoned from: capability intact, recent, continuous, coherent,
aligned -- and not merely a chart this process grew out of its own uptime.

That last clause is the one the coherence guard could not enforce on its own.
`coherent_window` counts bars; sixty bars observed since launch count exactly
like sixty bars of real history. On 2026-08-12 the guard held the session off
for nineteen scans and would have released it at 12:29 ET on a chart born at
11:30. It did not catch the defect; it delayed it. Process uptime may never
masquerade as market history, so the check that says so lives here, explicitly,
where a bar count cannot launder it.

Pure and side-effect free: it reads a report and a list of candles and returns a
verdict. It never fetches, repairs, or mutates anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_feed import candle_continuity as CONT

#: How old the newest canonical bar may be before the record is not "now".
#: Deliberately generous: this is a staleness floor, not a feed-health monitor
#: (`is_stale` already owns that), and a session attaching one minute after a
#: closed bar is normal.
DEFAULT_MAX_STALENESS_MINUTES = 10


def _minute_floor(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _as_utc(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def evaluate(*, backfill_report, candles, now=None, process_started_at=None,
             horizon_minutes: int = 300, minimum_bars: int = 60,
             align_minutes: int = CONT.COARSEST_TIMEFRAME_MINUTES,
             max_staleness_minutes: float = DEFAULT_MAX_STALENESS_MINUTES) -> dict:
    """Verdict on whether canonical history may author an armed session.

    Returns `{"fit": bool, "refusals": [...], "checks": {...}}`. Every refusal is
    a full sentence naming the measurement that failed, because these strings are
    what an operator reads at 09:29 with the window open.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    started = _as_utc(process_started_at)
    report = dict(backfill_report or {})
    refusals: list = []
    checks: dict = {}

    # 1. CAPABILITY. A warm-up that never ran, or raised, is not evidence about
    #    the market -- it is the absence of evidence, and absence may never
    #    masquerade as continuity.
    checks["warmup_attempted"] = bool(report.get("attempted"))
    checks["warmup_error"] = report.get("error")
    checks["bars_returned"] = report.get("returned")
    checks["bars_added"] = report.get("added")
    if not report:
        refusals.append(
            "NO_STARTUP_HISTORY_REPORT: the warm-up left no verdict, so there is "
            "no evidence historical retrieval was even attempted")
    elif not report.get("attempted"):
        refusals.append(
            "STARTUP_HISTORY_NOT_ATTEMPTED: historical warm-up never ran")
    elif report.get("error"):
        refusals.append(
            f"STARTUP_HISTORY_CAPABILITY_ERROR: historical retrieval failed -- "
            f"{report['error']}. An armed session will not reason from whatever "
            f"happens to be lying in the store when the venue could not be asked.")

    ordered = CONT.normalize(candles)
    checks["canonical_bars"] = len(ordered)

    # 2. PRESENCE.
    if not ordered:
        refusals.append(
            "NO_CANONICAL_HISTORY: the canonical 1m record is empty")
        checks["window"] = None
        return {"fit": False, "refusals": refusals, "checks": checks}

    newest = CONT.canonical_key(ordered[-1])
    oldest = CONT.canonical_key(ordered[0])
    checks["canonical_first"] = oldest.isoformat() if oldest else None
    checks["canonical_last"] = newest.isoformat() if newest else None

    # 3. FRESHNESS. History about yesterday is not history about now. This is the
    #    check that `added == 0` would have passed happily on a store still
    #    holding a full, continuous, perfectly coherent record of last Friday.
    age_minutes = None
    if newest is not None:
        age_minutes = (now - _as_utc(newest)).total_seconds() / 60.0
        checks["newest_age_minutes"] = round(age_minutes, 2)
        if age_minutes > float(max_staleness_minutes):
            refusals.append(
                f"CANONICAL_HISTORY_STALE: the newest canonical bar is "
                f"{age_minutes:.0f} minutes old (ceiling {max_staleness_minutes:.0f}); "
                f"the record does not describe the current session")

    # 4-5. COHERENCE + ALIGNMENT. One call owns both, so this gate can never
    #      drift from the gate the scan loop itself applies.
    window = CONT.coherent_window(ordered, horizon_minutes=horizon_minutes,
                                  minimum_bars=minimum_bars,
                                  align_minutes=align_minutes)
    checks["window"] = {k: window[k] for k in
                        ("bars", "span_minutes", "sufficient", "reason",
                         "continuous", "offered", "discarded_as_incoherent")}
    if not window["sufficient"]:
        refusals.append(
            f"INCOHERENT_STARTUP_HISTORY: {window['reason']}")

    # 6. NEWBORN CHART. The whole reason this module exists.
    #
    #    Evaluated at startup, when process uptime is ~0: if the coherent window
    #    contains nothing this process did not personally witness, then every bar
    #    it would reason from was manufactured by its own runtime, and waiting
    #    longer only makes a newborn chart LOOK legitimate. Refusing on bar
    #    provenance -- not bar count -- is what makes "wait for it to warm up"
    #    unavailable as an answer.
    checks["process_started_at"] = started.isoformat() if started else None
    checks["window_predates_process"] = None
    if started is not None and window["window"]:
        window_oldest = _as_utc(CONT.canonical_key(window["window"][0]))
        predates = window_oldest is not None and window_oldest < _minute_floor(started)
        checks["window_predates_process"] = predates
        checks["window_oldest"] = window_oldest.isoformat() if window_oldest else None
        if not predates:
            refusals.append(
                f"NEWBORN_CHART: every bar in the coherent window "
                f"({checks.get('window_oldest')} onward) was observed after this "
                f"process started ({started.isoformat()}). History that begins at "
                f"process boot is uptime, not market history, and accumulating "
                f"more live minutes will never repair its provenance.")

    return {"fit": not refusals, "refusals": refusals, "checks": checks}
