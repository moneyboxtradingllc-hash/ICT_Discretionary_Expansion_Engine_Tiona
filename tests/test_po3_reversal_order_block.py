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


#: The manipulation run, its terminal low, then the validating expansion.
BARS = [
    # Accumulation is BULLISH here on purpose: a bearish bar would be absorbed
    # into the unbroken opposing run and inflate the envelope. The run is
    # "contiguous opposing delivery", so where it STARTS is a market fact.
    _c("01:30", 29480.00, 29492.00, 29478.00, 29486.00),
    _c("01:35", 29470.00, 29483.00, 29468.00, 29474.00),
    _c("01:45", 29472.00, 29474.00, 29462.00, 29464.00),   # run starts
    _c("01:50", 29464.00, 29466.00, 29452.00, 29454.00),
    _c("01:55", 29454.00, 29457.00, 29444.00, 29446.00),
    _c("02:00", 29446.00, 29448.00, 29434.00, 29436.00),
    _c("02:05", 29436.00, 29438.00, SWING_LOW, 29432.00),  # terminal, sweeps low
    _c("02:10", 29432.00, 29440.00, 29431.00, 29439.00),   # first bullish
    _c("02:15", 29439.00, 29478.00, 29438.00, 29476.00),   # EXPANSION: closes
    _c("02:20", 29476.00, 29488.00, 29470.00, 29484.00),   #   through the run
]

#: `_ob_block_run` takes the contiguous opposing run BEFORE the swing candle --
#: the 02:05 bar that printed the low is the anchor and is excluded. That is
#: the existing tested convention and is preserved, not bent to the fixture.
RUN_BODY_LOW = 29436.00      # min(open, close) across 01:45-02:00
RUN_BODY_HIGH = 29472.00     # max(open, close) across 01:45-02:00
RUN_EXTREME = 29434.00       # lowest low IN THE RUN, not the swing low
MEAN_THRESHOLD = round((RUN_BODY_LOW + RUN_BODY_HIGH) / 2, 3)


def snapshot(**over):
    snap = {
        "symbol": "MNQ",
        "timeframes": {"5m": {"recent_candles": copy.deepcopy(BARS)}},
        "structure": {"5m": {"last_swing_low": SWING_LOW,
                             "last_swing_high": SWING_HIGH}},
        "liquidity": {"5m": {"sweep_detected": True,
                             "sweep_direction": "below_low",
                             "reclaim_detected": True}},
        "expansion": {"5m": {"state": "healthy_expansion",
                             "displacement_detected": True}},
        "protected_swings": {"by_timeframe": {"lows": {
            "5m": {"level": SWING_LOW, "role": "active_leg",
                   "swing_id": "5m:swing_low:29429.75",
                   "basis": "sell_side_raid_rejected"}}}},
    }
    snap.update(over)
    return snap


def block(direction="bullish", snap=None):
    return po3_reversal_order_block(snap if snap is not None else snapshot(),
                                    direction)


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
        # truncate the tape to the moment the run has just ended
        snap["timeframes"]["5m"]["recent_candles"] = copy.deepcopy(BARS[:7])
        return snap

    def test_no_object_exists_before_the_violation(self):
        b = block(snap=self._before_expansion())
        assert b["available"] is False

    def test_the_refusal_names_the_missing_link(self):
        assert block(snap=self._before_expansion())["reason"] == NOT_YET_VALIDATED

    def test_bearish_candles_near_a_low_are_not_enough(self):
        """Not 'bearish', not 'near a low', not 'sell-side taken'."""
        snap = self._before_expansion()
        assert snap["liquidity"]["5m"]["sweep_detected"] is True   # sweep DID happen
        assert block(snap=snap)["available"] is False              # still no object

    def test_a_wick_through_the_run_is_not_a_violation(self):
        """A probe is not a change in the state of delivery."""
        snap = snapshot()
        bars = copy.deepcopy(BARS[:8])
        bars.append(_c("02:15", 29439.00, 29480.00, 29438.00, 29460.00))  # wick only
        snap["timeframes"]["5m"]["recent_candles"] = bars
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
        snap["liquidity"]["5m"]["sweep_detected"] = False
        assert block(snap=snap)["reason"] == NO_MANIPULATION

    def test_the_wrong_side_sweep_does_not_qualify_a_bullish_block(self):
        """A buy-side raid does not create a BULLISH reversal block."""
        snap = snapshot()
        snap["liquidity"]["5m"]["sweep_direction"] = "above_high"
        assert block(snap=snap)["reason"] == NO_MANIPULATION

    def test_a_bearish_block_needs_the_buy_side_taken(self):
        snap = snapshot()
        snap["liquidity"]["5m"]["sweep_direction"] = "above_high"
        assert block("bearish", snap=snap)["reason"] != NO_MANIPULATION

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
        assert b["run_extreme"] == RUN_EXTREME        # geometry unchanged
        assert b["invalidation_level"] == 29425.00    # authority differs
        assert b["run_extreme"] != b["invalidation_level"]

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
        assert leg["high"] == max(c["high"] for c in BARS[8:])

    def test_the_leg_cannot_borrow_a_high_the_reversal_never_made(self):
        """Measured from the validating candle forward, never before it."""
        leg = block()["retracement_leg"]
        assert leg["high"] <= max(c["high"] for c in BARS[8:])
        assert leg["expansion_from"] == "02:15"

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
        assert r["retracement_leg_expansion_from"] == "02:15"

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
        snap["structure"]["5m"] = {"last_swing_high": SWING_HIGH}
        from broker.luna_candidate_producer import authorized_tool_catalog
        assert not [x for x in authorized_tool_catalog(snap)
                    if x.get("tool_family") == "po3_reversal_order_block"]

    def test_the_function_now_has_a_production_caller(self):
        """The regression this class exists to prevent."""
        import inspect
        from broker import luna_candidate_producer as P
        assert "retracement_equilibrium" in inspect.getsource(P._leg_equilibrium_facts)
