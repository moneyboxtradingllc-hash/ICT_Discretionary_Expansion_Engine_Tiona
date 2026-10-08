from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from ai_brain.narrative_continuity import build_narrative_continuity
from ai_brain import production_model as PM
from ai_retrieval.retrieval import retrieval_enabled
from broker import topstepx_session_authorization as SA
from broker.conditional_plan_authority import matches_authoring_output, validate
from broker.topstepx_candidate_freshness import CandidateSnapshot, LiquidityObjective
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data.campaign_lifecycle import AUTHORITY_UNKNOWN, evaluate_campaign_lifecycle


def context(monkeypatch, phase="continuation", *, prior_thesis=False):
    import test_luna_candidate_producer as fixtures
    from test_trade_horizon import authorities
    from broker.luna_candidate_producer import _digest

    authority_snapshot, draw, _ = authorities()
    snapshot = fixtures._detected("ifvg", "fvg")
    snapshot.update({"timestamp": authority_snapshot["timestamp"],
                     "contract_id": authority_snapshot["contract_id"],
                     "derived_state": deepcopy(authority_snapshot["derived_state"]),
                     "active_path_state": deepcopy(authority_snapshot["active_path_state"])})
    path = snapshot["active_path_state"]
    path["origin"]["source_tf"] = "1m"
    path["load_bearing_structure"].update({
        "timeframe": "5m", "basis": "sell_side_raid_rejected",
        "swing_id": "5m:swing_low:29875", "at": path["origin"]["at"]})
    if prior_thesis:
        from ai_brain.narrative_continuity import STATE_VERSION
        last = {
            "narrative_state_version": STATE_VERSION,
            "direction": "bullish", "campaign_direction": "bullish",
            "campaign_established": True,
            "timestamp": "2026-08-05T15:30:00+00:00",
            "phase": "continuation",
            "thesis_falsifier_status": "not_occurred",
            "thesis_falsifier": deepcopy(path["load_bearing_structure"]),
            "dominant_reasoning": "prior bullish campaign",
        }
        continuity = build_narrative_continuity(
            snapshot, {"available": True, "last": last})
    else:
        continuity = build_narrative_continuity(snapshot, {"available": False})
    invalidation_price = 29855.0
    output = fixtures.parsed(
        narrative_direction="bullish", narrative_phase=phase,
        current_action="watching",
        invalidation_level=invalidation_price,
        plan_expires_at=(fixtures.NOW + timedelta(minutes=5)).isoformat())
    block = {"source": "llm", "output": output, "fallback_reason": None,
             "llm_model": PM.PRODUCTION_MODEL,
             "narrative_continuity": continuity}
    result = ProductionScanCycle.to_brain_result(block)
    brain_input = fixtures.brain_input(prot_low=invalidation_price)
    # Objective identity is selected from the actual same-snapshot catalog.
    from broker.luna_candidate_producer import authorized_objective_catalog
    output["objective_id"] = next(
        row["objective_id"] for row in authorized_objective_catalog(
            snapshot, brain_input, 29880)
        if row["identity"] == "opposing_external_liquidity:buyside@29910.25")
    result = ProductionScanCycle.to_brain_result(block)
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output=output,
        narrative_continuity=continuity, campaign_draw=draw,
        session_id="TRADE-HORIZON-SESSION",
        contract_id="CON.F.US.MNQ.U26", brain_authority_available=True)
    assert lifecycle["state"] == ("RETRACING" if phase == "retracement"
                                   else "ACTIVE_DELIVERY")
    snapshot["campaign_lifecycle"] = lifecycle
    producer = fixtures.producer()
    candidate = fixtures.produce(
        p=producer, res=result, bi=brain_input, qual={"qualified": True},
        snapshot=snapshot, now=fixtures.NOW, conditional_plan=True,
        require_campaign_lifecycle=True, campaign_draw=draw,
        campaign_session_id="TRADE-HORIZON-SESSION")
    assert candidate.extras["conditional_plan"] is True
    assert candidate.extras["brain_response_digest"] == _digest(output)

    auth = SA.SessionAuthorization(
        session_id="TRADE-HORIZON-SESSION", account_fingerprint=candidate.account_fingerprint,
        contract_id=candidate.contract_id, session_date="20260805",
        decision_window=SA.window_text("20260805"),
        brain_model=PM.PRODUCTION_MODEL,
        brain_reasoning_effort=PM.reasoning_effort() or "",
        json_mode_required=True,
        brain_contract_fingerprint=PM.brain_contract_fingerprint(),
        retrieval_enabled=retrieval_enabled(), daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD,
        issued_at=fixtures.NOW.isoformat())
    auth.authorization_fingerprint = auth.fingerprint()
    scan = {"snapshot": snapshot, "snapshot_id": candidate.snapshot_id,
            "campaign_draw_authority": draw, "brain_block": block,
            "brain_result": result}
    authority = producer.capture_conditional_plan_authority(
        candidate=candidate, scan=scan, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION", now=fixtures.NOW)
    zone = candidate.extras["activation_zone"]
    trigger_quote = (float(zone["low"]) + float(zone["high"])) / 2
    brain_input["market"]["execution_price"] = fixtures.execution_block(
        trigger_quote, trigger_quote)
    return fixtures, snapshot, draw, candidate, result, brain_input, auth, producer, authority


@pytest.mark.parametrize("phase", ["continuation", "distribution", "retracement"])
def test_real_candidate_producer_plan_authority_survives_without_current_phase(
        monkeypatch, phase):
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

    (fixtures, snapshot, draw, candidate, result, brain_input, auth,
     producer, authority) = context(monkeypatch, phase)
    bound_result = authority.payload()["brain_result"]
    sealed_output = authority.payload()["parsed"]
    assert matches_authoring_output(
        authority=authority, scope=producer._conditional_plan_scope,
        parsed=deepcopy(sealed_output))
    altered_output = deepcopy(sealed_output)
    altered_output["narrative_phase"] = (
        "retracement" if sealed_output["narrative_phase"] != "retracement"
        else "continuation")
    assert not matches_authoring_output(
        authority=authority, scope=producer._conditional_plan_scope,
        parsed=altered_output)
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=bound_result["narrative_continuity"],
        campaign_draw=draw, session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, brain_authority_available=False)
    assert current["state"] == AUTHORITY_UNKNOWN
    assert current["reason"] == "current_brain_authority_unavailable"
    snapshot["campaign_lifecycle"] = current
    ok, reason, evidence = validate(
        authority=authority, scope=producer._conditional_plan_scope,
        candidate=candidate, candidate_at_trigger=None, brain_result=bound_result,
        snapshot=snapshot, brain_input=brain_input, draw=draw,
        lifecycle=current, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, session_id="TRADE-HORIZON-SESSION",
        trigger_event={"plan_id": candidate.candidate_id,
                       "occurrence_id": candidate.extras[
                           "selected_tool_occurrence_id"],
                       "reason": "conditional_plan_zone_reached"},
        now=fixtures.NOW + timedelta(seconds=1))
    assert ok, reason
    assert evidence["authority_basis"] == "PREAUTHORIZED_PLAN_JUDGMENT"
    assert evidence["authoring_phase"] == phase
    assert evidence["trigger_snapshot_id"] is None
    assert current["narrative_phase"] is None
    # Exercise the real CandidateProducer decision boundary; current Lifecycle
    # remains UNKNOWN while the sealed plan authority supplies the narrow path.
    snapshot["campaign_lifecycle"] = current
    triggered = fixtures.produce(
        p=producer, res=bound_result, bi=brain_input, qual={"qualified": True},
        snapshot=snapshot, now=fixtures.NOW + timedelta(seconds=1),
        snapshot_id=f"trigger-{phase}",
        conditional_trigger=True, require_campaign_lifecycle=True,
        campaign_draw=draw, campaign_session_id="TRADE-HORIZON-SESSION",
        conditional_plan_authority=authority,
        conditional_plan_candidate=candidate,
        conditional_session_authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        conditional_plan_trigger_event={
            "plan_id": candidate.candidate_id,
            "occurrence_id": candidate.extras["selected_tool_occurrence_id"],
            "reason": "conditional_plan_zone_reached"})
    assert triggered.direction == candidate.direction
    assert triggered.invalidation_price == candidate.invalidation_price
    assert triggered.objective.identity == candidate.objective.identity
    assert triggered.objective.kind == candidate.objective.kind
    assert triggered.objective.price == candidate.objective.price
    assert triggered.extras["conditional_plan_authority"]["authoring_phase"] == phase
    assert triggered.extras["trade_horizon"]["classification"] == AUTHORITY_UNKNOWN
    assert triggered.extras["current_lifecycle_assessment"]["reason"] == \
        "current_brain_authority_unavailable"
    assert triggered.extras["conditional_plan_authority"][
        "current_lifecycle"]["narrative_phase"] is None


