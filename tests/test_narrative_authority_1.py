"""Adversarial campaign/retracement authority tests for NARRATIVE-AUTHORITY-1."""
from __future__ import annotations

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.narrative_continuity import (  # noqa: E402
    build_narrative_continuity,
    candidate_direction_authorized,
    output_direction_hold,
)
from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT  # noqa: E402
from broker.luna_candidate_producer import CandidateProducer, NoCandidate  # noqa: E402
from broker.topstepx_client import TopstepXContract  # noqa: E402
from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402
from _step7_fixture import detected  # noqa: E402


STAMP = "2026-08-24T15:00:00+00:00"
NOW = "2026-08-24T15:03:00+00:00"
CONTRACT = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6",
                            description="MNQ", tick_size=0.25,
                            tick_value=0.5, active=True)


def path_state(owner="bearish", status="active", *, transfer_evidence=None,
               transferred=False):
    if transferred:
        prior_owner = "bearish" if owner == "bullish" else "bullish"
        invalidated_at = "2026-08-24T11:01:00-04:00"
        origin_at = "2026-08-24T15:02:00+00:00"
        last_invalidated = {"owner": prior_owner, "at": invalidated_at,
                            "level": 110.0}
    else:
        origin_at = STAMP
        last_invalidated = None
    return {
        "state_available": True,
        "owner": owner,
        "status": status,
        "origin": {"event": "sell_side_raid_rejected" if owner == "bullish"
                   else "buy_side_raid_rejected",
                   "proof_family": "rejected_raid_reclaim", "direction": owner,
                   "at": origin_at,
                   "source_tf": "5m", "occurrence_id": f"origin-{owner}"},
        "load_bearing_structure": {"level": 100.0,
                                   "side": "low" if owner == "bullish" else "high",
                                   "timeframe": "5m", "basis": "protected_swing",
                                   "swing_id": f"swing-{owner}", "at": origin_at,
                                   "intact": status == "active"},
        "progression": {"supporting_timeframes": ["5m"],
                        "highest_confirmed": "5m"},
        "transfer_evidence": transfer_evidence or {},
        "last_invalidated": last_invalidated,
        "session": "20260824",
    }


def established(direction="bearish", status="active", *, transfer_evidence=None,
                transferred=False, with_local_tools=False):
    path = path_state(direction, status, transfer_evidence=transfer_evidence,
                      transferred=transferred)
    snapshot = {"timestamp": NOW, "active_path_state": path}
    if with_local_tools:
        snapshot.update({
            "toolbox": {"tool_instances": [
                {"tool": "fvg", "direction": "bullish", "tool_id": "local-bull-fvg"}]},
            "structure": {"1m": {"mss": True, "bos_direction": "bullish"}},
            "liquidity": {"1m": {"sweep_detected": True,
                                  "sweep_direction": "below_low",
                                  "reclaim_detected": True}},
        })
    history = {"available": True, "last": {
        "timestamp": STAMP, "direction": "bearish" if transferred else direction,
        "narrative_state_version": 1, "campaign_established": True,
        "market_story": "incumbent campaign delivery",
        "dominant_reasoning": "causal delivery and protected structure",
        "invalidation_level": 110.0,
        "thesis_falsifier": {"level": 110.0},
        "active_draw": "external liquidity", "objective_id": "OBJ-1"}}
    return snapshot, history


def result_for(direction, continuity, *, action="propose_entry"):
    parsed = {
        "narrative_direction": direction,
        "narrative_phase": "retracement" if action == "propose_entry" else "transition",
        "current_action": action,
        "allowed_direction": direction,
        "recommended_playbook_family": "trend_continuation",
        "recommended_tool_family": ["fvg"],
        "invalidation_level": 100.0,
        "active_draw": "external liquidity",
        "market_story": "campaign with a local setup",
    }
    return {"ok": True, "source": "llm", "model": PRODUCTION_MODEL,
            "parsed": parsed, "narrative_continuity": continuity}


