"""LATENCY-1: a quote trigger routes an existing plan without paid cognition."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    from market_data.campaign_draw_truth import CampaignDrawTruth
    from market_state.active_path import production_session_key
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.luna_candidate_producer import CandidateProducer
    from broker import topstepx_execution_price

    contract = "CON.F.US.MNQ.Z26"
    session = "PROD-20260930"
    base = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    def candle(offset):
        at = (base + timedelta(minutes=offset)).isoformat()
        return {"timestamp": at, "open": 100.0, "high": 100.5,
                "low": 99.5, "close": 100.0, "volume": 10,
                "contract": contract, "members": 1, "expected_members": 1,
                "complete": True}

    rows = [candle(i) for i in range(3)]
    ownership = {"state_available": True, "owner": "bearish", "status": "active"}
    accepted = {"direction_authorized": True, "direction": "bearish",
                "objective": {"identity": "opposing_external_liquidity:sellside@95",
                              "kind": "opposing_external_liquidity", "price": 95},
                "brain_lineage": {"source": "llm", "snapshot_id": "author-scan"}}
    tracker = CampaignDrawTruth(contract_id=contract, session_id=session,
                                instrument="MNQ")
    tracker.observe(
        settled_bars=[rows[0]],
        settled_source={"source_bar_time": rows[0]["timestamp"],
                        "temporal_status": "settled",
                        "settled_edge_basis": "no_member_list_published"},
        contract_id=contract, session_id=session, history_revision=4,
        derived_state_current=True, accepted_view=accepted,
        ownership_state=ownership)
    public_draw = tracker.observe(
        settled_bars=rows,
        settled_source={"source_bar_time": rows[-1]["timestamp"],
                        "temporal_status": "settled",
                        "settled_edge_basis": "no_member_list_published"},
        contract_id=contract, session_id=session, history_revision=4,
        derived_state_current=True, accepted_view=accepted,
        ownership_state=ownership)
    assert public_draw["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert "anchor_bar_digest" not in public_draw

    current_at = rows[-1]["timestamp"]
    owner_path = {
        "state_available": True, "owner": "bearish", "status": "active",
        "forming_direction": None,
        "session": production_session_key(current_at),
        "origin": {"direction": "bearish", "event": "buy_side_raid_rejected",
                   "proof_family": "rejected_raid_reclaim", "at": rows[0]["timestamp"],
                   "occurrence_id": "owner-origin"},
        "load_bearing_structure": {"level": 101.0, "side": "high", "intact": True},
        "progression": {"supporting_timeframes": ["5m"]},
        "transfer_evidence": {},
        "last_invalidated": None,
    }
    snapshot = {"timestamp": current_at, "contract_id": contract,
                "derived_state": {"current": True, "history_revision": 4,
                                  "derived_revision": 4},
                "active_path_state": owner_path}
    continuity = {"prior_thesis": {"direction": "bearish",
                                    "campaign_established": True,
                                    "timestamp": rows[0]["timestamp"],
                                    "falsifier_status": "not_occurred"}}
    authored_block = {"source": "llm", "output": {
        "narrative_direction": "bearish", "narrative_phase": "continuation",
        "current_action": "watching"}, "fallback_reason": None,
        "llm_model": "gpt-6-luna", "narrative_continuity": continuity}
    stored_brain_result = ProductionScanCycle.to_brain_result(authored_block)
    old = SimpleNamespace(direction="bearish", extras={
        "activation_zone": {"occurrence_id": "occ-11", "direction": "bearish",
                            "low": 100.0, "high": 101.0},
        "plan_expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        "playbook": "trend_continuation", "tool_family": ["fvg"],
        "structural_invalidation": {"structure_identity": "inv-1"},
        "conditional_plan_transfer_evidence": owner_path["transfer_evidence"],
        "conditional_plan_snapshot_id": "author-scan",
    }, invalidation_price=110.0, objective=SimpleNamespace(identity="obj-1", price=95.0))
    trigger_block = {"source": "preauthorized_plan_trigger", "output": None,
                     "fallback_reason": None}
    scan = {
        "snapshot": snapshot, "brain_block": trigger_block,
        "brain_input": {"market": {"execution_price": {}}},
        "campaign_draw_authority": public_draw,
        "brain_result": ProductionScanCycle.to_brain_result(trigger_block),
        "qualification": {}, "engine_inventory": {},
        "snapshot_id": "trigger-scan-12", "market_data_timestamp": current_at,
        "latest_closed_bar_timestamp": current_at,
    }
    plan = {"plan_id": "plan-11", "candidate": old,
            "parsed": dict(stored_brain_result["parsed"]),
            "brain_result": stored_brain_result}
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.active_conditional_plan = plan
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True))
    loop.producer = CandidateProducer(account_fingerprint="acct:test", contract=contract,
                                      allow_prose_objective_fallback=True)
    # This archive-style fixture has no process-custodied plan authority; it
    # must remain refused even though it carries an old parsed Brain result.
    loop.mission = SimpleNamespace(authorization=None)
    loop.cycle = SimpleNamespace(session_id=session, contract_id=contract)
    loop.clock = lambda: NOW
    loop._record_plan_events = lambda *_args, **_kwargs: None
    loop._record_decision = lambda *_args, **_kwargs: None
    monkeypatch.setattr(topstepx_execution_price, "executable_price",
                        lambda *_args: 100.5)
    authority_blocks = []
    monkeypatch.setattr(ProductionScanCycle, "is_sovereign",
                        staticmethod(lambda block: (
                            authority_blocks.append(block) or
                            (block.get("source") == "llm"
                             and isinstance(block.get("output"), dict)
                             and bool(block.get("output"))
                             and not block.get("fallback_reason")))))

    result = loop._execute_conditional_plan(scan, conditional_event={
        "plan_id": "plan-11", "occurrence_id": "occ-11",
        "reason": "conditional_plan_zone_reached", "price": 100.5,
    }, in_window=True)

    assert result["outcome"] == "NO_CANDIDATE"
    assert result["reason"] == "conditional_plan_authority_invalid"
    # The incomplete archive plan refuses before it can substitute for current
    # phase authority or publish an assessment.
    assert snapshot.get("campaign_lifecycle") is None
    assert authority_blocks == []
    assert scan["brain_result"]["parsed"] == {}
    assert loop.active_conditional_plan is None


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


@pytest.mark.parametrize("phase", ["continuation", "retracement"])
def test_cached_plan_phase_cannot_authorize_no_brain_trigger(phase):
    from live_scan.production_scan_cycle import ProductionScanCycle
    from market_data.campaign_lifecycle import AUTHORITY_UNKNOWN
    from broker.luna_candidate_producer import NoCandidate
    from test_campaign_lifecycle import real_candidate_gate, real_public_draw, classify

    plan_block = {"source": "llm", "output": {
        "narrative_direction": "bullish", "narrative_phase": phase,
        "current_action": "watching"}, "fallback_reason": None,
        "llm_model": "gpt-6-luna", "narrative_continuity": {}}
    stored_result = ProductionScanCycle.to_brain_result(plan_block)
    trigger_block = {"source": "preauthorized_plan_trigger", "output": None,
                     "fallback_reason": None}
    current_result = ProductionScanCycle.to_brain_result(trigger_block)
    assert current_result["parsed"] == {}
    assert ProductionScanCycle.is_sovereign(trigger_block) is False
    assert ProductionScanCycle.is_sovereign(stored_result) is False
    assert ProductionScanCycle.is_validated_brain_result(stored_result) is True
    assert ProductionScanCycle.is_validated_brain_result(current_result) is False

    assessment = classify(
        output=stored_result["parsed"], campaign=real_public_draw(),
        brain_available=ProductionScanCycle.is_sovereign(trigger_block))
    assert assessment["state"] == AUTHORITY_UNKNOWN
    with pytest.raises(NoCandidate) as refusal:
        real_candidate_gate(assessment)
    assert refusal.value.reason == "campaign_lifecycle_refused"


def test_plan_publication_has_a_reconcilable_terminal_disposition():
    from broker.candidate_decision_record import (
        CONDITIONAL_PLAN_PUBLISHED, reconcile)

    report = reconcile([{"final_disposition": CONDITIONAL_PLAN_PUBLISHED}])
    assert report["status"] == "RECONCILED"
    assert report["dispositions"][CONDITIONAL_PLAN_PUBLISHED] == 1
