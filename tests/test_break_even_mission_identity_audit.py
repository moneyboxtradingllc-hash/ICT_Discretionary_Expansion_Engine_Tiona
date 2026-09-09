"""Regression invariants converted from the 48e35e2 identity audit.

Later missions must never inherit historical geometry or context authority.
All prices and trades are synthetic. Only the venue/quote are substitutes;
mission creation, slot allocation, reload, reconciliation, baseline recovery,
break-even evaluation, journal and actuator are the production implementations.
Unit cases supply bound contexts; lifecycle tests exercise real fresh arming.
"""
from __future__ import annotations

import os
import json
import socket
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import break_even as BE
from broker import break_even_actuator as ACT
from broker import break_even_baseline as BB
from broker import break_even_journal as JOURNAL
from broker import topstepx_mission_recovery as RECOVERY
from broker import topstepx_mission_state as MS
from broker import topstepx_mission_reconciler as RECON
from broker import topstepx_submission_record as SUB
from broker.topstepx_execution_runner import ExecutionRunner
from broker.topstepx_production_loop import ProductionLoop
from broker.topstepx_production_session import ProductionSession, ProductionLaneRefused
from broker.topstepx_session_authorization import (
    AuthorizationRefused, ProductionSessionMission, SessionAuthorization)
from broker.topstepx_slippage import ExecutionContext
from test_break_even_production_wiring import Contract, Quote, Venue

SESSION = "AUDIT-BE-SLOTS"
ACCOUNT = "acct:synthetic"
CID = Contract.id
OPEN = dict(positions=0, working_orders=0, unknown_external=False, in_window=True)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("audit must not open a network connection")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def owner_for(path):
    auth = SessionAuthorization(
        session_id=SESSION, account_fingerprint=ACCOUNT, contract_id=CID,
        session_date="20260909", decision_window="09:30-14:00 America/New_York",
        daily_loss_budget_usd=725.0,
        path=str(path / f"session_auth_{SESSION}.json"))
    auth.authorization_fingerprint = auth.fingerprint()
    auth.save()
    return ProductionSessionMission(auth, str(path))


def open_filled(owner, *, fill, stop, direction="long", quantity=2):
    mission = owner.open_trade_mission(**OPEN)
    index = owner.next_mission_index() - 1
    entry_id, stop_id, target_id = index * 1000, index * 1000 + 1, index * 1000 + 2
    token = f"token-{index}"
    mission.consume_attempt(candidate_fingerprint=f"candidate-{index}", token_id=token)
    target = fill + 80 if direction == "long" else fill - 80
    geo = dict(direction=direction, entry_price=fill, stop_price=stop,
               target_price=target, contract_id=CID)
    record = SUB.open_submission(
        store_dir=owner.store_dir, session_id=SESSION, mission_id=mission.mission_id,
        payload={"contractId": CID, "size": quantity, "type": 2,
                 "side": 0 if direction == "long" else 1},
        custom_tag=token, token_id=token, account_fingerprint=ACCOUNT,
        authorization_fingerprint=owner.authorization.fingerprint(),
        contract_id=CID, geometry=geo)
    SUB.record_response(store_dir=owner.store_dir, session_id=SESSION,
                        submission=record, raw_response={"success": True, "orderId": entry_id})
    mission.record_venue_acknowledgement(
        venue_order_id=entry_id, session_id=SESSION, evidence="synthetic venue ack")
    mission.observe_position_open(filled_quantity=quantity, fill_price=fill,
        protective_order_ids=[stop_id, target_id], evidence="synthetic venue fill")
    return mission


def complete(mission):
    mission.observe_exit(exit_type="target", evidence="synthetic venue exit")
    mission.reconcile_flat(positions=0, working_orders=0, evidence="synthetic flat")


def attach_context(loop, mission, *, stop, direction):
    """Bound unit precondition, not a substitute for the fresh-path tests."""
    loop.ps.runner.execution_context = ExecutionContext(
        candidate_id="synthetic", candidate_fingerprint=mission.candidate_fingerprint,
        snapshot_id="synthetic", mission_id=mission.mission_id,
        account_fingerprint=ACCOUNT, contract_id=CID, direction=direction,
        quantity=mission.filled_quantity, entry_order_id=mission.order_id,
        entry_fill_price=mission.fill_price, structural_stop_price=stop,
        liquidity_target_price=mission.fill_price + (80 if direction == "long" else -80),
        session_id=SESSION, token_id=mission.token_id,
        authorization_fingerprint=mission.authorization_fingerprint,
        position_id=mission.order_id + 100, stop_order_id=mission.order_id + 1,
        target_order_id=mission.order_id + 2,
        path=loop.ps.context_path)
    armed = loop.ps.runner._arm_protection_baseline(
        thesis_invalidation=stop, proven_stop_price=stop)
    assert armed["armed"]


