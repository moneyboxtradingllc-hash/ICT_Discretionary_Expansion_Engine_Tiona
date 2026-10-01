"""LATENCY-1: a quote trigger routes an existing plan without paid cognition."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from broker.topstepx_production_loop import ProductionLoop
from live_scan.wake_registry import WakeRegistry


NOW = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)


def test_matching_quote_wake_uses_fresh_mechanical_scan_without_brain_call():
    registry = WakeRegistry()
    candidate = SimpleNamespace(extras={
        "activation_zone": {"occurrence_id": "occ-7"}})
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.candles = SimpleNamespace(wake_registry=registry)
    loop.active_conditional_plan = {"plan_id": "plan-7", "candidate": candidate}
    loop._pending_wake_event = None
    loop.outcomes = []
    loop.clock = lambda: NOW
    calls = []
    loop._scan_once = lambda **kwargs: calls.append(kwargs) or {
        "outcome": "NO_CANDIDATE", "brain_call_count": 0}

    assert registry.publish_conditional_watch(
        plan_id="plan-7", occurrence_id="occ-7", direction="bearish",
        low=100.0, high=101.0, bid=102.0, ask=102.25)["published"]
    fired = registry.on_quote(bid=100.5, ask=100.75)
    assert fired and fired[0]["plan_id"] == "plan-7"
    registry.consume_interaction()

    result = loop.handle_pending_conditional_wake()
    assert result["brain_call_count"] == 0
    assert len(calls) == 1
    assert calls[0]["observed_at"] == NOW
    assert calls[0]["invoke_brain"] is False
    assert calls[0]["conditional_event"]["plan_id"] == "plan-7"
    assert calls[0]["conditional_event"]["occurrence_id"] == "occ-7"
    assert len(loop.outcomes) == 1


def test_plan_publisher_requires_an_explicit_timezone_aware_expiry():
    from broker.luna_candidate_producer import _aware_expiry

    assert _aware_expiry("2026-09-30T10:05:00-04:00", NOW) == datetime(
        2026, 9, 30, 14, 5, tzinfo=timezone.utc)
    assert _aware_expiry("2026-09-30T10:05:00", NOW) is None
    assert _aware_expiry("not-a-time", NOW) is None


def test_live_conditional_plan_suppresses_the_next_paid_brain_scan():
    future = "2026-09-30T14:05:00+00:00"
    registry = WakeRegistry()
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.clock = lambda: NOW
    loop._pending_wake_event = None
    loop.candles = SimpleNamespace(wake_registry=registry)
    loop.active_conditional_plan = {
        "plan_id": "plan-8",
        "candidate": SimpleNamespace(extras={"plan_expires_at": future}),
    }
    loop.mission = SimpleNamespace(authorization=SimpleNamespace(session_id="session"))
    loop.ps = SimpleNamespace(contract=SimpleNamespace(id="MNQ"))
    loop.outcomes = []
    calls = []
    loop._scan_once = lambda **kwargs: calls.append(kwargs) or {"outcome": "WAITING"}

    assert loop.scan_once() == {"outcome": "WAITING"}
    assert calls[0]["invoke_brain"] is False
    assert calls[0]["observed_at"] == NOW
    assert loop.active_conditional_plan["plan_id"] == "plan-8"


def test_expired_plan_is_cleared_and_restores_ordinary_brain_scan():
    registry = WakeRegistry()
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.clock = lambda: NOW
    loop._pending_wake_event = None
    loop.candles = SimpleNamespace(wake_registry=registry)
    loop.active_conditional_plan = {
        "plan_id": "plan-expired",
        "candidate": SimpleNamespace(extras={
            "plan_expires_at": "2026-09-30T13:59:59+00:00"}),
    }
    loop.mission = SimpleNamespace(authorization=SimpleNamespace(session_id="session"))
    loop.ps = SimpleNamespace(contract=SimpleNamespace(id="MNQ"))
    loop.outcomes = []
    calls = []
    loop._scan_once = lambda **kwargs: calls.append(kwargs) or {"outcome": "BRAIN"}

    assert loop.scan_once() == {"outcome": "BRAIN"}
    assert calls[0]["invoke_brain"] is True
    assert loop.active_conditional_plan is None


def test_mechanics_only_plan_scan_waits_outside_zone_without_consuming_plan(monkeypatch):
    from broker import topstepx_execution_price

    monkeypatch.setattr(topstepx_execution_price, "executable_price",
                        lambda _block, _direction: 102.0)
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.clock = lambda: NOW
    loop.active_conditional_plan = {
        "plan_id": "plan-9",
        "candidate": SimpleNamespace(extras={
            "activation_zone": {"direction": "bearish", "low": 100.0,
                                "high": 101.0},
            "plan_expires_at": "2026-09-30T14:05:00+00:00",
        }),
    }
    result = loop._observe_conditional_plan({
        "brain_input": {"market": {"execution_price": {}}}})

    assert result["outcome"] == "CONDITIONAL_PLAN_WAITING"
    assert loop.active_conditional_plan["plan_id"] == "plan-9"


def test_mechanics_only_plan_scan_inside_zone_dispatches_existing_plan(monkeypatch):
    from broker import topstepx_execution_price

    monkeypatch.setattr(topstepx_execution_price, "executable_price",
                        lambda _block, _direction: 100.5)
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.clock = lambda: NOW
    loop.active_conditional_plan = {
        "plan_id": "plan-10",
        "candidate": SimpleNamespace(extras={
            "activation_zone": {"occurrence_id": "occ-10",
                                "direction": "bearish", "low": 100.0,
                                "high": 101.0},
            "plan_expires_at": "2026-09-30T14:05:00+00:00",
        }),
    }
    loop._in_window = lambda: True
    calls = []
    loop._execute_conditional_plan = lambda scan, **kwargs: calls.append(
        (scan, kwargs)) or {"outcome": "DISPATCHED"}
    scan = {"brain_input": {"market": {"execution_price": {}}}}

    assert loop._observe_conditional_plan(scan) == {"outcome": "DISPATCHED"}
    assert calls[0][0] is scan
    assert calls[0][1]["conditional_event"]["plan_id"] == "plan-10"
    assert calls[0][1]["conditional_event"]["occurrence_id"] == "occ-10"


def test_trigger_uses_stored_brain_plan_and_current_mechanics_without_recalling_brain(monkeypatch):
    import broker.topstepx_production_loop as production_loop

    monkeypatch.setattr(production_loop.DLB, "resolve", lambda **_kwargs: {
        "entry_permitted": True, "allowed_planned_risk": 300.0})
    old_objective = SimpleNamespace(identity="obj-1", price=90.0)
    old = SimpleNamespace(direction="bearish", extras={
        "activation_zone": {"occurrence_id": "occ-11", "direction": "bearish",
                            "low": 100.0, "high": 101.0},
        "plan_expires_at": "2026-09-30T14:05:00+00:00",
        "playbook": "trend_continuation", "tool_family": ["fvg"],
        "structural_invalidation": {"structure_identity": "inv-1"},
        "conditional_plan_transfer_evidence": "unchanged",
    }, invalidation_price=110.0, objective=old_objective)
    stored_brain_result = {"parsed": {"current_action": "watching"},
                           "model": "gpt-6-luna"}
    fresh = SimpleNamespace(candidate_id="fresh-11", direction="bearish", extras={
        "playbook": "trend_continuation", "tool_family": ["fvg"],
        "selected_tool_occurrence_id": "occ-11",
        "selected_tool_zone": {"low": 100.0, "high": 101.0},
        "structural_invalidation": {"structure_identity": "inv-1"},
    }, invalidation_price=110.0, objective=old_objective)
    producer_calls = []

    class Producer:
        def produce(self, **kwargs):
            producer_calls.append(kwargs)
            return fresh

    loop = ProductionLoop.__new__(ProductionLoop)
    loop.active_conditional_plan = {
        "plan_id": "plan-11", "candidate": old,
        "parsed": {"current_action": "watching"},
        "brain_result": stored_brain_result,
    }
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True))
    loop.producer = Producer()
    loop.clock = lambda: NOW
    loop._in_window = lambda: True
    plan_events = []
    loop._record_plan_events = lambda _plan_id, rows: plan_events.extend(rows)
    decision_records = []
    evidence_records = []
    loop._record_decision = lambda *args, **kwargs: decision_records.append(
        (args, kwargs))
    loop._attach_evidence = lambda *args, **kwargs: evidence_records.append(
        (args, kwargs))
    loop.ps = SimpleNamespace(
        session=object(), contract=SimpleNamespace(id="MNQ"), runner=None,
        sizing={"stop_range": "structure", "reward_to_risk": 2.0},
        build_runner=lambda *_args, **_kwargs: SimpleNamespace(geometry=SimpleNamespace(
            size=1, stop_points=10.0, stop_price=110.0, target_price=90.0,
            risk_usd=200.0)),
    )
    loop.mission = SimpleNamespace(
        trade_missions=[], authorization=object(), active_mission=None,
        candidate_count=0)
    loop.armed = True
    executions = []
    loop._execute = lambda candidate, candidate_scan, sized, in_window: (
        executions.append((candidate, candidate_scan, sized, in_window))
        or {"outcome": "MOCK_EXECUTION"})
    scan = {
        "snapshot": {"active_path_state": {"transfer_evidence": "unchanged"}},
        "brain_input": {"market": {"execution_price": {
            "available": True, "fresh": True, "best_bid": 100.5,
            "best_ask": 100.75}}},
        "brain_result": {"parsed": {"current_action": "stand_down"}},
        "qualification": {}, "engine_inventory": {},
        "snapshot_id": "snapshot-11", "market_data_timestamp": "now",
        "latest_closed_bar_timestamp": "bar-now",
    }

    result = loop._execute_conditional_plan(scan, conditional_event={
        "plan_id": "plan-11", "occurrence_id": "occ-11",
        "reason": "conditional_plan_zone_reached", "price": 100.5,
    }, in_window=True)

    assert result == {"outcome": "MOCK_EXECUTION"}
    assert producer_calls[0]["brain_result"] is stored_brain_result
    assert producer_calls[0]["conditional_trigger"] is True
    assert len(executions) == 1
    assert executions[0][0] is fresh
    assert executions[0][1] is scan
    assert executions[0][3] is True
    assert evidence_records[0][1]["brain_result_override"] is stored_brain_result
    assert decision_records[0][1]["brain_output_override"] == {
        "current_action": "watching"}
    assert decision_records[0][1]["conditional_plan_id"] == "plan-11"
    assert loop.active_conditional_plan is None
    assert any(event["event"] == "entry_condition_reached"
               for event in plan_events)
    assert not any(event["event"] == "entry_zone_reached"
                   for event in plan_events)
    accepted = [event for event in plan_events
                if event["event"] == "plan_mechanics_accepted"]
    assert len(accepted) == 1
    assert accepted[0]["trigger_scan_id"] == "snapshot-11"


def test_pending_wake_records_trigger_scan_completion_without_brain_call():
    registry = WakeRegistry()
    candidate = SimpleNamespace(extras={
        "activation_zone": {"occurrence_id": "occ-t4"}})
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.candles = SimpleNamespace(wake_registry=registry)
    loop.active_conditional_plan = {"plan_id": "plan-t4", "candidate": candidate}
    loop._pending_wake_event = None
    loop.outcomes = []
    loop.clock = lambda: NOW
    loop._scan_once = lambda **kwargs: {
        "outcome": "NO_CANDIDATE", "reason": "conditional_plan_expired",
        "brain_call_count": 0, "scan": {"snapshot_id": "trigger-scan-t4"}}
    events = []
    loop._record_plan_events = lambda _plan_id, rows: events.extend(rows)
    assert registry.publish_conditional_watch(
        plan_id="plan-t4", occurrence_id="occ-t4", direction="bearish",
        low=100, high=101, bid=102, ask=102.25)["published"]
    assert registry.on_quote(bid=100.5, ask=100.75)
    registry.consume_interaction()

    result = loop.handle_pending_conditional_wake()
    assert result["brain_call_count"] == 0
    assert events[0] == {
        "event": "trigger_mechanics_scan_completed",
        "timestamp": NOW.isoformat(), "scan_id": "trigger-scan-t4",
        "outcome": "NO_CANDIDATE",
    }
    assert events[1]["event"] == "plan_refused"


def test_production_scan_cycle_invocation_counter_is_zero_on_trigger_scan(monkeypatch):
    import ai_retrieval.retrieval as retrieval
    import adaptive_learning.capital_intelligence_engine as capital
    import live_scan.production_scan_cycle as cycle_module
    import shared_context.council as council
    import shared_context.shared_market_context as shared
    import state_transitions.transition_engine as transitions
    from live_scan.production_scan_cycle import ProductionScanCycle

    calls = []
    monkeypatch.setattr(cycle_module, "build_timeframes", lambda _bars: {})
    monkeypatch.setattr(cycle_module.CONT, "summarize", lambda *_a, **_k: {})
    monkeypatch.setattr(cycle_module, "build_snapshot", lambda *_a, **_k: {
        "timestamp": "bar-time", "qualification": {"status": "no_trade"}})
    monkeypatch.setattr(capital, "track_capital", lambda *_a, **_k: {})
    monkeypatch.setattr(shared, "build_shared_market_context", lambda *_a: {})
    monkeypatch.setattr(council, "run_council", lambda *_a: {})
    monkeypatch.setattr(transitions, "analyze_transition", lambda *_a: {})
    monkeypatch.setattr(retrieval, "retrieve_for_snapshot", lambda *_a: {})
    monkeypatch.setattr(retrieval, "retrieval_startup_state", lambda: {})
    monkeypatch.setattr(cycle_module, "run_narrative_brain", lambda *_a: (
        calls.append("brain") or {"source": "llm", "output": {
            "current_action": "watching"}}))
    from ai_brain import ecu
    monkeypatch.setattr(ecu, "ecu_enabled", lambda: False)

    cycle = ProductionScanCycle.__new__(ProductionScanCycle)
    cycle.symbol = "MNQ"
    cycle.account_provider = None
    cycle.capital_identity = None
    cycle.contract_id = ""
    cycle.quote_provider = None
    cycle.htf_engine = SimpleNamespace(update=lambda _bars: {})
    cycle.memory = cycle.prev_experience_summary = None
    cycle.prev_memory_search = cycle.prev_dashboard = None
    cycle.thesis_engine = cycle.swing_tracker = cycle.po3_stability = None
    cycle.stance_memory = None
    cycle.session_po3 = SimpleNamespace()
    cycle._prior_po3_range = cycle._prior_po3_session_date = None
    cycle.expansion_stability = None
    cycle._history = SimpleNamespace(observe=lambda _bars: 1, revision=1)
    cycle._derived_revision = 1
    cycle.rebuilds = []
    cycle.scan_count = 0
    cycle.previous_snapshot = cycle.previous_qual_state = None
    cycle.bars_in_state = 0
    cycle.setup_tracker = SimpleNamespace(update=lambda *_a: {})
    cycle.retrieval_telemetry = SimpleNamespace(record_scan=lambda **_k: {})
    cycle._execution_price = lambda: {}
    cycle._record_sweep_occurrences = lambda _snapshot: []
    cycle._update_active_path = lambda _snapshot: {}
    cycle._update_structure_flips = lambda _snapshot: []
    cycle._brain_input = lambda _snapshot: {}
    shadow_calls = []
    cycle._two_brain_after_primary = lambda *_a: shadow_calls.append("shadow")

    authoring = cycle.scan([{"timestamp": "bar"}], now=NOW,
                           invoke_brain=True)
    assert calls == ["brain"]
    assert shadow_calls == ["shadow"]
    assert authoring["brain_block"]["output"]["current_action"] == "watching"
    trigger = cycle.scan([{"timestamp": "bar"}], now=NOW,
                         invoke_brain=False)
    trigger_brain_call_count = len(calls) - 1
    assert trigger_brain_call_count == 0
    assert trigger["brain_block"]["source"] == "preauthorized_plan_trigger"
    assert trigger["brain_block"]["output"] is None
    assert calls == ["brain"]
    assert shadow_calls == ["shadow"]


@pytest.mark.parametrize("mutation", [
    "direction", "tool_family", "invalidation_price", "invalidation_identity",
    "objective_identity", "objective_price", "occurrence_id", "zone_low",
    "zone_high",
])
def test_brain_authorized_plan_semantic_mutations_fail_closed(mutation):
    old_objective = SimpleNamespace(identity="obj-exact", price=90.0)
    old = SimpleNamespace(direction="bearish", extras={
        "activation_zone": {"occurrence_id": "occ-exact", "direction": "bearish",
                            "low": 100.0, "high": 101.0},
        "plan_expires_at": "2026-09-30T14:05:00+00:00",
        "conditional_plan_snapshot_id": "author-scan",
        "playbook": "trend_continuation", "tool_family": ["fvg"],
        "structural_invalidation": {"structure_identity": "inv-exact"},
        "conditional_plan_transfer_evidence": "unchanged",
    }, invalidation_price=110.0, objective=old_objective)
    fresh_objective = SimpleNamespace(identity="obj-exact", price=90.0)
    fresh = SimpleNamespace(direction="bearish", extras={
        "playbook": "trend_continuation", "tool_family": ["fvg"],
        "selected_tool_occurrence_id": "occ-exact",
        "selected_tool_zone": {"low": 100.0, "high": 101.0},
        "structural_invalidation": {"structure_identity": "inv-exact"},
    }, invalidation_price=110.0, objective=fresh_objective)
    if mutation == "direction":
        fresh.direction = "bullish"
    elif mutation == "tool_family":
        fresh.extras["tool_family"] = ["order_block"]
    elif mutation == "invalidation_price":
        fresh.invalidation_price = 111.0
    elif mutation == "invalidation_identity":
        fresh.extras["structural_invalidation"]["structure_identity"] = "inv-new"
    elif mutation == "objective_identity":
        fresh.objective.identity = "obj-new"
    elif mutation == "objective_price":
        fresh.objective.price = 89.0
    elif mutation == "occurrence_id":
        fresh.extras["selected_tool_occurrence_id"] = "occ-new"
    elif mutation == "zone_low":
        fresh.extras["selected_tool_zone"]["low"] = 99.75
    elif mutation == "zone_high":
        fresh.extras["selected_tool_zone"]["high"] = 101.25

    class Producer:
        def produce(self, **_kwargs):
            return fresh

    loop = ProductionLoop.__new__(ProductionLoop)
    loop.active_conditional_plan = {
        "plan_id": "plan-exact", "candidate": old,
        "parsed": {"current_action": "watching"},
        "brain_result": {"parsed": {"current_action": "watching"}},
    }
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True))
    loop.producer = Producer()
    loop.clock = lambda: NOW
    loop._record_plan_events = lambda *_args: None
    loop._record_decision = lambda *_args, **_kwargs: None
    loop._attach_evidence = lambda *_args, **_kwargs: pytest.fail(
        "a mutated plan must not reach candidate evidence attachment")
    venue_calls = []
    loop._execute = lambda *_args, **_kwargs: venue_calls.append("submit")
    scan = {
        "snapshot": {"active_path_state": {"transfer_evidence": "unchanged"}},
        "brain_input": {"market": {"execution_price": {
            "available": True, "fresh": True,
            "best_bid": 100.5, "best_ask": 100.75}}},
        "snapshot_id": "trigger-scan", "market_data_timestamp": "now",
        "latest_closed_bar_timestamp": "bar-now",
    }

    refused = loop._execute_conditional_plan(scan, conditional_event={
        "plan_id": "plan-exact", "occurrence_id": "occ-exact",
        "reason": "conditional_plan_zone_reached", "price": 100.5,
    }, in_window=True)
    assert refused["outcome"] == "NO_CANDIDATE"
    assert refused["reason"] == "conditional_plan_material_change"
    assert venue_calls == []
    assert loop.active_conditional_plan is None


def test_plan_publication_has_a_reconcilable_terminal_disposition():
    from broker.candidate_decision_record import (
        CONDITIONAL_PLAN_PUBLISHED, reconcile)

    report = reconcile([{"final_disposition": CONDITIONAL_PLAN_PUBLISHED}])
    assert report["status"] == "RECONCILED"
    assert report["dispositions"][CONDITIONAL_PLAN_PUBLISHED] == 1
