"""EVIDENCE CONTINUITY — was there supposed to be a bar between these bars?

STEP 2E (2026-08-12).

The per-bar temporal axis (S/F/I/U) describes the quality of observations that
EXIST. It says nothing about the space BETWEEN them. Real swing provenance made
that gap visible:

    pivot_time    2026-08-10 16:00
    confirmed_at  2026-08-11 13:30

Three individually SETTLED 15m bars, twenty-one hours apart. The detector
consumed three array members and called it confirmation. Array adjacency is not
market adjacency.

TWO ORTHOGONAL AXES
-------------------
    temporal    what the bars that exist are worth
    continuity  whether bars that should exist are missing

A fully settled series can have broken continuity. A perfectly contiguous series
can end in a forming bar. Neither axis may erase the other.

WHERE THE ANSWER COMES FROM
---------------------------
`venue_calendar` -- the verified CME Globex MNQ schedule. A first version used
`session_engine`, which labels 04:00-20:00 ET for STRATEGY purposes, and was
wrong in both directions: 22:00 ET weekday (MNQ trading) excused real missing
data as a break, while the 17:00-18:00 ET CME maintenance halt was accused of
losing data. A session label is not an exchange calendar.

Gaps are classified by counting the buckets the venue should have printed, not
by sampling timestamps and guessing. Where no verified schedule exists -- a
holiday, an unsupported instrument -- UNKNOWN_CADENCE is reported rather than
assumed in either direction.

It never synthesises bars. Missing means missing.
"""
from __future__ import annotations

from datetime import datetime, timedelta

CONTIGUOUS = "contiguous"
EXPECTED_MARKET_BREAK = "expected_market_break"
#: VENUE OPEN, NO OBSERVATION. Deliberately NOT called "missing data".
#: The venue schedule proves trading COULD occur; it does not prove the provider
#: must emit a candle. ProjectX `retrieveBars` documents OHLCV and
#: `includePartialBar` but is SILENT on whether a zero-trade interval is returned
#: as a zero-volume bar or omitted entirely. Until that contract is known,
#: absence during open hours is reported as absence -- not diagnosed as loss.
VENUE_OPEN_OBSERVATION_ABSENT = "venue_open_observation_absent"

#: The provider-emission contract itself, stated so nobody assumes it later.
PROVIDER_BAR_EMISSION_CONTRACT = "undocumented"
UNKNOWN_CADENCE = "unknown_cadence"
MIXED = "mixed"

#: Nominal minutes per bucket. Used only to size "how many bars should be here",
#: never to assert that the market was open.
_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def _parse(stamp):
    try:
        return datetime.fromisoformat(str(stamp))
    except (ValueError, TypeError):
        return None


