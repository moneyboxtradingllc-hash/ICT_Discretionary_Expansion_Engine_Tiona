from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from market_data.campaign_lifecycle import (
    ACTIVE_DELIVERY, AUTHORITY_UNKNOWN, DESTINATION_SUBSTANTIALLY_DELIVERED,
    ESTABLISHING, RETRACING, TRANSFER_UNRESOLVED, UNESTABLISHED,
    evaluate_campaign_lifecycle, participation_permission)


CONTRACT = "CON.F.US.MNQ.Z26"
SESSION = "PROD-20260914"
START = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
REVISION = 7


def stamp(minutes=0):
    return (START + timedelta(minutes=minutes)).isoformat()


def draw(*, direction="bullish", status="PROVEN_NOT_DELIVERED", **overrides):
    market_session = __import__(
        "market_state.active_path", fromlist=["production_session_key"]
    ).production_session_key(stamp(2))
    value = {
        "process_authority": "CURRENT_PROCESS_ONLY",
        "session_id": SESSION,
        "market_session": market_session,
        "contract_id": CONTRACT,
        "campaign_direction": direction,
        "campaign_episode_id": "episode-1",
        "objective_identity": "opposing_external_liquidity:buyside@105",
        "objective_price": 105.0,
        "anchor_bar_time": stamp(0),
        "anchor_bar_close": 100.0,
        "anchor_bar_digest": "anchor-digest",
        "anchor_price_basis": "settled_1m_source_bar_close",
        "settled_cutoff": stamp(2),
        "history_revision": REVISION,
        "coverage_status": "COMPLETE",
        "authority_status": status,
        "history_complete": True,
        "progress_authoritative": True,
        "progress_points": 0.0,
        "observed_progress_fraction": 0.0,
        "delivery_evidence_bar": None,
        "delivery_evidence_price": None,
        "superseded": False,
    }
    if direction == "bearish":
        value.update(objective_identity="opposing_external_liquidity:sellside@95",
                     objective_price=95.0)
    value.update(overrides)
    return value


def active_path(direction="bullish", *, status="active", available=True,
                **overrides):
    side = "low" if direction == "bullish" else "high"
    market_session = __import__(
        "market_state.active_path", fromlist=["production_session_key"]
    ).production_session_key(stamp(2))
    value = {
        "state_available": available,
        "owner": direction if available else None,
        "status": status if available else None,
        "forming_direction": None,
        "session": market_session,
        "origin": {"direction": direction, "at": stamp(0),
                   "event": "sell_side_raid_rejected" if direction == "bullish"
                   else "buy_side_raid_rejected",
                   "proof_family": "rejected_raid_reclaim",
                   "occurrence_id": "origin-1"},
        "load_bearing_structure": {"level": 99.0 if direction == "bullish" else 101.0,
                                   "side": side, "intact": True},
        "progression": {"supporting_timeframes": ["5m"]},
        "transfer_evidence": {},
        "last_invalidated": None,
    }
    value.update(overrides)
    return value


def snapshot(*, direction="bullish", path=None, revision=REVISION):
    cutoff = stamp(2)
    return {
        "timestamp": cutoff,
        "contract_id": CONTRACT,
        "derived_state": {"current": True, "history_revision": revision,
                          "derived_revision": revision},
        "settled_source": {"1m": {"source_bar_time": cutoff,
                                    "temporal_status": "settled"}},
        "active_path_state": path if path is not None else active_path(direction),
        "structure": {}, "liquidity": {}, "timeframes": {},
    }


def brain(direction="bullish", phase="continuation"):
    return {"narrative_direction": direction, "narrative_phase": phase}


def classify(*, snap=None, output=None, continuity=None, campaign=None,
             session_id=SESSION, contract_id=CONTRACT, brain_available=True):
    snap = snap if snap is not None else snapshot()
    output = output if output is not None else brain()
    campaign = campaign if campaign is not None else draw()
    return evaluate_campaign_lifecycle(
        snapshot=snap, brain_output=output,
        narrative_continuity=continuity or {}, campaign_draw=campaign,
        session_id=session_id, contract_id=contract_id,
        brain_authority_available=brain_available)


