"""Forced flatten must not leave an orphaned bracket, and must not cancel yours.

Measured live on the reset Combine, 2026-08-10:

    close_position    -> position 0
    working orders    -> 2   (stop 3386076130 and target 3386076131 STILL LIVE)

`close_position` does NOT cancel the OCO siblings. That is the whole hazard:

    long 5 MNQ, SELL stop 5 + SELL target 5
    forced flatten -> position 0, both SELL orders still working
    one of them triggers -> the "flat" bot is now SHORT 5

So flattening is not finished when the position hits zero. It is finished when
the position is zero AND nothing of ours is still working.

The opposite error matters too. Cancelling every order on the contract would
reach an operator's own order, so cancellation requires proof of ownership --
while BLOCKING requires only doubt. Three categories, two different bars:

    ours      lineage proven      -> cancel, then re-verify
    unproven  our contract only   -> never cancel, but block completion
    foreign   another contract    -> ignore

NO NETWORK. Every venue interaction is a stub.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_execution_runner as R          # noqa: E402
from broker import topstepx_submission_record as SUB       # noqa: E402
from broker import topstepx_smoke_auth as smoke_auth       # noqa: E402
from broker.topstepx_client import (ORDER_SIDE,            # noqa: E402
                                    TopstepXContract, TopstepXError)
from broker.topstepx_combine_risk import BracketGeometry   # noqa: E402

FP = "acct:flat"
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc)
MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="",
                       tick_size=0.25, tick_value=0.5, active=True)
ENTRY_ID = 3386076129
TAG = "EXPBOT-PROD-a1b2c3"

#: The exact live shapes.
STOP_LEG = {"id": 3386076130, "contract_id": MNQ.id, "type": 4, "side": 1,
            "size": 5, "stopPrice": 29783.75, "parentOrderId": ENTRY_ID,
            "customTag": TAG + "-SL", "status": 1}
TARGET_LEG = {"id": 3386076131, "contract_id": MNQ.id, "type": 1, "side": 1,
              "size": 5, "limitPrice": 29803.75, "parentOrderId": ENTRY_ID,
              "linkedOrderId": 3386076130, "customTag": TAG + "-TP", "status": 1}
OPERATOR_ORDER = {"id": 555000, "contract_id": MNQ.id, "type": 1, "side": 1,
                  "size": 2, "customTag": None, "status": 1}
OTHER_CONTRACT = {"id": 666000, "contract_id": "CON.F.US.ES.U26", "type": 1,
                  "parentOrderId": ENTRY_ID, "status": 1}


class FlattenVenue:
    """close_position empties the position and leaves the brackets, as measured."""

    def __init__(self, *, positions=None, orders=None, cancel_fails=(),
                 query_fails=False, close_fails=False):
        self._positions = list(positions or [])
        self._orders = list(orders or [])
        self.cancelled = []
        self.cancel_fails = set(cancel_fails)
        self.query_fails = query_fails
        self.close_fails = close_fails

    def close_position(self, contract_id):
        if self.close_fails:
            raise TopstepXError("close_position refused")
        self._positions = []                      # brackets deliberately remain
        return {"success": True}

    def cancel_order(self, order_id):
        if order_id in self.cancel_fails:
            raise TopstepXError(f"cancel refused for {order_id}")
        self.cancelled.append(order_id)
        self._orders = [o for o in self._orders if o.get("id") != order_id]
        return {"success": True}

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        Modelled here because current production emergency discovery uses it:
        `searchOpen` omits Suspended bracket children by venue contract, so a
        fixture without this method models the DEGRADED fallback, not the
        normal path. No status filter is applied, matching production.
        """
        if self.query_fails:
            raise TopstepXError("order query unavailable")
        rows = list(self._orders)
        if contract_id:
            rows = [o for o in rows if o.get("contract_id") == contract_id]
        return rows

    def open_orders(self):
        if self.query_fails:
            raise TopstepXError("order search unavailable")
        return list(self._orders)

    def open_positions(self):
        if self.query_fails:
            raise TopstepXError("position search unavailable")
        return list(self._positions)


def runner(venue):
    r = R.ExecutionRunner(session=venue, account_fingerprint=FP, contract=MNQ,
                          clock=lambda: NOW)
    r.geometry = BracketGeometry(
        direction="bullish", side="buy", side_code=ORDER_SIDE["buy"],
        entry_price=29793.75, stop_price=29783.75, target_price=29803.75,
        stop_points=10.0, target_points=10.0, stop_ticks=40, target_ticks=40,
        size=5, risk_usd=100.0, reward_usd=100.0)
    r.order_id = ENTRY_ID
    r.submission_custom_tag = TAG
    r.token = smoke_auth.issue(
        phrase=smoke_auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
        contract_id=MNQ.id, max_risk_usd=250.0, max_contracts=15,
        max_stop_points=40.0, now=NOW)
    return r


