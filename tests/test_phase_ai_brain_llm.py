"""
Phase AI-BRAIN-L — real LLM Brain path tests.

The LLM is mocked here (regression must make NO network calls). These prove the
ROUTING: enabled→LLM invoked, disabled→deterministic, failure→explicit logged
fallback, success→full schema, and that run_narrative_brain is the brain entry
point (build_narrative alone does not yield a brain package).
"""
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
from ai_brain.brain_schema import validate_brain_output, validate_llm_core


def _snap():
    return {
        "timestamp": "20260611T102955", "session": "morning_continuation",
        "timeframes": {"1m": {"candles": [{"open": 701.6, "high": 701.8,
                              "low": 701.2, "close": 701.42}],
                              "last_candle": {"close": 701.42}}},
        "market_regime": {"regime_label": "range_rotation", "volatility_state": "unstable",
                          "expansion_state": "exhaustion_risk"},
        "structure": {"15m": {"bias": "bullish"}},
        "shared_context": {"delivery_state": "bearish_delivery", "delivery_confidence": 25,
                           "exhaustion_present": True},
        "po3": {"15m": {"phase": "manipulation", "manipulation_direction": "bearish",
                        "manipulation_direction_source": "sweep_semantics"}, "alignment": "mixed"},
        "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 65},
        "ai_context": {"directional_bias": "bullish", "confidence_score": 65},
        "liquidity": {"15m": {"sweep_detected": True, "sweep_direction": "above_high",
                              "reclaim_detected": True}},
        "playbook": {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "toolbox": {"preferred_tool": "bullish_ifvg", "tool_candidates": [
            {"tool": "bullish_ifvg", "score": 80, "effective_status": "actionable",
             "price_level": {"zone_low": 700.79}}]},
        "narrative_authority": {"active_liquidity_draw": {"side": "sell_side", "level": 699.6}},
        "protected_swings": {"protected_high": {"level": 702.5}, "protected_low": None},
        "position_monitor": {"has_open_position": False},
    }


_GOOD_LLM = {  # a schema-core-valid LLM narrative payload
    "market_story": "bearish delivery into a protected high; exhaustion.",
    "narrative_direction": "bearish", "narrative_phase": "manipulation",
    "phase_confidence": 60, "delivery_interpretation": "bearish_delivery@25",
    "liquidity_interpretation": "sell-side draw", "protected_high_interpretation": "approaching 702.5",
    "protected_low_interpretation": "none", "active_draw": "sell_side@699.6",
    "allowed_direction": "bearish", "forbidden_direction": "bullish",
    "preferred_trade_family": "reversal", "preferred_playbooks": ["liquidity_sweep_reversal"],
    "preferred_tools": ["bearish_ifvg"], "invalidation_level": 702.5,
    "thesis_health": "n/a", "contradiction_flags": [], "warnings": [],
    "confidence_by_component": {"delivery": 25, "liquidity": 60, "structure": 40},
    "current_action": "avoid_bullish", "reason": "delivery bearish vs bias bullish",
    "must_not_do": ["do not trade bullish"], "protected_high_status": "approaching",
    "protected_low_status": "none", "dominant_reasoning": "bearish delivery at protected high",
    "recommended_playbook_family": "liquidity_sweep_reversal",
    "recommended_tool_family": ["bearish_ifvg"],
}


def _ok_call(_inp):
    return {"parsed": dict(_GOOD_LLM), "ok": True, "model": "gpt-4o-mini",
            "prompt": "P", "user_content": "{}", "raw_response": "{...}",
            "usage": {"prompt_tokens": 2000, "completion_tokens": 400, "total_tokens": 2400},
            "fallback_reason": None}


def _fail_call(_inp):
    return {"parsed": None, "ok": False, "model": "gpt-4o-mini", "prompt": "P",
            "user_content": "{}", "raw_response": "garbage", "usage": None,
            "fallback_reason": "no_json_in_response"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_DIR": self.tmp,
                           "AI_RETRIEVAL_DIR": self.tmp})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR"):
            os.environ.pop(k, None)


