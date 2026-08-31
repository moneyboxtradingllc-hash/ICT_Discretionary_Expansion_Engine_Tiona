"""PRODUCTION-STOP-CEILING-40 — the final MNQ stop and sizing doctrine.

35 preferred / 40 absolute / $250 all-in / 15 MNQ max. Neither ceiling is a stop
distance: the stop is always the exact structural invalidation, and the ceilings
decide only whether a setup is ELIGIBLE.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_client import TopstepXContract                # noqa: E402
from broker.topstepx_combine_risk import (                         # noqa: E402
    ABSOLUTE_MAX_STOP_POINTS, EXTENDED_VOLATILITY_STOP_RANGE,
    FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT, FIXED_ROUND_TRIP_FEES_PER_CONTRACT,
    MEASURED_FIXED_ROUND_TRIP_TOTAL, NORMAL_STOP_RANGE, PREFERRED_MAX_STOP_POINTS,
    PRODUCTION_MAX_CONTRACTS, PRODUCTION_MAX_RISK_USD, STOP_DISTANCE_REJECTED,
    RiskRejection, build_production_bracket, classify_stop_distance,
    friction_per_contract, size_for_risk,
)

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)

VOL_OK = {"volatility_state": "expansion", "expansion_state": "expanding",
          "structural_level_identity": "protected_swing_low@19960"}


def long_bracket(stop_pts, target_pts=None, evidence=VOL_OK, **kw):
    entry = 20000.0
    target_pts = stop_pts * 2 if target_pts is None else target_pts
    return build_production_bracket(
        direction="bullish", entry_price=entry, invalidation_level=entry - stop_pts,
        target_price=entry + target_pts, contract=MNQ, evidence=evidence, **kw)


class TestExactStopPreservation:

    @pytest.mark.parametrize("pts", [10.0, 11.75, 24.5, 34.75])
    def test_the_structural_stop_is_used_exactly(self, pts):
        g = long_bracket(pts)["geometry"]
        assert g.stop_price == pytest.approx(20000.0 - pts)

    def test_a_twelve_point_stop_is_never_widened_to_the_allowance(self):
        g = long_bracket(12.0)["geometry"]
        assert g.stop_points == pytest.approx(12.0, abs=0.25)

    def test_a_narrow_stop_does_not_inherit_the_ceiling(self):
        assert long_bracket(10.0)["geometry"].stop_points < 35.0


class TestLanes:

    @pytest.mark.parametrize("pts,lane", [
        (10.0, NORMAL_STOP_RANGE), (35.0, NORMAL_STOP_RANGE),
        (35.25, EXTENDED_VOLATILITY_STOP_RANGE), (39.75, EXTENDED_VOLATILITY_STOP_RANGE),
        # RISK-DOCTRINE-MIGRATION 2026-08-20: the extended lane now runs to 50.0.
        (40.0, EXTENDED_VOLATILITY_STOP_RANGE), (40.75, EXTENDED_VOLATILITY_STOP_RANGE),
        (47.0, EXTENDED_VOLATILITY_STOP_RANGE), (49.75, EXTENDED_VOLATILITY_STOP_RANGE),
        (50.0, EXTENDED_VOLATILITY_STOP_RANGE),
        (50.25, STOP_DISTANCE_REJECTED), (60.0, STOP_DISTANCE_REJECTED),
    ])
    def test_classification(self, pts, lane):
        assert classify_stop_distance(pts) == lane

    def test_thirty_five_is_normal_range(self):
        assert long_bracket(35.0)["stop_range"] == NORMAL_STOP_RANGE

    def test_thirty_five_and_a_quarter_is_extended(self):
        assert long_bracket(35.25)["stop_range"] == EXTENDED_VOLATILITY_STOP_RANGE

    def test_thirty_nine_seventy_five_qualifies_with_evidence(self):
        out = long_bracket(39.75)
        assert out["stop_range"] == EXTENDED_VOLATILITY_STOP_RANGE
        assert out["sizing"]["contracts"] >= 1

    def test_forty_point_seven_five_qualifies(self):
        """2026-08-20 11:03: this exact distance died on the old 40.0 ceiling,
        three ticks short, while the structure genuinely required it."""
        out = long_bracket(40.75)
        assert out["stop_range"] == EXTENDED_VOLATILITY_STOP_RANGE
        assert out["sizing"]["contracts"] >= 1

    def test_fifty_qualifies_at_the_boundary(self):
        assert long_bracket(50.0)["sizing"]["contracts"] >= 1

    @pytest.mark.parametrize("pts", [50.25, 60.0])
    def test_beyond_fifty_is_rejected(self, pts):
        with pytest.raises(RiskRejection) as exc:
            long_bracket(pts)
        assert "ceiling" in str(exc.value) or "cap" in str(exc.value)

    def test_a_sixty_point_invalidation_is_never_squeezed(self):
        with pytest.raises(RiskRejection) as exc:
            long_bracket(60.0)
        assert "rejected, not resized" in str(exc.value) or "not adjustable" in str(exc.value)

    def test_extended_width_requires_structure_not_just_volatility(self):
        with pytest.raises(RiskRejection) as exc:
            long_bracket(38.0, evidence={"volatility_state": "expansion",
                                         "expansion_state": "expanding"})
        assert exc.value.reason == "extended_volatility_unsupported"

    def test_a_quiet_market_refuses_the_extended_lane(self):
        with pytest.raises(RiskRejection):
            long_bracket(38.0, evidence={"volatility_state": "compression",
                                         "expansion_state": "contracting",
                                         "structural_level_identity": "x"})


class TestCostModel:
    """Measured fixed costs and an explicitly unmeasured slippage reserve."""

    def test_fixed_costs_are_the_measured_live_values(self):
        assert FIXED_ROUND_TRIP_FEES_PER_CONTRACT == 0.72
        assert FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT == 0.50
        assert MEASURED_FIXED_ROUND_TRIP_TOTAL == 1.22

    def test_friction_reports_fixed_and_reserve_separately(self):
        """Reserve raised to 2 ticks/side (provisional, operator 2026-08-05)."""
        f = friction_per_contract(MNQ)
        assert f["fixed_round_trip"] == pytest.approx(1.22)
        assert f["slippage_reserve"] == pytest.approx(2.00)
        assert f["total"] == pytest.approx(3.22)

    def test_slippage_is_labelled_as_not_measured(self):
        f = friction_per_contract(MNQ)
        assert f["slippage_is_measured"] is False
        assert "NOT measured" in f["slippage_source"]
        assert "measured:" in f["fixed_source"]

    def test_the_slippage_reserve_is_configurable(self):
        wide = friction_per_contract(MNQ, slippage_reserve_ticks_per_side=3.0)
        assert wide["slippage_reserve"] == pytest.approx(3.0)
        assert wide["total"] > friction_per_contract(MNQ)["total"]

    def test_fixed_costs_are_configurable(self):
        f = friction_per_contract(MNQ, fixed_fees=1.0, fixed_commissions=0.6)
        assert f["fixed_round_trip"] == pytest.approx(1.6)


class TestAdaptiveSizing:

    def test_quantity_falls_as_the_stop_widens(self):
        q = [size_for_risk(p, MNQ)["contracts"] for p in (10, 20, 35, 40)]
        assert q == sorted(q, reverse=True) and q[0] > q[-1]

    def test_friction_reduces_the_frictionless_quantity(self):
        """10-pt stop: 12 contracts ignoring friction, fewer once it is counted."""
        frictionless = int(PRODUCTION_MAX_RISK_USD // (10.0 * 2.0))
        actual = size_for_risk(10.0, MNQ)["contracts"]
        assert actual < frictionless

    @pytest.mark.parametrize("pts", [5, 10, 17.25, 24.5, 35, 39.75, 40])
    def test_all_in_risk_never_exceeds_the_cap(self, pts):
        assert size_for_risk(pts, MNQ)["all_in_planned_risk"] <= PRODUCTION_MAX_RISK_USD

    def test_the_forty_point_quantity_is_computed_not_assumed(self):
        """Whatever fits, fits — the count is arithmetic, not a constant."""
        s = size_for_risk(40.0, MNQ)
        per = 40.0 * 2.0 + friction_per_contract(MNQ)["total"]
        assert s["all_in_risk_per_contract"] == pytest.approx(per)
        assert s["contracts"] == int(PRODUCTION_MAX_RISK_USD // per)
        assert (s["contracts"] + 1) * per > PRODUCTION_MAX_RISK_USD   # one more would breach

    def test_a_larger_slippage_reserve_can_size_down(self):
        base = size_for_risk(40.0, MNQ)["contracts"]
        conservative = size_for_risk(40.0, MNQ, slippage_reserve_ticks_per_side=8.0)["contracts"]
        assert conservative <= base

    def test_quantity_never_exceeds_fifteen(self):
        assert size_for_risk(0.25, MNQ)["contracts"] <= 15
        assert PRODUCTION_MAX_CONTRACTS == 15

    def test_no_trade_when_one_contract_breaches_the_cap(self):
        """Sizing yields zero contracts, and the bracket path refuses.

        Either guard may fire first — the gross per-contract check inside
        build_bracket, or the all-in sizing check. Both reject with
        `risk_above_cap`; neither trims the stop or drops friction.
        """
        s = size_for_risk(40.0, MNQ, max_risk_usd=50.0)
        assert s["contracts"] == 0 and s["fits"] is False
        with pytest.raises(RiskRejection) as exc:
            long_bracket(40.0, max_risk_usd=50.0)
        assert exc.value.reason == "risk_above_cap"
        assert "not adjustable" in str(exc.value) or "not removed" in str(exc.value)

    def test_the_sizing_guard_names_friction_when_it_is_the_one_that_fires(self):
        """A cap between gross and all-in isolates the friction guard."""
        per_gross = 40.0 * 2.0                       # $80.00
        per_all_in = per_gross + friction_per_contract(MNQ)["total"]   # $82.22
        cap = (per_gross + per_all_in) / 2           # between the two
        with pytest.raises(RiskRejection) as exc:
            long_bracket(40.0, max_risk_usd=cap)
        assert exc.value.reason == "risk_above_cap"
        assert "not removed to make it fit" in str(exc.value)


class TestTargetIntegrity:

    def test_a_wide_stop_does_not_substitute_a_farther_target(self):
        assert long_bracket(38.0, target_pts=76.0)["geometry"].target_price == 20076.0

    def test_reward_collapse_rejects_instead_of_moving_the_target(self):
        # RR-FLOOR-1.0 (2026-08-08): 38/38 is exactly 1.0R and now qualifies.
        # A sub-floor target still refuses rather than reaching farther.
        with pytest.raises(RiskRejection) as exc:
            long_bracket(38.0, target_pts=30.0)     # 0.79R
        assert exc.value.reason == "reward_below_gate"


class TestVenueRepresentation:

    def test_long_signs(self):
        p = long_bracket(20.0)["geometry"].as_order_payload(1, MNQ.id)
        assert p["stopLossBracket"]["ticks"] < 0 < p["takeProfitBracket"]["ticks"]

    def test_short_signs(self):
        out = build_production_bracket(
            direction="bearish", entry_price=20000.0, invalidation_level=20020.0,
            target_price=19960.0, contract=MNQ, evidence=VOL_OK)
        p = out["geometry"].as_order_payload(1, MNQ.id)
        assert p["takeProfitBracket"]["ticks"] < 0 < p["stopLossBracket"]["ticks"]

    def test_prices_survive_serialization_unchanged(self):
        g = long_bracket(24.5)["geometry"]
        assert g.stop_price == 19975.5 and g.target_price == 20049.0
        assert abs(g.signed_stop_ticks()) == g.stop_ticks


class TestSmokeIsolation:

    def test_the_production_path_cannot_reference_smoke_constants(self):
        import inspect
        from broker import topstepx_combine_risk as R
        src = inspect.getsource(R.build_production_bracket)
        for smoke in ("SMOKE_MAX_STOP_POINTS", "SMOKE_MAX_CONTRACTS", "SMOKE_MAX_RISK_USD"):
            assert smoke not in src

    def test_a_thirty_point_stop_passes_production_but_not_the_smoke_ceiling(self):
        """Direct proof the 10-point smoke ceiling is not in force."""
        assert long_bracket(30.0)["geometry"].stop_points == pytest.approx(30.0, abs=0.25)

    def test_production_sizing_is_not_capped_at_one(self):
        assert size_for_risk(10.0, MNQ)["contracts"] > 1

    def test_the_doctrine_constants_are_the_operator_values(self):
        assert PREFERRED_MAX_STOP_POINTS == 35.0
        assert ABSOLUTE_MAX_STOP_POINTS == 50.0
        assert PRODUCTION_MAX_RISK_USD == 350.00
        assert PRODUCTION_MAX_CONTRACTS == 15


class TestStartupTelemetry:
    """The resolved doctrine must be printable and self-refusing."""

    def _mod(self):
        from broker import topstepx_production_doctrine as D
        return D

    def test_telemetry_prints_thirty_five_preferred_and_fifty_absolute(self):
        text = self._mod().render()
        assert "PREFERRED MAX STRUCTURAL STOP: 35.00 points" in text
        assert "ABSOLUTE MAX STRUCTURAL STOP : 50.00 points" in text
        assert ">35.00 through 50.00 points" in text

    def test_telemetry_names_the_authorities(self):
        text = self._mod().render()
        assert "exact structural invalidation" in text
        assert "Luna-selected liquidity objective" in text
        assert "bot-authored BracketGeometry" in text
        assert "TOPSTEP POSITION BRACKETS    : disabled" in text
        assert "SMOKE CONSTANTS              : not active" in text

    def test_telemetry_exposes_cost_provenance(self):
        text = self._mod().render()
        assert "$1.22" in text and "measured:" in text
        assert "measured                   : False" in text
        assert "provisional conservative reserve" in text
        assert "$2.00 per MNQ round trip" in text

    def test_telemetry_reports_the_slippage_sample(self):
        text = self._mod().render()
        assert "SLIPPAGE SAMPLE" in text
        assert "0/20 reliable observations" in text and "0/10 round trips" in text

    def test_a_clean_configuration_starts(self):
        assert self._mod().assert_no_conflict()["absolute_max_stop_points"] == 50.0

    @pytest.mark.parametrize("override,fragment", [
        ({"absolute_max_stop_points": 10.0}, "SMOKE"),
        ({"absolute_max_stop_points": 30.0, "preferred_max_stop_points": 35.0}, "below the preferred"),
        ({"absolute_max_stop_points": 60.0}, "exceeds the doctrinal maximum"),
        ({"preferred_max_stop_points": 20.0}, "doctrine is 35"),
        ({"production_max_risk_usd": 500.0}, "exceeds the $350"),
        ({"max_contracts": 40}, "exceeds 15 MNQ"),
        ({"topstep_position_brackets": "enabled"}, "not a production protection authority"),
        ({"smoke_constants_active": True}, "smoke constants are active"),
    ])
    def test_conflicting_configuration_refuses_startup(self, override, fragment):
        D = self._mod()
        d = {**D.resolve(), **override}
        with pytest.raises(D.DoctrineConflict) as exc:
            D.assert_no_conflict(d)
        assert fragment in str(exc.value)