LONG = [{"id": 1, "contract_id": MNQ.id, "side": "long", "size": 5}]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheLiveHazard:

    def test_close_position_alone_leaves_the_brackets_working(self):
        """The venue fact this whole module exists for."""
        v = FlattenVenue(positions=list(LONG),
                         orders=[dict(STOP_LEG), dict(TARGET_LEG)])
        v.close_position(MNQ.id)
        assert v.open_positions() == []
        assert len(v.open_orders()) == 2, "close_position cancelled nothing"

    def test_forced_flatten_cancels_our_legs_and_reverifies(self):
        v = FlattenVenue(positions=list(LONG),
                         orders=[dict(STOP_LEG), dict(TARGET_LEG)])
        out = runner(v).emergency_flatten("protection missing")
        assert sorted(v.cancelled) == [3386076130, 3386076131]
        assert out["cancelled_mission_orders"] == [3386076130, 3386076131]
        assert out["clean"] is True and out["verified"] is True
        assert out["open_positions"] == 0
        assert out["mission_working_orders"] == []
        assert v.open_orders() == [] and v.open_positions() == []

    def test_flatten_does_not_claim_success_while_a_leg_survives(self):
        """A cancel that fails must not read as a clean flatten."""
        v = FlattenVenue(positions=list(LONG),
                         orders=[dict(STOP_LEG), dict(TARGET_LEG)],
                         cancel_fails={3386076131})
        r = runner(v)
        out = r.emergency_flatten("protection missing")
        assert out["flattened"] is False, "declared flat with a live SELL target"
        assert out["clean"] is False
        assert out["mission_working_orders"] == [3386076131]
        assert [f["order_id"] for f in out["cancellation_failures"]] == [3386076131]
        assert r.state == R.RESIDUAL_ORDERS


class TestCompletionInvariant:
    """A flat position with a live bracket is NOT complete."""

    def _at_exit(self, venue):
        r = runner(venue)
        r.token.burn("test exit", now=NOW)
        return r

    def test_completion_is_refused_while_our_bracket_is_working(self):
        v = FlattenVenue(positions=[], orders=[dict(STOP_LEG)])
        with pytest.raises(R.RunnerHalt) as exc:
            self._at_exit(v).verify_clean(current_fingerprint=FP)
        assert exc.value.state == R.RESIDUAL_ORDERS
        assert "reverse position" in exc.value.detail

    def test_completion_is_refused_while_an_unaccounted_order_is_working(self):
        """Doubt is enough to block, even though it is not enough to cancel."""
        v = FlattenVenue(positions=[], orders=[dict(OPERATOR_ORDER)])
        with pytest.raises(R.RunnerHalt) as exc:
            self._at_exit(v).verify_clean(current_fingerprint=FP)
        assert exc.value.state == R.RESIDUAL_ORDERS
        assert v.cancelled == [], "an unproven order must never be cancelled"

    def test_completion_is_allowed_once_truly_clear(self):
        v = FlattenVenue(positions=[], orders=[])
        checks = self._at_exit(v).verify_clean(current_fingerprint=FP)
        assert checks["position_quantity_zero"] and checks["working_order_count_zero"]

    def test_an_order_on_another_contract_does_not_block(self):
        v = FlattenVenue(positions=[], orders=[dict(OTHER_CONTRACT)])
        checks = self._at_exit(v).verify_clean(current_fingerprint=FP)
        assert checks["working_order_count_zero"] is True
        assert v.cancelled == []


