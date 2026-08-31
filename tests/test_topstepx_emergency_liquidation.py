"""TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1 — the reversal race, closed.

THE INCIDENT, venue-proven on 2026-08-26:

    13:37:58.943  SELL 15 @ 29257.50   legitimate short
    13:37:59.718  BUY  15 @ 29264.50   emergency flatten -> FLAT      -$210.00
    13:37:59.804  BUY  15 @ 29266.25   still-working protective STOP fired
                                       into a flat account -> LONG 15
    13:38:07.430  SELL 15 @ 29256.00   cleanup -> FLAT                -$307.50

86 milliseconds. The unintended reversal cost more than the trade it protected.

Order 3451056003 never changed. It was protection while a short existed and an
ENTRY the instant the account went flat. Authority is a RELATIONSHIP between an
order and a currently existing position -- not a property of the order.

NINE call sites can hand this primitive an account whose child authority is
working, ambiguous, or mid-mutation. `risk_above_cap` was one of them.

NO LIVE ORDERS. NO BROKER. The planner is pure; these drive it against a
deterministic venue whose single modelled behaviour is the one that caused the
incident -- closing a position does not cancel working children.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_emergency_liquidation as EL      # noqa: E402
from broker.topstepx_client import TopstepXClient             # noqa: E402

ENTRY_ID, SL_ID, TP_ID = 3451056002, 3451056003, 3451056004


def order(oid, status=EL.STATUS_OPEN, side=0, size=15, parent=ENTRY_ID, tag=None):
    return {"id": oid, "status": status, "side": side, "size": size,
            "parent_order_id": parent, "custom_tag": tag}


def owns(o):
    return o.get("parent_order_id") == ENTRY_ID


def never_owns(_o):
    return False


class Venue:
    """The one behaviour that caused the incident: close_position leaves
    children working, and a resting stop fills the moment it can."""

    def __init__(self, position=-15, orders=None, fires=True):
        self.position = position
        self.orders = {o["id"]: dict(o) for o in (orders or [])}
        self.fires = fires
        self.log = []

    def working(self):
        return [dict(o) for o in self.orders.values()
                if o["status"] in EL.ACTIVE_STATUSES]

    def cancel(self, oid):
        o = self.orders.get(oid)
        if o and o["status"] in EL.ACTIVE_STATUSES:
            o["status"] = EL.STATUS_CANCELLED
            self.log.append(f"cancel {oid}")

    def close_position(self):
        if self.position != 0:
            self.log.append(f"close {self.position} -> 0")
            self.position = 0
        if self.fires:
            self._fire_resting()

    def _fire_resting(self):
        for o in self.orders.values():
            if o["status"] in EL.ACTIVE_STATUSES and o.get("_rests", True):
                o["status"] = EL.STATUS_FILLED
                before = self.position
                self.position += 15 if o["side"] == 0 else -15
                self.log.append(f"ORPHAN {o['id']} FILLED {before} -> {self.position}")
                return


def converge(venue, *, owns_fn=owns, max_rounds=EL.DEFAULT_MAX_ROUNDS):
    """Drive the planner to a terminal decision. Returns the last decision."""
    close_state = EL.CLOSE_NOT_SUBMITTED
    decision = None
    for r in range(max_rounds):
        decision = EL.plan(position_size=venue.position, orders=venue.working(),
                           owns=owns_fn, close_state=close_state, round_index=r)
        if decision["action"] == EL.ACTION_CANCEL:
            for oid in decision["order_ids"]:
                venue.cancel(oid)
        elif decision["action"] == EL.ACTION_CLOSE:
            venue.close_position()
            close_state = EL.CLOSE_FILLED
        else:
            break
    return decision


# ══ THE INCIDENT ════════════════════════════════════════════════════════════
class TestTheIncident:

    def test_old_ordering_reverses_the_account(self):
        """Close-then-cancel reproduces 2026-08-26 exactly."""
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        v.close_position()                 # what emergency_flatten does today
        for oid in list(v.orders):
            v.cancel(oid)
        assert v.position == 15, "the reproduction failed to reproduce"
        assert any("ORPHAN" in line for line in v.log)

    def test_new_ordering_cannot_reverse(self):
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        decision = converge(v)
        assert v.position == 0
        assert EL.is_safe_terminal(decision), decision
        assert not any("ORPHAN" in line for line in v.log)

    def test_children_are_neutralised_before_the_close(self):
        """A child can only reverse an account that is already flat, so entry
        authority must be removed BEFORE flatness is created."""
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        first = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert first["action"] == EL.ACTION_CANCEL
        assert set(first["order_ids"]) == {SL_ID, TP_ID}


# ══ AUTHORITY IS RELATIONAL ═════════════════════════════════════════════════
class TestOrderAuthority:

    def test_the_same_order_flips_authority_when_position_dies(self):
        """The exact 86ms transition, in one assertion."""
        stop = order(SL_ID, side=0)
        assert EL.classify_order(stop, position_size=-15) == EL.PROTECTIVE_AUTHORITY
        assert EL.classify_order(stop, position_size=0) == EL.ENTRY_AUTHORITY

    @pytest.mark.parametrize("status", sorted(EL.TERMINAL_STATUSES))
    def test_terminal_statuses_are_non_executable(self, status):
        assert EL.classify_order(order(SL_ID, status=status),
                                 position_size=-15) == EL.NON_EXECUTABLE

    @pytest.mark.parametrize("status", sorted(EL.ACTIVE_STATUSES))
    def test_active_statuses_retain_authority(self, status):
        assert EL.classify_order(order(SL_ID, status=status),
                                 position_size=0) == EL.ENTRY_AUTHORITY

    def test_pending_cancellation_is_not_cancelled(self):
        """A cancel in flight can still fill. Treating it as gone rebuilds the
        race one layer up."""
        o = order(SL_ID, status=EL.STATUS_PENDING_CANCELLATION)
        assert EL.classify_order(o, position_size=-15) != EL.NON_EXECUTABLE

    def test_suspended_is_not_harmless(self):
        """`searchOpen` omits Suspended bracket children by contract. That is a
        gap in the QUERY, not evidence about the ORDER."""
        o = order(SL_ID, status=EL.STATUS_SUSPENDED)
        assert EL.classify_order(o, position_size=-15) != EL.NON_EXECUTABLE

    @pytest.mark.parametrize("status", [0, 9, 42, -1, None, "open"])
    def test_unrecognised_status_is_unknown_not_safe(self, status):
        assert EL.classify_order(order(SL_ID, status=status),
                                 position_size=-15) == EL.UNKNOWN_AUTHORITY

    def test_the_official_enum_is_pinned(self):
        """Client drift must not silently re-interpret every terminality
        decision in the safety layer."""
        assert TopstepXClient.ORDER_STATUS == {
            0: "None", 1: "Open", 2: "Filled", 3: "Cancelled", 4: "Expired",
            5: "Rejected", 6: "Pending", 7: "PendingCancellation",
            8: "Suspended"}
        assert TopstepXClient.TERMINAL_ORDER_STATUSES == EL.TERMINAL_STATUSES
        assert TopstepXClient.ACTIVE_ORDER_STATUSES == EL.ACTIVE_STATUSES


# ══ THE RACE MATRIX ═════════════════════════════════════════════════════════
class TestRaceMatrix:
    """R1-R39. No scenario may end with unintended exposure or a false claim
    of safety."""

    def test_R1_stop_fills_before_cancel(self):
        v = Venue(orders=[order(SL_ID)])
        v.orders[SL_ID]["status"] = EL.STATUS_FILLED
        v.position = 0                      # the stop closed the short itself
        d = converge(v)
        assert v.position == 0 and EL.is_safe_terminal(d)

    def test_R2_stop_fills_while_cancel_in_flight(self):
        v = Venue(orders=[order(SL_ID, status=EL.STATUS_PENDING_CANCELLATION)])
        d = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert d["state"] == EL.E2_PROVE_TERMINAL
        assert d["action"] == EL.ACTION_PROVE, "must not proceed on an in-flight cancel"

    def test_R3_cancel_confirms_before_close(self):
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        d = converge(v)
        assert v.position == 0 and EL.is_safe_terminal(d)

    def test_R4_target_fills_during_handling(self):
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        v.orders[TP_ID]["status"] = EL.STATUS_FILLED
        v.position = 0
        d = converge(v)
        assert v.position == 0 and EL.is_safe_terminal(d)

    def test_R5_R6_flat_position_with_working_child_is_never_terminal(self):
        """Flat alone is not success -- that was the state 86ms before LONG 15."""
        d = EL.plan(position_size=0, orders=[order(SL_ID)], owns=owns)
        assert not EL.is_safe_terminal(d)
        assert d["action"] == EL.ACTION_CANCEL

    def test_R7_cancelled_status_with_fill_volume_moved_the_position(self):
        o = order(SL_ID, status=EL.STATUS_CANCELLED)
        o["fill_volume"] = 15
        assert EL.STATUS_CANCELLED in EL.POSITION_MAY_HAVE_MOVED
        assert EL.classify_order(o, position_size=-15) == EL.NON_EXECUTABLE

    def test_R8_R9_unreadable_position_halts(self):
        d = EL.plan(position_size=None, orders=[], owns=owns)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert d["terminal_success"] is False

    def test_R10_partial_entry_remainder_is_in_the_authority_set(self):
        """SELL 15 -> 8 fill -> flatten 8 -> remaining SELL 7 fills -> SHORT 7.
        Same defect class as the orphan stop, different order."""
        remainder = order(ENTRY_ID, side=1, size=7, parent=ENTRY_ID)
        found = EL.exposure_authority_set([remainder], owns=owns, position_size=-8)
        assert remainder in found["executable_ours"]

    def test_R11_partial_protective_fill(self):
        o = order(SL_ID, status=EL.STATUS_OPEN, size=7)
        found = EL.exposure_authority_set([o], owns=owns, position_size=-8)
        assert found["executable_ours"]

    def test_R13_duplicate_invocation_is_idempotent(self):
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        converge(v)
        again = converge(v)
        assert v.position == 0
        assert EL.is_safe_terminal(again), "second invocation must not act"

    def test_R17_unknown_broker_response_halts(self):
        d = EL.plan(position_size=-15, orders=[order(SL_ID, status=99)], owns=owns)
        assert d["state"] == EL.E9_INCIDENT_HALT

    def test_R18_already_flat_with_stale_child(self):
        v = Venue(position=0, orders=[order(SL_ID)])
        d = converge(v)
        assert v.position == 0 and EL.is_safe_terminal(d)

    def test_R19_reversal_already_exists_when_handler_wakes(self):
        """LONG 15 with nothing of ours working -> close MEASURED exposure."""
        v = Venue(position=15, orders=[], fires=False)
        d = EL.plan(position_size=15, orders=[], owns=owns)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["close_size"] == 15 and d["close_side"] == "sell"

    def test_R20_R28_discovery_does_not_depend_on_mission_lineage(self):
        """Today's mission held protective_order_ids=[] while the venue had a
        working SL. Discovery must come from venue truth."""
        found = EL.exposure_authority_set([order(SL_ID)], owns=owns,
                                          position_size=-15)
        assert found["executable_ours"], "venue-side lineage must suffice"

    def test_R21_R22_remainder_cancelled_before_close(self):
        v = Venue(position=-8, orders=[order(ENTRY_ID, side=1, size=7),
                                       order(SL_ID)])
        first = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert first["action"] == EL.ACTION_CANCEL
        assert ENTRY_ID in first["order_ids"], "entry remainder must be neutralised"

    def test_R23_close_in_flight_blocks_a_second_close(self):
        d = EL.plan(position_size=-15, orders=[], owns=owns,
                    close_state=EL.CLOSE_ACKNOWLEDGED)
        assert d["action"] == EL.ACTION_PROVE
        assert "second close" in d["detail"]

    def test_R24_unknown_close_outcome_halts(self):
        d = EL.plan(position_size=-15, orders=[], owns=owns,
                    close_state=EL.CLOSE_STATE_UNKNOWN)
        assert d["state"] == EL.E9_INCIDENT_HALT

    def test_R25_emergency_naked_is_explicit(self):
        """We cancelled valid protection; the position is genuinely exposed.
        Name it rather than defining it away."""
        d = EL.plan(position_size=-15, orders=[], owns=owns)
        assert d["state"] == EL.E3A_EMERGENCY_NAKED
        assert d["naked"] is True

    def test_R26_filled_is_terminal_and_position_must_be_reread(self):
        o = order(SL_ID, status=EL.STATUS_FILLED)
        assert EL.classify_order(o, position_size=-15) == EL.NON_EXECUTABLE
        assert EL.STATUS_FILLED in EL.POSITION_MAY_HAVE_MOVED

    def test_R27_absence_is_never_terminality(self):
        """No count of negative observations promotes UNKNOWN to safe."""
        d = EL.plan(position_size=0, orders=[], owns=owns)
        assert EL.is_safe_terminal(d), "an empty venue read with flat position"
        # ...but an order the venue reports with no status is NOT terminal:
        assert EL.classify_order({"id": SL_ID}, position_size=0) == EL.UNKNOWN_AUTHORITY

    def test_R29_unowned_order_is_never_cancelled(self):
        v = Venue(position=0, orders=[order(999, parent=None)])
        d = EL.plan(position_size=0, orders=v.working(), owns=never_owns)
        assert d["action"] != EL.ACTION_CANCEL
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert "provably ours" in d["detail"]

    def test_R30_safe_terminal_requires_both_conditions(self):
        v = Venue(orders=[order(SL_ID), order(TP_ID)])
        d = converge(v)
        assert v.position == 0
        assert not v.working(), "no old-trade order may remain executable"
        assert EL.is_safe_terminal(d)

    def test_R31_unproven_ownership_escalates_rather_than_resolving(self):
        """Safety and non-interference genuinely conflict here. Escalate."""
        d = EL.plan(position_size=0, orders=[order(999, parent=None)],
                    owns=never_owns)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert d["position_responsibility"] == "ACTIVE"

    @pytest.mark.parametrize("status,terminal", [
        (EL.STATUS_PENDING_CANCELLATION, False),   # R32
        (EL.STATUS_SUSPENDED, False),              # R33
        (EL.STATUS_EXPIRED, True),                 # R35
        (EL.STATUS_REJECTED, True),                # R36
    ])
    def test_R32_R33_R35_R36_status_semantics(self, status, terminal):
        got = EL.classify_order(order(SL_ID, status=status), position_size=-15)
        assert (got == EL.NON_EXECUTABLE) is terminal

    def test_R34_suspended_child_must_be_discoverable(self):
        """searchOpen omits it; discovery must ask for it explicitly."""
        assert EL.STATUS_SUSPENDED in EL.discovery_statuses()
        assert set(EL.discovery_statuses()) == set(EL.ACTIVE_STATUSES)

    def test_R37_unknown_future_status_halts(self):
        d = EL.plan(position_size=-15, orders=[order(SL_ID, status=12)], owns=owns)
        assert d["state"] == EL.E9_INCIDENT_HALT


# ══ INCIDENT_HALT IS NOT SUCCESS ════════════════════════════════════════════
class TestIncidentHalt:

    def test_halt_keeps_responsibility_active(self):
        d = EL.plan(position_size=-15, orders=[order(SL_ID, status=99)], owns=owns)
        assert d["terminal_success"] is False
        assert d["new_entry_authority"] is False
        assert d["blind_mutation"] is False
        assert d["venue_reconciliation"] is True
        assert d["operator_alert"] is True
        assert d["position_responsibility"] == "ACTIVE"

    def test_halt_is_not_safe_terminal(self):
        d = EL.plan(position_size=None, orders=[], owns=owns)
        assert not EL.is_safe_terminal(d)

    def test_convergence_budget_is_bounded(self):
        """A venue that never resolves is an incident, not a licence to poll."""
        d = EL.plan(position_size=-15, orders=[order(SL_ID)], owns=owns,
                    round_index=EL.DEFAULT_MAX_ROUNDS)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert "budget" in d["detail"]


# ══ THE PLANNER DECIDES; IT DOES NOT ACT ════════════════════════════════════
class TestPlannerIsPure:

    def test_it_submits_nothing(self):
        import inspect
        src = inspect.getsource(EL)
        for banned in ("place_order", "cancel_order(", "close_position(",
                       "modify_order", "requests", "_post("):
            assert banned not in src, banned

    def test_a_throwing_ownership_test_proves_nothing(self):
        def explodes(_o):
            raise RuntimeError("lineage lookup failed")
        found = EL.exposure_authority_set([order(SL_ID)], owns=explodes,
                                          position_size=-15)
        assert found["unknown"], "an ownership test that throws is not a 'no'"

    #: Modules permitted to DRIVE the planner -- to call `plan()` and act on the
    #: decision. Each one is a liquidation owner and each is separately
    #: regression-bound. Adding a name here means adding a place where the
    #: account can be closed, so the list is short on purpose.
    LIQUIDATION_OWNERS = ["topstepx_execution_runner.py", "topstepx_hard_flatten.py"]

    def _scan(self, predicate):
        hits = []
        for root, _dirs, files in os.walk(os.path.join(ROOT, "src")):
            if "__pycache__" in root or "rule_governance" in root:
                continue
            for name in files:
                if not name.endswith(".py") or name == "topstepx_emergency_liquidation.py":
                    continue
                with open(os.path.join(root, name), encoding="utf-8-sig") as fh:
                    if predicate(fh.read()):
                        hits.append(name)
        return sorted(hits)

    def test_only_sanctioned_owners_drive_the_planner(self):
        """A second caller deciding its own liquidation policy would be a second
        safety authority.

        THE GUARD NOW TESTS THE RIGHT PROPOSITION. It used to forbid IMPORTING
        this module at all, which conflated two different things: deciding when
        to close an account, and reading the official status enum this module
        happens to own. `topstepx_order_discovery` re-exports that vocabulary
        precisely so a second, quietly divergent copy of it cannot appear -- it
        submits nothing and plans nothing. What must stay scarce is `plan()`.
        """
        drivers = self._scan(lambda src: "EL.plan(" in src)
        assert drivers == sorted(self.LIQUIDATION_OWNERS), drivers

    def test_nothing_else_reimplements_the_status_vocabulary(self):
        """One enum, re-exported. Two copies drift, and a status the venue means
        as Suspended becoming a status we treat as terminal is a silent orphan.
        """
        copies = self._scan(
            lambda src: "STATUS_PENDING_CANCELLATION = 7" in src
            or "STATUS_SUSPENDED = 8" in src)
        assert copies == [], copies


# ══ THE WIRED SAFETY AUTHORITY ══════════════════════════════════════════════
class TestEmergencyFlattenIsWired:
    """`emergency_flatten` is the certified safety authority for all nine call
    sites. These assert the wiring, not the planner."""

    @staticmethod
    def _source():
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        return inspect.getsource(ExecutionRunner.emergency_flatten)

    def test_it_drives_the_planner(self):
        assert "EL.plan" in self._source()

    def test_children_are_cancelled_before_the_close(self):
        """The ordering that closes the race, asserted structurally."""
        src = self._source()
        assert src.index("ACTION_CANCEL") < src.index("ACTION_CLOSE")

    def test_a_failed_cancel_is_not_treated_as_cancelled(self):
        src = self._source()
        assert "proves nothing" in src.lower() or "not assumed gone" in src.lower()

    def test_an_ambiguous_close_becomes_unknown_not_retried(self):
        src = self._source()
        assert "CLOSE_STATE_UNKNOWN" in src

    def test_flattened_requires_safe_terminal_and_confirmation(self):
        """`flattened: True` may never mean 'we sent the calls'."""
        src = self._source()
        assert "bool(safe and confirmed" in src.replace(" ", " ")

    def test_discovery_uses_v2_query_with_no_status_filter(self):
        """`searchOpen` omits Suspended bracket children by venue contract, so
        discovery uses v2/query -- and passes NO status filter at all.

        Filtering even to the four statuses we recognise would let the venue
        hide a future state our enum has not heard of, and the planner's
        fail-closed handling of an unknown status is worthless if acquisition
        removes that status first."""
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner._emergency_venue_read)
        assert "query_orders" in src
        assert "statuses=" not in src, "a status filter can hide an unknown state"
        assert "NO STATUS FILTER" in src

    def test_a_fallback_read_is_labelled_incomplete(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner._emergency_venue_read)
        assert "INCOMPLETE" in src

    def test_unreadable_position_is_never_coerced_to_flat(self):
        """'I cannot see the position' and 'there is no position' are the two
        states this unit exists to keep apart."""
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner._signed_position)
        assert "return None" in src

    def test_signed_position_reads_short_as_negative(self):
        from broker.topstepx_execution_runner import ExecutionRunner

        class C:
            id = "CON.F.US.MNQ.U26"

        r = ExecutionRunner.__new__(ExecutionRunner)
        r.contract = C()
        assert r._signed_position([{"contract_id": C.id, "size": 15, "type": 2}]) == -15
        assert r._signed_position([{"contract_id": C.id, "size": 15, "type": 1}]) == 15
        assert r._signed_position([]) == 0
        assert r._signed_position([{"contract_id": C.id, "size": None}]) is None

# ══ R38 / R39 — TERMINAL ORDER != UNCHANGED POSITION ════════════════════════
class TestTerminalOrderStillMovedThePosition:
    """An order can be finished AND have changed the account on its way out.
    Acting on a remembered position after that is how a close becomes a
    reversal."""

    def test_R38_cancelled_with_fill_volume_requires_position_reread(self):
        o = order(SL_ID, status=EL.STATUS_CANCELLED)
        o["fill_volume"] = 15
        assert EL.classify_order(o, position_size=-15) == EL.NON_EXECUTABLE
        assert EL.STATUS_CANCELLED in EL.POSITION_MAY_HAVE_MOVED
        # the planner never closes from a remembered size: it re-reads first
        import inspect
        src = inspect.getsource(EL.plan)
        assert "close MEASURED exposure" in src or "MEASURED" in src

    def test_R38_partial_cancel_fill_leaves_measured_exposure(self):
        """Cancelled after filling 8 of 15: exposure moved -15 -> -7."""
        v = Venue(position=-7, orders=[], fires=False)
        d = EL.plan(position_size=v.position, orders=[], owns=owns)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["close_size"] == 7, "must close what EXISTS, not what we remember"

    def test_R39_filled_order_requires_position_reread(self):
        o = order(SL_ID, status=EL.STATUS_FILLED)
        assert EL.classify_order(o, position_size=0) == EL.NON_EXECUTABLE
        assert EL.STATUS_FILLED in EL.POSITION_MAY_HAVE_MOVED

    def test_R39_stop_filled_into_flat_is_the_incident_shape(self):
        """The stop is terminal, and the account is now LONG because of it."""
        v = Venue(position=15, orders=[order(SL_ID, status=EL.STATUS_FILLED)],
                  fires=False)
        d = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["close_size"] == 15 and d["close_side"] == "sell"


# ══ PRODUCTION BOUNDARY — ACQUISITION MAY NOT HIDE A STATE ══════════════════
class TestUnknownStatusSurvivesDiscovery:
    """The planner failing closed on an unrecognised status is worthless if the
    QUERY filters that status out before classification. A consumer can only
    reason over facts the producer lets reach it."""

    class Session:
        def __init__(self, orders, positions=None, fail_query=False):
            self._orders = orders
            self._positions = positions or []
            self.fail_query = fail_query
            self.query_calls = []

        def open_positions(self):
            return list(self._positions)

        def query_orders(self, *, statuses=None, contract_id=None):
            self.query_calls.append({"statuses": statuses,
                                     "contract_id": contract_id})
            if self.fail_query:
                raise RuntimeError("v2/query unavailable")
            return [dict(o) for o in self._orders]

        def open_orders(self):
            return [dict(o) for o in self._orders
                    if o.get("status") in EL.ACTIVE_STATUSES]

    def _runner(self, session):
        from broker.topstepx_execution_runner import ExecutionRunner

        class C:
            id = "CON.F.US.MNQ.U26"
        r = ExecutionRunner.__new__(ExecutionRunner)
        r.contract = C()
        r.session = session
        return r

    def test_discovery_does_not_filter_by_status(self):
        """No status filter -> the venue cannot hide a state we have not
        heard of."""
        s = self.Session([order(SL_ID)])
        read = self._runner(s)._emergency_venue_read()
        assert read["readable"]
        assert s.query_calls[0]["statuses"] is None, s.query_calls

    def test_an_unrecognised_status_reaches_the_planner_and_halts(self):
        """THE BOUNDARY SPECIMEN. Owned old-trade order, status the enum does
        not know, position open -> UNKNOWN -> E9 -> no close."""
        unknown = dict(order(SL_ID), status=99)
        s = self.Session([unknown],
                         positions=[{"contract_id": "CON.F.US.MNQ.U26",
                                     "size": 15, "type": 2}])
        r = self._runner(s)
        read = r._emergency_venue_read()
        assert any(o["status"] == 99 for o in read["orders"]), \
            "acquisition dropped the unknown status"
        size = r._signed_position(read["positions"])
        d = EL.plan(position_size=size, orders=read["orders"], owns=owns)
        assert d["state"] == EL.E9_INCIDENT_HALT
        assert d["action"] == EL.ACTION_HALT
        assert d["terminal_success"] is False


# ══ A NARROWER VIEW MAY NEVER GRANT SAFETY ══════════════════════════════════
class TestFallbackNeverUpgradesIncompleteTruth:

    def test_fallback_is_labelled_incomplete(self):
        s = TestUnknownStatusSurvivesDiscovery.Session(
            [order(SL_ID)], fail_query=True)
        r = TestUnknownStatusSurvivesDiscovery()._runner(s)
        read = r._emergency_venue_read()
        assert read["discovery"] == "open_orders_fallback_INCOMPLETE"
        assert read["errors"], "the query failure must be recorded, not swallowed"

    def test_incomplete_discovery_may_not_produce_safe_terminal(self):
        """v2/query unavailable + searchOpen shows no children + position open
        -> completeness UNKNOWN -> never a clean flatten claim.

        `searchOpen` omits Suspended bracket children by venue contract, so its
        silence is a gap in the QUERY, never evidence about the ACCOUNT."""
        s = TestUnknownStatusSurvivesDiscovery.Session(
            [], positions=[{"contract_id": "CON.F.US.MNQ.U26", "size": 15,
                            "type": 2}], fail_query=True)
        r = TestUnknownStatusSurvivesDiscovery()._runner(s)
        read = r._emergency_venue_read()
        assert read["discovery"] == "open_orders_fallback_INCOMPLETE"
        # The planner would see an empty order list and a live position. It may
        # propose a close, but the RUN must never report a clean flatten from
        # an admittedly incomplete view.
        d = EL.plan(position_size=-15, orders=read["orders"], owns=owns)
        assert not EL.is_safe_terminal(d)


# ══ PHASE 9 — RESTART / CRASH DURABILITY ════════════════════════════════════
class TestRestartDurability:
    """A crash mid-convergence must not cause a second close. Every restart
    boundary is reconstructed from VENUE truth, which is why the planner holds
    no memory of its own."""

    def test_A_cancel_submitted_terminality_unknown(self):
        v = Venue(orders=[order(SL_ID, status=EL.STATUS_PENDING_CANCELLATION)])
        d = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert d["action"] == EL.ACTION_PROVE, "must re-read, not assume"

    def test_B_cancel_confirmed_position_open_is_naked_and_resumes(self):
        v = Venue(orders=[order(SL_ID, status=EL.STATUS_CANCELLED)])
        d = EL.plan(position_size=v.position, orders=v.working(), owns=owns)
        assert d["state"] == EL.E3A_EMERGENCY_NAKED
        assert d["naked"] is True

    def test_C_close_acknowledged_fill_pending_does_not_resubmit(self):
        d = EL.plan(position_size=-15, orders=[], owns=owns,
                    close_state=EL.CLOSE_ACKNOWLEDGED)
        assert d["action"] == EL.ACTION_PROVE

    def test_D_ambiguous_close_halts_rather_than_repeating(self):
        d = EL.plan(position_size=-15, orders=[], owns=owns,
                    close_state=EL.CLOSE_STATE_UNKNOWN)
        assert d["state"] == EL.E9_INCIDENT_HALT

    def test_E_partial_close_fill_closes_only_the_remainder(self):
        d = EL.plan(position_size=-4, orders=[], owns=owns)
        assert d["action"] == EL.ACTION_CLOSE and d["close_size"] == 4

    def test_F_flat_with_unresolved_order_is_not_terminal(self):
        d = EL.plan(position_size=0, orders=[order(SL_ID, status=99)], owns=owns)
        assert not EL.is_safe_terminal(d)
        assert d["state"] == EL.E9_INCIDENT_HALT

    def test_G_reverse_exposure_present_at_restart(self):
        d = EL.plan(position_size=15, orders=[], owns=owns)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["close_side"] == "sell" and d["close_size"] == 15

    def test_the_planner_holds_no_cross_call_memory(self):
        """Restart safety rests on this: the planner is a pure function of the
        venue read it is given, so a fresh process reaches the same decision as
        the one that died."""
        args = dict(position_size=-15, orders=[order(SL_ID)], owns=owns)
        assert EL.plan(**args) == EL.plan(**args)

    def test_a_prior_close_is_rediscoverable_by_tag(self):
        """The emergency close must be attributable after restart. Submissions
        carry the mission's custom tag, so a prior close is found by lineage
        rather than by remembering it."""
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner.mission_owns_order)
        assert "customTag" in src or "custom_tag" in src
        assert "parentOrderId" in src or "parent_order_id" in src