class TestLLMEnabledCausesCall(_Base):
    def test_enabled_invokes_llm(self):
        os.environ["AI_BRAIN_LLM"] = "true"
        with patch.object(nb, "_call_llm", side_effect=_ok_call) as m:
            res = run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        m.assert_called_once()
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["output"]["narrative_direction"], "bearish")
        self.assertEqual(res["llm_usage"]["total_tokens"], 2400)

    def test_llm_success_full_schema(self):
        os.environ["AI_BRAIN_LLM"] = "true"
        with patch.object(nb, "_call_llm", side_effect=_ok_call):
            res = run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        ok, reason = validate_brain_output(res["output"])
        self.assertTrue(ok, reason)
        # code-injected fields present even though LLM didn't emit them
        self.assertIn("direction_provenance", res["output"])
        self.assertEqual(res["output"]["direction_provenance"]["source"], "ai_brain")


class TestLLMDisabledDeterministic(_Base):
    def test_disabled_does_not_call_llm(self):
        os.environ.pop("AI_BRAIN_LLM", None)
        with patch.object(nb, "_call_llm") as m:
            res = run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        m.assert_not_called()
        self.assertEqual(res["source"], "deterministic")


class TestFailedLLMExplicitFallback(_Base):
    def test_failure_logs_explicit_fallback(self):
        os.environ["AI_BRAIN_LLM"] = "true"
        with patch.object(nb, "_call_llm", side_effect=_fail_call):
            with self.assertLogs("ai_brain.narrative_brain", level="WARNING") as cm:
                res = run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        self.assertEqual(res["source"], "llm_failed_fallback")
        self.assertEqual(res["fallback_reason"], "no_json_in_response")
        self.assertTrue(any("explicit deterministic fallback" in m for m in cm.output))
        # output still schema-valid (deterministic core)
        ok, _ = validate_brain_output(res["output"])
        self.assertTrue(ok)


class TestPersistenceCapturesLLM(_Base):
    def test_llm_call_persisted(self):
        import json, glob
        os.environ["AI_BRAIN_LLM"] = "true"
        with patch.object(nb, "_call_llm", side_effect=_ok_call):
            run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        files = glob.glob(os.path.join(self.tmp, "*_QQQ.json"))
        self.assertTrue(files)
        rec = json.load(open(files[0], encoding="utf-8"))
        for f in ("llm_model", "llm_prompt", "llm_user_content", "llm_raw_response",
                  "llm_usage", "source", "input_payload", "parsed_output"):
            self.assertIn(f, rec)
        self.assertEqual(rec["source"], "llm")


class TestBrainEntryPointContract(_Base):
    def test_build_narrative_alone_is_not_a_brain_package(self):
        # build_narrative (NA engine) returns NA fields, NOT the 31-field brain
        # package. Brain evaluation must go through run_narrative_brain.
        from narrative_authority.narrative_engine import build_narrative
        na = build_narrative(_snap(), _snap()["protected_swings"])
        self.assertNotIn("memory_matches", na)
        self.assertNotIn("dominant_reasoning", na)
        res = run_narrative_brain(_snap(), "QQQ", StanceMemory(persist=False))
        self.assertIn("memory_matches", res["output"])
        self.assertIn("dominant_reasoning", res["output"])


class TestCoreValidator(_Base):
    def test_core_validator_accepts_narrative_only(self):
        core = {"market_story": "x", "narrative_direction": "bearish",
                "narrative_phase": "manipulation", "phase_confidence": 50,
                "allowed_direction": "bearish", "current_action": "avoid_bullish",
                "reason": "y"}
        ok, _ = validate_llm_core(core)
        self.assertTrue(ok)
        ok2, _ = validate_llm_core({"narrative_direction": "bearish"})
        self.assertFalse(ok2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
