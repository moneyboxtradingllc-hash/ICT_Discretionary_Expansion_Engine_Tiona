"""TOOLBOX DIRECTIONAL TRUTH — a tool must mean what its label claims.

2026-08-12. Every family scorer took a `direction` argument and none of them
read it. `bullish_ifvg` and `bearish_ifvg` returned IDENTICAL scores from the
same undirected booleans (72/72, 77/77 measured on PROD-20260812-PM). That was
survivable only while `run_toolbox` scored one mechanically preselected side:
the label was true by assumption.

The first repair gated on "does this direction exist ANYWHERE in the snapshot",
which is a different claim from "this tool is directionally proven" -- and on 7
of 81 scans two timeframes swept opposite ways and the mirror came straight
back. So direction is now anchored to the timeframe whose OWN evidence witnesses
it, and the score is split into the evidence that made the tool exist (local)
and the market context that merely informs it (global).

A fact may INFLUENCE another fact without IMPERSONATING it.

No network. No model. Synthetic snapshots so the facts under test are the only
facts present.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from toolbox.toolbox_engine import (                                # noqa: E402
    _anchor_tfs, _direction_supported, _raw_status, _score_tool,
    score_instance, tool_instances, tool_provenance,
)

TFS = ["15m", "5m", "3m", "1m"]


def snap(*, sweeps=None, structure=None, alignment="neutral", session="regular"):
    """A snapshot carrying only what a test is about."""
    liq = {tf: {} for tf in TFS}
    for tf, direction in (sweeps or {}).items():
        liq[tf] = {"sweep_detected": True, "reclaim_detected": True,
                   "sweep_direction": direction}
    st = {tf: {} for tf in TFS}
    for tf, spec in (structure or {}).items():
        st[tf] = dict(spec)
    st["alignment"] = alignment
    return {"liquidity": liq, "structure": st, "expansion": {tf: {} for tf in TFS},
            "po3": {}, "volatility": {}, "memory": {}, "session": session}


# ══════════════════════════════════════════════════════════════════════════════
class TestDirectionMustBeEarned:

    def test_a_high_sweep_witnesses_a_BEARISH_reversal_only(self):
        s = snap(sweeps={"5m": "above_high"})
        assert _direction_supported("ifvg", "bearish", s) is True
        assert _direction_supported("ifvg", "bullish", s) is False

    def test_a_low_sweep_witnesses_a_BULLISH_reversal_only(self):
        s = snap(sweeps={"5m": "below_low"})
        assert _direction_supported("ifvg", "bullish", s) is True
        assert _direction_supported("ifvg", "bearish", s) is False

    def test_a_sweep_without_a_direction_proves_nothing(self):
        s = snap()
        s["liquidity"]["5m"] = {"sweep_detected": True, "reclaim_detected": True}
        assert _direction_supported("ifvg", "bullish", s) is False
        assert _direction_supported("ifvg", "bearish", s) is False
        assert _score_tool("bearish_ifvg", s) == 0

    def test_the_mirror_is_dead_on_a_single_sided_snapshot(self):
        """The original defect: identical scores for opposite directions."""
        s = snap(sweeps={"5m": "above_high"})
        assert _score_tool("bearish_ifvg", s) > 0
        assert _score_tool("bullish_ifvg", s) == 0

    def test_continuation_is_witnessed_by_the_break_not_by_a_sweep(self):
        s = snap(structure={"5m": {"bos": True, "bos_direction": "bearish"}})
        assert _direction_supported("order_block", "bearish", s) is True
        assert _direction_supported("order_block", "bullish", s) is False
        assert _direction_supported("ifvg", "bearish", s) is False, \
            "a BOS is not a sweep; it may not witness a reversal family"


# ══════════════════════════════════════════════════════════════════════════════
class TestDirectionBlindFamiliesStayClosed:
    """`mss` is a bare boolean with no `mss_direction`; displacement records a
    magnitude, not a side. Inferring their direction from `bos_direction` would
    rebuild the authority inversion one layer down."""

    @pytest.mark.parametrize("family", ["fvg", "opening_fvg", "mss_retest"])
    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_blind_family_is_never_offered(self, family, direction):
        s = snap(sweeps={"5m": "above_high"},
                 structure={"5m": {"bos": True, "bos_direction": "bearish",
                                   "mss": True}})
        assert _direction_supported(family, direction, s) is False

    def test_blind_family_scores_zero_even_with_rich_evidence(self):
        s = snap(sweeps={tf: "above_high" for tf in TFS},
                 structure={tf: {"bos": True, "bos_direction": "bearish",
                                 "mss": True} for tf in TFS})
        for tool in ("bearish_fvg", "bullish_fvg", "bearish_mss_retest"):
            assert _score_tool(tool, s) == 0, tool


# ══════════════════════════════════════════════════════════════════════════════
class TestCrossTimeframeContamination:
    """The 7-of-81 defect: direction proven somewhere, trigger sourced elsewhere."""

    def test_A_opposite_anchors_produce_two_distinct_instances(self):
        s = snap(sweeps={"1m": "above_high", "5m": "below_low"})
        ids = {i["tool_id"] for i in tool_instances(s)}
        assert "bearish_ifvg@1m" in ids
        assert "bullish_ifvg@5m" in ids
        assert "bearish_ifvg@5m" not in ids, "5m swept LOW; it cannot witness bearish"
        assert "bullish_ifvg@1m" not in ids, "1m swept HIGH; it cannot witness bullish"

    def test_C_same_direction_on_two_timeframes_is_TWO_instances(self):
        s = snap(sweeps={"1m": "above_high", "5m": "above_high"})
        ids = {i["tool_id"] for i in tool_instances(s) if i["family"] == "ifvg"}
        assert ids == {"bearish_ifvg@1m", "bearish_ifvg@5m"}, ids

    def test_a_family_is_not_collapsed_into_one_object_with_many_anchors(self):
        s = snap(sweeps={"1m": "above_high", "5m": "above_high"})
        assert _anchor_tfs("ifvg", "bearish", s) == ["5m", "1m"]
        insts = [i for i in tool_instances(s) if i["tool"] == "bearish_ifvg"]
        assert len(insts) == 2
        assert {i["source_tf"] for i in insts} == {"1m", "5m"}

    def test_E_an_unrelated_timeframe_cannot_move_local_evidence(self):
        s = snap(sweeps={"1m": "above_high", "5m": "below_low"})
        before = score_instance("bearish_ifvg", s, "1m")["local_evidence_score"]
        m = copy.deepcopy(s)
        m["liquidity"]["5m"] = {}                      # wipe the UNRELATED anchor
        after = score_instance("bearish_ifvg", m, "1m")["local_evidence_score"]
        assert before == after

    def test_local_evidence_the_ANCHOR_LACKS_is_never_borrowed(self):
        """Survived the first mutation campaign.

        Wiping an unrelated timeframe was too weak a probe: a merged read still
        ends on the anchor's own values, so the score did not move and the test
        passed while contaminated. The real question is whether evidence the
        anchor DOES NOT HAVE can be imported from a timeframe that does.

        Here 1m swept but never reclaimed; 5m reclaimed. The 1m tool is entitled
        to its sweep points and to nothing else.
        """
        s = snap()
        s["liquidity"]["1m"] = {"sweep_detected": True, "sweep_direction": "above_high"}
        s["liquidity"]["5m"] = {"reclaim_detected": True}
        i = score_instance("bearish_ifvg", s, "1m")
        assert i["local_evidence_score"] == 40, (
            "expected base 20 + sweep 20; a reclaim borrowed from 5m would make it 55")

    def test_wiping_the_ANCHOR_removes_the_instance_entirely(self):
        """Absence must be reported as absence, never as a weak score."""
        s = snap(sweeps={"1m": "above_high"})
        assert score_instance("bearish_ifvg", s, "1m") is not None
        m = copy.deepcopy(s)
        m["liquidity"]["1m"] = {}
        assert score_instance("bearish_ifvg", m, "1m") is None


# ══════════════════════════════════════════════════════════════════════════════
class TestScoreProvenanceIsSeparable:

    def test_B_F_global_context_moves_context_not_local(self):
        s = snap(sweeps={"1m": "above_high"}, alignment="neutral")
        base = score_instance("bearish_order_block", s, "1m") or \
            score_instance("bearish_ifvg", s, "1m")
        m = copy.deepcopy(s)
        m["structure"]["alignment"] = "full"
        after = score_instance(base["tool"], m, "1m")
        assert after["local_evidence_score"] == base["local_evidence_score"]
        assert after["global_context_score"] >= base["global_context_score"]

    def test_the_two_halves_add_up_to_the_reported_score(self):
        s = snap(sweeps={"5m": "above_high"})
        i = score_instance("bearish_ifvg", s, "5m")
        assert i["score"] == max(0, min(100, i["local_evidence_score"]
                                        + i["global_context_score"]))

    def test_every_instance_carries_its_witness(self):
        s = snap(sweeps={"5m": "above_high"})
        for i in tool_instances(s):
            assert i["source_tf"] in TFS
            assert i["directional_witness"]
            assert i["tool_id"] == f"{i['tool']}@{i['source_tf']}"

    def test_provenance_names_the_timeframe_that_proved_the_side(self):
        s = snap(sweeps={"1m": "above_high", "5m": "below_low"})
        assert tool_provenance("bearish_ifvg", s)["source_tf"] == "1m"
        assert tool_provenance("bullish_ifvg", s)["source_tf"] == "5m"
        assert tool_provenance("bearish_ifvg", s)["directional_witness"] == "above_high"


# ══════════════════════════════════════════════════════════════════════════════
class TestTheCageIsGone:
    """PHASE 2. `run_toolbox` used to return before scoring anything unless a
    mechanical selector had already picked a playbook AND a side. On
    PROD-20260812-PM that produced `tool_candidates: []` on 58 of 81 scans; 52 of
    those held truthful inventory the whole time. Nobody had looked."""

    def _snap(self, *, playbook, direction, sweeps):
        s = snap(sweeps=sweeps)
        s["playbook"] = {"selected_playbook": playbook, "direction": direction}
        s["risk"] = {"trade_allowed": True}
        return s

    @pytest.mark.parametrize("playbook,direction", [
        ("no_playbook", "neutral"),
        ("no_playbook", "conflicted"),
        ("liquidity_sweep_reversal", "neutral"),
        ("liquidity_sweep_reversal", "conflicted"),
    ])
    def test_a_mechanical_non_decision_cannot_suppress_generation(self, playbook, direction):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook=playbook, direction=direction,
                                   sweeps={"5m": "above_high"}))
        assert r["bearish_instances"], (playbook, direction)
        assert r["tool_candidates"], "a witnessed tool must reach the candidate list"

    def test_mechanical_BULLISH_cannot_suppress_a_truthful_bearish_instance(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="liquidity_sweep_reversal",
                                   direction="bullish", sweeps={"5m": "above_high"}))
        assert r["bearish_instances"]
        assert not r["bullish_instances"], "nothing swept a low; bullish is unwitnessed"

    def test_mechanical_BEARISH_cannot_suppress_a_truthful_bullish_instance(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="liquidity_sweep_reversal",
                                   direction="bearish", sweeps={"5m": "below_low"}))
        assert r["bullish_instances"]
        assert not r["bearish_instances"]

    def test_both_sides_are_generated_when_both_are_witnessed(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="no_playbook", direction="neutral",
                                   sweeps={"1m": "above_high", "5m": "below_low"}))
        assert r["bearish_instances"] and r["bullish_instances"]

    def test_instances_stay_source_tf_distinct_through_run_toolbox(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="no_playbook", direction="neutral",
                                   sweeps={"1m": "above_high", "5m": "above_high"}))
        ids = {i["tool_id"] for i in r["tool_instances"] if i["family"] == "ifvg"}
        assert ids == {"bearish_ifvg@1m", "bearish_ifvg@5m"}, ids

    def test_an_empty_result_means_evaluated_and_absent_not_unexamined(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="no_playbook", direction="neutral",
                                   sweeps={}))
        assert r["tool_instances"] == []
        assert "both directions evaluated" in " ".join(r["warnings"]), r["warnings"]

    def test_the_mechanical_selector_survives_only_as_context(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="no_playbook", direction="neutral",
                                   sweeps={"5m": "above_high"}))
        assert r["mechanical_playbook_context"] == "no_playbook"
        assert r["mechanical_direction_context"] == "neutral"
        assert r["bearish_instances"], "context must not gate generation"

    def test_candidates_carry_their_instance_identity(self):
        from toolbox.toolbox_engine import run_toolbox
        r = run_toolbox(self._snap(playbook="no_playbook", direction="neutral",
                                   sweeps={"5m": "above_high"}))
        for c in r["tool_candidates"]:
            assert c["tool_id"] == f"{c['tool']}@{c['source_tf']}"
            assert c["direction"] in ("bullish", "bearish")
            assert c["local_evidence_score"] + c["global_context_score"] >= c["score"]


class TestUnprovenIsRefusedNotWeakened:

    def test_an_unknown_family_forfeits(self):
        assert _direction_supported("not_a_family", "bearish", snap()) is False

    def test_a_non_directional_label_forfeits(self):
        s = snap(sweeps={"5m": "above_high"})
        for d in ("neutral", "conflicted", "", None):
            assert _direction_supported("ifvg", d, s) is False

    def test_context_alone_can_never_manufacture_a_tool(self):
        """`_context_score` is added AFTER the family term, so a gated tool that
        merely returned 0 could still clear the 40-point threshold on context."""
        s = snap(alignment="full")                      # rich context, no anchor
        for tool in ("bearish_ifvg", "bullish_ifvg", "bearish_order_block"):
            assert _score_tool(tool, s) == 0, tool
            assert _raw_status(_score_tool(tool, s)) == "no_tool"
