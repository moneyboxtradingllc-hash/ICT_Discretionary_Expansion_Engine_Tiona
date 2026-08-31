"""ABSENCE MAY NEVER MASQUERADE AS CONTINUITY.

On 2026-08-11 two operator restarts punched holes in the day's 1m history --
10:11-10:19 and 10:41-11:01 ET -- and nothing detected, reported or repaired
them. The 11:03 Brain payload carried five bars that LOOKED contiguous:

    14:39Z  14:40Z  14:41Z   <<20 MINUTES MISSING>>   15:01Z  15:02Z

`degraded[]` said only `prior_session_levels_absent`. The buy-side manipulation
through 29,800 lived entirely inside that hole.

WHY A HOLE IS WORSE THAN THIN DATA. `structure_engine.find_swings` confirms a
pivot against its N neighbours ON BOTH SIDES, so across a gap those "neighbours"
are twenty real minutes away: a hole can FABRICATE a swing that never existed or
preserve one the missing bars would have killed. Corrupted topology, not sparse
data. And `timeframe_builder._aggregate` buckets by floored timestamp, so a 15m
bar built from two 1m bars is shape-identical to one built from fifteen.

THE LAW THESE TESTS ENFORCE, in one line:

    RESTART DOES NOT CHANGE MARKET REALITY.

Asserting `no_gaps` alone would be far too weak -- it would pass on an empty
record. So the load-bearing test runs the SAME real tape twice, once
uninterrupted and once through a simulated 10:41->11:01 outage plus repair, and
requires the canonical closed-bar history to be EQUIVALENT.

The fixture is real: `tests/fixtures/mnq_20260811_1420Z_1510Z_1m.json`, pulled
from TopstepX `/api/History/retrieveBars` with `includePartialBar=False`, OHLCV
only. Its landmarks are the ones the operator read off the chart by hand --
10:52 high 29805.0, no body acceptance above 29,800, 10:44 low 29723.25,
10:58 high 29797.0 -- every one of which was invisible to V13.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT              # noqa: E402
from data_feed.timeframe_builder import build_timeframes     # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")

#: The exact V13 outage, in the fixture's own clock.
OUTAGE_FIRST_MISSING = "2026-08-11T14:42:00+00:00"
OUTAGE_LAST_MISSING = "2026-08-11T15:00:00+00:00"


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def outage(bars: list) -> list:
    """The tape as V13 actually saw it: everything inside the hole removed."""
    return [b for b in bars
            if not (OUTAGE_FIRST_MISSING <= b["timestamp"] <= OUTAGE_LAST_MISSING)]


def keys(bars: list) -> list:
    return [CONT.canonical_key(b).isoformat() for b in CONT.normalize(bars)]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheFixtureIsRealAndWhole:

    def test_the_venue_record_is_continuous(self):
        ok, gaps = CONT.verify_continuous(tape())
        assert ok, gaps

    def test_it_brackets_the_outage(self):
        stamps = keys(tape())
        assert stamps[0] < OUTAGE_FIRST_MISSING < OUTAGE_LAST_MISSING < stamps[-1]

    def test_it_contains_the_landmarks_v13_never_saw(self):
        bars = {b["timestamp"]: b for b in tape()}
        assert bars["2026-08-11T14:52:00+00:00"]["high"] == 29805.0
        assert bars["2026-08-11T14:44:00+00:00"]["low"] == 29723.25
        assert bars["2026-08-11T14:58:00+00:00"]["high"] == 29797.0

    def test_no_body_acceptance_above_the_figure(self):
        """Descriptive only. The organism has NO big-figure semantics today
        (audited: zero repo matches); this records the tape, not a rule."""
        bars = {b["timestamp"]: b for b in tape()}
        pierced = [t for t, b in bars.items() if b["high"] >= 29800]
        assert pierced, "the fixture should contain the excursion"
        assert all(bars[t]["close"] < 29800 for t in pierced)


class TestGapDetection:

    def test_the_v13_hole_is_found(self):
        ok, gaps = CONT.verify_continuous(outage(tape()))
        assert not ok
        assert len(gaps) == 1
        assert gaps[0]["first_missing"] == OUTAGE_FIRST_MISSING
        assert gaps[0]["last_missing"] == OUTAGE_LAST_MISSING
        assert gaps[0]["missing_minutes"] == 19

    def test_a_short_record_is_not_a_holed_one(self):
        """Starting late is not a gap, or every cold start flags forever."""
        ok, _ = CONT.verify_continuous(tape()[10:])
        assert ok

    def test_an_empty_or_single_record_has_no_interior_gap(self):
        assert CONT.verify_continuous([])[0]
        assert CONT.verify_continuous(tape()[:1])[0]

    def test_every_missing_minute_is_enumerated(self):
        gaps = CONT.find_gaps(outage(tape()))
        listed = gaps[0]["missing"]
        assert len(listed) == gaps[0]["missing_minutes"]
        assert listed == sorted(listed)
        assert OUTAGE_FIRST_MISSING in listed and OUTAGE_LAST_MISSING in listed


class TestAbsenceIsSayable:

    def test_a_gap_produces_a_degraded_marker(self):
        report = CONT.summarize(outage(tape()))
        markers = CONT.degraded_markers(report)
        assert len(markers) == 1
        assert markers[0].startswith("candle_gap:1m:")
        assert "missing=19" in markers[0]
        assert "recovered=false" in markers[0]

    def test_a_whole_record_produces_no_marker(self):
        assert CONT.degraded_markers(CONT.summarize(tape())) == []

    def test_the_report_names_the_span(self):
        report = CONT.summarize(outage(tape()))
        assert report["continuous"] is False
        assert report["missing_minutes"] == 19
        assert report["first"] and report["last"]

    def test_a_recent_gap_is_material(self):
        assert CONT.material_gap(CONT.summarize(outage(tape())), within_last=60)

    def test_an_old_gap_is_not_material_to_a_recent_read(self):
        holed = outage(tape())
        report = CONT.summarize(holed)
        assert CONT.material_gap(report, within_last=5) is False

    def test_a_whole_record_is_never_material(self):
        assert CONT.material_gap(CONT.summarize(tape()), within_last=60) is False

    def test_an_unlocatable_record_fails_closed(self):
        assert CONT.material_gap({"continuous": False, "gaps": [
            {"missing_minutes": 5, "before": None}], "last": None},
            within_last=10) is True


class TestMergeHasOneAuthorityPerMinute:

    def test_overlapping_sources_do_not_duplicate(self):
        whole = tape()
        merged = CONT.merge(whole[:30], whole[20:])
        assert len(merged) == len(whole)
        assert keys(merged) == keys(whole)

    def test_later_sources_win(self):
        """Authority order is argument order: persisted -> REST -> live."""
        first = [dict(tape()[0], close=1.0)]
        second = [dict(tape()[0], close=2.0)]
        assert CONT.merge(first, second)[0]["close"] == 2.0

    def test_reversed_input_is_normalised_not_trusted(self):
        """Some venue endpoints answer newest-first. Normalise once, here."""
        assert keys(CONT.normalize(list(reversed(tape())))) == keys(tape())

    def test_unparseable_rows_are_dropped_not_guessed(self):
        assert keys(CONT.merge(tape(), [{"timestamp": "not-a-time"},
                                        {"no_timestamp": True}])) == keys(tape())

    def test_sub_minute_stamps_collapse_to_their_minute(self):
        odd = dict(tape()[0], timestamp="2026-08-11T14:20:37.512+00:00")
        assert len(CONT.merge(tape(), [odd])) == len(tape())

    def test_repair_window_brackets_every_gap_with_padding(self):
        gaps = CONT.find_gaps(outage(tape()))
        start, end = CONT.repair_window(gaps, pad_minutes=5)
        assert start <= CONT.parse_ts(OUTAGE_FIRST_MISSING) - timedelta(minutes=5)
        assert end >= CONT.parse_ts(OUTAGE_LAST_MISSING) + timedelta(minutes=5)

    def test_no_gaps_needs_no_window(self):
        assert CONT.repair_window([]) is None


# ══════════════════════════════════════════════════════════════════════════════
class TestRestartDoesNotChangeMarketReality:
    """THE LOAD-BEARING TEST. Same tape, two histories, one truth."""

    def test_repaired_history_equals_uninterrupted_history(self):
        whole = tape()
        # what the process personally witnessed across a 10:41->11:01 outage
        witnessed = outage(whole)
        assert not CONT.verify_continuous(witnessed)[0]

        # the repair: refetch the padded window and merge under one identity
        gaps = CONT.find_gaps(witnessed)
        start, end = CONT.repair_window(gaps, pad_minutes=5)
        refetched = [b for b in whole
                     if start <= CONT.parse_ts(b["timestamp"]) <= end]
        repaired = CONT.merge(witnessed, refetched)

        assert keys(repaired) == keys(whole), "restart changed market reality"
        assert CONT.verify_continuous(repaired)[0]
        assert len(repaired) == len(whole)

    def test_the_repair_is_verified_not_assumed(self):
        """A fetch that returns the wrong window must NOT read as healed.

        Without this second gate we would only trade 'we never noticed the gap'
        for 'we assumed the repair worked' -- the same disease.
        """
        witnessed = outage(tape())
        useless = [b for b in tape() if b["timestamp"] < "2026-08-11T14:30"]
        still_holed = CONT.merge(witnessed, useless)
        ok, gaps = CONT.verify_continuous(still_holed)
        assert not ok and gaps[0]["missing_minutes"] == 19

    def test_a_partial_repair_is_still_a_gap(self):
        witnessed = outage(tape())
        half = [b for b in tape()
                if OUTAGE_FIRST_MISSING <= b["timestamp"] <= "2026-08-11T14:50:00+00:00"]
        ok, gaps = CONT.verify_continuous(CONT.merge(witnessed, half))
        assert not ok, "a partly-filled hole reported as continuous"
        assert gaps[0]["missing_minutes"] < 19

    def test_higher_timeframes_converge_after_repair(self):
        """3m/5m/15m are derived from canonical 1m, so one repair fixes all."""
        whole = tape()
        repaired = CONT.merge(outage(whole), whole)
        built_whole = build_timeframes(CONT.normalize(whole))
        built_repaired = build_timeframes(repaired)
        for tf in ("1m", "3m", "5m", "15m"):
            assert built_repaired[tf] == built_whole[tf], f"{tf} diverged"

    def test_the_holed_tape_produces_DIFFERENT_higher_timeframes(self):
        """Proof the gap really does corrupt derived structure -- otherwise the
        convergence test above would be vacuous."""
        whole = tape()
        built_whole = build_timeframes(CONT.normalize(whole))
        built_holed = build_timeframes(CONT.normalize(outage(whole)))
        assert built_holed["15m"] != built_whole["15m"]

    def test_the_15m_bar_v13_never_had(self):
        """14:45Z existed in reality and was absent from V13's world."""
        whole = build_timeframes(CONT.normalize(tape()))["15m"]
        holed = build_timeframes(CONT.normalize(outage(tape())))["15m"]
        assert any(b["timestamp"].startswith("2026-08-11T14:45") for b in whole)
        assert not any(b["timestamp"].startswith("2026-08-11T14:45") for b in holed)

    def test_the_manipulation_extreme_is_restored(self):
        """29,805.0 was invisible to V13; after repair it is in the record."""
        holed = CONT.normalize(outage(tape()))
        repaired = CONT.merge(holed, tape())
        assert max(b["high"] for b in holed) < 29800
        assert max(b["high"] for b in repaired) == 29805.0


