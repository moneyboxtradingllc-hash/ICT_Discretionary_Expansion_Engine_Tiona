"""Session PO3 may testify but cannot authorize or veto a sovereign proposal."""
from __future__ import annotations

from copy import deepcopy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
import test_luna_candidate_producer as LCP
from _step7_fixture import detected
from ai_brain.brain_input import _session_po3_block
from broker.luna_candidate_producer import CandidateProducer, NoCandidate
from broker.topstepx_candidate_freshness import CandidateStale, assess
from execution_gate.execution_gate import evaluate_gate
from structure.session_po3 import entry_context
from test_phase_5f_authority_enforcement import _gate_snapshot

UNRESOLVED = ("ACCUMULATION_FORMING", "ACCUMULATION_ESTABLISHED",
              "EXCURSION_UNRESOLVED", "REACCUMULATION")


def snapshot(phase="REACCUMULATION"):
    out = deepcopy(detected("fvg"))
    out["session_po3"] = {"phase": phase, "authority_class": "CONTEXT_ONLY",
                          "mechanical_entry_posture": (
                              "permissive" if phase == "DISTRIBUTION_ACTIVE" else "caution"),
                          "mechanical_reason": "phase context only",
                          # Old archives retain these fields; neither is law.
                          "new_entry_allowed": phase == "DISTRIBUTION_ACTIVE",
                          "block_reason": "legacy mechanical opinion"}
    return out


def canonical_producer():
    return CandidateProducer(account_fingerprint=LCP.FP, contract=LCP.MNQ)


def produce_exact(snap, *, producer=None, parsed_over=None, bi=None, **kwargs):
    # Canonical identities, with both archive-only producer fallbacks disabled.
    instance = snap["toolbox"]["tool_instances"][0] if snap["toolbox"]["tool_instances"] else None
    parsed = LCP.parsed(current_action="propose_entry",
                        objective_id="OBJ_LIQ_BSL_1", invalidation_id="INV_PL_1",
                        recommended_tool_occurrence_id=(instance or {}).get("occurrence_id"))
    parsed.update(parsed_over or {})
    return LCP.produce(producer or canonical_producer(), snapshot=snap,
                       res=LCP.result(parsed=parsed), bi=bi or LCP.brain_input(), **kwargs)


@pytest.mark.parametrize("phase", UNRESOLVED)
def test_unresolved_phase_cannot_veto_lawful_brain_proposal(phase):
    p = canonical_producer()
    candidate = produce_exact(snapshot(phase), producer=p)
    assert candidate.direction == "bullish"
    assert candidate.objective.price == 29910.25
    assert candidate.invalidation_price == 29875.0
    assert p.last_decision_trace["session_phase"] == phase
    assert p.last_decision_trace["session_phase_brain_disagreed"] is True
    assert p.last_decision_trace["session_phase_authority_class"] == "CONTEXT_ONLY"


@pytest.mark.parametrize("phase", UNRESOLVED)
def test_brain_stand_down_still_refuses(phase):
    p = canonical_producer()
    with pytest.raises(NoCandidate) as exc:
        produce_exact(snapshot(phase), producer=p,
                      parsed_over={"current_action": "stand_down"})
    assert exc.value.reason == "action_declines_entry"
    assert p.last_decision_trace["session_phase"] == phase


def test_only_session_phase_changes_candidate_geometry_and_outcome_are_identical():
    permissive = snapshot("DISTRIBUTION_ACTIVE")
    cautious = deepcopy(permissive)
    cautious["session_po3"] = snapshot("REACCUMULATION")["session_po3"]
    one, two = canonical_producer(), canonical_producer()
    a = produce_exact(permissive, producer=one)
    b = produce_exact(cautious, producer=two)
    assert a.fingerprint() == b.fingerprint()
    assert (a.direction, a.entry_price, a.invalidation_price,
            a.objective.identity, a.objective.price) == (
            b.direction, b.entry_price, b.invalidation_price,
            b.objective.identity, b.objective.price)
    context_keys = {"session_phase", "session_phase_authority_class",
                    "session_phase_mechanical_posture", "session_phase_mechanical_reason",
                    "session_phase_brain_disagreed"}
    assert {k: v for k, v in one.last_decision_trace.items() if k not in context_keys} == {
        k: v for k, v in two.last_decision_trace.items() if k not in context_keys}
    assert one.last_decision_trace["session_phase_brain_disagreed"] is False
    assert two.last_decision_trace["session_phase_brain_disagreed"] is True