def test_verified_plan_does_not_bypass_selected_target_r_floor(monkeypatch):
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle
    from broker.luna_candidate_producer import NoCandidate

    (fixtures, snapshot, draw, candidate, result, brain_input, auth,
     producer, authority) = context(monkeypatch)
    bound_result = authority.payload()["brain_result"]
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=bound_result["narrative_continuity"],
        campaign_draw=draw, session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, brain_authority_available=False)
    snapshot["campaign_lifecycle"] = current
    producer.min_r = 100.0
    with pytest.raises(NoCandidate, match="reward_below_qualification"):
        fixtures.produce(
            p=producer, res=bound_result, bi=brain_input,
            qual={"qualified": True}, snapshot=snapshot,
            now=fixtures.NOW + timedelta(seconds=1),
            snapshot_id="trigger-risk-scan",
            conditional_trigger=True, require_campaign_lifecycle=True,
            campaign_draw=draw, campaign_session_id="TRADE-HORIZON-SESSION",
            conditional_plan_authority=authority,
            conditional_plan_candidate=candidate,
            conditional_session_authorization=auth,
            process_session_id="TRADE-HORIZON-SESSION",
            conditional_plan_trigger_event={
                "plan_id": candidate.candidate_id,
                "occurrence_id": candidate.extras["selected_tool_occurrence_id"],
                "reason": "conditional_plan_zone_reached"})


