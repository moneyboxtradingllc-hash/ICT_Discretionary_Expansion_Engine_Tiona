"""Synthetic replay tests; never evidence of historical trade recall."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import pre_brain_wake_shadow as REPLAY  # noqa: E402
from ai_brain import wake_controller as WAKE  # noqa: E402


NOW = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)
SESSION = "SYNTHETIC"
CONTRACT = "CON.TEST"


def observation(sequence=1, *, session=SESSION, relation="above_zone"):
    when = NOW + timedelta(seconds=60 * (sequence - 1))
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
    active_path = {
        "state_available": True, "owner": "none", "forming_direction": None,
        "status": "none", "session": "2026-09-11",
        "load_bearing_structure": None, "transfer_evidence": {},
    }
    mtf = {
        "schema_version": "mtf_market_state.v1", "timeframes": {},
        "synthesis": {"context_state": None, "active_leg_state": None,
                      "transition_state": None, "execution_state": None,
                      "timeframes_stating_something": [],
                      "alignment_state": "UNDETERMINED", "conflicts": []},
    }
    tool = {
        "tool": "bullish_fvg", "tool_family": "fvg",
        "occurrence_id": "FVG-1", "direction": "bullish",
        "source_tf": "1m", "level_type": "fvg_zone",
        "zone_low": 99.0, "zone_high": 99.5,
        "execution_eligible": True, "temporal_class": "settled",
        "price_relation": relation, "entered_zone": relation == "inside_zone",
    }
    snapshot = {
        "timestamp": when.isoformat(), "session": "new_york",
        "contract_id": CONTRACT,
        "candle_continuity": {"continuous": True},
        "derived_state": {"current": True, "history_revision": 0,
                          "derived_revision": 0},
        "execution_price": quote, "session_po3": po3,
        "setup_lifecycle": {"active": False, "setup_id": None},
        "active_path_state": active_path, "liquidity": {},
        "protected_swings": {"by_timeframe": {"highs": {}, "lows": {}}},
        "structure_flips": [], "mtf_market_state": mtf,
        "qualification": {"status": "no_trade", "qualified": False,
                          "direction": None, "authorized_playbooks": []},
        "market_regime": {"regime_label": "range", "regime_family": "range",
                          "volatility_state": "normal",
                          "expansion_state": "balanced"},
        "toolbox": {"tool_candidates": [], "tool_instances": []},
    }
    brain_input = {
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
        "active_path_state": active_path, "structure_flips": [],
        "MTF_MARKET_STATE": mtf,
        "authorized_tool_catalog": [tool],
        "authorized_objectives": [], "authorized_invalidations": [],
    }
    return {
        "session_id": session, "contract_id": CONTRACT,
        "scan_id": f"scan-{sequence}", "sequence": sequence,
        "observed_at": when.isoformat(),
        "capture_stage": REPLAY.NON_ECU_STAGE,
        "pipeline_mode": "non_ecu", "catalogs_ok": True,
        "snapshot": snapshot, "brain_input": brain_input,
    }


def bundle(count=3, *, session=SESSION, kind=REPLAY.SYNTHETIC,
           provenance=False):
    rows = [observation(i + 1, session=session) for i in range(count)]
    calls = [{
        "session_id": session, "contract_id": CONTRACT,
        "scan_id": row["scan_id"], "call_id": f"primary-{i + 1}",
        "role": REPLAY.PRIMARY, "sovereign_result": True,
    } for i, row in enumerate(rows)]
    return {
        "schema": REPLAY.BUNDLE_SCHEMA, "session_id": session,
        "evidence_kind": kind,
        "provenance_independently_verified": provenance,
        "expected_scan_count": count,
        "provider_call_coverage": "complete",
        "candidate_label_coverage": "complete",
        "trade_label_coverage": "complete",
        "provider_calls": calls,
        "candidate_origins": [], "trade_origins": [],
        "observations": rows,
    }


def candidate(sequence, candidate_id="C1", *, session=SESSION):
    return {"session_id": session, "contract_id": CONTRACT,
            "scan_id": f"scan-{sequence}", "candidate_id": candidate_id}


def trade(sequence, trade_id="T1", candidate_id="C1", *, session=SESSION,
          window=None, **details):
    return {"session_id": session, "contract_id": CONTRACT,
            "scan_id": f"scan-{sequence}", "candidate_id": candidate_id,
            "trade_id": trade_id,
            "opportunity_scan_ids": window or [f"scan-{sequence}"],
            **details}


def decisions(report):
    return [row["decision"] for row in report["decisions"]]


def test_replay_uses_the_exact_production_controller():
    assert REPLAY.WAKE.BrainWakeController is WAKE.BrainWakeController
    report = REPLAY.evaluate(bundle())
    assert decisions(report) == [WAKE.WAKE, WAKE.HOLD, WAKE.HOLD]
    assert report["projection_version"] == WAKE.PROJECTION_VERSION


def test_unchanged_valid_state_is_synthetic_only_and_never_authorizes():
    data = bundle()
    before = copy.deepcopy(data)
    report = REPLAY.evaluate(data)
    assert report["status"] == "SYNTHETIC_ONLY"
    assert report["historical_acceptance"] == "NOT_PROVEN_SYNTHETIC"
    assert report["hypothetical_wake_scans"] == 1
    assert report["hypothetical_hold_scans"] == 2
    assert report["production_authorized"] is False
    assert report["hypothetical_provider_call_reduction"] is None
    assert report["actual_call_ledger_reduction_estimate"] is None
    assert data == before


def test_raw_quote_tick_noise_does_not_wake():
    data = bundle(2)
    quote = data["observations"][1]["snapshot"]["execution_price"]
    quote.update({"best_bid": 100.25, "best_ask": 100.50,
                  "age_seconds": 0.8})
    data["observations"][1]["brain_input"]["market"][
        "execution_price"] = quote
    assert decisions(REPLAY.evaluate(data)) == [WAKE.WAKE, WAKE.HOLD]


def test_existing_semantic_zone_transition_wakes():
    data = bundle(2)
    data["observations"][1]["brain_input"][
        "authorized_tool_catalog"][0].update(
            {"price_relation": "inside_zone", "entered_zone": True})
    report = REPLAY.evaluate(data)
    assert decisions(report) == [WAKE.WAKE, WAKE.WAKE]
    assert "semantic_change:catalogs" in report["decisions"][1]["reasons"]


def test_bad_evidence_wakes_and_cannot_seed_the_next_hold():
    data = bundle(3)
    data["observations"][1]["snapshot"]["execution_price"]["fresh"] = False
    data["observations"][1]["brain_input"]["market"][
        "execution_price"]["fresh"] = False
    report = REPLAY.evaluate(data)
    assert decisions(report) == [WAKE.WAKE, WAKE.WAKE, WAKE.WAKE]
    assert "executable_quote_stale" in report["decisions"][1]["reasons"]
    assert "first_valid_scan_or_controller_state_reset" in \
        report["decisions"][2]["reasons"]


def test_maximum_silence_uses_counterfactual_wakes_not_historical_polling():
    report = REPLAY.evaluate(bundle(3), max_silence_seconds=120)
    assert decisions(report) == [WAKE.WAKE, WAKE.HOLD, WAKE.WAKE]
    assert report["decisions"][2]["reasons"] == ["maximum_silence_elapsed"]
    assert report["maximum_consecutive_hold_scans"] == 1
    assert report["maximum_consecutive_hold_duration_seconds"] == 120


def test_future_labels_cannot_choose_wakes():
    data = bundle(2)
    before = decisions(REPLAY.evaluate(data))
    data["candidate_origins"] = [candidate(2)]
    data["trade_origins"] = [trade(2, window=["scan-1", "scan-2"])]
    after = REPLAY.evaluate(data)
    assert decisions(after) == before
    assert after["trade_origin_recall"] == 0


def test_exact_candidate_trade_origin_and_lead_in_are_reported():
    data = bundle(2)
    data["observations"][1]["brain_input"][
        "authorized_tool_catalog"][0]["price_relation"] = "inside_zone"
    data["candidate_origins"] = [candidate(2)]
    data["trade_origins"] = [trade(
        2, window=["scan-1", "scan-2"], direction="bullish", quantity=1,
        planned_entry=100.25, stop=99.0, target=102.0)]
    report = REPLAY.evaluate(data)
    assert report["candidate_origin_recall"] == 1
    assert report["trade_origin_recall"] == 1
    timing = report["lead_in_wake_timing"][0]
    assert timing["wake_scan_ids"] == ["scan-1", "scan-2"]
    assert timing["first_wake_lead_seconds"] == 60
    assert timing["last_wake_lead_seconds"] == 0


def test_a_held_real_trade_origin_is_an_automatic_reject():
    data = bundle(2, session="RECORDED-TEST", kind=REPLAY.RECORDED,
                  provenance=True)
    data["candidate_origins"] = [candidate(
        2, session="RECORDED-TEST")]
    data["trade_origins"] = [trade(
        2, session="RECORDED-TEST", window=["scan-1", "scan-2"])]
    report = REPLAY.evaluate(data)
    assert report["trade_origin_recall"] == 0
    assert report["historical_acceptance"] == "REJECTED_TRADE_ORIGIN_MISS"
    assert report["status"] == "RECORDED_REPLAY_REJECTED"


def test_measured_recorded_replay_reports_primary_and_repair_reduction():
    data = bundle(3, session="RECORDED-TEST", kind=REPLAY.RECORDED,
                  provenance=True)
    data["provider_calls"].append({
        "session_id": "RECORDED-TEST", "contract_id": CONTRACT,
        "scan_id": "scan-2", "call_id": "repair-2",
        "role": "json_repair"})
    report = REPLAY.evaluate(data)
    assert report["status"] == "RECORDED_REPLAY_MEASURED"
    assert report["historical_calls"] == {
        "primary": 3, "repairs": 1,
        "repair_by_role": {"json_repair": 1, "family_repair": 0,
                           "invalidation_repair": 0, "other_repair": 0},
        "total": 4}
    assert report["hypothetical_provider_call_reduction"][
        "suppressed_primary_calls"] == 2
    assert report["actual_call_ledger_reduction_estimate"][
        "suppressed_total_calls"] == 3


def test_incomplete_call_or_identity_coverage_cannot_report_savings():
    data = bundle()
    data["provider_calls"].pop()
    data["observations"][1]["sequence"] = 9
    report = REPLAY.evaluate(data)
    assert report["evidence_complete_as_declared"] is False
    assert report["hypothetical_provider_call_reduction"] is None
    assert report["historical_acceptance"] == \
        "NOT_PROVEN_INCOMPLETE_EVIDENCE"
    assert any("primary_call_coverage_mismatch" in p
               for p in report["problems"])


def test_known_recall_day_manifest_cannot_omit_t2():
    data = bundle(2, session="PROD-20260909", kind=REPLAY.RECORDED,
                  provenance=True)
    data["candidate_origins"] = [candidate(
        1, session="PROD-20260909")]
    data["trade_origins"] = [trade(
        1, session="PROD-20260909", direction="bullish", quantity=7,
        planned_entry=29407.5, stop=29386.5, target=29451.75)]
    report = REPLAY.evaluate(data)
    assert "known_trade_manifest_mismatch" in report["problems"]
    assert any(problem.startswith("known_trade_spec_mismatch:T2")
               for problem in report["problems"])
    assert report["historical_acceptance_proven"] is False


def test_ecu_pre_provider_path_defaults_to_wake_not_hold():
    data = bundle(2)
    for row in data["observations"]:
        row["pipeline_mode"] = "ecu_pre_provider"
        row["capture_stage"] = REPLAY.ECU_STAGE
    report = REPLAY.evaluate(data)
    assert decisions(report) == [WAKE.WAKE, WAKE.WAKE]
    assert report["decisions"][1]["reasons"] == [
        "unsupported_pipeline_state:ecu_pre_provider"]


def test_absent_evidence_is_exit_two_and_remains_unknown(tmp_path, capsys):
    missing = tmp_path / "absent.json"
    assert REPLAY.main([
        "--session", "PROD-20260910", "--bundle", str(missing),
        "--max-silence-seconds", "300"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["runs"][0]["status"] == "MISSING_EVIDENCE"
    assert output["runs"][0]["total_scans"] is None


def test_cli_audits_several_values_without_mutating_synthetic_input(
        tmp_path, capsys):
    path = tmp_path / "synthetic.json"
    original = json.dumps(bundle()).encode()
    path.write_bytes(original)
    assert REPLAY.main(["--session", SESSION, "--bundle", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert [run["max_silence_seconds"] for run in output["runs"]] == [
        60.0, 180.0, 300.0, 600.0]
    assert all(run["status"] == "SYNTHETIC_ONLY" for run in output["runs"])
    assert path.read_bytes() == original


def test_cli_accepts_complete_recorded_waste_measurement(tmp_path, capsys):
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps(bundle(
        session="RECORDED-TEST", kind=REPLAY.RECORDED,
        provenance=True)), encoding="utf-8")
    assert REPLAY.main([
        "--session", "RECORDED-TEST", "--bundle", str(path),
        "--max-silence-seconds", "300"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["runs"][0]["historical_acceptance"] == \
        "WASTE_MEASUREMENT_ONLY"
    assert output["production_authorized"] is False


def test_replay_has_no_model_or_broker_call_path():
    source = Path(REPLAY.__file__).read_text(encoding="utf-8").lower()
    assert "wake_controller" in source
    for forbidden in ("_call_llm", "openai", "place_order", "submit_order",
                      "write_telemetry"):
        assert forbidden not in source
