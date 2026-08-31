"""STEP 4B.12 §4 UNIT 2 — a break is an EVENT, not a POSITION.

`analyze_structure` asked "is the close beyond the most recent swing?" and
published the answer as `bos` / `bos_event`. That is a STATE. Once price sat
beyond a level it stayed beyond it, so the same break was re-announced as a fresh
event on every subsequent scan.

Measured over 1000 scan x timeframe opportunities on the Unit-1 tree, by an
independent model that never called the implementation under test:

    OLD BOS positive deliveries   366     OLD MSS positive deliveries   90
    genuine fresh transitions      88     genuine fresh transitions     36
    persistent already-beyond     278     persistent already-in-state   54
    transitions OLD missed          0     transitions OLD missed         0
    unique market events           38     unique market events          12

The 54 persistent MSS deliveries are SET-IDENTICAL to OLD's 54 false positives.

Unit 2 adds NOTHING else -- no displacement requirement, no body ratio, no
excursion minimum, no close-quality rule. Only the transition theorem.

COVERAGE LABELS. The real tape exercises EVALUATED_NO_BREAK, ALREADY_BEYOND,
FRESH and UNEVALUABLE_PREVIOUS_SLOT (24 measured observations). Tests F, G, I
and T cover branches with ZERO measured real-tape examples and are SYNTHETIC
DOCTRINE COVERAGE, not empirical production coverage.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_data.swing_evidence import (                            # noqa: E402
    TRANSITION_EVALUABLE, TRANSITION_UNEVALUABLE_CADENCE,
    TRANSITION_UNEVALUABLE_CURRENT_CLOSE,
    TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE,
    TRANSITION_UNEVALUABLE_PREVIOUS_SLOT)
from structure.structure_engine import analyze_structure            # noqa: E402


def bar(m, high, low, close, day="2026-08-12"):
    return {"timestamp": f"{day}T18:{m:02d}:00+00:00", "open": close,
            "high": high, "low": low, "close": close, "volume": 10,
            "members": 1, "expected_members": 1, "complete": True}


def series(final_close, *, high_pivot=None, low_pivot=None):
    """Twelve 1m bars with one confirmed pivot and a chosen final close.

    A swing high needs three strictly lower highs each side; the mirror holds for
    a low. Built explicitly so each control below is non-vacuous.
    """
    out = []
    for m in range(11):
        h, l = 105.0, 95.0
        if high_pivot is not None and m == 5:
            h = high_pivot
        if low_pivot is not None and m == 5:
            l = low_pivot
        out.append(bar(m, h, l, 100.0))
    out.append(bar(11, max(105.0, final_close + 1), min(95.0, final_close - 1),
                   final_close))
    return out


def transition(prev_close, state=TRANSITION_EVALUABLE):
    return {"state": state, "previous_close": prev_close,
            "current_bucket": "2026-08-12T18:11:00+00:00"}


def structure(candles, prev_close, state=TRANSITION_EVALUABLE):
    return analyze_structure(candles, allow_uncadenced=True,
                             transition=transition(prev_close, state))


class TestA_BullishFreshTransition:

    def test_a_break_from_the_unbroken_side_is_an_event(self):
        c = series(final_close=130.0, high_pivot=120.0)
        out = structure(c, prev_close=110.0)          # 110 <= 120 < 130
        assert out["last_swing_high"] == 120.0, "fixture built no source swing"
        assert out["bos"] is True
        assert out["bos_direction"] == "bullish"
        assert out["broken_level"] == 120.0
        assert out["break_close"] == 130.0
        assert out["bos_evaluability"] == "EVALUATED"


class TestB_BearishFreshTransition:

    def test_the_mirror_case(self):
        c = series(final_close=70.0, low_pivot=80.0)
        out = structure(c, prev_close=90.0)           # 90 >= 80 > 70
        assert out["last_swing_low"] == 80.0, "fixture built no source swing"
        assert out["bos"] is True
        assert out["bos_direction"] == "bearish"
        assert out["broken_level"] == 80.0


class TestCD_AlreadyBeyondIsNotAnEvent:
    """The defect itself. 278 of OLD's 366 BOS deliveries were this."""

    def test_C_already_above_publishes_no_event(self):
        c = series(final_close=130.0, high_pivot=120.0)
        fresh = structure(c, prev_close=110.0)
        assert fresh["bos"] is True, "control is vacuous unless this fires"
        out = structure(c, prev_close=125.0)          # already beyond last bucket
        assert out["bos"] is False
        assert out["bos_direction"] is None
        assert out["broken_level"] is None, "event metadata implied a break"
        assert out["break_close"] is None
        assert out["position_beyond_swing_high"] is True, \
            "the POSITION is real and must still be published, under its own name"
        assert out["bos_evaluability"] == "EVALUATED"

    def test_D_already_below_publishes_no_event(self):
        c = series(final_close=70.0, low_pivot=80.0)
        assert structure(c, prev_close=90.0)["bos"] is True
        out = structure(c, prev_close=75.0)
        assert out["bos"] is False
        assert out["position_beyond_swing_low"] is True


