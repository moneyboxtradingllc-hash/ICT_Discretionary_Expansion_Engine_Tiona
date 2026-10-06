"""Provider-boundary integration for event-driven Brain wake."""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain import narrative_brain as NB  # noqa: E402
from ai_brain import wake_controller as W  # noqa: E402
from broker.topstepx_production_loop import ProductionLoop  # noqa: E402
from live_scan.wake_registry import WakeRegistry  # noqa: E402


NOW = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)

GOOD_LLM = {
    "market_story": "Bullish delivery remains inside a balanced auction.",
    "narrative_direction": "bullish",
    "narrative_phase": "accumulation",
    "phase_confidence": 60,
    "delivery_interpretation": "balanced delivery",
    "liquidity_interpretation": "sell-side draw remains available",
    "protected_high_interpretation": "none",
    "protected_low_interpretation": "intact",
    "active_draw": "sell_side",
    "allowed_direction": "bullish",
    "forbidden_direction": "bearish",
    "preferred_trade_family": "reversal",
    "preferred_playbooks": ["manipulation_to_distribution"],
    "preferred_tools": ["bullish_fvg"],
    "invalidation_level": 99.0,
    "thesis_health": "healthy",
    "contradiction_flags": [],
    "warnings": [],
    "confidence_by_component": {"delivery": 60, "liquidity": 60,
                                "structure": 50},
    "current_action": "stand_down",
    "reason": "Evidence is constructive but entry still requires a retest.",
    "must_not_do": ["do not chase price"],
    "protected_high_status": "none",
    "protected_low_status": "above",
    "dominant_reasoning": (
        "The session remains balanced after a sell-side raid, the protected low "
        "is intact, and a bullish gap is visible but still above its retest zone; "
        "fresh exposure must wait for the existing execution expression."),
    "recommended_playbook_family": "manipulation_to_distribution",
    "recommended_tool_family": ["bullish_fvg"],
}


def evidence(when=NOW, relation="above_zone"):
    quote = {
        "schema": "execution_price.v1", "available": True, "fresh": True,
        "source": "topstepx_realtime_quote", "best_bid": 100.0,
        "best_ask": 100.25, "captured_at": when.isoformat(),
        "age_seconds": 0.2,
    }
    po3 = {
        "phase": "ACCUMULATION_ESTABLISHED", "new_entry_allowed": True,
        "distribution_direction": None,
        "preferred_playbook_families": ["manipulation_to_distribution"],
        "manipulation": {"classification": "none", "direction": None,
                         "conflicted": False},
    }
    path_at = (when - timedelta(minutes=5)).isoformat()
    path = {"contract_id": "CON.TEST", "state_available": True,
            "owner": "bullish",
            "forming_direction": None, "status": "active",
            "session": "20260911",
            "origin": {"event": "sell_side_raid_rejected", "at": path_at},
            "load_bearing_structure": {"level": 99.0, "side": "low",
                                        "timeframe": "5m", "at": path_at,
                                        "intact": True},
            "progression": {"supporting_timeframes": ["5m"]},
            "transfer_evidence": {
                "opposing_structure_break": False,
                "load_bearing_failure": False,
                "load_bearing_replaced_against_path": False,
                "ambiguous_load_bearing_invalidation": False,
                "opposing_raid_rejected": False,
            }}
    mtf = {
        "schema_version": "mtf_market_state.v1", "timeframes": {},
        "synthesis": {"context_state": None, "active_leg_state": None,
                      "transition_state": None, "execution_state": None,
                      "timeframes_stating_something": [],
                      "alignment_state": "UNDETERMINED", "conflicts": []},
    }
    tool = {"tool": "bullish_fvg", "tool_family": "fvg",
            "occurrence_id": "FVG-1", "direction": "bullish",
            "source_tf": "1m", "level_type": "fvg_zone",
            "zone_low": 99.0, "zone_high": 99.5,
            "execution_eligible": True, "temporal_class": "settled",
            "price_relation": relation, "entered_zone": relation == "inside_zone"}
    snapshot = {
        "timestamp": when.isoformat(), "session": "new_york",
        "contract_id": "CON.TEST",
        "candle_continuity": {"continuous": True},
        "derived_state": {"current": True, "history_revision": 0,
                          "derived_revision": 0},
        "execution_price": quote, "session_po3": po3,
        "setup_lifecycle": {"active": False, "setup_id": None},
        "active_path_state": path, "liquidity": {},
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}}},
        "structure_flips": [], "mtf_market_state": mtf,
        "qualification": {"status": "no_trade", "qualified": False,
                          "direction": None, "authorized_playbooks": []},
        "market_regime": {"regime_label": "range", "regime_family": "range",
                          "volatility_state": "normal",
                          "expansion_state": "balanced"},
        "toolbox": {"tool_candidates": [], "tool_instances": []},
        "adaptive_policy": {}, "adaptive_mutation": {},
        "adaptive_live_authority": {},
    }
    from ai_brain.narrative_continuity import build_narrative_continuity
    continuity = build_narrative_continuity(snapshot, {"available": False})
    payload = {
        "timestamp": when.isoformat(), "session": "new_york", "degraded": [],
        "market": {"current_price": 100.0, "execution_price": quote,
                   "volatility_state": "normal", "expansion_state": "balanced"},
        "delivery": {"session_po3": po3},
        "liquidity": {"events": [], "active_draw": None},
        "liquidity_events": {"available": False, "events": []},
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}},
                             "protected_high": None,
                             "protected_high_status": "none",
                             "protected_low": None,
                             "protected_low_status": "none"},
        "active_path_state": path, "narrative_continuity": continuity,
        "structure_flips": [],
        "MTF_MARKET_STATE": mtf,
        "authorized_tool_catalog": [tool],
        "authorized_objectives": [], "authorized_invalidations": [],
    }
    return snapshot, payload


