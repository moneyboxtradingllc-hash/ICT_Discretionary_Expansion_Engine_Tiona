"""
Phase AB-4 — AI Brain authority wiring (OBSERVE MODE) tests (T1-T12).

Brain now consumes retrieval, emits the expanded package, runs parallel to the
wrapper with divergence logging, and persists stance across restart — all while
remaining observe-only (no generation/gate/execution influence).
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.narrative_brain as nb
from ai_brain.narrative_brain import run_narrative_brain
from ai_brain.stance_memory import StanceMemory
from ai_brain.divergence import compute_divergence
from ai_brain.brain_schema import validate_brain_output
from ai_retrieval import vector_store
from ai_retrieval.memory_schema import make_record


def _env(**kv):
    for k, v in kv.items():
        os.environ[k] = v


def _clear_env():
    for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR",
              "AI_RETRIEVAL_DIR", "AI_RETRIEVAL_ENABLED"):
        os.environ.pop(k, None)


def _snapshot(direction_bias="bullish"):
    return {
        "timestamp": "20260611T102955",
        "session": "morning_continuation",
        "timeframes": {"1m": {"candles": [{"open": 701.6, "high": 701.8,
                                           "low": 701.2, "close": 701.42}],
                              "last_candle": {"close": 701.42}}},
        "market_regime": {"regime_label": "range_rotation", "volatility_state": "unstable",
                          "expansion_state": "exhaustion_risk"},
        "structure": {"15m": {"bias": direction_bias}, "5m": {"bias": direction_bias}},
        "shared_context": {"delivery_state": "bearish_delivery", "delivery_confidence": 25,
                           "exhaustion_present": True},
        "po3": {"15m": {"phase": "manipulation", "manipulation_direction": "bearish",
                        "manipulation_direction_source": "sweep_semantics"},
                "alignment": "mixed"},
        "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 65,
                             "market_story": "bullish reversal post sweep"},
        "ai_debate": {"final_verdict": {"recommended_stance": "prepare_long"}},
        "ai_context": {"directional_bias": direction_bias, "confidence_score": 65},
        "liquidity": {"15m": {"sweep_detected": True, "sweep_direction": "above_high",
                              "reclaim_detected": True, "nearest_sell_side_liquidity": 699.6}},
        "playbook": {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "toolbox": {"preferred_tool": "bullish_ifvg",
                    "tool_candidates": [{"tool": "bullish_ifvg", "score": 80,
                                         "effective_status": "actionable",
                                         "price_level": {"zone_low": 700.79}}]},
        "narrative_authority": {"active_liquidity_draw": {"side": "sell_side", "level": 699.6}},
        "protected_swings": {"protected_high": {"level": 702.5}, "protected_low": None},
        "position_monitor": {"has_open_position": False},
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _env(AI_BRAIN_ENABLED="true", AI_BRAIN_DIR=self.tmp,
             AI_RETRIEVAL_DIR=self.tmp)
        os.environ.pop("AI_BRAIN_LLM", None)
        vector_store.clear()

    def tearDown(self):
        _clear_env()


class T1_T2_RetrievalReachesBrain(_Base):
    def _seed(self):
        for ts in ("a", "b"):
            vector_store.add_record(make_record(
                timestamp=ts, symbol="QQQ", regime="range_rotation",
                narrative_direction="bearish", narrative_phase="manipulation",
                delivery_direction="bearish", delivery_direction_source="sweep_semantics",
                direction_source="sweep_semantics", trade_taken=True,
                win_loss_be="loss", r_multiple=-1.0))

    def test_T1_retrieval_populates_memory_matches(self):
        self._seed()
        res = run_narrative_brain(_snapshot(), "QQQ", StanceMemory(persist=False))
        self.assertGreaterEqual(len(res["output"]["memory_matches"]), 1)

    def test_T2_brain_reasoning_includes_retrieval_evidence(self):
        self._seed()
        res = run_narrative_brain(_snapshot(), "QQQ", StanceMemory(persist=False))
        out = res["output"]
        self.assertIn("analog", out["reason"].lower() + out["dominant_reasoning"].lower())
        self.assertTrue(out["supporting_analogs"] or out["conflicting_analogs"])


class T3_SchemaPopulated(_Base):
    def test_expanded_package_present_and_valid(self):
        res = run_narrative_brain(_snapshot(), "QQQ", StanceMemory(persist=False))
        out = res["output"]
        ok, reason = validate_brain_output(out)
        self.assertTrue(ok, reason)
        for f in ("protected_high_status", "protected_low_status", "dominant_reasoning",
                  "supporting_analogs", "conflicting_analogs",
                  "recommended_playbook_family", "recommended_tool_family",
                  "direction_provenance"):
            self.assertIn(f, out)
        self.assertIn("structure_derived", out["direction_provenance"])


class T4_DivergenceLogging(_Base):
    def test_divergence_classified_and_logged(self):
        snap = _snapshot()
        snap["ai_brain"] = run_narrative_brain(snap, "QQQ", StanceMemory(persist=False))
        div = compute_divergence(snap, "QQQ", persist=True)
        # wrapper bullish@65 vs brain (NA synthesis → conflicted/bearish) must diverge
        self.assertTrue(div["diverged"])
        self.assertIn("direction_disagreement", div["classes"])
        self.assertEqual(div["wrapper_direction"], "bullish")
        self.assertNotEqual(div["brain_direction"], "bullish")
        self.assertIsNotNone(div.get("log_path"))
        rec = json.load(open(div["log_path"], encoding="utf-8"))
        self.assertIn("wrapper_reasoning", rec)
        self.assertIn("brain_reasoning", rec)


class T5_StanceSurvivesRestart(_Base):
    def test_stance_persists_and_reloads(self):
        m1 = StanceMemory(persist=True)
        m1.record("20260611T101500", {"narrative_direction": "bearish",
                                      "narrative_phase": "manipulation",
                                      "phase_confidence": 60, "current_action": "prepare_short"})
        # simulate process restart: brand-new instance reads from disk
        m2 = StanceMemory(persist=True)
        hist = m2.history_summary()
        self.assertTrue(hist["available"])
        self.assertEqual(hist["last"]["direction"], "bearish")


class T6_T7_T8_T9_ObserveOnly(_Base):
    def test_T6_brain_block_marked_observe_only(self):
        res = run_narrative_brain(_snapshot(), "QQQ", StanceMemory(persist=False))
        self.assertEqual(res["authority"], "observe_only")

    def test_T7_T8_T9_no_authority_imports(self):
        # brain + divergence must not import generation/gate/execution modules
        root = os.path.join(os.path.dirname(__file__), "..", "src", "ai_brain")
        forbidden = ("execution_gate", "order_builder", "paper_broker",
                     "risk_governor", "submit_paper_order", "qualify_trade",
                     "classify_playbook", "run_toolbox")
        for fn in os.listdir(root):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            for f in forbidden:
                self.assertNotIn(f, src, f"ai_brain/{fn} imports {f}")

    def test_disabled_is_inert(self):
        os.environ.pop("AI_BRAIN_ENABLED", None)
        res = run_narrative_brain(_snapshot(), "QQQ", StanceMemory(persist=False))
        self.assertFalse(res["enabled"])
        div = compute_divergence({"ai_brain": res}, "QQQ", persist=False)
        self.assertFalse(div["enabled"])


class T10_T11_Replay(_Base):
    """June 10/11 replay: both AIs observe, brain never authorizes."""
    def test_june11_long_scan_brain_diverges_from_wrapper(self):
        snap = _snapshot()  # the 10:29 long scan shape
        snap["ai_brain"] = run_narrative_brain(snap, "QQQ", StanceMemory(persist=False))
        div = compute_divergence(snap, "QQQ", persist=False)
        # wrapper said bullish (the trade that lost); brain did not
        self.assertEqual(div["wrapper_direction"], "bullish")
        self.assertNotEqual(div["brain_direction"], "bullish")

    def test_brain_provenance_non_structure(self):
        snap = _snapshot()
        res = run_narrative_brain(snap, "QQQ", StanceMemory(persist=False))
        prov = res["output"]["direction_provenance"]
        # delivery-led synthesis → not structure-derived
        self.assertFalse(prov["structure_derived"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