def test_forming_hypothesis_cannot_hide_unresolved_transfer(monkeypatch):
    from market_data.campaign_lifecycle import TRANSFER_UNRESOLVED
    from broker.luna_candidate_producer import NoCandidate

    (fixtures, snapshot, draw, candidate, result, brain_input, auth,
     producer, authority) = context(monkeypatch, prior_thesis=True)
    path = snapshot["active_path_state"]
    path.update({"owner": "none", "status": "forming",
                 "forming_direction": "bearish"})
    path["origin"].update({
        "direction": "bearish", "proof_family": "rejected_raid_reclaim",
        "occurrence_id": "new-bearish-forming-origin",
        "at": "2026-08-05T15:32:00+00:00"})
    path["last_invalidated"] = {
        "owner": "bullish", "at": "2026-08-05T15:31:30+00:00",
        "level": 29875.0}
    draw["authority_status"] = "UNKNOWN"
    draw["superseded"] = True
    bound_result = authority.payload()["brain_result"]
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=bound_result["narrative_continuity"],
        campaign_draw=draw, session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, brain_authority_available=False)
    assert current["narrative_control_state"] == "developing_transfer"
    assert current["state"] == TRANSFER_UNRESOLVED
    snapshot["campaign_lifecycle"] = current
    with pytest.raises(NoCandidate, match="campaign_lifecycle_refused"):
        fixtures.produce(
            p=producer, res=bound_result, bi=brain_input,
            qual={"qualified": True}, snapshot=snapshot,
            now=fixtures.NOW + timedelta(seconds=1),
            conditional_trigger=True, require_campaign_lifecycle=True,
            campaign_draw=draw, campaign_session_id="TRADE-HORIZON-SESSION",
            conditional_plan_authority=authority,
            conditional_plan_candidate=candidate,
            conditional_session_authorization=auth,
            process_session_id="TRADE-HORIZON-SESSION",
            conditional_plan_trigger_event={
                "plan_id": candidate.candidate_id,
                "occurrence_id": candidate.extras["selected_tool_occurrence_id"],
                "reason": "conditional_plan_zone_reached"})


