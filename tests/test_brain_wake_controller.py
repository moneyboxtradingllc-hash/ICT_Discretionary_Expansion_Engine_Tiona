"""Deterministic unit contract for event-driven external Brain wake."""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain import wake_controller as W


NOW = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)


def valid_evidence():
    quote = {
        "schema": "execution_price.v1", "available": True, "fresh": True,
        "source": "topstepx_realtime_quote", "best_bid": 100.0,
        "best_ask": 100.25, "age_seconds": 0.2,
    }
    po3 = {
        "phase": "ACCUMULATION_ESTABLISHED", "new_entry_allowed": True,
        "distribution_direction": None,
        "preferred_playbook_families": ["manipulation_to_distribution"],
        "manipulation": {"classification": "none", "direction": None,
                         "conflicted": False},
    }
    active_path = {
        "state_available": True, "owner": "none", "forming_direction": None,
        "status": "none", "session": "2026-09-11",
        "load_bearing_structure": None, "transfer_evidence": {},
    }
    mtf = {
        "schema_version": "mtf_market_state.v1",
        "synthesis": {"context_state": None, "active_leg_state": None,
                      "transition_state": None, "execution_state": None,
                      "timeframes_stating_something": [],
                      "alignment_state": "UNDETERMINED", "conflicts": []},
        "timeframes": {},
    }
    snapshot = {
        "timestamp": NOW.isoformat(), "session": "new_york",
        "contract_id": "CON.TEST",
        "candle_continuity": {"continuous": True},
        "derived_state": {"current": True, "history_revision": 0,
                          "derived_revision": 0},
        "execution_price": quote,
        "session_po3": po3,
        "setup_lifecycle": {"active": False, "setup_id": None,
                            "reason": "No active playbook or tool"},
        "active_path_state": active_path,
        "liquidity": {},
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}}},
        "structure_flips": [],
        "mtf_market_state": mtf,
        "qualification": {"status": "no_trade", "qualified": False,
                          "direction": None, "authorized_playbooks": []},
        "market_regime": {"regime_label": "range", "regime_family": "range",
                          "volatility_state": "normal",
                          "expansion_state": "balanced"},
        "toolbox": {"tool_candidates": [], "tool_instances": []},
    }
    brain_input = {
        "degraded": [],
        "market": {"execution_price": quote, "volatility_state": "normal",
                   "expansion_state": "balanced"},
        "delivery": {"session_po3": po3},
        "liquidity": {"events": [], "active_draw": None},
        "liquidity_events": [],
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}},
                             "protected_high": None,
                             "protected_high_status": "none",
                             "protected_low": None,
                             "protected_low_status": "none"},
        "active_path_state": active_path,
        "structure_flips": [],
        "MTF_MARKET_STATE": mtf,
        "authorized_tool_catalog": [],
        "authorized_objectives": [],
        "authorized_invalidations": [],
    }
    return snapshot, brain_input


def observe(controller, sequence=1, when=NOW, *, snapshot=None,
            brain_input=None, session="SESSION", contract="CON.TEST",
            pipeline="non_ecu", catalogs_ok=True):
    default_snapshot, default_input = valid_evidence()
    snapshot = default_snapshot if snapshot is None else snapshot
    brain_input = default_input if brain_input is None else brain_input
    snapshot["timestamp"] = when.isoformat()
    snapshot["contract_id"] = contract
    return controller.observe(
        snapshot=snapshot, brain_input=brain_input, session_id=session,
        contract_id=contract, scan=sequence, now=when,
        pipeline_mode=pipeline, catalogs_ok=catalogs_ok)


def establish(controller, *, mode_result=None):
    first = observe(controller)
    assert first["decision"] == W.WAKE
    controller.note_provider_result(first, request_attempted=True, sovereign=True)
    return first


def test_off_is_explicit_wake_and_enforce_hold_is_actual_suppression():
    off = W.BrainWakeController(mode=W.OFF)
    assert observe(off)["reasons"] == ["mode_off"]

    enforce = W.BrainWakeController(mode=W.ENFORCE)
    establish(enforce)
    held = observe(enforce, 2, NOW + timedelta(seconds=60))
    assert held["decision"] == W.HOLD
    assert held["would_suppress"] is True
    assert held["provider_call_suppressed"] is True
    assert held["actually_suppressed"] is True


def test_audit_computes_hold_but_never_suppresses_provider():
    controller = W.BrainWakeController(mode=W.AUDIT)
    establish(controller)
    held = observe(controller, 2, NOW + timedelta(seconds=60))
    assert held["decision"] == W.HOLD
    assert held["would_suppress"] is True
    assert held["provider_call_suppressed"] is False
    assert held["actually_suppressed"] is False


