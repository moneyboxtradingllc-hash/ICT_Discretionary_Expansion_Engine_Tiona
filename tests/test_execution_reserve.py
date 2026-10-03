"""Adversarial strategy-risk vs realized execution-slippage economics."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker.topstepx_combine_risk import (  # noqa: E402
    PRODUCTION_MAX_RISK_USD, SLIPPAGE_RESERVE_USD, RiskRejection,
    build_bracket, build_production_bracket, size_for_risk,
)
from test_exec_price_anchor import MNQ, _fill, _runner  # noqa: E402


def _risk349(direction="bullish"):
    entry = 30000.0
    if direction == "bullish":
        stop, target = entry - 87.25, entry + 500.0
    else:
        stop, target = entry + 87.25, entry - 500.0
    runner, _ = _runner(direction, entry, stop, target, entry, size=2,
                        max_stop_points=100.0, max_risk_usd=350.0)
    assert runner.geometry.risk_usd == 349.0
    return runner


class TestStrategyRiskSizing:
    def test_351_strategy_risk_is_refused_not_rescued_by_reserve(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(
                direction="bullish", entry_price=30000.0,
                invalidation_level=29970.75, target_price=30100.0,
                contract=MNQ, size=6, max_risk_usd=350.0,
                max_stop_points=50.0, min_reward_to_risk=1.0,
                max_contracts=15)
        assert exc.value.reason == "risk_above_cap"

    def test_11th_contract_is_not_authorized_by_350_plus_30(self):
        sized = size_for_risk(17.25, MNQ, max_risk_usd=350.0)
        assert 11 * 17.25 * 2.0 == pytest.approx(379.5)
        assert sized["contracts"] == 10
        assert sized["authorized_strategy_risk_usd"] == pytest.approx(345.0)
        assert sized["slippage_reserve_usd"] == SLIPPAGE_RESERVE_USD == 30.0

    def test_production_bracket_sizes_only_from_strategy_risk(self):
        sized = build_production_bracket(
            direction="bullish", entry_price=30000.0,
            invalidation_level=29982.75, target_price=30100.0,
            contract=MNQ, max_risk_usd=350.0, max_contracts=15,
            min_reward_to_risk=1.0)
        assert sized["geometry"].size == 10
        assert sized["geometry"].risk_usd == pytest.approx(345.0)
        assert sized["sizing"]["projected_all_in_risk_usd"] > 350.0


class TestPostFillReserveBoundaries:
    @pytest.mark.parametrize("adverse_ticks,expected_risk,remaining", [
        (0, 349.0, 30.0),
        (5, 354.0, 25.0),
        (25, 374.0, 5.0),
        (30, 379.0, 0.0),
    ])
    def test_adverse_slippage_consumes_reserve_once_and_inclusively(
            self, adverse_ticks, expected_risk, remaining):
        runner = _risk349()
        fill_price = 30000.0 + adverse_ticks * MNQ.tick_size
        auth = runner.authorize_actual_fill(_fill(fill_price, 2))
        assert auth["authorized"] is True
        assert auth["strategy_risk_cap_usd"] == PRODUCTION_MAX_RISK_USD
        assert auth["authorized_strategy_risk_usd"] == pytest.approx(349.0)
        assert auth["post_fill_structural_risk_usd"] == pytest.approx(expected_risk)
        assert auth["actual_entry_slippage_usd"] == pytest.approx(adverse_ticks)
        assert auth["remaining_slippage_reserve_usd"] == pytest.approx(remaining)
        assert auth["slippage_reserve_exceeded"] is False
        # Structural exposure already contains entry slip. The remaining
        # reserve plus measured costs does not add that same entry slip again.
        assert auth["all_in_risk_usd"] == pytest.approx(381.44)
        assert auth["fees_usd"] == pytest.approx(1.44)
        assert auth["commissions_usd"] == pytest.approx(1.0)

    def test_more_than_30_adverse_slippage_fails_closed(self):
        runner = _risk349()
        auth = runner.authorize_actual_fill(_fill(30000.0 + 31 * 0.25, 2))
        assert auth["authorized"] is False
        assert auth["reason"] == "slippage_reserve_exceeded"
        assert auth["actual_entry_slippage_usd"] == pytest.approx(31.0)
        assert auth["remaining_slippage_reserve_usd"] == 0.0

    def test_short_adverse_slippage_is_measured_against_final_bid(self):
        runner = _risk349("bearish")
        auth = runner.authorize_actual_fill(_fill(30000.0 - 5 * 0.25, 2))
        assert auth["authorized"] is True
        assert auth["final_quote_reference"] == 30000.0
        assert auth["actual_entry_slippage_usd"] == pytest.approx(5.0)
        assert auth["post_fill_structural_risk_usd"] == pytest.approx(354.0)

    def test_favorable_entry_price_consumes_no_reserve_or_authority(self):
        runner = _risk349()
        auth = runner.authorize_actual_fill(_fill(30000.0 - 5 * 0.25, 2))
        assert auth["authorized"] is True
        assert auth["signed_entry_slippage_ticks"] == pytest.approx(-5.0)
        assert auth["actual_entry_slippage_usd"] == 0.0
        assert auth["remaining_slippage_reserve_usd"] == 30.0
        assert auth["size"] == runner.geometry.size == 2

    def test_missing_quote_cannot_be_used_to_claim_slippage(self):
        runner = _risk349()
        runner.entry_capture = None
        auth = runner.authorize_actual_fill(_fill(30001.25, 2))
        assert auth["authorized"] is False
        assert auth["reason"] == "entry_slippage_unproven"
        assert auth["actual_entry_slippage_usd"] is None
        assert auth["remaining_slippage_reserve_usd"] is None

    def test_changed_stop_or_quantity_cannot_be_disguised_as_slippage(self):
        changed_stop = _risk349()
        changed_stop.final_quote_economics["structural_stop"] += 0.25
        refused_stop = changed_stop.authorize_actual_fill(_fill(30001.25, 2))
        assert refused_stop["authorized"] is False
        assert refused_stop["reason"] == "authorized_geometry_changed"

        changed_quantity = _risk349()
        refused_quantity = changed_quantity.authorize_actual_fill(_fill(30000.0, 3))
        assert refused_quantity["authorized"] is False
        assert refused_quantity["reason"] == "quantity_above_authorized"

    def test_prod_20261002_t2_one_tick_is_counted_once(self):
        runner, _ = _runner(
            "bullish", 31240.75, 31225.0, 31282.75, 31240.75,
            size=10, max_stop_points=40.0, max_risk_usd=350.0)
        assert runner.geometry.risk_usd == pytest.approx(315.0)
        auth = runner.authorize_actual_fill(_fill(31241.0, 10))
        assert auth["authorized"] is True
        assert auth["actual_entry_slippage_usd"] == pytest.approx(5.0)
        assert auth["post_fill_structural_risk_usd"] == pytest.approx(320.0)
        assert auth["remaining_slippage_reserve_usd"] == pytest.approx(25.0)
        assert auth["fees_usd"] == pytest.approx(7.2)
        assert auth["commissions_usd"] == pytest.approx(5.0)
        assert auth["all_in_risk_usd"] == pytest.approx(357.2)