class TestOwnershipScoping:

    @pytest.mark.parametrize("order,owned", [
        (STOP_LEG, True),                 # parentOrderId
        (TARGET_LEG, True),               # parentOrderId + linkedOrderId
        ({"id": ENTRY_ID, "contract_id": MNQ.id}, True),          # the entry
        ({"id": 5, "contract_id": MNQ.id, "customTag": TAG}, True),
        ({"id": 6, "contract_id": MNQ.id, "customTag": TAG + "-SL"}, True),
        (OPERATOR_ORDER, False),          # no lineage at all
        (OTHER_CONTRACT, False),          # right lineage, wrong contract
        ({"id": 7, "contract_id": MNQ.id, "customTag": "EXPBOT-PROD-other"}, False),
    ])
    def test_ownership_requires_lineage(self, order, owned):
        assert runner(FlattenVenue()).mission_owns_order(order) is owned

    def test_the_three_categories_are_disjoint(self):
        v = FlattenVenue(orders=[dict(STOP_LEG), dict(OPERATOR_ORDER),
                                 dict(OTHER_CONTRACT)])
        split = runner(v).classify_working_orders()
        assert [o["id"] for o in split["ours"]] == [3386076130]
        assert [o["id"] for o in split["unproven"]] == [555000]
        assert [o["id"] for o in split["foreign"]] == [666000]

    def test_a_mixed_book_with_a_live_position_halts_before_touching_anything(self):
        """THE BEHAVIOUR CHANGED, DELIBERATELY.

        This used to assert that our two legs were cancelled and the position
        closed, leaving the operator's order alone and reporting `clean=False`.
        Cancelling ours is only worth doing because it makes the CLOSE safe --
        and under `TOPSTEP-UNPROVEN-ORDER-CLOSE-AUTHORITY-1` that close can no
        longer happen while an unattributed executable order rests on this
        contract.

        So the old sequence would strip a live position of its real protection
        and then halt anyway: strictly worse than doing nothing. Nothing is
        dismantled for a sequence that cannot complete.

        The operator's order is still never cancelled, and the account is still
        never reported clean. What changed is that OUR protection survives too.
        """
        v = FlattenVenue(positions=list(LONG),
                         orders=[dict(STOP_LEG), dict(TARGET_LEG),
                                 dict(OPERATOR_ORDER), dict(OTHER_CONTRACT)])
        out = runner(v).emergency_flatten("mixed book")
        assert v.cancelled == [], "protection is not stripped for a close that cannot run"
        assert 555000 not in v.cancelled and 666000 not in v.cancelled
        assert v._positions, "no flatness is created around an unproven order"
        assert out["clean"] is False, "an unaccounted order still blocks"
        assert out["flattened"] is False
        assert out["safe_terminal"] is False


class TestDegradedVenues:

    def test_a_sibling_already_cancelled_is_fine(self):
        v = FlattenVenue(positions=list(LONG), orders=[dict(STOP_LEG)])
        out = runner(v).emergency_flatten("one leg already gone")
        assert v.cancelled == [3386076130] and out["clean"] is True

    def test_a_sibling_that_already_filled_is_fine(self):
        """Target filled, stop remains: cancel the stop, then clean."""
        v = FlattenVenue(positions=[], orders=[dict(STOP_LEG)])
        out = runner(v).emergency_flatten("target filled")
        assert v.cancelled == [3386076130] and out["clean"] is True

    def test_a_failed_close_leaves_children_cancelled_and_refuses_to_claim_flat(self):
        """THE ORDERING CHANGED, DELIBERATELY.

        This test previously asserted `v.cancelled == []` -- that a failed
        close halted BEFORE any cancellation. That expectation encoded the
        defect: closing first is what let the 2026-08-26 protective stop
        survive the close and reverse the account 86ms later.

        Children are now neutralised FIRST, so by the time the close is
        attempted they are already cancelled. A close that then fails leaves
        the position open and UNPROTECTED -- which the run must report
        honestly rather than as a clean flatten.
        """
        v = FlattenVenue(positions=list(LONG), orders=[dict(STOP_LEG)],
                         close_fails=True)
        out = runner(v).emergency_flatten("close refused")
        assert v.cancelled == [3386076130], "children are neutralised first"
        assert out["flattened"] is False
        assert out["safe_terminal"] is False
        assert v._positions, "the position genuinely remains open"

    def test_an_unqueryable_venue_is_never_reported_clean(self):
        v = FlattenVenue(positions=list(LONG), orders=[dict(STOP_LEG)])
        r = runner(v)
        v.query_fails = True
        out = r.emergency_flatten("venue went dark")
        assert out["clean"] is False and out["verified"] is False
        # THE REASON SHARPENED. It used to be "the venue could not be queried".
        # Under `TOPSTEP-INCOMPLETE-DISCOVERY-AUTHORITY-1` the refusal comes
        # earlier and says something stronger: the order VIEW may be missing
        # members, so it cannot prove the account clear -- which is true whether
        # the surface raised or merely fell back.
        assert "INCOMPLETE" in out["detail"]

    def test_confirm_flat_and_clear_is_honest_about_an_unreachable_venue(self):
        v = FlattenVenue(query_fails=True)
        out = runner(v).confirm_flat_and_clear(reason="restart")
        assert out["clean"] is False and out["verified"] is False
        # `discovery` now travels with the refusal: an operator reading this
        # needs to know WHICH surface answered, not merely that one did not.
        assert out["discovery"] == "unreadable"
        assert "INCOMPLETE" in out["detail"]


