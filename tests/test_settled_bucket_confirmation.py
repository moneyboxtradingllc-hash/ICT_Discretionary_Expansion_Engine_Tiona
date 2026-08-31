"""A CONFIRMED pivot may not rest on a bar that is still forming.

Step 2c removed the LEADING partial higher-timeframe bucket by aligning the
window start. The TRAILING partial bucket is deliberately kept, because live
scanning wants the bar in progress. What was never checked is whether that
forming bar could supply the RIGHT-SIDE evidence `find_swings` requires to
call a pivot confirmed.

It could. Measured on the real tape, with production settings:

    as of 15:05Z   trailing 15m bucket 6/15   -> swing highs [29805.0]
    same bucket closes higher  15/15          -> swing highs []

The 29,805.0 manipulation extreme was "confirmed" by a bar that was 40% formed,
and evaporated the moment that bar finished. That is the same category of error
as the three-day window: an observation without the temporal status the
semantic claim requires gets promoted anyway.

    realtime context   -- the forming bar is honest and useful
    confirmed structure -- must rest on settled evidence only

The forming bar is NOT discarded. `snapshot["timeframes"][tf]` still carries it.
What it may no longer do is create a confirmed structural claim.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                   # noqa: E402
from data_feed.timeframe_builder import build_timeframes          # noqa: E402
from market_data.snapshot_builder import _bucket_is_settled       # noqa: E402
from structure.structure_engine import find_swings                # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def window(end="2026-08-11T15:05:00+00:00") -> list:
    bars = [b for b in tape() if b["timestamp"] <= end]
    return CONT.coherent_window(bars, horizon_minutes=300, minimum_bars=1)["window"]


class TestBucketsDeclareTheirCompleteness:

    def test_every_derived_bucket_carries_membership(self):
        for tf, minutes in (("3m", 3), ("5m", 5), ("15m", 15)):
            for bar in build_timeframes(tape())[tf]:
                assert "members" in bar and "complete" in bar, (tf, bar)
                assert bar["complete"] == (bar["members"] == minutes)

    def test_one_minute_bars_are_always_settled(self):
        for bar in build_timeframes(tape())["1m"]:
            assert bar.get("complete", True) is True

    def test_the_forming_bucket_is_marked_incomplete(self):
        buckets = build_timeframes(window())["15m"]
        assert buckets[-1]["complete"] is False
        assert buckets[-1]["members"] < 15


class TestAFormingBarCannotConfirmAPivot:
    """The load-bearing regression, from real bars."""

    def test_the_29805_pivot_rested_on_a_6_of_15_bucket(self):
        """Documents the defect itself, so the fix cannot be quietly reverted
        without this failing."""
        buckets = build_timeframes(window())["15m"]
        # STEP 4B.12 §4 UNIT 1 — swing evidence held constant at legacy geometry so
        # the variable under test stays what it always was. Unit 1 added an
        # INDEPENDENT guard that also refuses this pivot; one defence getting
        # stronger may not silently delete coverage of another.
        highs, _ = find_swings(buckets, allow_uncadenced=True)
        assert 29805.0 in highs, "the fixture no longer reproduces the defect"
        assert buckets[-1]["complete"] is False
        assert buckets[-1]["members"] == 6

    def test_that_pivot_does_not_survive_the_bucket_closing(self):
        bars = copy.deepcopy([b for b in tape()
                              if b["timestamp"] <= "2026-08-11T15:05:00+00:00"])
        for minute in range(6, 15):
            bars.append({"timestamp": f"2026-08-11T15:{minute:02d}:00+00:00",
                         "open": 29800.0, "high": 29850.0, "low": 29795.0,
                         "close": 29840.0, "volume": 10})
        settled = CONT.coherent_window(bars, horizon_minutes=300,
                                       minimum_bars=1)["window"]
        highs, _ = find_swings(build_timeframes(settled)["15m"])
        assert 29805.0 not in highs, \
            "a pivot confirmed by a forming bar survived its completion"

    def test_settled_only_never_offers_the_unearned_pivot(self):
        buckets = build_timeframes(window())["15m"]
        settled = [b for b in buckets if b["complete"]]
        highs, _ = find_swings(settled)
        assert 29805.0 not in highs, \
            "the settled series still confirms a pivot from a forming bar"


class TestTheSnapshotSeparatesContextFromConfirmation:

    def test_settled_predicate_reads_the_raw_flag(self):
        raw = [{"timestamp": "t1", "complete": False},
               {"timestamp": "t2", "complete": True}]
        assert _bucket_is_settled(raw, {"timestamp": "t1"}) is False
        assert _bucket_is_settled(raw, {"timestamp": "t2"}) is True

    def test_unlabelled_history_is_treated_as_settled(self):
        """Older archives, replays and hand-built fixtures carry no flag.
        Inventing incompleteness would silently delete real structure."""
        assert _bucket_is_settled([{"timestamp": "t1"}], {"timestamp": "t1"}) is True
        assert _bucket_is_settled([], {"timestamp": "t1"}) is True
        assert _bucket_is_settled(None, {"timestamp": "t1"}) is True

    def test_structure_and_liquidity_consume_the_settled_series(self):
        """BEHAVIOURAL. The previous version matched the literal call text
        `analyze_liquidity(all_settled` and broke when STEP 4B.12 wrapped that
        call across lines to pass previous-expected-slot authority -- a refactor
        it did not disagree with.

        What actually matters is that a FORMING bar cannot author confirmed
        structure or a liquidity raid, so that is what is asserted.
        """
        from market_data.snapshot_builder import build_snapshot
        base = [{"timestamp": f"2026-08-12T18:{m:02d}:00+00:00",
                 "open": 100.0 + m, "high": 101.0 + m, "low": 99.0 + m,
                 "close": 100.5 + m, "volume": 10, "members": 1,
                 "complete": True, "expected_members": 1} for m in range(40)]
        # a forming final bar with an extreme high that would dominate any
        # detector willing to consume it
        forming = dict(base[-1], timestamp="2026-08-12T18:40:00+00:00",
                       high=9999.0, low=1.0, complete=False, members=0)
        snap = build_snapshot({"1m": base + [forming], "3m": [], "5m": [],
                               "15m": []}, symbol="MNQ")
        liq = (snap.get("liquidity") or {}).get("1m") or {}
        for key in ("nearest_buy_side_liquidity", "nearest_sell_side_liquidity"):
            assert liq.get(key) != 9999.0, \
                "liquidity consumed the forming bar's extreme"
        struct = (snap.get("structure") or {}).get("1m") or {}
        assert struct.get("last_swing_high") != 9999.0, \
            "confirmed structure consumed the forming bar"

    def test_the_forming_bar_is_still_delivered_as_context(self):
        """CONTINUITY-2G (2026-08-11) re-pinned this test.

        It asserted the literal source `'"recent_candles": normalized[-5:]'`.
        2G annotates those five bars with their temporal status before
        publishing them, so the string moved -- while the PROPERTY it existed to
        protect (the forming bar is still delivered as realtime context) is
        unchanged, and is now also pinned end-to-end in
        tests/test_brain_candle_temporal_contract.py.

        Re-expressed BEHAVIOURALLY, per this project's own 2c lesson: a source
        string catches a call being deleted but not defeated. This version fails
        if the forming bucket is filtered out of realtime context by any means.
        """
        from market_data.snapshot_builder import build_snapshot
        raw = build_timeframes(window())
        forming = raw["15m"][-1]
        assert forming["complete"] is False, "fixture no longer has a forming bar"
        recent = build_snapshot(raw, symbol="MNQ")["timeframes"]["15m"]["recent_candles"]
        assert recent, "realtime context disappeared"
        assert recent[-1]["timestamp"] == forming["timestamp"], \
            "the forming bar must remain visible as realtime context"


class TestBehaviourEndToEnd:

    def snapshot(self, end="2026-08-11T15:05:00+00:00"):
        from market_data.snapshot_builder import build_snapshot
        return build_snapshot(build_timeframes(window(end)), symbol="MNQ")

    def test_the_snapshot_still_shows_the_forming_bar(self):
        snap = self.snapshot()
        buckets = snap["timeframes"]["15m"]["recent_candles"]
        assert buckets, "realtime context disappeared"

    def test_the_forming_bar_fabricates_a_BOS_and_erases_liquidity(self):
        """R5 escaped the first campaign because my behavioural assertion was
        VACUOUS: it checked `last_swing_high`, which is None whether or not the
        filter runs, so it passed for the wrong reason.

        This is the case where the filter actually changes the answer. At
        15:10Z on the 3m the forming bucket does TWO destructive things at once:
        it manufactures a bearish break of structure through 29,723.25 that has
        not happened, and it simultaneously erases the sweep/reclaim and the
        `nearest_sell_side_liquidity` sitting AT 29,723.25 -- the very level the
        clean tape confirms as a real 1m/3m/5m pivot.
        """
        import market_data.snapshot_builder as SB
        raw = build_timeframes(window("2026-08-11T15:10:00+00:00"))

        settled = SB.build_snapshot(raw, symbol="MNQ")
        original = SB._bucket_is_settled
        SB._bucket_is_settled = lambda raw_series, candle: True   # the mutation
        try:
            unfiltered = SB.build_snapshot(raw, symbol="MNQ")
        finally:
            SB._bucket_is_settled = original

        # GUARD B, the ORIGINAL proposition, still discriminating. The forming
        # bar erases real liquidity: the sweep and the 29,723.25 pool the clean
        # tape confirms survive ONLY with the settled filter in place.
        assert settled["liquidity"]["3m"].get("nearest_sell_side_liquidity") == 29723.25
        assert unfiltered["liquidity"]["3m"].get("nearest_sell_side_liquidity") is None
        assert settled["liquidity"]["3m"].get("sweep_detected") is True

        # GUARD A, added by STEP 4B.12 §4 UNIT 2. The structure half of this
        # test used to read `unfiltered bos is True` -- the forming bar
        # FABRICATED a break through 29,723.25. Unit 2 blocks that for a SECOND,
        # independent reason: a forming bucket's CLOSE is not final, so the
        # transition cannot be evaluated at all.
        #
        # Both guards are kept because one defence getting stronger may not
        # delete coverage of another. Guard B above still fails if the settled
        # filter regresses; Guard A below still fails if current-close authority
        # regresses.
        assert settled["structure"]["3m"].get("bos") is False
        assert unfiltered["structure"]["3m"].get("bos") is False,             "a forming bucket fabricated a break event"
        assert unfiltered["structure"]["3m"].get("bos_evaluability") ==             "UNEVALUABLE_CURRENT_CLOSE",             "the forming bucket's unprovable close was treated as evaluated"
        assert unfiltered["structure"]["3m"].get("broken_level") is None,             "event metadata published for a non-event"

    def test_the_snapshot_builds_without_raising(self):
        assert isinstance(self.snapshot(), dict)