class TestEFGI_UnevaluableIsNotAnEvaluatedNegative:
    """E is MEASURED (24 real observations). F, G and I are SYNTHETIC DOCTRINE
    COVERAGE -- zero real-tape examples on the audited scope."""

    def unevaluable(self, state):
        c = series(final_close=130.0, high_pivot=120.0)
        return analyze_structure(c, allow_uncadenced=True,
                                 transition={"state": state})

    def test_E_previous_slot_absent(self):
        out = self.unevaluable(TRANSITION_UNEVALUABLE_PREVIOUS_SLOT)
        assert out["bos"] is False
        assert out["bos_evaluability"] == TRANSITION_UNEVALUABLE_PREVIOUS_SLOT
        assert out["bos_evaluability"] != "EVALUATED", \
            "an unanswerable question was recorded as an evaluated negative"

    def test_F_previous_close_unproven_SYNTHETIC(self):
        out = self.unevaluable(TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE)
        assert out["bos_evaluability"] == TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE

    def test_G_current_close_unproven_SYNTHETIC(self):
        out = self.unevaluable(TRANSITION_UNEVALUABLE_CURRENT_CLOSE)
        assert out["bos_evaluability"] == TRANSITION_UNEVALUABLE_CURRENT_CLOSE

    def test_I_cadence_unknown_SYNTHETIC(self):
        out = self.unevaluable(TRANSITION_UNEVALUABLE_CADENCE)
        assert out["bos_evaluability"] == TRANSITION_UNEVALUABLE_CADENCE
        assert out["bos"] is False, "cadence-unknown was bridged into an event"

    def test_the_causes_stay_distinct(self):
        seen = {self.unevaluable(s)["bos_evaluability"] for s in (
            TRANSITION_UNEVALUABLE_PREVIOUS_SLOT,
            TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE,
            TRANSITION_UNEVALUABLE_CURRENT_CLOSE,
            TRANSITION_UNEVALUABLE_CADENCE)}
        assert len(seen) == 4, f"forensic causes collapsed: {seen}"


class TestH_ScheduledClosure:
    """MEASURED indirectly: the resolver walking closures is already pinned in
    tests/test_cadence_authority_boundary.py. This proves the STRUCTURE lane
    consumes that answer rather than re-deriving one."""

    def test_a_resolved_previous_bucket_keeps_the_transition_evaluable(self):
        c = series(final_close=130.0, high_pivot=120.0)
        out = structure(c, prev_close=110.0)
        assert out["bos_evaluability"] == "EVALUATED"
        assert out["bos"] is True


