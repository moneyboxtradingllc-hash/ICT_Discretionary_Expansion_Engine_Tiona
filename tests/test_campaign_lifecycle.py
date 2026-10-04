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
from market_data.campaign_draw_truth import (
    CampaignDrawTruth, PROVEN_DELIVERED, PROVEN_NOT_DELIVERED)


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


def real_public_draw(*, delivered=False, direction="bullish"):
    """Build actual public authority through CampaignDrawTruth.observe()."""
    identity = ("opposing_external_liquidity:buyside@105" if direction == "bullish"
                else "opposing_external_liquidity:sellside@95")
    price = 105 if direction == "bullish" else 95
    accepted = {
        "direction_authorized": True,
        "direction": direction,
        "objective": {"identity": identity,
                      "kind": "opposing_external_liquidity", "price": price},
        "brain_lineage": {"source": "llm", "snapshot_id": "scan-current"},
    }
    ownership = {"state_available": True, "owner": direction, "status": "active"}

    def candle(offset, *, high=100.5, low=99.5):
        return {"timestamp": stamp(offset), "open": 100, "high": high,
                "low": low, "close": 100, "volume": 10,
                "contract": CONTRACT, "members": 1, "expected_members": 1,
                "complete": True}

    def observe(tracker, rows):
        return tracker.observe(
            settled_bars=rows,
            settled_source={"source_bar_time": rows[-1]["timestamp"],
                            "temporal_status": "settled",
                            "settled_edge_basis": "no_member_list_published"},
            contract_id=CONTRACT, session_id=SESSION,
            history_revision=REVISION, derived_state_current=True,
            accepted_view=accepted, ownership_state=ownership)

    tracker = CampaignDrawTruth(contract_id=CONTRACT, session_id=SESSION,
                                instrument="MNQ")
    rows = [candle(0)]
    observe(tracker, rows)
    if delivered:
        rows.append(candle(1, high=105.25, low=99.75))
    else:
        rows.extend((candle(1), candle(2)))
    return observe(tracker, rows)


def real_no_campaign_draw(path=None):
    tracker = CampaignDrawTruth(contract_id=CONTRACT, session_id=SESSION,
                                instrument="MNQ")
    rows = [{"timestamp": stamp(i), "open": 100, "high": 100.5,
             "low": 99.5, "close": 100, "volume": 10,
             "contract": CONTRACT, "members": 1, "expected_members": 1,
             "complete": True} for i in range(3)]
    return tracker.observe(
        settled_bars=rows,
        settled_source={"source_bar_time": stamp(2),
                        "temporal_status": "settled",
                        "settled_edge_basis": "no_member_list_published"},
        contract_id=CONTRACT, session_id=SESSION,
        history_revision=REVISION, derived_state_current=True,
        accepted_view=None,
        ownership_state=path or {"state_available": True, "owner": "none",
                                 "status": "none"})


def real_superseded_draw():
    tracker = CampaignDrawTruth(contract_id=CONTRACT, session_id=SESSION,
                                instrument="MNQ")
    rows = [{"timestamp": stamp(i), "open": 100, "high": 100.5,
             "low": 99.5, "close": 100, "volume": 10,
             "contract": CONTRACT, "members": 1, "expected_members": 1,
             "complete": True} for i in range(3)]
    accepted = {"direction_authorized": True, "direction": "bullish",
                "objective": {"identity": "opposing_external_liquidity:buyside@105",
                              "kind": "opposing_external_liquidity", "price": 105},
                "brain_lineage": {"source": "llm", "snapshot_id": "old-scan"}}
    source = {"source_bar_time": stamp(0), "temporal_status": "settled",
              "settled_edge_basis": "no_member_list_published"}
    tracker.observe(
        settled_bars=[rows[0]], settled_source=source,
        contract_id=CONTRACT, session_id=SESSION,
        history_revision=REVISION, derived_state_current=True,
        accepted_view=accepted,
        ownership_state={"state_available": True, "owner": "bullish",
                         "status": "active"})
    tracker.invalidate_for_history_revision(REVISION + 1)
    current = tracker.observe(
        settled_bars=rows,
        settled_source={**source, "source_bar_time": stamp(2)},
        contract_id=CONTRACT, session_id=SESSION,
        history_revision=REVISION + 1, derived_state_current=True,
        accepted_view=None,
        ownership_state={"state_available": True, "owner": "bullish",
                         "status": "active"})
    assert tracker.audit_records[0]["superseded"] is True
    assert current["authority_status"] == "UNKNOWN"
    return current