def produce_raw_proposal(direction, snapshot, continuity):
    producer = CandidateProducer(account_fingerprint="acct:test", contract=CONTRACT,
                                 allow_prose_objective_fallback=True,
                                 allow_numeric_invalidation_fallback=True)
    brain_result = result_for(direction, continuity)
    brain_input = {"timestamp": NOW, "narrative_continuity": continuity}
    with pytest.raises(NoCandidate) as exc:
        producer.produce(
            brain_result=brain_result,
            brain_input=brain_input,
            snapshot=detected("ifvg", "fvg") | {"active_path_state": snapshot["active_path_state"]},
            qualification={"qualified": True},
            engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
            snapshot_id="narrative-authority-test",
            market_data_timestamp=NOW,
            latest_closed_bar_timestamp=NOW,
        )
    return exc.value


@pytest.mark.parametrize("incumbent,opposing", [("bearish", "bullish"),
                                                  ("bullish", "bearish")])
def test_opposing_fvg_and_counterflow_cannot_produce_candidate(incumbent, opposing):
    snapshot, history = established(incumbent, with_local_tools=True)
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "incumbent_intact"
    refusal = produce_raw_proposal(opposing, snapshot, continuity)
    assert refusal.reason == "narrative_counterflow_not_authorized"


def test_opposing_local_mss_fvg_and_raid_do_not_change_dominant_narrative():
    snapshot, history = established("bearish", with_local_tools=True)
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["dominant_direction"] == "bearish"
    model_output = {"narrative_direction": "bullish", "current_action": "propose_entry",
                    "recommended_tool_family": ["fvg"],
                    "active_draw": "opposing buy-side pool"}
    guarded, telemetry = output_direction_hold(model_output, continuity)
    assert guarded["narrative_direction"] == "bearish"
    assert guarded["current_action"] == "stand_down"
    assert guarded["recommended_tool_family"] == ["none"]
    assert guarded["active_draw"] == "external liquidity"
    assert telemetry["status"] == "unconfirmed_flip_held"
    from ai_brain.brain_schema import empty_brain_output, validate_brain_output
    valid, reason = validate_brain_output(
        output_direction_hold(empty_brain_output(), continuity)[0])
    assert valid, reason


def test_opposing_raid_or_single_structure_break_is_not_confirmed_transfer():
    snapshot, history = established(
        "bearish", "contested",
        transfer_evidence={"opposing_raid_rejected": True,
                           "opposing_structure_break": True})
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "developing_transfer"
    assert continuity["transfer_confirmed"] is False
    assert candidate_direction_authorized("bullish", snapshot, continuity) == (
        False, "narrative_transfer_unresolved")
    assert candidate_direction_authorized("bearish", snapshot, continuity) == (
        False, "narrative_transfer_unresolved")


def test_causal_active_path_transfer_allows_new_dominant_direction():
    snapshot, history = established("bullish", transferred=True)
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "confirmed_transfer"
    assert continuity["dominant_direction"] == "bullish"
    assert continuity["transfer_proof"]["status"] == "verified"
    assert continuity["transfer_proof"]["authoritative_opposing_origin"][
        "proof_family"] == "rejected_raid_reclaim"
    assert candidate_direction_authorized("bullish", snapshot, continuity) == (
        True, "narrative_transfer_confirmed")
    held, telemetry = output_direction_hold(
        {"narrative_direction": "bullish", "current_action": "propose_entry"},
        continuity)
    assert held["narrative_direction"] == "bullish"
    assert telemetry is None