class TestJK_DeliveryIsNotOccurrence:

    def test_J_repeated_scans_of_one_transition_bucket(self):
        """Multiple scans over the same settled bucket re-deliver ONE event."""
        c = series(final_close=130.0, high_pivot=120.0)
        ident = set()
        for _ in range(5):
            out = structure(c, prev_close=110.0)
            assert out["bos"] is True
            ident.add((out["bos_direction"], out["broken_level"],
                       c[-1]["timestamp"]))
        assert len(ident) == 1, "one market event became several occurrences"

    def test_K_next_bucket_still_beyond_is_not_a_new_event(self):
        c = series(final_close=130.0, high_pivot=120.0)
        assert structure(c, prev_close=110.0)["bos"] is True
        # the next settled bucket: previous close is now BEYOND the level
        out = structure(c, prev_close=130.0)
        assert out["bos"] is False, "a persisting position re-fired as an event"
        assert out["position_beyond_swing_high"] is True


class TestL_EqualPriceDoesNotSubstituteIdentity:

    def test_the_broken_level_is_carried_with_its_occurrence(self):
        c = series(final_close=130.0, high_pivot=120.0)
        out = structure(c, prev_close=110.0)
        assert out["broken_level"] == out["last_swing_high"] == 120.0
        from structure.structure_engine import find_swings_detailed
        highs, _ = find_swings_detailed(c, "1m", allow_uncadenced=True)
        assert highs and highs[-1]["pivot_time"], \
            "the source swing carries no occurrence identity"
        assert highs[-1]["swing_id"].count(":") >= 3


class TestMNO_MssRelationIsPreservedVerbatim:
    """Unit 2 changed WHICH breaks qualify, never what makes a break a shift."""

    def test_O_a_fresh_break_with_aligned_bias_is_not_an_mss(self):
        c = series(final_close=130.0, high_pivot=120.0)
        out = structure(c, prev_close=110.0)
        assert out["bos"] is True
        assert out["mss"] is (out["bias"] == "bearish"), \
            "MSS fired without the frozen opposite-bias relation"

    def test_P_persistent_state_cannot_regenerate_an_mss(self):
        """54 of OLD's 90 MSS deliveries were exactly this."""
        c = series(final_close=70.0, low_pivot=80.0)
        assert structure(c, prev_close=90.0)["bos"] is True
        out = structure(c, prev_close=75.0)
        assert out["bos"] is False
        assert out["mss"] is False, "a persistent state produced a fresh MSS"

    def test_Q_unevaluable_transition_cannot_manufacture_an_mss(self):
        c = series(final_close=70.0, low_pivot=80.0)
        out = analyze_structure(c, allow_uncadenced=True,
                                transition={"state": TRANSITION_UNEVALUABLE_PREVIOUS_SLOT})
        assert out["mss"] is False
        assert out["mss_evaluability"] == "UNEVALUABLE_TRANSITION", \
            "MSS uncertainty was collapsed into a bare False"


class TestT_NoAuthoritativeSourceLevel:
    """SYNTHETIC DOCTRINE COVERAGE — zero real-tape examples."""

    def test_no_source_swing_fabricates_no_event(self):
        flat = [bar(m, 105.0, 95.0, 100.0) for m in range(12)]
        out = structure(flat, prev_close=100.0)
        assert out["last_swing_high"] is None and out["last_swing_low"] is None
        assert out["bos"] is False and out["mss"] is False
        assert out["broken_level"] is None


class TestOwnershipConsolidation:
    """Unit 2 moved `previous_slot_close` into the evidence owner so liquidity
    and structure share ONE resolver. Ownership only -- liquidity doctrine is
    closed and untouched."""

    def test_one_resolver_serves_both_lanes(self):
        from market_data import snapshot_builder as SB
        from market_data.swing_evidence import previous_slot_close
        assert SB._previous_slot_close.__module__ == "market_data.snapshot_builder"
        src = __import__("inspect").getsource(SB._previous_slot_close)
        assert "previous_slot_close" in src and "swing_evidence" in src, \
            "snapshot_builder no longer delegates to the single owner"
        assert callable(previous_slot_close)

    def test_no_duplicate_calendar_owner_in_structure(self):
        import inspect
        import structure.structure_engine as SE
        src = inspect.getsource(SE)
        for forbidden in ("venue_calendar", "expected_buckets", "is_expected"):
            assert forbidden not in src, \
                f"structure_engine re-derived cadence itself ({forbidden})"