def production_block(direction="bullish", phase="continuation", **overrides):
    block = {"source": "llm", "output": brain(direction, phase),
             "fallback_reason": None, "llm_model": "gpt-6-luna",
             "narrative_continuity": {}}
    block.update(overrides)
    return block


def real_candidate_gate(assessment, direction="bullish"):
    from broker.luna_candidate_producer import CandidateProducer
    from live_scan.production_scan_cycle import ProductionScanCycle

    block = production_block(direction, "continuation")
    result = ProductionScanCycle.to_brain_result(block)
    result["parsed"]["current_action"] = "stand_down"
    return CandidateProducer(account_fingerprint="acct:test", contract=CONTRACT,
                             allow_prose_objective_fallback=True).produce(
        brain_result=result, brain_input={},
        snapshot={"campaign_lifecycle": assessment}, qualification={},
        engine_inventory={}, snapshot_id="scan-current",
        market_data_timestamp=stamp(2), latest_closed_bar_timestamp=stamp(2),
        require_campaign_lifecycle=True)


def test_established_active_campaign_projects_active_delivery():
    result = classify()
    assert result["state"] == ACTIVE_DELIVERY
    assert result["participation_permitted"] is True
    assert result["authorized_direction"] == "bullish"


@pytest.mark.parametrize(("phase", "expected"), [
    ("continuation", ACTIVE_DELIVERY),
    ("distribution", ACTIVE_DELIVERY),
    ("retracement", RETRACING),
])
def test_real_public_draw_and_current_brain_conversion_drive_lifecycle_and_gate(
        phase, expected):
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.luna_candidate_producer import NoCandidate

    public = real_public_draw()
    assert public["authority_status"] == PROVEN_NOT_DELIVERED
    assert "anchor_bar_digest" not in public
    block = production_block(phase=phase)
    converted = ProductionScanCycle.to_brain_result(block)
    assert converted["parsed"]["narrative_phase"] == phase
    assert ProductionScanCycle.is_sovereign(block) is True
    assert ProductionScanCycle.is_sovereign(converted) is False
    assert ProductionScanCycle.is_validated_brain_result(converted) is True
    assert ProductionScanCycle.is_validated_brain_result(block) is False
    result = classify(output=block["output"], campaign=public,
                      brain_available=ProductionScanCycle.is_sovereign(block))
    assert result["state"] == expected
    with pytest.raises(NoCandidate) as refusal:
        real_candidate_gate(result)
    # The actual CandidateProducer crossed Lifecycle and refused only at the
    # later Brain action gate; no fake Producer is allowed to skip Lifecycle.
    assert getattr(refusal.value, "reason", None) != "campaign_lifecycle_refused"


def test_real_public_delivered_draw_refuses_real_candidate_producer():
    public = real_public_draw(delivered=True)
    assert public["authority_status"] == PROVEN_DELIVERED
    assert public["delivery_evidence_bar"] == stamp(1)
    result = classify(campaign=public)
    assert result["state"] == DESTINATION_SUBSTANTIALLY_DELIVERED
    from broker.luna_candidate_producer import NoCandidate
    with pytest.raises(NoCandidate) as refusal:
        real_candidate_gate(result)
    assert refusal.value.reason == "campaign_lifecycle_refused"


def test_real_scan_responses_replace_previous_brain_phase_each_scan():
    from live_scan.production_scan_cycle import ProductionScanCycle

    public = real_public_draw()
    phases = (("continuation", ACTIVE_DELIVERY),
              ("retracement", RETRACING),
              ("continuation", ACTIVE_DELIVERY))
    prior_block = None
    for current_phase, expected in phases:
        block = production_block(phase=current_phase)
        converted = ProductionScanCycle.to_brain_result(block)
        assert converted["parsed"]["narrative_phase"] == current_phase
        assessment = classify(output=block["output"], campaign=public,
                              brain_available=ProductionScanCycle.is_sovereign(block))
        assert assessment["state"] == expected
        if current_phase == "retracement":
            stale = classify(output=prior_block["output"], campaign=public,
                              brain_available=ProductionScanCycle.is_sovereign(
                                  prior_block))
            assert stale["state"] == ACTIVE_DELIVERY
            assert assessment["state"] == RETRACING
        prior_block = block


