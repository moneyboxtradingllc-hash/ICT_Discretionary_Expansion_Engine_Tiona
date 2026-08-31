"""PHASE 3 — mechanical opinions may not hold permissions.

The forensic chain from PROD-20260812-PM ran:

    qualification.status = no_trade   (42 of 81 scans)
      -> selected_playbook = no_playbook
      -> direction = neutral
      -> run_toolbox early-returned, scoring nothing
      -> authorized_tool_catalog = []
      -> Terra: "no executable playbook/tool inventory is available"
      -> current_action = stand_down
      -> producer: action_declines_entry

Phase 2 removed the toolbox early returns. Phase 3 removes what was left: the
producer's `direction_disagreement` / `qualification_rejected` vetoes, the
`authorized_playbooks` narrowing, and the `no_playbook` gate on what the Brain
was allowed to SEE.

What is NOT removed, and is pinned here as still-refusing: Terra's own answer
being empty, and every FACTUAL check (Step 7 tool existence, direction match,
execution eligibility, risk). Facts may constrain reality. Opinions may not
constrain Terra.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain.brain_input import _two_sided_inventory                # noqa: E402
from toolbox.toolbox_engine import run_toolbox                       # noqa: E402

TFS = ["15m", "5m", "3m", "1m"]


def snapshot(*, qualification_status="no_trade", playbook="no_playbook",
             direction="neutral", sweep_tf="5m", sweep="above_high"):
    liq = {tf: {} for tf in TFS}
    if sweep:
        liq[sweep_tf] = {"sweep_detected": True, "reclaim_detected": True,
                         "sweep_direction": sweep}
    s = {"liquidity": liq,
         "structure": {tf: {} for tf in TFS} | {"alignment": "neutral"},
         "expansion": {tf: {} for tf in TFS}, "po3": {}, "volatility": {},
         "memory": {}, "session": "regular",
         "qualification": {"status": qualification_status},
         "playbook": {"selected_playbook": playbook, "direction": direction},
         "risk": {"trade_allowed": True}}
    s["toolbox"] = run_toolbox(s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
class TestQualificationIsNotTheNextCage:
    """The chain STARTED at qualification. Breaking the toolbox link is not
    enough if qualification can still erase the opportunity elsewhere."""

    def test_no_trade_still_yields_truthful_inventory(self):
        s = snapshot(qualification_status="no_trade")
        assert s["toolbox"]["bearish_instances"], \
            "a mechanical no_trade verdict may not erase a witnessed sweep"

    def test_no_trade_still_reaches_the_brain(self):
        inv = _two_sided_inventory(snapshot(qualification_status="no_trade"))
        assert inv["bearish"], "Terra must SEE what exists, whatever mechanics concluded"

    @pytest.mark.parametrize("status", ["no_trade", "candidate", "qualified", "elite"])
    def test_inventory_is_identical_across_every_qualification_verdict(self, status):
        base = _two_sided_inventory(snapshot(qualification_status="qualified"))
        other = _two_sided_inventory(snapshot(qualification_status=status))
        assert [t["tool_id"] for t in other["bearish"]] == \
               [t["tool_id"] for t in base["bearish"]]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheBrainSeesWhatExists:

    @pytest.mark.parametrize("playbook,direction", [
        ("no_playbook", "neutral"),
        ("no_playbook", "conflicted"),
        ("liquidity_sweep_reversal", "conflicted"),
        ("liquidity_sweep_reversal", "bullish"),      # mechanics prefers the OTHER side
    ])
    def test_a_mechanical_opinion_cannot_hide_a_witnessed_tool(self, playbook, direction):
        inv = _two_sided_inventory(snapshot(playbook=playbook, direction=direction))
        assert inv["bearish"], (playbook, direction)

    def test_mechanics_bullish_does_not_delete_the_bearish_side(self):
        inv = _two_sided_inventory(snapshot(playbook="liquidity_sweep_reversal",
                                            direction="bullish", sweep="above_high"))
        assert inv["bearish"] and not inv["bullish"], \
            "bearish was witnessed; bullish was not. The recommendation is irrelevant."

    def test_changing_only_the_recommendation_cannot_change_the_inventory(self):
        a = _two_sided_inventory(snapshot(playbook="no_playbook", direction="neutral"))
        b = _two_sided_inventory(snapshot(playbook="trend_continuation",
                                          direction="bullish"))
        assert [t["tool_id"] for t in a["bearish"]] == [t["tool_id"] for t in b["bearish"]]

    def test_the_recommendation_is_still_carried_as_an_opinion(self):
        inv = _two_sided_inventory(snapshot(playbook="no_playbook", direction="neutral"))
        assert inv["mechanical_playbook_recommendation"] == "no_playbook"
        assert inv["mechanical_direction_recommendation"] == "neutral"

    def test_the_note_no_longer_claims_the_opposite_side_is_unscored(self):
        note = _two_sided_inventory(snapshot())["note"]
        assert "inventory-only" not in note
        assert "do not authorise, restrict or gate" in note
        assert "never that no tool exists" in note

    def test_an_empty_side_means_unwitnessed_not_unexamined(self):
        inv = _two_sided_inventory(snapshot(sweep=None))
        assert inv["bullish"] == [] and inv["bearish"] == []

    def test_every_visible_instance_carries_its_witness(self):
        inv = _two_sided_inventory(snapshot())
        for t in inv["bearish"]:
            assert t["source_tf"] and t["directional_witness"]
            assert t["tool_id"] == f"{t['tool']}@{t['source_tf']}"


# ══════════════════════════════════════════════════════════════════════════════
class TestFactualVetoesSurvive:
    """Demotion is not deregulation."""

    def test_step7_tool_existence_is_still_enforced(self):
        from broker.luna_candidate_producer import CandidateProducer as CP
        src = __import__("inspect").getsource(CP._assert_tool_detected)
        for proposition in ("TOOL_NOT_DETECTED", "TOOL_DIRECTION_MISMATCH",
                            "TOOL_NOT_EXECUTION_ELIGIBLE"):
            assert proposition in src, proposition

    def test_terras_own_empty_answer_still_refuses(self):
        from broker.luna_candidate_producer import CandidateProducer as CP, NoCandidate
        with pytest.raises(NoCandidate) as exc:
            CP._playbook({"recommended_playbook_family": "none",
                          "recommended_tool_family": ["ifvg"]}, {})
        assert exc.value.reason == "playbook_unauthorized"

    def test_terras_own_stand_down_still_refuses(self):
        from broker.luna_candidate_producer import CandidateProducer as CP, NoCandidate
        with pytest.raises(NoCandidate) as exc:
            CP._direction({"narrative_direction": "conflicted"}, {})
        assert exc.value.reason == "stand_down"

    def test_mechanical_disagreement_is_recorded_in_the_trace(self):
        from broker.luna_candidate_producer import CandidateProducer as CP
        trace = {}
        d = CP._direction({"narrative_direction": "bearish"},
                          {"direction": "bullish", "qualified": False,
                           "reason": "funnel refused"}, trace)
        assert d == "bearish", "Terra's direction survives"
        assert trace["mechanical_direction_recommendation"] == "bullish"
        assert trace["direction_agreement"] is False
        assert trace["mechanical_qualification_observation"] == "funnel refused"