@pytest.mark.parametrize("mutation", [
    "owner", "owner_lost", "episode", "revision", "delivered", "draw_unknown",
    "superseded", "phase_reason", "objective", "fingerprint", "expired",
    "draw_objective", "draw_price", "falsifier_failed", "direction",
    "anchor", "market_session", "path_unavailable", "path_status",
    "origin", "falsifier", "invalidation", "occurrence", "zone",
    "brain_response", "authorization", "contract", "session",
    "trigger_event", "trigger_quote",
])
def test_plan_authority_fails_closed_on_bound_change(monkeypatch, mutation):
    from ai_brain import production_model as PM
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

    fixtures, snapshot, draw, candidate, result, brain_input, auth, producer, authority = context(monkeypatch)
    now = fixtures.NOW + timedelta(seconds=1)
    if mutation == "owner":
        snapshot["active_path_state"]["owner"] = "bearish"
    elif mutation == "owner_lost":
        snapshot["active_path_state"].update({"owner": "none", "status": "none"})
    elif mutation == "episode":
        draw["campaign_episode_id"] = "new-episode"
    elif mutation == "revision":
        snapshot["derived_state"]["history_revision"] += 1
        snapshot["derived_state"]["derived_revision"] += 1
        draw["history_revision"] += 1
    elif mutation == "delivered":
        draw["authority_status"] = "PROVEN_DELIVERED"
    elif mutation == "draw_unknown":
        draw["authority_status"] = "UNKNOWN"
    elif mutation == "superseded":
        draw["superseded"] = True
    elif mutation == "anchor":
        draw["anchor_bar_close"] += 0.25
    elif mutation == "draw_objective":
        draw["objective_identity"] = "new-campaign-objective"
    elif mutation == "draw_price":
        draw["objective_price"] += 0.25
    elif mutation == "falsifier_failed":
        snapshot["active_path_state"]["load_bearing_structure"]["intact"] = False
    elif mutation == "market_session":
        draw["market_session"] = "previous-market-session"
    elif mutation == "path_unavailable":
        snapshot["active_path_state"]["state_available"] = False
    elif mutation == "path_status":
        snapshot["active_path_state"]["status"] = "forming"
    elif mutation == "origin":
        snapshot["active_path_state"]["origin"]["occurrence_id"] = "new-origin"
    elif mutation == "falsifier":
        snapshot["active_path_state"]["load_bearing_structure"]["level"] += 0.25
    elif mutation == "invalidation":
        snapshot["active_path_state"]["last_invalidated"] = {
            "owner": "bullish", "at": "2026-08-05T15:32:00+00:00",
            "level": 29875.0}
    elif mutation == "occurrence":
        candidate.extras["selected_tool_occurrence_id"] = "different-occurrence"
    elif mutation == "zone":
        candidate.extras["activation_zone"]["low"] += 0.25
    elif mutation == "brain_response":
        result["parsed"]["objective_id"] = "different-objective"
    elif mutation == "direction":
        result["parsed"]["narrative_direction"] = "bearish"
    elif mutation == "authorization":
        auth.authorization_fingerprint = "auth:rotated"
    elif mutation == "contract":
        contract_id = "CON.F.US.ES.U26"
    elif mutation == "session":
        session_id = "new-session"
    elif mutation == "trigger_quote":
        brain_input["market"]["execution_price"] = fixtures.execution_block(
            29880.0, 29880.0)
    elif mutation == "fingerprint":
        monkeypatch.setattr(PM, "brain_contract_fingerprint", lambda: "brain:changed")
    elif mutation == "expired":
        now = fixtures.NOW + timedelta(minutes=6)
    elif mutation == "objective":
        candidate.objective = LiquidityObjective(
            identity="changed", kind="opposing_external_liquidity", price=29910.25,
            created_at=fixtures.NOW)
    validation_result = authority.payload()["brain_result"]
    if mutation in ("brain_response", "direction"):
        validation_result = result
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=validation_result["narrative_continuity"], campaign_draw=draw,
        session_id="TRADE-HORIZON-SESSION", contract_id=candidate.contract_id,
        brain_authority_available=False)
    if mutation == "phase_reason":
        current["reason"] = "active_path_unavailable"
    event = {"plan_id": candidate.candidate_id,
             "occurrence_id": candidate.extras["selected_tool_occurrence_id"],
             "reason": "conditional_plan_zone_reached"}
    if mutation == "trigger_event":
        event["occurrence_id"] = "another-occurrence"
    ok, reason, _ = validate(
        authority=authority, scope=producer._conditional_plan_scope,
        candidate=candidate, candidate_at_trigger=None,
        brain_result=validation_result,
        snapshot=snapshot, brain_input=brain_input, draw=draw,
        lifecycle=current, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        contract_id=locals().get("contract_id", candidate.contract_id),
        session_id=locals().get("session_id", "TRADE-HORIZON-SESSION"),
        trigger_event=event,
        now=now)
    assert not ok, mutation
    assert reason