def opposed(direction, day="2026-08-12"):
    """Twenty 1m bars whose CERTIFIED swing sequence gives a definite bias, then
    a final bar that breaks the OTHER way -- the exact shape MSS requires.

    bearish bias: lower high AND lower low, then a close ABOVE the latest high
    bullish bias: higher high AND higher low, then a close BELOW the latest low

    Pivots need three strictly lower highs / higher lows on each side, so the
    indices below are chosen to satisfy that with room to spare.
    """
    out = []
    for m in range(20):
        out.append(bar(m, 110.0, 100.0, 105.0))
    if direction == "bearish":
        out[4] = bar(4, 130.0, 100.0, 105.0)     # swing high 1
        out[12] = bar(12, 120.0, 100.0, 105.0)   # swing high 2  (LOWER high)
        out[8] = bar(8, 110.0, 90.0, 105.0)      # swing low 1
        out[16] = bar(16, 110.0, 80.0, 105.0)    # swing low 2   (LOWER low)
        out[19] = bar(19, 126.0, 100.0, 124.0)   # closes ABOVE the 120 high
    else:
        out[4] = bar(4, 110.0, 80.0, 105.0)      # swing low 1
        out[12] = bar(12, 110.0, 90.0, 105.0)    # swing low 2   (HIGHER low)
        out[8] = bar(8, 120.0, 100.0, 105.0)     # swing high 1
        out[16] = bar(16, 130.0, 100.0, 105.0)   # swing high 2  (HIGHER high)
        out[19] = bar(19, 110.0, 84.0, 85.0)     # closes BELOW the 90 low
    return out


class TestMN_FreshMssAgainstTheBias:
    """M and N. A shift is a break that fires AGAINST the prevailing structure,
    so the fixtures must build a real opposing bias -- not merely a break."""

    def test_M_fresh_bullish_break_under_bearish_bias_is_an_mss(self):
        c = opposed("bearish")
        out = structure(c, prev_close=118.0)      # 118 <= 120 < 124
        assert out["bias"] == "bearish", f"fixture bias is {out['bias']}"
        assert out["last_swing_high"] == 120.0
        assert out["bos"] is True and out["bos_direction"] == "bullish"
        assert out["mss"] is True
        assert out["mss_evaluability"] == "EVALUATED"

    def test_N_fresh_bearish_break_under_bullish_bias_is_an_mss(self):
        c = opposed("bullish")
        out = structure(c, prev_close=92.0)       # 92 >= 90 > 85
        assert out["bias"] == "bullish", f"fixture bias is {out['bias']}"
        assert out["last_swing_low"] == 90.0
        assert out["bos"] is True and out["bos_direction"] == "bearish"
        assert out["mss"] is True

    def test_R_repeated_scans_of_one_mss_transition_are_one_occurrence(self):
        """R. Same settled transition bucket seen by several scans: one market
        event, several deliveries."""
        c = opposed("bearish")
        identities, deliveries = set(), 0
        for _ in range(6):
            out = structure(c, prev_close=118.0)
            assert out["mss"] is True
            deliveries += 1
            identities.add((out["bos_direction"], out["broken_level"],
                            c[-1]["timestamp"]))
        assert deliveries == 6
        assert len(identities) == 1, "one MSS event became several occurrences"


