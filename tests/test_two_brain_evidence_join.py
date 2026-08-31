"""EVIDENCE-SUBSTRATE-PHASE0 — the same-scan two-Brain join.

A completed trade must answer two questions at once: what the actual Terra-first
production organism did, and what deterministic-first + Terra shadow thought *on
that exact scan*. Without the join, Monday yields a trade and a pile of shadow
observations with no honest way to pair them -- and pairing them later by
timestamp is the same inference that once attributed a manual fill to the bot.

The join key is `snapshot_id`. Never time, never direction, never price.

The evidence is powerless: it is attached AFTER the candidate already exists,
nothing downstream reads it, and no shadow verdict changes anything.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import trade_lineage as TL                              # noqa: E402
from broker.topstepx_production_loop import ProductionLoop          # noqa: E402

SNAPSHOT_ID = "scan-20260810T141743"


class Producer:
    last_decision_trace = {
        "reward_risk": 1.27, "reward_risk_floor": 1.0,
        "legacy_reward_risk_floor": 1.5, "legacy_floor_verdict": "WOULD_REJECT",
        "eligible_only_because_floor_moved": True}


class Candidate:
    def __init__(self):
        self.extras = {"source": "live_llm"}


def shadow(verdict="CONFIRM", direction="bullish", outcome="ADJUDICATED",
           contradictions=None):
    """Build the shadow block THROUGH THE REAL CODE PATH.

    An earlier version of this fixture hardcoded `would_have_done`, so the join
    test fed its own constant through and asserted it came back -- proving
    nothing about `shadow_hypothetical()` and letting a wrong counterfactual be
    reported as fact. The disposition is now computed, never asserted.
    """
    from ai_brain import two_brain as TB
    if contradictions is None:
        contradictions = (["bullish delivery opposes bearish candidate"]
                          if verdict == "MATERIAL_REJECT" else [])
    proposal = TB.build_mechanical_proposal(
        thesis={"narrative_direction": direction,
                "narrative_phase": "distribution",
                "recommended_playbook_family": "liquidity_sweep_reversal"},
        objective={"objective_id": "OBJ_LIQ_SSL_2", "price": 29400.0,
                   "kind": "opposing_external_liquidity"},
        invalidation={"invalidation_id": "INV_PH_1", "price": 29850.0},
        reference_price=29700.0, snapshot_id=SNAPSHOT_ID, timestamp="t")
    proposal["mechanical_proposal_id"] = "MP-777"
    proposal["frozen_digest"] = TB.digest(
        {k: v for k, v in proposal.items() if k != "frozen_digest"})
    review = {"candidate_id": "MP-777", "verdict": verdict, "confidence": 91,
              "mechanical_direction_seen": direction,
              "objective_id_seen": "OBJ_LIQ_SSL_2",
              "invalidation_id_seen": "INV_PH_1",
              "material_contradictions": contradictions, "reasoning": "t"}
    classification = TB.classify_review(review, proposal)
    envelope = TB.build_envelope(proposal=proposal, review=review,
                                 classification=classification, mode=TB.SHADOW)
    return {"outcome": outcome,
            "would_have_done": TB.shadow_hypothetical(envelope),
            "effective_verdict": classification["effective_verdict"],
            "envelope": envelope}


def scan(shadow_block=None):
    return {"snapshot_id": SNAPSHOT_ID,
            "two_brain_shadow": shadow_block,
            "brain_result": {"model": "gpt-5.6-terra", "source": "llm",
                             "parsed": {"narrative_direction": "bullish",
                                        "current_action": "propose bullish entry",
                                        "objective_id": "OBJ_LIQ_BSL_1",
                                        "invalidation_id": "INV_PL_1"}}}


def attach(scan_dict):
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.producer = Producer()
    candidate = Candidate()
    loop._attach_evidence(candidate, scan_dict)
    return candidate


# ══════════════════════════════════════════════════════════════════════════════
class TestTheJoin:

    def test_the_link_is_by_snapshot_id(self):
        evidence = attach(scan(shadow())).extras["evidence"]
        assert evidence["snapshot_id"] == SNAPSHOT_ID
        assert evidence["two_brain_linkage"] == "SAME_SCAN"

    def test_every_two_brain_field_lands(self):
        block = attach(scan(shadow())).extras["evidence"]["two_brain_shadow"]
        assert block["mechanical_proposal_id"] == "MP-777"
        assert block["mechanical_direction"] == "bullish"
        assert block["objective_id"] == "OBJ_LIQ_SSL_2"
        assert block["invalidation_id"] == "INV_PH_1"
        assert block["terra_verdict"] == "CONFIRM"
        assert block["terra_confidence"] == 91
        assert block["material_contradictions"] == []
        assert block["would_have_done"] == "CONTINUE_TO_MECHANICAL_GATES"  # CONFIRM
        assert block["hybrid_disposition"] == "SHADOW_RECORDED_ONLY"

    def test_the_production_decision_lands(self):
        block = attach(scan(shadow())).extras["evidence"]["production_brain"]
        assert block["model"] == "gpt-5.6-terra"
        assert block["direction"] == "bullish"
        assert block["objective_id"] == "OBJ_LIQ_BSL_1"

    def test_the_rr_counterfactual_lands(self):
        block = attach(scan(shadow())).extras["evidence"]["rr_doctrine"]
        assert block["reward_risk"] == 1.27
        assert block["reward_risk_floor"] == 1.0
        assert block["legacy_reward_risk_floor"] == 1.5
        assert block["legacy_floor_verdict"] == "WOULD_REJECT"
        assert block["eligible_only_because_floor_moved"] is True

    def test_the_combine_governor_is_absent_not_fabricated(self):
        """It lives on another branch and is not in this build."""
        assert attach(scan(shadow())).extras["evidence"]["profit_governor"] is None


class TestDisagreementIsPreserved:
    """Phase 2 congruence research dies if the lineage normalises them."""

    def test_both_stories_survive_intact(self):
        evidence = attach(scan(shadow(verdict="MATERIAL_REJECT",
                                      direction="bearish"))).extras["evidence"]
        assert evidence["production_brain"]["direction"] == "bullish"
        assert evidence["two_brain_shadow"]["mechanical_direction"] == "bearish"
        assert evidence["two_brain_shadow"]["terra_verdict"] == "MATERIAL_REJECT"
        assert evidence["two_brain_shadow"]["material_contradictions"] == [
            "bullish delivery opposes bearish candidate"]
        assert evidence["production_brain"]["objective_id"] != \
            evidence["two_brain_shadow"]["objective_id"]

    @pytest.mark.parametrize("verdict", ["CONFIRM", "MATERIAL_REJECT", "ABSTAIN"])
    def test_no_shadow_verdict_alters_the_candidate(self, verdict):
        candidate = attach(scan(shadow(verdict=verdict)))
        assert candidate.extras["source"] == "live_llm"          # untouched
        assert candidate.extras["evidence"]["two_brain_shadow"][
            "terra_verdict"] == verdict


class TestAbsenceStaysAbsence:

    @pytest.mark.parametrize("outcome", [
        "MECHANICAL_STAND_DOWN", "BINDING_FAILED",
        "BOUND_NOT_ADJUDICATED", "ADJUDICATION_FAILED"])
    def test_every_shadow_non_result_is_recorded_honestly(self, outcome):
        evidence = attach(scan({"outcome": outcome})).extras["evidence"]
        assert evidence["shadow_outcome"] == outcome
        assert evidence["two_brain_shadow"]["terra_verdict"] is None
        assert evidence["two_brain_linkage"] == "SAME_SCAN"

    def test_a_missing_shadow_never_blocks_the_candidate(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", "off")
        evidence = attach(scan(None)).extras["evidence"]
        assert evidence["two_brain_linkage"] == "OFF"
        assert evidence["production_brain"]["direction"] == "bullish"

    def test_a_malformed_shadow_is_unavailable_not_guessed(self):
        evidence = attach(scan("not a dict")).extras["evidence"]
        assert evidence["two_brain_linkage"] == "UNAVAILABLE"

    def test_broken_plumbing_yields_missing_evidence_not_a_missing_trade(self):
        loop = ProductionLoop.__new__(ProductionLoop)
        loop.producer = Producer()

        class Hostile:
            @property
            def extras(self):
                raise RuntimeError("boom")

        loop._attach_evidence(Hostile(), scan(shadow()))     # must not raise


class TestImmutability:

    def test_later_snapshot_mutation_cannot_rewrite_history(self):
        source = scan(shadow())
        candidate = attach(source)
        envelope = source["two_brain_shadow"]["envelope"]
        envelope["terra_review"]["verdict"] = "MUTATED"
        envelope["mechanical_proposal"]["direction"] = "MUTATED"
        source["brain_result"]["parsed"]["narrative_direction"] = "MUTATED"
        evidence = candidate.extras["evidence"]
        assert evidence["two_brain_shadow"]["terra_verdict"] == "CONFIRM"
        assert evidence["two_brain_shadow"]["mechanical_direction"] == "bullish"
        assert evidence["production_brain"]["direction"] == "bullish"

    def test_nested_lists_are_detached_too(self):
        source = scan(shadow(verdict="MATERIAL_REJECT"))
        candidate = attach(source)
        source["two_brain_shadow"]["envelope"]["terra_review"][
            "material_contradictions"].append("injected later")
        assert candidate.extras["evidence"]["two_brain_shadow"][
            "material_contradictions"] == ["bullish delivery opposes bearish candidate"]


class TestZeroAuthority:

    GATES = ["src/broker/luna_candidate_producer.py",
             "src/broker/topstepx_combine_risk.py",
             "src/broker/topstepx_execution_runner.py",
             "src/qualification/trade_qualification_engine.py"]

    @pytest.mark.parametrize("key", ["two_brain_shadow", "would_have_done",
                                     "terra_verdict", "mechanical_proposal_id"])
    def test_no_gate_reads_the_evidence(self, key):
        """TWO_BRAIN_EXTRAS_AUTHORITY_READERS = 0."""
        out = subprocess.run(["git", "grep", "-l", key, "--"] + self.GATES,
                             capture_output=True, text=True, cwd=ROOT)
        assert out.stdout.strip() == "", f"{key}: {out.stdout}"

    def test_evidence_is_attached_after_the_candidate_exists(self):
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        produced = src.index("candidate = self.producer.produce(")
        attached = src.index("self._attach_evidence(candidate, scan)")
        assert produced < attached, "evidence must not participate in creation"


class TestEndToEndLineage:
    """One fake lifecycle: scan -> shadow -> candidate -> order -> fill -> exit."""

    class Ctx:
        def as_dict(self):
            return {"candidate_id": "CAN-9", "snapshot_id": SNAPSHOT_ID,
                    "mission_id": "M-1", "direction": "long", "quantity": 2,
                    "entry_order_id": 5001, "entry_trade_id": 6001,
                    "entry_fill_price": 29700.0,
                    "structural_stop_price": 29665.0,
                    "liquidity_target_price": 29760.0,
                    "stop_order_id": 5002, "target_order_id": 5003,
                    "contract_id": "CON.F.US.MNQ.U26",
                    "candidate_fingerprint": "fp"}

    def test_the_close_row_tells_the_whole_story(self, tmp_path, monkeypatch):
        monkeypatch.setattr(TL, "_root", lambda sid: str(tmp_path / str(sid)))
        candidate = attach(scan(shadow(verdict="MATERIAL_REJECT",
                                       direction="bearish")))
        extras = candidate.extras

        opened = TL.open_lineage(
            session_id="PROD-20260810", execution_context=self.Ctx(),
            brain_result=extras["brain_result"],
            shadow=extras["two_brain_shadow"],
            decision_trace=extras["decision_trace"],
            governor=extras["evidence"]["profit_governor"])
        closed = TL.close_lineage(session_id="PROD-20260810", lineage=opened,
                                  exit_price=29760.0, exit_reason="EXIT_TARGET",
                                  exit_trade_id=6002, reconciled=True)

        # execution identity
        assert closed["snapshot_id"] == SNAPSHOT_ID
        assert closed["candidate_id"] == "CAN-9"
        assert closed["entry_order_id"] == 5001
        # what production did
        assert closed["production_direction"] == "bullish"
        assert closed["production_model"] == "gpt-5.6-terra"
        # what the other brain thought, on the same scan, disagreeing
        assert closed["mechanical_proposal_id"] == "MP-777"
        assert closed["mechanical_direction"] == "bearish"
        assert closed["terra_review_verdict"] == "MATERIAL_REJECT"
        assert closed["terra_material_contradictions"] == [
            "bullish delivery opposes bearish candidate"]
        # a GROUNDED material reject means veto mode would have stood down
        assert closed["hybrid_would_have_done"] == "STAND_DOWN_CONTEXTUAL_REJECT"
        # the doctrine in force
        assert closed["legacy_floor_verdict"] == "WOULD_REJECT"
        assert closed["eligible_only_because_floor_moved"] is True
        # and the market's answer
        assert closed["exit_reason"] == "EXIT_TARGET"
        assert closed["realized_r"] == 1.714
        assert closed["reconciled"] is True


class TestShadowHypotheticalTruthTable:
    """The counterfactual must be COMPUTED, never asserted by a fixture.

    A black box that faithfully records the wrong hypothetical is worse than no
    black box: it produces confident, checkable-looking evidence for a claim the
    architecture never made.
    """

    @pytest.mark.parametrize("verdict,contradictions,effective,hypothetical", [
        ("CONFIRM", [], "CONFIRM", "CONTINUE_TO_MECHANICAL_GATES"),
        ("ABSTAIN", [], "ABSTAIN", "CONTINUE_TO_MECHANICAL_GATES"),
        ("MATERIAL_REJECT", ["bullish delivery opposes bearish candidate"],
         "MATERIAL_REJECT", "STAND_DOWN_CONTEXTUAL_REJECT"),
        # an unsupported veto is recorded as INVALID and does NOT stand down
        ("MATERIAL_REJECT", [], "INVALID_MATERIAL_REJECT",
         "CONTINUE_TO_MECHANICAL_GATES"),
        # nor does one that only restates a mechanical calculation
        ("MATERIAL_REJECT", ["reward_to_risk is only 0.7"],
         "INVALID_MATERIAL_REJECT", "CONTINUE_TO_MECHANICAL_GATES"),
    ])
    def test_the_truth_table(self, verdict, contradictions, effective,
                             hypothetical):
        block = shadow(verdict=verdict, direction="bearish",
                       contradictions=contradictions)
        assert block["effective_verdict"] == effective
        assert block["would_have_done"] == hypothetical
        # and shadow itself still never acts
        assert block["envelope"]["hybrid_disposition"] == "SHADOW_RECORDED_ONLY"

    def test_a_grounded_rejection_survives_into_the_lineage(self, tmp_path,
                                                            monkeypatch):
        """shadow -> extras -> OPEN -> CLOSE, without inversion."""
        monkeypatch.setattr(TL, "_root", lambda sid: str(tmp_path / str(sid)))
        candidate = attach(scan(shadow(verdict="MATERIAL_REJECT",
                                       direction="bearish")))
        assert candidate.extras["evidence"]["two_brain_shadow"][
            "would_have_done"] == "STAND_DOWN_CONTEXTUAL_REJECT"

        opened = TL.open_lineage(
            session_id="PROD-T", execution_context=TestEndToEndLineage.Ctx(),
            brain_result=candidate.extras["brain_result"],
            shadow=candidate.extras["two_brain_shadow"])
        assert opened["hybrid_would_have_done"] == "STAND_DOWN_CONTEXTUAL_REJECT"
        closed = TL.close_lineage(session_id="PROD-T", lineage=opened,
                                  exit_price=29760.0, exit_reason="EXIT_TARGET")
        assert closed["hybrid_would_have_done"] == "STAND_DOWN_CONTEXTUAL_REJECT"
        assert closed["terra_review_verdict"] == "MATERIAL_REJECT"

    def test_no_fabricated_opinion_when_adjudication_did_not_happen(self):
        for outcome in ("ADJUDICATION_FAILED", "BOUND_NOT_ADJUDICATED",
                        "MECHANICAL_STAND_DOWN", "BINDING_FAILED"):
            evidence = attach(scan({"outcome": outcome})).extras["evidence"]
            block = evidence["two_brain_shadow"]
            assert block["terra_verdict"] is None
            assert block["would_have_done"] is None
            assert block["material_contradictions"] is None

    def test_the_fixture_no_longer_hardcodes_the_answer(self):
        """Guard against the exact defect this class was written for."""
        src = open(os.path.join(ROOT, "tests",
                                "test_two_brain_evidence_join.py"),
                   encoding="utf-8").read()
        fixture = src[src.index("def shadow("):src.index("def scan(")]
        assert "shadow_hypothetical" in fixture
        assert '"would_have_done": "CONTINUE' not in fixture
