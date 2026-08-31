"""PROTECTED-LEVEL-REJECTION-AGGRESSIVE-1 — a wick is not a setup.

2026-08-20. The operator drew a short at the retest of the 09:30 protected high
and asked why Luna never took it. The forensic answer was not discretion: the
trade had no mechanical tool to be expressed through.

`_find_rejection_zone` takes `max(recent, key=upper_wick)` across five bars and
calls that candle's BODY the zone. At 11:02:10 it published a 15m "bearish
rejection block" at 29350.25-29367.75 while the level it was nominally rejecting
from sat at 29470.25 -- a hundred points away, on the wrong side of the market.

    A BIG WICK IS NOT A REJECTION.
    A REJECTION IS A FAILURE *AT* SOMETHING.

Without a structural referent every candle in a two-sided range qualifies. On
this tape: 13 candidates in two hours unanchored, 1 once an anchor is required.
That single survivor is the setup on the operator's chart.

TWO GEOMETRY CORRECTIONS the 3-minute chart forced:

  THE ZONE IS THE WICK, not the body. The body is the part price did NOT reject
  from. Bearish: body_top -> wick_high. Bullish: wick_low -> body_bottom.

  THE BLOCK WAS CREATED AT 09:36, not by the 11:02 retest. It had existed for
  eighty-four minutes. Building it from the retest candle produces the wrong
  object entirely -- a retest is not a creation.

FRACTAL-TIMEFRAME LAW. One extreme appears on many timeframes; those are
RESOLUTIONS of one event, not competing setups. The protected swing owns the
LEVEL, the finest allowed settled candle that prints that extreme AND
independently expresses the rejection owns the GEOMETRY, and both provenances
travel together. Selection is by resolution, NEVER by which timeframe yields a
tighter stop. Here the criteria are over-determined: of the allowed source
timeframes only 3m expresses the rejection at all.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from toolbox.price_levels import (NO_ANCHOR,                        # noqa: E402
                                  NO_CREATING_CANDLE,
                                  PROTECTED_LEVEL_PROXIMITY_POINTS,
                                  REJECTION_ANCHOR_ROLES,
                                  _expresses_rejection,
                                  _rejection_zone_from,
                                  anchored_rejection_block)

ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260820_110334_MNQ.json")

PROTECTED_HIGH = 29470.25
BLOCK_LOW = 29448.50
MEAN_THRESHOLD = 29459.375


def snapshot():
    with open(ARCHIVE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh).get("raw_snapshot") or {})


def block(direction="bearish", snap=None):
    return anchored_rejection_block(snap if snap is not None else snapshot(),
                                    direction)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheAugustTwentyBlock:
    """The object on the operator's 3-minute chart, reproduced from the tape."""

    def test_it_is_available(self):
        assert block()["available"] is True

    def test_the_zone_is_the_wick_region(self):
        b = block()
        assert (b["zone_low"], b["zone_high"]) == (BLOCK_LOW, PROTECTED_HIGH)

    def test_the_mean_threshold_is_published(self):
        assert block()["mean_threshold"] == MEAN_THRESHOLD

    def test_the_creating_candle_is_the_nine_thirty_six_bar(self):
        """NOT the 11:02 retest. The block predates it by 84 minutes."""
        assert block()["creating_candle_timestamp"] == "2026-08-20T13:36:00+00:00"

    def test_the_invalidation_is_the_level_not_the_wick(self):
        """The thesis is wrong when price ACCEPTS through the structure, not
        when it ticks past the candle that rejected from it."""
        assert block()["invalidation_level"] == PROTECTED_HIGH

    def test_the_body_zone_the_old_detector_would_have_built_is_not_this(self):
        b = block()
        assert (29437.00, 29448.50) != (b["zone_low"], b["zone_high"])


