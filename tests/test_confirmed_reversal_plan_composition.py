from __future__ import annotations

from datetime import timedelta

from ai_brain import production_model as PM
from ai_brain.narrative_continuity import build_narrative_continuity
from ai_brain.stance_memory import StanceMemory
from broker import topstepx_session_authorization as SA
from broker.luna_candidate_producer import authorized_objective_catalog
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data.campaign_draw_truth import CampaignDrawTruth
from market_data.campaign_lifecycle import AUTHORITY_UNKNOWN, evaluate_campaign_lifecycle
from market_state.active_path import ActivePath, extract_occurrences
from ai_retrieval.retrieval import retrieval_enabled

import test_luna_candidate_producer as fixtures


def test_verified_reversal_watch_plan_reaches_real_no_brain_trigger():
    """A synthetic causal tape traverses real producers and the real gate."""
    contract = fixtures.CID
    session_id = "TRADE-HORIZON-SESSION"
    revision = 9
    now = fixtures.NOW
    stamp = lambda minute: f"2026-08-05T15:{minute:02d}:00+00:00"
    path_machine = ActivePath()
    path_machine.enforce_lifecycle(now.isoformat(), contract)
    prior_protected = {}

    def path_scan(at, *, raid=None, bos=None, protected=None):
        nonlocal prior_protected
        protected = protected or {"lows": {}, "highs": {}}
        snapshot = {
            "timestamp": at,
            "contract_id": contract,
            "liquidity": ({"1m": {
                "sweep_detected": True,
                "reclaim_detected": True,
                "sweep_direction": raid,
                "sweep_fact": {"swept_level": 29875.0 if raid == "below_low"
                               else 29915.0},
            }} if raid else {}),
            "structure": ({"1m": {
                "bos": True,
                "bos_direction": bos,
                "broken_level": 29875.0 if bos == "bullish" else 29915.0,
            }} if bos else {}),
            "settled_source": {tf: {"source_bar_time": at,
                                    "settled_edge_time": at,
                                    "temporal_status": "settled"}
                               for tf in ("1m", "3m", "5m", "15m")},
            "protected_swings": {"by_timeframe": protected},
        }
        path_machine.enforce_lifecycle(at, contract)
        path_machine.ingest(extract_occurrences(snapshot, prior_protected, contract))
        prior_protected = protected
        snapshot["active_path_state"] = path_machine.state()
        return snapshot

    old_low = {"5m": {"level": 29875.0,
                       "basis": "sell_side_raid_rejected",
                       "swing_id": "5m:old-bull-low",
                       "registered_at": stamp(18), "role": "active_leg",
                       "side": "low", "timeframe": "5m"}}
    initial = path_scan(stamp(20), raid="below_low", bos="bullish",
                        protected={"lows": old_low, "highs": {}})
    assert (initial["active_path_state"]["owner"],
            initial["active_path_state"]["status"]) == ("bullish", "active")
    memory = StanceMemory(persist=False)
    continuity = build_narrative_continuity(initial, {"available": False})
    memory.record(stamp(20), {
        "narrative_direction": "bullish", "narrative_phase": "continuation",
        "current_action": "propose_entry"}, continuity)

    failed = path_scan(stamp(23))
    assert failed["active_path_state"]["owner"] == "none"
    failure_continuity = build_narrative_continuity(failed, memory.history_summary())
    assert failure_continuity["control_state"] == "developing_transfer"
    assert failed["active_path_state"]["last_invalidated"]["swing_id"] == \
        "5m:old-bull-low"
    memory.record(stamp(23), {
        "narrative_direction": "bullish", "narrative_phase": "transition",
        "current_action": "stand_down"}, failure_continuity)

    forming = path_scan(stamp(24), raid="above_high")
    assert (forming["active_path_state"]["owner"],
            forming["active_path_state"]["status"],
            forming["active_path_state"]["forming_direction"]) == (
                "none", "forming", "bearish")
    new_high = {"5m": {"level": 29915.0,
                        "basis": "buy_side_raid_rejected",
                        "swing_id": "5m:new-bear-high",
                        "registered_at": stamp(25), "role": "active_leg",
                        "side": "high", "timeframe": "5m"}}
    confirmed = path_scan(stamp(26), bos="bearish",
                          protected={"lows": {}, "highs": new_high})
    assert (confirmed["active_path_state"]["owner"],
            confirmed["active_path_state"]["status"]) == ("bearish", "active")

    path_machine.enforce_lifecycle(now.isoformat(), contract)
    snapshot = fixtures._detected("fvg", direction="bearish")
    snapshot.update({"timestamp": now.isoformat(), "contract_id": contract,
                     "active_path_state": path_machine.state(),
                     "derived_state": {"current": True,
                                       "history_revision": revision,
                                       "derived_revision": revision}})
    continuity = build_narrative_continuity(snapshot, memory.history_summary())
    assert continuity["control_state"] == "confirmed_transfer"
    assert continuity["confirmed_to"] == "bearish"
    assert continuity["transfer_proof"]["status"] == "verified"

    brain_input = fixtures.brain_input(
        price=29863.0, buy_side=30000.0, sell_side=29700.0,
        prot_low=29875.0, prot_high=29915.0,
        execution=fixtures.execution_block(29863.0, 29863.0))
    objective_rows = authorized_objective_catalog(snapshot, brain_input, 29863.0)
    objective = next((row for row in objective_rows
                      if row["identity"] ==
                      "opposing_external_liquidity:sellside@29700.0"), None)
    assert objective is not None, objective_rows
    accepted = {
        "direction_authorized": True,
        "direction": "bearish",
        "objective": {key: objective[key] for key in ("identity", "kind", "price")},
        "brain_lineage": {"source": "llm", "snapshot_id": "reversal-plan-scan"},
    }
    tracker = CampaignDrawTruth(contract_id=contract, session_id=session_id,
                                instrument="MNQ")

    def observe_draw(rows):
        return tracker.observe(
            settled_bars=rows,
            settled_source={"source_bar_time": rows[-1]["timestamp"],
                            "temporal_status": "settled",
                            "settled_edge_basis": "no_member_list_published"},
            contract_id=contract, session_id=session_id,
            history_revision=revision, derived_state_current=True,
            accepted_view=accepted, ownership_state=path_machine.state())

    bars = [{"timestamp": stamp(minute), "open": 29863.0, "high": 29864.0,
             "low": 29862.0, "close": 29863.0, "volume": 10,
             "contract": contract, "members": 1, "expected_members": 1,
             "complete": True} for minute in (28, 29, 30)]
    # The Draw is accepted on the prior scan; this planning scan holds its
    # measurement one settled minute beyond that birth anchor.
    born = observe_draw(bars[:-1])
    assert born["settled_cutoff"] == born["anchor_bar_time"]
    draw = observe_draw(bars)
    assert draw["record_id"] == born["record_id"]
    assert draw["settled_cutoff"] == bars[-1]["timestamp"] == now.isoformat()
    assert draw["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert draw["campaign_direction"] == "bearish"
    snapshot["settled_source"] = {"1m": {
        "source_bar_time": bars[-1]["timestamp"], "temporal_status": "settled"}}

    output = fixtures.parsed(
        narrative_direction="bearish", narrative_phase="reversal",
        current_action="watching", invalidation_id="",
        invalidation_level=29915.0,
        active_draw="sell side liquidity below",
        objective_id=objective["objective_id"],
        recommended_playbook_family="manipulation_to_distribution",
        recommended_tool_family=["fvg"],
        plan_expires_at=(now + timedelta(minutes=5)).isoformat())
    block = {"source": "llm", "output": output, "fallback_reason": None,
             "llm_model": PM.PRODUCTION_MODEL,
             "narrative_continuity": continuity}
    brain_result = ProductionScanCycle.to_brain_result(block)
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output=output,
        narrative_continuity=continuity, campaign_draw=draw,
        session_id=session_id, contract_id=contract,
        brain_authority_available=True)
    assert lifecycle["state"] == "ACTIVE_DELIVERY"
    snapshot["campaign_lifecycle"] = lifecycle

    producer = fixtures.producer()
    candidate = producer.produce(
        brain_result=brain_result, brain_input=brain_input, snapshot=snapshot,
        qualification={"qualified": True},
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id="reversal-plan-scan", market_data_timestamp=now.isoformat(),
        latest_closed_bar_timestamp=now.isoformat(), now=now,
        conditional_plan=True, require_campaign_lifecycle=True,
        campaign_draw=draw, campaign_session_id=session_id)
    assert candidate.direction == "bearish"
    assert candidate.extras["conditional_plan"] is True

    authorization = SA.SessionAuthorization(
        session_id=session_id, account_fingerprint=candidate.account_fingerprint,
        contract_id=contract, session_date="20260805",
        decision_window=SA.window_text("20260805"),
        brain_model=PM.PRODUCTION_MODEL,
        brain_reasoning_effort=PM.reasoning_effort() or "",
        json_mode_required=True,
        brain_contract_fingerprint=PM.brain_contract_fingerprint(),
        retrieval_enabled=retrieval_enabled(),
        daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD,
        issued_at=now.isoformat())
    authorization.authorization_fingerprint = authorization.fingerprint()
    from broker.conditional_plan_authority import _transfer_binding
    proof = continuity["transfer_proof"]
    assert _transfer_binding(proof, contract_id=contract,
                             session=path_machine.state().get("session")) is not None, (
        sorted(proof), sorted((proof.get("incumbent_invalidation") or {})),
        sorted((proof.get("authoritative_opposing_origin") or {})),
        proof.get("contract_id"), proof.get("session"))
    assert ProductionScanCycle.is_sovereign(block)
    assert ProductionScanCycle.is_validated_brain_result(brain_result)
    assert brain_result["parsed"] == output
    assert lifecycle["participation_permitted"] is True
    assert lifecycle["narrative_phase"] == "reversal"
    authority = producer.capture_conditional_plan_authority(
        candidate=candidate,
        scan={"snapshot": snapshot, "snapshot_id": "reversal-plan-scan",
              "campaign_draw_authority": draw, "brain_block": block,
              "brain_result": brain_result},
        authorization=authorization, process_session_id=session_id, now=now)
    assert authority.payload()["authoring_phase"] == "reversal"
    assert authority.payload()["authoring_transfer_proof"]["to_direction"] == "bearish"

    trigger_time = (now + timedelta(minutes=1)).isoformat()
    path_machine.enforce_lifecycle(trigger_time, contract)
    trigger_snapshot = fixtures._detected("fvg", direction="bearish")
    trigger_snapshot.update({"timestamp": trigger_time, "contract_id": contract,
                             "active_path_state": path_machine.state(),
                             "derived_state": {"current": True,
                                               "history_revision": revision,
                                               "derived_revision": revision}})
    bars.append({"timestamp": trigger_time, "open": 29863.0, "high": 29864.0,
                 "low": 29862.0, "close": 29863.0, "volume": 10,
                 "contract": contract, "members": 1, "expected_members": 1,
                 "complete": True})
    current_draw = observe_draw(bars)
    trigger_snapshot["settled_source"] = {"1m": {
        "source_bar_time": trigger_time, "temporal_status": "settled"}}
    current_lifecycle = evaluate_campaign_lifecycle(
        snapshot=trigger_snapshot, brain_output={},
        narrative_continuity=continuity, campaign_draw=current_draw,
        session_id=session_id, contract_id=contract,
        brain_authority_available=False)
    assert current_lifecycle["state"] == AUTHORITY_UNKNOWN
    assert current_lifecycle["reason"] == "current_brain_authority_unavailable"
    trigger_snapshot["campaign_lifecycle"] = current_lifecycle
    brain_input["timestamp"] = trigger_time
    brain_input["market"]["execution_price"] = fixtures.execution_block(
        29863.0, 29863.0)

    triggered = producer.produce(
        brain_result=authority.payload()["brain_result"],
        brain_input=brain_input, snapshot=trigger_snapshot,
        qualification={"qualified": True},
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id="reversal-trigger-scan",
        market_data_timestamp=trigger_time,
        latest_closed_bar_timestamp=trigger_time,
        now=now + timedelta(minutes=1), conditional_trigger=True,
        require_campaign_lifecycle=True, campaign_draw=current_draw,
        campaign_session_id=session_id,
        conditional_plan_authority=authority,
        conditional_plan_candidate=candidate,
        conditional_session_authorization=authorization,
        process_session_id=session_id,
        conditional_plan_trigger_event={
            "plan_id": candidate.candidate_id,
            "occurrence_id": candidate.extras["selected_tool_occurrence_id"],
            "reason": "conditional_plan_zone_reached"})
    assert triggered.direction == "bearish"
    assert triggered.extras["conditional_plan_authority"][
        "authoring_phase"] == "reversal"
    assert triggered.extras["current_lifecycle_assessment"]["state"] == \
        AUTHORITY_UNKNOWN
    assert triggered.extras["current_lifecycle_assessment"][
        "narrative_phase"] is None
