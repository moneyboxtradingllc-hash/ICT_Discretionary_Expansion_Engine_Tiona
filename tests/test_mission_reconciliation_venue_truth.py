"""MISSION-RECONCILIATION-VENUE-TRUTH-1 — bound to the REAL client object graph.

WHY THIS FILE EXISTS SEPARATELY. `tests/test_execution_lifecycle_closure.py`
certifies the reconciler against hand-built dicts carrying `contractId`,
`averagePrice` and `customTag`. `TopstepXClient` emits none of those: positions
and orders are normalised to snake_case and the order contract has no tag field
at all. The old fixtures therefore proved a shape production never produces,
and both venue selectors were structurally dead in the live lane while the
suite stayed green.

Every venue payload below is copied from what `TopstepXClient.open_positions()`
and `open_orders()` actually build (client lines ~474-500), and the trade rows
from `TopstepXLiveSession.recent_trades()`, which returns RAW venue JSON.

No broker. No provider. No network.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_mission_state as MS                      # noqa: E402
from broker import topstepx_mission_reconciler as RC                 # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:aaaaaaaaaaaa"

# ── the real 2026-08-25 identities ──────────────────────────────────────────
T1_ENTRY, T1_EXIT = 3446530387, 3446530516
T2_ENTRY, T2_STOP, T2_TARGET = 3446535520, 3446535522, 3446535523
T1_FILL, T2_FILL = 29229.50, 29226.25
STOP_PX, TARGET_PX = 29192.00, 29409.25


# ── real normalised venue payloads ──────────────────────────────────────────
def real_position(size=5, avg=T2_FILL):
    """EXACTLY TopstepXClient.open_positions() output."""
    return {"id": 830922009, "contract_id": CID, "side": "long", "size": size,
            "avg_price": avg, "opened_at": "2026-08-25T14:49:20.296104+00:00"}


def real_child(oid, otype, *, parent=T2_ENTRY, stop=None, limit=None):
    """EXACTLY TopstepXClient.open_orders() output — note: NO customTag."""
    return {"id": oid, "contract_id": CID, "status": 1, "type": otype,
            "side": 1, "size": 5, "limit_price": limit, "stop_price": stop,
            "parent_order_id": parent}


def t2_children():
    return [real_child(T2_STOP, RC.ORDER_TYPE_STOP, stop=STOP_PX),
            real_child(T2_TARGET, RC.ORDER_TYPE_LIMIT, limit=TARGET_PX)]


def trade(order_id, price, size=5):
    """RAW venue trade JSON, as recent_trades() returns it."""
    return {"orderId": order_id, "price": price, "size": size}


class Venue:
    def __init__(self, positions=None, orders=None, trades=None):
        self._p, self._o, self._t = positions or [], orders or [], trades or []

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        Production reads this, not `searchOpen`, because `searchOpen` omits
        Suspended bracket children by venue contract. A fixture without this
        method models the degraded fallback, where absence can never be proven.
        No status filter is applied, matching production.
        """
        rows = list(self._o)
        if contract_id:
            rows = [o for o in rows
                    if (o.get("contract_id") or o.get("contractId")) == contract_id]
        return rows

    def recent_trades(self, since=None):
        return list(self._t)


class BlindVenue(Venue):
    """The venue read raises — UNKNOWN, and unknown is never flat."""

    def open_positions(self):
        raise RuntimeError("venue unreachable")


class MutePartialVenue(Venue):
    """A venue object that cannot answer about positions at all."""
    open_positions = None


def mission(tmp_path, mission_id="PRAC-20260825-T2", order_id=T2_ENTRY,
            *, to_open=False, fill=T2_FILL, protective=None):
    m = MS.open_mission(path=str(tmp_path / f"{mission_id}.json"),
                        mission_id=mission_id, account_fingerprint=FP,
                        contract_id=CID, authorization_fingerprint="auth:test")
    m.consume_attempt(candidate_fingerprint="cand", token_id="tok-" + mission_id)
    m.record_venue_acknowledgement(venue_order_id=order_id, session_id="PRAC-20260825")
    if to_open:
        m.observe_position_open(filled_quantity=5, fill_price=fill,
                                protective_order_ids=protective or [],
                                evidence="test")
    return m


# ══ A · POSITION AUTHORITY ══════════════════════════════════════════════════
class TestPositionAuthority:

    def test_real_normalised_position_is_detected(self):
        """The 08-25 defect: `contractId` selector vs `contract_id` payload
        made `size` 0 on every tick of every mission."""
        assert RC.position_size([real_position(size=5)], CID) == 5
        assert RC.position_for([real_position()], CID).get("id") == 830922009

    def test_a_foreign_contract_is_not_our_exposure(self):
        other = dict(real_position(), contract_id="CON.F.US.ES.U26")
        assert RC.position_size([other], CID) == 0

    def test_short_exposure_counts_as_exposure(self):
        assert RC.position_size([real_position(size=-5)], CID) == 5

    def test_empty_answer_is_zero(self):
        assert RC.position_size([], CID) == 0


