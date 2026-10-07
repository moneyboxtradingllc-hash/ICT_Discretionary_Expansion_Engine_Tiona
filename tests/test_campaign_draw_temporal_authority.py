"""STAGE 2 -- CAMPAIGN DRAW TEMPORAL-AUTHORITY CLOSURE.

Two causal laws close the participation boundary that 8c64ab77 left open:

  RETIRED      A positive Draw used by scan N must still be the tracker's live
               record AFTER scan N's own current acceptance. When the current
               sovereign judgment supersedes/replaces/revises the incumbent,
               scan N is refusal-only. The newborn is persisted, not discarded.
  UNMEASURED   A Draw may give positive authority only once settled market
               evidence exists beyond its birth anchor (settled_cutoff >
               anchor_bar_time). A second cognition on the same settled cutoff
               cannot be authorized by its predecessor's output.

Every scan below is the real ProductionScanCycle on the synthetic reversal tape
with mocked model transport only; candidates come from the real
CandidateProducer and plans from the real capture/validate boundary. No order,
venue, runner, or token is involved.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import test_reversal_foundation_proof_closure as RF
from broker.conditional_plan_authority import _draw_identity
from broker.luna_candidate_producer import CandidateProducer, NoCandidate
from market_data.campaign_draw_truth import (
    PARTICIPATION_AUTHORITY_MISSING, PARTICIPATION_WITHHELD_RETIRED,
    PARTICIPATION_WITHHELD_UNMEASURED, scan_participation_authority)
from market_data.campaign_lifecycle import (AUTHORITY_UNKNOWN,
                                            evaluate_campaign_lifecycle)

# One later healthy 5m interval (high 29490 stays below the 29500 objective),
# then quiet healthy intervals: the objective stays undelivered and the plan's
# selected execution object stays physically present for its trigger.
LATER = RF.TAPE_1M + RF._expand_5m(("03:00", 29459.0, 29490.0, 29450.0, 29460.0))
LATER2 = LATER + RF._expand_5m(("03:05", 29460.0, 29461.0, 29459.0, 29460.0))
LATER3 = LATER2 + RF._expand_5m(("03:10", 29460.0, 29461.0, 29459.0, 29460.0))
# The very next settled minute after LATER (a strict prefix of LATER2, so no
# scan ever sees a revised bar): a brainless trigger tape on which the plan's
# selected execution object is still physically present.
NEXT_MINUTE = LATER2[:len(LATER) + 1]
NEXT_MINUTE_AFTER_LATER2 = LATER3[:len(LATER2) + 1]

ECU_MODES = pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non-ecu"])


def _cycle_with_brain(tmp_path, monkeypatch, *, ecu, mutator=None):
    cycle = RF._cycle(tmp_path, monkeypatch)
    RF._scan_prefix(cycle, len(RF.TAPE_1M) - 5)
    calls = []
    RF._mock_current_brain(monkeypatch, calls, output_mutator=mutator)
    # `_mock_current_brain` enables ECU; the non-ECU lane runs its own single
    # `run_narrative_brain` call after the build with the same transport.
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    return cycle, calls


def _scan(cycle, rows, *, brain=True):
    return cycle.scan(rows, now=RF._now_for(rows), invoke_brain=brain)


def _audit(cycle, record_id):
    rows = [row for row in cycle.campaign_draw_truth.audit_records
            if row.get("record_id") == record_id]
    assert len(rows) == 1, record_id
    return rows[0]


def _assert_withheld(scan, reason, withheld_record_id):
    authority = scan["campaign_draw_authority"]
    assert authority["authority_status"] == "UNKNOWN"
    assert authority["participation_withheld_reason"] == reason
    assert authority["withheld_record_id"] == withheld_record_id
    assert scan["snapshot"]["campaign_draw_authority"] == authority
    lifecycle = scan["campaign_lifecycle"]
    assert lifecycle["state"] == AUTHORITY_UNKNOWN
    assert lifecycle["reason"] == f"campaign_draw_participation_withheld:{reason}"
    assert lifecycle["participation_permitted"] is False
    assert _draw_identity(authority) is None
    with pytest.raises(NoCandidate) as refused:
        RF._produce_candidate(scan)
    assert refused.value.reason == "campaign_lifecycle_refused"


# ── A1: the current acceptance retires the pre-cognition incumbent ──────────
@ECU_MODES
def test_acceptance_that_replaces_incumbent_identity_refuses_same_scan(
        tmp_path, monkeypatch, ecu):
    def protected_swing_from_second_call(output, ordinal, _payload):
        return ({**output, "active_draw": "protected swing"}
                if ordinal >= 2 else output)

    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu,
                                     mutator=protected_swing_from_second_call)
    first = _scan(cycle, RF.TAPE_1M)
    incumbent = first["campaign_draw_truth"]
    assert incumbent["authority_status"] == "PROVEN_NOT_DELIVERED"

    current = _scan(cycle, LATER)
    assert len(calls) == 2
    # The pre-cognition authority really was positive before this judgment.
    context = calls[1]["campaign_draw_context"]
    assert context["record_id"] == incumbent["record_id"]
    assert context["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert current["campaign_draw_acceptance"] == {"accepted": True, "reason": None}
    newborn = current["campaign_draw_truth"]
    assert newborn["record_id"] != incumbent["record_id"]
    assert newborn["objective_identity"] != incumbent["objective_identity"]
    retired = _audit(cycle, incumbent["record_id"])
    assert retired["superseded"] is True
    assert retired["superseded_reason"] == "campaign_or_draw_identity_changed"

    _assert_withheld(current, PARTICIPATION_WITHHELD_RETIRED,
                     incumbent["record_id"])
    # Not discarded: the lawful newborn is the tracker's live record.
    live = _audit(cycle, newborn["record_id"])
    assert live["superseded"] is False
    assert live["authority_status"] == "PROVEN_NOT_DELIVERED"


@ECU_MODES
def test_acceptance_that_revises_incumbent_price_refuses_same_scan(
        tmp_path, monkeypatch, ecu):
    """Same objective identity, revised price -> `objective_price_revised`.

    The current catalog seldom emits one identity at two prices (most
    identities embed their price), so this test shapes ONLY the catalog row
    the post-cognition acceptance resolves: same identity, price + 2.0. Every
    other step is the real production path, and the branch exercised is the
    tracker's own `objective_price_revised` supersession.
    """
    import broker.luna_candidate_producer as LCP

    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu)
    first = _scan(cycle, RF.TAPE_1M)
    incumbent = first["campaign_draw_truth"]
    assert incumbent["authority_status"] == "PROVEN_NOT_DELIVERED"

    real_enumerate = LCP.enumerate_objectives

    def revised_catalog(snapshot, brain_input):
        rows = copy.deepcopy(real_enumerate(snapshot, brain_input))
        for row in rows:
            if row.get("identity") == incumbent["objective_identity"]:
                row["price"] = float(incumbent["objective_price"]) + 2.0
        return rows

    monkeypatch.setattr(LCP, "enumerate_objectives", revised_catalog)
    current = _scan(cycle, LATER)
    monkeypatch.setattr(LCP, "enumerate_objectives", real_enumerate)

    assert len(calls) == 2
    assert calls[1]["campaign_draw_context"]["record_id"] == incumbent["record_id"]
    assert current["campaign_draw_acceptance"]["accepted"] is True
    revised = current["campaign_draw_truth"]
    assert revised["record_id"] != incumbent["record_id"]
    assert revised["objective_identity"] == incumbent["objective_identity"]
    assert revised["objective_price"] == float(incumbent["objective_price"]) + 2.0
    retired = _audit(cycle, incumbent["record_id"])
    assert retired["superseded"] is True
    assert retired["superseded_reason"] == "objective_price_revised"
    _assert_withheld(current, PARTICIPATION_WITHHELD_RETIRED,
                     incumbent["record_id"])


@ECU_MODES
def test_reaccepting_the_same_incumbent_keeps_positive_authority(
        tmp_path, monkeypatch, ecu):
    """Control: a same-identity, same-price acceptance retires nothing."""
    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu)
    first = _scan(cycle, RF.TAPE_1M)
    current = _scan(cycle, LATER)
    authority = current["campaign_draw_authority"]
    assert authority["record_id"] == first["campaign_draw_truth"]["record_id"]
    assert "participation_withheld_reason" not in authority
    assert current["campaign_draw_truth"]["record_id"] == authority["record_id"]
    assert current["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    RF._assert_retained_reversal_candidate(RF._produce_candidate(current))


# ── A2: no positive authority before market evidence beyond birth ───────────
@ECU_MODES
def test_same_cutoff_recognition_cannot_promote_newborn_until_newer_settled_bar(
        tmp_path, monkeypatch, ecu):
    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu)
    scan_n = _scan(cycle, RF.TAPE_1M)
    newborn = scan_n["campaign_draw_truth"]
    assert newborn["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert scan_n["campaign_lifecycle"]["state"] == AUTHORITY_UNKNOWN

    # A second sovereign cognition on the IDENTICAL settled tape.
    same = _scan(cycle, RF.TAPE_1M)
    assert len(calls) == 2
    context = calls[1]["campaign_draw_context"]
    assert context["record_id"] == newborn["record_id"]       # seen as context
    assert context["settled_cutoff"] == context["anchor_bar_time"]
    _assert_withheld(same, PARTICIPATION_WITHHELD_UNMEASURED, newborn["record_id"])
    kept = _audit(cycle, newborn["record_id"])                  # still available
    assert kept["superseded"] is False

    # Once a newer settled interval exists, the same surviving Draw may lead.
    later = _scan(cycle, LATER)
    assert len(calls) == 3
    authority = later["campaign_draw_authority"]
    assert authority["record_id"] == newborn["record_id"]
    assert authority["anchor_bar_time"] == newborn["anchor_bar_time"]
    assert authority["settled_cutoff"] > authority["anchor_bar_time"]
    assert later["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    RF._assert_retained_reversal_candidate(RF._produce_candidate(later))


# ── Boundary hardening ───────────────────────────────────────────────────────
def test_missing_participation_authority_fails_closed_and_truth_is_no_substitute(
        tmp_path, monkeypatch):
    cycle, _ = _cycle_with_brain(tmp_path, monkeypatch, ecu=True)
    _scan(cycle, RF.TAPE_1M)
    scan = _scan(cycle, LATER)
    assert scan["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    stripped = dict(scan)
    stripped.pop("campaign_draw_authority")
    authority = scan_participation_authority(stripped)
    assert authority["authority_status"] == "UNKNOWN"
    assert authority["participation_withheld_reason"] == PARTICIPATION_AUTHORITY_MISSING
    assert authority is not stripped["campaign_draw_truth"]
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=scan["snapshot"],
        brain_output=scan["brain_result"]["parsed"],
        narrative_continuity=scan["brain_result"]["narrative_continuity"],
        campaign_draw=authority, session_id=RF.SESSION_ID,
        contract_id=RF.CONTRACT, brain_authority_available=True)
    assert lifecycle["participation_permitted"] is False
    assert lifecycle["reason"] == (
        f"campaign_draw_participation_withheld:{PARTICIPATION_AUTHORITY_MISSING}")


@ECU_MODES
def test_no_brain_scan_publishes_no_acceptance_and_stays_brainless(
        tmp_path, monkeypatch, ecu):
    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu)
    first = _scan(cycle, RF.TAPE_1M)
    records = len(cycle.campaign_draw_truth.audit_records)
    quiet = _scan(cycle, LATER, brain=False)
    assert len(calls) == 1
    assert quiet["campaign_draw_acceptance"] is None
    assert "campaign_draw_acceptance" not in quiet["snapshot"]
    assert len(cycle.campaign_draw_truth.audit_records) == records
    assert quiet["campaign_draw_truth"]["record_id"] == \
        first["campaign_draw_truth"]["record_id"]
    assert quiet["campaign_draw_authority"]["record_id"] == \
        first["campaign_draw_truth"]["record_id"]
    lifecycle = quiet["campaign_lifecycle"]
    assert lifecycle["state"] == AUTHORITY_UNKNOWN
    # The truthful refusal: no current Brain authority -- not a fabricated
    # "acceptance refused" for an acceptance that never ran.
    assert lifecycle["reason"] == "current_brain_authority_unavailable"


# ── Conditional plan / LATENCY-1 temporal lineage ───────────────────────────
def _watching(now):
    """A watching plan on an execution object with an exact occurrence identity.

    Plan publication requires a top-level `occurrence_id` on the selected tool.
    The retained po3 reversal row carries its identity only inside
    `formation_authority`, so it cannot be published as a watching plan today
    (a pre-existing Stage 4 participation-object limit, not changed here). The
    plan lineage is therefore proven on the same real tape with the bullish
    execution-eligible FVG the producer itself published, selected by its id.
    """
    def mutate(output, _ordinal, payload):
        if output.get("current_action") != "propose_entry":
            return output
        fvg = next((row for row in payload.get("authorized_tool_catalog") or []
                    if row.get("tool_family") == "fvg"
                    and row.get("direction") == output.get("narrative_direction")
                    and row.get("execution_eligible") is True
                    and row.get("occurrence_id")), None)
        if fvg is None:
            return output
        return {**output, "current_action": "watching",
                "recommended_tool_family": ["fvg"],
                "recommended_tool_occurrence_id": fvg["occurrence_id"],
                "plan_expires_at": (now + timedelta(minutes=30)).isoformat()}
    return mutate


def _authorization(candidate, now):
    from ai_brain import production_model as PM
    from ai_retrieval.retrieval import retrieval_enabled
    from broker import topstepx_session_authorization as SA

    session_date = now.astimezone(ZoneInfo(SA.PRODUCTION_WINDOW_TZ)).strftime("%Y%m%d")
    auth = SA.SessionAuthorization(
        session_id=RF.SESSION_ID, account_fingerprint=candidate.account_fingerprint,
        contract_id=candidate.contract_id, session_date=session_date,
        decision_window=SA.window_text(session_date),
        brain_model=PM.PRODUCTION_MODEL,
        brain_reasoning_effort=PM.reasoning_effort() or "",
        json_mode_required=True,
        brain_contract_fingerprint=PM.brain_contract_fingerprint(),
        retrieval_enabled=retrieval_enabled(),
        daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD,
        issued_at=now.isoformat())
    auth.authorization_fingerprint = auth.fingerprint()
    return auth


def _plan_candidate(producer, scan, now):
    return producer.produce(
        brain_result=scan["brain_result"], brain_input=scan["brain_input"],
        snapshot=scan["snapshot"], qualification=scan["qualification"],
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id=scan["snapshot_id"],
        market_data_timestamp=scan["snapshot"]["timestamp"],
        latest_closed_bar_timestamp=scan["snapshot"]["timestamp"],
        now=now, conditional_plan=True, require_campaign_lifecycle=True,
        campaign_draw=scan_participation_authority(scan),
        campaign_session_id=RF.SESSION_ID)


def _trigger(producer, trigger_scan, *, plan_candidate, authority, auth, now):
    """Mirror ProductionLoop's brainless LATENCY-1 trigger lane exactly."""
    import test_luna_candidate_producer as fixtures

    plan_brain_result = authority.payload()["brain_result"]
    snapshot = trigger_scan["snapshot"]
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=plan_brain_result.get("narrative_continuity") or {},
        campaign_draw=scan_participation_authority(trigger_scan),
        session_id=RF.SESSION_ID, contract_id=RF.CONTRACT,
        brain_authority_available=False)
    snapshot["campaign_lifecycle"] = lifecycle
    zone = plan_candidate.extras["activation_zone"]
    inside = (float(zone["low"]) + float(zone["high"])) / 2
    brain_input = copy.deepcopy(trigger_scan["brain_input"])
    brain_input.setdefault("market", {})["execution_price"] = \
        fixtures.execution_block(inside, inside)
    return producer.produce(
        brain_result=plan_brain_result, brain_input=brain_input,
        snapshot=snapshot, qualification=trigger_scan["qualification"],
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id=trigger_scan["snapshot_id"],
        market_data_timestamp=snapshot["timestamp"],
        latest_closed_bar_timestamp=snapshot["timestamp"],
        now=now, conditional_trigger=True, require_campaign_lifecycle=True,
        campaign_draw=scan_participation_authority(trigger_scan),
        campaign_session_id=RF.SESSION_ID,
        conditional_plan_authority=authority,
        conditional_plan_candidate=plan_candidate,
        conditional_session_authorization=auth,
        process_session_id=RF.SESSION_ID,
        conditional_plan_trigger_event={
            "plan_id": plan_candidate.candidate_id,
            "occurrence_id": plan_candidate.extras["selected_tool_occurrence_id"],
            "reason": "conditional_plan_zone_reached"})


