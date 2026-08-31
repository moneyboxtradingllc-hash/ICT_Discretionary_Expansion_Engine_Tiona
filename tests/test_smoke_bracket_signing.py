"""SMOKE-SIGN-REPAIR — the smoke harness must sign bracket ticks like production.

Topstep reads bracket legs as SIGNED offsets and refuses the order when the sign
is wrong. Live, 2026-08-10, on the reset Combine:

    errorCode 2 — "Invalid stop loss ticks (40). Ticks should be less than zero
                   when longing."

`BracketGeometry` had always signed them correctly. `place_bracket_market_order`
sent `points_to_ticks(...)` unsigned, so the smoke harness could never place an
order at all -- it died at venue validation before testing anything else.

The repair does not add a second sign convention. Both paths now call
`sign_stop_ticks` / `sign_target_ticks`, and these tests pin them together: the
rendered smoke payload is compared against the PRODUCTION geometry's own signed
values, so the two cannot drift apart again without a failure here.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.topstepx_client import (ORDER_SIDE, ORDER_TYPE,  # noqa: E402
                                    TopstepXClient, TopstepXContract,
                                    TopstepXError)
from broker.topstepx_combine_risk import (BracketGeometry,  # noqa: E402
                                          sign_stop_ticks, sign_target_ticks)

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="Micro Nasdaq",
                       tick_size=0.25, tick_value=0.5, active=True)
ACCOUNT = 12345
STOP_POINTS = 10.0
TARGET_POINTS = 10.0


def geometry(direction: str, *, stop_points=STOP_POINTS, target_points=TARGET_POINTS):
    """The PRODUCTION object, built exactly as production builds it."""
    bullish = direction == "bullish"
    entry = 29800.0
    return BracketGeometry(
        direction=direction, side="buy" if bullish else "sell",
        side_code=ORDER_SIDE["buy" if bullish else "sell"], entry_price=entry,
        stop_price=entry - stop_points if bullish else entry + stop_points,
        target_price=entry + target_points if bullish else entry - target_points,
        stop_points=stop_points, target_points=target_points,
        stop_ticks=MNQ.points_to_ticks(stop_points),
        target_ticks=MNQ.points_to_ticks(target_points),
        size=1, risk_usd=stop_points * 2.0, reward_usd=target_points * 2.0)


def smoke_payload(side: str, *, stop_points=STOP_POINTS, target_points=TARGET_POINTS,
                  tag="SMOKE-TEST"):
    """Render the smoke payload without any network call.

    The transport is replaced by a recorder, so this exercises the REAL payload
    construction in `place_bracket_market_order` rather than a copy of it.
    """
    sent = {}

    def transport(url, payload, headers):        # noqa: ARG001
        sent.update(payload)
        return {"success": True, "orderId": 1, "errorCode": 0, "errorMessage": None}

    client = TopstepXClient("u", "k")
    client._token = "test-token"                                    # noqa: SLF001
    client._token_at = None                                         # noqa: SLF001
    client._request_with_backoff = transport                        # noqa: SLF001
    client._session_token = lambda: "test-token"                    # noqa: SLF001
    client.place_bracket_market_order(
        account_id=ACCOUNT, contract=MNQ, side=side, size=1,
        stop_points=stop_points, target_points=target_points, custom_tag=tag)
    return sent


# ══════════════════════════════════════════════════════════════════════════════
class TestSmokeMatchesProductionSigning:
    """The whole point: one convention, proven equal at the payload."""

    @pytest.mark.parametrize("side,direction", [("buy", "bullish"), ("sell", "bearish")])
    def test_stop_sign_matches_production_geometry(self, side, direction):
        payload = smoke_payload(side)
        assert payload["stopLossBracket"]["ticks"] == \
            geometry(direction).signed_stop_ticks()

    @pytest.mark.parametrize("side,direction", [("buy", "bullish"), ("sell", "bearish")])
    def test_target_sign_matches_production_geometry(self, side, direction):
        payload = smoke_payload(side)
        assert payload["takeProfitBracket"]["ticks"] == \
            geometry(direction).signed_target_ticks()

    @pytest.mark.parametrize("side,direction", [("buy", "bullish"), ("sell", "bearish")])
    def test_the_whole_bracket_matches_the_production_payload(self, side, direction):
        """Not just the signs -- the rendered bracket legs are identical."""
        smoke = smoke_payload(side)
        prod = geometry(direction).as_order_payload(ACCOUNT, MNQ.id, "SMOKE-TEST")
        assert smoke["stopLossBracket"] == prod["stopLossBracket"]
        assert smoke["takeProfitBracket"] == prod["takeProfitBracket"]
        assert smoke["side"] == prod["side"]
        assert smoke["type"] == prod["type"]


class TestTheVenueContract:
    """What Topstep told us, asserted directly."""

    def test_a_long_sends_a_negative_stop_and_positive_target(self):
        p = smoke_payload("buy")
        assert p["stopLossBracket"]["ticks"] == -40, "the exact live rejection"
        assert p["takeProfitBracket"]["ticks"] == 40

    def test_a_short_sends_a_positive_stop_and_negative_target(self):
        p = smoke_payload("sell")
        assert p["stopLossBracket"]["ticks"] == 40
        assert p["takeProfitBracket"]["ticks"] == -40

    def test_the_unsigned_value_that_was_rejected_is_no_longer_sent(self):
        assert smoke_payload("buy")["stopLossBracket"]["ticks"] != \
            MNQ.points_to_ticks(STOP_POINTS)


class TestPayloadShape:

    @pytest.mark.parametrize("side", ["buy", "sell"])
    def test_ticks_are_integers(self, side):
        p = smoke_payload(side)
        for leg in ("stopLossBracket", "takeProfitBracket"):
            assert isinstance(p[leg]["ticks"], int), leg
            assert not isinstance(p[leg]["ticks"], bool)

    @pytest.mark.parametrize("side", ["buy", "sell"])
    def test_bracket_leg_types(self, side):
        p = smoke_payload(side)
        assert p["stopLossBracket"]["type"] == ORDER_TYPE["stop"] == 4
        assert p["takeProfitBracket"]["type"] == ORDER_TYPE["limit"] == 1

    @pytest.mark.parametrize("side", ["buy", "sell"])
    def test_the_parent_stays_a_market_order(self, side):
        p = smoke_payload(side)
        assert p["type"] == ORDER_TYPE["market"] == 2
        assert p["limitPrice"] is None and p["stopPrice"] is None
        assert p["trailPrice"] is None
        assert p["side"] == ORDER_SIDE[side]
        assert p["size"] == 1

    def test_the_custom_tag_is_carried(self):
        assert smoke_payload("buy", tag="SMOKE-XYZ")["customTag"] == "SMOKE-XYZ"

    def test_a_bracketless_order_is_still_impossible(self):
        for bad in ({"stop_points": 0.0}, {"target_points": 0.0},
                    {"stop_points": -5.0}):
            with pytest.raises(TopstepXError, match="bracket distances must be"):
                smoke_payload("buy", **bad)


class TestNoProductionInvolvement:
    """The smoke path must not reach for a mission or a token."""

    def test_the_smoke_path_names_no_mission_or_token(self):
        import inspect
        src = inspect.getsource(TopstepXClient.place_bracket_market_order)
        for forbidden in ("mission", "token", "authorization", "consume_attempt",
                          "smoke_auth", "brain", "candidate"):
            assert forbidden not in src.lower(), forbidden

    def test_signing_helpers_are_pure(self):
        """No state, no I/O -- just the convention."""
        assert sign_stop_ticks("bullish", 40) == -40
        assert sign_stop_ticks("bearish", 40) == 40
        assert sign_target_ticks("bullish", 40) == 40
        assert sign_target_ticks("bearish", 40) == -40
        # idempotent in the sense that repeated calls never drift
        assert sign_stop_ticks("bullish", 40) == sign_stop_ticks("bullish", 40)


class TestProductionSigningUnchanged:
    """The repair must not have altered production behaviour."""

    @pytest.mark.parametrize("direction,stop_expect,target_expect", [
        ("bullish", -40, 40), ("bearish", 40, -40)])
    def test_geometry_still_signs_as_before(self, direction, stop_expect, target_expect):
        g = geometry(direction)
        assert g.signed_stop_ticks() == stop_expect
        assert g.signed_target_ticks() == target_expect

    def test_geometry_payload_unchanged_shape(self):
        p = geometry("bullish").as_order_payload(ACCOUNT, MNQ.id, "T")
        assert p["stopLossBracket"] == {"ticks": -40, "type": 4}
        assert p["takeProfitBracket"] == {"ticks": 40, "type": 1}
