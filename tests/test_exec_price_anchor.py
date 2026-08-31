"""EXEC-PRICE-ANCHOR-1 — authorized ABSOLUTE prices survive the actual fill.

Measured live on 2026-08-18 (PRAC execution smoke, BRACKETLESS=0): TopstepX
applies `stopLossBracket`/`takeProfitBracket` TICKS to the ACTUAL FILL. A
reference entry of 29591.25 with an intended stop of 29581.25 filled at 29574.25
and left the stop working at 29564.25 — 40 ticks below the fill, ten points
below the level the thesis named.

`build_bracket` promises the invalidation "becomes the stop unmodified". That
held through approval and was undone at the transport boundary, because only a
DISTANCE reaches the venue. Dollar risk survived; market truth did not.

The contract these tests pin:

    final_working_stop_price   == authorized structural invalidation
    final_working_target_price == authorized objective

subject only to the certified conservative tick rounding, and re-authorized
against the ACTUAL fill. Restoring absolute prices is exactly what makes risk
stop being invariant — holding the stop still while the fill moves changes the
distance, and therefore the money — so every production cap is re-applied here.

There is no approved bounded-drift doctrine: exact structural prices, or flat.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_execution_runner as R          # noqa: E402
from broker.topstepx_client import TopstepXContract        # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="",
                       tick_size=0.25, tick_value=0.50, active=True)

ENTRY_ORDER_ID = 9001
STOP_ORDER_ID = 9002
TARGET_ORDER_ID = 9003


class FakeSession:
    """Records modifies and flattens; never reaches a venue."""

    def __init__(self, orders, position=0):
        self._orders = [dict(o) for o in orders]
        #: SIGNED net exposure. These fixtures model POST-FILL scenarios -- an
        #: entry has just filled -- so reporting flat was fixture shorthand,
        #: not a modelled venue state. Emergency liquidation now reads the
        #: position before mutating, and a scenario that claims a fill must say
        #: what it filled: a believed-flat account is never closed "just in
        #: case", because `close_position` is itself an exposure-changing
        #: mutation.
        self.position = position
        self.modifies = []
        self.closed = []
        self.cancelled = []
        self.modify_error = None
        self.readback_override = None

    def open_orders(self):
        if self.readback_override is not None:
            return [dict(o) for o in self.readback_override]
        return [dict(o) for o in self._orders]

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the complete discovery surface.

        `searchOpen` omits Suspended bracket children by venue contract, so a
        venue without this method models the degraded fallback rather than the
        normal production path."""
        rows = self.open_orders()
        if contract_id:
            rows = [o for o in rows if o.get("contract_id") == contract_id]
        return rows

    def open_positions(self):
        if not self.position:
            return []
        return [{"contract_id": MNQ.id, "size": abs(self.position),
                 "type": 1 if self.position > 0 else 2}]

    def modify_order(self, order_id, *, size=None, limit_price=None,
                     stop_price=None, trail_price=None):
        if self.modify_error is not None:
            raise self.modify_error
        self.modifies.append({"order_id": order_id, "stop_price": stop_price,
                              "limit_price": limit_price})
        for o in self._orders:
            if o.get("id") == order_id:
                if stop_price is not None:
                    o["stop_price"] = stop_price
                if limit_price is not None:
                    o["limit_price"] = limit_price
        return {"success": True}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        self._orders = [o for o in self._orders if o.get("id") != order_id]
        if self.readback_override is not None:
            # A cancelled order stops being returned by the venue. Without this
            # the override kept re-serving cancelled children, the convergence
            # loop re-cancelled them every round, and the budget expired before
            # the position could be closed -- a fixture artefact, not behaviour.
            self.readback_override = [o for o in self.readback_override
                                      if o.get("id") != order_id]
        return {"success": True}

    def close_position(self, contract_id):
        self.closed.append(contract_id)
        self.position = 0
        return {"success": True}


def _children(fill, direction, stop_ticks=80, target_ticks=200):
    """The provisional FILL-RELATIVE bracket the venue actually creates."""
    sign = -1 if direction == "bullish" else 1
    return [
        # `status: 1` (Open) is stated, never inferred. `OrderModel.status` is
        # required by the Gateway schema; treating endpoint membership as proof
        # of the value would fabricate a field the payload never carried.
        # `status` and `side` are both REQUIRED OrderModel fields and both are
        # stated rather than inferred. Without `side` an order cannot be told
        # apart from one that would OPEN a position -- which is exactly the
        # distinction the 2026-08-26 orphan stop turned on.
        # A protective child opposes its entry: sell against a long, buy
        # against a short.
        {"id": STOP_ORDER_ID, "contract_id": MNQ.id, "type": 4, "size": 1,
         "parentOrderId": ENTRY_ORDER_ID, "status": 1,
         "side": 1 if direction == "bullish" else 0,
         "stop_price": fill + sign * stop_ticks * MNQ.tick_size},
        {"id": TARGET_ORDER_ID, "contract_id": MNQ.id, "type": 1, "size": 1,
         "parentOrderId": ENTRY_ORDER_ID, "status": 1,
         "side": 1 if direction == "bullish" else 0,
         "limit_price": fill - sign * target_ticks * MNQ.tick_size},
    ]