@ECU_MODES
def test_conditional_plan_temporal_lineage_end_to_end(tmp_path, monkeypatch, ecu):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu,
                                     mutator=_watching(now))
    producer = CandidateProducer(account_fingerprint="acct:temporal-authority",
                                 contract=RF.MNQ)

    # 1. Newborn scan N: persisted, but no positive plan authority on N.
    scan_n = _scan(cycle, RF.TAPE_1M)
    newborn = scan_n["campaign_draw_truth"]
    assert newborn["authority_status"] == "PROVEN_NOT_DELIVERED"
    with pytest.raises(NoCandidate) as on_n:
        _plan_candidate(producer, scan_n, now)
    assert on_n.value.reason == "campaign_lifecycle_refused"
    # ...nor on a same-cutoff re-cognition.
    same = _scan(cycle, RF.TAPE_1M)
    assert same["campaign_draw_authority"]["participation_withheld_reason"] == \
        PARTICIPATION_WITHHELD_UNMEASURED
    with pytest.raises(NoCandidate):
        _plan_candidate(producer, same, now)

    # 2-3. After newer settled evidence the surviving Draw is prior-generation
    # authority, and a lawful watching plan binds its exact identity.
    planning = _scan(cycle, LATER)
    authority_draw = planning["campaign_draw_authority"]
    assert authority_draw["record_id"] == newborn["record_id"]
    assert planning["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    plan_candidate = _plan_candidate(producer, planning, now)
    assert plan_candidate.extras["conditional_plan"] is True
    assert plan_candidate.extras["tool_family"] == ["fvg"]
    assert plan_candidate.extras["activation_zone"]["occurrence_id"]
    auth = _authorization(plan_candidate, now)
    plan = producer.capture_conditional_plan_authority(
        candidate=plan_candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    bound = plan.payload()
    assert bound["draw"] == _draw_identity(authority_draw)
    assert bound["draw"]["objective_identity"] == newborn["objective_identity"]
    assert bound["draw"]["anchor_bar_time"] == newborn["anchor_bar_time"]
    assert bound["history_revision"] == authority_draw["history_revision"]

    # 4. A brainless trigger revalidates the exact bound Draw, revision and
    # ActivePath and is permitted only by the sealed plan judgment.
    brain_calls = len(calls)
    trigger_scan = _scan(cycle, NEXT_MINUTE, brain=False)
    assert len(calls) == brain_calls
    assert trigger_scan["campaign_draw_acceptance"] is None
    assert _draw_identity(trigger_scan["campaign_draw_authority"]) == bound["draw"]
    fresh = _trigger(producer, trigger_scan, plan_candidate=plan_candidate,
                     authority=plan, auth=auth, now=now)
    assert fresh.direction == "bullish"
    evidence = fresh.extras["conditional_plan_authority"]
    assert evidence["state"] == "VERIFIED"
    assert evidence["authoring_snapshot_id"] == planning["snapshot_id"]
    assert evidence["campaign_episode_id"] == bound["draw"]["campaign_episode_id"]
    assert evidence["history_revision"] == bound["history_revision"]
    assert len(calls) == brain_calls

    # 6. When the bound Draw identity changes before trigger, the trigger
    # refuses under the existing mismatch rule.
    def retarget(output, ordinal, payload):
        return {**_watching(now)(output, ordinal, payload),
                "active_draw": "protected swing"}
    calls_before = len(calls)
    RF._mock_current_brain(monkeypatch, calls, output_mutator=retarget)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    retargeted = _scan(cycle, LATER2)
    assert len(calls) == calls_before + 1
    assert retargeted["campaign_draw_acceptance"]["accepted"] is True
    assert retargeted["campaign_draw_authority"]["participation_withheld_reason"] \
        == PARTICIPATION_WITHHELD_RETIRED
    late_trigger = _scan(cycle, NEXT_MINUTE_AFTER_LATER2, brain=False)
    assert _draw_identity(late_trigger["campaign_draw_authority"]) != bound["draw"]
    with pytest.raises(NoCandidate) as mismatch:
        _trigger(producer, late_trigger, plan_candidate=plan_candidate,
                 authority=plan, auth=auth, now=now)
    assert mismatch.value.reason == "campaign_lifecycle_refused"
    assert "conditional_plan_campaign_draw_changed_or_unavailable" in str(
        mismatch.value)


@ECU_MODES
def test_planning_scan_that_retires_incumbent_captures_no_stale_plan(
        tmp_path, monkeypatch, ecu):
    """5. The immediate path refuses and no stale-I plan authority is minted."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls = _cycle_with_brain(tmp_path, monkeypatch, ecu=ecu,
                                     mutator=_watching(now))
    producer = CandidateProducer(account_fingerprint="acct:temporal-authority",
                                 contract=RF.MNQ)
    _scan(cycle, RF.TAPE_1M)
    lawful = _scan(cycle, LATER)
    lawful_candidate = _plan_candidate(producer, lawful, now)
    incumbent_id = lawful["campaign_draw_authority"]["record_id"]

    def retarget(output, ordinal, payload):
        return {**_watching(now)(output, ordinal, payload),
                "active_draw": "protected swing"}
    RF._mock_current_brain(monkeypatch, calls, output_mutator=retarget)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    planning = _scan(cycle, LATER2)
    assert calls[-1]["campaign_draw_context"]["record_id"] == incumbent_id
    assert calls[-1]["campaign_draw_context"]["authority_status"] == \
        "PROVEN_NOT_DELIVERED"
    _assert_withheld(planning, PARTICIPATION_WITHHELD_RETIRED, incumbent_id)
    with pytest.raises(NoCandidate) as immediate:
        _plan_candidate(producer, planning, now)
    assert immediate.value.reason == "campaign_lifecycle_refused"
    # Even handed a lawful candidate, the capture boundary will not mint a plan
    # from a scan whose participation authority was retired.
    with pytest.raises(ValueError):
        producer.capture_conditional_plan_authority(
            candidate=lawful_candidate, scan=planning,
            authorization=_authorization(lawful_candidate, now),
            process_session_id=RF.SESSION_ID, now=now)