class TestBothProvenancesTravel:
    """FRACTAL-TIMEFRAME LAW: the swing owns the level, the candle the geometry."""

    def test_the_anchor_is_the_canonical_swing(self):
        b = block()
        assert b["anchor_swing_id"] == "5m:swing_high:29470.2"
        assert b["anchor_level"] == PROTECTED_HIGH
        assert b["anchor_basis"] == "buy_side_raid_rejected"

    def test_the_anchor_timeframe_and_block_timeframe_differ(self):
        b = block()
        assert b["anchor_tf"] == "5m"
        assert b["rejection_block_tf"] == "3m"

    def test_the_block_does_not_masquerade_as_its_anchor(self):
        assert block()["rejection_block_tf"] != block()["anchor_tf"]

    def test_only_one_block_is_produced_for_one_event(self):
        """5m and 15m contain the same 29470.25. They are witnesses."""
        b = block()
        assert isinstance(b, dict)          # one object, not a list of three


class TestTheMorphologyGate:
    """A candle that CONTAINS the extreme has not necessarily EXPRESSED it."""

    @pytest.mark.parametrize("o,h,l,c,expected", [
        (29448.50, 29470.25, 29431.00, 29437.00, True),    # 3m  wick 21.75 > body 11.50
        (29403.75, 29470.25, 29371.00, 29439.25, False),   # 5m  wick 31.00 < body 35.50
        (29350.75, 29470.25, 29338.50, 29443.00, False),   # 15m wick 27.25 < body 92.25
    ])
    def test_the_wick_must_dominate_the_body(self, o, h, l, c, expected):
        candle = {"open": o, "high": h, "low": l, "close": c,
                  "body_size": abs(c - o), "upper_wick": h - max(o, c),
                  "lower_wick": min(o, c) - l}
        assert _expresses_rejection(candle, "bearish") is expected

    def test_a_bar_that_closed_near_its_high_accepted_rather_than_rejected(self):
        candle = {"open": 29400.0, "high": 29470.25, "low": 29395.0,
                  "close": 29468.0, "body_size": 68.0,
                  "upper_wick": 2.25, "lower_wick": 5.0}
        assert _expresses_rejection(candle, "bearish") is False

    def test_the_gate_is_what_selects_three_minute_here(self):
        """Resolution and morphology agree; the answer is over-determined."""
        assert block()["rejection_block_tf"] == "3m"


class TestTheRoleGate:
    """The operator's consolidation concern: interior wicks must not qualify."""

    def test_the_permitted_roles_are_structural_only(self):
        assert REJECTION_ANCHOR_ROLES == ("context", "active_leg")

    def test_a_transition_only_registry_yields_no_anchor(self):
        snap = snapshot()
        highs = snap["protected_swings"]["by_timeframe"]["highs"]
        for rec in highs.values():
            rec["role"] = "transition"
        b = block(snap=snap)
        assert b["available"] is False
        assert b["reason"] == NO_ANCHOR

    def test_an_execution_only_registry_yields_no_anchor(self):
        snap = snapshot()
        for rec in snap["protected_swings"]["by_timeframe"]["highs"].values():
            rec["role"] = "execution"
        assert block(snap=snap)["reason"] == NO_ANCHOR

    def test_an_empty_registry_yields_no_anchor(self):
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["highs"] = {}
        assert block(snap=snap)["reason"] == NO_ANCHOR

    def test_the_active_leg_anchor_is_preferred(self):
        assert block()["anchor_role"] == "active_leg"


class TestPresenceIsLiveness:
    def test_a_removed_swing_cannot_anchor_anything(self):
        """`ProtectedSwingTracker` POPS a swing once a close accepts through it,
        so an absent swing IS a violated one. No `retired` flag exists."""
        snap = snapshot()
        del snap["protected_swings"]["by_timeframe"]["highs"]["5m"]
        b = block(snap=snap)
        assert b["available"] is False or b["anchor_tf"] != "5m"

    def test_the_tracker_really_does_pop_on_violation(self):
        import inspect
        from narrative_authority import protected_swings as PS
        src = inspect.getsource(PS.ProtectedSwingTracker)
        assert "self.protected_highs.pop(tf, None)" in src
        assert "self.protected_lows.pop(tf, None)" in src