@pytest.mark.parametrize("scenario,expected", [
    ("normal", AUTHORITY_UNKNOWN),
    ("unresolved", TRANSFER_UNRESOLVED),
    ("delivered", DESTINATION_SUBSTANTIALLY_DELIVERED),
    ("superseded", AUTHORITY_UNKNOWN),
    ("revision_changed", AUTHORITY_UNKNOWN),
    ("opposite_confirmed", AUTHORITY_UNKNOWN),
    ("same_direction_new_episode", AUTHORITY_UNKNOWN),
])
def test_cached_plan_phase_cannot_survive_current_campaign_truth_changes(
        scenario, expected):
    from live_scan.production_scan_cycle import ProductionScanCycle

    plan_output = brain("bullish", "retracement")
    snap = snapshot()
    continuity = {}
    campaign = real_public_draw()
    if scenario == "unresolved":
        path = active_path(status="forming", owner="none",
                           load_bearing_structure=None,
                           forming_direction="bearish",
                           last_invalidated={"owner": "bullish", "at": stamp(1),
                                             "level": 99.0})
        snap = snapshot(path=path)
        continuity = prior_bullish_thesis()
        campaign = real_no_campaign_draw(path)
    elif scenario == "delivered":
        campaign = real_public_draw(delivered=True)
    elif scenario == "superseded":
        campaign = real_superseded_draw()
    elif scenario == "revision_changed":
        snap = snapshot(revision=REVISION + 1)
    elif scenario == "opposite_confirmed":
        from market_state.active_path import (
            LIQUIDITY_SWEEP, PROTECTED_SWING_REGISTERED,
            PROTECTED_SWING_VIOLATED, STRUCTURE_BREAK, ActivePath,
            occurrence_id)

        def event(kind, at, **fields):
            return {"occurrence_id": occurrence_id(
                        CONTRACT, kind, "1m", at,
                        fields.get("direction") or fields.get("side") or ""),
                    "event_type": kind, "contract": CONTRACT,
                    "source_tf": "1m", "event_time": at, **fields}

        machine = ActivePath()
        machine.enforce_lifecycle(stamp(0), CONTRACT)
        machine.ingest([
            event(LIQUIDITY_SWEEP, stamp(0), sweep_direction="below_low",
                  reclaimed=True),
            event(STRUCTURE_BREAK, stamp(1), direction="bullish",
                  broken_level=100),
            event(PROTECTED_SWING_REGISTERED, stamp(2), side="low", level=99),
            event(PROTECTED_SWING_VIOLATED, stamp(3), side="low", level=99),
            event(LIQUIDITY_SWEEP, stamp(4), sweep_direction="above_high",
                  reclaimed=True),
            event(STRUCTURE_BREAK, stamp(5), direction="bearish",
                  broken_level=101),
            event(PROTECTED_SWING_REGISTERED, stamp(6), side="high", level=101),
        ])
        path = machine.state()
        assert (path["owner"], path["status"]) == ("bearish", "active")
        snap = snapshot(direction="bearish", path=path)
        snap["timestamp"] = stamp(6)
        continuity = prior_bullish_thesis()
        campaign = real_public_draw(direction="bearish")
    elif scenario == "same_direction_new_episode":
        old_public = real_public_draw()
        campaign = real_public_draw()
        assert campaign["campaign_episode_id"] != old_public["campaign_episode_id"]

    trigger_block = {"source": "preauthorized_plan_trigger", "output": None,
                     "fallback_reason": None}
    result = classify(snap=snap, output=plan_output, continuity=continuity,
                      campaign=campaign,
                      brain_available=ProductionScanCycle.is_sovereign(trigger_block))
    assert result["state"] == expected
    from broker.luna_candidate_producer import NoCandidate
    with pytest.raises(NoCandidate) as refusal:
        real_candidate_gate(result, "bullish")
    assert refusal.value.reason == "campaign_lifecycle_refused"


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
                  "process_authority": "CURRENT_PROCESS_ONLY",
                  "authority_reason": "no_accepted_campaign_draw"},
        output=brain(direction="neutral", phase="neutral"))
    assert result["state"] == UNESTABLISHED


def test_forming_causal_hypothesis_is_establishing_and_never_permits():
    path = active_path(status="forming", owner="none", load_bearing_structure=None,
                       forming_direction="bullish")
    result = classify(snap=snapshot(path=path),
                      campaign=real_no_campaign_draw(path))
    assert result["state"] == ESTABLISHING
    assert participation_permission(result, "bullish")[0] is False


