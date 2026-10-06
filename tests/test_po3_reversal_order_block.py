"""PO3-REVERSAL-ORDER-BLOCK-1 — the manipulation leg is not yet an order block.

The operator's primary expansion-entry model, illustrated on MNQ 5m,
2026-08-19 ~01:45-02:15 ET:

    ACCUMULATION -> SELL-SIDE MANIPULATION -> BULLISH EXPANSION (change in state
    of delivery) -> the prior manipulation run is RECLASSIFIED as the bullish
    reversal order block -> retracement into it -> distribution.

    "this series of down candles represent a bullish orderblock"
    "these three bullish candles create the expansion / bullish engulfing, that
     creates the bullish orderblock once the highlighted down candles get
     violated in this expansion"

THE CAUSALITY IS THE OBJECT, and the ordering is the whole point. During the
manipulation those bearish candles are BEARISH DELIVERY. They do not become a
bullish order block because they are bearish, because they sit near a low, or
because sell-side was taken. They become one only in retrospect, once opposing
expansion VIOLATES the run and proves delivery changed state. Publishing the
candidate before that violation would hand the Brain an execution object the
market has not yet created.

WHY A DISTINCT FAMILY, not `order_block` under a reversal playbook. The audit
found `order_block` authorized ONLY under `trend_continuation`; the playbook
literally named for this sequence -- `manipulation_to_distribution` -- cannot
use it. Adding it there would have let ANY continuation block ride the reversal
doctrine and made the causal requirement unenforceable. The operator ruled for a
distinct causally-validated object; generic `order_block` is untouched.

GEOMETRY IS NOT REINVENTED. `_ob_block_run` / `_find_ob_block` were already
written, tested against real MNQ bars (2026-07-24) and NEVER WIRED to
production -- the second such find in this session. Their run convention is
reused as-is.

TWO EXTREMES, KEPT APART. `run_extreme` is a GEOMETRY fact; the protected
manipulation swing is the INVALIDATION AUTHORITY. On the operator's chart they
nearly coincide. They are still different claims, and both are published --
the same provenance discipline that saved the rejection block.

FIXTURE PROVENANCE — RECONSTRUCTED OPERATOR ILLUSTRATION. Doctrine/geometry
fixture, NOT historical bot replay evidence. The bars below are reconstructed
from the operator's annotated chart, not replayed from an archived scan. The 2026-08-19 session
armed at 09:52 ET and this setup formed hours earlier, so no scan artifact of it
exists. Levels the operator stated on the chart (swing 29429.75 / 29499.00 and
the OTE ladder) are used as the anchors.

THESE TESTS PROVE THE MECHANICS REPRESENT THE MODEL. They do NOT establish what
Luna would have decided: we do not hold the frozen information state for an
overnight setup, so no Brain replay is run against this fixture. When this
pattern next occurs inside an archived or live session, it gets the same
uncontaminated A/B treatment the rejection block received.
"""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from toolbox.price_levels import (NO_MANIPULATION,                  # noqa: E402
                                  NO_TERMINAL_RUN, NOT_YET_VALIDATED,
                                  PO3_REVERSAL_OB_LEVEL_TYPE,
                                  _reversal_leg,
                                  po3_reversal_order_block)

SWING_LOW = 29429.75
SWING_HIGH = 29499.00


def _c(ts, o, h, l, c, settled=True):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
            "direction": "bullish" if c > o else ("bearish" if c < o else "doji"),
            "body_size": abs(c - o), "upper_wick": h - max(o, c),
            "lower_wick": min(o, c) - l,
            "temporal_status": "settled" if settled else "forming"}


def _ts(hhmm):
    hour, minute = (int(part) for part in hhmm.split(":"))
    return f"2026-08-19T{hour:02d}:{minute:02d}:00+00:00"


SWEEP_TIME = _ts("02:10")
REGISTERED_AT = _ts("02:12")  # observed registration follows its source bar

#: Opposing run, protected pivot, settled sweep/reclaim, then confirmation.
BARS = [
    _c(_ts("01:30"), 29480.00, 29492.00, 29478.00, 29486.00),
    _c(_ts("01:35"), 29470.00, 29483.00, 29468.00, 29474.00),
    _c(_ts("01:45"), 29472.00, 29474.00, 29462.00, 29464.00),   # run starts
    _c(_ts("01:50"), 29464.00, 29466.00, 29452.00, 29454.00),
    _c(_ts("01:55"), 29454.00, 29457.00, 29444.00, 29446.00),
    _c(_ts("02:00"), 29446.00, 29448.00, 29434.00, 29436.00),
    _c(_ts("02:05"), 29436.00, 29438.00, SWING_LOW, 29432.00),  # protected pivot
    _c(_ts("02:10"), 29432.00, 29440.00, 29428.75, 29432.00),   # sweep and reclaim
    _c(_ts("02:15"), 29432.00, 29440.00, 29431.00, 29439.00),
    _c(_ts("02:20"), 29439.00, 29478.00, 29438.00, 29476.00),   # first close through
]

#: `_ob_block_run` takes the contiguous opposing run BEFORE the swing candle --
#: the 02:05 bar that printed the low is the anchor and is excluded. That is
#: the existing tested convention and is preserved, not bent to the fixture.
RUN_BODY_LOW = 29436.00      # min(open, close) across 01:45-02:00
RUN_BODY_HIGH = 29472.00     # max(open, close) across 01:45-02:00
RUN_EXTREME = 29434.00       # lowest low IN THE RUN, not the swing low
MEAN_THRESHOLD = round((RUN_BODY_LOW + RUN_BODY_HIGH) / 2, 3)


