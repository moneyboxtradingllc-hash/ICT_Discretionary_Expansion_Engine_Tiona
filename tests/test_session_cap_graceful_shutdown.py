"""SESSION-CAP-GRACEFUL-SHUTDOWN-1 — trade authority ends before responsibility.

THE 2026-08-25 DEFECT. Attempt #2 was consumed at 10:49. The process then
printed `SESSION_COMPLETE` 160 times across ~19 minutes and had to be killed
externally: `should_continue` held the loop for the whole decision window
regardless of cap state, and nothing could conclude "my job is finished".
Terminal was a LABEL, never a decision.

Venue payloads here are the REAL normalised `TopstepXClient` shapes — the same
discipline `045c472` had to restore. No broker, no provider, no network.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_mission_state as MS                      # noqa: E402
from broker import topstepx_session_lifecycle as LC                  # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:aaaaaaaaaaaa"
T1_ENTRY, T2_ENTRY = 3446530387, 3446535520
T2_STOP, T2_TARGET = 3446535522, 3446535523


def position(size=5):
    return {"id": 830922009, "contract_id": CID, "side": "long", "size": size,
            "avg_price": 29226.25, "opened_at": "2026-08-25T14:49:20.296104+00:00"}


def child(oid, otype=4, parent=T2_ENTRY):
    return {"id": oid, "contract_id": CID, "status": 1, "type": otype,
            "side": 1, "size": 5, "limit_price": None, "stop_price": 29192.0,
            "parent_order_id": parent}


class Venue:
    def __init__(self, positions=None, orders=None):
        self._p, self._o = positions or [], orders or []

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def recent_trades(self, since=None):
        return []


class PositionReadFails(Venue):
    def open_positions(self):
        raise RuntimeError("venue unreachable")


class OrderReadFails(Venue):
    def open_orders(self):
        raise RuntimeError("venue unreachable")


class FakeMission:
    """The durable facts `resolve` consumes: allowance + mission records."""

    class Auth:
        maximum_trades = 2

    def __init__(self, used, missions=None):
        self.authorization = self.Auth()
        self._used = used
        self.trade_missions = missions or []

    def trades_used(self):
        return self._used


class M:
    """A mission record stand-in: identity + lifecycle state only."""

    def __init__(self, mission_id, state, order_id):
        self.mission_id, self.state, self.order_id = mission_id, state, order_id


def done_t1():
    return M("PRAC-20260825-T1", MS.COMPLETE, T1_ENTRY)


def live_t2():
    return M("PRAC-20260825-T2", MS.POSITION_OPEN, T2_ENTRY)


def done_t2():
    return M("PRAC-20260825-T2", MS.COMPLETE, T2_ENTRY)


def resolve(mission, venue):
    return LC.resolve(mission=mission, venue=venue, contract_id=CID)


# ══ 1 · CAP NOT REACHED ═════════════════════════════════════════════════════
class TestTradingContinues:

    def test_below_the_cap_the_session_is_trading_active(self):
        out = resolve(FakeMission(1, [done_t1()]), Venue())
        assert out["mode"] == LC.TRADING_ACTIVE
        assert out["may_exit"] is False

    def test_cap_authority_is_the_durable_counter(self):
        """`trades_used()` is derived from mission records on disk, so it
        survives process death. No RAM-only counter is introduced."""
        assert LC.entry_authority_exhausted(FakeMission(1)) is False
        assert LC.entry_authority_exhausted(FakeMission(2)) is True
        assert LC.entry_authority_exhausted(FakeMission(3)) is True

    def test_an_attempt_that_lost_money_still_spent_the_cap(self):
        """T1 filled, failed protection, auto-flattened — and still consumed
        attempt #1. Fills and winners are not the authority."""
        assert LC.entry_authority_exhausted(FakeMission(2, [done_t1(), done_t2()]))


# ══ 2-4 · MANAGEMENT-ONLY WHILE RESPONSIBLE ═════════════════════════════════
class TestManagementOnly:

    def test_cap_reached_with_an_open_position_does_not_exit(self):
        out = resolve(FakeMission(2, [done_t1(), live_t2()]),
                      Venue([position()], [child(T2_STOP), child(T2_TARGET, 1)]))
        assert out["mode"] == LC.MANAGEMENT_ONLY
        assert out["may_exit"] is False
        assert out["exposure"] == 5

    def test_protective_orders_are_recognised_as_ours(self):
        out = resolve(FakeMission(2, [done_t1(), live_t2()]),
                      Venue([position()], [child(T2_STOP), child(T2_TARGET, 1)]))
        assert sorted(out["owned_orders"]) == sorted([T2_STOP, T2_TARGET])
        assert out["unexplained_orders"] == []

    def test_an_unresolved_mission_blocks_exit_even_with_no_position(self):
        """Attempt #2 may be consumed BEFORE the venue lifecycle is terminal:
        acknowledged, no fill observed yet. The whole submitted attempt is owned
        until venue truth settles it."""
        pending = M("PRAC-20260825-T2", MS.VENUE_ACKNOWLEDGED, T2_ENTRY)
        out = resolve(FakeMission(2, [done_t1(), pending]), Venue([], []))
        assert out["mode"] == LC.MANAGEMENT_ONLY
        assert out["may_exit"] is False
        assert any("unresolved mission" in r for r in out["reasons"])

    def test_a_working_entry_order_blocks_exit(self):
        pending = M("PRAC-20260825-T2", MS.VENUE_ACKNOWLEDGED, T2_ENTRY)
        entry = {"id": T2_ENTRY, "contract_id": CID, "status": 1, "type": 2,
                 "side": 0, "size": 5, "limit_price": None, "stop_price": None,
                 "parent_order_id": None}
        out = resolve(FakeMission(2, [done_t1(), pending]), Venue([], [entry]))
        assert out["may_exit"] is False
        assert T2_ENTRY in out["owned_orders"]


