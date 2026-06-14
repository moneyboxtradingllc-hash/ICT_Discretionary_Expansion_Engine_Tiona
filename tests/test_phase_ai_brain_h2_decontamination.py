"""
Phase AI-BRAIN-H2 — production LLM input decontamination tests (T1-T9).

Proves the production build_brain_input payload carries no structure-direction
contamination, structure is isolated to STRUCTURE_WITNESS (non-directional), the
prompt states the safety contract, and the taint guard rejects contaminated input.
LLM mocked where called.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.brain_input import build_brain_input
from ai_brain.brain_validation import scan_payload_taint
from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
import ai_brain.narrative_brain as nb
from ai_brain.stance_memory import StanceMemory


def _snap(struct_bias="bearish", delivery="bullish_delivery"):
    return {
        "timestamp": "20260611T171700+00:00", "session": "afternoon",
        "structure": {"15m": {"bias": struct_bias, "state": f"{struct_bias}_continuation",
                              "last_swing_high": 699.42, "last_swing_low": 699.28,
                              "bos": True, "mss": False}},
        "shared_context": {"delivery_state": delivery, "delivery_confidence": 25,
                           "exhaustion_present": True},
        "po3": {"15m": {"phase": "manipulation", "manipulation_direction": "bullish",
                        "manipulation_direction_source": "sweep_semantics"}},
        "liquidity": {"3m": {"sweep_detected": True, "sweep_direction": "below_low",
                             "reclaim_detected": True, "nearest_buy_side_liquidity": 702.0}},
        "narrative_authority": {"narrative_direction": "bearish",   # NA suggested side (must be isolated)
                                "forbidden_trade_direction": "bullish",
                                "active_liquidity_draw": {"side": "buy_side", "level": 702.0}},
        "market_regime": {"regime_label": "range_rotation", "volatility_state": "unstable"},
        "council": {"report": {"dominant_position": "no"}},
        "timeframes": {"1m": {"candles": [{"open": 698.5, "high": 698.7, "low": 698.3, "close": 698.59}],
                              "last_candle": {"close": 698.59}}},
        "position_monitor": {"has_open_position": False},
    }


def _payload_minus_witness(bi):
    return json.dumps({k: v for k, v in bi.items() if k != "STRUCTURE_WITNESS"}, default=str).lower()


class T1_NoDirectionalBias(unittest.TestCase):
    def test_no_directional_bias_in_payload(self):
        blob = _payload_minus_witness(build_brain_input(_snap(), {"available": False}))
        self.assertNotIn("directional_bias", blob)
        self.assertNotIn('"bias"', blob)


class T2_NoBullBearStructureBias(unittest.TestCase):
    def test_no_structure_bias_terms(self):
        blob = _payload_minus_witness(build_brain_input(_snap(), {"available": False}))
        for term in ("bullish_bias", "bearish_bias", "market_bias", "narrative_bias", "bias_only"):
            self.assertNotIn(term, blob)


class T3_StructureOnlyInWitness(unittest.TestCase):
    def test_structure_isolated_and_nondirectional(self):
        bi = build_brain_input(_snap(struct_bias="bearish"), {"available": False})
        self.assertIn("STRUCTURE_WITNESS", bi)
        sw = bi["STRUCTURE_WITNESS"]
        self.assertIn("NOT DIRECTIONAL AUTHORITY", sw["_disclaimer"])
        # witness carries levels + event booleans only — no bias/direction
        for tf, d in sw.items():
            if tf == "_disclaimer":
                continue
            self.assertNotIn("bias", d)
            self.assertNotIn("state", d)
            self.assertIn("bos_event", d)
        # governance has no directional suggestion
        self.assertNotIn("narrative_authority_direction", bi["governance_context"])
        self.assertNotIn("council_dominant", bi["governance_context"])


class T4_TaintGuardRejects(unittest.TestCase):
    def test_guard_flags_contaminated_payload(self):
        bad = {"foo": {"directional_bias": "bearish"}, "STRUCTURE_WITNESS": {}}
        clean, paths = scan_payload_taint(bad)
        self.assertFalse(clean)
        self.assertIn("directional_bias", paths)

    def test_guard_passes_clean_payload(self):
        clean, paths = scan_payload_taint(build_brain_input(_snap(), {"available": False}))
        self.assertTrue(clean, paths)

    def test_witness_block_is_exempt(self):
        # a bias inside STRUCTURE_WITNESS would be exempt, but production puts none there
        ok, _ = scan_payload_taint({"STRUCTURE_WITNESS": {"15m": {"bias": "bearish"}}, "x": 1})
        self.assertTrue(ok)


class T5_PromptContract(unittest.TestCase):
    def test_prompt_states_structure_witness_only(self):
        p = BRAIN_SYSTEM_PROMPT
        self.assertIn("STRUCTURE SAFETY CONTRACT", p)
        self.assertIn("WITNESS ONLY", p)
        self.assertIn("cannot override DELIVERY", p)
        self.assertIn("TRUST THE CLEAN EVIDENCE", p)


class T6_1317CleanDelivery(unittest.TestCase):
    def test_1317_payload_has_clean_bullish_delivery_no_bearish_structure_summary(self):
        # 13:17: below_low sweep → bullish delivery; structure bias bearish must
        # NOT appear as narrative truth in the payload.
        bi = build_brain_input(_snap(struct_bias="bearish", delivery="bullish_delivery"),
                               {"available": False})
        self.assertEqual(bi["delivery"]["state"], "bullish_delivery")
        blob = _payload_minus_witness(bi)
        self.assertNotIn("bearish_continuation", blob)   # directional structure state gone
        self.assertNotIn('"bias"', blob)


class T_ContaminatedInputFallback(unittest.TestCase):
    def setUp(self):
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true"})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM"):
            os.environ.pop(k, None)

    def test_contaminated_input_skips_llm_and_logs(self):
        # force a contaminated payload by patching build_brain_input
        bad = {"timestamp": "t", "directional_bias": "bearish", "STRUCTURE_WITNESS": {}}
        with patch.object(nb, "build_brain_input", return_value=bad):
            with patch.object(nb, "_call_llm") as call:
                with self.assertLogs("ai_brain.narrative_brain", level="WARNING") as cm:
                    res = nb.run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        call.assert_not_called()                          # LLM never called on contaminated input
        self.assertEqual(res["source"], "contaminated_input")
        self.assertTrue(any("contaminated" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main(verbosity=2)
