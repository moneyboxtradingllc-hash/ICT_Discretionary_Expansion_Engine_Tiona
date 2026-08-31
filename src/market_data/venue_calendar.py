"""VENUE CADENCE — was an MNQ observation EXPECTED at this timestamp?

STEP 2E.1 (2026-08-12).

A SESSION LABEL IS NOT AN EXCHANGE CALENDAR
-------------------------------------------
The first continuity classifier used `session_engine` to decide whether a bar
should exist. That engine labels roughly 04:00-20:00 ET and returns "closed"
outside -- a STRATEGY ontology (premarket / ny_open / lunch / power_hour). It is
correct at its own job and wrong for this one, and it produced errors in BOTH
directions, measured:

    22:00 ET weekday   MNQ trades; session_engine says "closed"
                       -> real missing data excused as an expected break
    17:00-18:00 ET     CME daily maintenance; session_engine says "after_hours"
                       -> a scheduled halt accused of losing data

Separate jurisdictions:

    session_engine    "what part of the strategy day is this?"
    venue_calendar    "should a market observation exist here?"

SOURCE
------
CME Group, Micro E-mini Equity Index futures. Verified against cmegroup.com
rather than assumed:

    Sunday 18:00 ET  ->  Friday 17:00 ET   trading week
    16:15 - 16:30 ET                       daily equity-index trading halt
    17:00 - 18:00 ET                       daily session close / maintenance

The 16:15-16:30 halt was MISSED by the first version, which expected bars during
a period CME explicitly halts and therefore overstated absent observations.

WHAT THIS DOES NOT KNOW
-----------------------
Holiday HOURS. 2026 holiday DATES are recorded (see `SPECIAL_SCHEDULE_DATES`),
but knowing a date is special is not knowing its schedule -- a 12:00 CT early
halt and a full closure are different cadences and neither is loaded. Special
dates therefore report SPECIAL_SCHEDULE_UNKNOWN rather than being run through
the ordinary weekly rules. `SPECIAL_SCHEDULE_AUTHORITY_MISSING` stays True.

This module also says nothing about whether the BOT MAY TRADE. That is the
production decision window's job. Market-data cadence and trading permission are
different questions with different owners.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz

EASTERN = pytz.timezone("America/New_York")

TRADING_OPEN = "trading_open"
SCHEDULED_DAILY_MAINTENANCE = "scheduled_daily_maintenance"
SCHEDULED_INTRADAY_TRADING_HALT = "scheduled_intraday_trading_halt"
WEEKLY_MARKET_CLOSED = "weekly_market_closed"
SPECIAL_SCHEDULE_UNKNOWN = "special_schedule_unknown"

#: The only instrument this lane trades. MNQ's schedule is NOT asserted as a
#: universal futures rule -- another product would need its own entry.
SUPPORTED_INSTRUMENTS = ("MNQ",)

#: Verified CME Globex weekly schedule, expressed in ET.
WEEKLY_OPEN_WEEKDAY, WEEKLY_OPEN_HOUR = 6, 18      # Sunday 18:00 ET
WEEKLY_CLOSE_WEEKDAY, WEEKLY_CLOSE_HOUR = 4, 17    # Friday 17:00 ET
MAINTENANCE_START_HOUR, MAINTENANCE_END_HOUR = 17, 18
#: CME lists a DAILY equity-index trading halt 16:15-16:30 ET for Micro E-mini
#: Equity Index futures, separate from the 17:00-18:00 session close. Omitting it
#: made the cadence owner expect bars during a period CME explicitly halts, which
#: overstated "missing" observations.
INTRADAY_HALT_START = (16, 15)
INTRADAY_HALT_END = (16, 30)

#: SPECIAL-DATE SCOPE.
#:
#: "No holiday source exists" was not enough on its own: without a date
#: authority the calendar cannot KNOW which dates are special, so an ordinary
#: Thursday and Thanksgiving Thursday would both run the ordinary weekly rules.
#:
#: Authority is therefore OPT-IN. A date is treated as ordinary only inside a
#: range positively verified to contain no CME holiday. Everything else --
#: including a known holiday and any date outside the verified ranges -- reports
#: SPECIAL_SCHEDULE_UNKNOWN. Refusing to classify is a fact; assuming ordinary
#: hours on Thanksgiving would be a fabrication.
SPECIAL_SCHEDULE_AUTHORITY_MISSING = True

#: 2026 CME holiday dates. STEP 3A: this list is no longer the basis of any
#: "ordinary" claim -- see VERIFIED_ORDINARY_RANGES below for why that matters.
SPECIAL_SCHEDULE_DATES = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Presidents Day",
    "2026-04-03": "Good Friday (full closure)",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day observed",
    # VENUE-CALENDAR-AUTHORITY-HORIZON-1 (2026-08-30). A HOLIDAY IS A WINDOW,
    # NOT A DAY. The list held only the holiday DATE, which was harmless while
    # ordinary authority stopped at 2026-08-31 -- every one of these lay outside
    # it. Extending authority to year-end made the omission load-bearing: the
    # Sunday reopen before a holiday and the Tuesday resumption after it would
    # have inherited ORDINARY cadence from the surrounding range.
    #
    # Owner-verified against cmegroup.com/trading-hours.html (2026-08-30). The
    # exact intraday cadence of these dates is still NOT encoded -- naming a
    # window is not knowing its hours -- so they resolve KNOWN_SPECIAL and, with
    # SPECIAL_SCHEDULE_AUTHORITY_MISSING still True, yield CADENCE_UNKNOWN.
    # That is the intended answer, not a gap to fill by inference.
    "2026-09-06": "Labor Day window (Sunday reopen)",
    "2026-09-07": "Labor Day",
    "2026-09-08": "Labor Day window (Tuesday resumption)",
    "2026-11-26": "Thanksgiving",
    "2026-11-27": "Day after Thanksgiving (early close)",
    "2026-11-28": "Thanksgiving window",
    "2026-12-24": "Christmas Eve (early close)",
    "2026-12-25": "Christmas Day",
    "2026-12-26": "Christmas window",
    "2026-12-31": "New Year's Eve (early close)",
    "2027-01-01": "New Year's Day",
}

#: WHY A RANGE AND NOT AN ABSENCE ARGUMENT.
#:
#: STEP 3A caught a real gap in the previous version: it held BOTH that the
#: holiday list was "deliberately incomplete" AND that Aug-07 -> Aug-12 was
#: ordinary. Those coexist only if the August range was positively verified by
#: something OTHER than the list. It had not been -- the range was justified by
#: the absence of an August entry, and
#:
#:     not listed  !=  proven ordinary
#:
#: is exactly the inference that reasoning licenses. The claim was invalid even
#: though its conclusion happens to be correct.
#:
#: POSITIVE SOURCE (recorded 2026-08-13). Two independent publications of the
#: COMPLETE 2026 CME holiday calendar were retrieved and enumerated end to end.
#: Both run Jul-03 -> Sep-07 with no intervening date, so August is covered by
#: an exhaustive enumeration rather than by the silence of a partial list:
#:
#:     crosstrade.io/blog/cme-trading-hours-2026        10 dates, none in August
#:     discounttrading.com/futures-holiday-schedule     13 dates, none in August
#:
#: AUTHORITY TIER: SECONDARY_CORROBORATED. cmegroup.com's own holiday calendar
#: page was attempted first and timed out, so this is two agreeing third-party
#: enumerations, not the primary source. That is enough to authorise an ordinary
#: weekly schedule for the replay scope and is deliberately recorded as a tier
#: rather than laundered into "verified".
ORDINARY_RANGE_AUTHORITY = "PRIMARY_OWNER_VERIFIED"
ORDINARY_RANGE_SOURCES = (
    "cmegroup.com/trading-hours.html -- 2026 holiday calendar, owner-verified "
    "2026-08-30 (PRIMARY)",
    "cmegroup.com Micro E-mini Equity Index FAQ -- Sun-Fri 18:00-17:00 ET with "
    "the 16:15-16:30 ET halt, owner-verified 2026-08-30 (PRIMARY)",
    "crosstrade.io/blog/cme-trading-hours-2026 (complete 2026 enumeration)",
    "discounttrading.com/futures-holiday-schedule.html (complete 2026 enumeration)",
)

#: VENUE-CALENDAR-AUTHORITY-HORIZON-1 -- ORDINARY AUTHORITY IS NO LONGER CONVEX.
#:
#: The previous single span ended 2026-08-31 and expired two days before the
#: practice campaign. Measured on 2026-08-30: from 2026-09-01 every date
#: answered OUTSIDE_AUTHORITY, `is_expected` was False for every minute, and
#: `expected_buckets` returned [] for every window -- which three certified
#: consumers correctly read as "no jurisdiction" and one
#: (`price_levels._canonically_adjacent`) read as "therefore adjacent".
#:
#: Extending to year-end crosses real CME holidays, so the ranges MUST leave
#: holes where the special windows sit. That retires the convexity the old
#: endpoint shortcut rested on -- see `cadence_authority_over`, which now scans
#: the interior. The holes are the point: an ordinary span may never be drawn
#: across a date whose cadence is unproven.
VERIFIED_ORDINARY_RANGES = (
    ("2026-08-01", "2026-09-05"),   # ends the day before the Labor Day window
    ("2026-09-09", "2026-11-25"),   # resumes after it, ends before Thanksgiving
    ("2026-11-29", "2026-12-23"),   # resumes after it, ends before Christmas
    ("2026-12-27", "2026-12-30"),   # resumes after it, ends before New Year's Eve
)


def calendar_authority(moment) -> str:
    """KNOWN_SPECIAL / KNOWN_ORDINARY / OUTSIDE_AUTHORITY for a date."""
    et = _to_eastern(moment)
    if et is None:
        return "OUTSIDE_AUTHORITY"
    day = et.date().isoformat()
    if day in SPECIAL_SCHEDULE_DATES:
        return "KNOWN_SPECIAL"
    for lo, hi in VERIFIED_ORDINARY_RANGES:
        if lo <= day <= hi:
            return "KNOWN_ORDINARY"
    return "OUTSIDE_AUTHORITY"


def _to_eastern(moment) -> "datetime | None":
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if not isinstance(moment, datetime):
        return None
    # DST is handled by the zone, never by a fixed offset.
    return (EASTERN.localize(moment) if moment.tzinfo is None
            else moment.astimezone(EASTERN))


def classify(moment, instrument: str = "MNQ") -> dict:
    """What the venue was doing at `moment`."""
    if instrument not in SUPPORTED_INSTRUMENTS:
        return {"class": SPECIAL_SCHEDULE_UNKNOWN, "instrument": instrument,
                "rule": f"no verified schedule for {instrument!r}"}
    et = _to_eastern(moment)
    if et is None:
        return {"class": SPECIAL_SCHEDULE_UNKNOWN, "instrument": instrument,
                "rule": "unusable timestamp"}
    authority = calendar_authority(et)
    if authority != "KNOWN_ORDINARY":
        reason = ("date is a known CME holiday; exact product hours not loaded"
                  if authority == "KNOWN_SPECIAL"
                  else "date lies outside any range verified free of CME holidays")
        return {"class": SPECIAL_SCHEDULE_UNKNOWN, "instrument": instrument,
                "calendar_authority": authority, "rule": reason}

    day, hour = et.weekday(), et.hour          # Mon=0 ... Sun=6
    if day == 5:                                # Saturday
        return {"class": WEEKLY_MARKET_CLOSED, "instrument": instrument,
                "rule": "Saturday: between Friday 17:00 ET close and Sunday 18:00 ET open"}
    if day == WEEKLY_OPEN_WEEKDAY:              # Sunday
        if hour < WEEKLY_OPEN_HOUR:
            return {"class": WEEKLY_MARKET_CLOSED, "instrument": instrument,
                    "rule": "Sunday before the 18:00 ET weekly open"}
        return {"class": TRADING_OPEN, "instrument": instrument,
                "rule": "Sunday after the 18:00 ET weekly open"}
    if day == WEEKLY_CLOSE_WEEKDAY and hour >= WEEKLY_CLOSE_HOUR:   # Friday
        return {"class": WEEKLY_MARKET_CLOSED, "instrument": instrument,
                "rule": "Friday after the 17:00 ET weekly close"}
    minutes = et.hour * 60 + et.minute
    if (INTRADAY_HALT_START[0] * 60 + INTRADAY_HALT_START[1]) <= minutes <             (INTRADAY_HALT_END[0] * 60 + INTRADAY_HALT_END[1]):
        return {"class": SCHEDULED_INTRADAY_TRADING_HALT, "instrument": instrument,
                "rule": "CME equity-index intraday trading halt 16:15-16:30 ET"}
    if MAINTENANCE_START_HOUR <= hour < MAINTENANCE_END_HOUR:
        return {"class": SCHEDULED_DAILY_MAINTENANCE, "instrument": instrument,
                "rule": "CME daily maintenance 17:00-18:00 ET"}
    return {"class": TRADING_OPEN, "instrument": instrument,
            "rule": "inside CME Globex trading hours"}


def is_expected(moment, instrument: str = "MNQ") -> bool:
    """Should a market observation exist at `moment`?"""
    return classify(moment, instrument)["class"] == TRADING_OPEN


def expected_buckets(start, end, tf_minutes: int, instrument: str = "MNQ") -> list:
    """Every aligned bucket between `start` and `end` the venue should have printed.

    EXCLUSIVE of both endpoints: the caller already observed those bars; the
    question is what belongs strictly between them.

    Alignment floors from midnight in the timestamp's own zone, which is exactly
    what `timeframe_builder._floor_timestamp` does. A cadence checker that
    expected a bucket the timeframe builder could never emit would be worse than
    no checker, so the rule is not reinterpreted here.
    """
    a, b = _to_eastern(start), _to_eastern(end)
    if a is None or b is None or tf_minutes <= 0:
        return []
    out, probe = [], a + timedelta(minutes=tf_minutes)
    guard = 0
    while probe < b and guard < 100000:
        guard += 1
        total = probe.hour * 60 + probe.minute
        floored = (total // tf_minutes) * tf_minutes
        aligned = probe.replace(hour=floored // 60, minute=floored % 60,
                                second=0, microsecond=0)
        if is_expected(aligned, instrument):
            out.append(aligned)
        probe = probe + timedelta(minutes=tf_minutes)
    return out


#: STEP 4B.12 §9 — THE EXPECTED TERMINAL CONSTITUENT BELONGS TO THE CADENCE.
#:
#: `snapshot_builder` computed it as `bucket_start + N - 1` minutes. That is
#: nominal arithmetic wearing the costume of a schedule: it asserts the venue
#: was scheduled to print at that minute, which only this module can answer.
#:
#: The failure it invites is specific. A bucket whose nominal last minute falls
#: inside a scheduled closure has NO observation there and never should have.
#: Reading that as an absent terminal constituent reports the CLOSE unprovable
#: for a bucket that is in fact complete — a scheduled closure masquerading as a
#: missing observation, which is the mirror image of the defect this whole step
#: exists to remove.
#:
#: THREE outcomes, never a boolean:
#:
#:     CADENCE_OWNED                  the schedule is known and answered
#:     NOMINAL_UNDER_UNKNOWN_SCHEDULE the schedule is NOT known; nominal
#:                                    arithmetic is used and SAYS SO
#:     NO_EXPECTED_CONSTITUENT        the venue was scheduled closed throughout
#:
#: The middle one is load-bearing. `is_expected` answers False for a
#: SPECIAL_SCHEDULE_UNKNOWN date, so a two-valued implementation would declare
#: every bucket outside the verified ranges to have no expected terminal and
#: withhold the world. `_crosses_forbidden_boundary` already made exactly that
#: mistake in the FVG work and killed every gap outside verified August. Unknown
#: stays UNKNOWN: behaviour is unchanged from nominal, and the CLAIM is honest.
CADENCE_OWNED = "CADENCE_OWNED"
NOMINAL_UNDER_UNKNOWN_SCHEDULE = "NOMINAL_UNDER_UNKNOWN_SCHEDULE"
NO_EXPECTED_CONSTITUENT = "NO_EXPECTED_CONSTITUENT"


def expected_terminal_constituent(bucket_start, tf_minutes: int,
                                  instrument: str = "MNQ") -> dict:
    """The LAST 1m observation the venue was scheduled to print in this bucket.

    Returns {"terminal": <UTC isoformat or None>, "basis": <one of the three>}.
    Minutes are stepped in UTC and classified in Eastern, so a DST transition
    inside a bucket cannot shift the answer.
    """
    et = _to_eastern(bucket_start)
    if et is None or tf_minutes <= 0:
        return {"terminal": None, "basis": NO_EXPECTED_CONSTITUENT,
                "rule": "unusable bucket start"}
    base = et.astimezone(pytz.utc)
    minutes = [base + timedelta(minutes=k) for k in range(int(tf_minutes))]
    classes = [classify(m, instrument)["class"] for m in minutes]

    if any(c == SPECIAL_SCHEDULE_UNKNOWN for c in classes):
        return {"terminal": minutes[-1].isoformat(),
                "basis": NOMINAL_UNDER_UNKNOWN_SCHEDULE,
                "rule": "schedule not verified for this date; nominal last "
                        "minute used and not claimed as cadence authority"}

    open_minutes = [m for m, c in zip(minutes, classes) if c == TRADING_OPEN]
    if not open_minutes:
        return {"terminal": None, "basis": NO_EXPECTED_CONSTITUENT,
                "rule": "venue scheduled closed for the whole bucket"}
    return {"terminal": open_minutes[-1].isoformat(), "basis": CADENCE_OWNED,
            "rule": "last minute the venue was scheduled to print"}


#: STEP 4B.12 §9 RESIDUE — UNKNOWN SCHEDULE IS NOT AN EMPTY SCHEDULE.
#:
#: `expected_buckets` filters candidates through `is_expected`, which answers
#: False for a SPECIAL_SCHEDULE_UNKNOWN date. So on any date outside the
#: verified ranges it returns [] -- and the caller reads [] as
#:
#:     "no expected market slot sits between these two observations"
#:
#: when what this module actually said was
#:
#:     "I do not possess the schedule authority to answer that."
#:
#: The caller then asserts that the array neighbour IS the previous market slot.
#: Silence from an authority that never had jurisdiction became proof of
#: absence, which is the same collapse as reading a filtered array as
#: consecutive market slots -- arrived at through a different control flow.
#:
#: A caller that needs to make an ADJACENCY claim must ask this first. Callers
#: doing descriptive/provisional timing work may still use the nominal answers;
#: what they may not do is prove a negative continuity claim with them.
#:
#: HORIZON-1: `cadence_authority_over` below now scans every date in the span
#: rather than its endpoints, so a special or unverified date BETWEEN two
#: verified ones can no longer hide behind them.
CADENCE_KNOWN = "CADENCE_KNOWN"
CADENCE_UNKNOWN = "CADENCE_UNKNOWN"


def cadence_authority_over(start, end, instrument: str = "MNQ") -> dict:
    """Do we hold schedule authority across EVERY date in [start, end]?

    INTERIOR SCAN (VENUE-CALENDAR-AUTHORITY-HORIZON-1, 2026-08-30). This checked
    only the two endpoints, which was sound while VERIFIED_ORDINARY_RANGES was a
    single contiguous convex span: a span whose ends were both KNOWN_ORDINARY
    could not enclose an unverified date. The previous docstring recorded that
    assumption and said plainly that if the ranges ever grew a hole, this must
    become an interior scan.

    They have. Extending ordinary authority to 2026-12-31 crosses the Labor Day,
    Thanksgiving, Christmas and New Year windows, so KNOWN_ORDINARY is now
    deliberately non-convex, and endpoint checking would answer CADENCE_KNOWN
    for a span running from before a holiday to after it -- claiming jurisdiction
    over exactly the dates whose cadence is unproven.

    So every ET calendar date the span touches is asked. The answer is the
    weakest one found, never the endpoints' one.
    """
    if instrument not in SUPPORTED_INSTRUMENTS:
        return {"authority": CADENCE_UNKNOWN,
                "rule": f"no verified schedule for {instrument!r}"}
    a, b = _to_eastern(start), _to_eastern(end)
    for label, moment in (("start", a), ("end", b)):
        if moment is None:
            return {"authority": CADENCE_UNKNOWN,
                    "rule": f"{label} timestamp unusable"}
    if b < a:
        a, b = b, a
    day, last = a.date(), b.date()
    # A span is bounded by the tape it describes; a runaway range must degrade
    # to UNKNOWN rather than spin. 400 days comfortably exceeds any window this
    # organism asks about and still terminates.
    guard = 0
    while day <= last and guard < 400:
        guard += 1
        found = calendar_authority(f"{day.isoformat()}T12:00:00")
        if found == "KNOWN_SPECIAL":
            # A named holiday whose exact intraday cadence is not encoded. When
            # SPECIAL_SCHEDULE_AUTHORITY_MISSING is retired and per-date hours
            # are certified, this is the branch that learns to honour them.
            return {"authority": CADENCE_UNKNOWN,
                    "rule": f"{day.isoformat()} is a known special date "
                            f"({SPECIAL_SCHEDULE_DATES.get(day.isoformat())}); "
                            f"exact product hours are not encoded",
                    "unknown_date": day.isoformat()}
        if found != "KNOWN_ORDINARY":
            return {"authority": CADENCE_UNKNOWN,
                    "rule": f"{day.isoformat()} is {found}; expected-slot "
                            f"membership cannot be established",
                    "unknown_date": day.isoformat()}
        day += timedelta(days=1)
    if day <= last:
        return {"authority": CADENCE_UNKNOWN,
                "rule": "span exceeds the 400-day scan bound"}
    return {"authority": CADENCE_KNOWN,
            "rule": "every date in the span is inside a verified ordinary range"}