def _runner(direction, entry, stop, target, fill, *, orders=None, size=1):
    from broker.topstepx_combine_risk import build_bracket
    # The scenario says the entry FILLED, so the venue holds that position.
    session = FakeSession(
        orders if orders is not None else _children(fill, direction),
        position=size if direction == "bullish" else -size)
    r = R.ExecutionRunner(session=session, account_fingerprint="acct:test",
                          contract=MNQ)
    r.execution_lane = "production"
    r.order_id = ENTRY_ORDER_ID
    r.geometry = build_bracket(direction=direction, entry_price=entry,
                               invalidation_level=stop, target_price=target,
                               contract=MNQ, size=size, max_risk_usd=250.0,
                               max_stop_points=40.0, min_reward_to_risk=1.0,
                               max_contracts=15)
    r.max_risk_usd = 250.0
    r.max_stop_points = 40.0
    r.max_contracts = 15
    r.min_reward_to_risk = 1.0
    return r, session


def _fill(price, size=1):
    return {"price": price, "size": size, "contract_id": MNQ.id}


# ── the defect itself ─────────────────────────────────────────────────────────

class TestTheDefect:
    def test_venue_bracket_is_fill_relative_not_absolute(self):
        """The measured live behaviour, pinned so a regression is visible."""
        orders = _children(29574.25, "bullish", stop_ticks=40, target_ticks=80)
        assert orders[0]["stop_price"] == 29564.25
        assert orders[1]["limit_price"] == 29594.25

    def test_side_check_alone_cannot_detect_drift(self):
        """Why the old verification passed a wrong price: side is not price."""
        r, _ = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        out = r.verify_protection(r.session.open_orders())      # no fill_price
        assert out["verified"] is True                          # side-only: passes
        drifted = r.verify_protection(r.session.open_orders(),
                                      fill_price=29998.0)
        assert drifted["verified"] is False
        assert drifted["reason"] == "protection_not_on_structure"


# ── LONG deterministic matrix ─────────────────────────────────────────────────

class TestLongMatrix:
    @pytest.mark.parametrize("fill,stop_pts,reward_pts", [
        (30000.0, 20.0, 50.0),      # L0        no slippage
        (29998.0, 18.0, 52.0),      # favorable  absolutes hold, economics move
        (30002.0, 22.0, 48.0),      # adverse    absolutes hold, economics move
    ])
    def test_absolute_prices_survive_every_fill(self, fill, stop_pts, reward_pts):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, fill)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(fill), working_orders=session.open_orders())
        assert out["reanchored"] is True
        auth = out["authorization"]
        assert auth["aligned_stop_price"] == 29980.0
        assert auth["aligned_target_price"] == 30050.0
        assert auth["stop_points"] == pytest.approx(stop_pts)
        assert auth["reward_points"] == pytest.approx(reward_pts)
        # economics are recomputed against the ACTUAL fill, not candidate entry
        assert auth["risk_usd"] == pytest.approx(stop_pts / MNQ.tick_size * MNQ.tick_value)
        assert session.closed == []

    def test_no_slippage_still_re_anchors_explicitly(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30000.0), working_orders=session.open_orders())
        assert out["reanchored"] is True
        assert {m["order_id"] for m in session.modifies} == {STOP_ORDER_ID, TARGET_ORDER_ID}


# ── SHORT deterministic matrix ────────────────────────────────────────────────

class TestShortMatrix:
    @pytest.mark.parametrize("fill,stop_pts,reward_pts", [
        (30000.0, 20.0, 50.0),      # S0
        (30002.0, 18.0, 52.0),      # favorable
        (29998.0, 22.0, 48.0),      # adverse
    ])
    def test_absolute_prices_survive_every_fill(self, fill, stop_pts, reward_pts):
        r, session = _runner("bearish", 30000.0, 30020.0, 29950.0, fill)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(fill), working_orders=session.open_orders())
        assert out["reanchored"] is True
        auth = out["authorization"]
        assert auth["aligned_stop_price"] == 30020.0
        assert auth["aligned_target_price"] == 29950.0
        assert auth["stop_points"] == pytest.approx(stop_pts)
        assert auth["reward_points"] == pytest.approx(reward_pts)
        assert session.closed == []


# ── post-fill re-authorization refuses, never repairs ─────────────────────────