def test_active_path_typed_origin_reaches_transfer_proof_end_to_end():
    from market_state.active_path import ActivePath

    def occurrence(event_type, at, **facts):
        return {"occurrence_id": f"{event_type}:{at}:{facts.get('direction') or facts.get('side')}",
                "event_type": event_type, "event_time": at,
                "source_tf": "5m", **facts}

    ap = ActivePath()
    ap.ingest([
        occurrence("LIQUIDITY_SWEEP", "2026-08-24T14:58:00+00:00",
                   sweep_direction="below_low", reclaimed=True),
        occurrence("STRUCTURE_BREAK", "2026-08-24T14:58:00+00:00",
                   direction="bullish"),
        occurrence("PROTECTED_SWING_REGISTERED", "2026-08-24T14:59:00+00:00",
                   side="low", level=100.0),
    ])
    ap.ingest([occurrence("PROTECTED_SWING_VIOLATED",
                          "2026-08-24T15:01:00+00:00",
                          side="low", level=100.0)])
    ap.ingest([occurrence("LIQUIDITY_SWEEP", "2026-08-24T15:02:00+00:00",
                          sweep_direction="above_high", reclaimed=True)])
    ap.ingest([
        occurrence("STRUCTURE_BREAK", "2026-08-24T15:03:00+00:00",
                   direction="bearish"),
        occurrence("PROTECTED_SWING_REGISTERED", "2026-08-24T15:04:00+00:00",
                   side="high", level=110.0),
    ])
    snapshot = {"timestamp": "2026-08-24T15:05:00+00:00",
                "active_path_state": ap.state()}
    history = {"available": True, "last": {
        "timestamp": "2026-08-24T15:00:00+00:00", "direction": "bullish",
        "narrative_state_version": 1, "campaign_established": True,
        "market_story": "bullish incumbent", "dominant_reasoning": "causal path",
    }}

    continuity = build_narrative_continuity(snapshot, history)
    proof = continuity["transfer_proof"]
    assert continuity["control_state"] == "confirmed_transfer"
    assert continuity["dominant_direction"] == "bearish"
    assert proof["authoritative_opposing_origin"]["proof_family"] == (
        "rejected_raid_reclaim")
    assert proof["incumbent_invalidation"]["owner"] == "bullish"
    assert proof["opposing_owner"] == "bearish"


def test_after_transfer_new_campaign_direction_is_authorized_not_counterflow():
    snapshot, history = established("bullish", transferred=True)
    continuity = build_narrative_continuity(snapshot, history)
    # A bearish local retracement/tool may be observed, but cannot be traded
    # against the newly confirmed bullish campaign.
    assert candidate_direction_authorized("bearish", snapshot, continuity) == (
        False, "narrative_direction_not_current_owner")
    assert candidate_direction_authorized("bullish", snapshot, continuity)[0] is True


def test_unregistered_origin_family_cannot_masquerade_as_verified_transfer():
    snapshot, history = established("bullish", transferred=True)
    snapshot["active_path_state"]["origin"]["proof_family"] = "unregistered_origin"
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "developing_transfer"
    assert continuity["transfer_proof"] is None
    assert candidate_direction_authorized("bullish", snapshot, continuity) == (
        False, "narrative_transfer_unresolved")


def test_same_direction_continuation_remains_lawful():
    snapshot, history = established("bearish")
    continuity = build_narrative_continuity(snapshot, history)
    assert candidate_direction_authorized("bearish", snapshot, continuity) == (
        True, "narrative_direction_authorized")


def test_unresolved_or_missing_campaign_stands_down():
    snapshot, history = established("bearish", "contested")
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "developing_transfer"
    assert candidate_direction_authorized("bearish", snapshot, continuity)[0] is False
    missing = {"timestamp": NOW, "active_path_state": {"state_available": False}}
    unknown = build_narrative_continuity(missing, {"available": False})
    assert candidate_direction_authorized("bullish", missing, unknown) == (
        False, "narrative_campaign_unestablished")
    held, guard = output_direction_hold(
        {"narrative_direction": "bullish", "current_action": "propose_entry",
         "recommended_tool_family": ["fvg"]}, unknown)
    assert held["narrative_direction"] == "conflicted"
    assert held["current_action"] == "stand_down"
    assert guard["status"] == "unestablished_campaign_held"
    from ai_brain.brain_schema import empty_brain_output, validate_brain_output
    valid, reason = validate_brain_output(output_direction_hold(
        empty_brain_output(), unknown)[0])
    assert valid, reason


def test_tool_geometry_without_established_campaign_cannot_manufacture_direction():
    snapshot = {"timestamp": NOW, "active_path_state": {"state_available": True,
                "owner": "none", "status": "none"},
                "toolbox": {"tool_instances": [{"tool": "fvg", "direction": "bullish"}]}}
    unknown = build_narrative_continuity(snapshot, {"available": False})
    assert candidate_direction_authorized("bullish", snapshot, unknown) == (
        False, "narrative_campaign_unestablished")