# ══ B · PROTECTIVE LINEAGE ══════════════════════════════════════════════════
class TestProtectiveLineage:

    def test_children_of_our_entry_are_adopted(self):
        ours = RC.lineage_orders(t2_children(), contract_id=CID,
                                 entry_order_id=T2_ENTRY)
        assert sorted(o["id"] for o in ours) == sorted([T2_STOP, T2_TARGET])

    def test_stop_and_target_are_split_by_venue_order_type(self):
        stops, targets = RC.split_protective(t2_children())
        assert stops == [T2_STOP] and targets == [T2_TARGET]

    def test_another_missions_children_are_never_adopted(self):
        """The property the dead customTag rule was reaching for."""
        foreign = [real_child(999001, RC.ORDER_TYPE_STOP, parent=T1_ENTRY)]
        assert RC.lineage_orders(foreign, contract_id=CID,
                                 entry_order_id=T2_ENTRY) == []

    def test_an_unparented_order_is_not_ours(self):
        orphan = [real_child(999002, RC.ORDER_TYPE_STOP, parent=None)]
        assert RC.lineage_orders(orphan, contract_id=CID,
                                 entry_order_id=T2_ENTRY) == []

    def test_no_entry_order_means_no_lineage(self):
        assert RC.lineage_orders(t2_children(), contract_id=CID,
                                 entry_order_id=None) == []


# ══ C · THE 2026-08-25 T2 REPRODUCTION ══════════════════════════════════════
class TestT2Reproduction:
    """The exact live scenario: T1 closed, T2 open and protected."""

    def venue(self):
        return Venue(positions=[real_position()], orders=t2_children(),
                     trades=[trade(T1_ENTRY, T1_FILL), trade(T1_EXIT, 29228.50),
                             trade(T2_ENTRY, T2_FILL)])

    def test_t2_stays_open_while_the_venue_holds_the_position(self, tmp_path):
        m = mission(tmp_path)
        out = RC.MissionReconciler(venue=self.venue(), contract_id=CID).reconcile(m)
        assert m.state == MS.POSITION_OPEN
        assert m.state not in MS.TERMINAL_STATES, "a live position was completed"
        assert out["position_size"] == 5

    def test_t2_adopts_its_real_protective_children(self, tmp_path):
        m = mission(tmp_path)
        RC.MissionReconciler(venue=self.venue(), contract_id=CID).reconcile(m)
        assert sorted(str(o) for o in m.protective_order_ids) == \
            sorted([str(T2_STOP), str(T2_TARGET)])

    def test_t1s_entry_is_never_recorded_as_t2s_exit(self, tmp_path):
        """The literal 08-25 corruption: exit_price 29229.50 / exit_order
        3446530387 — T1's ENTRY — written onto T2."""
        m = mission(tmp_path)
        RC.MissionReconciler(venue=self.venue(), contract_id=CID).reconcile(m)
        assert m.exit_price != T1_FILL
        assert str(m.exit_order_id or "") != str(T1_ENTRY)
        assert not m.flat_confirmed_at


# ══ D/E · EXIT ATTRIBUTION LAW ══════════════════════════════════════════════
class TestExitAttribution:

    def test_a_foreign_trade_is_never_our_exit(self, tmp_path):
        m = mission(tmp_path, to_open=True, protective=[T2_STOP, T2_TARGET])
        m.stop_order_ids, m.target_order_ids = [T2_STOP], [T2_TARGET]
        kind, price, oid = RC.classify_exit(
            [trade(T1_ENTRY, T1_FILL), trade(T1_EXIT, 29228.50)], m)
        assert (kind, price, oid) == (RC.EXIT_UNATTRIBUTED, None, None)

    def test_our_stop_fill_is_classified_as_a_stop(self, tmp_path):
        m = mission(tmp_path, to_open=True, protective=[T2_STOP, T2_TARGET])
        m.stop_order_ids, m.target_order_ids = [T2_STOP], [T2_TARGET]
        assert RC.classify_exit([trade(T2_STOP, STOP_PX)], m) == \
            (RC.EXIT_STOP, STOP_PX, T2_STOP)

    def test_our_target_fill_is_classified_as_a_target(self, tmp_path):
        m = mission(tmp_path, to_open=True, protective=[T2_STOP, T2_TARGET])
        m.stop_order_ids, m.target_order_ids = [T2_STOP], [T2_TARGET]
        assert RC.classify_exit([trade(T2_TARGET, TARGET_PX)], m) == \
            (RC.EXIT_TARGET, TARGET_PX, T2_TARGET)

    def test_unknown_protection_cannot_attribute_anything(self, tmp_path):
        """No adopted children -> no identity -> no borrowed price."""
        m = mission(tmp_path, to_open=True, protective=[])
        assert RC.classify_exit([trade(T1_ENTRY, T1_FILL)], m) == \
            (RC.EXIT_UNATTRIBUTED, None, None)