class TestPostFillRefusal:
    def test_adverse_fill_past_stop_ceiling_flattens(self):
        # authorized 39-point stop; a 2-point adverse fill makes it 41 > 40
        r, session = _runner("bullish", 30000.0, 29961.0, 30100.0, 30002.0)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30002.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "stop_distance_above_cap"
        assert session.closed == [MNQ.id]

    def test_adverse_fill_past_risk_cap_flattens(self):
        """Approved at the cap; ONE adverse point pushes actual risk past it.

        This is the case fill-relative anchoring could never produce, because
        preserving the distance preserves the money. Holding the structural stop
        still is what makes the dollar figure move — so the cap has to be
        re-applied against the real fill, or the repair would fix market truth
        while quietly breaking the money theorem.
        """
        # 12 MNQ x 10 pts = $240 approved (under $250); at 30001 the same
        # structural stop is 11 pts = $264.
        r, session = _runner("bullish", 30000.0, 29990.0, 30030.0, 30001.0, size=12)
        assert r.geometry.risk_usd == 240.0            # approval genuinely passed
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30001.0, size=12), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "risk_above_cap"
        assert out["authorization"]["risk_usd"] == 264.0
        assert session.closed == [MNQ.id]

    def test_adverse_fill_below_r_floor_flattens(self):
        # approved at entry 30000: 20 risk / 25 reward = 1.25R.
        # a 6-point adverse fill => 26 risk / 19 reward = 0.73R
        r, session = _runner("bullish", 30000.0, 29980.0, 30025.0, 30006.0)
        r.min_reward_to_risk = 1.0
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30006.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "reward_below_gate"
        assert session.closed == [MNQ.id]

    def test_fill_through_structural_stop_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29979.0)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29979.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "fill_crossed_structural_stop"
        assert session.closed == [MNQ.id]

    def test_fill_through_objective_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30051.0)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30051.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "fill_crossed_objective"
        assert session.closed == [MNQ.id]

    def test_unusable_fill_price_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0)
        out = r.reanchor_protection_to_structure(
            fill_event={"price": None, "size": 1}, working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "unusable_fill_price"
        assert session.closed == [MNQ.id]

    def test_quantity_above_cap_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0)
        r.max_contracts = 1
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30000.0, size=2), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["authorization"]["reason"] == "quantity_above_cap"
        assert session.closed == [MNQ.id]

    def test_refusal_never_moves_a_leg(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29979.0)
        r.reanchor_protection_to_structure(
            fill_event=_fill(29979.0), working_orders=session.open_orders())
        assert session.modifies == []


# ── child ownership must be proven, never guessed ─────────────────────────────

class TestChildOwnership:
    def test_unlinked_order_is_not_ours_and_no_longer_flattens(self):
        """THE 2026-08-26 SPECIMEN, AND THE REASON THE RESPONSE CHANGED.

        A protective child whose lineage we cannot read is EXACTLY the state
        that mission produced: `protective_order_ids` was empty, so the bot
        could not recognise its own bracket. This test used to answer that with
        a flatten -- close the position, leave the unprovable order resting.

        That is the incident. Once the position is gone the surviving order is
        an ENTRY, and 86 milliseconds later the account was LONG 15 for
        -$307.50. Ownership ambiguity and lost lineage are the same condition
        seen from two sides, and neither grants authority to create flatness
        around the order.

        The re-anchor still refuses -- `child_ownership_ambiguous` is unchanged,
        nothing is modified -- but the emergency response is now a HALT that
        keeps the position AND whatever protection is actually resting on it,
        with the operator alerted. Doing nothing is the safe answer when the
        machine cannot prove what it would be acting on.
        """
        orders = _children(30000.0, "bullish")
        orders[0].pop("parentOrderId")          # lineage gone
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0,
                             orders=orders)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30000.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == "child_ownership_ambiguous"
        assert session.modifies == []
        assert session.closed == [], "no flatness around an unprovable order"
        assert session.cancelled == [], "and no protection stripped either"
        flat = out["flattened"]
        assert flat["flattened"] is False and flat["safe_terminal"] is False
        assert flat["emergency_reason"] == "OWNERSHIP_AMBIGUOUS", flat
        assert flat["unresolved_live_exposure"] is True

    def test_duplicate_stop_children_are_ambiguous(self):
        orders = _children(30000.0, "bullish")
        twin = dict(orders[0]); twin["id"] = 9099
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0,
                             orders=orders + [twin])
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30000.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == "child_ownership_ambiguous"
        assert session.modifies == []

    def test_foreign_contract_order_is_never_touched(self):
        foreign = {"id": 7777, "contract_id": "CON.F.US.ES.U26", "type": 4,
                   "size": 1, "stop_price": 1.0}
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 30000.0,
                             orders=_children(30000.0, "bullish") + [foreign])
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(30000.0), working_orders=session.open_orders())
        assert out["reanchored"] is True
        assert 7777 not in {m["order_id"] for m in session.modifies}


# ── modify + readback failures are terminal ───────────────────────────────────