def loop_for(owner, mission, *, stop, direction="long", quote=30020, armed=True):
    oid, qty = mission.order_id, mission.filled_quantity
    target = mission.fill_price + 80 if direction == "long" else mission.fill_price - 80
    orders = [dict(id=oid + 1, contract_id=CID, type=4, status=1,
                   side=1 if direction == "long" else 0, size=qty,
                   parent_order_id=oid, stop_price=stop, limit_price=None),
              dict(id=oid + 2, contract_id=CID, type=1, status=1,
                   side=1 if direction == "long" else 0, size=qty,
                   parent_order_id=oid, stop_price=None, limit_price=target)]
    venue = Venue([dict(id=oid + 100, contract_id=CID, size=qty,
                         side=direction, avg_price=mission.fill_price)], orders)
    quotes = Quote(quote, quote)
    quotes.contract = Contract()
    ps = ProductionSession(session=venue, account_fingerprint=ACCOUNT,
        contract=Contract(), mission_id=SESSION, store_dir=owner.store_dir,
        session_id=SESSION, quote_provider=quotes)
    ps.runner = ExecutionRunner(session=venue, account_fingerprint=ACCOUNT, contract=ps.contract)
    ps.runner.order_id = oid
    loop = ProductionLoop(production_session=ps, session_mission=owner,
        producer=None, candles=None, runtime=None, account_id=1,
        scan_cycle=SimpleNamespace(), armed=True)
    if armed:
        attach_context(loop, mission, stop=stop, direction=direction)
    return loop, venue


def correct_decision(loop, mission):
    baseline = BB.recover(mission_path=mission.path,
        submissions_path=SUB.ledger_path(loop.mission.store_dir, SESSION))
    ctx = loop.ps.runner.execution_context
    return BE.evaluate(direction=baseline["direction"],
        entry_fill_price=baseline["entry_fill_price"],
        initial_stop_price=baseline["original_initial_stop"],
        active_protective_stop=ctx.active_protective_stop,
        current_price=loop._sided_trigger_price(baseline["direction"]),
        armed=ctx.protection_baseline_armed, contract=loop.ps.contract,
        quantity=baseline["quantity"])


@pytest.mark.parametrize("direction", ["long", "short"])
@pytest.mark.parametrize("reload_kind", ["none", "durable_reload", "cold_with_explicit_context_restore", "full_scan_tick"])
def test_t2_uses_own_risk_and_holds_at_quarter_r(tmp_path, direction, reload_kind):
    owner = owner_for(tmp_path)
    first_fill, first_stop, second_fill, second_stop, quote = (
        (30000, 29990, 30015, 29995, 30020) if direction == "long"
        else (30020, 30030, 30005, 30025, 30000))
    first = open_filled(owner, fill=first_fill, stop=first_stop, direction=direction)
    complete(first)
    second = open_filled(owner, fill=second_fill, stop=second_stop, direction=direction)
    loop, venue = loop_for(owner, second, stop=second_stop, direction=direction, quote=quote)
    if reload_kind != "none":
        if reload_kind.startswith("cold"):
            auth = SessionAuthorization.load(owner.authorization.path)
            owner = ProductionSessionMission(auth, owner.store_dir)
            loop.mission = owner
            loop.ps.runner.execution_context = ExecutionContext.load(loop.ps.context_path)
        owner.load_existing()
        owner.filled_trade_count, owner.completed_round_trip_count = 999, 0
        loop.reconcile_missions()
    active = owner.active_mission
    assert active.mission_id == second.mission_id
    assert active.path == owner.mission_path(2)
    assert not hasattr(active, "_slot")
    correct = correct_decision(loop, active)
    assert correct["outcome"] == BE.HOLD and correct["open_r"] == 0.25
    if reload_kind == "full_scan_tick":
        tick = loop.scan_once()
        assert tick["outcome"] == "SESSION_MANAGEMENT_ONLY"
        result = loop.last_management
    else:
        result = loop.manage_open_position()
    assert result["status"] == "decision_declines", result
    assert result["baseline"]["mission_id"] == second.mission_id
    assert result["baseline"]["entry_order_id"] == second.order_id
    assert result["decision"]["open_r"] == 0.25
    assert venue.modifies == []
    assert JOURNAL.load(owner.store_dir, SESSION) == []