def snapshot(**over):
    sweep = {
        "occurrence_id": "LIQUIDITY_SWEEP:fixture:5m:2026-08-19T02:10:00+00:00",
        "event_type": "LIQUIDITY_SWEEP", "contract": "CON.F.US.MNQ.Z26",
        "source_tf": "5m", "event_time": SWEEP_TIME,
        "sweep_direction": "below_low", "swept_level": SWING_LOW,
        "reclaimed": True, "reclaim_basis": "same_bar_close_back_through_level",
        "source_bars": [_ts("02:05"), SWEEP_TIME],
    }
    registration = {
        "occurrence_id": "PROTECTED_SWING_REGISTERED:fixture:5m:anchor-life-1",
        "event_type": "PROTECTED_SWING_REGISTERED",
        "contract": "CON.F.US.MNQ.Z26", "source_tf": "5m",
        "event_time": REGISTERED_AT, "source_bar_time": SWEEP_TIME,
        "side": "low", "level": SWING_LOW,
        "basis": "sell_side_raid_rejected", "swing_id": "5m:swing_low:29429.75",
        "registered_at": REGISTERED_AT,
    }
    snap = {
        "symbol": "MNQ",
        "contract_id": "CON.F.US.MNQ.Z26",
        "timestamp": BARS[-1]["timestamp"],
        "derived_state": {"current": True, "history_revision": 1,
                          "derived_revision": 1},
        "timeframes": {"5m": {"recent_candles": copy.deepcopy(BARS)}},
        "structure": {"5m": {"last_swing_low": SWING_LOW,
                             "last_swing_high": SWING_HIGH}},
        "liquidity": {"5m": {"sweep_detected": False,
                             "sweep_direction": None,
                             "reclaim_detected": False}},
        "reversal_sweep_history": [sweep],
        "protected_swing_lifetime_history": [registration],
        "expansion": {"5m": {"state": "healthy_expansion",
                             "displacement_detected": True}},
        "protected_swings": {"by_timeframe": {"lows": {
            "5m": {"level": SWING_LOW, "role": "active_leg",
                   "swing_id": "5m:swing_low:29429.75",
                   "timeframe": "5m", "registered_at": REGISTERED_AT,
                   "basis": "sell_side_raid_rejected"}}}},
    }
    snap.update(over)
    return snap


def block(direction="bullish", snap=None):
    return po3_reversal_order_block(snap if snap is not None else snapshot(),
                                    direction)


def bearish_mirror_snapshot():
    """Price-mirror the synthetic bullish fixture to test the same causal law."""
    snap = snapshot()
    center_twice = 60000.0

    def mirror(value):
        return round(center_twice - value, 4)

    bars = []
    for source in BARS:
        bar = copy.deepcopy(source)
        bar.update({
            "open": mirror(source["open"]),
            "high": mirror(source["low"]),
            "low": mirror(source["high"]),
            "close": mirror(source["close"]),
            "direction": ("bearish" if source["close"] > source["open"]
                          else "bullish" if source["close"] < source["open"]
                          else "doji"),
        })
        bars.append(bar)
    anchor = mirror(SWING_LOW)
    snap["timeframes"]["5m"]["recent_candles"] = bars
    snap["timestamp"] = bars[-1]["timestamp"]
    snap["structure"]["5m"] = {
        "last_swing_high": anchor,
        "last_swing_low": mirror(SWING_HIGH),
    }
    snap["reversal_sweep_history"][0].update({
        "sweep_direction": "above_high", "swept_level": anchor,
    })
    snap["protected_swing_lifetime_history"][0].update({
        "side": "high", "level": anchor,
        "basis": "buy_side_raid_rejected",
        "swing_id": f"5m:swing_high:{anchor:g}",
    })
    snap["protected_swings"]["by_timeframe"] = {
        "highs": {"5m": {
            "level": anchor, "role": "active_leg",
            "swing_id": f"5m:swing_high:{anchor:g}",
            "timeframe": "5m", "registered_at": REGISTERED_AT,
            "basis": "buy_side_raid_rejected",
        }},
        "lows": {},
    }
    return snap


# ══════════════════════════════════════════════════════════════════════════════
class TestTheObjectIsBuilt:
    def test_it_is_established_after_the_expansion(self):
        assert block()["available"] is True

    def test_the_zone_is_the_runs_body_envelope(self):
        b = block()
        assert (b["zone_low"], b["zone_high"]) == (RUN_BODY_LOW, RUN_BODY_HIGH)

    def test_the_mean_threshold_is_published(self):
        assert block()["mean_threshold"] == MEAN_THRESHOLD

    def test_it_is_a_distinct_level_type(self):
        assert block()["level_type"] == PO3_REVERSAL_OB_LEVEL_TYPE

    def test_the_run_spans_multiple_candles(self):
        """The operator's 'series of down candles', not one candle."""
        assert block()["creating_run_length"] >= 3

    def test_bearish_mirror_requires_and_accepts_its_own_buy_side_reversal(self):
        result = block("bearish", snap=bearish_mirror_snapshot())
        assert result["available"] is True, result
        assert result["liquidity_side_taken"] == "buy_side"
        assert result["manipulation_sweep_direction"] == "above_high"
        assert result["invalidation_level"] == round(60000.0 - SWING_LOW, 4)


class TestTheCausalBirthCertificate:
    def test_it_names_the_liquidity_side_taken(self):
        assert block()["liquidity_side_taken"] == "sell_side"

    def test_it_names_the_manipulation_sweep(self):
        b = block()
        assert b["manipulation_sweep_direction"] == "below_low"
        assert b["manipulation_reclaimed"] is True

    def test_it_names_the_creating_run(self):
        b = block()
        assert b["creating_run_start"] and b["creating_run_end"]
        assert b["creating_run_start"] < b["creating_run_end"]

    def test_it_names_the_validating_expansion(self):
        b = block()
        assert b["validation_basis"] == "bullish_expansion_close_through_run_envelope"
        assert b["validation_close"] > RUN_BODY_HIGH

    def test_the_validation_happens_after_the_run(self):
        b = block()
        assert b["validation_timestamp"] > b["creating_run_end"]