def _step_minutes(source_tf: str, stamps: list) -> "float | None":
    """Expected minutes between neighbours.

    Prefers the declared timeframe; falls back to the series' own median
    interval, which is how `price_levels._bar_span_tolerance` already infers
    cadence without being told the timeframe.
    """
    if source_tf in _TF_MINUTES:
        return float(_TF_MINUTES[source_tf])
    deltas = []
    for a, b in zip(stamps, stamps[1:]):
        if a and b:
            d = (b - a).total_seconds() / 60.0
            if d > 0:
                deltas.append(d)
    if len(deltas) < 3:
        return None
    deltas.sort()
    return deltas[len(deltas) // 2]


def _classify_gap(before: datetime, after: datetime, step: float,
                  instrument: str = "MNQ") -> tuple:
    """(classification, rule, missing_buckets) for one discontinuity.

    EXACT, not sampled. The first version probed interior timestamps against
    `session_engine` -- a strategy-label ontology -- and got both directions
    wrong: 22:00 ET weekday (MNQ trading) was excused as a break, and the
    17:00-18:00 ET CME maintenance halt was accused of losing data.

    The question is now answered by counting the buckets the VENUE should have
    printed between the two observations.
    """
    from market_data.venue_calendar import (
        SCHEDULED_DAILY_MAINTENANCE, SPECIAL_SCHEDULE_UNKNOWN, TRADING_OPEN,
        WEEKLY_MARKET_CLOSED, classify, expected_buckets)

    # AN UNAVAILABLE CALENDAR IS AN UNKNOWN SCHEDULE, NOT AN EXCEPTION.
    #
    # Caught by STEP 4B.12 §4 UNIT 5 certification: `test_cadence_authority_
    # boundary` makes `expected_buckets` raise and asserts the whole snapshot
    # still refuses to emit synthetic positives. Until Unit 5 nothing reached
    # this function during `build_snapshot`, so the raise had no way out; wiring
    # the trailing-run authority into A1/A2 gave it one, and the RuntimeError
    # escaped `detect_expansion` and destroyed the entire snapshot.
    #
    # `swing_evidence._adjacency` already answers this exact question the right
    # way -- a calendar that cannot answer yields the non-authorising CADENCE
    # UNKNOWN state, never a bridged positive and never a crash. The same
    # convention is adopted here, in the canonical owner, so EVERY consumer
    # inherits it rather than each one guarding separately.
    #
    # UNKNOWN_CADENCE fails closed downstream: `authoritative_trailing_run`
    # truncates the run to its newest bar, so no credit is bought across a
    # boundary whose schedule could not be established.
    try:
        missing = expected_buckets(before, after, int(step), instrument)
        # What the venue was doing across the gap, sampled only to DESCRIBE it.
        seen = set()
        probe, span = before, (after - before).total_seconds() / 60.0
        stride = min(30.0, max(1.0, span / 4.0))
        steps = max(1, int(span // stride))
        for i in range(1, steps + 1):
            probe = before + timedelta(minutes=stride * i)
            if probe >= after:
                break
            seen.add(classify(probe, instrument)["class"])
    except Exception as exc:         # noqa: BLE001 — cadence unavailable
        return UNKNOWN_CADENCE, f"venue calendar unavailable: {exc}", 0

    if missing:
        rule = (f"{len(missing)} venue-open bucket(s) have no observation "
                f"(provider emission contract undocumented)")
        return VENUE_OPEN_OBSERVATION_ABSENT, rule, len(missing)
    if SPECIAL_SCHEDULE_UNKNOWN in seen:
        return UNKNOWN_CADENCE, "gap covers a date with no verified schedule", 0
    if seen and TRADING_OPEN not in seen:
        which = sorted(seen & {SCHEDULED_DAILY_MAINTENANCE, WEEKLY_MARKET_CLOSED})
        return (EXPECTED_MARKET_BREAK,
                f"venue closed across the whole gap ({', '.join(which)})", 0)
    return (EXPECTED_MARKET_BREAK,
            "no bucket was expected inside this gap under the venue schedule", 0)


def authoritative_trailing_run(series: list, source_tf: str,
                               direction_of) -> dict:
    """The longest TRAILING same-direction run that is market-contiguous.

    STEP 4B.12 §4 UNIT 5 — CONSECUTIVE MEANS CONSECUTIVE MARKET BARS.

    `expansion_detector._follow_through` and `displacement_detector._follow_through`
    walked ARRAY neighbours. A venue-open bucket with no observation is never
    built, so its neighbours are array-adjacent and the walk crossed the hole.
    Measured over 1000 evaluations per producer on the 2026-08-12 tape: 29 of
    426 multi-bar runs spanned a missing expected bucket -- three unique holes
    (15m 18:00, 3m 18:09, 5m 18:10) re-delivered across consecutive scans.

    MODEL B. The observation is preserved, never overwritten: an observed run of
    six is a true statement about what the array held, it is simply not proof
    that six consecutive market bars occurred. Deterministic credit consumes
    `authoritative_run`; diagnostics and publishers keep `observed_run`.

    The run is assessed AS A SERIES, not pairwise, so `_step_minutes` can infer
    cadence from the observations when no timeframe is declared -- a pairwise
    call offers one interval and could never establish a step. This is also how
    `market_events` already asks the question.

    A break in OLDER history does not erase a valid recent suffix: for
    A [hole] B C the authoritative run is 2, not 0. A scheduled closure is
    `EXPECTED_MARKET_BREAK`, which is continuous market time and does NOT
    truncate. Unknown cadence does truncate -- not knowing what the venue was
    scheduled to print is not evidence that it printed nothing.
    """
    out = {"observed_run": 0, "authoritative_run": 0, "direction": None,
           "continuity": CONTIGUOUS, "stopped_between": None}
    if not series or len(series) < 2:
        return out
    last = direction_of(series[-1])
    if last in (None, "neutral"):
        return out
    out["direction"] = last

    run = [series[-1]]
    for c in reversed(series[:-1]):
        if direction_of(c) != last:
            break
        run.insert(0, c)
    out["observed_run"] = len(run)
    if len(run) < 2:
        out["authoritative_run"] = len(run)
        return out

    verdict = evaluate(run, source_tf)
    klass = verdict.get("continuity_class")
    if klass in (CONTIGUOUS, EXPECTED_MARKET_BREAK):
        out["authoritative_run"] = len(run)
        out["continuity"] = klass
        return out

    # Truncate at the MOST RECENT discontinuity: everything after it is still
    # provable, and older damage may not erase a valid recent suffix.
    stamps = [(b.get("timestamp") if isinstance(b, dict) else b) for b in run]
    cut = 0
    for gap in (verdict.get("gaps") or []):
        try:
            idx = stamps.index(gap.get("gap_end"))
        except ValueError:
            continue
        cut = max(cut, idx)
    if cut == 0 and klass == UNKNOWN_CADENCE:
        cut = len(run) - 1          # cadence unknown anywhere: nothing extends
    out["authoritative_run"] = len(run) - cut
    out["continuity"] = klass
    out["stopped_between"] = (stamps[cut - 1], stamps[cut]) if cut else None
    return out


def evaluate(bars_or_stamps: list, source_tf: str = None) -> dict:
    """Continuity of ONE evidence window.

    Accepts bars or bare timestamps. Reports every discontinuity it finds and
    what authority classified it. Simultaneous conditions are preserved rather
    than collapsed to a single label.
    """
    raw = [(b.get("timestamp") if isinstance(b, dict) else b)
           for b in (bars_or_stamps or [])]
    stamps = [_parse(s) for s in raw]
    usable = [s for s in stamps if s]
    if len(usable) < 2:
        return {"continuity_class": UNKNOWN_CADENCE,
                "continuity_issues": [], "gaps": [],
                "observation_count": len(usable),
                "elapsed_minutes": None,
                "classification_source": "insufficient or unusable timestamps"}

    step = _step_minutes(source_tf, usable)
    gaps, issues = [], set()
    for a, b in zip(usable, usable[1:]):
        delta = (b - a).total_seconds() / 60.0
        if step is None:
            issues.add(UNKNOWN_CADENCE)
            continue
        if delta <= step * 1.5:          # one bucket, with slack for jitter
            continue
        kind, rule, missing = _classify_gap(a, b, step)
        issues.add(kind)
        gaps.append({"gap_start": a.isoformat(), "gap_end": b.isoformat(),
                     "gap_minutes": round(delta, 2),
                     "missing_expected_buckets": missing,
                     "classification": kind, "rule": rule})

    elapsed = round((usable[-1] - usable[0]).total_seconds() / 60.0, 2)
    if not issues:
        klass = CONTIGUOUS
    elif len(issues) == 1:
        klass = next(iter(issues))
    else:
        klass = MIXED
    return {"continuity_class": klass,
            "continuity_issues": sorted(issues),
            "gaps": gaps,
            "observation_count": len(usable),
            # OBSERVATION COUNT MAY NEVER MASQUERADE AS ELAPSED MARKET TIME.
            # Both are published so "3 confirming bars" can never silently read as
            # "45 minutes", nor "21 elapsed hours" as 21 hours of delivery.
            "elapsed_minutes": elapsed,
            "expected_step_minutes": step,
            "classification_source": "session_engine + calendar weekday probe"}


NOT_TESTABLE = "not_testable_archive_out_of_scope"
EMPIRICAL = "empirical"
#: Bars EXIST inside a window the venue calendar says the market was closed.
#: Both facts are kept: the observation is real evidence about the PROVIDER, and
#: it is not evidence about the MARKET. See `trade_opportunity_authority`.
CONFLICTED_WITH_SCHEDULE = "conflicted_observation_inside_scheduled_break"

#: BAR-HALT-OBSERVATION-1 (2026-08-18). The inference this module now refuses.
#:
#: On 2026-08-17 the canonical store held a bar for all fifteen 16:15-16:30 ET
#: CME halt minutes -- with changing OHLC and volume 129-1155 -- while holding
#: none for the sixty 17:00-18:00 maintenance minutes. 1380 = 1440 - 60. The
#: same file, day and timestamp convention corroborate one scheduled break and
#: contradict the other, which rules out a timezone or bucket-label shift.
#:
#: ProjectX documents `/api/History/retrieveBars` as returning aggregated
#: `t/o/h/l/c/v`. It nowhere promises a bar implies executed trades in the
#: interval, and it exposes `GatewayTrade` as a SEPARATE real-time market-trade
#: stream. So a continuous chart series through a halt may be entirely
#: intentional on the provider's side -- that is not proven either way, and
#: `tools/topstepx_halt_observer.py` exists to settle it empirically.
#:
#: What is ours, and what is denied here:
#:
#:     a provider historical bar exists
#:         -/->  the venue was open / an executed-trade observation was possible
#:
#: MODEL B, as everywhere else in this project: PRESERVE THE OBSERVATION, GATE
#: THE CREDIT. The bar is not deleted, not rewritten, not hidden from raw
#: inspection, and its OHLCV is untouched. It simply may not manufacture
#: trade-opportunity authority while an authoritative schedule says otherwise.
TRADE_AUTHORITY_DENIED_IN_SCHEDULED_BREAK = (
    "provider_bar_present_but_schedule_denies_trade_opportunity")


def trade_opportunity_authority(moment, *, bar_present: bool,
                                instrument: str = "MNQ") -> dict:
    """May a provider bar at `moment` prove the market could have traded?

    The one place the denied inference is stated, so no caller has to remember
    it. Absence of a bar is NOT handled here -- that is `_classify_gap`'s job;
    this answers only what a PRESENT bar is allowed to prove.
    """
    from market_data import venue_calendar as VC
    state = VC.classify(moment, instrument)
    scheduled_break = state["class"] in (VC.SCHEDULED_DAILY_MAINTENANCE,
                                         VC.SCHEDULED_INTRADAY_TRADING_HALT,
                                         VC.WEEKLY_MARKET_CLOSED)
    unknown = state["class"] == VC.SPECIAL_SCHEDULE_UNKNOWN
    if not bar_present:
        return {"bar_present": False, "calendar_class": state["class"],
                "trade_opportunity_authority": False,
                "observation_preserved": False,
                "reason": "no observation to credit"}
    if unknown:
        # Fail closed: an unknown schedule is not permission.
        return {"bar_present": True, "calendar_class": state["class"],
                "trade_opportunity_authority": False,
                "observation_preserved": True,
                "reason": "schedule authority unknown; credit withheld"}
    if scheduled_break:
        return {"bar_present": True, "calendar_class": state["class"],
                "trade_opportunity_authority": False,
                "observation_preserved": True,
                "conflicts_with_schedule": True,
                "reason": TRADE_AUTHORITY_DENIED_IN_SCHEDULED_BREAK}
    return {"bar_present": True, "calendar_class": state["class"],
            "trade_opportunity_authority": True,
            "observation_preserved": True,
            "reason": "venue open and an observation exists"}


def empirical_coverage(bars: list, start_hm: tuple, end_hm: tuple,
                       instrument: str = "MNQ") -> dict:
    """Did this archive have the OPPORTUNITY to observe a given daily window?

    STEP 2E.3. A zero count is evidence only when the denominator is non-zero.
    An archive spanning 08:40-16:07 ET was reported as empirically corroborating
    that no bars exist in the 16:15-16:30 halt and the 17:00-18:00 close -- but
    it never reaches either window, so it observed nothing and could not have.
    Zero observations with zero opportunity is not corroboration; it is silence.

    A date counts as covered only when the archive holds bars on BOTH sides of
    the window that day, which is the only way absence inside it means anything.

    BAR-HALT-OBSERVATION-1: when the window is an AUTHORITATIVE SCHEDULED BREAK
    and the archive nonetheless holds observations inside it, the status is
    CONFLICTED_WITH_SCHEDULE, never EMPIRICAL. The observations are counted and
    returned exactly as before -- what changes is only what they are allowed to
    prove. The calendar is consulted here rather than by the caller so the law
    cannot be forgotten at a call site.
    """
    from datetime import datetime as _dt
    import pytz
    from market_data import venue_calendar as VC
    et = pytz.timezone("America/New_York")
    lo = start_hm[0] * 60 + start_hm[1]
    hi = end_hm[0] * 60 + end_hm[1]
    by_day: dict = {}
    for b in bars or []:
        try:
            t = _dt.fromisoformat(str(b.get("timestamp"))).astimezone(et)
        except (ValueError, TypeError, AttributeError):
            continue
        by_day.setdefault(t.date(), []).append(t.hour * 60 + t.minute)
    covered = sum(1 for mins in by_day.values()
                  if any(m < lo for m in mins) and any(m >= hi for m in mins))
    inside = sum(1 for mins in by_day.values() for m in mins if lo <= m < hi)

    # Is the window itself a scheduled break? Judged on each observed date, so a
    # special schedule on one day cannot silently speak for another.
    break_dates, mid = 0, (lo + hi) // 2
    for day in by_day:
        moment = et.localize(_dt(day.year, day.month, day.day, mid // 60, mid % 60))
        if VC.classify(moment, instrument)["class"] in (
                VC.SCHEDULED_DAILY_MAINTENANCE, VC.SCHEDULED_INTRADAY_TRADING_HALT,
                VC.WEEKLY_MARKET_CLOSED):
            break_dates += 1

    if not covered:
        status = NOT_TESTABLE
    elif break_dates and inside:
        status = CONFLICTED_WITH_SCHEDULE
    else:
        status = EMPIRICAL
    return {"dates_with_bracketing_coverage": covered,
            "observations_inside_window": inside,
            "scheduled_break_dates": break_dates,
            # The load-bearing separation: observations are preserved above;
            # this says whether they may prove the market could have traded.
            "trade_opportunity_authority": status == EMPIRICAL and not inside,
            "empirical_status": status}
