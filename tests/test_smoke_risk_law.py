"""FIRST-DAY SMOKE LAW locks (operator authorization 2026-08-05).

The production doctrine ($250 / 2 trades / 15 MNQ) is NOT active for the first
execution smoke. These locks prove the stricter mission caps govern, that the
structural stop is never adjusted to fit them, and that the authorization
phrase and token state the real limit.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_smoke_auth as auth                # noqa: E402
from broker.topstepx_client import TopstepXContract           # noqa: E402
from broker.topstepx_combine_risk import (                    # noqa: E402
    MAX_RISK_PER_TRADE_USD, MIN_REWARD_TO_RISK, MNQ_DOLLARS_PER_POINT,
    SMOKE_MAX_CONTRACTS, SMOKE_MAX_RISK_USD, SMOKE_MAX_STOP_POINTS,
    RiskRejection, build_bracket, effective_max_risk_usd, ticks_between,
)

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 14, 0, tzinfo=timezone.utc)


class TestSmokeCaps:

    def test_production_cap_remains_250(self):
        assert MAX_RISK_PER_TRADE_USD == 250.00

    def test_smoke_cap_is_20(self):
        assert SMOKE_MAX_RISK_USD == 20.00

    def test_the_stricter_cap_governs(self):
        assert effective_max_risk_usd() == 20.00
        assert effective_max_risk_usd(250.0, 20.0) == 20.0
        assert effective_max_risk_usd(20.0, 250.0) == 20.0

    def test_smoke_size_is_exactly_one_mnq(self):
        assert SMOKE_MAX_CONTRACTS == 1

    def test_max_stop_distance_is_ten_points(self):
        assert SMOKE_MAX_STOP_POINTS == 10.00

    def test_mnq_point_value_is_two_dollars(self):
        assert MNQ_DOLLARS_PER_POINT == 2.00

    @pytest.mark.parametrize("points,expected", [(5.0, 10.0), (7.5, 15.0), (10.0, 20.0)])
    def test_the_operator_risk_table_reproduces(self, points, expected):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20000.0 - points,
                          target_price=20000.0 + points * 2, contract=MNQ)
        assert g.risk_usd == expected

    def test_a_ten_point_stop_is_exactly_twenty_dollars(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19990.0, target_price=20030.0, contract=MNQ)
        assert g.stop_ticks == 40 and g.risk_usd == 20.00

    def test_a_stop_wider_than_ten_points_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19989.0, target_price=20050.0, contract=MNQ)
        assert exc.value.reason == "stop_distance_above_cap"

    def test_the_default_cap_is_the_smoke_cap_not_production(self):
        """A caller who forgets the cap gets 20 dollars, never 250."""
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19970.0, target_price=20100.0,
                          contract=MNQ, max_stop_points=None)
        assert exc.value.reason == "risk_above_cap"


class TestStopIsNeverAdjusted:

    def test_the_stop_equals_the_luna_invalidation(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19993.75, target_price=20030.0, contract=MNQ)
        assert g.stop_price == 19993.75

    def test_a_long_stop_rounds_away_from_entry(self):
        """Rounding toward entry would sit INSIDE the structural level."""
        assert ticks_between(20000.0, 19993.1, MNQ, round_away=True) == 28
        assert ticks_between(20000.0, 19993.1, MNQ, round_away=False) == 27

    def test_a_short_stop_also_rounds_away(self):
        g = build_bracket(direction="bearish", entry_price=20000.0,
                          invalidation_level=20006.9, target_price=19980.0, contract=MNQ)
        assert g.stop_ticks == 28

    def test_rounding_away_cannot_smuggle_risk_past_the_cap(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20000.0 - 9.94, target_price=20040.0,
                          contract=MNQ)
        assert g.stop_ticks == 40 and g.risk_usd == 20.00

    def test_the_target_rounds_toward_entry_so_reward_is_never_overstated(self):
        assert ticks_between(20000.0, 20009.9, MNQ, round_away=False) == 39


class TestRewardGate:

    def test_reward_below_the_gate_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19995.0, target_price=20004.0,
                          contract=MNQ)          # 4 up vs 5 down = 0.80R
        assert exc.value.reason == "reward_below_gate"
        assert "may be moved to manufacture" in str(exc.value)

    def test_the_default_gate_is_one_r(self):
        # RR-FLOOR-1.0 (2026-08-08, operator ruling). An eligibility floor, not
        # a take-profit: liquidity still sets the target, structure the stop.
        assert MIN_REWARD_TO_RISK == 1.0

    def test_exactly_one_r_passes(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19995.0, target_price=20005.0,
                          contract=MNQ)
        assert g.reward_usd / g.risk_usd == pytest.approx(1.0)

    def test_one_and_a_half_r_still_passes(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19995.0, target_price=20007.5, contract=MNQ)
        assert g.reward_usd / g.risk_usd == pytest.approx(1.5)


class TestSmokeAuthorization:

    def test_the_phrase_states_twenty_dollars(self):
        assert "MAX PLANNED RISK $20" in auth.AUTHORIZATION_PHRASE
        assert "$250" not in auth.AUTHORIZATION_PHRASE

    def test_the_retired_250_phrase_is_refused_with_a_reason(self):
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.issue(phrase=auth._RETIRED_PHRASES[0], account_fingerprint=FP,
                       contract_id=MNQ.id, now=NOW)
        assert "RETIRED" in str(exc.value)

    def test_the_token_binds_to_twenty_not_two_fifty(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, now=NOW)
        assert t.max_risk_usd == 20.00
        assert t.max_stop_points == 10.00

    def test_risk_over_twenty_is_refused_by_the_token(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, now=NOW)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=20.01, now=NOW)
        assert "exceeds the authorized maximum" in str(exc.value)

    def test_a_stop_wider_than_ten_points_is_refused_by_the_token(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, now=NOW)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=15.0, stop_points=10.5, now=NOW)
        assert "stop distance" in str(exc.value)

    def test_the_token_binds_to_one_candidate(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, candidate_fingerprint="cand-1",
                       snapshot_id="snap-1", now=NOW)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0,
                                      candidate_fingerprint="cand-2", now=NOW)
        assert "different candidate" in str(exc.value)

    def test_the_token_binds_to_one_snapshot(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, snapshot_id="snap-1", now=NOW)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0, snapshot_id="snap-2", now=NOW)
        assert "bound to snapshot" in str(exc.value)

    def test_size_above_one_is_refused(self):
        t = auth.issue(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                       contract_id=MNQ.id, now=NOW)
        with pytest.raises(auth.AuthorizationError):
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=2, risk_usd=10.0, now=NOW)


class TestVenueSignedBracketTicks:
    """REGRESSION - live venue, 2026-08-05.

    The published example shows unsigned ticks. The gateway rejects them:
      errorCode=2 "Invalid stop loss ticks (40).
                   Ticks should be less than zero when longing."
    Ticks are SIGNED relative to entry. The economic levels do not change.
    """

    def _long(self):
        return build_bracket(direction="bullish", entry_price=20000.0,
                             invalidation_level=19990.0, target_price=20020.0,
                             contract=MNQ)

    def _short(self):
        return build_bracket(direction="bearish", entry_price=20000.0,
                             invalidation_level=20010.0, target_price=19980.0,
                             contract=MNQ)

    def test_a_long_sends_a_negative_stop_and_positive_target(self):
        g = self._long()
        p = g.as_order_payload(1, MNQ.id)
        assert p["stopLossBracket"]["ticks"] == -40
        assert p["takeProfitBracket"]["ticks"] == 80

    def test_a_short_sends_a_positive_stop_and_negative_target(self):
        g = self._short()
        p = g.as_order_payload(1, MNQ.id)
        assert p["stopLossBracket"]["ticks"] == 40
        assert p["takeProfitBracket"]["ticks"] == -80

    def test_the_magnitudes_are_unchanged_by_the_sign(self):
        for g in (self._long(), self._short()):
            assert abs(g.signed_stop_ticks()) == g.stop_ticks
            assert abs(g.signed_target_ticks()) == g.target_ticks

    def test_the_economic_levels_are_untouched(self):
        g = self._long()
        assert g.stop_price == 19990.0 and g.target_price == 20020.0
        assert g.risk_usd == 20.00

    def test_signed_ticks_appear_in_evidence(self):
        e = self._long().evidence()
        assert e["signed_stop_ticks"] == -40 and e["signed_target_ticks"] == 80

    def test_bracket_types_are_unchanged(self):
        p = self._long().as_order_payload(1, MNQ.id)
        assert p["stopLossBracket"]["type"] == 4     # Stop
        assert p["takeProfitBracket"]["type"] == 1   # Limit