def test_real_active_path_failed_incumbent_plus_new_forming_hypothesis_is_transfer():
    from ai_brain.narrative_continuity import (
        STATE_VERSION, build_narrative_continuity, recheck_narrative_continuity)
    from market_state.active_path import (
        LIQUIDITY_SWEEP, PROTECTED_SWING_REGISTERED,
        PROTECTED_SWING_VIOLATED, STRUCTURE_BREAK, ActivePath,
        occurrence_id)

    def event(kind, at, **fields):
        tf = "1m"
        return {"occurrence_id": occurrence_id(CONTRACT, kind, tf, at,
                                                fields.get("direction")
                                                or fields.get("side") or ""),
                "event_type": kind, "contract": CONTRACT, "source_tf": tf,
                "event_time": at, **fields}

    path_machine = ActivePath()
    path_machine.enforce_lifecycle(stamp(0), CONTRACT)
    path_machine.ingest([
        event(LIQUIDITY_SWEEP, stamp(0), sweep_direction="below_low",
              reclaimed=True),
        event(STRUCTURE_BREAK, stamp(1), direction="bullish",
              broken_level=100.0),
        event(PROTECTED_SWING_REGISTERED, stamp(2), side="low", level=99.0,
              basis="sell_side_raid_rejected"),
    ])
    incumbent = path_machine.state()
    assert (incumbent["owner"], incumbent["status"]) == ("bullish", "active")
    assert incumbent["load_bearing_structure"]["intact"] is True
    assert incumbent["progression"]["supporting_timeframes"]

    initial_snapshot = snapshot(path=incumbent)
    prior_memory = {"available": True, "last": {
        "narrative_state_version": STATE_VERSION,
        "campaign_direction": "bullish", "campaign_established": True,
        "timestamp": stamp(1), "thesis_falsifier_status": "not_occurred",
    }}
    authored_continuity = build_narrative_continuity(initial_snapshot, prior_memory)
    assert authored_continuity["control_state"] == "incumbent_intact"

    path_machine.ingest([
        event(PROTECTED_SWING_VIOLATED, stamp(3), side="low", level=99.0),
        event(LIQUIDITY_SWEEP, stamp(4), sweep_direction="above_high",
              reclaimed=True),
    ])
    forming = path_machine.state()
    assert forming["owner"] == "none"
    assert forming["status"] == "forming"
    assert forming["forming_direction"] == "bearish"
    assert forming["origin"]["proof_family"] == "rejected_raid_reclaim"
    assert forming["last_invalidated"]["owner"] == "bullish"

    current_snapshot = snapshot(path=forming)
    current_snapshot["timestamp"] = stamp(4)
    current_continuity = recheck_narrative_continuity(
        current_snapshot, authored_continuity)
    assert current_continuity["control_state"] == "developing_transfer"
    result = classify(snap=current_snapshot, output={},
                      continuity=authored_continuity,
                      campaign=real_no_campaign_draw(forming),
                      brain_available=False)
    assert result["state"] == TRANSFER_UNRESOLVED
    assert result["participation_permitted"] is False


def test_lawful_initial_real_active_path_formation_establishes_and_refuses():
    from ai_brain.narrative_continuity import build_narrative_continuity
    from market_state.active_path import LIQUIDITY_SWEEP, ActivePath, occurrence_id

    path_machine = ActivePath()
    path_machine.enforce_lifecycle(stamp(0), CONTRACT)
    path_machine.ingest([{
        "occurrence_id": occurrence_id(CONTRACT, LIQUIDITY_SWEEP, "1m",
                                        stamp(0), "below_low"),
        "event_type": LIQUIDITY_SWEEP, "contract": CONTRACT,
        "source_tf": "1m", "event_time": stamp(0),
        "sweep_direction": "below_low", "reclaimed": True,
    }])
    path = path_machine.state()
    assert (path["owner"], path["status"], path["forming_direction"]) == (
        "none", "forming", "bullish")
    snap = snapshot(path=path)
    continuity = build_narrative_continuity(snap, {"available": False})
    assert continuity["control_state"] == "unestablished"
    result = classify(snap=snap, output={}, continuity=continuity,
                      campaign=real_no_campaign_draw(path), brain_available=False)
    assert result["state"] == ESTABLISHING
    assert participation_permission(result, "bullish")[0] is False


def test_forming_cannot_mask_unavailable_narrative_authority(monkeypatch):
    import ai_brain.narrative_continuity as continuity_module

    path = active_path(status="forming", owner="none", load_bearing_structure=None,
                       forming_direction="bullish")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("continuity unavailable")

    monkeypatch.setattr(continuity_module, "recheck_narrative_continuity", unavailable)
    result = classify(snap=snapshot(path=path), campaign=real_no_campaign_draw(path))
    assert result["state"] == AUTHORITY_UNKNOWN


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