def test_established_active_campaign_projects_active_delivery():
    result = classify()
    assert result["state"] == ACTIVE_DELIVERY
    assert result["participation_permitted"] is True
    assert result["authorized_direction"] == "bullish"


def test_valid_retracement_with_intact_owner_projects_retracing():
    assert classify(output=brain(phase="retracement"))["state"] == RETRACING


def test_retracement_resumes_delivery_from_validated_brain_phase():
    assert classify(output=brain(phase="continuation"))["state"] == ACTIVE_DELIVERY
    assert classify(output=brain(phase="distribution"))["state"] == ACTIVE_DELIVERY


def test_deep_retracement_does_not_use_progress_or_depth_thresholds():
    campaign = draw(observed_progress_fraction=0.99,
                    observed_lowest_price_after_anchor=90.0)
    result = classify(output=brain(phase="retracement"), campaign=campaign)
    assert result["state"] == RETRACING


@pytest.mark.parametrize("local_fact", ["mss", "fvg", "ob", "ote", "raid",
                                         "short_term_displacement"])
def test_local_opposite_fact_cannot_flip_campaign_owner(local_fact):
    snap = snapshot()
    snap["structure"] = {"1m": {local_fact: {"direction": "bearish"}}}
    snap["liquidity"] = {"1m": {local_fact: {"direction": "bearish"}}}
    result = classify(snap=snap, output=brain(phase="retracement"))
    assert result["state"] == RETRACING
    assert result["authorized_direction"] == "bullish"


def prior_bullish_thesis():
    return {"prior_thesis": {"direction": "bullish",
                              "campaign_established": True,
                              "timestamp": stamp(-1),
                              "falsifier_status": "not_occurred"}}


def test_substantive_incumbent_challenge_becomes_transfer_unresolved():
    path = active_path(status="contested", transfer_evidence={
        "opposing_structure_break": True})
    result = classify(snap=snapshot(path=path), continuity=prior_bullish_thesis())
    assert result["state"] == TRANSFER_UNRESOLVED
    assert result["participation_permitted"] is False


def test_failed_falsifier_without_new_owner_is_transfer_unresolved():
    path = active_path(status="none", owner="none", load_bearing_structure=None,
                       last_invalidated={"owner": "bullish", "at": stamp(1),
                                         "level": 99.0})
    result = classify(snap=snapshot(path=path), continuity=prior_bullish_thesis())
    assert result["state"] == TRANSFER_UNRESOLVED


def confirmed_bearish_path():
    path = active_path("bearish")
    path.update(last_invalidated={"owner": "bullish", "at": stamp(0),
                                  "level": 99.0},
                origin={"direction": "bearish", "at": stamp(1),
                        "event": "buy_side_raid_rejected",
                        "proof_family": "rejected_raid_reclaim",
                        "occurrence_id": "bearish-origin"},
                progression={"supporting_timeframes": ["5m"]})
    return path


def test_confirmed_transfer_needs_new_owner_draw_episode():
    snap = snapshot(direction="bearish", path=confirmed_bearish_path())
    fresh = classify(snap=snap, output=brain("bearish"),
                      continuity=prior_bullish_thesis(),
                      campaign=draw(direction="bearish"))
    assert fresh["state"] == ACTIVE_DELIVERY
    assert fresh["campaign_episode_id"] == "episode-1"

    stale_owner_draw = draw(direction="bullish")
    stale = classify(snap=snap, output=brain("bearish"),
                     continuity=prior_bullish_thesis(), campaign=stale_owner_draw)
    assert stale["state"] == AUTHORITY_UNKNOWN
    assert "identity_mismatch" in stale["reason"]