def test_plan_authority_is_process_local_and_rejects_other_producer(monkeypatch):
    fixtures, snapshot, draw, candidate, result, brain_input, auth, producer, authority = context(monkeypatch)
    other = fixtures.producer()
    current = snapshot["campaign_lifecycle"]
    ok, _, _ = validate(
        authority=authority, scope=other._conditional_plan_scope,
        candidate=candidate, candidate_at_trigger=None, brain_result=result,
        snapshot=snapshot, brain_input=brain_input, draw=draw,
        lifecycle={**current, "state": AUTHORITY_UNKNOWN,
                   "reason": "current_brain_authority_unavailable",
                   "narrative_phase": None}, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, session_id="TRADE-HORIZON-SESSION",
        trigger_event={"plan_id": candidate.candidate_id,
                       "occurrence_id": candidate.extras[
                           "selected_tool_occurrence_id"],
                       "reason": "conditional_plan_zone_reached"},
        now=fixtures.NOW + timedelta(seconds=1))
    assert not ok


def test_saved_json_cannot_restore_live_plan_authority(monkeypatch):
    fixtures, snapshot, draw, candidate, result, brain_input, auth, producer, authority = context(monkeypatch)
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=result["narrative_continuity"],
        campaign_draw=draw, session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, brain_authority_available=False)
    ok, reason, _ = validate(
        authority=authority.payload(), scope=producer._conditional_plan_scope,
        candidate=candidate, candidate_at_trigger=None, brain_result=result,
        snapshot=snapshot, brain_input=brain_input, draw=draw,
        lifecycle=current, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, session_id="TRADE-HORIZON-SESSION",
        trigger_event={"plan_id": candidate.candidate_id,
                       "occurrence_id": candidate.extras[
                           "selected_tool_occurrence_id"],
                       "reason": "conditional_plan_zone_reached"},
        now=fixtures.NOW + timedelta(seconds=1))
    assert not ok
    assert reason == "conditional_plan_authority_missing_or_unbound"


def test_healthy_cutoff_and_obstacle_evidence_changes_do_not_invalidate_plan(
        monkeypatch):
    fixtures, snapshot, draw, candidate, result, brain_input, auth, producer, authority = context(monkeypatch)
    draw["settled_cutoff"] = (
        datetime.fromisoformat(draw["settled_cutoff"])
        + timedelta(minutes=1)).isoformat()
    # A later trigger scan's snapshot is cut at its own settled bar.
    snapshot["timestamp"] = draw["settled_cutoff"]
    candidate.extras["trade_horizon"]["protected_structure"] = {
        "status": "AVAILABLE", "reason": None,
        "witnesses": [{"timeframe": "5m", "price": 29864.0}],
        "nearest": [{"price": 29864.0, "reward_to_risk": 0.1}],
    }
    snapshot["active_path_state"]["progression"]["supporting_timeframes"].append(
        "1m")
    bound_result = authority.payload()["brain_result"]
    current = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=bound_result["narrative_continuity"],
        campaign_draw=draw, session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, brain_authority_available=False)
    ok, reason, _ = validate(
        authority=authority, scope=producer._conditional_plan_scope,
        candidate=candidate, candidate_at_trigger=None, brain_result=bound_result,
        snapshot=snapshot, brain_input=brain_input, draw=draw,
        lifecycle=current, authorization=auth,
        process_session_id="TRADE-HORIZON-SESSION",
        contract_id=candidate.contract_id, session_id="TRADE-HORIZON-SESSION",
        trigger_event={"plan_id": candidate.candidate_id,
                       "occurrence_id": candidate.extras[
                           "selected_tool_occurrence_id"],
                       "reason": "conditional_plan_zone_reached"},
        now=fixtures.NOW + timedelta(seconds=1))
    assert ok, reason