def test_raw_quote_tick_and_age_noise_do_not_change_semantic_state():
    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    snapshot, brain_input = valid_evidence()
    snapshot["execution_price"].update(
        {"best_bid": 100.25, "best_ask": 100.50, "age_seconds": 0.8})
    brain_input["market"]["execution_price"] = snapshot["execution_price"]
    held = observe(controller, 2, NOW + timedelta(seconds=60),
                   snapshot=snapshot, brain_input=brain_input)
    assert held["decision"] == W.HOLD


@pytest.mark.parametrize(("dimension", "mutate"), [
    ("session_po3", lambda s, b: s["session_po3"].update(
        {"phase": "MANIPULATION_CONFIRMED"})),
    ("setup_lifecycle", lambda s, b: s["setup_lifecycle"].update(
        {"active": True, "setup_id": "SETUP-2", "current_phase": "born"})),
    ("active_path", lambda s, b: (
        s["active_path_state"].update({"owner": "bullish", "status": "active"}),
        b["active_path_state"].update({"owner": "bullish", "status": "active"}))),
    ("liquidity", lambda s, b: b["liquidity_events"].append(
        {"occurrence_id": "SWEEP-2", "timeframe": "1m",
         "liquidity_side_taken": "sell_side", "reclaimed": True})),
    ("protected_swings", lambda s, b: s["protected_swings"]["by_timeframe"][
        "lows"].update({"1m": {"swing_id": "LOW-2", "level": 99.0,
                                "registered_at": "2026-09-11T14:01:00+00:00"}})),
    ("structure_flips", lambda s, b: (
        s["structure_flips"].append({"invalidation_id": "INV-2",
                                     "type": "BROKEN_RESISTANCE_FLIP",
                                     "price": 101.0, "timeframe": "1m",
                                     "lifecycle_state": "ACTIVE"}),
        b["structure_flips"].append({"invalidation_id": "INV-2",
                                     "type": "BROKEN_RESISTANCE_FLIP",
                                     "price": 101.0, "timeframe": "1m",
                                     "lifecycle_state": "ACTIVE"}))),
    ("mtf_market_state", lambda s, b: s["mtf_market_state"]["synthesis"].update(
        {"execution_state": "bullish_break", "alignment_state": "NESTED"})),
    ("qualification", lambda s, b: s["qualification"].update(
        {"status": "candidate", "qualified": True, "direction": "bullish"})),
    ("catalogs", lambda s, b: b["authorized_tool_catalog"].append(
        {"tool": "bullish_fvg", "tool_family": "fvg",
         "occurrence_id": "FVG-2", "direction": "bullish",
         "source_tf": "1m", "execution_eligible": True,
         "price_relation": "above_zone"})),
    ("regime", lambda s, b: s["market_regime"].update(
        {"regime_label": "trend_up", "regime_family": "trend"})),
])
def test_meaningful_detector_transition_wakes_named_dimension(dimension, mutate):
    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    snapshot, brain_input = valid_evidence()
    mutate(snapshot, brain_input)
    result = observe(controller, 2, NOW + timedelta(seconds=60),
                     snapshot=snapshot, brain_input=brain_input)
    assert result["decision"] == W.WAKE
    assert f"semantic_change:{dimension}" in result["reasons"]


def test_existing_zone_relation_transition_wakes_without_using_distance():
    controller = W.BrainWakeController(mode=W.ENFORCE)
    snapshot, brain_input = valid_evidence()
    brain_input["authorized_tool_catalog"] = [{
        "tool": "bullish_fvg", "tool_family": "fvg", "occurrence_id": "FVG-1",
        "direction": "bullish", "source_tf": "1m", "execution_eligible": True,
        "price_relation": "above_zone", "distance_to_zone": 8.0,
    }]
    first = observe(controller, snapshot=snapshot, brain_input=brain_input)
    controller.note_provider_result(first, request_attempted=True, sovereign=True)
    next_snapshot, next_input = copy.deepcopy(snapshot), copy.deepcopy(brain_input)
    next_input["authorized_tool_catalog"][0].update(
        {"price_relation": "inside_zone", "entered_zone": True,
         "distance_to_zone": 0.0})
    result = observe(controller, 2, NOW + timedelta(seconds=60),
                     snapshot=next_snapshot, brain_input=next_input)
    assert result["decision"] == W.WAKE
    assert result["changed_dimensions"] == ["catalogs"]