# ══ F · MANUAL CLOSE ════════════════════════════════════════════════════════
class TestManualClose:
    """Venue-proven flat with no attributable execution — 2026-08-25's real
    ending. Terminal is allowed; a fabricated exit price is not."""

    def test_manual_close_completes_without_stealing_a_price(self, tmp_path):
        m = mission(tmp_path, to_open=True, protective=[T2_STOP, T2_TARGET])
        venue = Venue(positions=[], orders=[],
                      trades=[trade(T1_ENTRY, T1_FILL)])
        RC.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)
        assert m.state == MS.COMPLETE
        assert m.exit_type == RC.EXIT_UNATTRIBUTED
        assert m.exit_price is None and m.exit_order_id is None


# ══ G/H · UNKNOWN IS NOT FLAT ═══════════════════════════════════════════════
class TestUnknownIsNotFlat:

    def test_a_failed_venue_read_never_completes_a_mission(self, tmp_path):
        m = mission(tmp_path, to_open=True, protective=[T2_STOP])
        out = RC.MissionReconciler(venue=BlindVenue(), contract_id=CID).reconcile(m)
        assert out.get("skipped") == "venue unreadable"
        assert m.state == MS.POSITION_OPEN

    def test_a_venue_that_cannot_be_asked_never_completes_a_mission(self, tmp_path):
        """`open_positions` absent returned a default [] that read as flat."""
        m = mission(tmp_path, to_open=True, protective=[T2_STOP])
        v = MutePartialVenue(orders=[], trades=[])
        out = RC.MissionReconciler(venue=v, contract_id=CID).reconcile(m)
        assert m.state != MS.COMPLETE
        assert out.get("skipped") == "venue unreadable"

    def test_a_successful_empty_answer_may_establish_flat(self, tmp_path):
        """The REAL two-tick sequence: tick 1 sees the open position and its
        children, tick 2 sees the venue flat after the stop filled. The tick
        that observes the exit no longer sees the working orders, so the
        stop/target split must survive from tick 1 -- otherwise a knowable
        stop-fill is demoted to a bare `closed`."""
        m = mission(tmp_path)
        rec = RC.MissionReconciler(
            venue=Venue(positions=[real_position()], orders=t2_children(),
                        trades=[trade(T2_ENTRY, T2_FILL)]), contract_id=CID)
        rec.reconcile(m)
        assert m.state == MS.POSITION_OPEN

        flat = RC.MissionReconciler(
            venue=Venue(positions=[], orders=[],
                        trades=[trade(T2_ENTRY, T2_FILL), trade(T2_STOP, STOP_PX)]),
            contract_id=CID)
        flat.reconcile(m)
        assert m.state == MS.COMPLETE
        assert m.exit_type == RC.EXIT_STOP and m.exit_price == STOP_PX
        assert str(m.exit_order_id) == str(T2_STOP)

    def test_working_protective_orders_block_completion(self, tmp_path):
        """Flat position but our stop still resting: not clean, not terminal."""
        m = mission(tmp_path, to_open=True, protective=[T2_STOP])
        venue = Venue(positions=[], orders=t2_children(),
                      trades=[trade(T2_ENTRY, T2_FILL)])
        RC.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)
        assert m.state != MS.COMPLETE


# ══ I/J/K · RESTART, IDEMPOTENCE, AND T1 ════════════════════════════════════
class TestRestartAndIdempotence:

    def test_restart_sees_a_live_position_and_reopens_the_mission(self, tmp_path):
        """A cold read of the durable record must recover live exposure."""
        m = mission(tmp_path)
        path = m.path
        fresh = MS.load(path)
        venue = Venue(positions=[real_position()], orders=t2_children(),
                      trades=[trade(T2_ENTRY, T2_FILL)])
        RC.MissionReconciler(venue=venue, contract_id=CID).reconcile(fresh)
        assert fresh.state == MS.POSITION_OPEN
        assert sorted(str(o) for o in fresh.protective_order_ids) == \
            sorted([str(T2_STOP), str(T2_TARGET)])

    def test_repeated_reconciliation_is_idempotent(self, tmp_path):
        m = mission(tmp_path)
        venue = Venue(positions=[real_position()], orders=t2_children(),
                      trades=[trade(T2_ENTRY, T2_FILL)])
        rec = RC.MissionReconciler(venue=venue, contract_id=CID)
        rec.reconcile(m)
        history_len = len(m.history)
        rec.reconcile(m)
        rec.reconcile(m)
        assert m.state == MS.POSITION_OPEN
        assert len(m.history) == history_len, "re-observation rewrote history"

    def test_t1_auto_flatten_still_completes_correctly(self, tmp_path):
        """T1 filled, could not be protected, was flattened. It must still
        reach COMPLETE — the fix must not strand a genuinely closed mission."""
        m = mission(tmp_path, mission_id="PRAC-20260825-T1", order_id=T1_ENTRY)
        venue = Venue(positions=[], orders=[],
                      trades=[trade(T1_ENTRY, T1_FILL), trade(T1_EXIT, 29228.50)])
        RC.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)
        assert m.state == MS.COMPLETE
        assert m.filled_quantity == 5 and m.fill_price == T1_FILL
        # It had no adopted protection, so the closing execution cannot be
        # bound to it — truthfully unattributed rather than borrowed.
        assert m.exit_price is None
