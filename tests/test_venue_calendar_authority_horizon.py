"""VENUE-CALENDAR-AUTHORITY-HORIZON-1 — the calendar that expired, and the
execution-bearing fail-open it was hiding.

WHAT WAS FOUND (2026-08-30, during cross-session PO3 scoping).

`VERIFIED_ORDINARY_RANGES` ended 2026-08-31. From 2026-09-01 every date answered
OUTSIDE_AUTHORITY, `is_expected` was False for every minute, and
`expected_buckets` returned `[]` for every window. Three certified consumers read
that correctly as "the calendar has no jurisdiction here" and degraded. One did
not:

    price_levels._canonically_adjacent  ->  return not expected_buckets(...)
                                            not []  ==  True

so "I cannot answer" became "therefore these bars are market neighbours", and the
guard standing between the FVG detector and the 2026-07-26 phantom would have
stopped skipping anything at all — two days after the defect was found, on every
date, for the whole practice campaign.

WHAT THIS FILE PROVES.

  1. Ordinary authority now reaches 2026-12-31, with holes cut around the real
     CME holiday windows rather than drawn across them.
  2. Special dates still outrank ordinary membership, and the widened windows
     (Sunday reopen / Tuesday resumption) are covered.
  3. `cadence_authority_over` scans the interior, so a holiday between two
     verified endpoints can no longer hide behind them.
  4. Unknown cadence can never become proven adjacency — the fail-open is shut.
  5. The horizon cannot silently expire again.

Every assertion is about the calendar and the geometry guard. No trade outcome
is consulted anywhere in this file.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

import pytest
import pytz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import market_data.venue_calendar as VC                            # noqa: E402
from toolbox.price_levels import _canonically_adjacent, find_fvgs  # noqa: E402

ET = pytz.timezone("America/New_York")

#: The date the old horizon died on. The specimen of this whole unit.
EXPIRY_SPECIMEN = "2026-09-01"
#: A named holiday whose exact intraday cadence is deliberately NOT encoded.
SPECIAL_SPECIMEN = "2026-09-07"
#: Still outside any verified range, and must stay that way for the
#: unknown-cadence specimens in this file to mean anything.
UNKNOWN_SPECIMEN = "2027-02-01"


def at(day: str, hhmm: str = "12:00:00"):
    return ET.localize(datetime.fromisoformat(f"{day}T{hhmm}"))


def bar(day: str, hhmm: str, o, h, l, c):
    return {"timestamp": at(day, hhmm).isoformat(), "open": o, "high": h,
            "low": l, "close": c, "volume": 100}


# ── 1. the horizon itself ─────────────────────────────────────────────────────

class TestTheOrdinaryHorizon:
    def test_authority_reaches_the_end_of_2026(self):
        latest = max(date.fromisoformat(hi) for _lo, hi in VC.VERIFIED_ORDINARY_RANGES)
        assert latest >= date(2026, 12, 30), (
            f"verified ordinary authority stops at {latest}; the horizon unit "
            f"authorised coverage through 2026-12-31 less the holiday windows")

    def test_the_expiry_specimen_is_now_ordinary(self):
        """2026-09-01 was OUTSIDE_AUTHORITY at 3291c93. That is the whole unit."""
        assert VC.calendar_authority(at(EXPIRY_SPECIMEN)) == "KNOWN_ORDINARY"

    def test_the_expiry_specimen_has_real_expected_cadence(self):
        """Authority without cadence would be a label. The London-killzone
        window on that date must enumerate real 1m slots."""
        slots = VC.expected_buckets(at(EXPIRY_SPECIMEN, "02:59:00"),
                                    at(EXPIRY_SPECIMEN, "05:01:00"), 1)
        assert len(slots) == 121, len(slots)

    def test_september_through_december_ordinary_days_are_covered(self):
        """Walk every date to year-end: each is either ordinary or a declared
        special date. Nothing is left OUTSIDE_AUTHORITY by accident."""
        day, orphans = date(2026, 9, 1), []
        while day <= date(2026, 12, 30):
            found = VC.calendar_authority(at(day.isoformat()))
            if found == "OUTSIDE_AUTHORITY":
                orphans.append(day.isoformat())
            day += timedelta(days=1)
        assert orphans == [], f"dates with no authority at all: {orphans}"


# ── 2. special windows outrank ordinary membership ────────────────────────────

class TestSpecialDatesStillWin:
    @pytest.mark.parametrize("day", ["2026-09-06", "2026-09-07", "2026-09-08",
                                     "2026-11-26", "2026-11-27", "2026-11-28",
                                     "2026-12-24", "2026-12-25", "2026-12-26",
                                     "2026-12-31", "2027-01-01"])
    def test_the_holiday_window_is_special_not_ordinary(self, day):
        assert day in VC.SPECIAL_SCHEDULE_DATES
        assert VC.calendar_authority(at(day)) == "KNOWN_SPECIAL"

    def test_labor_day_did_not_inherit_ordinary_semantics(self):
        """The precise trap the widened horizon created: 09-07 lies between two
        ordinary spans, and precedence is the only thing stopping it becoming an
        ordinary Monday."""
        assert VC.calendar_authority(at("2026-09-05")) == "KNOWN_ORDINARY"
        assert VC.calendar_authority(at("2026-09-07")) == "KNOWN_SPECIAL"
        assert VC.calendar_authority(at("2026-09-09")) == "KNOWN_ORDINARY"

    def test_a_special_date_yields_no_expected_cadence(self):
        """Naming a window is not knowing its hours. With
        SPECIAL_SCHEDULE_AUTHORITY_MISSING still True, a special date must
        enumerate nothing rather than assume ordinary slots."""
        assert VC.SPECIAL_SCHEDULE_AUTHORITY_MISSING is True
        assert VC.expected_buckets(at(SPECIAL_SPECIMEN, "02:59:00"),
                                   at(SPECIAL_SPECIMEN, "05:01:00"), 1) == []

    def test_no_intraday_holiday_cadence_was_invented(self):
        """The unit was authorised to widen the WINDOW list, never to encode
        holiday hours. If someone later encodes them, this fails and the
        CADENCE_UNKNOWN branch must be taught to honour them."""
        assert VC.SPECIAL_SCHEDULE_AUTHORITY_MISSING is True


# ── 3. the interior scan ──────────────────────────────────────────────────────

class TestInteriorScan:
    def test_a_holiday_between_verified_endpoints_is_not_hidden(self):
        v = VC.cadence_authority_over(at("2026-09-04"), at("2026-09-10"))
        assert v["authority"] == VC.CADENCE_UNKNOWN
        assert v["unknown_date"] in VC.SPECIAL_SCHEDULE_DATES

    def test_both_endpoints_being_ordinary_is_not_sufficient(self):
        """The retired theorem, stated as a negative so it cannot come back."""
        assert VC.calendar_authority(at("2026-11-24")) == "KNOWN_ORDINARY"
        assert VC.calendar_authority(at("2026-11-30")) == "KNOWN_ORDINARY"
        assert VC.cadence_authority_over(
            at("2026-11-24"), at("2026-11-30"))["authority"] == VC.CADENCE_UNKNOWN

    def test_a_clean_span_is_still_known(self):
        assert VC.cadence_authority_over(
            at("2026-09-09"), at("2026-10-30"))["authority"] == VC.CADENCE_KNOWN

    def test_reversed_bounds_are_handled_not_trusted(self):
        assert VC.cadence_authority_over(
            at("2026-09-10"), at("2026-09-04"))["authority"] == VC.CADENCE_UNKNOWN

    def test_an_unusable_timestamp_is_unknown(self):
        assert VC.cadence_authority_over(
            "not-a-time", at("2026-09-09"))["authority"] == VC.CADENCE_UNKNOWN


# ── 4. THE FAIL-OPEN, SHUT ────────────────────────────────────────────────────

class TestAdjacencyNeverFailsOpen:
    """`expected_buckets() == []` means one of two opposite things, and the old
    code could not tell them apart:

        cadence KNOWN + []   ->  no slot sits between them: ADJACENT
        cadence UNKNOWN + [] ->  I have no jurisdiction: NOTHING IS PROVEN
    """

    def test_unknown_cadence_is_not_adjacency(self):
        a = bar(UNKNOWN_SPECIMEN, "10:00:00", 100, 101, 99, 100)
        b = bar(UNKNOWN_SPECIMEN, "10:01:00", 100, 101, 99, 100)
        assert VC.expected_buckets(a["timestamp"], b["timestamp"], 1) == []
        assert _canonically_adjacent(a, b, 1) is False

    def test_a_special_date_is_not_adjacency_either(self):
        a = bar(SPECIAL_SPECIMEN, "10:00:00", 100, 101, 99, 100)
        b = bar(SPECIAL_SPECIMEN, "10:01:00", 100, 101, 99, 100)
        assert _canonically_adjacent(a, b, 1) is False

    def test_known_cadence_still_proves_real_adjacency(self):
        """Non-vacuity in the safe direction: the repair must not simply refuse
        everything, or the FVG detector would go dark instead of fail-open."""
        a = bar(EXPIRY_SPECIMEN, "10:00:00", 100, 101, 99, 100)
        b = bar(EXPIRY_SPECIMEN, "10:01:00", 100, 101, 99, 100)
        assert _canonically_adjacent(a, b, 1) is True

    def test_known_cadence_still_rejects_a_real_hole(self):
        a = bar(EXPIRY_SPECIMEN, "10:00:00", 100, 101, 99, 100)
        b = bar(EXPIRY_SPECIMEN, "10:05:00", 100, 101, 99, 100)
        assert _canonically_adjacent(a, b, 1) is False

    def test_the_defect_would_have_been_reachable(self):
        """Non-vacuity of the whole unit: prove the OLD implementation really
        does admit adjacency on an unknown date, so this file is guarding a real
        failure rather than describing a hypothetical one."""
        a = bar(UNKNOWN_SPECIMEN, "10:00:00", 100, 101, 99, 100)
        b = bar(UNKNOWN_SPECIMEN, "10:01:00", 100, 101, 99, 100)
        legacy = not VC.expected_buckets(a["timestamp"], b["timestamp"], 1)
        assert legacy is True, "the old expression no longer fails open"
        assert _canonically_adjacent(a, b, 1) is not legacy


# ── 5. the phantom, at the detector ───────────────────────────────────────────

class TestPhantomFvgStaysRefused:
    """The 2026-07-26 incident in miniature: three bars that are array
    neighbours but not market neighbours, carrying a gap manufactured by the
    clock. On an unknown date the adjacency guard is the only thing between that
    triple and the toolbox."""

    def _phantom(self, day):
        # c1.high < c3.low  ->  a bullish imbalance on paper.
        return [bar(day, "10:00:00", 100, 101, 99, 100),
                bar(day, "10:01:00", 101, 130, 100, 129),
                bar(day, "10:02:00", 129, 140, 120, 139)]

    def test_a_gap_on_an_unknown_date_is_not_admitted(self):
        assert find_fvgs(self._phantom(UNKNOWN_SPECIMEN), "bullish", 1) == []

    def test_a_gap_on_a_special_date_is_not_admitted(self):
        assert find_fvgs(self._phantom(SPECIAL_SPECIMEN), "bullish", 1) == []

    def test_the_same_geometry_is_admitted_when_cadence_is_known(self):
        """The geometry did not change. Only the calendar's ability to vouch for
        it did — which is exactly the distinction the unit exists to restore."""
        found = find_fvgs(self._phantom(EXPIRY_SPECIMEN), "bullish", 1)
        assert len(found) == 1, found

    def test_no_fvg_geometry_was_tuned(self):
        """The repair is epistemic. With cadence known, the detector's answer
        must be identical to what it always was for adjacent bars."""
        found = find_fvgs(self._phantom(EXPIRY_SPECIMEN), "bullish", 1)
        assert found[0]["low"] == 101 and found[0]["high"] == 120


# ── 6. the horizon cannot expire in silence again ─────────────────────────────

REVIEW_WINDOW_DAYS = 30


class TestTheHorizonGuard:
    """THE DEFECT THAT MADE THIS UNIT NECESSARY WAS NOT A BUG. It was a dated
    fact quietly going out of date while every test stayed green — the calendar
    was correct on the day it was written and wrong 30 days later, and nothing
    in the suite was watching the clock.

    This is the only test in the repository that is allowed to fail because of
    what day it is. That is the point.
    """

    def test_verified_authority_extends_beyond_the_review_window(self):
        latest = max(date.fromisoformat(hi) for _lo, hi in VC.VERIFIED_ORDINARY_RANGES)
        deadline = date.today() + timedelta(days=REVIEW_WINDOW_DAYS)
        assert latest >= deadline, (
            f"VENUE CALENDAR AUTHORITY IS EXPIRING.\n"
            f"  verified ordinary authority ends : {latest}\n"
            f"  today                            : {date.today()}\n"
            f"  required through                 : {deadline}\n"
            f"\n"
            f"When it lapses, `calendar_authority` answers OUTSIDE_AUTHORITY for "
            f"every date, `expected_buckets` returns [] for every window, and "
            f"every cadence-dependent claim degrades to UNKNOWN.\n"
            f"\n"
            f"THE FIX IS HUMAN VERIFICATION, NOT ARITHMETIC. Read the CME holiday "
            f"calendar, extend VERIFIED_ORDINARY_RANGES with holes cut around the "
            f"holiday windows, and add those windows to SPECIAL_SCHEDULE_DATES. "
            f"Do not extend the horizon by inferring weekdays.")

    def test_the_guard_is_load_bearing(self):
        """A guard that cannot fail guards nothing."""
        original = VC.VERIFIED_ORDINARY_RANGES
        VC.VERIFIED_ORDINARY_RANGES = (("2026-08-01", "2026-08-31"),)
        try:
            latest = max(date.fromisoformat(hi)
                         for _lo, hi in VC.VERIFIED_ORDINARY_RANGES)
            assert latest < date.today() + timedelta(days=REVIEW_WINDOW_DAYS), (
                "the configuration that actually expired would now pass the "
                "guard; the guard is decorative")
        finally:
            VC.VERIFIED_ORDINARY_RANGES = original

    def test_the_guard_did_not_auto_extend_anything(self):
        """No silent widening. The horizon is source, verified by a human, and
        this file must never become the thing that moves it."""
        assert VC.ORDINARY_RANGE_AUTHORITY == "PRIMARY_OWNER_VERIFIED"
        assert any("cmegroup.com" in s for s in VC.ORDINARY_RANGE_SOURCES)