class TestTheManipulationLegIsNotYetAnOrderBlock:
    """The ordering IS the doctrine."""

    @staticmethod
    def _before_expansion():
        snap = snapshot()
        # The sweep and first response have happened; the body-envelope close
        # has not. Transient sweep flags are already expired.
        snap["timeframes"]["5m"]["recent_candles"] = copy.deepcopy(BARS[:9])
        snap["timestamp"] = BARS[8]["timestamp"]
        return snap

    def test_no_object_exists_before_the_violation(self):
        b = block(snap=self._before_expansion())
        assert b["available"] is False

    def test_the_refusal_names_the_missing_link(self):
        assert block(snap=self._before_expansion())["reason"] == NOT_YET_VALIDATED

    def test_bearish_candles_near_a_low_are_not_enough(self):
        """Not 'bearish', not 'near a low', not 'sell-side taken'."""
        snap = self._before_expansion()
        assert snap["reversal_sweep_history"]                       # sweep DID happen
        assert block(snap=snap)["available"] is False              # still no object

    def test_a_wick_through_the_run_is_not_a_violation(self):
        """A probe is not a change in the state of delivery."""
        snap = snapshot()
        bars = copy.deepcopy(BARS[:9])
        bars.append(_c(_ts("02:20"), 29439.00, 29480.00, 29438.00, 29460.00))  # wick only
        snap["timeframes"]["5m"]["recent_candles"] = bars
        snap["timestamp"] = bars[-1]["timestamp"]
        assert block(snap=snap)["reason"] == NOT_YET_VALIDATED

    def test_colour_alone_does_not_validate(self):
        """Bullish candles closing through, but no canonical expansion evidence."""
        snap = snapshot()
        snap["expansion"] = {"5m": {"state": "contraction",
                                    "displacement_detected": False}}
        assert block(snap=snap)["reason"] == NOT_YET_VALIDATED


class TestTheManipulationIsRequired:
    def test_no_sweep_means_no_reversal_block(self):
        snap = snapshot()
        snap["reversal_sweep_history"] = []
        assert block(snap=snap)["reason"] == NO_MANIPULATION

    def test_the_wrong_side_sweep_does_not_qualify_a_bullish_block(self):
        """A buy-side raid does not create a BULLISH reversal block."""
        snap = snapshot()
        snap["reversal_sweep_history"][0]["sweep_direction"] = "above_high"
        assert block(snap=snap)["reason"] == NO_MANIPULATION

    def test_future_settled_validation_bar_cannot_form_an_earlier_object(self):
        snap = snapshot()
        snap["timestamp"] = _ts("02:15")
        result = po3_reversal_order_block(snap, "bullish")
        assert result["available"] is False

    def test_a_bearish_block_needs_the_buy_side_taken(self):
        snap = snapshot()
        snap["reversal_sweep_history"][0]["sweep_direction"] = "above_high"
        assert block("bearish", snap=snap)["available"] is False

    def test_an_unresolved_direction_is_refused(self):
        assert block("conflicted")["reason"] == NO_MANIPULATION


class TestTwoExtremesStaySeparate:
    def test_the_run_extreme_is_published_as_geometry(self):
        """The run's own lowest low -- NOT the swing low, which belongs
        to the anchor candle excluded from the run."""
        assert block()["run_extreme"] == RUN_EXTREME

    def test_invalidation_comes_from_the_protected_swing(self):
        b = block()
        assert b["protected_swing_id"] == "5m:swing_low:29429.75"
        assert b["invalidation_level"] == SWING_LOW

    def test_they_are_published_separately_even_when_they_differ(self):
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["lows"]["5m"]["level"] = 29425.00
        b = block(snap=snap)
        assert b["available"] is False
        assert b["reason"] == "SWEEP_NOT_ASSOCIATED_WITH_CURRENT_PROTECTED_ANCHOR_LIFE"

    def test_unrelated_cross_timeframe_anchor_never_supplies_invalidation(self):
        from broker.luna_candidate_producer import authorized_tool_catalog

        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["lows"].pop("5m")
        unrelated = {
            "level": SWING_LOW - 8.0, "role": "active_leg",
            "swing_id": "15m:unrelated-low-life",
            "timeframe": "15m", "registered_at": REGISTERED_AT,
            "basis": "sell_side_raid_rejected",
        }
        snap["protected_swings"]["by_timeframe"]["lows"]["15m"] = unrelated
        life = copy.deepcopy(snap["protected_swing_lifetime_history"][0])
        life.update({
            "occurrence_id": "PROTECTED_SWING_REGISTERED:fixture:15m:unrelated",
            "source_tf": "15m", "side": "low", "level": unrelated["level"],
            "swing_id": unrelated["swing_id"],
        })
        snap["protected_swing_lifetime_history"].append(life)

        result = block(snap=snap)
        assert result["available"] is False
        assert result["reason"] == \
            "SWEEP_NOT_ASSOCIATED_WITH_CURRENT_PROTECTED_ANCHOR_LIFE"
        assert not [row for row in authorized_tool_catalog(snap)
                    if row.get("tool_family") == "po3_reversal_order_block"]

    def test_no_fixed_stop_distance_is_encoded(self):
        import inspect
        from toolbox import price_levels as PL
        src = inspect.getsource(PL.po3_reversal_order_block)
        for n in ("30", "30.0", "35", "50"):
            assert f"= {n}" not in src