def test_audit_t1_ignores_future_terminal_slot(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    # An unrelated historical artifact cannot redirect slot-1 management to T2.
    MS.MissionState(mission_id=f"{SESSION}-T2", account_fingerprint=ACCOUNT,
        contract_id=CID, authorization_fingerprint=owner.authorization.fingerprint(),
        state=MS.COMPLETE, path=owner.mission_path(2), order_id=2000,
        fill_price=30100, filled_quantity=2).save()
    owner.load_existing()
    loop, venue = loop_for(owner, first, stop=29990)
    result = loop.manage_open_position()
    assert result["status"] == ACT.APPLIED
    assert result["baseline"]["mission_id"] == first.mission_id
    assert venue.modifies[0]["order_id"] == first.order_id + 1


def test_t2_at_true_trigger_uses_only_its_owned_stop(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30030, stop=30010)
    complete(first)
    second = open_filled(owner, fill=30000, stop=29990)
    loop, venue = loop_for(owner, second, stop=29990, quote=30010)
    assert correct_decision(loop, second)["outcome"] == BE.PROPOSE
    result = loop.manage_open_position()
    assert result["status"] == ACT.APPLIED, result
    assert result["baseline"]["mission_id"] == second.mission_id
    assert venue.modifies == [{"order_id": second.order_id + 1,
                              "stop_price": result["decision"]["break_even_price"]}]
    assert loop.manage_open_position()["status"] == ACT.HELD
    assert len(venue.modifies) == 1


def test_different_size_still_uses_correct_geometry_before_actuation(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990, quantity=1)
    complete(first)
    second = open_filled(owner, fill=30015, stop=29995, quantity=2)
    loop, venue = loop_for(owner, second, stop=29995)
    result = loop.manage_open_position()
    assert result["status"] == "decision_declines", result
    assert result["baseline"]["mission_id"] == second.mission_id
    assert result["decision"]["open_r"] == 0.25
    assert venue.modifies == []


def test_audit_opposite_direction_cannot_send_stop_modify(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    complete(first)
    second = open_filled(owner, fill=30015, stop=30025, direction="short")
    loop, venue = loop_for(owner, second, stop=30025, direction="short")
    result = loop.manage_open_position()
    assert result["decision"]["reason"] == BE.NOT_YET
    assert result["baseline"]["direction"] == "short"
    assert venue.modifies == []
    # Missing local authority is rejected before any proposal or effect.
    loop.ps.runner.execution_context.active_protective_stop = None
    result = loop.manage_open_position()
    assert result["status"] == "identity_unavailable"
    assert venue.modifies == []


@pytest.mark.parametrize("void_count", [1, 2])
def test_voided_slots_preserve_later_mission_own_baseline(tmp_path, void_count):
    owner = owner_for(tmp_path)
    for index in range(1, void_count + 1):
        aborted = owner.open_trade_mission(**OPEN)
        aborted.consume_attempt(candidate_fingerprint="aborted", token_id=f"aborted-{index}")
        RECOVERY.record_void(store_dir=owner.store_dir, session_id=SESSION,
            mission_index=index, mission=aborted, phrase=RECOVERY.VOID_PHRASE,
            reason="synthetic pre-transport abort", venue_evidence=dict(
                open_positions=0, working_orders=0, fills_today=0))
        owner.load_existing()
    active = open_filled(owner, fill=30000, stop=29990)
    assert active.path == owner.mission_path(void_count + 1)
    owner.load_existing()
    assert owner.trades_used() == 1
    loop, venue = loop_for(owner, active, stop=29990)
    result = loop.manage_open_position()
    assert result["status"] == ACT.APPLIED, result
    assert result["baseline"]["mission_id"] == active.mission_id
    assert venue.modifies[0]["order_id"] == active.order_id + 1


def test_audit_zero_fill_rejection_cannot_open_a_later_mission(tmp_path):
    owner = owner_for(tmp_path)
    rejected = owner.open_trade_mission(**OPEN)
    rejected.consume_attempt(candidate_fingerprint="rejected", token_id="rejected")
    rejected.venue_rejected_zero_fill(venue_order_id=1000, error_code=2,
        error_message="synthetic refusal", positions=0, working_orders=0)
    owner.load_existing()
    assert owner.trades_used() == 0 and owner.next_mission_index() == 2
    with pytest.raises(AuthorizationRefused, match="HALTED"):
        owner.open_trade_mission(**OPEN)


def test_audit_unvoided_zero_fill_attempt_blocks_later_mission(tmp_path):
    owner = owner_for(tmp_path)
    aborted = owner.open_trade_mission(**OPEN)
    aborted.consume_attempt(candidate_fingerprint="pending", token_id="pending")
    owner.load_existing()
    with pytest.raises(AuthorizationRefused, match="already active"):
        owner.open_trade_mission(**OPEN)


def test_audit_normal_runner_context_absent_disables_break_even(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    loop, venue = loop_for(owner, first, stop=29990, armed=False)
    assert loop.ps.runner.execution_context is None
    result = loop.manage_open_position()
    assert result["status"] == "identity_unavailable"
    assert venue.modifies == []


def test_audit_structural_protection_can_succeed_without_arming_context():
    from test_exec_price_anchor import _fill_runner, _trade
    runner, _ = _fill_runner(30000.0, batches=[[_trade(30000.0, 1)]])
    result = runner.establish_structural_protection(sleep=lambda _: None)
    assert result["established"] is True
    assert result["anchor"]["baseline"]["armed"] is False
    assert result["anchor"]["baseline"]["reason"] == "no_execution_context"
    assert runner.execution_context is None


def test_restart_restores_only_after_bound_fresh_evidence(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    loop, venue = loop_for(owner, first, stop=29990)
    cold = ProductionSession(session=venue, account_fingerprint=ACCOUNT,
        contract=Contract(), mission_id=SESSION, session_id=SESSION,
        store_dir=owner.store_dir, quote_provider=loop.ps.quote_provider)
    assert cold.open_lane()["lane"] == "RECOVERY"
    assert cold.runner is None
    loop.ps = cold
    result = loop.manage_open_position()
    assert result["status"] == ACT.APPLIED, result
    assert cold.runner.execution_context.mission_id == first.mission_id
    assert venue.modifies[0]["order_id"] == first.order_id + 1


def test_audit_restart_with_only_mission_records_refuses_open_lane(tmp_path):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    loop, _ = loop_for(owner, first, stop=29990, armed=False)
    with pytest.raises(ProductionLaneRefused, match="no context explains it"):
        loop.ps.open_lane()


@pytest.mark.parametrize("field,value", [
    ("mission_id", "foreign"), ("entry_order_id", 8888),
    ("account_fingerprint", "foreign"), ("contract_id", "foreign"),
    ("token_id", "foreign"), ("session_id", "foreign"),
    ("authorization_fingerprint", "foreign"), ("entry_fill_price", 30000),
    ("structural_stop_price", 29990), ("original_thesis_invalidation", 29990),
    ("direction", "short"), ("quantity", 1), ("position_id", 8888),
    ("protection_baseline_armed", "true")])
@pytest.mark.parametrize("cold", [False, True])
def test_foreign_execution_context_rejected_before_proposal(tmp_path, field, value, cold):
    owner = owner_for(tmp_path)
    first = open_filled(owner, fill=30000, stop=29990)
    complete(first)
    second = open_filled(owner, fill=30015, stop=29995)
    loop, venue = loop_for(owner, second, stop=29995)
    ctx = loop.ps.runner.execution_context
    setattr(ctx, field, value)
    if cold:
        ctx.save()
        loop.ps.runner = None
    result = loop.manage_open_position()
    assert result["status"] == "identity_unavailable", result
    assert "decision" not in result
    assert venue.modifies == []
    assert JOURNAL.load(owner.store_dir, SESSION) == []


def test_audit_reconciler_matches_position_by_contract_without_entry_fill_link(tmp_path):
    owner = owner_for(tmp_path)
    mission = owner.open_trade_mission(**OPEN)
    mission.consume_attempt(candidate_fingerprint="candidate", token_id="token")
    mission.record_venue_acknowledgement(venue_order_id=1000, evidence="synthetic ack")
    venue = Venue([dict(id=999999, contract_id=CID, size=2,
                         side="long", avg_price=30077)], [])
    result = RECON.MissionReconciler(venue=venue, contract_id=CID).reconcile(mission)
    assert result["state"] == MS.POSITION_OPEN
    assert mission.fill_price == 30077
    assert mission.protective_order_ids == []
    assert venue.recent_trades() == []  # no fill bound to this entry supplied the price
    assert "position_id" not in mission.as_dict()
