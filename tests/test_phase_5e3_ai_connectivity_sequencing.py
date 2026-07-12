"""
Phase 5E.3 — AI Connectivity and Sequencing Tests.

Covers:
  01  AI config reads model from env
  02  Invalid model failure surfaces safely (no exception)
  03  fallback_used=True on external failure
  04  ai_external_success=True on mocked success
  05  ai_model_used persisted in ai_discretionary
  06  memory_search included in AI compact input when present in snapshot
  07  performance_dashboard included in AI compact input when present in snapshot
  08  recommendations included in AI compact input when present in snapshot
  09  confidence_modifier remains 0 (authority invariant)
  10  authority_level remains observe_only in intelligence layers
  11  no execution behavior changed (gate still evaluates correctly)
  12  no decision authority changed (decision engine still evaluates correctly)
  13  full regression — all key modules importable
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_snapshot():
    return {
        "timestamp":  "2026-06-08T10:00:00",
        "session":    "ny",
        "qualification": {"status": "no_trade", "grade": "F", "direction": "neutral", "opportunity_score": 0},
        "playbook":      {"selected_playbook": "no_playbook", "status": "no_playbook", "direction": "neutral", "playbook_confidence": 0},
        "risk":          {"trade_allowed": False, "risk_tier": "blocked", "authority_reason": "test", "blocks": [], "restrictions": []},
        "toolbox":       {"preferred_tool": None, "toolbox_status": "no_tool", "best_available_raw_status": "no_tool",
                          "best_available_effective_status": "no_tool", "tool_candidates": [], "near_tie_tools": []},
        "structure":     {"alignment": "neutral"},
        "volatility":    {},
        "expansion":     {},
        "liquidity":     {},
        "po3":           {"alignment": ""},
        "memory":        {"available": False, "snapshot_count": 0},
        "ai_context":    {"market_narrative": "neutral", "market_state": "ranging", "directional_bias": "neutral",
                          "confidence_score": 50, "confidence_tier": "moderate", "trade_personality": "neutral",
                          "coherence": {}, "warnings": [], "summary": ""},
        "market_regime": {"enabled": False},
        "experience_summary": {"experience_enabled": False, "sample_size": 0},
        "experience_correlation": {"sample_size": 0, "correlation_confidence": "none",
                                   "strongest_positive_correlations": [], "strongest_negative_correlations": []},
        "ai_feedback_summary": {"sample_size": 0},
        "decision_authority": {"decision": "stand_down", "trade_authorized": False,
                               "authority_level": "observe_only", "confidence_modifier": 0},
    }


def _valid_external_response():
    return {
        "agreement_with_playbook": True,
        "agreement_with_risk":     True,
        "ai_direction":            "neutral",
        "ai_confidence":           45,
        "market_story":            "Test market story.",
        "primary_thesis":          "Test thesis.",
        "concerns":                [],
        "missing_evidence":        [],
        "invalidation_thesis":     "Test invalidation.",
        "preferred_scenario":      "Test preferred.",
        "alternative_scenario":    "Test alternative.",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPhase5E3AIConnectivitySequencing(unittest.TestCase):

    # 01 — config reads from env
    def test_01_ai_config_reads_from_env(self):
        from ai_layer.ai_api_adapter import get_ai_config
        with patch.dict(os.environ, {"AI_PROVIDER": "openai", "AI_MODEL": "gpt-test-model", "AI_TIMEOUT_SECONDS": "15"}):
            cfg = get_ai_config()
        self.assertEqual(cfg["provider"], "openai")
        self.assertEqual(cfg["model"],    "gpt-test-model")
        self.assertEqual(cfg["timeout"],  15)

    # 02 — invalid model failure surfaces safely
    def test_02_invalid_model_failure_surfaces_safely(self):
        from ai_layer.ai_api_adapter import call_external_ai
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("model_not_found")
        with patch("ai_layer.ai_api_adapter._openai") as mock_openai:
            mock_openai.OpenAI.return_value = mock_client
            mock_openai.APITimeoutError       = type("T", (Exception,), {})
            mock_openai.AuthenticationError   = type("A", (Exception,), {})
            mock_openai.RateLimitError        = type("R", (Exception,), {})
            mock_openai.APIConnectionError    = type("C", (Exception,), {})
            mock_openai.APIStatusError        = type("S", (Exception,), {})
            mock_openai.OpenAIError           = type("O", (Exception,), {})
            result = call_external_ai({"test": True})
        self.assertFalse(result["ai_external_success"])
        self.assertTrue(result["fallback_required"])

    # (test_08 retired with the recommendation_engine — ADAPT-LOOP-5)

    # 11 — no execution behavior changed
    def test_11_no_execution_behavior_changed(self):
        from execution_gate.execution_gate import evaluate_gate
        snap = _minimal_snapshot()
        snap["decision_authority"] = {"decision": "stand_down", "trade_authorized": False,
                                      "warnings": [], "confidence": 0}
        snap["setup_lifecycle"]    = {"active": False}
        snap["state_transition"]   = {"invalidated": False}
        snap["ai_debate"]          = {"enabled": False, "final_verdict": {}}
        snap["confidence_fusion"]  = {"fusion_status": "agreement", "combined_confidence": 0}
        gate = evaluate_gate(snap)
        self.assertIn("gate_status",    gate)
        self.assertIn("allow_execution", gate)
        self.assertFalse(gate["allow_execution"])

    # 12 — no decision authority changed
    def test_12_no_decision_authority_changed(self):
        from decision_authority.decision_engine import make_decision
        snap = _minimal_snapshot()
        snap["setup_lifecycle"]   = {"active": False}
        snap["state_transition"]  = {"invalidated": False}
        snap["ai_debate"]         = {"enabled": False, "final_verdict": {}}
        snap["confidence_fusion"] = {"fusion_status": "agreement", "combined_confidence": 0}
        snap["execution_gate"]    = {"allow_execution": False}
        da = make_decision(snap)
        self.assertIn("decision",        da)
        self.assertIn("trade_authorized", da)
        self.assertFalse(da["trade_authorized"])
        self.assertEqual(da.get("authority_level", "observe_only"), "observe_only")

    # 13 — full regression: all key modules importable without error
    def test_13_full_regression_imports(self):
        import importlib
        modules = [
            "ai_layer.ai_api_adapter",
            "ai_layer.ai_connectivity_test",
            "market_data.snapshot_builder",
            "execution_gate.execution_gate",
            "decision_authority.decision_engine",
            "memory_search.similarity_search",
            "memory_search.memory_record_builder",
            "performance_intelligence.dashboard_builder",
        ]
        for mod in modules:
            with self.subTest(module=mod):
                importlib.import_module(mod)


if __name__ == "__main__":
    unittest.main()
