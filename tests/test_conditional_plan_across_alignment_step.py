"""N1: a sealed conditional plan across a coherent window's alignment step.

The plan is authored on one 15m-aligned rolling window and triggered, without
the Brain, on the next minute's window, which CONT.coherent_window has shortened
by one partial bucket (125 -> 111 bars). Everything is the real
ProductionScanCycle, CandidateProducer, plan capture and final-quote validation
on the temporal-authority reversal tape; only the model transport is mocked
(the existing `_watching` reply). Expiry, campaign/Draw, zone and risk gates
are the production ones.

At f822371 the trigger window's shrink made derived state stale, so the
authentic plan could not be revalidated. With N1 it composes through the final
quote, and history revision and expiry still refuse.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_draw_temporal_authority as T
import test_reversal_foundation_proof_closure as RF
from broker.conditional_plan_authority import validate_final_quote
from broker.luna_candidate_producer import (CandidateProducer, NoCandidate,
                                            authorized_tool_catalog)
from data_feed import candle_continuity as CONT

# The provider horizon (tail = tip - HORIZON .. tip) starting on 01:00 at the planning tip
# (03:04): one minute later the tail starts at 01:01 and alignment moves the
# window start to 01:15.
HORIZON = 124


def _coherent(rows):
    window = CONT.coherent_window(rows, horizon_minutes=HORIZON, minimum_bars=60)
    assert window["sufficient"], window["reason"]
    return window["window"]


def _scan(cycle, rows, *, brain=True):
    window = _coherent(rows)
    return cycle.scan(window, now=RF._now_for(window), invoke_brain=brain), window


def _plan(tmp_path, monkeypatch, ecu):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle = RF._cycle(tmp_path, monkeypatch)
    for end in range(65, len(RF.TAPE_1M) - 4):
        cycle.scan(_coherent(RF.TAPE_1M[:end]), now=RF._now_for(RF.TAPE_1M[:end]),
                   invoke_brain=False)
    calls = []
    RF._mock_current_brain(monkeypatch, calls, output_mutator=T._watching(now))
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    producer = CandidateProducer(account_fingerprint="acct:n1-plan", contract=RF.MNQ)
    newborn, _ = _scan(cycle, RF.TAPE_1M)
    assert newborn["campaign_draw_truth"]["authority_status"] == "PROVEN_NOT_DELIVERED"
    planning, planning_window = _scan(cycle, T.LATER)
    assert planning["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    candidate = T._plan_candidate(producer, planning, now)
    assert candidate.extras["conditional_plan"] is True
    auth = T._authorization(candidate, now)
    authority = producer.capture_conditional_plan_authority(
        candidate=candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    return dict(cycle=cycle, calls=calls, producer=producer, now=now,
                planning=planning, planning_window=planning_window,
                candidate=candidate, auth=auth, authority=authority)


def _final_quote(p, fresh, *, now=None):
    zone = p["authority"].payload()["activation_zone"]
    fresh.extras["conditional_plan_id"] = p["candidate"].candidate_id
    return validate_final_quote(
        authority=p["authority"], scope=p["producer"]._conditional_plan_scope,
        candidate=fresh, contract_id=RF.CONTRACT,
        executable_price=(zone["low"] + zone["high"]) / 2, now=now or p["now"])


@T.ECU_MODES
def test_sealed_plan_triggers_through_the_final_quote_across_the_step(
        tmp_path, monkeypatch, ecu):
    p = _plan(tmp_path, monkeypatch, ecu)
    brain_calls = len(p["calls"])
    custody = p["cycle"].reversal_formation_custody
    formations = copy.deepcopy(custody._records)
    assert formations, "no formation in custody at plan capture"
    trigger, window = _scan(p["cycle"], T.NEXT_MINUTE, brain=False)
    # The trigger window is the alignment step itself.
    assert (p["planning_window"][0]["timestamp"][11:16], len(p["planning_window"])) == ("01:00", 125)
    assert (window[0]["timestamp"][11:16], len(window)) == ("01:15", 111)
    state = trigger["snapshot"]["derived_state"]
    assert state["current"] is True and state["coverage"]["catch_up_bars"] == 0
    assert len(p["calls"]) == brain_calls          # no Brain on the trigger
    # The same formation custody and the same bound participation authority
    # survive the step; nothing was re-accepted on the trigger minute.
    assert custody._records == formations
    bound = p["authority"].payload()
    assert trigger["campaign_draw_acceptance"] is None
    assert T._draw_identity(trigger["campaign_draw_authority"]) == bound["draw"]
    # The sealed execution object is still the current producer-bound,
    # execution-eligible occurrence on the shortened window.
    selected_id = p["candidate"].extras["conditional_plan_brain_output"][
        "recommended_tool_occurrence_id"]
    assert selected_id == bound["occurrence_id"]
    current = [row for row in authorized_tool_catalog(trigger["snapshot"])
               if row.get("occurrence_id") == selected_id]
    assert len(current) == 1 and current[0]["execution_eligible"] is True
    fresh = T._trigger(p["producer"], trigger, plan_candidate=p["candidate"],
                       authority=p["authority"], auth=p["auth"], now=p["now"])
    assert fresh.extras["selected_tool_occurrence_id"] == bound["occurrence_id"]
    evidence = fresh.extras["conditional_plan_authority"]
    assert evidence["state"] == "VERIFIED"
    assert evidence["authoring_snapshot_id"] == p["planning"]["snapshot_id"]
    assert evidence["campaign_episode_id"] == bound["draw"]["campaign_episode_id"]
    assert evidence["history_revision"] == bound["history_revision"] == 0
    assert _final_quote(p, fresh) == (True, None)
    assert len(p["calls"]) == brain_calls


@T.ECU_MODES
def test_rewritten_history_refuses_the_sealed_plan(tmp_path, monkeypatch, ecu):
    p = _plan(tmp_path, monkeypatch, ecu)
    # A bar inside the shared span is rewritten on the trigger minute; the
    # rows cover the whole session, so the existing rebuild lawfully succeeds
    # under revision 1 -- and the plan sealed under revision 0 must refuse.
    rows = copy.deepcopy(T.NEXT_MINUTE)
    bar = rows[len(rows) - 40]
    bar["close"] = round(bar["close"] + 0.25, 2)
    bar["high"] = max(bar["high"], bar["close"])
    trigger = p["cycle"].scan(rows, now=RF._now_for(rows), invoke_brain=False)
    state = trigger["snapshot"]["derived_state"]
    assert state["history_revision"] == 1
    assert p["cycle"].rebuilds[-1]["revision"] == 1
    with pytest.raises(NoCandidate) as refused:
        T._trigger(p["producer"], trigger, plan_candidate=p["candidate"],
                   authority=p["authority"], auth=p["auth"], now=p["now"])
    assert "history" in refused.value.reason or "history" in str(refused.value), refused.value


@T.ECU_MODES
def test_expired_plan_is_not_resurrected_by_the_step(tmp_path, monkeypatch, ecu):
    p = _plan(tmp_path, monkeypatch, ecu)
    trigger, window = _scan(p["cycle"], T.NEXT_MINUTE, brain=False)
    assert len(window) == 111 and trigger["snapshot"]["derived_state"]["current"] is True
    late = p["now"] + timedelta(minutes=31)          # plan_expires_at is now + 30m
    with pytest.raises(NoCandidate) as refused:
        T._trigger(p["producer"], trigger, plan_candidate=p["candidate"],
                   authority=p["authority"], auth=p["auth"], now=late)
    assert "expir" in refused.value.reason or "expir" in str(refused.value), refused.value