class TestDerivedTimeframesAreRealNotJustEqual:
    """M7 escaped the first campaign: `test_higher_timeframes_converge_after
    _repair` compared two builds of the same function, so breaking the builder
    broke BOTH sides equally and the comparison still passed. Comparing two
    broken things proves nothing. These assert absolute content."""

    def test_every_timeframe_covers_the_whole_tape(self):
        built = build_timeframes(CONT.normalize(tape()))
        minutes = len(tape())
        for tf, step in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15)):
            expected = len({CONT.canonical_key(b).replace(
                minute=(CONT.canonical_key(b).minute // step) * step)
                for b in tape()})
            assert len(built[tf]) == expected, f"{tf} has {len(built[tf])} of {expected}"
            assert len(built[tf]) >= minutes // (step * 2), f"{tf} collapsed"

    def test_each_derived_bar_spans_its_own_bucket(self):
        built = build_timeframes(CONT.normalize(tape()))
        by_minute = {CONT.canonical_key(b): b for b in tape()}
        for bar in built["15m"]:
            start = CONT.parse_ts(bar["timestamp"])
            members = [b for m, b in by_minute.items()
                       if start <= m < start + timedelta(minutes=15)]
            assert members
            assert bar["high"] == max(m["high"] for m in members)
            assert bar["low"] == min(m["low"] for m in members)
            assert bar["open"] == members[0]["open"]
            assert bar["close"] == members[-1]["close"]

    def test_the_manipulation_bar_survives_derivation(self):
        """29,805.0 must be present on EVERY timeframe, not just 1m."""
        built = build_timeframes(CONT.normalize(tape()))
        for tf in ("1m", "3m", "5m", "15m"):
            assert max(b["high"] for b in built[tf]) == 29805.0, tf
