"""STAGE 2 -- EXACT DRAW GENERATION AND MEASUREMENT BINDING.

8ad1f76 bound a permissive Lifecycle to its participation authority by labels
only: campaign episode, objective identity and status. Two Draws can share all
three and still be different authority:

  * the SAME record's birth-scan measurement (settled_cutoff == anchor), which
    is only the Brain's judgment restated, never later market evidence;
  * a DIFFERENT record (another generation) carrying the same labels;
  * a measurement scoped to another contract or process session.

The closure binds every permissive consumer to ONE Draw generation (stable
`record_id` plus its generation identity) measured at ONE settled cutoff --
the consumer's own current snapshot cutoff, strictly beyond the birth anchor.
A conditional plan binds the generation, not the planning cutoff: its trigger
must hold that same generation's CURRENT measurement, later than planning.

Every scan below is the real ProductionScanCycle on the synthetic reversal tape
with mocked model transport only. Ordinary consumers run through the real
`ProductionLoop._scan_once`; triggers through the real
`ProductionLoop._execute_conditional_plan`. Both stop at the daily-loss budget
step, before any mission, token or venue use.

DEFENSE-ONLY SUBSTITUTIONS. ProductionScanCycle publishes the authority its
Lifecycle was computed from; these tests replace it at the consumer boundary,
leaving the scan's permissive Lifecycle attached, to prove the consumer refuses
rather than trusting labels. They do not model a normal producer omission.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

import test_campaign_draw_temporal_authority as TA
import test_reversal_foundation_proof_closure as RF
from broker.conditional_plan_authority import _draw_identity
from broker.luna_candidate_producer import CandidateProducer
from market_data.campaign_draw_truth import CampaignDrawTruth
from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

UNMEASURED = "campaign_draw_not_measured_beyond_birth_anchor"
NOT_CURRENT = "campaign_draw_measurement_not_current"
NOT_BOUND = "campaign_lifecycle_not_bound_to_participation_authority"
SCOPE = "campaign_draw_scope_mismatch"
PLAN_NOT_CURRENT = "conditional_plan_draw_measurement_not_current"
PLAN_CHANGED = "conditional_plan_campaign_draw_changed_or_unavailable"
LABELS = ("campaign_episode_id", "objective_identity", "authority_status")


def _instant(value):
    return datetime.fromisoformat(str(value))


def _assert_birth_measurement(birth, lawful):
    """The same generation, as measured on the scan that minted it."""
    assert birth["record_id"] == lawful["record_id"]
    assert birth["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert birth["superseded"] is False
    assert birth["settled_cutoff"] == birth["anchor_bar_time"]
    assert _instant(lawful["settled_cutoff"]) > _instant(birth["settled_cutoff"])
    for key in LABELS:
        assert birth[key] == lawful[key]


def _birth_and_lawful(tmp_path, monkeypatch, ecu, mutator=None):
    cycle, calls = TA._cycle_with_brain(tmp_path, monkeypatch, ecu=ecu,
                                        mutator=mutator)
    birth = TA._scan(cycle, RF.TAPE_1M)
    lawful = TA._scan(cycle, TA.LATER)
    assert len(calls) == 2
    authority = lawful["campaign_draw_authority"]
    assert "participation_withheld_reason" not in authority
    assert lawful["campaign_lifecycle"]["participation_permitted"] is True
    assert lawful["snapshot"]["campaign_lifecycle"] == lawful["campaign_lifecycle"]
    # On a real scan the consumer's current settled evidence -- the snapshot's
    # settled bar time -- IS the authority's measurement cutoff.
    assert lawful["snapshot"]["timestamp"] == authority["settled_cutoff"]
    assert lawful["latest_closed_bar_timestamp"] == authority["settled_cutoff"]
    _assert_birth_measurement(birth["campaign_draw_truth"], authority)
    return cycle, calls, birth, lawful


def _reevaluate(scan, draw):
    """Lifecycle exactly as ProductionScanCycle evaluated it, with `draw`."""
    block = scan["brain_block"]
    return evaluate_campaign_lifecycle(
        snapshot=scan["snapshot"], brain_output=block.get("output") or {},
        narrative_continuity=block.get("narrative_continuity") or {},
        campaign_draw=draw,
        current_draw_acceptance=scan["campaign_draw_acceptance"],
        session_id=RF.SESSION_ID, contract_id=RF.CONTRACT,
        brain_authority_available=True)


# ── Lifecycle is born bound to one generation and one current measurement ──
@TA.ECU_MODES
def test_permissive_lifecycle_records_exact_generation_and_measurement(
        tmp_path, monkeypatch, ecu):
    from market_data.campaign_draw_truth import participation_binding

    _cycle, _calls, _birth, lawful = _birth_and_lawful(tmp_path, monkeypatch, ecu)
    authority = lawful["campaign_draw_authority"]
    lifecycle = lawful["campaign_lifecycle"]
    assert lifecycle["state"] == "ACTIVE_DELIVERY"
    binding = lifecycle["campaign_draw_binding"]
    assert binding == participation_binding(authority)
    assert binding["record_id"] == authority["record_id"]
    assert binding["settled_cutoff"] == lawful["snapshot"]["timestamp"]
    assert _instant(binding["settled_cutoff"]) > _instant(binding["anchor_bar_time"])
    assert (binding["session_id"], binding["contract_id"]) == (
        RF.SESSION_ID, RF.CONTRACT)
    # Re-evaluation from the published authority reproduces it exactly.
    assert _reevaluate(lawful, authority) == lifecycle


@TA.ECU_MODES
def test_lifecycle_refuses_birth_or_older_measurement_of_same_generation(
        tmp_path, monkeypatch, ecu):
    cycle, calls, birth, lawful = _birth_and_lawful(tmp_path, monkeypatch, ecu)
    birth_measurement = copy.deepcopy(birth["campaign_draw_truth"])
    refused = _reevaluate(lawful, birth_measurement)
    assert refused["state"] == "AUTHORITY_UNKNOWN"
    assert refused["reason"] == UNMEASURED
    assert refused["participation_permitted"] is False

    # A measurement beyond birth but from an EARLIER scan is not current.
    newer = TA._scan(cycle, TA.LATER2)
    assert len(calls) == 3
    assert newer["campaign_lifecycle"]["participation_permitted"] is True
    older = copy.deepcopy(lawful["campaign_draw_authority"])
    assert older["record_id"] == newer["campaign_draw_authority"]["record_id"]
    assert _instant(older["settled_cutoff"]) > _instant(older["anchor_bar_time"])
    assert older["settled_cutoff"] != newer["snapshot"]["timestamp"]
    stale = _reevaluate(newer, older)
    assert stale["state"] == "AUTHORITY_UNKNOWN"
    assert stale["reason"] == NOT_CURRENT


# ── Ordinary ProductionLoop consumer ────────────────────────────────────────
def _forged(substitution, birth, lawful_authority):
    if substitution == "birth_measurement":
        return copy.deepcopy(birth["campaign_draw_truth"])
    forged = copy.deepcopy(lawful_authority)
    if substitution == "different_record":
        forged["record_id"] = "f" * 24
    elif substitution == "contradictory_contract":
        forged["contract_id"] = "CON.F.US.MES.Z26"
    elif substitution == "contradictory_session":
        forged["session_id"] = "ANOTHER-PROCESS-SESSION"
    else:
        raise AssertionError(substitution)
    return forged


@TA.ECU_MODES
@pytest.mark.parametrize("substitution,expected", [
    ("birth_measurement", UNMEASURED),
    ("different_record", NOT_BOUND),
    ("contradictory_contract", SCOPE),
    ("contradictory_session", SCOPE),
])
def test_ordinary_loop_refuses_substituted_generation_measurement_or_scope(
        tmp_path, monkeypatch, ecu, substitution, expected):
    _cycle, calls, birth, scan = _birth_and_lawful(tmp_path, monkeypatch, ecu)
    lawful_authority = copy.deepcopy(scan["campaign_draw_authority"])
    permissive = copy.deepcopy(scan["snapshot"]["campaign_lifecycle"])
    forged = _forged(substitution, birth, lawful_authority)
    # Every label the label-only binding compared still matches.
    for key in LABELS:
        assert forged[key] == lawful_authority[key]
    assert permissive["campaign_episode_id"] == forged["campaign_episode_id"]
    assert permissive["objective_identity"] == forged["objective_identity"]
    assert permissive["campaign_draw_status"] == forged["authority_status"]
    scan["campaign_draw_authority"] = forged
    assert scan["snapshot"]["campaign_lifecycle"] == permissive

    brain_calls = len(calls)
    loop, outcome, budget_calls, decisions, venue = TA._run_ordinary(
        monkeypatch, scan)
    assert len(calls) == brain_calls
    assert outcome["reason"] == "campaign_lifecycle_refused"
    assert outcome["detail"] == f"campaign_lifecycle_refused: {expected}"
    assert decisions[-1][:2] == ("REJECTED", "campaign_lifecycle_refused")
    assert loop.active_candidate is None
    assert loop.mission.candidate_count == 0
    assert budget_calls == []
    assert loop.mission.trade_missions == []
    assert venue.calls == []


# ── Conditional plan through the real ProductionLoop trigger lane ──────────
def _sealed_plan(tmp_path, monkeypatch, ecu):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls, birth, planning = _birth_and_lawful(
        tmp_path, monkeypatch, ecu, mutator=TA._watching(now))
    producer = CandidateProducer(account_fingerprint="acct:exact-binding",
                                 contract=RF.MNQ)
    plan_candidate = TA._plan_candidate(producer, planning, now)
    assert plan_candidate.extras["conditional_plan"] is True
    auth = TA._authorization(plan_candidate, now)
    authority = producer.capture_conditional_plan_authority(
        candidate=plan_candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    bound = authority.payload()["draw"]
    assert bound == _draw_identity(planning["campaign_draw_authority"])
    return now, cycle, calls, producer, birth, planning, plan_candidate, auth, authority


def _trigger_scan(cycle, calls, monkeypatch, record_id):
    """One brainless trigger scan: no Brain call, one advancement."""
    advances = []
    original = CampaignDrawTruth._advance

    def counted(instance, record, rows, cutoff):
        if instance is cycle.campaign_draw_truth:
            advances.append((record.get("record_id"), cutoff))
        return original(instance, record, rows, cutoff)

    monkeypatch.setattr(CampaignDrawTruth, "_advance", counted)
    brain_calls = len(calls)
    trigger = TA._scan(cycle, TA.NEXT_MINUTE, brain=False)
    monkeypatch.setattr(CampaignDrawTruth, "_advance", original)
    assert len(calls) == brain_calls
    assert trigger["campaign_draw_acceptance"] is None
    assert [rid for rid, _cutoff in advances] == [record_id]
    return trigger


def _trigger_loop(monkeypatch, *, producer, plan_candidate, authority, auth, now):
    from types import SimpleNamespace
    import broker.topstepx_production_loop as loop_module
    from broker.topstepx_production_loop import ProductionLoop

    budget_calls, decisions = [], []

    def budget(**_kwargs):
        budget_calls.append(True)
        return {"entry_permitted": False, "state": "TEST_STOP_BEFORE_MISSION",
                "reason": "trigger control stops before any mission"}

    monkeypatch.setattr(loop_module.DLB, "resolve", budget)
    venue = TA._VenueRecorder()
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.active_conditional_plan = {
        "plan_id": plan_candidate.candidate_id, "candidate": plan_candidate,
        "authority": authority,
        "parsed": dict(plan_candidate.extras["conditional_plan_brain_output"]),
        "brain_result": dict(plan_candidate.extras["conditional_plan_brain_result"]),
        "published_at": now.isoformat()}
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True))
    loop.producer = producer
    loop.mission = SimpleNamespace(authorization=auth, candidate_count=0,
                                   trade_missions=[], active_mission=None)
    loop.ps = SimpleNamespace(session=venue, contract=RF.MNQ)
    loop.cycle = SimpleNamespace(session_id=RF.SESSION_ID, contract_id=RF.CONTRACT)
    loop.clock = lambda: now
    loop.armed = False
    loop._record_plan_events = lambda *_args, **_kwargs: None
    loop._record_decision = lambda _scan, disposition, reason, detail, **_kw: \
        decisions.append((disposition, reason, detail))
    loop._attach_evidence = lambda *_args, **_kwargs: None
    return loop, budget_calls, decisions, venue


def _fire(loop, trigger, plan_candidate):
    import test_luna_candidate_producer as fixtures

    zone = plan_candidate.extras["activation_zone"]
    inside = (float(zone["low"]) + float(zone["high"])) / 2
    trigger["brain_input"].setdefault("market", {})["execution_price"] = \
        fixtures.execution_block(inside, inside)
    return loop._execute_conditional_plan(trigger, conditional_event={
        "plan_id": plan_candidate.candidate_id,
        "occurrence_id": zone["occurrence_id"],
        "reason": "conditional_plan_zone_reached", "price": inside},
        in_window=True)


@TA.ECU_MODES
def test_real_trigger_same_generation_later_measurement_is_preserved(
        tmp_path, monkeypatch, ecu):
    (now, cycle, calls, producer, _birth, planning, plan_candidate, auth,
     authority) = _sealed_plan(tmp_path, monkeypatch, ecu)
    planning_draw = planning["campaign_draw_authority"]
    trigger = _trigger_scan(cycle, calls, monkeypatch, planning_draw["record_id"])
    trigger_draw = trigger["campaign_draw_authority"]
    # Same generation; a strictly LATER current measurement than planning.
    assert trigger_draw["record_id"] == planning_draw["record_id"]
    assert _draw_identity(trigger_draw) == authority.payload()["draw"]
    assert _instant(trigger_draw["settled_cutoff"]) > _instant(
        planning_draw["settled_cutoff"])
    assert trigger_draw["settled_cutoff"] == trigger["snapshot"]["timestamp"]

    brain_calls = len(calls)
    loop, budget_calls, decisions, venue = _trigger_loop(
        monkeypatch, producer=producer, plan_candidate=plan_candidate,
        authority=authority, auth=auth, now=now)
    outcome = _fire(loop, trigger, plan_candidate)
    assert len(calls) == brain_calls
    # The candidate was produced and reached the budget step, which stops it.
    assert outcome["reason"] == "TEST_STOP_BEFORE_MISSION", outcome
    assert loop.mission.candidate_count == 1
    assert budget_calls == [True]
    assert ("CANDIDATE", None, "conditional_plan_triggered") in decisions
    trace = producer.last_decision_trace
    assert trace["campaign_lifecycle_authority_basis"] == "PREAUTHORIZED_PLAN_JUDGMENT"
    assert trace["conditional_plan_authority"]["state"] == "VERIFIED"
    assert trigger["snapshot"]["campaign_lifecycle"]["reason"] == \
        "current_brain_authority_unavailable"
    assert loop.mission.trade_missions == []
    assert venue.calls == []


@TA.ECU_MODES
@pytest.mark.parametrize("substitution,expected", [
    ("birth_measurement", f"{PLAN_NOT_CURRENT}:{UNMEASURED}"),
    ("planning_measurement", f"{PLAN_NOT_CURRENT}:{NOT_CURRENT}"),
    ("different_record", PLAN_CHANGED),
])
def test_real_trigger_refuses_stale_measurement_or_different_generation(
        tmp_path, monkeypatch, ecu, substitution, expected):
    (now, cycle, calls, producer, birth, planning, plan_candidate, auth,
     authority) = _sealed_plan(tmp_path, monkeypatch, ecu)
    planning_draw = copy.deepcopy(planning["campaign_draw_authority"])
    trigger = _trigger_scan(cycle, calls, monkeypatch, planning_draw["record_id"])
    if substitution == "birth_measurement":
        forged = copy.deepcopy(birth["campaign_draw_truth"])
        # The label-only plan identity cannot tell birth from current.
        assert forged["record_id"] == planning_draw["record_id"]
        assert {k: v for k, v in _draw_identity(forged).items() if k != "record_id"} \
            == {k: v for k, v in authority.payload()["draw"].items() if k != "record_id"}
    elif substitution == "planning_measurement":
        forged = planning_draw
        assert forged["settled_cutoff"] != trigger["snapshot"]["timestamp"]
    else:
        forged = copy.deepcopy(trigger["campaign_draw_authority"])
        forged["record_id"] = "f" * 24
    for key in LABELS:
        assert forged[key] == planning_draw[key]
    trigger["campaign_draw_authority"] = forged

    brain_calls = len(calls)
    loop, budget_calls, decisions, venue = _trigger_loop(
        monkeypatch, producer=producer, plan_candidate=plan_candidate,
        authority=authority, auth=auth, now=now)
    outcome = _fire(loop, trigger, plan_candidate)
    assert len(calls) == brain_calls
    assert outcome["reason"] == "campaign_lifecycle_refused", outcome
    assert outcome["detail"] == f"campaign_lifecycle_refused: {expected}"
    assert decisions[-1][:2] == ("REJECTED", "campaign_lifecycle_refused")
    assert loop.active_conditional_plan is None  # one shot, refusal included
    assert loop.mission.candidate_count == 0
    assert budget_calls == []
    assert loop.mission.trade_missions == []
    assert venue.calls == []