def test_real_production_loop_trigger_passes_sealed_plan_without_brain_call(
        monkeypatch):
    from types import SimpleNamespace

    import broker.topstepx_production_loop as loop_module
    from broker.topstepx_production_loop import ProductionLoop
    import live_scan.production_scan_cycle as cycle_module

    (fixtures, snapshot, draw, candidate, result, brain_input, auth,
     producer, authority) = context(monkeypatch)
    zone = candidate.extras["activation_zone"]
    quote = float(brain_input["market"]["execution_price"]["bullish_executable"])
    plan = {
        "plan_id": candidate.candidate_id,
        "candidate": candidate,
        "authority": authority,
        "parsed": dict(candidate.extras["conditional_plan_brain_output"]),
        "brain_result": dict(candidate.extras["conditional_plan_brain_result"]),
        "published_at": fixtures.NOW.isoformat(),
    }
    # The real plan container keeps a shallow converted result. Ordinary path
    # progression can update its aliased authoring-continuity evidence; the
    # sealed result must supply the original judgment without rejecting noise.
    snapshot["active_path_state"]["progression"]["supporting_timeframes"].append(
        "3m")
    draw["settled_cutoff"] = (
        datetime.fromisoformat(draw["settled_cutoff"])
        + timedelta(minutes=1)).isoformat()
    # A later trigger scan's snapshot is cut at its own settled bar.
    snapshot["timestamp"] = draw["settled_cutoff"]
    trigger_block = {"source": "preauthorized_plan_trigger", "output": None,
                     "fallback_reason": None}
    scan = {
        "snapshot": snapshot,
        "brain_block": trigger_block,
        "brain_result": ProductionScanCycle.to_brain_result(trigger_block),
        "brain_input": brain_input,
        "campaign_draw_authority": draw,
        "qualification": {"qualified": True},
        "engine_inventory": {"liquidity": "PRESENT_AND_POPULATED"},
        "snapshot_id": "trigger-snapshot-2",
        "market_data_timestamp": "2026-08-05T15:30:01+00:00",
        "latest_closed_bar_timestamp": "2026-08-05T15:30:00+00:00",
    }
    mission = SimpleNamespace(authorization=auth, candidate_count=0,
                               trade_missions=[], active_mission=None)
    geometry = SimpleNamespace(size=1, stop_points=8,
                               stop_price=candidate.invalidation_price,
                               target_price=candidate.objective.price,
                               risk_usd=4.0)
    ps = SimpleNamespace(
        session=object(), contract=fixtures.MNQ,
        sizing={"stop_range": 8, "reward_to_risk": 5.9}, runner=None,
        build_runner=lambda *_args, **_kwargs: SimpleNamespace(geometry=geometry))
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.active_conditional_plan = plan
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True))
    loop.producer = producer
    loop.mission = mission
    loop.ps = ps
    loop.cycle = SimpleNamespace(session_id="TRADE-HORIZON-SESSION",
                                 contract_id=candidate.contract_id)
    loop.clock = lambda: fixtures.NOW + timedelta(seconds=1)
    loop.armed = False
    loop._record_plan_events = lambda *_args, **_kwargs: None
    loop._record_decision = lambda *_args, **_kwargs: None
    attached = []
    def attach_current_evidence(fresh_candidate, fresh_scan, **kwargs):
        ProductionLoop._attach_evidence(loop, fresh_candidate, fresh_scan, **kwargs)
        attached.append(fresh_candidate)
    loop._attach_evidence = attach_current_evidence
    monkeypatch.setattr(loop_module.DLB, "resolve", lambda **_kwargs: {
        "entry_permitted": True, "allowed_planned_risk": 200.0})
    brain_calls = []
    monkeypatch.setattr(cycle_module, "run_narrative_brain",
                        lambda *_args, **_kwargs: brain_calls.append(True))

    outcome = loop._execute_conditional_plan(
        scan, conditional_event={
            "plan_id": candidate.candidate_id,
            "occurrence_id": zone["occurrence_id"],
            "reason": "conditional_plan_zone_reached",
            "price": quote,
        }, in_window=True)

    assert outcome["outcome"] == loop_module.QUALIFIED_CANDIDATE_OBSERVED
    assert outcome["execution"] == loop_module.EXECUTION_DISARMED
    assert loop.active_conditional_plan is None
    assert brain_calls == []
    assert scan["brain_result"]["parsed"] == {}
    assert snapshot["campaign_lifecycle"]["state"] == AUTHORITY_UNKNOWN
    assert snapshot["campaign_lifecycle"]["reason"] == \
        "current_brain_authority_unavailable"
    assert len(attached) == 1
    assert attached[0].extras["brain_result"]["parsed"] == {}
    assert attached[0].extras["evidence"]["production_brain"]["direction"] is None
    assert attached[0].extras["evidence"]["production_brain"]["action"] == ""
    authoring = attached[0].extras["preauthorized_plan_authoring"]
    assert authoring["authority_basis"] == "PREAUTHORIZED_PLAN_JUDGMENT"
    assert authoring["authoring_phase"] == "continuation"
    assert authoring["parsed"]["narrative_phase"] == "continuation"
    assert attached[0].entry_price == quote
    assert attached[0].entry_price != candidate.entry_price
    assert attached[0].extras["current_lifecycle_assessment"]["narrative_phase"] is None
    trace = producer.last_decision_trace
    assert trace["campaign_lifecycle_state"] == AUTHORITY_UNKNOWN
    assert trace["campaign_lifecycle_authority_basis"] == \
        "PREAUTHORIZED_PLAN_JUDGMENT"
