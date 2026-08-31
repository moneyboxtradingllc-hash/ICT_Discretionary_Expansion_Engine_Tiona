"""TOPSTEP-UNPROVEN-ORDER-CLOSE-AUTHORITY-1.

THE ASYMMETRY THIS UNIT REMOVED. The shared emergency planner already halted on
an executable order it could not attribute -- but only when the position was
already flat:

    position FLAT + executable UNPROVEN order   ->  HALT
    position OPEN + executable UNPROVEN order   ->  ACTION_CLOSE

Its own halt says "cancelling requires proof; claiming safety requires
certainty; neither is available." That reasoning does not weaken because the
position quantity is nonzero -- it strengthens, because the close is itself the
mutation in question.

THE THEOREM:

    AN EXECUTABLE ORDER WHOSE AUTHORITY IS UNPROVEN MAY NOT BE MUTATED AROUND
    BY CREATING OR CHANGING FLATNESS.

Closing changes the semantic authority of every remaining order on the
contract. The same resting order that was reducing exposure becomes a
reverse-position entry the moment the exposure it opposed is gone -- and we do
not know whose order it is. On 2026-08-26 the bot could not recognise its OWN
bracket (`protective_order_ids` was empty), so "unproven" and "our lost child"
are the same condition seen from two sides.

WHAT THIS UNIT DOES NOT DO. It never blocks on history. An order that is
POSITIVELY terminal cannot create future exposure, so unattributed terminal
orders never become permanent wedges (U10, U11).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_emergency_liquidation as EL    # noqa: E402

MNQ = "CON.F.US.MNQ.U26"
ENTRY_ID = 3451056002
MINE = 3451056003
THEIRS = 555000

BUY, SELL = 0, 1


def o(oid, *, side, size=15, status=EL.STATUS_OPEN, otype=4, parent=None):
    row = {"id": oid, "contract_id": MNQ, "type": otype, "side": side,
           "size": size, "status": status}
    if parent is not None:
        row["parent_order_id"] = parent
    return row


def mine(order):
    """Lineage predicate: only a child of OUR entry is ours."""
    return str((order or {}).get("parent_order_id") or "") == str(ENTRY_ID)


def nobody(_order):
    return False


def halted(decision) -> bool:
    return (decision["action"] == EL.ACTION_HALT
            and decision["state"] == EL.E9_INCIDENT_HALT)


# ══ U1-U5  GEOMETRY GRANTS NOTHING ══════════════════════════════════════════
class TestGeometryIsNotPermission:
    """Side and size are not evidence of ownership, and no arithmetic makes an
    unattributed order safe to close around."""

    def test_U1_short_15_against_an_unproven_buy_stop_15(self):
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY)], owns=nobody)
        assert halted(d) and d["reason"] == EL.OWNERSHIP_AMBIGUOUS
        assert d["action"] != EL.ACTION_CLOSE

    def test_U2_short_6_against_an_unproven_buy_stop_15(self):
        """The exposure invariant, exactly: executable quantity EXCEEDS the
        remaining opposing position. Six flatten and nine become LONG."""
        d = EL.plan(position_size=-6, orders=[o(THEIRS, side=BUY, size=15)],
                    owns=nobody)
        assert halted(d)
        assert d["found"]["unproven"]

    def test_U3_an_apparently_reducing_smaller_order_still_halts(self):
        """SHORT 15 against an unproven BUY 5 looks harmlessly reducing. It is
        not: if it fills before or during the close, the measured quantity the
        close was built on is already wrong."""
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY, size=5)],
                    owns=nobody)
        assert halted(d)

    def test_U4_short_against_an_unproven_same_side_order(self):
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=SELL)], owns=nobody)
        assert halted(d)

    def test_U5_long_against_an_unproven_sell_order(self):
        d = EL.plan(position_size=15, orders=[o(THEIRS, side=SELL)], owns=nobody)
        assert halted(d)

    @pytest.mark.parametrize("size", [-15, -6, -1, 1, 6, 15])
    def test_no_position_quantity_buys_permission(self, size):
        d = EL.plan(position_size=size, orders=[o(THEIRS, side=BUY, size=1)],
                    owns=nobody)
        assert halted(d), size


# ══ U6-U9  EVERY NONTERMINAL STATE ══════════════════════════════════════════
class TestEveryExecutableState:
    """`WORKING` is Open / Pending / PendingCancellation / Suspended, and an
    unrecognised status is UNKNOWN. None of them are absence."""

    @pytest.mark.parametrize("status,label", [
        (EL.STATUS_OPEN, "U6-open"),
        (EL.STATUS_PENDING, "U6-pending"),
        (EL.STATUS_PENDING_CANCELLATION, "U7-pending-cancellation"),
        (EL.STATUS_SUSPENDED, "U8-suspended"),
    ])
    def test_U6_U8_executable_states_halt(self, status, label):
        d = EL.plan(position_size=-15,
                    orders=[o(THEIRS, side=BUY, status=status)], owns=nobody)
        assert halted(d), label
        assert d["reason"] == EL.OWNERSHIP_AMBIGUOUS

    def test_U7_pending_cancellation_is_a_request_not_an_outcome(self):
        """It can still fill. Treating it as gone is how a 'clean' account
        fires."""
        d = EL.plan(position_size=-15,
                    orders=[o(THEIRS, side=BUY,
                              status=EL.STATUS_PENDING_CANCELLATION)],
                    owns=nobody)
        assert d["action"] != EL.ACTION_CLOSE

    def test_U9_an_unknown_future_status_halts(self):
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY, status=99)],
                    owns=nobody)
        assert halted(d)
        assert d["found"]["unknown"], "an unrecognised status is UNKNOWN"

    def test_a_status_the_venue_never_stated_halts(self):
        row = o(THEIRS, side=BUY)
        row.pop("status")
        d = EL.plan(position_size=-15, orders=[row], owns=nobody)
        assert halted(d)


# ══ U10-U11  HISTORY IS NOT A WEDGE ═════════════════════════════════════════
class TestTerminalUnprovenDoesNotBlock:
    """UNPROVEN restricts MUTATION. It may never restrict VISIBILITY, and it
    may never turn a finished order into a permanent block."""

    @pytest.mark.parametrize("status", [EL.STATUS_FILLED, EL.STATUS_CANCELLED,
                                        EL.STATUS_EXPIRED, EL.STATUS_REJECTED])
    def test_U10_U11_a_terminal_unattributed_order_does_not_block(self, status):
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY, status=status)],
                    owns=nobody)
        assert d["action"] == EL.ACTION_CLOSE, status
        assert d["close_size"] == 15 and d["close_side"] == "buy"

    def test_terminality_is_decided_before_ownership_is_consulted(self):
        """Which is why an unattributed FILLED order never reaches `unproven`
        at all -- the bucket is chosen by lifecycle first."""
        found = EL.exposure_authority_set(
            [o(THEIRS, side=BUY, status=EL.STATUS_FILLED)],
            owns=nobody, position_size=-15)
        assert found["terminal"] and not found["unproven"]

    def test_a_terminal_order_is_still_VISIBLE_in_the_authority_set(self):
        found = EL.exposure_authority_set(
            [o(THEIRS, side=BUY, status=EL.STATUS_CANCELLED)],
            owns=nobody, position_size=-15)
        assert len(found["terminal"]) == 1


# ══ U12-U13  THE CERTIFIED PATHS ARE UNCHANGED ══════════════════════════════
class TestPriorSafetyPreserved:

    def test_U12_all_owned_executable_orders_follow_the_normal_path(self):
        """511a493's sequence is untouched when ownership IS proven:
        neutralise -> prove -> re-read -> close measured."""
        d = EL.plan(position_size=-15,
                    orders=[o(MINE, side=BUY, parent=ENTRY_ID)], owns=mine)
        assert d["action"] == EL.ACTION_CANCEL
        assert d["order_ids"] == [MINE]

    def test_U12_owned_pending_cancellation_still_proves_terminal(self):
        d = EL.plan(position_size=-15,
                    orders=[o(MINE, side=BUY, parent=ENTRY_ID,
                              status=EL.STATUS_PENDING_CANCELLATION)],
                    owns=mine)
        assert d["action"] == EL.ACTION_PROVE

    def test_U12_owned_and_neutralised_still_closes_measured_exposure(self):
        d = EL.plan(position_size=-15,
                    orders=[o(MINE, side=BUY, parent=ENTRY_ID,
                              status=EL.STATUS_CANCELLED)], owns=mine)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["close_size"] == 15 and d["naked"] is True

    def test_U13_the_flat_side_halt_is_preserved(self):
        d = EL.plan(position_size=0, orders=[o(THEIRS, side=BUY)], owns=nobody)
        assert halted(d) and d["reason"] == EL.OWNERSHIP_AMBIGUOUS
        assert d["unresolved_live_exposure"] is False

    def test_a_clean_book_still_reaches_safe_terminal(self):
        d = EL.plan(position_size=0, orders=[], owns=mine)
        assert d["state"] == EL.E5_SAFE_TERMINAL
        assert EL.is_safe_terminal(d)


# ══ U14  INCOMPLETE DISCOVERY ═══════════════════════════════════════════════
class TestIncompleteDiscovery:

    def test_U14_an_unreadable_position_halts_before_anything(self):
        d = EL.plan(position_size=None, orders=[], owns=mine)
        assert halted(d)
        assert d["action"] != EL.ACTION_CLOSE

    def test_U14_discovery_must_not_filter_unproven_orders_away(self):
        """UNPROVEN may restrict MUTATION. It may never restrict VISIBILITY --
        an order filtered out before the planner cannot halt anything."""
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner._emergency_venue_read)
        assert "statuses" not in src.split("query_orders(")[1].split(")")[0]
        assert "owns" not in src, "acquisition must not pre-filter by ownership"

    def test_U14_the_authority_set_keeps_unproven_orders(self):
        found = EL.exposure_authority_set([o(THEIRS, side=BUY)], owns=nobody,
                                          position_size=-15)
        assert len(found["unproven"]) == 1
        assert found["any_unresolved"] is True


# ══ U15-U17  AMBIGUITY IS NOT PERMANENT ═════════════════════════════════════
class TestAmbiguityResolves:
    """A halt is a refusal to act on THIS venue read, never a latch. The
    planner is pure, so the next read decides afresh."""

    def test_U15_an_order_that_resolves_terminal_unblocks_the_close(self):
        working = o(THEIRS, side=BUY)
        assert halted(EL.plan(position_size=-15, orders=[working], owns=nobody))
        resolved = dict(working, status=EL.STATUS_CANCELLED)
        after = EL.plan(position_size=-15, orders=[resolved], owns=nobody)
        assert after["action"] == EL.ACTION_CLOSE

    def test_U16_an_order_that_gains_lineage_follows_the_owned_path(self):
        anon = o(THEIRS, side=BUY)
        assert halted(EL.plan(position_size=-15, orders=[anon], owns=mine))
        adopted = dict(anon, parent_order_id=ENTRY_ID)
        after = EL.plan(position_size=-15, orders=[adopted], owns=mine)
        assert after["action"] == EL.ACTION_CANCEL

    def test_U17_a_restart_reconstructs_the_same_halt_from_venue_truth(self):
        args = dict(position_size=-15, orders=[o(THEIRS, side=BUY)], owns=nobody)
        assert EL.plan(**args) == EL.plan(**args)
        assert halted(EL.plan(**args))

    def test_the_halt_carries_no_state_of_its_own(self):
        """Nothing latches: the decision is a pure function of the read."""
        import inspect
        src = inspect.getsource(EL.plan)
        assert "global " not in src


# ══ U18-U20  THE WIRED SURFACES ═════════════════════════════════════════════
class TestWiredCallers:

    def test_U18_missionless_hard_flatten_remains_halted(self):
        from broker import topstepx_hard_flatten as HF

        class V:
            def __init__(self):
                self.cancelled, self.closed = [], []

            def query_orders(self, *, statuses=None, contract_id=None):
                return [o(THEIRS, side=BUY)]

            def open_positions(self):
                return [{"contract_id": MNQ, "size": 15, "type": 2}]

            def cancel_order(self, oid):
                self.cancelled.append(oid)

            def close_position(self, cid):
                self.closed.append(cid)

        class C:
            id = MNQ

        v = V()
        rep = HF.hard_flatten(v, C())
        assert v.closed == [] and v.cancelled == []
        assert rep["flat"] is False

    def test_U19_exactly_one_method_may_close_a_position(self):
        """THE ARCHITECTURAL ASSERTION, and it got stronger.

        This test has now recorded three different answers, which is the whole
        point of keeping it:

            before UNPROVEN-ORDER-CLOSE-AUTHORITY-1
                emergency_flatten, abandon_unfilled_entry
                -- two independent liquidation sequences, each defending only
                   against the failure its author had seen

            after that unit
                still two, but both bound by the ownership law

            now
                ONE

        `abandon_unfilled_entry` delegates account convergence entirely. Its
        abandonment semantics are unchanged; it simply no longer owns a mutation
        authority. Every additional closer is another place the certified
        sequence can be got wrong, so this number may only go down.
        """
        import ast
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner)
        closers = []
        for node in ast.walk(ast.parse(src.lstrip())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "self.session.close_position(" in ast.unparse(node).replace(" ", ""):
                closers.append(node.name)
        assert closers == ["emergency_flatten"], closers
        assert "EL.plan(" in src

    def test_U19_the_late_fill_recovery_path_owns_no_mutation_authority(self):
        """It reached `close_position` on its own, then cancelled the protective
        children AFTERWARDS -- the ordering that reversed a flat account on
        2026-08-26. It now performs no venue mutation at all."""
        import ast
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        body = ast.unparse(ast.parse(
            inspect.getsource(ExecutionRunner.abandon_unfilled_entry).lstrip()))
        for forbidden in ("self.session.close_position", "self.session.cancel_order",
                          "self.session.place_order", "self.session.modify_order"):
            assert forbidden not in body, forbidden
        assert "self.emergency_flatten(" in body

    def test_U19_the_nine_callers_all_call_emergency_flatten(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner)
        assert src.count("self.emergency_flatten(") >= 7, (
            "the runner's emergency callers must go through the one authority")

    def test_U20_the_2026_08_26_specimen_cannot_create_flatness(self):
        """OUR OWN CHILD, LINEAGE LOST. That mission's `protective_order_ids`
        was empty, so the bot could not recognise its own bracket -- which
        presents to the planner as an unattributable executable order beside a
        live position. The old planner closed. Closing is what armed the stop.
        """
        orphan = o(MINE, side=BUY, size=15)          # no parent_order_id
        d = EL.plan(position_size=-15, orders=[orphan], owns=mine)
        assert halted(d)
        assert d["reason"] == EL.OWNERSHIP_AMBIGUOUS
        assert d["unresolved_live_exposure"] is True
        assert d["action"] != EL.ACTION_CLOSE


# ══ THE HALT CONTRACT ═══════════════════════════════════════════════════════
class TestHaltContract:
    """A halt stops MUTATION. It does not end responsibility, and it never
    throws -- an exception at an open position would be abandoning it."""

    def test_the_halt_is_nonterminal_and_keeps_responsibility(self):
        d = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY)], owns=nobody)
        assert d["terminal_success"] is False
        assert d["new_entry_authority"] is False
        assert d["blind_mutation"] is False
        assert d["venue_reconciliation"] is True
        assert d["operator_alert"] is True
        assert d["position_responsibility"] == "ACTIVE"
        assert EL.is_safe_terminal(d) is False

    def test_live_exposure_is_stated_explicitly(self):
        """Never inferred from the absence of a close."""
        live = EL.plan(position_size=-15, orders=[o(THEIRS, side=BUY)],
                       owns=nobody)
        flat = EL.plan(position_size=0, orders=[o(THEIRS, side=BUY)], owns=nobody)
        assert live["unresolved_live_exposure"] is True
        assert flat["unresolved_live_exposure"] is False

    def test_the_planner_never_raises(self):
        for bad in (None, [{"id": None}], ["not a dict"], [{}]):
            EL.plan(position_size=-15, orders=bad, owns=nobody)

    def test_nothing_is_dismantled_for_a_sequence_that_cannot_complete(self):
        """Our own protective leg survives beside an unattributed order.

        Cancelling ours is only worth doing because it makes the CLOSE safe. If
        the close cannot happen, cancelling first strips a live position of real
        protection and halts anyway -- strictly worse than doing nothing.
        """
        d = EL.plan(position_size=-15,
                    orders=[o(MINE, side=BUY, parent=ENTRY_ID),
                            o(THEIRS, side=BUY)],
                    owns=mine)
        assert halted(d)
        assert d["action"] != EL.ACTION_CANCEL
        assert d["found"]["executable_ours"], "ours is seen, and left alone"