def test_brain_stand_down_is_preserved_even_with_directional_geometry():
    snapshot, history = established("bearish", with_local_tools=True)
    continuity = build_narrative_continuity(snapshot, history)
    output, guard = output_direction_hold(
        {"narrative_direction": "bearish", "current_action": "stand_down",
         "recommended_tool_family": ["none"]}, continuity)
    assert output["current_action"] == "stand_down"
    assert output["narrative_direction"] == "bearish"
    assert guard is None


def test_same_direction_entry_is_held_while_transfer_is_developing():
    snapshot, history = established(
        "bearish", "contested", transfer_evidence={"opposing_structure_break": True})
    continuity = build_narrative_continuity(snapshot, history)
    output, guard = output_direction_hold(
        {"narrative_direction": "bearish", "current_action": "propose_entry",
         "recommended_tool_family": ["fvg"]}, continuity)
    assert output["narrative_direction"] == "bearish"
    assert output["current_action"] == "stand_down"
    assert output["recommended_tool_family"] == ["none"]
    assert guard["status"] == "entry_held_for_control_state"


def test_stance_memory_preserves_falsified_thesis_until_new_owner_is_confirmed():
    from ai_brain.stance_memory import StanceMemory

    snapshot, history = established("bearish")
    snapshot["active_path_state"].update({
        "owner": "none", "status": "forming", "forming_direction": "bullish",
        "load_bearing_structure": None,
        "last_invalidated": {"owner": "bearish",
                             "at": "2026-08-24T15:01:00+00:00", "level": 100.0},
    })
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["control_state"] == "developing_transfer"
    assert continuity["dominant_direction"] is None
    assert continuity["thesis_falsifier_status"] == "occurred"
    memory = StanceMemory(persist=False)
    held, _ = output_direction_hold(
        {"narrative_direction": "bullish", "current_action": "propose_entry",
         "recommended_tool_family": ["fvg"]}, continuity)
    memory.record(NOW, held, continuity)

    next_snapshot = copy.deepcopy(snapshot)
    next_snapshot["timestamp"] = "2026-08-24T15:04:00+00:00"
    pending = build_narrative_continuity(next_snapshot, memory.history_summary())
    assert pending["control_state"] == "developing_transfer"
    assert pending["prior_thesis"]["direction"] == "bearish"
    assert pending["thesis_falsifier_status"] == "occurred"
    assert candidate_direction_authorized("bullish", next_snapshot, pending) == (
        False, "narrative_transfer_unresolved")

    next_snapshot["active_path_state"] = path_state("bullish", transferred=True)
    transferred = build_narrative_continuity(next_snapshot, memory.history_summary())
    assert transferred["control_state"] == "confirmed_transfer"
    assert transferred["dominant_direction"] == "bullish"
    memory.record("2026-08-24T15:04:00+00:00",
                  {"narrative_direction": "bullish", "narrative_phase": "reversal",
                   "current_action": "stand_down", "market_story": "new bullish campaign"},
                  transferred)
    following = copy.deepcopy(next_snapshot)
    following["timestamp"] = "2026-08-24T15:05:00+00:00"
    stable = build_narrative_continuity(following, memory.history_summary())
    assert stable["control_state"] == "incumbent_intact"
    assert stable["dominant_direction"] == "bullish"
    assert stable["thesis_falsifier_status"] == "not_occurred"


def test_production_prompt_places_campaign_before_geometry():
    prompt = " ".join(BRAIN_SYSTEM_PROMPT.lower().split())
    assert "`narrative_direction` means the dominant current market delivery / campaign direction" in prompt
    assert "retracement is counter-flow, not an opposing trade" in prompt
    assert "typed authoritative opposing origin" in prompt
    assert "not the definition of every possible reversal" in prompt
    assert "rejected_raid_reclaim` is currently a supported family" in prompt
    assert "first establish the narrative, then select geometry" in prompt
    assert "counter-directional path trade inside a broader narrative is lawful" not in prompt