@pytest.mark.parametrize("mutation,kwargs,expected", [
    ("missing_tool", {}, "tool"),
    ("ineligible_tool", {}, "tool"),
    ("unknown_objective", {"objective_id": "UNKNOWN"}, "objective_id_unknown"),
    ("missing_invalidation", {"invalidation_level": None}, "invalidation_missing"),
    ("wrong_side_invalidation", {"bi": LCP.brain_input(prot_low=29890.0),
                                 "invalidation_level": 29890.0}, "invalidation_wrong_side"),
    ("closed_window", {"in_window": False}, "window_closed"),
    ("contract_mismatch", {}, "contract_mismatch"),
    ("stale_derived_state", {}, "derived_state_stale"),
    ("broken_continuity", {}, "candle_gap_unrecovered"),
])
def test_caution_cannot_override_hard_truth(mutation, kwargs, expected):
    snap = snapshot()
    if mutation == "missing_tool":
        snap["toolbox"]["tool_instances"] = []
        snap["toolbox"]["tool_candidates"] = []
    elif mutation == "ineligible_tool":
        for instance in snap["toolbox"]["tool_instances"]:
            instance["execution_eligible"] = False
    elif mutation == "contract_mismatch":
        snap["contract_id"] = "CON.F.US.MNQ.Z26"
    elif mutation == "stale_derived_state":
        snap["derived_state"] = {"history_revision": 2,
                                 "derived_revision": 1, "current": False}
    elif mutation == "broken_continuity":
        snap["candle_continuity"] = {"continuous": False, "gaps": None,
                                      "last": None}
    parsed_over = {k: v for k, v in kwargs.items()
                   if k in {"objective_id", "invalidation_level"}}
    other = {k: v for k, v in kwargs.items() if k not in parsed_over}
    with pytest.raises(NoCandidate) as exc:
        produce_exact(snap, parsed_over=parsed_over, **other)
    assert expected in exc.value.reason
    assert exc.value.reason != "session_phase_blocks_entry"


def test_permissive_phase_cannot_manufacture_a_trade_or_missing_objects():
    snap = snapshot("DISTRIBUTION_ACTIVE")
    with pytest.raises(NoCandidate) as exc:
        produce_exact(snap, parsed_over={"current_action": "stand_down"})
    assert exc.value.reason == "action_declines_entry"
    snap["toolbox"]["tool_instances"] = []
    with pytest.raises(NoCandidate) as exc:
        produce_exact(snap)
    assert "tool" in exc.value.reason
    for data, reason in (({"objective_id": "UNKNOWN"}, "objective_id_unknown"),
                         ({"invalidation_level": None}, "invalidation_missing")):
        with pytest.raises(NoCandidate) as exc:
            produce_exact(snapshot("DISTRIBUTION_ACTIVE"), parsed_over=data)
        assert exc.value.reason == reason


@pytest.mark.parametrize("history,reason", [
    ({}, "invalidation_history_unavailable"),
    ({"5m": {"recent_candles": [
        {"timestamp": "2026-08-05T14:55:00+00:00", "close": 29880.0,
         "temporal_status": "settled"},
        {"timestamp": "2026-08-05T15:25:00+00:00", "close": 29874.75,
         "temporal_status": "settled"},
    ]}}, "invalidation_touched"),
])
def test_unresolved_phase_cannot_rescue_unproven_or_broken_invalidation(history, reason):
    candidate = produce_exact(snapshot("EXCURSION_UNRESOLVED"))
    with pytest.raises(CandidateStale) as exc:
        assess(candidate, current_price=29880.0, high_since=29884.0,
               low_since=29878.0, tick_size=0.25, snapshot_id="snap-1",
               contract_id=LCP.CID, account_fingerprint=LCP.FP,
               account_state_digest="", data_age_seconds=2.0,
               in_window=True, manual_activity=False, now=LCP.NOW,
               invalidation_timeframes=history)
    assert exc.value.reason == reason


def test_execution_gate_session_phase_cannot_flip_authorization(monkeypatch):
    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    base = _gate_snapshot(required_trigger="confirmed", actual_trigger="confirmed")
    base["session_po3"] = snapshot("DISTRIBUTION_ACTIVE")["session_po3"]
    cautious = deepcopy(base)
    cautious["session_po3"] = snapshot("REACCUMULATION")["session_po3"]
    a, b = evaluate_gate(base), evaluate_gate(cautious)
    assert a["would_authorize_if_enabled"] is True
    assert b["would_authorize_if_enabled"] is True
    assert a["blocking_factors"] == b["blocking_factors"] == []
    assert a["session_phase_context"]["mechanical_entry_posture"] == "permissive"
    assert b["session_phase_context"]["mechanical_entry_posture"] == "caution"


def test_brain_input_exposes_context_not_legacy_permission():
    source = snapshot()
    payload = _session_po3_block(source)
    assert payload["authority_class"] == "CONTEXT_ONLY"
    assert payload["mechanical_entry_posture"] == "caution"
    assert "new_entry_allowed" not in payload
    assert "block_reason" not in payload
    absent = _session_po3_block({})
    assert absent["available"] is False
    assert absent["authority_class"] == "CONTEXT_ONLY"
    assert entry_context(source["session_po3"])["authority_class"] == "CONTEXT_ONLY"