def ok_call(*args, **kwargs):
    return {"parsed": copy.deepcopy(GOOD_LLM), "ok": True, "model": "gpt-5",
            "prompt": "prompt", "user_content": "{}", "raw_response": "{}",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2}, "fallback_reason": None,
            "provider_request_attempted": True}


class Stance:
    def __init__(self):
        self.records = []

    def history_summary(self):
        return {"available": False}

    def record(self, timestamp, output, narrative_continuity=None):
        self.records.append((timestamp, output))


@pytest.fixture(autouse=True)
def wake_environment(monkeypatch):
    monkeypatch.setenv("AI_BRAIN_ENABLED", "true")
    monkeypatch.setenv("AI_BRAIN_LLM", "true")
    monkeypatch.setenv("BRAIN_WAKE_MAX_SILENCE_SECONDS", "300")
    monkeypatch.delenv("BRAIN_ECU_MODE", raising=False)
    monkeypatch.delenv("BRAIN_FAMILY_REPAIR", raising=False)
    monkeypatch.delenv("BRAIN_INVALIDATION_REPAIR", raising=False)
    W.reset_controller_registry()
    NB.reset_provider_circuit_for_tests()
    NB.set_call_context()
    yield
    W.reset_controller_registry()
    NB.reset_provider_circuit_for_tests()
    NB.set_call_context()


def install_boundaries(monkeypatch, payload, provider=None, telemetry=None):
    provider = provider or Mock(side_effect=ok_call)
    telemetry = telemetry or Mock(return_value={"ok": True, "path": "wake.jsonl"})
    persisted = Mock(return_value="brain.json")
    monkeypatch.setattr(NB, "build_brain_input",
                        lambda snapshot, history: copy.deepcopy(payload))
    monkeypatch.setattr(NB, "_call_llm", provider)
    monkeypatch.setattr(NB, "persist_brain_call", persisted)
    monkeypatch.setattr(W, "write_telemetry", telemetry)

    from broker import luna_candidate_producer as LP
    monkeypatch.setattr(LP, "authorized_objective_catalog",
                        lambda snapshot, brain_input, reference: [])
    monkeypatch.setattr(LP, "authorized_invalidation_catalog",
                        lambda brain_input: [])
    return provider, telemetry, persisted


def call(snapshot, *, sequence, when):
    NB.set_call_context(session_id="SESSION", contract_id="CON.TEST",
                        scan=sequence, observed_at=when)
    snapshot = copy.deepcopy(snapshot)
    snapshot["timestamp"] = when.isoformat()
    snapshot["execution_price"]["captured_at"] = when.isoformat()
    return NB.run_narrative_brain(snapshot, "MNQ", None)


