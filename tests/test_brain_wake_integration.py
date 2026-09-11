"""Provider-boundary integration for event-driven Brain wake."""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain import narrative_brain as NB  # noqa: E402
from ai_brain import wake_controller as W  # noqa: E402


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
    "current_action": "await_retest",
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
    path = {"state_available": True, "owner": "none",
            "forming_direction": None, "status": "none",
            "session": "2026-09-11", "transfer_evidence": {}}
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
    payload = {
        "timestamp": when.isoformat(), "session": "new_york", "degraded": [],
        "market": {"current_price": 100.0, "execution_price": quote,
                   "volatility_state": "normal", "expansion_state": "balanced"},
        "delivery": {"session_po3": po3},
        "liquidity": {"events": [], "active_draw": None},
        "liquidity_events": [],
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}},
                             "protected_high": None,
                             "protected_high_status": "none",
                             "protected_low": None,
                             "protected_low_status": "none"},
        "active_path_state": path, "structure_flips": [],
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

    def record(self, timestamp, output):
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
    NB.set_call_context()
    yield
    W.reset_controller_registry()
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
