"""TOPSTEP-ABANDON-UNFILLED-ENTRY-ATOMICITY-1.

THE LAST INDEPENDENT LIQUIDATION SEQUENCE. `abandon_unfilled_entry` carried its
own convergence loop:

    cancel parent -> re-read -> CLOSE POSITION -> cancel protective children

Its author had seen a real failure and defended against it: for a partially
filled parent, closing 5 of 12 and cancelling afterwards leaves a window in
which the remaining 7 can fill. That reasoning was right. Its scope was too
narrow -- it stopped the PARENT from creating new exposure before the close and
left the protective CHILDREN executable across it, which is exactly the
ordering `TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` removed from
`emergency_flatten` after a surviving stop reversed a flat account 86ms later.

Two liquidation sequences meant each defended only against the failure its
author had seen.

THE PARENT WAS NEVER A SPECIAL CASE. `mission_owns_order` proves the entry order
by id, so the certified planner already treats an unfilled remainder as a member
of the old-trade exposure set and neutralises it in the same batch as the
children, before any close:

    an old-trade order can create unintended exposure whenever its executable
    quantity exceeds the REMAINING opposing position

SELL 15 entry, 8 filled, 7 working: closing BUY 8 leaves SHORT 7. Same defect
class as the stop, and now the same defence.

WHAT IS PRESERVED. Abandonment is a LIFECYCLE decision and liquidation is not.
The attempt's own proof -- parent terminal, position zero, no mission-owned
orders -- still gates whether a recovery may be called clean.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_emergency_liquidation as EL          # noqa: E402
from broker import topstepx_execution_runner as R                # noqa: E402
from broker.topstepx_combine_risk import build_bracket           # noqa: E402

ENTRY = 7001
STOP = 7002
TARGET = 7003
FOREIGN = 9999

BUY, SELL = 0, 1


class Contract:
    id = "CON.F.US.MNQ.U26"
    name = "MNQU26"
    tick_size = 0.25
    tick_value = 0.5


MNQ = Contract()


class Venue:
    """A venue that can race: orders may fill while we are cancelling them.

    Every row carries `status` and `side` because `OrderModel` requires them and
    the planner reads an order with neither as UNKNOWN authority. A fixture that
    omits them is asserting a venue shape that does not exist.
    """

    def __init__(self, *, parent_working=True, position=0, children=(),
                 fill_on_parent_cancel=0, fill_on_child_cancel=0,
                 parent_cancel_fails=False, parent_cancel_ignored=False,
                 close_fails=False, blind=False):
        self.parent_working = parent_working
        self.position = position                    # SIGNED
        self._children = [dict(c) for c in children]
        self.fill_on_parent_cancel = fill_on_parent_cancel
        self.fill_on_child_cancel = fill_on_child_cancel
        self.parent_cancel_fails = parent_cancel_fails
        self.parent_cancel_ignored = parent_cancel_ignored
        self.close_fails = close_fails
        self.blind = blind
        self.calls = []                             # ordered (kind, arg)
        self.cancelled = []
        self.closed = []

    # ── reads ───────────────────────────────────────────────────────────────
    def _rows(self):
        rows = [dict(c) for c in self._children]
        if self.parent_working:
            rows.append({"id": ENTRY, "contract_id": MNQ.id, "type": 2,
                         "size": 12, "status": 1, "side": BUY})
        return rows

    def query_orders(self, *, statuses=None, contract_id=None):
        if self.blind:
            raise RuntimeError("venue unreadable")
        rows = self._rows()
        if contract_id:
            rows = [o for o in rows if o["contract_id"] == contract_id]
        return rows

    def open_orders(self):
        if self.blind:
            raise RuntimeError("venue unreadable")
        return self._rows()

    def open_positions(self):
        if self.blind:
            raise RuntimeError("venue unreadable")
        if not self.position:
            return []
        return [{"contract_id": MNQ.id, "size": abs(self.position),
                 "type": 1 if self.position > 0 else 2}]

    def recent_trades(self):
        return []

    def order_by_id(self, order_id):
        for row in self._rows():
            if str(row["id"]) == str(order_id):
                return dict(row)
        return None

    # ── writes ──────────────────────────────────────────────────────────────
    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        if str(order_id) == str(ENTRY):
            if self.parent_cancel_fails:
                from broker.topstepx_client import TopstepXError
                raise TopstepXError("cancel rejected")
            if self.fill_on_parent_cancel:          # it filled first
                self.position += self.fill_on_parent_cancel
                self.fill_on_parent_cancel = 0
            if not self.parent_cancel_ignored:
                self.parent_working = False
            self.cancelled.append(order_id)
            return {"success": True}
        if self.fill_on_child_cancel:
            self.position += self.fill_on_child_cancel
            self.fill_on_child_cancel = 0
        self.cancelled.append(order_id)
        self._children = [c for c in self._children if c["id"] != order_id]
        return {"success": True}

    def close_position(self, contract_id):
        self.calls.append(("close", contract_id))
        if self.close_fails:
            raise RuntimeError("venue refused the close")
        self.closed.append(contract_id)
        self.position = 0
        return {"success": True}


def child(oid, *, side, size=12, status=1, otype=4, parent=ENTRY):
    row = {"id": oid, "contract_id": MNQ.id, "type": otype, "side": side,
           "size": size, "status": status}
    if parent is not None:
        row["parent_order_id"] = parent
    return row


def runner(venue):
    r = R.ExecutionRunner(session=venue, account_fingerprint="acct:test",
                          contract=MNQ)
    r.execution_lane = "production"
    r.order_id = ENTRY
    # PRODUCTION CAPS, not the smoke defaults. `build_bracket` deliberately
    # falls back to the stricter 10-point smoke ceiling when a caller forgets,
    # which is the safe direction for a default -- and the wrong shape for a
    # fixture modelling a production entry.
    r.geometry = build_bracket(direction="bullish", entry_price=30000.0,
                               invalidation_level=29996.0, target_price=30012.0,
                               contract=MNQ, size=12, max_risk_usd=250.0,
                               max_stop_points=40.0, min_reward_to_risk=1.0,
                               max_contracts=15)
    r.max_risk_usd, r.max_stop_points = 250.0, 40.0
    r.max_contracts, r.min_reward_to_risk = 15, 1.0
    r.state = R.FILLED
    return r


def kinds(venue):
    return [k for k, _ in venue.calls]


# ══ A1-A2  THE ABANDONMENT STATES ═══════════════════════════════════════════
class TestAbandonmentStates:
    """"unfilled" does not prove venue exposure is zero. The method name is a
    statement of INTENT, never of account state."""

    def test_A1_never_filled_and_already_terminal_mutates_nothing(self):
        v = Venue(parent_working=False, position=0)
        out = runner(v).abandon_unfilled_entry("no fill observed")
        assert out["safe"] is True
        assert v.calls == [], "nothing to do, and nothing was done"

    def test_A1_never_filled_but_parent_still_working_cancels_it(self):
        v = Venue(parent_working=True, position=0)
        out = runner(v).abandon_unfilled_entry("deadline")
        assert out["safe"] is True
        assert ("cancel", ENTRY) in v.calls
        assert v.closed == [], "no position, so no close"

    def test_A2_partial_fill_neutralises_the_remainder_before_closing(self):
        """THE PARENT REMAINDER IS OLD-TRADE AUTHORITY. SELL 15 entry with 8
        filled and 7 working: closing the 8 leaves SHORT 7."""
        v = Venue(parent_working=True, position=8)
        out = runner(v).abandon_unfilled_entry("8 of 12 at deadline")
        assert out["safe"] is True
        assert kinds(v).index("cancel") < kinds(v).index("close")
        assert v.position == 0

    def test_A2_the_close_is_measured_never_remembered(self):
        v = Venue(parent_working=True, position=8)
        out = runner(v).abandon_unfilled_entry("partial")
        closes = out["liquidation"]["closes"]
        assert closes and closes[0]["size"] == 8


# ══ A3-A4  THE ORDERING SPECIMEN ════════════════════════════════════════════
class TestOrderingAtomicity:

    def test_A3_children_are_neutralised_before_the_close(self):
        v = Venue(parent_working=True, position=12,
                  children=[child(STOP, side=SELL), child(TARGET, side=SELL,
                                                          otype=1)])
        out = runner(v).abandon_unfilled_entry("late fill")
        assert out["safe"] is True
        first_close = kinds(v).index("close")
        cancels = [i for i, k in enumerate(kinds(v)) if k == "cancel"]
        assert cancels, "the children must be cancelled"
        assert max(cancels) < first_close, (
            f"a child survived the close: {v.calls}")
        assert STOP in v.cancelled and TARGET in v.cancelled

    def test_A4_the_2026_08_26_specimen_cannot_close_first(self):
        """A protective stop that survives the close is an ENTRY the instant the
        account goes flat. That is the whole incident."""
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL)])
        runner(v).abandon_unfilled_entry("stop must not outlive the position")
        assert kinds(v) == ["cancel", "close"], v.calls

    def test_A4_no_close_happens_while_a_child_is_still_executable(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL)])
        r = runner(v)
        original = v.close_position

        def guarded(cid):
            live = [c for c in v._children if c["status"] in EL.ACTIVE_STATUSES]
            assert not live, f"closing with {live} still executable"
            return original(cid)

        v.close_position = guarded
        r.abandon_unfilled_entry("guarded")


# ══ A5-A7  RACES ════════════════════════════════════════════════════════════
class TestRaces:

    def test_A5_a_position_that_closes_externally_is_not_closed_again(self):
        v = Venue(parent_working=True, position=5)

        def vanish(order_id):
            v.position = 0                       # someone else flattened it
            return Venue.cancel_order(v, order_id)

        v.cancel_order = vanish
        out = runner(v).abandon_unfilled_entry("external close")
        assert out["safe"] is True
        assert v.closed == [], "no blind close on a venue-proven flat account"

    def test_A6_a_child_filling_during_cancellation_is_measured_afresh(self):
        """The cancel raced a fill and REVERSED the exposure. The close must act
        on what exists now, never on what was read before."""
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL)], fill_on_child_cancel=-24)
        out = runner(v).abandon_unfilled_entry("child raced the cancel")
        closes = out["liquidation"]["closes"]
        assert closes, "the reversed exposure must be closed"
        assert closes[0]["size"] == 12 and closes[0]["side"] == "buy", closes
        assert v.position == 0

    def test_A7_the_entry_remainder_filling_during_cancellation_is_flattened(self):
        v = Venue(parent_working=True, position=0, fill_on_parent_cancel=7)
        out = runner(v).abandon_unfilled_entry("remainder raced the cancel")
        assert out["safe"] is True
        assert any(st["step"] == "close_position" and st["ok"]
                   for st in out["steps"]), out["steps"]
        assert v.position == 0


# ══ A8-A11  AMBIGUITY ═══════════════════════════════════════════════════════
class TestAmbiguityLaws:

    def test_A8_an_unproven_executable_order_halts_before_any_mutation(self):
        """61d5329 preserved: ownership ambiguity gates BEFORE cancellation, so
        known-owned protection is never stripped for a close that cannot run."""
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL),
                            child(FOREIGN, side=BUY, parent=None)])
        out = runner(v).abandon_unfilled_entry("mixed book")
        assert out["safe"] is False
        assert v.calls == [], "nothing was touched"
        assert out["liquidation"]["emergency_reason"] == EL.OWNERSHIP_AMBIGUOUS

    def test_A9_an_unknown_status_order_halts(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(FOREIGN, side=BUY, status=99, parent=None)])
        out = runner(v).abandon_unfilled_entry("unknown status")
        assert out["safe"] is False
        assert v.closed == []

    def test_A10_a_terminal_unproven_order_does_not_wedge(self):
        """History is not a block. A finished order cannot create exposure."""
        v = Venue(parent_working=False, position=12,
                  children=[child(FOREIGN, side=BUY, status=EL.STATUS_FILLED,
                                  parent=None)])
        out = runner(v).abandon_unfilled_entry("historical order present")
        assert out["safe"] is True
        assert v.closed == [MNQ.id]
        assert FOREIGN not in v.cancelled

    def test_A11_a_cancel_the_venue_ignores_never_yields_safety(self):
        """A 2xx is not proof. The re-read is."""
        v = Venue(parent_working=True, position=0, parent_cancel_ignored=True)
        r = runner(v)
        out = r.abandon_unfilled_entry("silent cancel")
        assert out["safe"] is False
        assert out["final_state"]["parent_working"] is True
        assert r.state == R.RESIDUAL_ORDERS

    def test_A11_a_rejected_cancel_is_reported_and_bounded(self):
        v = Venue(parent_working=True, position=5, parent_cancel_fails=True)
        out = runner(v).abandon_unfilled_entry("cancel rejected")
        assert out["safe"] is False
        assert any(st["step"] == "cancel_parent" and st["ok"] is False
                   for st in out["steps"]), out["steps"]

    def test_A12_an_ambiguous_close_is_never_blindly_repeated(self):
        v = Venue(parent_working=False, position=12, close_fails=True)
        out = runner(v).abandon_unfilled_entry("close refused")
        assert out["safe"] is False
        assert kinds(v).count("close") == 1, "a second close could reverse it"


# ══ A13-A15  RESTART ════════════════════════════════════════════════════════
class TestRestartConvergence:
    """Every boundary is reconstructed from VENUE truth, which is why the
    planner holds no memory of its own."""

    def test_A13_restart_after_a_cancel_was_submitted(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL,
                                  status=EL.STATUS_PENDING_CANCELLATION)])
        out = runner(v).abandon_unfilled_entry("restart mid-cancel")
        assert out["safe"] is False, "PendingCancellation is not Cancelled"
        assert v.closed == []

    def test_A14_restart_after_children_terminal_but_before_the_close(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL, status=EL.STATUS_CANCELLED)])
        out = runner(v).abandon_unfilled_entry("restart pre-close")
        assert out["safe"] is True
        assert v.closed == [MNQ.id]

    def test_A15_restart_after_the_close_filled_does_not_close_again(self):
        v = Venue(parent_working=False, position=0,
                  children=[child(STOP, side=SELL, status=EL.STATUS_CANCELLED)])
        out = runner(v).abandon_unfilled_entry("restart post-close")
        assert out["safe"] is True
        assert v.closed == [], "the account is already flat"

    def test_A16_flat_with_an_unresolved_child_is_not_safe_terminal(self):
        v = Venue(parent_working=False, position=0,
                  children=[child(FOREIGN, side=BUY, status=99, parent=None)])
        out = runner(v).abandon_unfilled_entry("flat but unclear")
        assert out["liquidation"]["safe_terminal"] is False


# ══ A17-A20  ARCHITECTURE ═══════════════════════════════════════════════════
class TestArchitecture:

    def test_A17_an_oversized_child_cannot_reverse_through_abandonment(self):
        """SHORT 6 against an owned BUY stop for 15 flattens six and goes LONG
        NINE. The child is neutralised first, so the reversal cannot occur."""
        v = Venue(parent_working=False, position=-6,
                  children=[child(STOP, side=BUY, size=15)])
        out = runner(v).abandon_unfilled_entry("oversized child")
        assert out["safe"] is True
        assert max(i for i, k in enumerate(kinds(v)) if k == "cancel") \
            < kinds(v).index("close")
        assert v.position == 0

    def test_A18_bookkeeping_cannot_claim_clean_while_venue_state_is_unknown(self):
        v = Venue(blind=True)
        out = runner(v).abandon_unfilled_entry("blind venue")
        assert out["safe"] is False
        assert out["final_state"]["readable"] is False

    def test_A19_no_independent_close_before_cancel_sequence_remains(self):
        import ast
        import inspect
        body = ast.unparse(ast.parse(inspect.getsource(
            R.ExecutionRunner.abandon_unfilled_entry).lstrip()))
        for forbidden in ("self.session.close_position", "self.session.cancel_order",
                          "self.session.modify_order", "self.session.place_order"):
            assert forbidden not in body, forbidden
        assert "self.emergency_flatten(" in body

    def test_A20_exactly_one_position_closing_authority_exists(self):
        """The number may only go down. Every additional closer is another place
        the certified sequence can be got wrong."""
        import ast
        import inspect
        closers = []
        for node in ast.walk(ast.parse(
                inspect.getsource(R.ExecutionRunner).lstrip())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    "self.session.close_position(" in ast.unparse(node).replace(" ", ""):
                closers.append(node.name)
        assert closers == ["emergency_flatten"], closers

    def test_abandonment_semantics_are_not_collapsed_into_the_liquidation(self):
        """A safe liquidation that left the parent working is NOT a completed
        abandonment. Two lifecycles, two verdicts."""
        v = Venue(parent_working=True, position=0, parent_cancel_ignored=True)
        out = runner(v).abandon_unfilled_entry("distinct lifecycles")
        assert out["liquidation"]["safe_terminal"] is False
        assert out["safe"] is False
        assert out["reason"] == "distinct lifecycles"
        assert "final_state" in out and "liquidation" in out


# ══ THE FOUR PRIOR SAFETY UNITS ═════════════════════════════════════════════
class TestPriorUnitsPreserved:

    def test_511a493_cancel_precedes_close_for_proven_owned_children(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL)])
        runner(v).abandon_unfilled_entry("regression")
        assert kinds(v).index("cancel") < kinds(v).index("close")

    def test_7c2dd5b_discovery_is_unfiltered_and_sees_suspended(self):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL, status=EL.STATUS_SUSPENDED)])
        runner(v).abandon_unfilled_entry("suspended child")
        assert STOP in v.cancelled, "a Suspended child must be discoverable"

    def test_4301b31_no_instrument_equality_ownership(self):
        v = Venue(parent_working=False, position=0,
                  children=[child(FOREIGN, side=BUY, parent=None)])
        runner(v).abandon_unfilled_entry("foreign order")
        assert FOREIGN not in v.cancelled

    def test_61d5329_ambiguity_blocks_mutation_symmetrically(self):
        for position in (0, 12, -12):
            v = Venue(parent_working=False, position=position,
                      children=[child(FOREIGN, side=BUY, parent=None)])
            runner(v).abandon_unfilled_entry("ambiguous")
            assert v.closed == [] and v.cancelled == [], position

    @pytest.mark.parametrize("status", [EL.STATUS_OPEN, EL.STATUS_PENDING,
                                        EL.STATUS_SUSPENDED])
    def test_every_executable_owned_child_is_neutralised_first(self, status):
        v = Venue(parent_working=False, position=12,
                  children=[child(STOP, side=SELL, status=status)])
        runner(v).abandon_unfilled_entry(f"status {status}")
        assert kinds(v).index("cancel") < kinds(v).index("close")