class TestRestartRecovery:
    """A new process inherits only the venue's answer, never a memory."""

    def test_a_restarted_runner_without_lineage_blocks_rather_than_cancels(self):
        """No order_id and no tag: it cannot prove ownership, so it blocks."""
        v = FlattenVenue(positions=[], orders=[dict(STOP_LEG)])
        cold = R.ExecutionRunner(session=v, account_fingerprint=FP,
                                 contract=MNQ, clock=lambda: NOW)
        cold.token = smoke_auth.issue(
            phrase=smoke_auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
            contract_id=MNQ.id, max_risk_usd=250.0, max_contracts=15,
            max_stop_points=40.0, now=NOW)
        cold.token.burn("test exit", now=NOW)
        split = cold.classify_working_orders()
        assert split["ours"] == []
        assert [o["id"] for o in split["unproven"]] == [3386076130]
        with pytest.raises(R.RunnerHalt) as exc:
            cold.verify_clean(current_fingerprint=FP)
        assert exc.value.state == R.RESIDUAL_ORDERS
        assert v.cancelled == [], "a cold runner must not cancel on a guess"

    def test_a_restarted_runner_with_the_entry_id_can_clean_up(self):
        v = FlattenVenue(positions=[], orders=[dict(STOP_LEG), dict(TARGET_LEG)])
        warm = runner(v)                      # order_id + tag restored
        out = warm.confirm_flat_and_clear(reason="restart")
        assert out["clean"] is False
        assert sorted(out["mission_working_orders"]) == [3386076130, 3386076131]
        out2 = warm.emergency_flatten("restart cleanup")
        assert out2["clean"] is True and v.open_orders() == []


# ══ GATEWAY STATUS CONTRACT ═════════════════════════════════════════════════
class TestOrderStatusContract:
    """`OrderModel.status` is REQUIRED by the official Gateway schema, and
    `searchOpen` is documented as returning Open-status orders.

    That does NOT license inferring the value: converting endpoint membership
    into a field the payload never stated is the same fabrication this whole
    unit removes.
    """

    def test_a_working_order_with_status_1_is_open(self):
        from broker import topstepx_emergency_liquidation as EL
        assert EL.classify_order(dict(STOP_LEG), position_size=5) \
            == EL.PROTECTIVE_AUTHORITY

    def test_a_missing_status_is_unknown_and_blocks_the_close(self):
        from broker import topstepx_emergency_liquidation as EL
        leg = {k: v for k, v in STOP_LEG.items() if k != "status"}
        assert EL.classify_order(leg, position_size=5) == EL.UNKNOWN_AUTHORITY
        d = EL.plan(position_size=5, orders=[leg],
                    owns=lambda o: o.get("parentOrderId") == ENTRY_ID)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert d["action"] != EL.ACTION_CLOSE

    def test_status_zero_is_none_not_open(self):
        """0 is `None` in the official enum. A searchOpen row carrying it is
        self-contradictory, and contradiction is not evidence of safety."""
        from broker import topstepx_emergency_liquidation as EL
        leg = dict(STOP_LEG, status=0)
        assert EL.classify_order(leg, position_size=5) == EL.UNKNOWN_AUTHORITY
        d = EL.plan(position_size=5, orders=[leg],
                    owns=lambda o: o.get("parentOrderId") == ENTRY_ID)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert d["action"] != EL.ACTION_CLOSE

    def test_per_order_truth_does_not_grant_set_completeness(self):
        """THE DISTINCTION THAT MATTERS.

            "this visible order is positively Open"   can be proven
            "we have seen every relevant order"       cannot, from searchOpen

        A valid status:1 repairs the first. It can never upgrade an incomplete
        discovery surface into complete venue truth, because Suspended bracket
        children are omitted from that endpoint by contract.
        """
        v = FlattenVenue(positions=list(LONG), orders=[dict(STOP_LEG)])
        # ONLY the v2 query is unavailable. `query_fails` would also blind the
        # position read, which halts earlier and never exercises the fallback.
        def _no_query(*_a, **_k):
            raise TopstepXError("v2/query unavailable")
        v.query_orders = _no_query
        read = runner(v)._emergency_venue_read()
        assert read["discovery"] == "open_orders_fallback_INCOMPLETE"
        # the individual order is still classified correctly...
        from broker import topstepx_emergency_liquidation as EL
        assert EL.classify_order(dict(STOP_LEG), position_size=5) \
            == EL.PROTECTIVE_AUTHORITY
        # ...but the SET was never proven complete.
        assert "INCOMPLETE" in read["discovery"]