class TestTheLegIsCausallyOwned:
    """The third 50% must belong to THIS reversal.

    An earlier version read `structure[tf].last_swing_high/low` -- whatever pair
    the structure engine happened to hold. That is not necessarily the leg the
    reversal created, and choosing a swing because its midpoint clusters more
    prettily with the FVG or the block would be MANUFACTURING confluence.
    Confluence is observed, not manufactured. (`retracement_equilibrium` was
    removed rather than left behind: a superseded helper that computes a
    non-causal 0.50 is a trap, not merely dead code.)
    """

    def test_the_leg_low_is_the_protected_manipulation_swing(self):
        leg = block()["retracement_leg"]
        assert leg["low"] == SWING_LOW
        assert leg["low_source"] == "protected_manipulation_swing"

    def test_the_leg_high_is_the_validated_expansion_extreme(self):
        leg = block()["retracement_leg"]
        assert leg["high_source"] == "validated_expansion_extreme"
        assert leg["high"] == max(c["high"] for c in BARS[9:])

    def test_the_leg_cannot_borrow_a_high_the_reversal_never_made(self):
        """Measured from the validating candle forward, never before it."""
        leg = block()["retracement_leg"]
        assert leg["high"] <= max(c["high"] for c in BARS[9:])
        assert leg["expansion_from"] == _ts("02:20")

    def test_the_equilibrium_is_the_midpoint_of_THAT_leg(self):
        leg = block()["retracement_leg"]
        assert leg["equilibrium_50"] == round(
            leg["low"] + (leg["high"] - leg["low"]) * 0.5, 2)

    def test_it_is_not_the_arbitrary_structure_swing_midpoint(self):
        """The regression: the old value was 29464.38 from struct swings."""
        leg = block()["retracement_leg"]
        assert leg["equilibrium_50"] != round((SWING_LOW + SWING_HIGH) / 2, 2)

    def test_ote_is_restated_but_untouched(self):
        leg = block()["retracement_leg"]
        assert (leg["ote_low_pct"], leg["ote_high_pct"]) == (0.62, 0.79)

    def test_the_superseded_helper_is_gone(self):
        import toolbox.price_levels as PL
        assert not hasattr(PL, "retracement_equilibrium")

    def test_a_degenerate_leg_is_reported_not_invented(self):
        assert _reversal_leg([], None, "bullish", 100.0)["retracement_leg"] is None


class TestSafety:
    def test_it_never_raises(self):
        for bad in (None, {}, {"timeframes": None}, {"liquidity": "x"},
                    {"timeframes": {"5m": {"recent_candles": "x"}}}):
            out = po3_reversal_order_block(bad, "bullish")
            assert isinstance(out, dict) and "available" in out

    def test_every_refusal_names_a_reason(self):
        for snap in (None, {}, snapshot()):
            out = po3_reversal_order_block(snap, "bullish")
            assert out["available"] is True or out["reason"]

    def test_forming_candles_cannot_validate(self):
        snap = snapshot()
        bars = copy.deepcopy(BARS)
        for c in bars[8:]:
            c["temporal_status"] = "forming"
        snap["timeframes"]["5m"]["recent_candles"] = bars
        assert block(snap=snap)["available"] is False

    def test_generic_order_block_is_untouched(self):
        from toolbox.price_levels import _find_ob
        assert callable(_find_ob)
        import inspect
        assert "order block" in inspect.getdoc(_find_ob).lower()


