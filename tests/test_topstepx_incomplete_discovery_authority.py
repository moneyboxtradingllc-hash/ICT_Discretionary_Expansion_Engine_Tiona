"""TOPSTEP-INCOMPLETE-DISCOVERY-AUTHORITY-1.

THE SEVENTH DEFECT. The system LABELLED its order view INCOMPLETE and then acted
as if it were complete:

    v2/query down -> searchOpen returns [] -> the planner sees no old-trade
    authority -> it CLOSES the position -> the account is FLAT with a Suspended
    stop still armed -> flattened=True, safe_terminal=True

That is the 2026-08-26 causal family reached through epistemic incompleteness
rather than through close-before-cancel ordering. `_emergency_venue_read` had
always labelled the fallback `open_orders_fallback_INCOMPLETE`; nothing
consumed the label.

    AN INCOMPLETE ORDER SET MAY NEVER BE CONSUMED AS PROOF OF ABSENCE,
    OWNERSHIP-SET COMPLETENESS, PROTECTION ABSENCE, CLOSE PERMISSION, OR
    SAFE_TERMINAL.

THE GATE IS BEFORE THE FIRST MUTATION, NOT THE LAST. Fixing only the final
boolean would still permit the dangerous close. And halting only at the close
would mean cancelling the protection we CAN see and then discovering we may not
legally close -- leaving a live position strictly worse off than doing nothing.

It is a RECOVERABLE epistemic halt: the planner is pure, so the tick on which
authoritative discovery returns re-decides from current venue truth.
"""
import os
import sys

from test_combined_safety_readiness import (                     # noqa: E402
    ENTRY, MNQ_ID, STOP, TARGET, Venue, kinds, order, runner)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_emergency_liquidation as EL          # noqa: E402
from broker import topstepx_order_discovery as DISC              # noqa: E402