def test_proven_delivery_enters_completed_destination_state():
    campaign = draw(
        status="PROVEN_DELIVERED", history_complete=False,
        coverage_status="INCOMPLETE", progress_authoritative=False,
        delivery_evidence_bar=stamp(1), delivery_evidence_price=105.25)
    result = classify(campaign=campaign)
    assert result["state"] == DESTINATION_SUBSTANTIALLY_DELIVERED
    assert result["participation_permitted"] is False


def test_seventy_five_percent_without_touch_does_not_mark_destination_delivered():
    result = classify(campaign=draw(observed_progress_fraction=0.75))
    assert result["state"] == ACTIVE_DELIVERY


def test_draw_unknown_is_authority_unknown():
    assert classify(campaign=draw(status="UNKNOWN"))["state"] == AUTHORITY_UNKNOWN


def test_superseded_draw_is_authority_unknown():
    result = classify(campaign=draw(superseded=True))
    assert result["state"] == AUTHORITY_UNKNOWN


def test_unavailable_active_path_is_authority_unknown():
    path = active_path(available=False)
    assert classify(snap=snapshot(path=path))["state"] == AUTHORITY_UNKNOWN


def test_affirmative_no_campaign_is_unestablished():
    path = active_path(status="none", owner="none", load_bearing_structure=None,
                       origin=None)
    result = classify(
        snap=snapshot(path=path),
        campaign={"authority_status": "UNKNOWN",
                  "authority_reason": "no_accepted_campaign_draw"},
        output=brain(direction="neutral", phase="neutral"))
    assert result["state"] == UNESTABLISHED


def test_forming_causal_hypothesis_is_establishing_and_never_permits():
    path = active_path(status="forming", owner="none", load_bearing_structure=None,
                       forming_direction="bullish")
    result = classify(snap=snapshot(path=path), campaign=None)
    assert result["state"] == ESTABLISHING
    assert participation_permission(result, "bullish")[0] is False


def test_missing_brain_authority_is_not_unestablished():
    assert classify(brain_available=False)["state"] == AUTHORITY_UNKNOWN


def test_same_direction_reacquisition_is_classified_from_new_draw_episode():
    result = classify(campaign=draw(campaign_episode_id="episode-new"))
    assert result["state"] == ACTIVE_DELIVERY
    assert result["campaign_episode_id"] == "episode-new"


def test_lifecycle_cannot_authorize_direction_opposite_the_active_owner():
    result = classify(output=brain("bearish"))
    assert result["state"] == AUTHORITY_UNKNOWN
    assert participation_permission(result, "bearish")[0] is False


def test_gate_pass_does_not_change_brain_stand_down_or_other_gates():
    result = classify()
    assert participation_permission(result, "bullish")[0] is True
    original_action = "stand_down"
    assert original_action == "stand_down"
    from broker.luna_candidate_producer import CandidateProducer, NoCandidate
    with pytest.raises(NoCandidate) as refusal:
        CandidateProducer._assert_action_permits_entry({
            "current_action": original_action})
    assert getattr(refusal.value, "reason", None) == "action_declines_entry"


def test_new_history_revision_invalidates_lifecycle_authority():
    snap = snapshot(revision=REVISION + 1)
    result = classify(snap=snap, campaign=draw())
    assert result["state"] == AUTHORITY_UNKNOWN


def test_lifecycle_projection_has_no_restart_cache():
    first = classify()
    unavailable = classify(snap=snapshot(path=active_path(available=False)))
    assert first["state"] == ACTIVE_DELIVERY
    assert unavailable["state"] == AUTHORITY_UNKNOWN


def test_trade_horizon_fields_and_snapshot_are_unchanged():
    snap = snapshot()
    snap["selected_trade_objective"] = {"identity": "local-obstacle", "price": 101}
    snap["first_meaningful_obstacle"] = 101
    before = copy.deepcopy(snap)
    result = classify(snap=snap)
    assert result["state"] == ACTIVE_DELIVERY
    assert snap == before