# ══ 5 · THE CLEAN EXIT ══════════════════════════════════════════════════════
class TestGracefulExit:

    def test_cap_reached_flat_and_order_clean_may_exit(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([], []))
        assert out["mode"] == LC.SESSION_COMPLETE
        assert out["may_exit"] is True
        assert out["exposure"] == 0

    def test_a_foreign_instrument_does_not_block_exit(self):
        other = dict(position(), contract_id="CON.F.US.ES.U26")
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([other], []))
        assert out["may_exit"] is True


# ══ 6-7 · UNKNOWN IS NOT CLEAN ══════════════════════════════════════════════
class TestUnknownIsNotClean:

    def test_a_failed_position_read_never_permits_exit(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), PositionReadFails())
        assert out["mode"] == LC.WAITING_FOR_VENUE_TRUTH
        assert out["may_exit"] is False and out["venue_known"] is False

    def test_a_failed_order_read_never_permits_exit(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), OrderReadFails())
        assert out["mode"] == LC.WAITING_FOR_VENUE_TRUTH
        assert out["may_exit"] is False

    def test_waiting_for_venue_truth_is_still_not_trading(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), PositionReadFails())
        assert out["mode"] in LC.MANAGING_MODES
        assert out["mode"] != LC.TRADING_ACTIVE


# ══ 8-9 · ORDER OWNERSHIP ═══════════════════════════════════════════════════
class TestOrderOwnership:

    def test_another_missions_child_is_not_adopted_but_still_blocks(self):
        """Ambiguity resolves toward staying alive, never toward finished."""
        foreign = child(999001, parent=555555555)
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([], [foreign]))
        assert out["owned_orders"] == []
        assert out["unexplained_orders"] == [999001]
        assert out["may_exit"] is False

    def test_an_order_on_another_contract_is_ignored(self):
        foreign = dict(child(999002, parent=555555555),
                       contract_id="CON.F.US.ES.U26")
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([], [foreign]))
        assert out["may_exit"] is True


# ══ 10-11 · VENUE OVERRULES THE MISSION RECORD ══════════════════════════════
class TestVenueTruthOverrulesMissionState:

    def test_mission_says_complete_but_venue_shows_a_position(self):
        """EXACTLY 2026-08-25: T2 reported COMPLETE/flat while the venue held
        LONG 5. Shutdown must not trust the derived record."""
        out = resolve(FakeMission(2, [done_t1(), done_t2()]),
                      Venue([position()], [child(T2_STOP)]))
        assert out["mode"] == LC.MANAGEMENT_ONLY
        assert out["may_exit"] is False
        assert out["exposure"] == 5

    def test_mission_says_open_but_venue_is_clean_still_blocks(self):
        """A mission's own opinion may only ADD responsibility, never subtract
        it — so an unreconciled record keeps the process alive until the
        reconciler settles it."""
        out = resolve(FakeMission(2, [done_t1(), live_t2()]), Venue([], []))
        assert out["may_exit"] is False
        assert any("unresolved mission" in r for r in out["reasons"])


# ══ 15-17 · RESTART ═════════════════════════════════════════════════════════
class TestRestartBehaviour:
    """The cap is read off disk, so a restart cannot hand back authority."""

    def test_restart_with_cap_exhausted_and_exposure_is_management_only(self):
        out = resolve(FakeMission(2, [done_t1(), live_t2()]),
                      Venue([position()], [child(T2_STOP)]))
        assert out["mode"] == LC.MANAGEMENT_ONLY

    def test_restart_with_cap_exhausted_and_clean_exits_promptly(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([], []))
        assert out["mode"] == LC.SESSION_COMPLETE

    def test_restart_with_cap_exhausted_and_venue_unknown_fails_closed(self):
        out = resolve(FakeMission(2, [done_t1(), done_t2()]), PositionReadFails())
        assert out["mode"] == LC.WAITING_FOR_VENUE_TRUTH

    def test_restart_below_cap_may_still_trade(self):
        out = resolve(FakeMission(1, [done_t1()]), Venue())
        assert out["mode"] == LC.TRADING_ACTIVE


