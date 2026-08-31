"""RR-FLOOR-1.0 (2026-08-08, operator ruling). 1.5R -> 1.0R.

A FLOOR, not a target. Structure still sets the invalidation, liquidity still
sets the objective, and RR is only the ratio those two market-derived objects
happen to produce. The rule decides eligibility; it never decides where either
boundary sits.

Two authoritative gates sit on the same live path -- the producer qualifies,
then the bracket builder sizes. Moving only one would have killed every
1.0-1.49 trade at `reward_below_gate` while the ruling appeared applied.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402
from _step7_fixture import EXECUTABLE_TOOL_EXEMPLAR as EXEMPLAR  # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL                 # noqa: E402
from broker.luna_candidate_producer import (LEGACY_QUALIFICATION_R,    # noqa: E402
                                            MIN_QUALIFICATION_R,
                                            CandidateProducer, NoCandidate,
                                            authorized_objective_catalog)
from broker.topstepx_client import TopstepXContract                    # noqa: E402
from broker.topstepx_combine_risk import MIN_REWARD_TO_RISK            # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
NOW = datetime(2026, 8, 8, 14, 0, tzinfo=timezone.utc)
ENTRY = 29700.0
STOP = 29735.0                    # 35-point structural stop (the preferred ceiling)


def world(objective_price):
    """One market. The stop is structural, the objective is liquidity."""
    return {"timestamp": "2026-08-08T14:00:00+00:00",
            "market": _priced({"current_price": ENTRY}),
            "liquidity": {"nearest_buy_side": 29900.0,
                          "nearest_sell_side": objective_price},
            "protected_swings": {"protected_high": {"level": STOP},
                                 "protected_low": {"level": 29000.0}}}


def produce(objective_price):
    bi = world(objective_price)
    cat = authorized_objective_catalog({}, bi, ENTRY)
    match = [o for o in cat if abs(o["price"] - objective_price) < 1e-6]
    assert match, f"no catalog entry at {objective_price}"
    parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
              "narrative_phase": "distribution",
              "current_action": "propose bearish entry",
              "recommended_playbook_family": "liquidity_sweep_reversal",
              "recommended_tool_family": [EXEMPLAR],
              "invalidation_level": STOP,
              "objective_id": match[0]["objective_id"]}
    producer = CandidateProducer(account_fingerprint="acct:test", contract=MNQ)
    try:
        candidate = producer.produce(
            brain_result={"ok": True, "parsed": parsed, "fallback_reason": None,
                          "model": PRODUCTION_MODEL},
            brain_input=bi, snapshot=_detected("ifvg", "fvg"),
            qualification={"qualified": True},
            engine_inventory={}, snapshot_id="s",
            market_data_timestamp=bi["timestamp"],
            latest_closed_bar_timestamp=bi["timestamp"], now=NOW)
        return producer, candidate, None
    except NoCandidate as exc:
        return producer, None, exc


def objective_for(rr):
    """The liquidity level that HAPPENS to yield ~this ratio against a 35pt stop.

    Snapped to the 0.25 MNQ tick grid, because a real liquidity level always is
    -- an off-grid target is refused by `objective_off_tick` long before the
    reward floor is consulted, which would test the wrong gate.
    """
    raw = ENTRY - rr * 35.0
    return round(round(raw / 0.25) * 0.25, 2)


def actual_rr(objective_price):
    """The ratio the SNAPPED level really produces."""
    return abs(objective_price - ENTRY) / abs(STOP - ENTRY)


class TestTheFloorItself:

    def test_both_authoritative_gates_moved_together(self):
        assert MIN_QUALIFICATION_R == 1.0
        assert MIN_REWARD_TO_RISK == 1.0, (
            "the bracket gate would silently kill every 1.0-1.49 trade")
        assert LEGACY_QUALIFICATION_R == 1.5    # retained for telemetry only

    @pytest.mark.parametrize("rr,qualifies", [
        (0.80, False), (0.99, False),
        (1.00, True), (1.01, True), (1.23, True), (1.25, True),
        (1.49, True), (1.50, True), (2.00, True), (2.20, True),
    ])
    def test_eligibility_at_the_boundary(self, rr, qualifies):
        objective = objective_for(rr)
        # the snapped level must still sit on the intended side of the floor
        assert (actual_rr(objective) >= 1.0) is qualifies, (
            f"fixture drifted: {rr} snapped to {actual_rr(objective):.4f}R")
        _, candidate, exc = produce(objective)
        if qualifies:
            assert candidate is not None, f"{rr}R should qualify: {exc}"
        else:
            assert exc is not None
            assert exc.reason == "reward_below_qualification"

    def test_the_owner_examples(self):
        """35pt stop / 43pt target = 1.23R eligible; 28pt target = 0.80R reject."""
        _, candidate, _ = produce(ENTRY - 43.0)
        assert candidate is not None
        assert round(candidate.extras["expected_reward_to_risk"], 2) == 1.23
        _, none, exc = produce(ENTRY - 28.0)
        assert none is None
        assert exc.reason == "reward_below_qualification"


class TestNothingElseMoved:

    def test_the_target_is_the_liquidity_objective_not_a_ratio(self):
        """A 2.20R setup keeps its liquidity target; it is not trimmed to 1.0R."""
        _, candidate, _ = produce(ENTRY - 77.0)
        assert candidate.objective.price == ENTRY - 77.0
        assert round(candidate.extras["expected_reward_to_risk"], 2) == 2.20

    def test_the_stop_is_the_structural_invalidation(self):
        _, candidate, _ = produce(objective_for(1.23))
        assert candidate.invalidation_price == STOP

    def test_the_floor_cannot_manufacture_either_boundary(self):
        """A sub-floor setup is REFUSED, never rescued by moving an object."""
        _, none, exc = produce(objective_for(0.90))
        assert none is None
        assert "Neither boundary may be moved" in str(exc)

    def test_risk_and_size_doctrine_untouched(self):
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  PREFERRED_MAX_STOP_POINTS,
                                                  PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        assert (PRODUCTION_MAX_RISK_USD, PRODUCTION_MAX_CONTRACTS) == (350.0, 15)
        assert (PREFERRED_MAX_STOP_POINTS, ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)

    def test_hybrid_shadow_untouched(self):
        from ai_brain.two_brain import hybrid_has_authority, two_brain_mode
        assert two_brain_mode() in ("off", "shadow")
        assert hybrid_has_authority() is False


class TestCounterfactualTelemetry:
    """Monday must be able to say how many trades exist ONLY because of this."""

    def test_a_sub_legacy_trade_is_flagged(self):
        producer, candidate, _ = produce(objective_for(1.27))
        trace = producer.last_decision_trace
        assert candidate is not None
        assert trace["reward_risk_floor"] == 1.0
        assert trace["reward_risk_valid"] is True
        assert trace["legacy_reward_risk_floor"] == 1.5
        assert trace["legacy_floor_verdict"] == "WOULD_REJECT"
        assert trace["eligible_only_because_floor_moved"] is True

    def test_a_trade_that_always_qualified_is_not_flagged(self):
        producer, candidate, _ = produce(objective_for(2.00))
        trace = producer.last_decision_trace
        assert candidate is not None
        assert trace["legacy_floor_verdict"] == "WOULD_PASS"
        assert trace["eligible_only_because_floor_moved"] is False

    def test_the_counterfactual_gates_nothing(self):
        """Disposition follows the 1.0 floor alone."""
        for rr in (1.05, 1.20, 1.45):
            _, candidate, _ = produce(objective_for(rr))
            assert candidate is not None, f"{rr}R blocked by the retired floor"

    def test_the_fields_exist_on_every_decision_record(self):
        from broker.candidate_decision_record import blank_trace
        for field in ("legacy_reward_risk_floor", "legacy_floor_verdict",
                      "eligible_only_because_floor_moved"):
            assert field in blank_trace(), field
