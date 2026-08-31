"""PROD-20260810 — the production execution token must carry production limits.

The first armed session of the Organism Era produced a legitimate candidate on
scan 2: a 33.75-point structural stop, comfortably inside the 35 preferred /
40 absolute doctrine. It never reached Topstep. The execution token had been
minted with `max_risk_usd` and `max_contracts` bound to the authorization -- but
`max_stop_points` was never passed at all, so `smoke_auth.issue()` fell through
to its own default:

    SMOKE_MAX_STOP_POINTS = 10.00

Every candidate with a normal ICT stop was therefore unexecutable, and the halt
fired AFTER the mission attempt had already been consumed. One of two authorized
session trades was spent on an internal binding error with zero orders placed.

Same shape as `wrong_model` and the duplicated reward floor: a second source of
truth quietly supplying a stale value. The repair binds the ceiling to the SAME
authorization the other two limits come from -- never a fresh literal.

Smoke keeps its own 10-point law. It just cannot lend it to production.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_smoke_auth as auth                        # noqa: E402
from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,   # noqa: E402
                                          PREFERRED_MAX_STOP_POINTS,
                                          PRODUCTION_MAX_CONTRACTS,
                                          PRODUCTION_MAX_RISK_USD,
                                          SMOKE_MAX_RISK_USD,
                                          SMOKE_MAX_STOP_POINTS)
from broker.topstepx_session_authorization import (                   # noqa: E402
    SessionAuthorization)

NOW = datetime(2026, 8, 10, 13, 40, tzinfo=timezone.utc)
FINGERPRINT = "acct:test"
CONTRACT = "CON.F.US.MNQ.U26"


def production_token(*, max_stop_points, max_risk_usd=PRODUCTION_MAX_RISK_USD,
                     max_contracts=PRODUCTION_MAX_CONTRACTS):
    return auth.issue(phrase=auth.AUTHORIZATION_PHRASE,
                      account_fingerprint=FINGERPRINT, contract_id=CONTRACT,
                      max_risk_usd=max_risk_usd, max_contracts=max_contracts,
                      max_stop_points=max_stop_points, now=NOW)


def authorize(token, *, stop_points, size=1, risk_usd=100.0):
    """Raises AuthorizationError when the token refuses the geometry."""
    return auth.authorize_submission(token, account_fingerprint=FINGERPRINT,
                                     contract_id=CONTRACT, size=size,
                                     risk_usd=risk_usd,
                                     stop_points=stop_points, now=NOW)


def session_authorization():
    """The real doctrine object the mint now reads its ceilings from."""
    return SessionAuthorization(
        session_id="PROD-20260810", account_fingerprint=FINGERPRINT,
        contract_id=CONTRACT, session_date="2026-08-10",
        decision_window="09:30-14:00 America/New_York")


# ══════════════════════════════════════════════════════════════════════════════
class TestTheDefect:

    def test_the_mint_now_binds_the_authorization_stop_ceiling(self):
        """The one-line repair, asserted at its call site."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        mint = src[src.index("def mint():"):src.index("def on_consumed(")]
        assert "max_stop_points=self.mission.authorization.absolute_stop_ceiling" \
            in mint, "the token would fall back to the smoke default"
        # and all three limits come from ONE object -- no third source of truth
        for field in ("maximum_risk_per_trade", "maximum_contracts",
                      "absolute_stop_ceiling"):
            assert f"self.mission.authorization.{field}" in mint, field

    def test_the_authorization_already_carries_the_ceiling(self):
        a = session_authorization()
        assert a.absolute_stop_ceiling == 50.0
        assert a.preferred_stop_ceiling == 35.0
        assert a.maximum_risk_per_trade == 350.0
        assert a.maximum_contracts == 15

    def test_an_unpassed_ceiling_still_defaults_to_smoke(self):
        """The trap is still there for any future caller that forgets it."""
        token = auth.issue(phrase=auth.AUTHORIZATION_PHRASE,
                           account_fingerprint=FINGERPRINT, contract_id=CONTRACT,
                           max_risk_usd=PRODUCTION_MAX_RISK_USD,
                           max_contracts=PRODUCTION_MAX_CONTRACTS, now=NOW)
        assert token.max_stop_points == SMOKE_MAX_STOP_POINTS == 10.0


class TestProductionStopBoundaries:
    """PHASE 7 — the full ladder, against a production-bound token."""

    @pytest.mark.parametrize("stop_points,allowed", [
        (9.75, True), (10.00, True), (10.25, True),
        (33.75, True),                       # THE EXACT FAILED CANDIDATE
        (35.00, True),                       # the preferred bound, unchanged
        # RISK-DOCTRINE-MIGRATION 2026-08-20: ceiling 40.0 -> 50.0.
        (40.75, True),                       # 2026-08-20 11:03 — died on 3 ticks
        (47.00, True),                       # the 11:02 candle's worst price
        (49.75, True), (50.00, True),        # the new bound, inclusive
        (50.25, False),                      # and one tick past it
        (60.00, False),
    ])
    def test_the_ladder(self, stop_points, allowed):
        token = production_token(max_stop_points=ABSOLUTE_MAX_STOP_POINTS)
        if allowed:
            assert authorize(token, stop_points=stop_points) is not None
        else:
            with pytest.raises(auth.AuthorizationError) as exc:
                authorize(token, stop_points=stop_points)
            assert "stop distance" in str(exc.value)

    def test_the_repair_does_not_weaken_the_absolute_ceiling(self):
        token = production_token(max_stop_points=ABSOLUTE_MAX_STOP_POINTS)
        assert token.max_stop_points == 50.0 == ABSOLUTE_MAX_STOP_POINTS
        with pytest.raises(auth.AuthorizationError):
            authorize(token, stop_points=50.25)

    def test_preferred_and_absolute_remain_distinct(self):
        """50 is a VETO CEILING, not a target. The preferred bound did not move,
        so the extended-volatility lane widened from 5 points to 15 -- setups
        that must justify their width, not setups that get a wider stop."""
        assert PREFERRED_MAX_STOP_POINTS == 35.0
        assert ABSOLUTE_MAX_STOP_POINTS == 50.0
        assert ABSOLUTE_MAX_STOP_POINTS - PREFERRED_MAX_STOP_POINTS == 15.0


class TestRiskAndSizeBoundaries:

    @pytest.mark.parametrize("risk,allowed", [(349.99, True), (350.00, True),
                                              (350.01, False), (1000.0, False)])
    def test_production_risk_ceiling(self, risk, allowed):
        token = production_token(max_stop_points=ABSOLUTE_MAX_STOP_POINTS)
        if allowed:
            assert authorize(token, stop_points=33.75, risk_usd=risk)
        else:
            with pytest.raises(auth.AuthorizationError):
                authorize(token, stop_points=33.75, risk_usd=risk)

    @pytest.mark.parametrize("size,allowed", [(1, True), (15, True),
                                              (16, False), (100, False)])
    def test_production_contract_cap(self, size, allowed):
        token = production_token(max_stop_points=ABSOLUTE_MAX_STOP_POINTS)
        if allowed:
            assert authorize(token, stop_points=33.75, size=size)
        else:
            with pytest.raises(auth.AuthorizationError):
                authorize(token, stop_points=33.75, size=size)


class TestSmokeKeepsItsOwnLaw:
    """PHASE 5 — smoke authority stays smoke-only. It is not deleted."""

    def test_the_smoke_constants_are_intact(self):
        assert SMOKE_MAX_STOP_POINTS == 10.00
        assert SMOKE_MAX_RISK_USD == 20.00

    def test_a_smoke_token_still_refuses_a_wide_stop(self):
        token = production_token(max_stop_points=SMOKE_MAX_STOP_POINTS,
                                 max_risk_usd=SMOKE_MAX_RISK_USD,
                                 max_contracts=1)
        assert authorize(token, stop_points=10.0, risk_usd=20.0)
        for bad in (10.25, 33.75, 40.0):
            with pytest.raises(auth.AuthorizationError):
                authorize(token, stop_points=bad, risk_usd=20.0)

    def test_a_smoke_token_still_refuses_production_risk(self):
        token = production_token(max_stop_points=SMOKE_MAX_STOP_POINTS,
                                 max_risk_usd=SMOKE_MAX_RISK_USD,
                                 max_contracts=1)
        with pytest.raises(auth.AuthorizationError):
            authorize(token, stop_points=9.0, risk_usd=250.0)


class TestScanTwoExactReplay:
    """PHASE 11 — the exact candidate that died, old binding vs new."""

    STOP_POINTS = 33.75

    def test_the_old_binding_rejects_it(self):
        """Reproduce the live failure precisely."""
        old = auth.issue(phrase=auth.AUTHORIZATION_PHRASE,
                         account_fingerprint=FINGERPRINT, contract_id=CONTRACT,
                         max_risk_usd=250.0, max_contracts=15, now=NOW)
        with pytest.raises(auth.AuthorizationError) as exc:
            authorize(old, stop_points=self.STOP_POINTS)
        assert "33.75" in str(exc.value)
        assert "maximum of 10" in str(exc.value)

    def test_the_new_binding_accepts_it(self):
        a = session_authorization()
        new = production_token(max_stop_points=a.absolute_stop_ceiling,
                               max_risk_usd=a.maximum_risk_per_trade,
                               max_contracts=a.maximum_contracts)
        assert authorize(new, stop_points=self.STOP_POINTS, size=7,
                         risk_usd=236.25) is not None

    def test_no_broker_endpoint_is_touched_by_this_suite(self):
        import ast
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("gated_submit", "place_bracket_market_order",
                          "place_order_raw", "submit", "modify_order"):
            assert forbidden not in called, forbidden


class TestAttemptConsumptionOrdering:
    """PHASE 8 — why a pre-venue refusal cost a session trade."""

    def test_the_attempt_is_consumed_before_the_token_is_validated(self):
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_execution_runner.py"),
                   encoding="utf-8").read()
        consumed = src.index("on_attempt_consumed(self.token.token_id)")
        validated = src.index("self._halt(TOKEN_BINDING_MISMATCH, str(exc))")
        assert consumed < validated, (
            "if this ever reverses, update the recovery doctrine")

    def test_the_token_itself_was_correctly_not_burned(self):
        """The token and the attempt are separate resources, and only the
        attempt was spent."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_execution_runner.py"),
                   encoding="utf-8").read()
        block = src[src.index("except smoke_auth.AuthorizationError as exc:"):]
        assert "_invalidate(" in block[:400]
        assert "The token was NOT burned" in block[:400]
