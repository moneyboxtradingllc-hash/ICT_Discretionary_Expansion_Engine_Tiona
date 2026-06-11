"""
Phase AI-SHADOW — Fable 5 shadow evaluator test suite.

Non-negotiable: shadow failures never affect live trading; shadow output
never enters execution_gate, order_builder, or trade_manager.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_layer.shadow_ai_evaluator as sh_mod
from ai_layer.shadow_ai_evaluator import evaluate_shadow_ai


def _snapshot(live_stance="prepare_long"):
    return {
        "ai_debate": {"final_verdict": {"recommended_stance": live_stance}},
        "ai_context": {}, "structure": {}, "volatility": {}, "expansion": {},
        "liquidity": {}, "po3": {}, "qualification": {"status": "qualified"},
        "toolbox": {"tool_candidates": []},
    }


def _api_response(stance="long", confidence=70):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"type": "text", "text": json.dumps({
            "stance": stance, "confidence": confidence,
            "reasons": ["structure aligned"], "concerns": ["range day"],
        })}],
    }
    return resp


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["AI_SHADOW_DIR"]     = self.tmp.name
        os.environ["AI_SHADOW_ENABLED"] = "true"
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        for k in ("AI_SHADOW_DIR", "AI_SHADOW_ENABLED", "ANTHROPIC_API_KEY"):
            self.addCleanup(lambda k=k: os.environ.pop(k, None))


class TestShadowEvaluation(_Base):

    def test_success_agreement_logged(self):
        with patch.object(sh_mod.requests, "post",
                          return_value=_api_response("long", 72)):
            result = evaluate_shadow_ai(_snapshot("prepare_long"), "QQQ")
        self.assertTrue(result["success"])
        self.assertEqual(result["stance"], "long")
        self.assertEqual(result["live_stance"], "long")
        self.assertTrue(result["agrees_with_live"])
        self.assertEqual(result["provider"], "Fable5")
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_disagreement_logged(self):
        with patch.object(sh_mod.requests, "post",
                          return_value=_api_response("stand_down", 80)):
            result = evaluate_shadow_ai(_snapshot("prepare_long"), "QQQ")
        self.assertTrue(result["success"])
        self.assertFalse(result["agrees_with_live"])
        self.assertEqual(result["stance"], "stand_down")
        self.assertEqual(result["live_stance"], "long")

    def test_timeout_does_not_raise_or_block(self):
        with patch.object(sh_mod.requests, "post",
                          side_effect=requests.Timeout()):
            result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["success"])
        self.assertIn("timeout", result["error"])
        self.assertIsNone(result["agrees_with_live"])

    def test_invalid_json_does_not_raise_or_block(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"type": "text",
                                               "text": "the market feels bullish"}]}
        with patch.object(sh_mod.requests, "post", return_value=resp):
            result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["success"])
        self.assertIn("no JSON", result["error"])

    def test_invalid_stance_rejected_gracefully(self):
        with patch.object(sh_mod.requests, "post",
                          return_value=_api_response("yolo", 50)):
            result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["success"])
        self.assertIn("invalid stance", result["error"])

    def test_stance_aliases_normalized(self):
        for raw, expected in (("bullish", "long"), ("SELL", "short"),
                              ("neutral", "no_trade"), ("avoid", "stand_down")):
            with patch.object(sh_mod.requests, "post",
                              return_value=_api_response(raw, 50)):
                result = evaluate_shadow_ai(_snapshot(), "QQQ")
            self.assertTrue(result["success"], raw)
            self.assertEqual(result["stance"], expected, raw)

    def test_missing_api_key_fails_open(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["success"])
        self.assertIn("ANTHROPIC_API_KEY", result["error"])

    def test_disabled_skips_entirely(self):
        os.environ["AI_SHADOW_ENABLED"] = "false"
        with patch.object(sh_mod.requests, "post") as post:
            result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["enabled"])
        post.assert_not_called()

    def test_http_error_fails_open(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        with patch.object(sh_mod.requests, "post", return_value=resp):
            result = evaluate_shadow_ai(_snapshot(), "QQQ")
        self.assertFalse(result["success"])
        self.assertIn("429", result["error"])


class TestPersistence(_Base):

    def test_result_persisted_success_and_failure(self):
        with patch.object(sh_mod.requests, "post",
                          return_value=_api_response("long", 70)):
            evaluate_shadow_ai(_snapshot("prepare_long"), "QQQ")
        with patch.object(sh_mod.requests, "post",
                          side_effect=requests.Timeout()):
            evaluate_shadow_ai(_snapshot(), "QQQ")

        import glob
        files = glob.glob(os.path.join(self.tmp.name, "*_QQQ_shadow.json"))
        self.assertEqual(len(files), 1)
        with open(files[0], encoding="utf-8") as f:
            evals = json.load(f)["evaluations"]
        self.assertEqual(len(evals), 2)
        self.assertTrue(evals[0]["success"])
        self.assertTrue(evals[0]["agrees_with_live"])
        self.assertFalse(evals[1]["success"])


class TestExecutionIsolation(_Base):
    """Proof the execution path is unchanged."""

    def test_gate_output_identical_with_shadow_present(self):
        from execution_gate.execution_gate import evaluate_gate
        os.environ["EXECUTION_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

        snap = {
            "decision_authority": {"decision": "ready_for_execution",
                                   "trade_authorized": False},
            "risk": {"trade_allowed": True},
            "state_transition": {"invalidated": False},
            "setup_lifecycle": {"active": True, "current_phase": "maturing",
                                "age_scans": 3},
            "ai_debate": {"final_verdict": {"recommended_stance": "prepare_long"}},
            "confidence_fusion": {"fusion_status": "agreement"},
            "toolbox": {"preferred_tool": "bullish_fvg", "tool_candidates": [{
                "tool": "bullish_fvg",
                "trigger_prep": {"execution_ready": True,
                                 "raw_trigger_status": "confirmed"}}]},
            "regime_permissions": {"enabled": True, "allowed": True,
                                   "required_trigger_status": "confirmed",
                                   "min_setup_age_scans": 2},
        }
        before = evaluate_gate(copy.deepcopy(snap))
        snap["ai_shadow"] = {"enabled": True, "success": True,
                             "stance": "stand_down", "confidence": 99,
                             "agrees_with_live": False}
        after = evaluate_gate(snap)
        self.assertEqual(before, after)

    def test_execution_modules_never_reference_shadow(self):
        root = os.path.join(os.path.dirname(__file__), "..", "src")
        for rel in ("execution_gate/execution_gate.py",
                    "paper_execution/order_builder.py",
                    "paper_execution/trade_manager.py"):
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                self.assertNotIn("ai_shadow", f.read(),
                                 f"{rel} references shadow AI — isolation violation")


class TestOutcomeScoring(_Base):

    def test_shadow_vs_outcomes_join(self):
        from ai_layer.shadow_ai_evaluator import score_shadow_vs_outcomes
        trades = [
            {"trade_id": "T1", "realized_r": -1.0,
             "ai_shadow_at_entry": {"stance": "stand_down",
                                    "live_stance": "long",
                                    "agrees_with_live": False}},
            {"trade_id": "T2", "realized_r": 2.0,
             "ai_shadow_at_entry": {"stance": "no_trade",
                                    "live_stance": "long",
                                    "agrees_with_live": False}},
            {"trade_id": "T3", "realized_r": 1.5,
             "ai_shadow_at_entry": {"stance": "long",
                                    "live_stance": "long",
                                    "agrees_with_live": True}},
        ]
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=[("20260611", "f.json", trades)]):
            card = score_shadow_vs_outcomes("QQQ")
        self.assertEqual(card["trades_scored"], 3)
        self.assertEqual(card["agreed"], 1)
        self.assertEqual(card["disagreed"], 2)
        self.assertEqual(card["avoided_loss_R"], 1.0)   # T1: shadow dodged a loser
        self.assertEqual(card["missed_winner_R"], 2.0)  # T2: shadow skipped a winner
        self.assertEqual(card["net_shadow_value_R"], -1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