@pytest.mark.parametrize("field", ["anchor_bar_time", "settled_cutoff",
                                    "objective_identity", "objective_price",
                                    "campaign_episode_id", "history_revision",
                                    "market_session", "contract_id", "session_id"])
def test_invalid_draw_identity_or_geometry_fails_closed(field):
    bad = draw()
    bad[field] = None if field != "history_revision" else REVISION - 1
    assert classify(campaign=bad)["state"] == AUTHORITY_UNKNOWN


def test_negative_delivery_requires_complete_authoritative_progress():
    campaign = draw(progress_authoritative=False)
    result = classify(campaign=campaign)
    assert result["state"] == AUTHORITY_UNKNOWN


def test_delivered_draw_requires_valid_settled_evidence_bar():
    campaign = draw(status="PROVEN_DELIVERED",
                    delivery_evidence_bar=stamp(3),
                    delivery_evidence_price=105.25)
    assert classify(campaign=campaign)["state"] == AUTHORITY_UNKNOWN


def test_candidate_producer_enforces_a_present_lifecycle_assessment():
    from broker.luna_candidate_producer import CandidateProducer, NoCandidate
    with pytest.raises(NoCandidate) as refusal:
        CandidateProducer(account_fingerprint="acct:test", contract=CONTRACT,
                          allow_prose_objective_fallback=True).produce(
            brain_result={"ok": True, "parsed": brain()}, brain_input={},
            snapshot={"campaign_lifecycle": {
                "state": AUTHORITY_UNKNOWN,
                "participation_permitted": False}},
            qualification={}, engine_inventory={}, snapshot_id="scan",
            market_data_timestamp=stamp(2), latest_closed_bar_timestamp=stamp(2),
            require_campaign_lifecycle=True)
    assert refusal.value.reason == "campaign_lifecycle_refused"


def test_production_candidate_gate_refuses_missing_lifecycle_assessment():
    from broker.luna_candidate_producer import CandidateProducer, NoCandidate
    with pytest.raises(NoCandidate) as refusal:
        CandidateProducer(account_fingerprint="acct:test", contract=CONTRACT,
                          allow_prose_objective_fallback=True).produce(
            brain_result={"ok": True, "parsed": brain()}, brain_input={},
            snapshot={}, qualification={}, engine_inventory={}, snapshot_id="scan",
            market_data_timestamp=stamp(2), latest_closed_bar_timestamp=stamp(2),
            require_campaign_lifecycle=True)
    assert refusal.value.reason == "campaign_lifecycle_refused"


def test_production_cycle_attaches_lifecycle_after_brain_input_is_built():
    from live_scan.production_scan_cycle import ProductionScanCycle
    import inspect
    body = inspect.getsource(ProductionScanCycle.scan)
    assert body.index("brain_input = self._brain_input(snapshot)") < \
        body.index("campaign_lifecycle = evaluate_campaign_lifecycle")
    assert 'snapshot["campaign_lifecycle"] = campaign_lifecycle' in body


def test_both_production_candidate_paths_remain_visible_to_structural_guard():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src/broker/topstepx_production_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    producer_calls = [node for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "produce"
                      and isinstance(node.func.value, ast.Attribute)
                      and node.func.value.attr == "producer"]
    assert len(producer_calls) == 2
    assert all(any(keyword.arg == "require_campaign_lifecycle"
                   and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is True
                   for keyword in call.keywords)
               for call in producer_calls)
    from ai_brain.production_model import _CONTRACT_SOURCES
    assert ("campaign_lifecycle_gate", "broker/topstepx_production_loop.py") in \
        _CONTRACT_SOURCES


def test_campaign_draw_and_other_policy_sources_are_not_modified():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD"], cwd=root, text=True).splitlines()
    assert "src/market_data/campaign_draw_truth.py" not in changed
    for protected in (
        "src/broker/trailing_protection.py",
        "src/broker/topstepx_combine_risk.py",
        "src/broker/daily_loss_budget.py",
        "src/data_feed/trade_interval_truth.py",
    ):
        assert protected not in changed