class TestTheProximityBand:
    def test_the_band_is_the_ruled_fifteen_points(self):
        assert PROTECTED_LEVEL_PROXIMITY_POINTS == 15.00

    def test_an_exact_print_of_the_extreme_is_zero_distance(self):
        assert block()["distance_to_anchor"] == 0.0

    def test_an_exact_print_outranks_a_nearer_finer_candle(self):
        """PRECEDENCE, and a real bug this caught. Searching band and
        resolution together let a 3m candle 14.75 points away outrank a 5m
        candle sitting ON the level. "Actually prints the extreme" is the
        primary criterion; resolution only breaks ties among equals."""
        b = block("bullish")
        assert b["distance_to_anchor"] == 0.0
        assert b["wick_extreme"] == b["anchor_level"]

    def test_both_sides_of_this_tape_have_exact_prints(self):
        snap = snapshot()
        for d in ("bearish", "bullish"):
            assert anchored_rejection_block(
                snap, d, proximity_points=0.0)["available"] is True

    def test_the_band_is_a_fallback_not_a_shortcut(self):
        """With no exact print available, the band admits a near miss."""
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["highs"]["5m"]["level"] = \
            PROTECTED_HIGH + 9.0
        b = block(snap=snap)
        assert b["available"] is True
        assert 0 < b["distance_to_anchor"] <= PROTECTED_LEVEL_PROXIMITY_POINTS

    def test_a_wick_beyond_the_band_cannot_claim_the_level(self):
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["highs"]["5m"]["level"] = 29600.0
        assert block(snap=snap)["reason"] == NO_CREATING_CANDLE


class TestTheBullishMirror:
    def test_it_anchors_to_a_protected_low(self):
        b = block("bullish")
        assert b["anchor_swing_id"] == "5m:swing_low:29309.2"
        assert b["invalidation_level"] == 29309.25

    def test_its_zone_is_the_lower_wick_region(self):
        b = block("bullish")
        assert b["zone_low"] < b["zone_high"]
        assert b["zone_low"] == b["wick_extreme"]

    @pytest.mark.parametrize("direction,o,c,h,l,lo,hi", [
        ("bearish", 29448.50, 29437.00, 29470.25, 29431.00, 29448.50, 29470.25),
        ("bullish", 29330.00, 29340.00, 29345.00, 29324.00, 29324.00, 29330.00),
    ])
    def test_the_zone_formula_is_symmetric(self, direction, o, c, h, l, lo, hi):
        z_lo, z_hi, mt = _rejection_zone_from(
            {"open": o, "close": c, "high": h, "low": l}, direction)
        assert (z_lo, z_hi) == (lo, hi)
        assert mt == round((lo + hi) / 2, 3)


class TestNegativeControls:
    def test_a_settled_only_requirement_is_enforced(self):
        snap = snapshot()
        for tf in ("3m", "5m", "15m"):
            for c in (snap.get("timeframes", {}).get(tf, {})
                      .get("recent_candles") or []):
                c["temporal_status"] = "forming"
        assert block(snap=snap)["reason"] == NO_CREATING_CANDLE

    def test_no_timeframes_yields_no_creating_candle(self):
        snap = snapshot()
        snap["timeframes"] = {}
        assert block(snap=snap)["reason"] == NO_CREATING_CANDLE

    def test_it_never_raises_on_malformed_input(self):
        for bad in (None, {}, {"protected_swings": None},
                    {"protected_swings": {"by_timeframe": {"highs": "nope"}}}):
            out = anchored_rejection_block(bad, "bearish")
            assert isinstance(out, dict) and "available" in out

    def test_a_refusal_always_names_its_reason(self):
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["highs"] = {}
        b = block(snap=snap)
        assert b["available"] is False and b["reason"]

    def test_mechanics_does_not_decide_the_trade(self):
        """No field advertises an action. Selection remains Luna's."""
        b = block()
        for verdict in ("should_enter", "take_trade", "signal", "recommendation",
                        "confidence", "score"):
            assert verdict not in b