class TestIncompleteDiscoveryAuthority:

    def test_D1_open_position_hidden_child_degraded_view_halts_before_close(self):
        v = Venue(position=15, query_fails=True,
                  hidden=[order(STOP, status=DISC.STATUS_SUSPENDED)])
        assert v.open_orders() == [], "searchOpen genuinely omits it"
        out = runner(v).emergency_flatten("D1")
        assert v.closed == [], "NO flatness created around an unseen child"
        assert v.cancelled == []
        assert out["flattened"] is False and out["safe_terminal"] is False
        assert out["emergency_reason"] == EL.DISCOVERY_INCOMPLETE
        assert v._hidden[0]["status"] == DISC.STATUS_SUSPENDED, \
            "the child survives -- and so does the position it is protecting"

    def test_D2_a_visible_owned_stop_is_not_cancelled_under_an_incomplete_view(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        out = runner(v).emergency_flatten("D2")
        assert v.calls == [], "no cancel, no close, no modify"
        assert out["emergency_reason"] == EL.DISCOVERY_INCOMPLETE

    def test_D3_a_visible_stop_plus_a_hidden_sibling_mutates_nothing(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True,
                  hidden=[order(TARGET, otype=1, status=DISC.STATUS_SUSPENDED)])
        runner(v).emergency_flatten("D3")
        assert v.calls == []

    def test_D4_flat_with_an_empty_degraded_view_is_not_safe_terminal(self):
        v = Venue(position=0, query_fails=True)
        out = runner(v).emergency_flatten("D4")
        assert out["safe_terminal"] is False and out["flattened"] is False

    def test_D5_flat_with_a_visible_owned_order_is_not_clear(self):
        v = Venue(position=0, orders=[order(STOP)], query_fails=True)
        assert runner(v).emergency_flatten("D5")["flattened"] is False

    def test_D6_a_one_tick_outage_halts_then_convergence_resumes(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        r = runner(v)
        assert r.emergency_flatten("D6 outage")["flattened"] is False
        assert v.calls == []
        v.query_fails = False
        out = r.emergency_flatten("D6 recovered")
        assert STOP in v.cancelled and v.closed == [MNQ_ID]
        assert out["flattened"] is True

    def test_D7_repeated_outage_never_mutates_and_still_self_heals(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        r = runner(v)
        for _ in range(4):
            r.emergency_flatten("D7")
        assert v.calls == []
        v.query_fails = False
        assert r.emergency_flatten("D7 recovered")["flattened"] is True

    def test_D8_a_restart_reconstructs_the_same_halt(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        a = runner(v).emergency_flatten("D8 first")
        b = runner(v).emergency_flatten("D8 fresh process")
        assert a["emergency_reason"] == EL.DISCOVERY_INCOMPLETE
        assert b["emergency_reason"] == EL.DISCOVERY_INCOMPLETE
        assert v.calls == []

    def test_D9_a_fill_during_the_outage_is_governed_by_truth_on_return(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        r = runner(v)
        r.emergency_flatten("D9 outage")
        v._orders[0]["status"] = DISC.STATUS_FILLED      # it filled, unseen
        v.position = 0
        v.query_fails = False
        out = r.emergency_flatten("D9 recovered")
        assert v.closed == [], "no blind close on a venue-proven flat account"
        assert out["safe_terminal"] is True

    def test_D10_a_complete_view_with_no_orders_still_converges(self):
        assert runner(Venue(position=15)).emergency_flatten("D10")["flattened"] \
            is True

    def test_D11_a_complete_view_with_owned_children_still_converges(self):
        v = Venue(position=15, orders=[order(STOP), order(TARGET, otype=1)])
        out = runner(v).emergency_flatten("D11")
        assert out["flattened"] is True
        assert max(i for i, k in enumerate(kinds(v)) if k == "cancel") \
            < kinds(v).index("close")

    def test_D12_the_fallback_never_upgrades_itself_by_returning_rows(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        read = runner(v)._emergency_venue_read()
        assert read["orders"], "the fallback did return rows"
        assert read["complete"] is False, "rows are not completeness"
        assert read["discovery"] == "open_orders_fallback_INCOMPLETE"

    def test_D13_confirm_flat_and_clear_refuses_an_incomplete_view(self):
        got = runner(Venue(position=0, query_fails=True)).confirm_flat_and_clear(
            reason="D13")
        assert got["clean"] is False and got["verified"] is False

    def test_D14_hard_flatten_consumes_the_same_law(self):
        from broker import topstepx_hard_flatten as HF

        class C:
            id = MNQ_ID
        v = Venue(position=15, query_fails=True,
                  hidden=[order(STOP, status=DISC.STATUS_SUSPENDED)])
        rep = HF.hard_flatten(v, C())
        assert v.closed == [] and v.cancelled == []
        assert rep["flat"] is False

    def test_D15_abandonment_delegation_consumes_the_same_law(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        out = runner(v).abandon_unfilled_entry("D15")
        assert v.calls == [] and out["safe"] is False

    def test_D16_management_cannot_read_incomplete_as_absent(self):
        from broker import break_even_actuator as ACT
        v = Venue(position=15, query_fails=True,
                  hidden=[order(STOP, status=DISC.STATUS_SUSPENDED)])
        probe = ACT.inspect_protection(session=v, contract_id=MNQ_ID,
                                       entry_order_id=ENTRY)
        assert probe["presence"] == DISC.UNKNOWN
        assert probe["complete"] is False

    def test_D17_new_entry_is_never_granted_from_incomplete_truth(self):
        import inspect

        from broker.topstepx_production_loop import ProductionLoop
        from broker.topstepx_production_session import ProductionSession
        assert "DISC.require_working_orders(" in inspect.getsource(
            ProductionLoop._execute)
        assert "_DISC.require_working_orders(" in inspect.getsource(
            ProductionSession)

    def test_D18_the_degraded_specimen_cannot_create_flatness(self):
        """THE CANONICAL RED SPECIMEN, now green for the right reason."""
        v = Venue(position=15, query_fails=True,
                  hidden=[order(STOP, status=DISC.STATUS_SUSPENDED)])
        out = runner(v).emergency_flatten("degraded specimen")
        assert v.closed == []
        assert out["flattened"] is False and out["safe_terminal"] is False

    def test_the_law_has_ONE_owner(self):
        """Completeness is consumed by the planner, never re-derived from
        endpoint names in each caller."""
        import inspect
        assert "discovery_complete" in inspect.getsource(EL.plan)
        for caller in ("topstepx_hard_flatten", "topstepx_execution_runner"):
            with open(os.path.join(ROOT, "src", "broker", f"{caller}.py"),
                      encoding="utf-8") as fh:
                assert "discovery_complete=" in fh.read(), caller
