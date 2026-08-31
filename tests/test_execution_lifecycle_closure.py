"""The lifecycle V13 could not complete: ACK -> fill -> protect -> exit -> flat.

THE DEFECT. On 2026-08-11 PROD-20260811-V13 submitted 15 MNQ short, Topstep
acknowledged order 3391019204, the position filled and stopped out for -$138.30
and the account returned flat -- while the durable mission still read
ATTEMPT_CONSUMED / order_id=null / token_spent=false. `ATTEMPT_CONSUMED` is not
terminal, so `active_mission` wedged and the session's second authorized trade
became permanently unreachable.

Three separate holes, each of which alone would have caused it:

  1. `MissionState` had no method that could write `order_id` on a SUCCESSFUL
     path. The only assignment lived in `venue_rejected_zero_fill`.
  2. `token_spent` was never assigned True anywhere in src/.
  3. `reconcile_after_fill` / `reconcile_after_exit` -- including the only
     `COMPLETE` transition in the codebase -- had NO production caller. Their
     only callers were in tests/test_production_scan_loop.py.

WHY THESE TESTS LOOK THE WAY THEY DO. Hole 3 existed *underneath a passing test
suite*, because the tests called the reconcilers directly and production never
did. So nothing here calls a transition helper by hand to manufacture progress.
Every mission below advances only by `loop.scan_once()` observing a venue
double, which is the same path production takes. A test that hand-walks the
ladder proves the ladder exists, not that anything climbs it.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from broker import topstepx_mission_state as MS                     # noqa: E402
from broker import topstepx_mission_recovery as RECOVERY            # noqa: E402
from broker import topstepx_submission_record as SUBREC             # noqa: E402
from broker import topstepx_session_authorization as SA             # noqa: E402

# The SAME orchestration harness production tests use. Importing it rather than
# rebuilding it is the point: a private harness could drift into proving
# something production does not do.
from test_production_scan_loop import (                             # noqa: E402
    CID, FP, MNQ, NOW, Session, build, authorization)

#: The live venue id, kept verbatim so the regression is recognisable.
V13_ORDER_ID = 3391019204


class VenueDouble(Session):
    """A venue that MOVES. Positions, orders and trades change underneath the
    loop exactly as Topstep's would, and the loop must notice by asking."""

    #: The approved entry price this harness's candidate actually resolves to.
    #: A market fill has to land somewhere the authorized structure still makes
    #: sense -- filling past the objective is a legitimate REFUSAL, not a
    #: successful execution, so a completed-execution test must fill near here.
    HARNESS_ENTRY_PRICE = 29880.0

    def __init__(self, order_id=V13_ORDER_ID, fill_on_place=False,
                 fill_price=None):
        """`fill_on_place` models what a MARKET order actually does.

        EXEC-PRICE-ANCHOR-1 (2026-08-18). The DEFAULT IS UNCHANGED and is now a
        deliberate test condition rather than an oversight: it acknowledges and
        fills LATER, exercising "venue acknowledged, no authoritative fill
        observable", which the prompt post-fill lifecycle must refuse rather
        than call a successful entry. Tests whose subject is a COMPLETED market
        execution opt in, so neither scenario is destroyed to satisfy the other.
        """
        super().__init__(place=self._on_place)
        self.order_id = order_id
        self.fill_on_place = fill_on_place
        self.fill_price = (self.HARNESS_ENTRY_PRICE if fill_price is None
                           else float(fill_price))
        self._trades = []
        self.modifies = []
        self.read_counts = {"positions": 0, "orders": 0, "trades": 0}

    def _on_place(self, payload):
        if self.fill_on_place:
            size = int(payload.get("size") or 1)
            px = self.fill_price
            tick = MNQ.tick_size
            stop_ticks = (payload.get("stopLossBracket") or {}).get("ticks") or 0
            tgt_ticks = (payload.get("takeProfitBracket") or {}).get("ticks") or 0
            # MISSION-RECONCILIATION-VENUE-TRUTH-1: these are now EXACTLY the
            # shapes `TopstepXClient.open_positions()` / `open_orders()` build.
            # They used to carry `contractId` / `averagePrice` / `parentOrderId`,
            # which the normalised client never emits -- so the reconciler's
            # selectors were dead in production while this file stayed green.
            self._p = [{"id": 830000001, "contract_id": CID, "side": "long",
                        "size": abs(size), "avg_price": px,
                        "opened_at": "2026-08-25T14:49:20.296104+00:00"}]
            # Protection derived from the ACTUAL FILL -- the measured venue
            # behaviour this whole unit exists to correct.
            self._o = [
                {"id": 901, "contract_id": CID, "status": 1, "type": 4,
                 "side": 1, "size": size, "limit_price": None,
                 "parent_order_id": self.order_id,
                 "stop_price": px + stop_ticks * tick},
                {"id": 902, "contract_id": CID, "status": 1, "type": 1,
                 "side": 1, "size": size, "stop_price": None,
                 "parent_order_id": self.order_id,
                 "limit_price": px + tgt_ticks * tick},
            ]
            self._trades.append({"orderId": self.order_id, "price": px, "size": size})
        return {"orderId": self.order_id, "order_id": self.order_id,
                "success": True, "errorCode": 0}

    def modify_order(self, order_id, *, size=None, limit_price=None,
                     stop_price=None, trail_price=None):
        self.modifies.append({"order_id": order_id, "stop_price": stop_price,
                              "limit_price": limit_price})
        for o in self._o:
            if o.get("id") == order_id:
                if stop_price is not None:
                    o["stop_price"] = stop_price
                if limit_price is not None:
                    o["limit_price"] = limit_price
        return {"success": True}

    # ── what the loop is allowed to ask ──────────────────────────────────────
    def open_positions(self):
        self.read_counts["positions"] += 1
        return list(self._p)

    def open_orders(self):
        self.read_counts["orders"] += 1
        return list(self._o)

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        Production reads this, not `searchOpen`, because `searchOpen` omits
        Suspended bracket children by venue contract. A fixture without this
        method models the degraded fallback, where absence can never be proven.
        No status filter is applied, matching production.
        """
        self.read_counts["orders"] += 1
        rows = list(self._o)
        if contract_id:
            rows = [o for o in rows
                    if (o.get("contract_id") or o.get("contractId")) == contract_id]
        return rows

    def recent_trades(self, since=None):
        self.read_counts["trades"] += 1
        return list(self._trades)

    # ── what the market does to it ───────────────────────────────────────────
    def fill(self, *, size, price, tag):
        self._p = [{"id": 830000002, "contract_id": CID, "side": "short",
                    "size": -abs(size), "avg_price": price,
                    "opened_at": "2026-08-25T14:49:20.296104+00:00"}]
        # Ownership is the venue's own parent/child relationship, not a tag the
        # normalised order contract does not publish.
        self._o = [{"id": 901, "contract_id": CID, "status": 1, "type": 4,
                    "side": 1, "size": abs(size),
                    "parent_order_id": self.order_id, "stop_price": price},
                   {"id": 902, "contract_id": CID, "status": 1, "type": 1,
                    "side": 1, "size": abs(size),
                    "parent_order_id": self.order_id, "limit_price": price}]
        self._trades.append({"orderId": self.order_id, "price": price,
                             "size": abs(size)})
        return self

    def stop_out(self, *, size, price):
        self._p, self._o = [], []
        self._trades.append({"orderId": 901, "price": price, "size": abs(size)})
        return self


def armed_scan(tmp_path, venue=None):
    """One armed scan through the real orchestration: submit + venue ack."""
    venue = venue or VenueDouble()
    loop, ps, sess, mission = build(tmp_path, armed=True, session=venue)
    out = loop.scan_once()
    return loop, ps, venue, mission, out


def the_mission(mission):
    mission.load_existing()
    return mission.trade_missions[0]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheAcknowledgementIsDurable:
    """Hole 1 and 2: the venue answered and the mission could not write it down."""

    def test_the_venue_order_id_lands_on_the_mission(self, tmp_path):
        """V13 REGRESSION: the id reached the flight recorder and stopped there.

        The invariant is the DURABLE MISSION RECORD, not the outcome string. The
        outcome guard needs a venue that actually completes a market execution:
        under EXEC-PRICE-ANCHOR-1 an entry is not established at ACK, so the
        delayed-fill default now correctly reports SUBMIT_FAILED. That scenario
        is preserved and asserted directly in `TestAckAloneIsNotAnEntry`.
        """
        _, _, _, mission, out = armed_scan(tmp_path,
                                           venue=VenueDouble(fill_on_place=True))
        assert out["outcome"] == "SUBMITTED", out
        m = the_mission(mission)
        assert str(m.order_id) == str(V13_ORDER_ID), \
            "the venue order id never reached the durable mission record"

    def test_acknowledged_but_unobservable_fill_is_not_a_successful_entry(self, tmp_path):
        """EXEC-PRICE-ANCHOR-1: ACK != FILL != FULL FILL != STRUCTURAL PROTECTION.

        Its own theorem so the delayed-fill venue is never quietly retired. A
        market order the venue acknowledged, whose fill cannot be authoritatively
        observed inside the deadline, must NOT be reported as a successful entry:
        the working stop and target are still tick offsets nobody authorized.
        """
        _, _, _, _, out = armed_scan(tmp_path)          # delayed-fill default
        assert out["outcome"] != "SUBMITTED", out

    def test_failing_closed_still_records_the_order_id(self, tmp_path):
        """Refusing the entry may not cost the durable record -- that WAS V13."""
        _, _, _, mission, _ = armed_scan(tmp_path)      # delayed-fill default
        assert str(the_mission(mission).order_id) == str(V13_ORDER_ID)

    def test_the_execution_token_is_marked_spent(self, tmp_path):
        _, _, _, mission, _ = armed_scan(tmp_path)
        assert the_mission(mission).token_spent is True

    def test_the_mission_leaves_ATTEMPT_CONSUMED(self, tmp_path):
        _, _, _, mission, _ = armed_scan(tmp_path)
        assert the_mission(mission).state == MS.VENUE_ACKNOWLEDGED

    def test_the_exact_V13_shape_is_now_unreachable(self, tmp_path):
        """order_id=null + token_spent=false + ATTEMPT_CONSUMED, after an ack."""
        _, _, _, mission, _ = armed_scan(tmp_path)
        m = the_mission(mission)
        assert not (m.order_id is None and m.token_spent is False
                    and m.state == MS.ATTEMPT_CONSUMED)

    def test_it_is_durable_on_disk_not_only_in_memory(self, tmp_path):
        _, _, _, mission, _ = armed_scan(tmp_path)
        reread = MS.load(mission.mission_path(1))
        assert str(reread.order_id) == str(V13_ORDER_ID)
        assert reread.token_spent is True
        assert reread.state == MS.VENUE_ACKNOWLEDGED

    def test_provenance_is_carried_on_the_mission(self, tmp_path):
        _, _, _, mission, _ = armed_scan(tmp_path)
        m = the_mission(mission)
        assert m.session_id == mission.authorization.session_id
        assert m.authorization_fingerprint == mission.authorization.fingerprint()
        assert m.acknowledged_at


class TestTheLifecycleClosesByObservation:
    """Hole 3: nothing in production ever watched the venue."""

    def flow(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag = ps.runner.submission_custom_tag
        size = ps.runner.geometry.size
        return loop, ps, venue, mission, tag, size

    def test_a_fill_becomes_POSITION_OPEN_without_being_told(self, tmp_path):
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        m = the_mission(mission)
        assert m.state == MS.POSITION_OPEN
        assert m.filled_quantity == size
        assert m.position_state == "open"

    def test_protective_orders_are_recorded(self, tmp_path):
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        assert set(the_mission(mission).protective_order_ids) == {901, 902}

    def test_the_stop_out_terminalizes_the_mission(self, tmp_path):
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()
        m = the_mission(mission)
        assert m.state == MS.COMPLETE
        assert m.state in MS.TERMINAL_STATES
        assert m.flat_confirmed_at

    def test_the_whole_trade_inside_ONE_tick_still_closes(self, tmp_path):
        """V13's trade was born and stopped out inside a single 60s interval."""
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()
        m = the_mission(mission)
        assert m.state == MS.COMPLETE
        walked = [h["to"] for h in m.history]
        for rung in (MS.ATTEMPT_CONSUMED, MS.VENUE_ACKNOWLEDGED, MS.POSITION_OPEN,
                     MS.EXIT_PENDING_RECONCILIATION, MS.COMPLETE):
            assert rung in walked, f"{rung} missing from history: {walked}"

    def test_reconciliation_runs_on_the_ordinary_scan_path(self, tmp_path):
        """Not just when called by hand -- scan_once must do it."""
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        venue.stop_out(size=size, price=29785.0)
        loop.scan_once()
        assert the_mission(mission).state == MS.COMPLETE

    def test_the_session_is_not_wedged_afterwards(self, tmp_path):
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()
        mission.load_existing()
        assert mission.active_mission is None, \
            "a completed trade still counts as an active mission"
        ok, why = mission.may_open_trade_mission(
            positions=0, working_orders=0, unknown_external=False, in_window=True)
        assert ok is True, why

    def test_the_second_trade_is_reachable_and_only_the_second(self, tmp_path):
        loop, ps, venue, mission, tag, size = self.flow(tmp_path)
        venue.fill(size=size, price=29781.25, tag=tag)
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()
        mission.load_existing()
        assert mission.trades_used() == 1
        assert mission.authorization.maximum_trades == 2