class TestTheGenericDetectorIsUntouched:
    def test_the_old_rejection_zone_finder_still_exists(self):
        from toolbox.price_levels import _find_rejection_zone
        assert callable(_find_rejection_zone)

    def test_it_still_uses_the_body_convention(self):
        """The generic scan answers a different question and is not changed."""
        import inspect
        from toolbox.price_levels import _find_rejection_zone
        src = inspect.getsource(_find_rejection_zone)
        assert "body_lo" in src and "body_hi" in src

    def test_the_anchored_variant_does_not_call_it(self):
        import inspect
        src = inspect.getsource(anchored_rejection_block)
        assert "_find_rejection_zone" not in src


class TestItReachesLunaWithoutAmbiguity:
    """The catalog is where the block becomes visible — and where publishing it
    carelessly would have created a silent wrong-resolution defect."""

    @staticmethod
    def catalog():
        from broker.luna_candidate_producer import authorized_tool_catalog
        return authorized_tool_catalog(snapshot())

    def test_the_anchored_block_is_published(self):
        rows = [r for r in self.catalog()
                if r.get("level_type") == "protected_level_rejection_block"]
        assert {r["direction"] for r in rows} == {"bearish", "bullish"}

    def test_no_tool_name_appears_twice(self):
        """Outside plain FVG the resolver takes `eligible[0]` WITHOUT refusing,
        so a duplicate tool name silently resolves on list order. Publishing the
        anchored block beside the generic one would have handed the producer the
        unanchored zone -- 100 points from the level it claims to reject from."""
        import collections
        names = collections.Counter(r["tool"] for r in self.catalog())
        assert not [t for t, n in names.items() if n > 1]

    def test_the_anchored_block_supersedes_the_generic_one(self):
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        assert row["level_type"] == "protected_level_rejection_block"
        assert (row["zone_low"], row["zone_high"]) == (BLOCK_LOW, PROTECTED_HIGH)

    def test_the_superseded_row_is_preserved_as_evidence(self):
        """Supersession must not destroy what it replaced."""
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        prior = row["superseded_generic"]
        assert prior["level_type"] == "rejection_block_zone"
        assert (prior["zone_low"], prior["zone_high"]) == (29350.25, 29367.75)

    def test_the_superseded_zone_really_was_nowhere_near_the_level(self):
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        assert PROTECTED_HIGH - row["superseded_generic"]["zone_high"] > 100.0

    def test_the_mean_threshold_reaches_the_brain(self):
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        assert row["mean_threshold"] == MEAN_THRESHOLD

    def test_both_provenances_reach_the_brain(self):
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        assert row["anchor_tf"] == "5m" and row["source_tf"] == "3m"
        assert row["anchor_swing_id"] == "5m:swing_high:29470.2"
        assert row["anchor_role"] == "active_leg"

    def test_other_families_are_untouched_by_supersession(self):
        tools = {r["tool"] for r in self.catalog()}
        assert "bearish_ote_after_reclaim" in tools
        assert "bearish_breaker" in tools

    def test_a_snapshot_with_no_anchor_keeps_the_generic_row(self):
        """Supersession happens only where an anchored block actually exists."""
        from broker.luna_candidate_producer import authorized_tool_catalog
        snap = snapshot()
        for rec in snap["protected_swings"]["by_timeframe"]["highs"].values():
            rec["role"] = "transition"
        for rec in snap["protected_swings"]["by_timeframe"]["lows"].values():
            rec["role"] = "transition"
        rows = [r for r in authorized_tool_catalog(snap)
                if r.get("tool_family") == "rejection_block"]
        assert rows and all(
            r["level_type"] != "protected_level_rejection_block" for r in rows)

    def test_the_2026_08_20_retest_failed_beneath_the_published_threshold(self):
        """The fact the operator reads off the chart, now a mechanical field."""
        row = [r for r in self.catalog()
               if r["tool"] == "bearish_rejection_block"][0]
        retest_high = 29457.25
        assert row["zone_low"] <= retest_high <= row["zone_high"]
        assert retest_high < row["mean_threshold"]
        assert round(row["mean_threshold"] - retest_high, 3) == 2.125
