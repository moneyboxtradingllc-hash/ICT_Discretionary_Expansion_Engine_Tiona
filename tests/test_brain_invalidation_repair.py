"""
BRAIN-INVALIDATION-REPAIR (2026-07-10) — completeness: the Brain must name
where it is wrong.

Measured defect: invalidation_level null on 73% of directional reads —
blocking trade-path grading (419/896 rows) and forcing zone-edge fallback
stops. Same proven recipe as the family repair: inline prompt mandate + gap
detector + ONE soft repair turn with adoption guards (same direction, hard
validation, gap closed, AND the level on the CORRECT SIDE of price —
hallucinated stops refused). Original read stands on any failure; never falls
back. BRAIN_INVALIDATION_REPAIR default off = byte-identical.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.narrative_brain as nb                          # noqa: E402
from ai_brain.narrative_brain import run_narrative_brain       # noqa: E402
from ai_brain.stance_memory import StanceMemory                # noqa: E402
from ai_brain.brain_validation import (                        # noqa: E402
    directional_invalidation_gap, invalidation_side_ok,
)

_REASON = ("Buy-side liquidity was swept and reclaimed; price is trading near "
           "the protected high at 702.5 while delivery is bearish; the draw "
           "remains sell-side liquidity at 699.6 in a manipulation phase; "
           "invalidation is a reclaim above 702.5; the bot must not take "
           "bullish positions.")


def _out(direction="bearish", inval=None):
    return {
        "market_story": "bearish delivery into a protected high",
        "narrative_direction": direction, "narrative_phase": "manipulation",
        "phase_confidence": 60, "delivery_interpretation": "bearish",
        "liquidity_interpretation": "sell-side draw",
        "protected_high_interpretation": "approaching",
        "protected_low_interpretation": "none", "active_draw": "sell_side@699.6",
        "allowed_direction": direction, "forbidden_direction": "bullish",
        "preferred_trade_family": "reversal",
        "preferred_playbooks": ["liquidity_sweep_reversal"],
        "preferred_tools": ["ifvg"], "invalidation_level": inval,
        "thesis_health": "n/a", "contradiction_flags": [], "warnings": [],
        "confidence_by_component": {"delivery": 25, "liquidity": 60, "structure": 40},
        "current_action": "avoid_bullish", "reason": "x",
        "must_not_do": ["do not trade bullish"],
        "protected_high_status": "approaching", "protected_low_status": "none",
        "dominant_reasoning": _REASON,
        "recommended_playbook_family": "liquidity_sweep_reversal",
        "recommended_tool_family": ["ifvg"],
    }


def _callrec(parsed, ok=True, reason=None):
    return {"parsed": parsed, "ok": ok, "model": "gpt-4o-mini", "prompt": "P",
            "user_content": "{}", "raw_response": "{...}",
            "usage": {"total_tokens": 2000}, "fallback_reason": reason,
            "is_repair": False}


class TestDetectorAndSideGuard(unittest.TestCase):
    def test_directional_null_is_gap(self):
        gap, errs = directional_invalidation_gap(_out(inval=None))
        self.assertTrue(gap)
        self.assertIn("MUST name", errs[0])

    def test_directional_numeric_no_gap(self):
        self.assertFalse(directional_invalidation_gap(_out(inval=702.5))[0])

    def test_conflicted_null_is_legal(self):
        self.assertFalse(directional_invalidation_gap(
            _out(direction="conflicted", inval=None))[0])

    def test_side_guard(self):
        self.assertTrue(invalidation_side_ok("bearish", 702.5, 700.0))
        self.assertFalse(invalidation_side_ok("bearish", 698.0, 700.0))
        self.assertTrue(invalidation_side_ok("bullish", 698.0, 700.0))
        self.assertFalse(invalidation_side_ok("bullish", 702.5, 700.0))
        self.assertTrue(invalidation_side_ok("bearish", 702.5, None))  # unknown px
        self.assertFalse(invalidation_side_ok("bearish", "soon", 700.0))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                           "AI_BRAIN_DIR": self.tmp, "AI_RETRIEVAL_DIR": self.tmp})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR",
                  "AI_RETRIEVAL_DIR", "BRAIN_INVALIDATION_REPAIR"):
            os.environ.pop(k, None)

    def _run(self):
        # market.current_price rides the snapshot -> brain_input path; patching
        # _call_llm bypasses payload build, so pass a minimal snapshot and rely
        # on the side-guard's unknown-price acceptance in most tests.
        return run_narrative_brain({"timestamp": "t"}, "QQQ",
                                   StanceMemory(persist=False))


class TestSoftRepair(_Base):
    def test_default_off_null_passes_through(self):
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(_out(inval=None))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertEqual(calls["n"], 1)
        self.assertFalse(res["invalidation_repair_attempted"])
        self.assertIsNone(res["output"]["invalidation_level"])

    def test_on_gap_repaired_and_adopted(self):
        os.environ["BRAIN_INVALIDATION_REPAIR"] = "on"
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_out(inval=None))
            return _callrec(_out(inval=702.5))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["invalidation_repair_attempted"])
        self.assertTrue(res["invalidation_repair_fixed"])
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["output"]["invalidation_level"], 702.5)

    def test_direction_flip_rejected(self):
        os.environ["BRAIN_INVALIDATION_REPAIR"] = "on"
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_out(inval=None))
            return _callrec(_out(direction="bullish", inval=698.0))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertFalse(res["invalidation_repair_fixed"])
        self.assertEqual(res["output"]["narrative_direction"], "bearish")
        self.assertEqual(res["source"], "llm")           # never falls back

    def test_failed_repair_keeps_original(self):
        os.environ["BRAIN_INVALIDATION_REPAIR"] = "on"
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_out(inval=None))
            return _callrec(None, ok=False, reason="timeout")
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["invalidation_repair_attempted"])
        self.assertFalse(res["invalidation_repair_fixed"])
        self.assertEqual(res["source"], "llm")


class TestWrongSideRefused(unittest.TestCase):
    """The side guard integrated: a hallucinated bearish stop BELOW price is
    refused even though it closes the gap."""

    def test_wrong_side_level_rejected_via_guard(self):
        # unit-level: guard is what the adoption path consults
        self.assertFalse(invalidation_side_ok("bearish", 690.0, 700.0))
        self.assertTrue(invalidation_side_ok("bearish", 710.0, 700.0))


class TestPromptMandate(unittest.TestCase):
    def test_schema_line_carries_mandate(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT, REPAIR_PROMPT_TEMPLATE
        # system prompt: inline schema mandate (where small models attend)
        self.assertIn("REQUIRED when narrative_direction is bullish/bearish",
                      BRAIN_SYSTEM_PROMPT)
        self.assertIn("ABOVE price for bearish, BELOW for bullish",
                      BRAIN_SYSTEM_PROMPT)
        # repair template: the requirement the repair turn enforces
        self.assertIn("invalidation_level MUST be a", REPAIR_PROMPT_TEMPLATE)
        self.assertIn("INCOMPLETE and will be sent back", REPAIR_PROMPT_TEMPLATE)


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("execution_gate", "execution_gate.py")):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("BRAIN_INVALIDATION_REPAIR", fh.read(),
                                 f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