@pytest.mark.parametrize(("failure", "expected"), [
    ("missing", "missing_required_evidence:candle_continuity"),
    ("gap", "candle_continuity_not_proven"),
    ("derived", "derived_state_not_current"),
    ("quote_missing", "executable_quote_unavailable"),
    ("quote_stale", "executable_quote_stale"),
    ("active_path", "active_path_state_unavailable"),
    ("catalog", "catalog_construction_unproven"),
])
def test_uncertain_or_incomplete_evidence_always_wakes(failure, expected):
    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    snapshot, brain_input = valid_evidence()
    catalogs_ok = True
    if failure == "missing":
        del snapshot["candle_continuity"]
    elif failure == "gap":
        snapshot["candle_continuity"]["continuous"] = False
    elif failure == "derived":
        snapshot["derived_state"]["current"] = False
    elif failure == "quote_missing":
        snapshot["execution_price"]["available"] = False
    elif failure == "quote_stale":
        snapshot["execution_price"]["fresh"] = False
    elif failure == "active_path":
        snapshot["active_path_state"]["state_available"] = False
    else:
        catalogs_ok = False
    result = observe(controller, 2, NOW + timedelta(seconds=60),
                     snapshot=snapshot, brain_input=brain_input,
                     catalogs_ok=catalogs_ok)
    assert result["decision"] == W.WAKE
    assert expected in result["reasons"]
    assert result["provider_call_suppressed"] is False


def test_ecu_pre_provider_state_is_explicitly_unsupported_and_wakes():
    controller = W.BrainWakeController(mode=W.ENFORCE)
    result = observe(controller, pipeline="ecu_pre_provider")
    assert result["decision"] == W.WAKE
    assert result["reasons"] == ["unsupported_pipeline_state:ecu_pre_provider"]


def test_session_contract_sequence_and_restart_boundaries_wake():
    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    session = observe(controller, 2, NOW + timedelta(seconds=60), session="NEW")
    assert "session_change" in session["reasons"]

    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    contract = observe(controller, 2, NOW + timedelta(seconds=60), contract="NEW.CON")
    assert "contract_change" in contract["reasons"]

    controller = W.BrainWakeController(mode=W.ENFORCE)
    establish(controller)
    gap = observe(controller, 3, NOW + timedelta(seconds=120))
    assert "sequence_gap_or_observation_reordering" in gap["reasons"]
    restarted = observe(W.BrainWakeController(mode=W.ENFORCE), 9,
                        NOW + timedelta(seconds=180))
    assert restarted["decision"] == W.WAKE
    assert "first_valid_scan_or_controller_state_reset" in restarted["reasons"]


def test_maximum_silence_is_a_counterfactual_backstop():
    controller = W.BrainWakeController(mode=W.AUDIT, max_silence_seconds=120)
    establish(controller)
    held = observe(controller, 2, NOW + timedelta(seconds=60))
    # The real AUDIT provider call does not erase the counterfactual silence.
    controller.note_provider_result(held, request_attempted=True, sovereign=True)
    wake = observe(controller, 3, NOW + timedelta(seconds=120))
    assert wake["decision"] == W.WAKE
    assert wake["reasons"] == ["maximum_silence_elapsed"]
    assert wake["seconds_since_last_brain"] == 60
    assert wake["seconds_since_last_provider_call"] == 60
    assert wake["seconds_since_last_scheduled_wake"] == 120
    assert wake["last_brain_scan"] == 2
    assert wake["last_scheduled_wake_scan"] == 1


def test_failed_or_unattempted_provider_forces_next_wake():
    controller = W.BrainWakeController(mode=W.ENFORCE)
    first = observe(controller)
    controller.note_provider_result(first, request_attempted=True, sovereign=False)
    second = observe(controller, 2, NOW + timedelta(seconds=60))
    assert "previous_brain_not_sovereign" in second["reasons"]

    controller = W.BrainWakeController(mode=W.ENFORCE)
    first = observe(controller)
    controller.note_provider_result(first, request_attempted=False, sovereign=False)
    second = observe(controller, 2, NOW + timedelta(seconds=60))
    assert "previous_provider_request_not_attempted" in second["reasons"]


def test_controller_exception_fails_open_to_cognition(monkeypatch):
    controller = W.BrainWakeController(mode=W.ENFORCE)
    monkeypatch.setattr(W, "semantic_projection",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    result = observe(controller)
    assert result["decision"] == W.WAKE
    assert result["reasons"] == ["controller_exception:RuntimeError"]


def test_telemetry_is_compact_and_write_failure_cannot_change_decision(
        tmp_path, monkeypatch):
    controller = W.BrainWakeController(mode=W.ENFORCE)
    first = establish(controller)
    path = tmp_path / "wake.jsonl"
    monkeypatch.setattr(W, "telemetry_path", lambda session_id: str(path))
    status = W.write_telemetry(first, primary_provider_request=True,
                               repair_provider_requests=2)
    assert status["ok"] is True
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["primary_provider_request"] is True
    assert record["repair_provider_requests"] == 2
    assert "snapshot" not in record and "brain_input" not in record

    path.unlink()
    path.mkdir()
    failed = W.write_telemetry(first, primary_provider_request=True)
    assert failed["ok"] is False
    assert first["decision"] == W.WAKE