# ══ 18 · IDEMPOTENCE ════════════════════════════════════════════════════════
class TestIdempotence:

    def test_resolving_repeatedly_is_stable_and_mutates_nothing(self):
        m = FakeMission(2, [done_t1(), live_t2()])
        v = Venue([position()], [child(T2_STOP)])
        first = resolve(m, v)
        for _ in range(5):
            assert resolve(m, v)["mode"] == first["mode"]
        assert m.trade_missions[1].state == MS.POSITION_OPEN, "resolve mutated a mission"

    def test_resolve_places_and_cancels_nothing(self):
        """This unit decides WHETHER to stop, never HOW to flatten."""
        v = Venue([position()], [child(T2_STOP)])
        assert not hasattr(v, "cancelled")
        resolve(FakeMission(2, [done_t1(), live_t2()]), v)
        assert v.open_positions() == [position()]


# ══ 20 · THE 2026-08-25 SEQUENCE ════════════════════════════════════════════
class TestTheLiveSpecimen:
    """T1 auto-flattened, T2 filled and stayed live, operator closed manually."""

    def test_the_full_lifecycle_walk(self):
        # attempt #1 consumed, T1 still working -> still trading
        assert resolve(FakeMission(1, [live_t2()]), Venue())["mode"] == \
            LC.TRADING_ACTIVE

        # attempt #2 consumed, T2 live and protected -> MANAGEMENT_ONLY
        managing = resolve(
            FakeMission(2, [done_t1(), live_t2()]),
            Venue([position()], [child(T2_STOP), child(T2_TARGET, 1)]))
        assert managing["mode"] == LC.MANAGEMENT_ONLY
        assert managing["may_exit"] is False

        # operator closes manually; reconciler settles the mission -> exit
        after = resolve(FakeMission(2, [done_t1(), done_t2()]), Venue([], []))
        assert after["mode"] == LC.SESSION_COMPLETE
        assert after["may_exit"] is True

    def test_the_160_reprint_cannot_happen_again(self):
        """Terminal now means terminal: the only mode that permits leaving the
        loop is the one that also proved the venue clean."""
        managing = resolve(FakeMission(2, [done_t1(), live_t2()]),
                           Venue([position()], [child(T2_STOP)]))
        assert managing["mode"] != LC.SESSION_COMPLETE
        assert managing["may_exit"] is False


# ══ 19 · NO COGNITION AFTER THE CAP — against the REAL ProductionLoop ═══════
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_production_scan_loop import build, Cycle                   # noqa: E402


class TestNoCognitionAfterCap:
    """The seam that matters most for cost AND for doctrine.

    Before this unit the cap gate required `active_mission is None`, so a
    session whose allowance was spent but whose trade was still live ran the
    FULL scan every tick — snapshot, Brain payload, Luna call — to decide
    something it had no authority to act on. On 2026-08-25 that stayed hidden
    only because the mission went falsely terminal in 38 seconds. Repairing the
    reconciler (045c472) is exactly what would have exposed it.

    `Cycle.scans` counts entries into the scan cycle, which is where the Brain
    call lives. It must not move once the cap is spent.
    """

    def exhausted_loop(self, tmp_path, *, positions=None, orders=None):
        cycle = Cycle()
        loop, ps, sess, mission = build(tmp_path, armed=True, cycle=cycle)
        sess._p = positions if positions is not None else []
        sess._o = orders if orders is not None else []
        # Spend the allowance the way production does: durable mission records.
        loop.mission.trades_used = lambda: 2
        loop.mission.trade_missions = []
        return loop, cycle, sess

    def test_cognition_stops_the_moment_the_cap_is_spent(self, tmp_path):
        loop, cycle, _ = self.exhausted_loop(tmp_path)
        before = cycle.scans
        out = loop.scan_once()
        assert cycle.scans == before, "the Brain was consulted after the cap"
        assert out["outcome"] in (LC.SESSION_COMPLETE, LC.MANAGEMENT_ONLY,
                                 LC.WAITING_FOR_VENUE_TRUTH)

    def test_no_cognition_even_while_managing_a_live_position(self, tmp_path):
        """The case the old gate fell through: exposure still open."""
        loop, cycle, _ = self.exhausted_loop(
            tmp_path, positions=[position()], orders=[child(T2_STOP)])
        for _ in range(5):
            out = loop.scan_once()
        assert cycle.scans == 0, "management-only called the Brain"
        assert out["outcome"] == LC.MANAGEMENT_ONLY

    def test_repeated_post_cap_ticks_never_place_an_order(self, tmp_path):
        loop, _, sess = self.exhausted_loop(tmp_path, positions=[position()])
        for _ in range(5):
            loop.scan_once()
        assert sess.place_calls == 0

    def test_a_clean_venue_yields_the_terminal_decision(self, tmp_path):
        loop, cycle, _ = self.exhausted_loop(tmp_path)
        out = loop.scan_once()
        assert out["outcome"] == LC.SESSION_COMPLETE
        assert out["lifecycle"]["may_exit"] is True
        assert cycle.scans == 0

    def test_below_the_cap_cognition_still_runs(self, tmp_path):
        """The gate must not have turned into a blanket mute."""
        cycle = Cycle()
        loop, _, _, _ = build(tmp_path, armed=True, cycle=cycle)
        loop.scan_once()
        assert cycle.scans == 1
