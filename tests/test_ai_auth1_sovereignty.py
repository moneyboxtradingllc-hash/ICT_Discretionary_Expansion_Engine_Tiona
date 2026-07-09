"""
AI-AUTH-1 — Sovereign intelligence regression lock.

One organism. One brain. One sovereign intelligence. Everything else observes.

TEST A: ECU Brain is the sole live directional owner (wrapper/debate cannot
        author direction anywhere in the decision chain).
TEST B: the legacy wrapper cannot veto (gate authorizes with debate stand_down
        + fusion strong_disagreement when every sovereign check passes).
TEST C: the legacy wrapper cannot alter authorization via confidence (fusion
        status flips change nothing; no wrapper check in authorization_checks).
TEST D: the legacy wrapper cannot alter execution inputs (intent creation and
        the gated intent score are wrapper-free; alignment points come only
        from the Brain thesis).
TEST E: Market Commander remains shadow (observe_only, no consumer, and its
        reconnected thesis witness works).
TEST F: single sovereign chain — source-level guard that the authority modules
        contain no legacy-wrapper reads.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")

from decision_authority.decision_engine import make_decision, _determine_direction  # noqa: E402
from execution_gate.execution_gate import evaluate_gate                             # noqa: E402
from trade_intent.intent_builder import build_intent                                # noqa: E402
from intent_scoring.intent_scorer import _score_ai_alignment                        # noqa: E402
from market_commander.market_commander import (                                     # noqa: E402
    build_market_commander_matrix, _thesis_executable,
)

_CLEAN_ENV = {"EXECUTION_ENABLED": "false", "RULE_GOVERNANCE_MODE": "shadow",
              "COUNCIL_AUTHORITY": "observe", "NARRATIVE_AUTHORITY": "observe",
              "MARKET_COMMANDER_MODE": "false"}


def _gate_pass_snapshot(**over) -> dict:
    """Every SOVEREIGN gate check passes; wrapper output is maximally hostile."""
    snap = {
        "decision_authority": {"decision": "ready_for_execution",
                               "trade_authorized": False, "warnings": []},
        "risk": {"trade_allowed": True},
        "state_transition": {"invalidated": False},
        "setup_lifecycle": {"active": True, "current_phase": "actionable",
                            "age_scans": 5, "direction": "bullish"},
        "toolbox": {"preferred_tool": "bullish_fvg",
                    "best_available_raw_status": "actionable",
                    "tool_candidates": [{
            "tool": "bullish_fvg", "raw_status": "actionable",
            "effective_status": "actionable",
            "trigger_prep": {"execution_ready": True,
                             "raw_trigger_status": "confirmed"},
        }]},
        "regime_permissions": {"enabled": False},
        "playbook": {"selected_playbook": "expansion_continuation",
                     "direction": "bullish"},
        "qualification": {"status": "qualified"},
        "council": {},
        "shared_context": {},
        "narrative_authority": {},
        # ── hostile wrapper output: must change NOTHING ──
        "ai_debate": {"final_verdict": {"recommended_stance": "stand_down",
                                        "dominant_thesis": "bearish",
                                        "verdict_confidence": 99}},
        "confidence_fusion": {"combined_confidence": 10,
                              "fusion_status": "strong_disagreement"},
        "ai_discretionary": {"ai_direction": "bearish", "ai_confidence": 1},
    }
    snap.update(over)
    return snap


class TestA_SovereignDirection(unittest.TestCase):
    def test_wrapper_cannot_author_direction(self):
        # no setup, neutral playbook — wrapper and debate scream bullish
        snap = {
            "setup_lifecycle": {"active": False},
            "playbook": {"direction": "neutral", "selected_playbook": "no_playbook"},
            "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 95},
            "ai_debate": {"final_verdict": {"dominant_thesis": "bullish"}},
        }
        self.assertEqual(_determine_direction(snap), "neutral")

    def test_brain_owned_playbook_direction_flows(self):
        snap = {
            "setup_lifecycle": {"active": False},
            "playbook": {"direction": "bearish"},
            "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 95},
        }
        self.assertEqual(_determine_direction(snap), "bearish")

    def test_decision_output_ignores_hostile_wrapper(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            da = make_decision(_gate_pass_snapshot())
        self.assertEqual(da["direction"], "bullish")     # setup/playbook, not wrapper
        self.assertEqual(da["decision"], "ready_for_execution")


class TestB_WrapperCannotVeto(unittest.TestCase):
    def test_gate_authorizes_despite_hostile_wrapper(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            snap = _gate_pass_snapshot()
            snap["decision_authority"] = make_decision(snap)
            gate = evaluate_gate(snap)
        self.assertTrue(gate["would_authorize_if_enabled"],
                        f"blocked by: {gate['blocking_factors']}")
        self.assertNotIn("ai debate stance is stand_down",
                         " | ".join(gate["blocking_factors"]))

    def test_debate_stance_recorded_as_observability_only(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            snap = _gate_pass_snapshot()
            snap["decision_authority"] = make_decision(snap)
            gate = evaluate_gate(snap)
        self.assertEqual(gate["ai_debate_stance_observed"], "stand_down")
        self.assertEqual(gate["fusion_status_observed"], "strong_disagreement")


class TestC_WrapperCannotAlterConfidenceAuthority(unittest.TestCase):
    def test_fusion_flip_changes_nothing(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            hostile = _gate_pass_snapshot()
            hostile["decision_authority"] = make_decision(hostile)
            friendly = _gate_pass_snapshot(
                confidence_fusion={"combined_confidence": 95,
                                   "fusion_status": "agreement"})
            friendly["decision_authority"] = make_decision(friendly)
            g1, g2 = evaluate_gate(hostile), evaluate_gate(friendly)
        self.assertEqual(g1["would_authorize_if_enabled"],
                         g2["would_authorize_if_enabled"])
        self.assertEqual(g1["blocking_factors"], g2["blocking_factors"])

    def test_no_wrapper_check_in_authorization(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            gate = evaluate_gate(_gate_pass_snapshot())
        self.assertNotIn("ai_verdict_supports_trade", gate["authorization_checks"])


class TestD_WrapperCannotAlterExecution(unittest.TestCase):
    def test_intent_created_despite_debate_stand_down(self):
        with patch.dict(os.environ, _CLEAN_ENV):
            snap = _gate_pass_snapshot()
            snap["decision_authority"] = make_decision(snap)
            snap["execution_gate"] = evaluate_gate(snap)
            # give the preferred candidate an entry zone for intent building
            snap["toolbox"]["tool_candidates"][0]["price_level"] = {
                "level_type": "fvg",
                "zone_low": 700.0, "zone_high": 701.0, "midpoint": 700.5,
                "current_price": 700.6, "price_relation": "inside_zone",
                "invalidation_level": 699.0,
            }
            intent = build_intent(snap, "QQQ")
        self.assertTrue(intent["intent_created"],
                        f"intent blocked: {intent.get('reason')}")
        self.assertEqual(intent["intent_type"], "long")

    def test_alignment_score_is_brain_sourced_only(self):
        wrapper_only = {
            "ai_debate": {"final_verdict": {"dominant_thesis": "bullish"}},
            "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 99},
            "confidence_fusion": {"fusion_status": "agreement"},
        }
        self.assertEqual(_score_ai_alignment(wrapper_only, "bullish"), 0)

        brain = {"brain_thesis": {"owner": "ai_brain", "direction": "bullish",
                                  "confidence": 70}}
        self.assertEqual(_score_ai_alignment(brain, "bullish"), 10)
        brain_low = {"brain_thesis": {"owner": "ai_brain", "direction": "bullish",
                                      "confidence": 40}}
        self.assertEqual(_score_ai_alignment(brain_low, "bullish"), 7)
        brain_opposed = {"brain_thesis": {"owner": "ai_brain",
                                          "direction": "bearish",
                                          "confidence": 90}}
        self.assertEqual(_score_ai_alignment(brain_opposed, "bullish"), 0)


class TestE_MarketCommanderShadow(unittest.TestCase):
    def test_matrix_always_observe_only(self):
        for snap in ({}, _gate_pass_snapshot()):
            m = build_market_commander_matrix(snap)
            self.assertEqual(m["authority_level"], "observe_only")

    def test_thesis_witness_reconnected(self):
        self.assertTrue(_thesis_executable(
            {"thesis_state": {"thesis_status": "EXECUTABLE"}}))
        self.assertTrue(_thesis_executable(
            {"thesis_lifecycle": {"active_thesis": {"status": "EXECUTABLE"}}}))
        self.assertFalse(_thesis_executable(
            {"thesis_state": {"thesis_status": "ACTIVE"}}))
        self.assertFalse(_thesis_executable({}))

    def test_no_module_consumes_commander_output(self):
        """Source guard: nothing outside the allowed set reads
        snapshot['market_commander'].

        MC-ENFORCE (2026-07-09): Market Commander was promoted from OBSERVE_ONLY
        to FINAL ENVIRONMENT AUTHORITY. commander_authority.py is the thin
        authority adapter that derives the commander_* verdict from the MC matrix;
        it is the ONE sanctioned consumer of the read. The execution gate consumes
        it only through that adapter's import (no direct 'market_commander' read),
        so the sovereignty invariant is preserved: exactly one authority owner."""
        allowed = {
            os.path.join("market_commander", "market_commander.py"),
            os.path.join("market_commander", "commander_authority.py"),  # MC-ENFORCE authority adapter
            os.path.join("market_data", "snapshot_builder.py"),   # writes it
            os.path.join("live_scan", "scan_loop.py"),            # writes/prints
            os.path.join("live_scan", "snapshot_store.py"),       # persists
            # REPLAY-2 — the replay walker mirrors scan_loop's write (same
            # observe-only build; the pipeline never imports replay_validation)
            os.path.join("replay_validation", "replay_session.py"),
            os.path.join("ai_brain", "narrative_brain.py"),       # AUTHORS B2 block
            os.path.join("ai_brain", "brain_prompt.py"),          # B2 prompt text
            # META-1 — observe-only self-observation reads MC contradictions
            # as a health WITNESS (no authority; locked by test_meta1_awareness)
            os.path.join("adaptive_learning", "meta_awareness_engine.py"),
        }
        offenders = []
        for root, _dirs, files in os.walk(_SRC):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                rel = os.path.relpath(path, _SRC)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
                if '"market_commander"' in txt or "'market_commander'" in txt:
                    if rel not in allowed:
                        offenders.append(rel)
        self.assertEqual(offenders, [],
                         f"market_commander consumed outside shadow set: {offenders}")


class TestF_SingleSovereignChain(unittest.TestCase):
    """Source-level lock: the authority modules are wrapper-free."""

    def _src(self, *parts) -> str:
        with open(os.path.join(_SRC, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_decision_engine_wrapper_free(self):
        txt = self._src("decision_authority", "decision_engine.py")
        self.assertNotIn('get("ai_debate"', txt)
        self.assertNotIn('get("ai_discretionary"', txt)

    def test_intent_builder_wrapper_free(self):
        txt = self._src("trade_intent", "intent_builder.py")
        self.assertNotIn('get("ai_debate"', txt)
        self.assertNotIn('get("ai_discretionary"', txt)

    def test_intent_scorer_wrapper_free(self):
        txt = self._src("intent_scoring", "intent_scorer.py")
        self.assertNotIn('get("ai_discretionary"', txt)
        self.assertNotIn('get("confidence_fusion"', txt)
        self.assertNotIn('get("ai_debate"', txt)

    def test_gate_has_no_wrapper_authority(self):
        txt = self._src("execution_gate", "execution_gate.py")
        self.assertNotIn("ai_verdict_supports_trade", txt)
        self.assertNotIn('fusion_status != "strong_disagreement"', txt)
        self.assertNotIn('fusion_status == "strong_disagreement"', txt)

    def test_narrative_lens_is_brain_sourced(self):
        txt = self._src("narrative_authority", "narrative_engine.py")
        self.assertNotIn('get("ai_discretionary"', txt)
        self.assertIn('snapshot.get("ai_brain"', txt)


if __name__ == "__main__":
    unittest.main()