class TestItRefusesToCloseOnAnythingLessThanProof:

    def test_an_open_position_keeps_the_mission_open(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        venue.fill(size=ps.runner.geometry.size, price=29781.25,
                   tag=ps.runner.submission_custom_tag)
        loop.reconcile_missions()
        loop.reconcile_missions()
        assert the_mission(mission).state == MS.POSITION_OPEN

    def test_a_working_protective_order_keeps_it_open(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        venue._p = []                                   # flat...
        venue._o = [{"id": 901, "contract_id": CID, "status": 1, "type": 4,
                     "side": 1, "size": 1,
                     "parent_order_id": venue.order_id, "stop_price": 1.0}]
        loop.reconcile_missions()
        assert the_mission(mission).state != MS.COMPLETE

    def test_an_unreadable_venue_changes_nothing(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        before = the_mission(mission).state

        def boom():
            raise RuntimeError("venue unreachable")

        venue.open_positions = boom
        loop.reconcile_missions()
        assert the_mission(mission).state == before, \
            "an unreadable venue was treated as flat"

    def test_an_unreadable_venue_NEVER_CLOSES_AN_OPEN_POSITION(self, tmp_path):
        """The dangerous shape the previous test could not see.

        With no position ever opened, a read failure that degrades to "[]" is
        indistinguishable from the truth, so that test passed even when the
        failure path was mutated away. This one has a LIVE position first: a
        failed read must not be able to end it.
        """
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        assert the_mission(mission).state == MS.POSITION_OPEN

        def boom():
            raise RuntimeError("venue unreachable")

        venue.open_positions = boom
        loop.reconcile_missions()
        m = the_mission(mission)
        assert m.state == MS.POSITION_OPEN, \
            "a failed venue read closed a position that was still open"
        assert m.state not in MS.TERMINAL_STATES

    def test_an_unreadable_ORDER_book_also_changes_nothing(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        venue._p = []

        def boom():
            raise RuntimeError("venue unreachable")

        # BOTH SURFACES. Blinding `searchOpen` alone no longer blinds the
        # reconciler: production discovers through `/api/Order/v2/query`, so a
        # fixture that silences only the legacy endpoint is modelling a venue
        # that is still perfectly readable.
        venue.open_orders = boom
        venue.query_orders = boom
        loop.reconcile_missions()
        assert the_mission(mission).state == MS.POSITION_OPEN

    def test_a_foreign_order_on_our_contract_does_not_hold_us_open(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        venue._p, venue._trades = [], venue._trades + [
            {"orderId": 901, "price": 29785.0, "size": size}]
        # Foreign because its parent is a DIFFERENT entry order -- the property
        # the retired customTag rule was reaching for.
        venue._o = [{"id": 555, "contract_id": CID, "status": 1, "type": 4,
                     "side": 1, "size": 1,
                     "parent_order_id": 999999999, "stop_price": 1.0}]
        loop.reconcile_missions()
        assert the_mission(mission).state == MS.COMPLETE

    def test_the_ladder_cannot_be_walked_backward(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = the_mission(mission)
        with pytest.raises(MS.MissionStateError, match="backward"):
            m._advance(MS.ATTEMPT_CONSUMED, "regress", evidence="test")

    def test_completion_requires_a_recorded_order_id(self, tmp_path):
        """A mission that never recorded an order id has no trade to close."""
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = the_mission(mission)
        m.order_id = None
        with pytest.raises(MS.MissionStateError, match="never recorded"):
            m.reconcile_flat(positions=0, working_orders=0)

    def test_completion_requires_the_venue_to_have_been_asked(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = the_mission(mission)
        with pytest.raises(MS.MissionStateError, match="must be asked"):
            m.reconcile_flat(positions=None, working_orders=None)


class TestRestartSafetyAtEveryBoundary:
    """A restart must never duplicate a submission or reuse spent authority."""

    def restart(self, tmp_path, mission):
        """A genuinely cold read of the durable record."""
        fresh = SA.ProductionSessionMission(
            authorization=mission.authorization, store_dir=str(tmp_path))
        fresh.load_existing()
        return fresh

    def test_B_after_attempt_before_ack(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = MS.load(mission.mission_path(1))
        m.state, m.order_id, m.token_spent = MS.ATTEMPT_CONSUMED, None, False
        m.save()
        fresh = self.restart(tmp_path, mission)
        ok, why = fresh.trade_missions[0].may_attempt_entry()
        assert ok is False and "spent" in why

    def test_C_after_ack_before_persistence_is_not_voidable(self, tmp_path):
        """The V13 shape exactly: ack recorded in the ledger, not on the mission."""
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = MS.load(mission.mission_path(1))
        m.state, m.order_id, m.token_spent = MS.ATTEMPT_CONSUMED, None, False
        m.position_state, m.completion_state = "flat", ""
        m.save()
        evidence = RECOVERY.submission_evidence_for(
            str(tmp_path), mission.authorization.session_id, m.mission_id,
            token_id=m.token_id)
        ok, reasons = RECOVERY.never_reached_venue(m, submission_evidence=evidence)
        assert ok is False, "a mission the venue acknowledged was voidable"
        assert any(str(V13_ORDER_ID) in r for r in reasons)

    def test_D_the_completed_mission_is_never_resubmitted(self, tmp_path):
        """A later scan may open the SECOND trade -- that is the fix working --
        but it must never re-send the first. So the assertion is about mission
        1's identity, not about the raw call count: counting calls would have
        called the legitimately-unblocked second trade a duplicate."""
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        venue.fill(size=ps.runner.geometry.size, price=29781.25,
                   tag=ps.runner.submission_custom_tag)
        venue.stop_out(size=ps.runner.geometry.size, price=29785.0)
        first_before = MS.load(mission.mission_path(1)).as_dict()

        loop.scan_once()

        first_after = MS.load(mission.mission_path(1))
        assert first_after.attempt_count == 1, "mission 1 attempted twice"
        assert str(first_after.order_id) == str(V13_ORDER_ID)
        assert first_after.state == MS.COMPLETE
        # its terminal record is not rewritten by later activity
        assert first_after.token_id == first_before["token_id"]

    def test_D2_a_second_mission_never_reuses_the_first_token(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        venue.fill(size=ps.runner.geometry.size, price=29781.25,
                   tag=ps.runner.submission_custom_tag)
        venue.stop_out(size=ps.runner.geometry.size, price=29785.0)
        loop.scan_once()
        mission.load_existing()
        tokens = [m.token_id for m in mission.trade_missions if m.token_id]
        assert len(tokens) == len(set(tokens)), f"token reused across missions: {tokens}"

    def test_D3_a_restart_mid_flight_does_not_resubmit(self, tmp_path):
        """Position still open: the loop must reconcile, never enter again."""
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        venue.fill(size=ps.runner.geometry.size, price=29781.25,
                   tag=ps.runner.submission_custom_tag)
        before = venue.place_calls
        loop.scan_once()
        loop.scan_once()
        assert venue.place_calls == before, "submitted while a position was open"

    def test_E_position_open_blocks_a_new_mission(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        venue.fill(size=ps.runner.geometry.size, price=29781.25,
                   tag=ps.runner.submission_custom_tag)
        loop.reconcile_missions()
        fresh = self.restart(tmp_path, mission)
        assert fresh.active_mission is not None
        ok, why = fresh.may_open_trade_mission(
            positions=1, working_orders=2, unknown_external=False, in_window=True)
        assert ok is False

    def test_G_exit_seen_but_not_terminal_still_blocks(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = the_mission(mission)
        m.observe_position_open(filled_quantity=3, evidence="t")
        m.observe_exit(exit_type="stop", evidence="t")
        fresh = self.restart(tmp_path, mission)
        assert fresh.active_mission is not None

    def test_H_after_terminalization_the_token_is_never_reusable(self, tmp_path):
        loop, ps, venue, mission, tag_size = armed_scan(tmp_path)[:5]
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()
        fresh = self.restart(tmp_path, mission)
        done = fresh.trade_missions[0]
        assert done.state == MS.COMPLETE and done.token_spent is True
        ok, why = done.may_attempt_entry()
        assert ok is False


class TestIdentityAndTelemetryTellTheTruth:

    def test_the_flight_record_names_the_per_trade_mission(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        m = the_mission(mission)
        rows = SUBREC.scan_all_ledgers(str(tmp_path), m.mission_id, m.token_id)
        assert rows, "the submission ledger cannot be joined to its own mission"
        assert any(str(r.get("venue_order_id")) == str(V13_ORDER_ID)
                   for r in rows if r.get("venue_order_id"))

    def test_the_exact_V13_identity_mismatch_still_joins(self, tmp_path):
        """mission `X-T1` against a row stamped `X`, in a file named for a
        RETIRED session. The live shape, and the reason a filled trade looked
        voidable. The recorder now stamps the per-trade id, so this asserts the
        TOLERANCE that protects us when some other writer does not.
        """
        store = str(tmp_path)
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, "submissions_PROD-RETIRED.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({
                "submission_id": "sub-v13", "state": "VENUE_ACKNOWLEDGED",
                "session_id": "PROD-RETIRED",          # the wrong session
                "mission_id": "PROD-X-V13",            # session-level, not -T1
                "token_id": "prod-deadbeef",
                "venue_order_id": V13_ORDER_ID}) + "\n")

        ev = SUBREC.mission_venue_evidence(store, "PROD-X-V13-SESSION",
                                           "PROD-X-V13-T1")
        assert ev["submission_count"] == 1, \
            "the per-trade mission id failed to join its session-level row"
        assert ev["venue_may_have_seen"] is True
        assert V13_ORDER_ID in ev["venue_order_ids"]

    def test_the_token_id_joins_even_when_every_other_key_is_wrong(self, tmp_path):
        store = str(tmp_path)
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, "submissions_NONSENSE.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({
                "submission_id": "sub-t", "state": "VENUE_ACKNOWLEDGED",
                "session_id": "NONSENSE", "mission_id": "TOTALLY-UNRELATED",
                "token_id": "prod-abc123", "venue_order_id": 7}) + "\n")
        ev = SUBREC.mission_venue_evidence(store, "S", "M", token_id="prod-abc123")
        assert ev["submission_count"] == 1 and ev["venue_may_have_seen"] is True

    def test_an_unrelated_mission_is_not_falsely_joined(self, tmp_path):
        """Tolerance must not become promiscuity: `X-T1` and `Y-T1` are not
        the same mission, and neither are `X` and `XY`."""
        store = str(tmp_path)
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, "submissions_S.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({
                "submission_id": "s1", "state": "VENUE_ACKNOWLEDGED",
                "session_id": "S", "mission_id": "PROD-Y", "token_id": "tok-y",
                "venue_order_id": 11}) + "\n")
        ev = SUBREC.mission_venue_evidence(store, "S", "PROD-X-T1")
        assert ev["submission_count"] == 0
        assert SUBREC._identity_matches({"mission_id": "PROD-XY"}, "PROD-X") is False

    def test_an_empty_search_is_never_proof_when_the_key_is_weak(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        ev = SUBREC.mission_venue_evidence(str(tmp_path), "WRONG-SESSION",
                                           "WRONG-MISSION")
        assert ev["venue_may_have_seen"] is None
        assert ev["evidence_absent"] is True
        assert ev["search_key_strength"] == "mission_id"

    def test_geometry_evidence_reports_production_caps_not_smoke(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        ev = ps.runner.geometry.evidence()
        assert ev["effective_cap_usd"] == 350.00, ev
        assert ev["max_stop_points"] == 50.0, ev
        assert ev["governing_lane"] == "production"
        assert ev["governing_caps_declared"] is True

    def test_the_recorded_caps_match_what_actually_enforced(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        ev = ps.runner.geometry.evidence()
        assert ev["effective_cap_usd"] == ps.runner.max_risk_usd
        assert ev["max_stop_points"] == ps.runner.max_stop_points

    def test_risk_doctrine_is_untouched(self, tmp_path):
        from broker import topstepx_combine_risk as R
        assert R.ABSOLUTE_MAX_STOP_POINTS == 50.0
        assert R.PREFERRED_MAX_STOP_POINTS == 35.0
        assert R.PRODUCTION_MAX_RISK_USD == 350.00
        assert R.PRODUCTION_MAX_CONTRACTS == 15
        assert R.MIN_REWARD_TO_RISK == 1.0


class TestTheV13HistoricalRegression:
    """The specific flight, start to finish, as the shape that must not recur."""

    def test_ack_fill_stop_flat_ends_terminal_with_everything_recorded(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        tag, size = ps.runner.submission_custom_tag, ps.runner.geometry.size
        venue.fill(size=size, price=29781.25, tag=tag)
        loop.reconcile_missions()
        venue.stop_out(size=size, price=29785.0)
        loop.reconcile_missions()

        m = the_mission(mission)
        assert m.state == MS.COMPLETE
        assert str(m.order_id) == str(V13_ORDER_ID)
        assert m.token_spent is True
        assert m.filled_quantity == size
        assert m.exit_price == 29785.0
        assert m.flat_confirmed_at and m.acknowledged_at
        assert m.session_id and m.authorization_fingerprint

    def test_no_real_venue_write_ever_happened(self, tmp_path):
        loop, ps, venue, mission, out = armed_scan(tmp_path)
        assert venue.place_calls == 1