class TestS_Unit1AuthoritativeSourceCannotRegress:
    """S. The pre-Unit-1 5m defect anchor: a pivot whose canonical neighbour was
    omitted must never become a BOS source level again.

    Reconstructed rather than replayed: a 5m bucket is removed entirely, so the
    pivot that depended on it is uncertified while an earlier pivot remains
    authoritative. NON-VACUOUS -- the legacy path still certifies the bad pivot.
    """

    def tape(self, drop_bucket=None):
        from datetime import datetime, timedelta
        bars, base = [], datetime.fromisoformat("2026-08-12T18:00:00+00:00")
        # A pivot needs `lookback` bars on BOTH sides, so index 2 could never
        # form one -- the first fixture put the authoritative low there and it
        # was silently never a swing at all.
        lows = {5: 90.0, 11: 80.0}                # two candidate swing lows
        for b in range(16):
            if b == drop_bucket:
                continue
            for k in range(5):
                t = base + timedelta(minutes=b * 5 + k)
                bars.append({"timestamp": t.isoformat(), "open": 105.0,
                             "high": 110.0, "low": lows.get(b, 100.0),
                             "close": 105.0, "volume": 10})
        return bars

    def test_an_uncertified_pivot_cannot_supply_the_broken_level(self):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import _bucket_is_settled
        from market_data.swing_evidence import build_swing_evidence
        bars = self.tape(drop_bucket=10)          # neighbour of the 80.0 pivot
        raw = build_timeframes(bars)["5m"]
        settled = [c for c in raw if _bucket_is_settled(raw, c)]
        ev = build_swing_evidence(settled, raw, 5)

        legacy = analyze_structure(settled, allow_uncadenced=True,
                                   transition=transition(95.0))
        final = analyze_structure(settled, ev, transition=transition(95.0))
        assert legacy["last_swing_low"] == 80.0,             "legacy no longer certifies the uncertified pivot; control is vacuous"
        assert final["last_swing_low"] != 80.0,             "an uncertified pivot re-entered Unit-2 as a BOS source level"
        assert final["last_swing_low"] == 90.0,             "the authoritative earlier pivot did not become the source"


class TestInsufficientHistoryIsAlsoUnevaluable:
    """EXTRA COVERAGE beyond A-T, added because a downstream test stumbled over
    this branch rather than a doctrine test catching it.

    `analyze_structure` returns an `insufficient_data` block before any of the
    Unit-2 reasoning runs. That early return predated the transition contract
    and published a structure dict carrying NO evaluability at all -- so a
    consumer could not tell "not enough candles to evaluate" from "evaluated and
    found no event". That is the exact conflation this whole unit exists to
    remove, surviving in the one branch nothing had looked at.

    Locked here so it cannot return quietly.
    """

    def out(self):
        return analyze_structure([bar(0, 101.0, 99.0, 100.0)])

    def test_the_state_is_unevaluable_not_an_evaluated_negative(self):
        out = self.out()
        assert out["state"] == "insufficient_data"
        assert out["bos"] is False
        assert out["bos_evaluability"] == "UNEVALUABLE_INSUFFICIENT_CANDLES"
        assert out["bos_evaluability"] != "EVALUATED",             "insufficient history was recorded as an evaluated no-event"

    def test_no_event_metadata_is_published(self):
        out = self.out()
        for key in ("bos_direction", "broken_level", "break_close"):
            assert out.get(key) is None, f"{key} implied a break with no history"

    def test_position_state_is_explicit_not_absent(self):
        """False, not missing: the position IS known -- there is no swing to be
        beyond -- and a consumer must not have to infer that from a KeyError."""
        out = self.out()
        assert out["position_beyond_swing_high"] is False
        assert out["position_beyond_swing_low"] is False

    def test_mss_carries_the_same_honesty(self):
        out = self.out()
        assert out["mss"] is False
        assert out["mss_evaluability"] == "UNEVALUABLE_INSUFFICIENT_CANDLES"
        assert out["mss_evaluability"] != "EVALUATED"