def test_off_is_the_existing_provider_path_and_never_runs_controller(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.OFF)
    snapshot, payload = evidence()
    provider, _, persisted = install_boundaries(monkeypatch, payload)
    monkeypatch.setattr(W, "controller_for",
                        lambda **kwargs: (_ for _ in ()).throw(
                            AssertionError("OFF ran controller")))
    first = call(snapshot, sequence=1, when=NOW)
    second = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert provider.call_count == 2 and persisted.call_count == 2
    assert first["source"] == second["source"] == "llm"
    assert "wake_decision" not in first and "wake_decision" not in second


def test_audit_records_counterfactual_hold_but_calls_existing_provider(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.AUDIT)
    snapshot, payload = evidence()
    provider, telemetry, _ = install_boundaries(monkeypatch, payload)
    first = call(snapshot, sequence=1, when=NOW)
    second = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert provider.call_count == 2
    assert first["wake_decision"]["decision"] == W.WAKE
    assert second["wake_decision"]["decision"] == W.HOLD
    assert second["provider_call_suppressed"] is False
    assert second["source"] == "llm"
    assert telemetry.call_count == 2


def test_enforce_hold_makes_zero_provider_or_repair_call_and_no_stance(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    provider, telemetry, persisted = install_boundaries(monkeypatch, payload)
    stance = Stance()

    NB.set_call_context(session_id="SESSION", contract_id="CON.TEST", scan=1,
                        observed_at=NOW)
    first = NB.run_narrative_brain(copy.deepcopy(snapshot), "MNQ", stance)
    later = NOW + timedelta(seconds=60)
    second_snapshot = copy.deepcopy(snapshot)
    second_snapshot["timestamp"] = later.isoformat()
    NB.set_call_context(session_id="SESSION", contract_id="CON.TEST", scan=2,
                        observed_at=later)
    second = NB.run_narrative_brain(second_snapshot, "MNQ", stance)

    assert first["source"] == "llm"
    assert second["source"] == W.HOLD_SOURCE
    assert second["output"] is None and second["persisted"] is None
    assert second["repair_attempted"] is False
    assert provider.call_count == 1
    assert persisted.call_count == 1
    assert len(stance.records) == 1
    assert telemetry.call_count == 2
    assert telemetry.call_args_list[-1].kwargs["primary_provider_request"] is False
    assert telemetry.call_args_list[-1].kwargs["repair_provider_requests"] == 0


def test_semantic_zone_crossing_wakes_the_existing_provider_path(monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence(relation="above_zone")
    provider, _, _ = install_boundaries(monkeypatch, payload)
    call(snapshot, sequence=1, when=NOW)
    held = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert held["source"] == W.HOLD_SOURCE

    payload["authorized_tool_catalog"][0].update(
        {"price_relation": "inside_zone", "entered_zone": True})
    crossed = call(snapshot, sequence=3, when=NOW + timedelta(seconds=120))
    assert crossed["source"] == "llm"
    assert "semantic_change:catalogs" in crossed["wake_decision"]["reasons"]
    assert provider.call_count == 2


def test_raw_event_with_material_canonical_change_wakes_for_semantics(monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence(relation="above_zone")
    provider, _, _ = install_boundaries(monkeypatch, payload)
    call(snapshot, sequence=1, when=NOW)
    payload["authorized_tool_catalog"][0].update(
        {"price_relation": "inside_zone", "entered_zone": True})
    NB.set_call_context(session_id="SESSION", contract_id="CON.TEST", scan=2,
                        observed_at=NOW + timedelta(seconds=60), wake_event={
                            "schema": W.WAKE_EVENT_SCHEMA,
                            "source": W.WAKE_EVENT_SOURCE,
                            "event_id": "wake-registry:semantic",
                            "observed_at": (NOW + timedelta(seconds=30)).isoformat(),
                            "actionable": True,
                            "events": [{"occurrence_id": "FVG-1",
                                        "reason": "entered_zone"}],
                        })
    changed = NB.run_narrative_brain(copy.deepcopy(snapshot), "MNQ", None)
    assert changed["source"] == "llm"
    assert "semantic_change:catalogs" in changed["wake_decision"]["reasons"]
    assert not any(reason.startswith("actionable_mechanical_event")
                   for reason in changed["wake_decision"]["reasons"])
    assert provider.call_count == 2


def test_one_hundred_valid_raw_events_buy_zero_provider_calls_when_unchanged(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    provider, _, _ = install_boundaries(monkeypatch, payload)
    call(snapshot, sequence=1, when=NOW)
    for sequence in range(2, 102):
        when = NOW + timedelta(seconds=sequence)
        NB.set_call_context(session_id="SESSION", contract_id="CON.TEST",
                            scan=sequence, observed_at=when, wake_event={
                                "schema": W.WAKE_EVENT_SCHEMA,
                                "source": W.WAKE_EVENT_SOURCE,
                                "event_id": f"wake-registry:{sequence}",
                                "observed_at": when.isoformat(),
                                "actionable": True,
                                "events": [{"occurrence_id": "FVG-1",
                                            "reason": "entered_zone"}],
                            })
        result = NB.run_narrative_brain(copy.deepcopy(snapshot), "MNQ", None)
        assert result["source"] == W.HOLD_SOURCE
        assert result["provider_call_suppressed"] is True
    assert provider.call_count == 1


def test_hard_quota_circuit_allows_one_attempt_then_locally_degrades(monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    calls = Mock()

    def quota_provider(*args, **kwargs):
        calls()
        NB._open_hard_quota_circuit("credit_balance_exhausted")
        return {"parsed": None, "ok": False, "model": "gpt-5",
                "prompt": "prompt", "user_content": "{}", "raw_response": None,
                "usage": None,
                "fallback_reason": "provider_hard_quota:credit_balance_exhausted",
                "provider_request_attempted": True,
                "provider_circuit_open": True,
                "provider_circuit_opened": True}

    _, telemetry, _ = install_boundaries(monkeypatch, payload, provider=quota_provider)
    first = call(snapshot, sequence=1, when=NOW)
    assert first["source"] == "degraded"
    assert first["provider_circuit_open"] is True
    for sequence in range(2, 102):
        result = call(snapshot, sequence=sequence,
                      when=NOW + timedelta(seconds=sequence * 60))
        assert result["source"] == "degraded"
        assert result["provider_circuit_open"] is True
        assert result["provider_call_suppressed"] is False
        assert result["fallback_reason"] == (
            "provider_circuit_open:credit_balance_exhausted")
    assert calls.call_count == 1
    assert telemetry.call_count == 101


def test_only_explicit_hard_quota_evidence_opens_the_circuit():
    assert NB._hard_quota_reason(RuntimeError("429 rate limit exceeded")) is None
    assert NB._hard_quota_reason(TimeoutError("request timed out")) is None
    assert NB._hard_quota_reason(RuntimeError("no credits remaining")) == (
        "no_credits_remaining")

    class QuotaError(RuntimeError):
        code = "credit_balance_exhausted"
        type = "insufficient_quota"

    assert NB._hard_quota_reason(QuotaError("quota")) == (
        "credit_balance_exhausted")


def test_real_provider_boundary_latches_only_explicit_credit_exhaustion(
        monkeypatch):
    import ai_layer.ai_api_adapter as adapter

    class QuotaError(RuntimeError):
        code = "credit_balance_exhausted"
        type = "insufficient_quota"

    class Completions:
        def __init__(self):
            self.calls = 0
            self.with_raw_response = self

        def create(self, **_kwargs):
            self.calls += 1
            raise QuotaError("You have no credits remaining")

    completions = Completions()

    class Client:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=completions)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-6-luna")
    monkeypatch.setattr(adapter, "_OPENAI_AVAILABLE", True)
    monkeypatch.setattr(adapter, "_openai", SimpleNamespace(OpenAI=Client))

    first = NB._call_llm({"timestamp": "t", "market": {}})
    second = NB._call_llm({"timestamp": "t", "market": {}})
    assert first["provider_request_attempted"] is True
    assert first["provider_circuit_opened"] is True
    assert first["fallback_reason"] == (
        "provider_hard_quota:credit_balance_exhausted")
    assert second["provider_request_attempted"] is False
    assert second["provider_circuit_open"] is True
    assert completions.calls == 1


def test_stale_quote_and_controller_exception_both_leave_provider_reachable(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    provider, _, _ = install_boundaries(monkeypatch, payload)
    call(snapshot, sequence=1, when=NOW)
    snapshot["execution_price"]["fresh"] = False
    payload["market"]["execution_price"]["fresh"] = False
    stale = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert stale["source"] == "llm"
    assert "executable_quote_stale" in stale["wake_decision"]["reasons"]

    monkeypatch.setattr(W, "controller_for",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    failed_open = call(snapshot, sequence=3, when=NOW + timedelta(seconds=120))
    assert failed_open["source"] == "llm"
    assert failed_open["wake_decision"]["decision"] == W.WAKE
    assert failed_open["wake_decision"]["reasons"] == [
        "controller_exception:RuntimeError"]
    assert provider.call_count == 3


def test_telemetry_failure_never_costs_wake_or_hold_scan(monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    telemetry = Mock(side_effect=OSError("disk unavailable"))
    provider, _, _ = install_boundaries(
        monkeypatch, payload, telemetry=telemetry)
    first = call(snapshot, sequence=1, when=NOW)
    second = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert first["source"] == "llm"
    assert second["source"] == W.HOLD_SOURCE
    assert first["wake_telemetry_write_ok"] is False
    assert second["wake_telemetry_write_ok"] is False
    assert provider.call_count == 1


def test_ecu_uncertainty_always_wakes_even_in_enforce(monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true")
    snapshot, payload = evidence()
    provider, _, _ = install_boundaries(monkeypatch, payload)
    first = call(snapshot, sequence=1, when=NOW)
    second = call(snapshot, sequence=2, when=NOW + timedelta(seconds=60))
    assert provider.call_count == 2
    assert first["source"] == second["source"] == "llm"
    assert second["wake_decision"]["reasons"] == [
        "unsupported_pipeline_state:ecu_pre_provider"]


def test_consumed_registry_event_reaches_final_provider_gate_once(monkeypatch):
    """Exercise registry -> production scan context -> Narrative Brain gate."""
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    provider, _, _ = install_boundaries(monkeypatch, payload)
    registry = WakeRegistry()
    registry._armed = (("FVG-1", "bullish", 99.0, 99.5, False),)

    times = iter((NOW, NOW + timedelta(seconds=60),
                  NOW + timedelta(seconds=120),
                  NOW + timedelta(seconds=180)))
    loop = object.__new__(ProductionLoop)
    loop.clock = Mock(side_effect=times)
    loop.candles = SimpleNamespace(wake_registry=registry)
    loop.mission = SimpleNamespace(
        authorization=SimpleNamespace(session_id="SESSION"))
    loop.ps = SimpleNamespace(contract=SimpleNamespace(id="CON.TEST"))
    loop.outcomes = []
    loop._pending_wake_event = None
    loop.active_conditional_plan = None

    def brain_scan(*, observed_at=None, invoke_brain=True):
        current = copy.deepcopy(snapshot)
        current["timestamp"] = (NOW - timedelta(days=2)).isoformat()
        current["execution_price"]["captured_at"] = observed_at.isoformat()
        return NB.run_narrative_brain(current, "MNQ", None)

    loop._scan_once = brain_scan
    first = loop.scan_once()
    held = loop.scan_once()
    assert first["source"] == "llm"
    assert held["source"] == W.HOLD_SOURCE

    # The production pump's on_quote detector raises the actionable fact; the
    # launcher contract consumes its wait bit before invoking the next scan.
    registry.on_quote(bid=100.0, ask=100.25,
                      observed_at=NOW + timedelta(seconds=90))  # seed OUTSIDE
    fired = registry.on_quote(bid=99.0, ask=99.25,
                              observed_at=NOW + timedelta(seconds=90))
    assert fired and registry.consume_interaction() is True

    held_after_event = loop.scan_once()
    after = loop.scan_once()
    assert held_after_event["source"] == W.HOLD_SOURCE
    assert held_after_event["wake_decision"]["wake_event"]["actionable"] is True
    assert after["source"] == W.HOLD_SOURCE
    assert provider.call_count == 1
    assert loop.clock.call_count == 4
    assert held_after_event["wake_decision"]["timestamp"] == (
        NOW + timedelta(seconds=120)).isoformat()


def test_missing_production_observation_time_does_not_fall_back_to_candle(
        monkeypatch):
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.ENFORCE)
    snapshot, payload = evidence()
    provider, _, _ = install_boundaries(monkeypatch, payload)
    NB.set_call_context(session_id="SESSION", contract_id="CON.TEST", scan=1,
                        observed_at=None)
    result = NB.run_narrative_brain(copy.deepcopy(snapshot), "MNQ", None)
    assert result["source"] == "llm"
    assert "invalid_observation_time" in result["wake_decision"]["reasons"]
    assert provider.call_count == 1


def test_fake_candidate_cannot_publish_unbound_conditional_plan(monkeypatch, tmp_path):
    """Provider timing survives while incomplete plan authority is refused."""
    import adaptive_learning.capital_intelligence_engine as capital
    import live_scan.production_scan_cycle as cycle_module
    import shared_context.council as council
    import shared_context.shared_market_context as shared
    import state_transitions.transition_engine as transitions
    import broker.topstepx_production_loop as loop_module
    from live_scan.production_scan_cycle import ProductionScanCycle

    monkeypatch.setenv("BRAIN_ECU_MODE", "false")
    monkeypatch.setenv("BRAIN_WAKE_MODE", W.OFF)
    snapshot, payload = evidence()
    parsed = copy.deepcopy(GOOD_LLM)
    parsed["current_action"] = "watching"
    provider_timing = {
        "provider_call_started_at": "2026-09-11T14:00:01.125000+00:00",
        "provider_call_completed_at": "2026-09-11T14:00:13.470000+00:00",
        "latency_seconds": 12.345,
    }
    provider = Mock(return_value={
        "parsed": parsed, "ok": True, "model": "gpt-6-luna",
        "model_requested": "gpt-6-luna", "model_returned": "gpt-6-luna",
        "fallback_reason": None, "provider_request_attempted": True,
        **provider_timing,
    })
    persisted = Mock(return_value="brain.json")
    monkeypatch.setattr(NB, "build_brain_input",
                        lambda *_args: copy.deepcopy(payload))
    monkeypatch.setattr(NB, "_call_llm", provider)
    monkeypatch.setattr(NB, "persist_brain_call", persisted)
    monkeypatch.setattr(cycle_module, "build_timeframes", lambda _bars: {})
    monkeypatch.setattr(cycle_module.CONT, "summarize", lambda *_a, **_k: {
        "continuous": True})
    monkeypatch.setattr(loop_module.CONT, "coherent_window", lambda bars, **_k: {
        "sufficient": True, "window": bars, "continuous": True})
    monkeypatch.setattr(cycle_module, "build_snapshot", lambda *_a, **_k:
                        copy.deepcopy(snapshot))
    monkeypatch.setattr(capital, "track_capital", lambda *_a, **_k: {})
    monkeypatch.setattr(shared, "build_shared_market_context", lambda *_a: {})
    monkeypatch.setattr(council, "run_council", lambda *_a: {})
    monkeypatch.setattr(transitions, "analyze_transition", lambda *_a: {})
    import ai_retrieval.retrieval as retrieval
    monkeypatch.setattr(retrieval, "retrieve_for_snapshot", lambda *_a: {})
    monkeypatch.setattr(retrieval, "retrieval_startup_state", lambda: {})
    from ai_brain import ecu
    monkeypatch.setattr(ecu, "ecu_enabled", lambda: False)

    cycle = ProductionScanCycle.__new__(ProductionScanCycle)
    cycle.symbol = "MNQ"
    cycle.account_provider = None
    cycle.capital_identity = None
    cycle.contract_id = "CON.TEST"
    cycle.quote_provider = None
    cycle.htf_engine = SimpleNamespace(update=lambda _bars: {})
    cycle.memory = cycle.prev_experience_summary = None
    cycle.prev_memory_search = cycle.prev_dashboard = None
    cycle.thesis_engine = cycle.swing_tracker = cycle.po3_stability = None
    cycle.stance_memory = Stance()
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
    cycle._execution_price = lambda: snapshot["execution_price"]
    cycle._record_sweep_occurrences = lambda _snapshot: []
    cycle._update_active_path = lambda _snapshot: copy.deepcopy(
        snapshot["active_path_state"])
    cycle._update_structure_flips = lambda _snapshot: []
    cycle._brain_input = lambda _snapshot: copy.deepcopy(payload)
    cycle._two_brain_after_primary = lambda *_a: None
    actual_scan = cycle.scan
    scan_results = []

    def capture_actual_scan(*args, **kwargs):
        result = actual_scan(*args, **kwargs)
        scan_results.append(result)
        return result

    cycle.scan = capture_actual_scan

    events = []
    registry = WakeRegistry()
    candidate = SimpleNamespace(
        candidate_id="plan-real-brain", direction="bullish",
        extras={
            "conditional_plan": True,
            "activation_zone": {"occurrence_id": "occ-real-brain",
                                "direction": "bullish", "low": 99.0,
                                "high": 99.5},
            "conditional_plan_brain_output": parsed,
            "conditional_plan_brain_result": {},
            "plan_expires_at": "2026-09-11T14:05:00+00:00",
        })

    class Producer:
        def produce(self, **kwargs):
            # Candidate production consumes the real result built by the cycle.
            assert kwargs["brain_result"]["parsed"]["current_action"] == "watching"
            candidate.extras["conditional_plan_brain_result"] = kwargs["brain_result"]
            return candidate

    monkeypatch.setattr(loop_module.LIFECYCLE, "entry_authority_exhausted",
                        lambda _mission: False)
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.clock = lambda: NOW
    loop.candles = SimpleNamespace(
        wake_registry=registry,
        fetch_1m_candles=lambda *_a, **_k: [{"timestamp": "bar"}],
    )
    loop.cycle = cycle
    loop.symbol = "MNQ"
    loop.ps = SimpleNamespace(
        account_fingerprint="acct:brain-timing-test",
        contract=SimpleNamespace(id="CON.TEST"),
        session=object(),
        quote_provider=SimpleNamespace(capture=lambda: SimpleNamespace(
            market_data_age_seconds=0.1, best_bid=100.0, best_ask=100.25,
            captured_at=NOW)),
    )
    loop.mission = SimpleNamespace(
        store_dir=str(tmp_path),
        trade_missions=[],
        authorization=SimpleNamespace(session_id="SESSION"), candidate_count=0,
    )
    loop._terminal_cognition = None
    loop.outcomes = []
    loop._pending_wake_event = None
    loop.active_conditional_plan = None
    loop.active_candidate = None
    loop.producer = Producer()
    loop.reconcile_missions = lambda: {}
    loop.manage_open_position = lambda: {"status": "no_live_mission"}
    loop._repair_history_if_holed = lambda bars: bars
    loop._volume_profile_evidence = lambda *_a: {}
    loop._record_volume_profile_evidence = lambda *_a: None
    loop._in_window = lambda: True
    loop._attach_evidence = lambda *_a, **_k: None
    loop._record_decision = lambda *_a, **_k: None
    loop._record_plan_events = lambda _plan_id, rows: events.extend(rows)

    result = loop.scan_once()

    assert result["outcome"] == "NO_CANDIDATE"
    assert result["reason"].startswith("conditional_plan_authority_capture_failed:")
    assert provider.call_count == 1
    # This is the actual result returned from run_narrative_brain and
    # propagated through ProductionScanCycle.scan into production publication.
    brain_block = scan_results[0]["brain_block"]
    assert brain_block["provider_call_started_at"] == provider_timing[
        "provider_call_started_at"]
    assert brain_block["provider_call_completed_at"] == provider_timing[
        "provider_call_completed_at"]
    assert brain_block["provider_latency_seconds"] == provider_timing["latency_seconds"]
    assert persisted.call_count == 1
    archived = persisted.call_args.args[1]
    assert archived["provider_call_started_at"] == provider_timing[
        "provider_call_started_at"]
    assert archived["provider_call_completed_at"] == provider_timing[
        "provider_call_completed_at"]
    assert archived["provider_latency_seconds"] == provider_timing["latency_seconds"]
    assert next(e for e in events if e["event"] == "brain_call_started")[
        "timestamp"] == archived["provider_call_started_at"]
    completed = next(e for e in events if e["event"] == "brain_decision_completed")
    assert completed["timestamp"] == archived["provider_call_completed_at"]
    assert completed["latency_seconds"] == archived["provider_latency_seconds"]
    assert next(e for e in events if e["event"] == "plan_authority_refused")[
        "reason"] == result["reason"]
    assert not any(e["event"] == "plan_published" for e in events)

    # The following mechanics-only scan uses the cycle's real trigger branch;
    # there must be no second provider/Brain invocation.
    trigger = cycle.scan([{"timestamp": "bar"}], now=NOW, invoke_brain=False)
    assert trigger["brain_block"]["source"] == "preauthorized_plan_trigger"
    assert provider.call_count == 1