def test_brain_input_carries_prior_thesis_and_current_transfer_state():
    from ai_brain.brain_input import build_brain_input

    snapshot, history = established("bearish", "contested",
                                    transfer_evidence={"opposing_structure_break": True})
    payload = build_brain_input(snapshot, history)
    continuity = payload["narrative_continuity"]
    assert continuity["prior_thesis"]["direction"] == "bearish"
    assert continuity["prior_thesis"]["thesis_falsifier"]["level"] == 110.0
    assert continuity["thesis_falsifier_status"] == "not_occurred"
    assert continuity["control_state"] == "developing_transfer"


def test_run_narrative_brain_applies_campaign_guard_after_provider_response(monkeypatch):
    from ai_brain import narrative_brain
    from ai_brain.brain_schema import empty_brain_output
    from ai_brain.stance_memory import StanceMemory

    snapshot, history = established("bearish")
    continuity = build_narrative_continuity(snapshot, history)
    memory = StanceMemory(persist=False)
    memory.record(STAMP, {
        "narrative_direction": "bearish", "narrative_phase": "continuation",
        "market_story": "Bearish campaign toward external sell-side liquidity.",
        "dominant_reasoning": "The bearish active path and protected high remain intact.",
        "invalidation_level": 110.0, "active_draw": "sell-side external liquidity",
        "objective_id": "OBJ-1", "current_action": "stand_down",
    }, continuity)

    proposed = empty_brain_output()
    proposed.update({
        "market_story": "A local bullish retracement reached a bullish FVG.",
        "narrative_direction": "bullish", "narrative_phase": "retracement",
        "phase_confidence": 70, "delivery_interpretation": "local bullish reaction",
        "liquidity_interpretation": "sell-side sweep reclaimed",
        "protected_high_interpretation": "intact", "protected_low_interpretation": "below",
        "active_draw": "buy-side liquidity", "allowed_direction": "bullish",
        "forbidden_direction": "bearish", "preferred_trade_family": "reversal",
        "preferred_playbooks": ["liquidity_sweep_reversal"], "preferred_tools": ["fvg"],
        "invalidation_level": 90.0, "thesis_health": "local reversal",
        "dominant_reasoning": ("Price is near a local level; the bullish sweep and reclaim "
                                "are counter-flow evidence, while bearish delivery and the "
                                "protected high remain intact. The incumbent invalidation "
                                "has not occurred, and sell-side liquidity remains the draw. " * 2),
        "reason": "local FVG reaction", "current_action": "stand_down",
        "recommended_playbook_family": "liquidity_sweep_reversal",
        "recommended_tool_family": ["fvg"],
    })

    monkeypatch.setattr(narrative_brain, "enabled", lambda: True)
    monkeypatch.setattr(narrative_brain, "_llm_enabled", lambda: True)
    monkeypatch.setattr(narrative_brain, "provider_circuit_state", lambda: {"open": False})
    monkeypatch.setattr(narrative_brain, "persist_brain_call",
                        lambda symbol, record: "test-archive")
    monkeypatch.setattr(narrative_brain, "_call_llm", lambda brain_input, repair=None: {
        "ok": True, "parsed": copy.deepcopy(proposed), "fallback_reason": None,
        "model": "gpt-6-luna", "model_requested": "gpt-6-luna",
        "model_returned": "gpt-6-luna", "provider_request_attempted": True,
    })

    result = narrative_brain.run_narrative_brain(snapshot, "MNQ", memory)
    assert result["source"] == "llm"
    assert result["output"]["narrative_direction"] == "bearish"
    assert result["output"]["current_action"] == "stand_down"
    assert result["narrative_authority_guard"]["status"] == "unconfirmed_flip_held"


def test_latency_execution_risk_protection_and_reconciliation_files_are_untouched():
    import subprocess

    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "fed9b8d443dde1b8f05b08eaa72b6009565877cb"],
        cwd=ROOT, text=True).splitlines()
    forbidden = {
        "src/execution_gate/execution_gate.py",
        "src/broker/topstepx_candidate_freshness.py",
        "src/broker/pre_submit_risk.py",
        "src/execution/protection.py",
        "src/execution/reconciliation.py",
        "src/live_scan/wake_registry.py",
    }
    assert not forbidden.intersection(changed)