class TestModifyFailure:
    def test_stop_modify_rejected_flattens_before_touching_target(self):
        from broker.topstepx_client import TopstepXError
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        session.modify_error = TopstepXError("rejected")
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == "stop_modify_failed"
        assert session.modifies == []          # target never attempted
        assert session.closed == [MNQ.id]

    def test_stop_is_corrected_before_target(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert [m["order_id"] for m in session.modifies] == [STOP_ORDER_ID,
                                                             TARGET_ORDER_ID]

    def test_stop_readback_wrong_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        bad = _children(29998.0, "bullish")
        bad[0]["stop_price"] = 29979.0                 # venue kept a wrong price
        bad[1]["limit_price"] = 30050.0
        session.readback_override = bad
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == "stop_price_wrong"
        assert session.modifies == [{"order_id": STOP_ORDER_ID,
                                     "stop_price": 29980.0, "limit_price": None}]
        assert session.closed == [MNQ.id]

    def test_target_readback_wrong_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        bad = _children(29998.0, "bullish")
        bad[0]["stop_price"] = 29980.0
        bad[1]["limit_price"] = 30049.0                # off by four ticks
        session.readback_override = bad
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == "target_price_wrong"
        assert session.closed == [MNQ.id]

    def test_child_disappearing_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        session.readback_override = [_children(29998.0, "bullish")[0]]
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert session.closed == [MNQ.id]

    def test_wrong_child_quantity_flattens(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        bad = _children(29998.0, "bullish")
        bad[0]["stop_price"] = 29980.0
        bad[1]["limit_price"] = 30050.0
        bad[0]["size"] = 2                              # not the filled quantity
        session.readback_override = bad
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(29998.0), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert session.closed == [MNQ.id]


# ── final verification theorem ────────────────────────────────────────────────

class TestVerificationTheorem:
    def test_fill_relative_stop_fails_verification(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        out = r.verify_protection(session.open_orders(), fill_price=29998.0)
        assert out["verified"] is False
        assert "authorized structure is 29980.0" in out["detail"]

    def test_fill_relative_target_fails_verification(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        fixed = _children(29998.0, "bullish")
        fixed[0]["stop_price"] = 29980.0                # stop right, target not
        out = r.verify_protection(fixed, fill_price=29998.0)
        assert out["verified"] is False
        assert "authorized objective is 30050.0" in out["detail"]

    def test_exact_absolute_prices_verify(self):
        r, session = _runner("bullish", 30000.0, 29980.0, 30050.0, 29998.0)
        good = _children(29998.0, "bullish")
        good[0]["stop_price"] = 29980.0
        good[1]["limit_price"] = 30050.0
        out = r.verify_protection(good, fill_price=29998.0)
        assert out["verified"] is True
        assert out["anchored_to_structure"] is True
        assert r.state == R.PROTECTED
        assert session.closed == []


# ── production reachability ───────────────────────────────────────────────────

# ── the prompt post-fill lifecycle ────────────────────────────────────────────

class FillSession(FakeSession):
    """Adds trade/position observation so the full-fill theorem can be driven."""

    def __init__(self, orders, trade_batches, positions=None):
        super().__init__(orders)
        self._batches = list(trade_batches)     # one list per poll
        self._positions = positions
        self.trade_polls = 0

    def recent_trades(self):
        batch = self._batches[min(self.trade_polls, len(self._batches) - 1)]
        self.trade_polls += 1
        return list(batch)

    def open_positions(self):
        # A closed position STAYS closed -- otherwise the bounded recovery loop
        # keeps seeing exposure it already flattened and retries every pass.
        if self.closed:
            return []
        if self._positions is not None:
            return list(self._positions)
        batch = self._batches[min(max(self.trade_polls - 1, 0), len(self._batches) - 1)]
        # Attribute by parent order, exactly as the runner does; a stranger's
        # fill is not this position.
        qty = sum(int(t.get("size") or 0) for t in batch
                  if str(t.get("orderId")) == str(ENTRY_ORDER_ID))
        return [{"contract_id": MNQ.id, "size": qty}] if qty else []


def _trade(price, size, tid=1):
    return {"id": tid, "orderId": ENTRY_ORDER_ID, "price": price, "size": size}


def _fill_runner(fill, *, batches, positions=None, size=1, orders=None,
                 stop=29980.0, target=30050.0):
    from broker.topstepx_combine_risk import build_bracket
    session = FillSession(orders if orders is not None else _children(fill, "bullish"),
                          batches, positions=positions)
    r = R.ExecutionRunner(session=session, account_fingerprint="acct:test", contract=MNQ)
    r.execution_lane = "production"
    r.order_id = ENTRY_ORDER_ID
    r.geometry = build_bracket(direction="bullish", entry_price=30000.0,
                               invalidation_level=stop, target_price=target,
                               contract=MNQ, size=size, max_risk_usd=250.0,
                               max_stop_points=40.0, min_reward_to_risk=1.0,
                               max_contracts=15)
    r.max_risk_usd, r.max_stop_points = 250.0, 40.0
    r.max_contracts, r.min_reward_to_risk = 15, 1.0
    r.prompt_fill_authority = True
    return r, session


class TestFullFillAuthority:
    def test_single_fill_establishes_protection(self):
        r, session = _fill_runner(30000.0, batches=[[_trade(30000.0, 1)]])
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["established"] is True
        assert out["fill"]["fill_price"] == 30000.0
        assert out["anchor"]["moved"] == {"stop": 29980.0, "target": 30050.0}

    def test_multiple_fills_use_the_weighted_average(self):
        # 5 @ 30000 and 7 @ 30001  ->  vwap 30000.5833...
        r, session = _fill_runner(
            30000.0, size=12,
            batches=[[_trade(30000.0, 5, 1), _trade(30001.0, 7, 2)]],
            positions=[{"contract_id": MNQ.id, "size": 12}],
            orders=_children(30000.0, "bullish"),
            stop=29996.0, target=30012.0)      # 4 pts x 12 = $96, well under $250
        for o in session._orders:
            o["size"] = 12
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["fill"]["fill_count"] == 2
        assert out["fill"]["fill_price"] == pytest.approx((30000.0 * 5 + 30001.0 * 7) / 12)
        # An off-grid VWAP fill must NOT drag the authorized levels off their
        # exact prices -- this is the case that proves the grid snap is applied
        # to the LEVEL, not reconstructed from a distance off the fill.
        assert out["anchor"]["moved"] == {"stop": 29996.0, "target": 30012.0}

    def test_first_fill_alone_does_not_re_anchor(self):
        r, session = _fill_runner(
            30000.0, size=2,
            batches=[[_trade(30000.0, 1)], [_trade(30000.0, 1), _trade(30002.0, 1, 2)]],
            positions=[{"contract_id": MNQ.id, "size": 2}])
        for o in session._orders:
            o["size"] = 2
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert session.trade_polls >= 2          # it waited for the rest
        assert out["fill"]["size"] == 2
        assert out["established"] is True

    def test_partial_fill_at_deadline_fails_closed(self):
        r, session = _fill_runner(30000.0, size=2, batches=[[_trade(30000.0, 1)]],
                                  positions=[{"contract_id": MNQ.id, "size": 1}])
        r._elapsed = _ticking_elapsed(0.4)
        out = r.establish_structural_protection(deadline_seconds=1.0, sleep=lambda s: None)
        assert out["established"] is False
        assert out["reason"] == "partial_fill_at_deadline"
        assert session.modifies == []
        assert MNQ.id in session.closed          # bounded loop may act >once
        assert out["recovery"]["safe"] is True

    def test_no_fill_by_deadline_fails_closed_without_resubmitting(self):
        r, session = _fill_runner(30000.0, batches=[[]])
        r._elapsed = _ticking_elapsed(0.4)
        out = r.establish_structural_protection(deadline_seconds=1.0, sleep=lambda s: None)
        assert out["established"] is False
        assert out["reason"] == "no_fill_observed"
        assert session.modifies == []

    def test_overfill_fails_closed(self):
        r, session = _fill_runner(30000.0, batches=[[_trade(30000.0, 3)]])
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["established"] is False
        assert out["reason"] == "overfill"
        assert MNQ.id in session.closed

    def test_position_quantity_disagreement_fails_closed(self):
        r, session = _fill_runner(30000.0, batches=[[_trade(30000.0, 1)]],
                                  positions=[{"contract_id": MNQ.id, "size": 3}])
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["established"] is False
        assert out["reason"] == "position_quantity_disagrees"
        assert session.modifies == []
        assert MNQ.id in session.closed

    def test_foreign_order_fills_are_never_attributed(self):
        stranger = {"id": 5, "orderId": 424242, "price": 1.0, "size": 9}
        r, session = _fill_runner(30000.0, batches=[[stranger, _trade(30000.0, 1)]])
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["fill"]["size"] == 1
        assert out["established"] is True


def _ticking_elapsed(step_seconds=0.4):
    """A monotonic WALL-CLOCK stand-in for bounded-wait tests.

    Deliberately not the business clock: production pins `clock` to a frozen
    NOW in its harness, and a deadline measured on a frozen clock never expires.
    """
    state = {"t": 0.0}

    def elapsed():
        state["t"] += step_seconds
        return state["t"]
    return elapsed


def _advancing_clock(step_seconds=10.0):
    """A MONOTONIC fake clock, so a bounded wait actually expires.

    An earlier version jumped once and then returned a constant, which made
    `elapsed` permanently zero and hung the poll loop forever. A deadline test
    whose clock does not advance is not testing a deadline.
    """
    from datetime import datetime, timedelta, timezone
    state = {"n": 0}

    def clock():
        state["n"] += 1
        return datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc) + timedelta(
            seconds=state["n"] * step_seconds)
    return clock


class TestStopFirstThenProveThenTarget:
    def test_stop_is_proven_before_target_is_modified(self):
        r, session = _fill_runner(29998.0, batches=[[_trade(29998.0, 1)]])
        calls = []
        real = session.modify_order

        def spy(order_id, **kw):
            calls.append(("modify", order_id))
            return real(order_id, **kw)
        session.modify_order = spy
        real_orders = session.open_orders

        def watched():
            calls.append(("readback", None))
            return real_orders()
        session.open_orders = watched
        r.establish_structural_protection(sleep=lambda s: None)
        i_stop = calls.index(("modify", STOP_ORDER_ID))
        i_tgt = calls.index(("modify", TARGET_ORDER_ID))
        readbacks = [i for i, c in enumerate(calls) if c == ("readback", None)]
        assert i_stop < i_tgt                          # stop is corrected first
        assert any(i_stop < i < i_tgt for i in readbacks)   # and PROVEN between

    def test_stop_modify_success_with_wrong_readback_never_touches_target(self):
        r, session = _fill_runner(29998.0, batches=[[_trade(29998.0, 1)]])

        def lying_modify(order_id, **kw):
            session.modifies.append({"order_id": order_id, **kw})
            return {"success": True}          # accepted, but nothing moves
        session.modify_order = lying_modify
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["established"] is False
        assert out["anchor"]["reason"] == "stop_price_wrong"
        assert [m["order_id"] for m in session.modifies] == [STOP_ORDER_ID]
        assert session.closed == [MNQ.id]

    def test_stop_modify_unknown_response_never_touches_target(self):
        from broker.topstepx_client import TopstepXError
        r, session = _fill_runner(29998.0, batches=[[_trade(29998.0, 1)]])
        session.modify_error = TopstepXError("timeout")
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["anchor"]["reason"] == "stop_modify_failed"
        assert session.modifies == []
        assert session.closed == [MNQ.id]

    def test_exact_child_ids_are_carried_through_both_modifications(self):
        r, session = _fill_runner(29998.0, batches=[[_trade(29998.0, 1)]])
        out = r.establish_structural_protection(sleep=lambda s: None)
        assert out["anchor"]["child_ids"] == {"stop": STOP_ORDER_ID,
                                              "target": TARGET_ORDER_ID}
        assert out["anchor"]["proofs"]["stop"]["order_id"] == STOP_ORDER_ID
        assert out["anchor"]["proofs"]["target"]["order_id"] == TARGET_ORDER_ID

    def test_a_same_contract_stranger_is_never_modified(self):
        stranger = {"id": 4242, "contract_id": MNQ.id, "type": 4, "size": 1,
                    "stop_price": 1.0}
        r, session = _fill_runner(29998.0, batches=[[_trade(29998.0, 1)]],
                                  orders=_children(29998.0, "bullish") + [stranger])
        r.establish_structural_protection(sleep=lambda s: None)
        assert 4242 not in {m["order_id"] for m in session.modifies}


# ── production reachability ───────────────────────────────────────────────────

class TestProductionReachability:
    """The prompt hook must be on the real submit transaction, and ONLY there."""

    @staticmethod
    def _calls(fn):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(fn).lstrip())
        return {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def test_gated_submit_runs_the_prompt_lifecycle(self):
        assert "self.establish_structural_protection" in self._calls(
            R.ExecutionRunner.gated_submit)

    def test_production_enables_prompt_fill_authority(self):
        """The obvious failure mode is production forgetting to turn it on."""
        import ast
        import inspect
        from broker import topstepx_production_session as PS
        src = inspect.getsource(PS.ProductionSession.build_runner)
        tree = ast.parse(src.lstrip())
        assigned = {ast.unparse(t) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) for t in n.targets}
        assert "runner.prompt_fill_authority" in assigned

    def test_it_is_off_by_default_so_smoke_and_gating_tests_keep_their_meaning(self):
        r = R.ExecutionRunner(session=FakeSession([]), account_fingerprint="a",
                              contract=MNQ)
        assert r.prompt_fill_authority is False

    def test_the_scan_tick_reconciler_is_not_the_owner(self):
        from broker import topstepx_production_loop as PL
        called = self._calls(PL.ProductionLoop.reconcile_missions)
        assert not any("reanchor" in c or "establish_structural_protection" in c
                       for c in called)

    def test_reconcile_entry_remains_measurement_only(self):
        from broker import topstepx_production_session as PS
        called = self._calls(PS.ProductionSession.reconcile_entry)
        assert not any("reanchor" in c or "establish_structural_protection" in c
                       or "modify_order" in c for c in called)

    def test_live_session_exposes_modify_order(self):
        from broker.topstepx_live_session import WRITE_PATHS, TopstepXLiveSession
        assert hasattr(TopstepXLiveSession, "modify_order")
        assert "/api/Order/modify" in WRITE_PATHS


# ── late-fill resurrection ────────────────────────────────────────────────────

class ResurrectionSession(FakeSession):
    """A venue where the PARENT can still fill after recovery has begun.

    Models the P0 the ordering fix exists for: close the filled part first and
    the unfilled remainder can come back from the dead.
    """

    def __init__(self, *, parent_working=True, position_qty=0, children=None,
                 fill_on_cancel=0, cancel_parent_fails=False,
                 cancel_parent_silently_ignored=False):
        super().__init__(children or [])
        self.parent_working = parent_working
        self.position_qty = position_qty
        self.fill_on_cancel = fill_on_cancel      # qty that races the cancel
        self.cancel_parent_fails = cancel_parent_fails
        self.cancel_parent_silently_ignored = cancel_parent_silently_ignored
        self.order_of_calls = []

    def open_orders(self):
        rows = [dict(o) for o in self._orders]
        if self.parent_working:
            # PRODUCTION SHAPE. `status` and `side` are REQUIRED on OrderModel,
            # and their absence is not neutral: the certified planner reads an
            # order with no side as UNKNOWN authority and refuses to act around
            # it. This row is the working remainder of a BULLISH entry, so it is
            # a BUY (side 0) that can still add exposure.
            rows.append({"id": ENTRY_ORDER_ID, "contract_id": MNQ.id, "type": 2,
                         "size": 12, "status": 1, "side": 0})
        return rows

    def open_positions(self):
        # A position row carries its DIRECTION. `type` 1 is long, 2 is short --
        # the planner sizes and sides the close from it, and a row without one
        # is a fixture asserting a venue shape that does not exist.
        return ([{"contract_id": MNQ.id, "size": self.position_qty, "type": 1}]
                if self.position_qty else [])

    def recent_trades(self):
        return []

    def cancel_order(self, order_id):
        self.order_of_calls.append(("cancel", order_id))
        if str(order_id) == str(ENTRY_ORDER_ID):
            if self.cancel_parent_fails:
                from broker.topstepx_client import TopstepXError
                raise TopstepXError("cancel rejected")
            if self.fill_on_cancel:               # the race: it filled first
                self.position_qty += self.fill_on_cancel
                self.fill_on_cancel = 0
            if not self.cancel_parent_silently_ignored:
                self.parent_working = False
            return {"success": True}
        self.cancelled.append(order_id)
        self._orders = [o for o in self._orders if o.get("id") != order_id]
        return {"success": True}

    def close_position(self, contract_id):
        self.order_of_calls.append(("close", contract_id))
        self.closed.append(contract_id)
        self.position_qty = 0
        return {"success": True}


def _abandon_runner(session, size=12):
    from broker.topstepx_combine_risk import build_bracket
    r = R.ExecutionRunner(session=session, account_fingerprint="acct:test", contract=MNQ)
    r.execution_lane = "production"
    r.order_id = ENTRY_ORDER_ID
    r.geometry = build_bracket(direction="bullish", entry_price=30000.0,
                               invalidation_level=29996.0, target_price=30012.0,
                               contract=MNQ, size=size, max_risk_usd=250.0,
                               max_stop_points=40.0, min_reward_to_risk=1.0,
                               max_contracts=15)
    r.max_risk_usd, r.max_stop_points = 250.0, 40.0
    r.max_contracts, r.min_reward_to_risk = 15, 1.0
    r.prompt_fill_authority = True
    return r


class TestLateFillResurrection:
    """LATE-FILL RESURRECTION, now served by the ONE convergence authority.

    Every behavioural expectation in this class survived the delegation
    unchanged -- parent cancelled before the close, races discovered, a 2xx
    never accepted as proof, unreadable venues never claiming safety. Only the
    two tests that inspected the LOCAL sequence had to move, because that
    sequence is gone.
    """

    def test_parent_is_cancelled_BEFORE_the_position_is_closed(self):
        """The whole point: stop new exposure first, then flatten what exists."""
        s = ResurrectionSession(parent_working=True, position_qty=5)
        out = _abandon_runner(s).abandon_unfilled_entry("partial fill")
        assert out["safe"] is True
        kinds = [k for k, _ in s.order_of_calls]
        assert kinds.index("cancel") < kinds.index("close")

    def test_partial_fill_leaves_parent_terminal_position_zero_no_orders(self):
        s = ResurrectionSession(parent_working=True, position_qty=5,
                                children=_children(30000.0, "bullish"))
        out = _abandon_runner(s).abandon_unfilled_entry("5/12 at deadline")
        assert out["safe"] is True
        assert out["final_state"]["parent_working"] is False
        assert out["final_state"]["position_quantity"] == 0
        assert out["final_state"]["mission_orders"] == []

    def test_a_fill_racing_the_cancel_is_discovered_and_flattened(self):
        s = ResurrectionSession(parent_working=True, position_qty=5, fill_on_cancel=7)
        out = _abandon_runner(s).abandon_unfilled_entry("cancel/fill race")
        assert out["safe"] is True
        assert s.position_qty == 0
        assert s.closed == [MNQ.id]

    def test_no_fill_record_but_a_position_exists_is_still_flattened(self):
        """A trades read of [] does not prove no position exists."""
        s = ResurrectionSession(parent_working=False, position_qty=3)
        out = _abandon_runner(s).abandon_unfilled_entry("no_fill_observed")
        assert out["safe"] is True
        assert s.closed == [MNQ.id]

    def test_no_fill_record_and_parent_still_working_cancels_the_parent(self):
        s = ResurrectionSession(parent_working=True, position_qty=0)
        out = _abandon_runner(s).abandon_unfilled_entry("no_fill_observed")
        assert out["safe"] is True
        assert ("cancel", ENTRY_ORDER_ID) in s.order_of_calls

    def test_cancel_reports_success_but_parent_still_working_is_not_safe(self):
        s = ResurrectionSession(parent_working=True, position_qty=0,
                                cancel_parent_silently_ignored=True)
        r = _abandon_runner(s)
        out = r.abandon_unfilled_entry("silent cancel")
        assert out["safe"] is False          # a 2xx is not proof
        assert out["final_state"]["parent_working"] is True
        assert r.state == R.RESIDUAL_ORDERS

    def test_cancel_failure_is_bounded_and_never_claims_safety(self):
        s = ResurrectionSession(parent_working=True, position_qty=5,
                                cancel_parent_fails=True)
        out = _abandon_runner(s).abandon_unfilled_entry("cancel rejected")
        assert out["safe"] is False
        assert any(st["step"] == "cancel_parent" and st["ok"] is False
                   for st in out["steps"])

    def test_unreadable_venue_never_claims_safety(self):
        class Blind(ResurrectionSession):
            def open_orders(self):
                raise RuntimeError("venue unreadable")
        out = _abandon_runner(Blind()).abandon_unfilled_entry("blind")
        assert out["safe"] is False
        assert out["final_state"]["readable"] is False

    def test_a_foreign_same_contract_order_blocks_the_close_and_is_never_cancelled(self):
        """THE EXPECTATION CHANGED, DELIBERATELY.

        This used to assert `safe is True`: leave the foreign order alone, close
        our position, call the recovery clean. `TOPSTEP-UNPROVEN-ORDER-CLOSE-
        AUTHORITY-1` forbids exactly that -- an executable order whose authority
        is unproven may not be mutated around by creating or changing flatness.

        Closing here would change what that resting order MEANS. It opposed a
        position; once the position is gone it is an entry. And we do not know
        whose it is: on 2026-08-26 this same shape was OUR OWN bracket with its
        lineage lost, and closing around it is what turned -$210.00 into an
        additional -$307.50.

        What is preserved: it is still never cancelled -- cancelling requires
        proof we do not have. What changed is that we no longer claim a clean
        recovery we could not make.
        """
        foreign = {"id": 5150, "contract_id": MNQ.id, "type": 4, "size": 1,
                   "stop_price": 1.0, "status": 1, "side": 0}
        s = ResurrectionSession(parent_working=True, position_qty=5,
                                children=[foreign])
        out = _abandon_runner(s).abandon_unfilled_entry("partial")
        assert 5150 not in [oid for kind, oid in s.order_of_calls if kind == "cancel"]
        assert 5150 not in s.cancelled
        assert out["safe"] is False, "an unattributed order is not a clean recovery"
        halt = [st for st in out["steps"] if st.get("halted")]
        assert halt and halt[0]["reason"] == "OWNERSHIP_AMBIGUOUS", out["steps"]


    def test_a_race_from_zero_is_discovered_and_closed_not_deferred(self):
        """The case a stale pre-cancel reading alone would miss.

        Position is 0 when recovery begins, so a close gated on that reading is
        skipped entirely and the 7 that fill during the cancel survive. The
        certified planner re-reads the position after every mutation, so the
        exposure the cancel CREATED is closed by the convergence that created
        it -- never deferred to some later attempt.

        THE ASSERTION MOVED FROM PASS-NUMBERING TO BEHAVIOUR. `steps` no longer
        carries a `pass` key because the convergence rounds are the planner's,
        not this method's. What mattered was never the numbering: it was that
        the raced fill does not survive the recovery.
        """
        s = ResurrectionSession(parent_working=True, position_qty=0, fill_on_cancel=7)
        r = _abandon_runner(s)
        out = r.abandon_unfilled_entry("race from flat")
        assert out["safe"] is True
        assert any(st["step"] == "close_position" and st["ok"]
                   for st in out["steps"]), "the raced fill was never flattened"
        assert s.position_qty == 0
        assert s.closed == [MNQ.id]

    def test_the_recovery_performs_no_venue_mutation_of_its_own(self):
        """SOURCE, TEST and CLAIM must describe the same ordering -- and the
        ordering no longer lives here.

        This test used to read `abandon_unfilled_entry` for a cancel, a re-read
        and a close in that order. That local sequence was the SECOND
        liquidation implementation in this class, and it defended only against
        the failure its author had seen: it stopped the PARENT from creating new
        exposure before the close, but left the protective CHILDREN executable
        across it -- the exact ordering ATOMICITY-1 removed from
        `emergency_flatten` after a surviving stop reversed a flat account.

        The invariant is unchanged; its home is. It is now asserted against the
        certified planner in
        `tests/test_topstepx_unproven_order_close_authority.py`, and what this
        method must prove is the negative: that it mutates nothing itself.
        """
        import ast
        import inspect
        body = ast.unparse(ast.parse(
            inspect.getsource(R.ExecutionRunner.abandon_unfilled_entry).lstrip()))
        for forbidden in ("self.session.cancel_order", "self.session.close_position",
                          "self.session.place_order", "self.session.modify_order"):
            assert forbidden not in body, f"{forbidden} is a second mutation authority"
        assert "self.emergency_flatten(" in body, "convergence must be delegated"
        assert "self.entry_exposure_state(" in body, "the abandonment still proves itself"

    def test_the_prompt_lifecycle_routes_failures_through_the_safe_path(self):
        """A partial fill must NOT reach the old close-first emergency_flatten."""
        import ast
        import inspect
        src = inspect.getsource(R.ExecutionRunner.establish_structural_protection)
        called = {ast.unparse(n.func) for n in ast.walk(ast.parse(src.lstrip()))
                  if isinstance(n, ast.Call)}
        assert "self.abandon_unfilled_entry" in called
        assert "self.emergency_flatten" not in called


class TestDeadlinePropagation:
    def test_a_production_session_hands_its_deadline_to_the_runner(self):
        import ast
        import inspect
        from broker import topstepx_production_session as PS
        tree = ast.parse(inspect.getsource(PS.ProductionSession.build_runner).lstrip())
        pairs = {(ast.unparse(t), ast.unparse(n.value))
                 for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets}
        assert ("runner.fill_deadline_seconds", "self.fill_deadline_seconds") in pairs

    def test_the_production_default_is_unchanged(self):
        assert R.FILL_DEADLINE_SECONDS == 30.0
        assert R.ExecutionRunner.fill_deadline_seconds == 30.0