class TestTheFamilyIsAuthorizedWhereItBelongs:
    """A distinct family, reachable only through the REVERSAL playbooks."""

    def test_it_is_a_recognised_concrete_expression(self):
        from ai_brain.brain_validation import CONCRETE_TOOL_FAMILIES
        assert "po3_reversal_order_block" in CONCRETE_TOOL_FAMILIES

    def test_both_directional_tools_are_canonical(self):
        from toolbox.tool_library import VALID_TOOLS
        for t in ("bullish_po3_reversal_order_block",
                  "bearish_po3_reversal_order_block"):
            assert t in VALID_TOOLS, t

    @pytest.mark.parametrize("playbook", ["liquidity_sweep_reversal",
                                          "manipulation_to_distribution"])
    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_it_is_authorized_under_both_reversal_playbooks(self, playbook, direction):
        from toolbox.tool_library import _ELIGIBLE
        assert f"{direction}_po3_reversal_order_block" in _ELIGIBLE[playbook][direction]

    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_it_is_NOT_authorized_under_trend_continuation(self, direction):
        """The whole reason for a distinct family. A continuation block must
        never acquire the reversal doctrine by being renamed."""
        from toolbox.tool_library import _ELIGIBLE
        assert f"{direction}_po3_reversal_order_block" not in \
            _ELIGIBLE["trend_continuation"][direction]

    def test_generic_order_block_keeps_its_continuation_home(self):
        from toolbox.tool_library import _ELIGIBLE
        assert "bullish_order_block" in _ELIGIBLE["trend_continuation"]["bullish"]
        assert "bullish_order_block" not in _ELIGIBLE["liquidity_sweep_reversal"]["bullish"]
        assert "bullish_order_block" not in _ELIGIBLE["manipulation_to_distribution"]["bullish"]

    def test_mechanics_expresses_no_PREFERENCE_for_it(self):
        """Eligible means Luna MAY select it. Preferred would mean mechanics
        recommends it — an opinion about which trade to take."""
        from toolbox.tool_library import _PREFERRED
        assert not [t for pb in _PREFERRED.values() for lst in pb.values()
                    for t in lst if "po3_reversal" in t]

    def test_luna_is_allowed_to_emit_the_token(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
        assert "po3_reversal_order_block" in BRAIN_SYSTEM_PROMPT


class TestItReachesTheCatalog:
    @staticmethod
    def rows(snap=None):
        from broker.luna_candidate_producer import authorized_tool_catalog
        return [r for r in authorized_tool_catalog(snap or snapshot())
                if r.get("tool_family") == "po3_reversal_order_block"]

    def test_the_validated_block_is_published(self):
        r = self.rows()
        assert len(r) == 1 and r[0]["direction"] == "bullish"

    def test_the_row_carries_the_birth_certificate(self):
        r = self.rows()[0]
        for fact in ("liquidity_side_taken", "manipulation_sweep_direction",
                     "creating_run_start", "creating_run_end",
                     "validation_timestamp", "validation_basis"):
            assert r.get(fact) is not None, fact

    def test_the_row_carries_both_extremes_separately(self):
        r = self.rows()[0]
        assert r["run_extreme"] == RUN_EXTREME
        assert r["invalidation_level"] == SWING_LOW
        assert r["run_extreme"] != r["invalidation_level"]

    def test_public_row_carries_the_bound_anchor_sweep_and_revision(self):
        row = self.rows()[0]
        assert row["protected_swing_registered_at"] == REGISTERED_AT
        assert row["protected_swing_occurrence_id"] == (
            "PROTECTED_SWING_REGISTERED:fixture:5m:anchor-life-1")
        assert row["sweep_occurrence_id"] == (
            "LIQUIDITY_SWEEP:fixture:5m:2026-08-19T02:10:00+00:00")
        assert row["history_revision"] == 1

    def test_the_row_carries_the_mean_threshold(self):
        assert self.rows()[0]["mean_threshold"] == MEAN_THRESHOLD

    def test_nothing_is_published_before_the_expansion(self):
        snap = snapshot()
        snap["timeframes"]["5m"]["recent_candles"] = copy.deepcopy(BARS[:7])
        assert self.rows(snap) == []

    def test_no_tool_name_collides_with_the_generic_block(self):
        from broker.luna_candidate_producer import authorized_tool_catalog
        import collections
        names = collections.Counter(r["tool"] for r in authorized_tool_catalog(snapshot()))
        assert not [t for t, n in names.items() if n > 1]

    def test_the_row_advertises_no_verdict(self):
        r = self.rows()[0]
        for verdict in ("confluence_score", "signal", "should_enter",
                        "recommendation", "score"):
            assert verdict not in r


class TestTheThirdFiftyPercentReachesLuna:
    """`retracement_equilibrium` was written, tested, and had ZERO production
    callers -- the third dead-but-correct capability found in one session, and
    the only one authored the same night. A DEAD-CAPABILITY sweep caught it
    before the commit landed. These tests keep it reachable."""

    @staticmethod
    def row():
        from broker.luna_candidate_producer import authorized_tool_catalog
        return [r for r in authorized_tool_catalog(snapshot())
                if r.get("tool_family") == "po3_reversal_order_block"][0]

    def test_the_leg_equilibrium_is_published(self):
        expansion_high = max(c["high"] for c in BARS[8:])
        assert self.row()["retracement_equilibrium"] == \
            round(SWING_LOW + (expansion_high - SWING_LOW) * 0.5, 2)

    def test_the_leg_is_published_with_both_ends_attributed(self):
        r = self.row()
        assert (r["retracement_leg_low"], r["retracement_leg_high"]) == \
            (SWING_LOW, max(c["high"] for c in BARS[8:]))
        assert r["retracement_leg_low_source"] == "protected_manipulation_swing"
        assert r["retracement_leg_high_source"] == "validated_expansion_extreme"
        assert r["retracement_leg_expansion_from"] == _ts("02:20")

    def test_ote_travels_beside_it_undisturbed(self):
        r = self.row()
        assert (r["ote_low_pct"], r["ote_high_pct"]) == (0.62, 0.79)

    def test_three_independent_equilibria_not_one_fused_verdict(self):
        r = self.row()
        assert r["mean_threshold"] != r["retracement_equilibrium"]   # a POCKET
        for fused in ("confluence_score", "confluence", "equilibria_aligned",
                      "signal", "should_enter"):
            assert fused not in r

    def test_no_equality_or_tolerance_gate_exists(self):
        """Operator ruling: never `OB_MT == FVG_MT == LEG_0.50`, and no invented
        proximity constant to manufacture a mechanical confluence."""
        import inspect
        from broker import luna_candidate_producer as P
        src = inspect.getsource(P._leg_equilibrium_facts)
        for banned in ("abs(", "tolerance", "<=", ">=", "=="):
            assert banned not in src, banned

    def test_the_leg_no_longer_depends_on_structure_swings(self):
        """The regression this whole correction exists for: removing
        `last_swing_high` must NOT change the equilibrium, because the leg is
        built from the protected swing and the expansion — not from struct."""
        snap = snapshot()
        before = self.row()["retracement_equilibrium"]
        snap["structure"]["5m"] = {"last_swing_low": SWING_LOW}   # no high
        from broker.luna_candidate_producer import authorized_tool_catalog
        rows = [x for x in authorized_tool_catalog(snap)
                if x.get("tool_family") == "po3_reversal_order_block"]
        assert rows, "the block itself must still be published"
        assert rows[0]["retracement_equilibrium"] == before

    def test_removing_the_swing_low_removes_the_block_entirely(self):
        """The converse: without the anchor there is nothing to reclassify."""
        snap = snapshot()
        snap["protected_swings"]["by_timeframe"]["lows"] = {}
        from broker.luna_candidate_producer import authorized_tool_catalog
        assert not [x for x in authorized_tool_catalog(snap)
                    if x.get("tool_family") == "po3_reversal_order_block"]

    def test_the_function_now_has_a_production_caller(self):
        """The regression this class exists to prevent."""
        import inspect
        from broker import luna_candidate_producer as P
        assert "retracement_equilibrium" in inspect.getsource(P._leg_equilibrium_facts)


class TestProducerOwnedFormationLifetime:
    """A proved setup survives later scans, but never outranks revised history."""

    @staticmethod
    def observe(custody, snap, rows=None, *, revision=1):
        from market_data.reversal_formation import ReversalFormationCustody
        assert isinstance(custody, ReversalFormationCustody)
        return custody.observe(
            snap, contract_id="CON.F.US.MNQ.Z26", history_revision=revision,
            canonical_timeframes={"5m": copy.deepcopy(rows or
                                                        snap["timeframes"]["5m"]["recent_candles"])},
            sweep_events=snap.get("reversal_sweep_history"),
            lifetime_events=snap.get("protected_swing_lifetime_history"))

    def test_established_block_survives_expired_flags_and_healthy_retracement(self):
        from market_data.reversal_formation import (ReversalFormationCustody,
                                                    current_block)
        custody = ReversalFormationCustody()
        formed = snapshot()
        view = self.observe(custody, formed)
        formed["reversal_formation_view"] = view
        first = current_block(formed, "bullish")
        assert first and first["validation_timestamp"] == _ts("02:20")

        later = snapshot()
        later["timeframes"]["5m"]["recent_candles"].append(
            _c(_ts("02:25"), 29470.0, 29472.0, 29452.0, 29458.0))
        later["timestamp"] = _ts("02:25")
        later["liquidity"]["5m"].update(
            sweep_detected=False, sweep_direction=None, reclaim_detected=False)
        later["expansion"]["5m"].update(
            state="retracement", displacement_detected=False)
        later["derived_state"] = {"current": True, "history_revision": 1,
                                  "derived_revision": 1}
        later["reversal_formation_view"] = self.observe(custody, later)
        retained = current_block(later, "bullish")
        assert retained
        assert retained["formation_authority"]["status"] == \
            "CURRENT_PROCESS_REVALIDATED"
        assert retained["formation_authority"]["occurrence_id"] == \
            first["formation_authority"]["occurrence_id"]
        assert retained["validation_timestamp"] == first["validation_timestamp"]

    @pytest.mark.parametrize("mutation", ["changed", "removed"])
    def test_revised_or_removed_proving_close_retires_prior_authority(self, mutation):
        from market_data.reversal_formation import (ReversalFormationCustody,
                                                    current_block)
        custody = ReversalFormationCustody()
        original = snapshot()
        original["reversal_formation_view"] = self.observe(custody, original)
        assert current_block(original, "bullish")

        revised = snapshot()
        bars = revised["timeframes"]["5m"]["recent_candles"]
        if mutation == "changed":
            bars[-1]["close"] = 29430.0
        else:
            bars.pop()
        revised["timestamp"] = bars[-1]["timestamp"]
        revised["derived_state"] = {"current": True, "history_revision": 2,
                                    "derived_revision": 2}
        revised["reversal_formation_view"] = self.observe(
            custody, revised, revision=2)
        assert current_block(revised, "bullish") is None

    def test_identical_repeated_history_keeps_stable_object_identity(self):
        from market_data.reversal_formation import ReversalFormationCustody, current_block
        custody = ReversalFormationCustody()
        snap = snapshot()
        snap["reversal_formation_view"] = self.observe(custody, snap)
        first = current_block(snap, "bullish")
        snap["reversal_formation_view"] = self.observe(custody, snap)
        second = current_block(snap, "bullish")
        assert first and second
        assert first["formation_authority"]["occurrence_id"] == \
            second["formation_authority"]["occurrence_id"]

    def test_later_exact_anchor_invalidation_retires_retained_object(self):
        from market_data.reversal_formation import ReversalFormationCustody, current_block
        custody = ReversalFormationCustody()
        original = snapshot()
        original["reversal_formation_view"] = self.observe(custody, original)
        assert current_block(original, "bullish")

        later = snapshot()
        later["timestamp"] = _ts("02:25")
        later["timeframes"]["5m"]["recent_candles"].append(
            _c(_ts("02:25"), 29470.0, 29472.0, 29452.0, 29458.0))
        # Keep a stale registry row to prove that canonical retirement of this
        # exact lifetime independently invalidates cached formation authority.
        later["protected_swing_lifetime_history"].append({
            "occurrence_id": "PROTECTED_SWING_VIOLATED:fixture:5m:anchor-life-1",
            "event_type": "PROTECTED_SWING_VIOLATED",
            "contract": "CON.F.US.MNQ.Z26", "source_tf": "5m", "side": "low",
            "level": SWING_LOW, "swing_id": "5m:swing_low:29429.75",
            "registered_at": REGISTERED_AT, "source_bar_time": _ts("02:25"),
            "event_time": _ts("02:25"),
        })
        later["derived_state"] = {"current": True, "history_revision": 1,
                                  "derived_revision": 1}
        later["reversal_formation_view"] = self.observe(custody, later)
        assert current_block(later, "bullish") is None

    def test_json_restoration_cannot_restore_live_formation_authority(self):
        import json
        from market_data.reversal_formation import ReversalFormationCustody, current_block
        custody = ReversalFormationCustody()
        formed = snapshot()
        live_view = self.observe(custody, formed)
        formed["reversal_formation_view"] = live_view
        assert current_block(formed, "bullish")
        restored = snapshot()
        restored["reversal_formation_view"] = json.loads(json.dumps(live_view))
        assert current_block(restored, "bullish") is None

    def test_unavailable_or_retracted_public_event_lineage_cannot_use_cache(self):
        from market_data.reversal_formation import (ReversalFormationCustody,
                                                    current_block)
        custody = ReversalFormationCustody()
        original = snapshot()
        original["reversal_formation_view"] = self.observe(custody, original)
        assert current_block(original, "bullish")

        later = snapshot()
        later["timeframes"]["5m"]["recent_candles"].append(
            _c(_ts("02:25"), 29470.0, 29472.0, 29452.0, 29458.0))
        later["timestamp"] = _ts("02:25")
        later["derived_state"] = {"current": True, "history_revision": 1,
                                  "derived_revision": 1}
        unavailable = custody.observe(
            later, contract_id="CON.F.US.MNQ.Z26", history_revision=1,
            canonical_timeframes={"5m": copy.deepcopy(
                later["timeframes"]["5m"]["recent_candles"])},
            sweep_events=None, lifetime_events=None)
        later["reversal_formation_view"] = unavailable
        assert current_block(later, "bullish") is None

        # A healthy but authoritative current ledger view which has omitted
        # the proving sweep also retires prior process custody.
        restored = snapshot()
        restored["timeframes"]["5m"]["recent_candles"].append(
            _c(_ts("02:25"), 29470.0, 29472.0, 29452.0, 29458.0))
        restored["timestamp"] = _ts("02:25")
        restored["derived_state"] = {"current": True, "history_revision": 1,
                                     "derived_revision": 1}
        restored["reversal_formation_view"] = custody.observe(
            restored, contract_id="CON.F.US.MNQ.Z26", history_revision=1,
            canonical_timeframes={"5m": copy.deepcopy(
                restored["timeframes"]["5m"]["recent_candles"])},
            sweep_events=[], lifetime_events=restored[
                "protected_swing_lifetime_history"])
        assert current_block(restored, "bullish") is None

    def test_natural_leading_rollout_does_not_call_old_witness_a_deletion(self):
        from market_data.reversal_formation import ReversalFormationCustody, current_block
        custody = ReversalFormationCustody()
        formed = snapshot()
        formed["reversal_formation_view"] = self.observe(custody, formed)
        assert current_block(formed, "bullish")
        rolled = snapshot()
        rolled["timeframes"]["5m"]["recent_candles"] = \
            copy.deepcopy(BARS[6:]) + [
                _c(_ts("02:25"), 29470.0, 29472.0, 29452.0, 29458.0)]
        rolled["timestamp"] = _ts("02:25")
        rolled["derived_state"] = {"current": True, "history_revision": 1,
                                   "derived_revision": 1}
        rolled["reversal_formation_view"] = self.observe(custody, rolled)
        assert current_block(rolled, "bullish")

    def test_explicit_cross_timeframe_anchor_life_is_reconstructed_and_retained(self):
        """A cross-TF anchor is usable only when the sweep names its exact life."""
        from market_data.reversal_formation import (ReversalFormationCustody,
                                                    current_block)
        from toolbox.price_levels import po3_reversal_order_block

        snap = snapshot()
        sweep = snap["reversal_sweep_history"][0]
        registration = snap["protected_swing_lifetime_history"][0]
        registration["occurrence_id"] = (
            "PROTECTED_SWING_REGISTERED:fixture:15m:anchor-life-1")
        registration["source_tf"] = "15m"
        registration["source_bar_time"] = _ts("02:05")
        # The producer observed/registered this anchor after the source candle;
        # chronology comes from the source bar, while identity keeps its own
        # later registered_at value.
        registration["event_time"] = REGISTERED_AT
        registration["registered_at"] = REGISTERED_AT
        sweep["swept_level_id"] = registration["occurrence_id"]
        protected = snap["protected_swings"]["by_timeframe"]["lows"].pop("5m")
        protected["timeframe"] = "15m"
        snap["protected_swings"]["by_timeframe"]["lows"]["15m"] = protected

        detected = po3_reversal_order_block(snap, "bullish")
        assert detected["available"] is True, detected
        assert detected["protected_swing_tf"] == "15m"

        custody = ReversalFormationCustody()
        snap["reversal_formation_view"] = self.observe(custody, snap)
        retained = current_block(snap, "bullish")
        assert retained is not None
        assert retained["protected_swing_tf"] == "15m"
        assert retained["formation_authority"]["anchor_identity"]["timeframe"] == "15m"

    def test_production_scan_attaches_only_ledger_backed_formation(self, tmp_path):
        from live_scan.production_scan_cycle import ProductionScanCycle
        from market_data.occurrence_ledger import HEALTHY, OccurrenceLedger
        from market_data.reversal_formation import is_producer_owned_view

        snap = snapshot()
        cycle = ProductionScanCycle(symbol="MNQ")
        cycle.contract_id = "CON.F.US.MNQ.Z26"
        cycle.occurrence_ledger = OccurrenceLedger(
            cycle.contract_id, directory=str(tmp_path))
        cycle.occurrence_ledger_status = HEALTHY
        for event in (snap["reversal_sweep_history"]
                      + snap["protected_swing_lifetime_history"]):
            assert cycle.occurrence_ledger.record(event)["outcome"] == "recorded"

        revision = cycle._history.revision
        snap["derived_state"] = {
            "current": True, "history_revision": revision,
            "derived_revision": revision,
        }
        canonical = {"5m": copy.deepcopy(BARS)}
        cycle._attach_reversal_formation(snap, canonical)
        assert is_producer_owned_view(snap["reversal_formation_view"])
        attached = block(snap=snap)
        assert attached["available"] is True, attached
        assert attached["formation_authority"]["status"] == \
            "CURRENT_PROCESS_REVALIDATED"


class TestReaffirmedProtectedAnchorChronology:
    """A later sweep may use the same still-live anchor without minting a new
    protected-swing life. These synthetic bars exercise the real tracker,
    occurrence extractor, reversal detector and public catalog."""

    @staticmethod
    def later_sweep_on_existing_life(direction="bullish"):
        from narrative_authority.protected_swings import ProtectedSwingTracker
        from market_state.active_path import extract_occurrences
        from market_data.sweep_occurrence import liquidity_sweep_occurrence
        from market_data.swing_evidence import build_swing_evidence
        from structure.liquidity_engine import PRIOR_ADJACENT, analyze_liquidity

        bullish = direction == "bullish"
        side = "low" if bullish else "high"
        side_bucket = "lows" if bullish else "highs"
        anchor_level = SWING_LOW if bullish else round(60000.0 - SWING_LOW, 4)
        sweep_direction = "below_low" if bullish else "above_high"
        liquidity_side = "sell_side" if bullish else "buy_side"
        bars = (BARS if bullish else
                bearish_mirror_snapshot()["timeframes"]["5m"]["recent_candles"])
        base = snapshot if bullish else bearish_mirror_snapshot

        # The later sweep fact comes from the production liquidity detector,
        # with canonical 5m adjacency/extrema evidence. The earlier prefix makes
        # the defended protected level a confirmed pivot before the new sweep.
        mirror = (lambda value: round(60000.0 - value, 4)) if not bullish else None

        def prebar(hhmm, values):
            o, h, low, close = values
            if mirror:
                o, h, low, close = (mirror(o), mirror(low), mirror(h), mirror(close))
            return _c(_ts(hhmm), o, h, low, close)

        prefix = [
            prebar("00:55", (29480.00, 29490.00, 29470.00, 29475.00)),
            prebar("01:00", (29475.00, 29488.00, 29465.00, 29470.00)),
            prebar("01:05", (29470.00, 29482.00, 29455.00, 29460.00)),
            prebar("01:10", (29455.00, 29465.00, SWING_LOW, 29440.00)),
            prebar("01:15", (29440.00, 29455.00, 29435.00, 29445.00)),
            prebar("01:20", (29445.00, 29460.00, 29438.00, 29450.00)),
            prebar("01:25", (29450.00, 29465.00, 29440.00, 29455.00)),
        ]
        detector_bars = copy.deepcopy(prefix + bars[:8])
        for row in detector_bars:
            start = datetime.fromisoformat(row["timestamp"])
            row["source_member_times"] = [
                (start + timedelta(minutes=offset)).isoformat()
                for offset in range(5)]
            row["members"] = row["expected_members"] = 5
            row["complete"] = True
        swing_evidence = build_swing_evidence(
            detector_bars, detector_bars, 5)
        detected = analyze_liquidity(
            detector_bars,
            {"authority": PRIOR_ADJACENT,
             "close": detector_bars[-2]["close"]},
            swing_evidence=swing_evidence)
        assert detected["sweep_detected"] is True, detected
        assert detected["reclaim_detected"] is True, detected
        assert detected["sweep_fact"]["event_time"] == SWEEP_TIME
        assert detected["sweep_fact"]["swept_level"] == anchor_level

        tracker = ProtectedSwingTracker()
        birth = base()
        birth["timestamp"] = _ts("01:10")
        birth["timeframes"]["5m"]["recent_candles"] = [
            (_c(_ts("01:10"), 29438.00, 29445.00, 29428.75, 29440.00)
             if bullish else
             _c(_ts("01:10"), 30562.00, 30571.25, 30555.00, 30560.00))]
        birth["structure"]["5m"] = {
            f"last_swing_{side}": anchor_level}
        birth["liquidity"]["5m"].update(
            sweep_detected=True, reclaim_detected=True,
            sweep_direction=sweep_direction)
        birth["settled_source"] = {"5m": {
            "source_bar_time": _ts("01:10"),
            "settled_edge_time": _ts("01:10")}}
        birth["protected_swings"] = tracker.update(birth)
        original = birth["protected_swings"]["by_timeframe"][side_bucket]["5m"]
        lifetime = [r for r in extract_occurrences(
            birth, {}, birth["contract_id"])
                    if r.get("event_type") == "PROTECTED_SWING_REGISTERED"]

        # Replay subsequent settled bars through the real stateful tracker.
        later_sweeps = []
        for bar in bars[:8]:
            step = base()
            step["timestamp"] = bar["timestamp"]
            step["timeframes"]["5m"]["recent_candles"] = [copy.deepcopy(bar)]
            # The later liquidity detector can select the still-live anchor
            # while structure has already confirmed a newer, nearby pivot.
            # The sweep fact and the structural pivot answer different
            # questions; the protected lifetime must follow the exact level
            # the settled sweep reclaimed.
            structural_level = anchor_level
            if bar["timestamp"] == SWEEP_TIME:
                structural_level = (anchor_level - 1.0 if bullish
                                    else anchor_level + 1.0)
            step["structure"]["5m"] = {
                f"last_swing_{side}": structural_level}
            step["settled_source"] = {"5m": {
                "source_bar_time": bar["timestamp"],
                "settled_edge_time": bar["timestamp"]}}
            if bar["timestamp"] == SWEEP_TIME:
                step["liquidity"] = {"5m": detected}
            prior = copy.deepcopy(tracker.state()["by_timeframe"])
            step["protected_swings"] = tracker.update(step)
            events = extract_occurrences(step, prior, step["contract_id"])
            lifetime.extend(r for r in events if r.get("event_type") ==
                            "PROTECTED_SWING_REGISTERED")
            if bar["timestamp"] == SWEEP_TIME:
                fact = detected["sweep_fact"]
                row = liquidity_sweep_occurrence(
                    fact, source_tf="5m", contract=step["contract_id"],
                    snapshot=step)
                assert row and row.get("protected_swing_lifetime")
                later_sweeps.append(row)

        current = base()
        current["protected_swings"] = tracker.state()
        current["protected_swing_lifetime_history"] = lifetime
        current["reversal_sweep_history"] = later_sweeps
        assert current["protected_swings"]["by_timeframe"][side_bucket]["5m"][
            "registered_at"] == original["registered_at"]
        assert not [r for r in lifetime if r.get("event_time") == SWEEP_TIME]
        return current

    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_later_sweep_of_same_intact_life_establishes_the_object(self, direction):
        current = self.later_sweep_on_existing_life(direction)
        result = block(direction=direction, snap=current)
        assert result["available"] is True, result

    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_later_sweep_of_same_life_reaches_the_public_catalog(self, direction):
        rows = [r for r in self._catalog(
            self.later_sweep_on_existing_life(direction))
                if r.get("tool_family") == "po3_reversal_order_block"]
        assert len(rows) == 1 and rows[0]["direction"] == direction

    def test_mismatched_lifetime_attestation_still_refuses(self):
        current = self.later_sweep_on_existing_life()
        current["reversal_sweep_history"][0]["protected_swing_lifetime"][
            "swing_id"] = "same-price-different-life"
        result = block(snap=current)
        assert result["available"] is False
        assert result["reason"] == "SWEEP_NOT_ASSOCIATED_WITH_CURRENT_PROTECTED_ANCHOR_LIFE"

    def test_later_registered_same_price_life_cannot_borrow_the_old_sweep(self):
        current = self.later_sweep_on_existing_life()
        new_registered_at = _ts("02:17")
        registration = current["protected_swing_lifetime_history"][0]
        registration.update(source_bar_time=_ts("02:15"),
                            registered_at=new_registered_at,
                            event_time=new_registered_at)
        current["protected_swings"]["by_timeframe"]["lows"]["5m"][
            "registered_at"] = new_registered_at
        result = block(snap=current)
        assert result["available"] is False
        assert result["reason"] == "SWEEP_NOT_ASSOCIATED_WITH_CURRENT_PROTECTED_ANCHOR_LIFE"

    def test_later_sweep_without_lifetime_attestation_is_unknown(self):
        current = self.later_sweep_on_existing_life()
        current["reversal_sweep_history"][0].pop("protected_swing_lifetime")
        result = block(snap=current)
        assert result["available"] is False
        assert result["reason"] == "SWEEP_NOT_ASSOCIATED_WITH_CURRENT_PROTECTED_ANCHOR_LIFE"

    @staticmethod
    def _catalog(snap):
        from broker.luna_candidate_producer import authorized_tool_catalog
        return authorized_tool_catalog(snap)
