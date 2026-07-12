"""
BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12) — initial-read guard tests.

The #9 watch item, measured 4x worse than estimated: 83/394 (21.1%) of
directional LLM reads with a NUMERIC invalidation had it on the WRONG side of
price (bullish theses "dying" above price — target named as stop). Repair
adoptions were side-checked; initial reads were not. When
BRAIN_INVALIDATION_SIDE_CHECK=on the poisoned level is STRIPPED (recorded in
telemetry) and becomes an ordinary invalidation gap for the existing guarded
repair. Direction never touched; unknown price never fires; default off =
byte-identical.
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
    wrong_side_initial_invalidation,
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


def _callrec(parsed, ok=True):
    return {"parsed": parsed, "ok": ok, "model": "gpt-4o-mini", "prompt": "P",
            "user_content": "{}", "raw_response": "{...}",
            "usage": {"total_tokens": 2000}, "fallback_reason": None,
            "is_repair": False}


class TestDetector(unittest.TestCase):
    def test_wrong_sides_fire(self):
        # bearish must die ABOVE price; a level below (or AT) price is poison
        w, errs = wrong_side_initial_invalidation(_out(inval=698.0), 700.0)
        self.assertTrue(w)
        self.assertIn("wrong_side_invalidation", errs[0])
        self.assertTrue(wrong_side_initial_invalidation(
            _out(direction="bullish", inval=702.5), 700.0)[0])
        self.assertTrue(wrong_side_initial_invalidation(   # inv == px degenerate
            _out(inval=700.0), 700.0)[0])

    def test_correct_sides_pass(self):
        self.assertFalse(wrong_side_initial_invalidation(
            _out(inval=702.5), 700.0)[0])
        self.assertFalse(wrong_side_initial_invalidation(
            _out(direction="bullish", inval=698.0), 700.0)[0])

    def test_unknown_price_never_fires(self):
        self.assertFalse(wrong_side_initial_invalidation(
            _out(inval=698.0), None)[0])

    def test_non_numeric_is_gap_detectors_case(self):
        self.assertFalse(wrong_side_initial_invalidation(
            _out(inval=None), 700.0)[0])
        self.assertFalse(wrong_side_initial_invalidation(
            _out(inval="soon"), 700.0)[0])
        self.assertFalse(wrong_side_initial_invalidation(
            _out(inval=True), 700.0)[0])

    def test_non_directional_never_fires(self):
        self.assertFalse(wrong_side_initial_invalidation(
            _out(direction="conflicted", inval=698.0), 700.0)[0])


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                           "AI_BRAIN_DIR": self.tmp, "AI_RETRIEVAL_DIR": self.tmp})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR",
                  "AI_RETRIEVAL_DIR", "BRAIN_INVALIDATION_REPAIR",
                  "BRAIN_INVALIDATION_SIDE_CHECK"):
            os.environ.pop(k, None)

    def _run(self):
        # a 1m last_candle delivers market.current_price=700.0 to brain_input
        snap = {"timestamp": "t", "timeframes": {"1m": {
            "last_candle": {"open": 700.1, "high": 700.4, "low": 699.8,
                            "close": 700.0}}}}
        return run_narrative_brain(snap, "QQQ", StanceMemory(persist=False))


class TestDefaultOff(_Base):
    def test_wrong_side_passes_through_when_off(self):
        # legacy behavior preserved byte-for-byte: the poisoned level survives
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out(inval=698.0))):
            res = self._run()
        self.assertEqual(res["output"]["invalidation_level"], 698.0)
        self.assertFalse(res["invalidation_side_check_flagged"])
        self.assertIsNone(res["invalidation_side_check_stripped"])


class TestSideCheckOn(_Base):
    def setUp(self):
        super().setUp()
        os.environ["BRAIN_INVALIDATION_SIDE_CHECK"] = "on"

    def test_wrong_side_stripped_no_repair_flag(self):
        # repair OFF: poisoned level removed -> honest null (a gap), never a
        # poisoned stop; direction untouched; telemetry carries the original
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out(inval=698.0))):
            res = self._run()
        self.assertIsNone(res["output"]["invalidation_level"])
        self.assertTrue(res["invalidation_side_check_flagged"])
        self.assertEqual(res["invalidation_side_check_stripped"], 698.0)
        self.assertEqual(res["output"]["narrative_direction"], "bearish")
        self.assertFalse(res["invalidation_repair_attempted"])
        self.assertEqual(res["source"], "llm")

    def test_correct_side_untouched(self):
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out(inval=702.5))):
            res = self._run()
        self.assertEqual(res["output"]["invalidation_level"], 702.5)
        self.assertFalse(res["invalidation_side_check_flagged"])

    def test_strip_routes_into_guarded_repair(self):
        # repair ON: the strip becomes a gap; the repair turn is told WHY
        # (wrong_side context) and its correct-side answer is adopted
        os.environ["BRAIN_INVALIDATION_REPAIR"] = "on"
        seen = {}
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_out(inval=698.0))
            seen["errors"] = repair["errors"]
            return _callrec(_out(inval=702.5))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["invalidation_side_check_flagged"])
        self.assertTrue(res["invalidation_repair_attempted"])
        self.assertTrue(res["invalidation_repair_fixed"])
        self.assertEqual(res["output"]["invalidation_level"], 702.5)
        self.assertTrue(any("wrong_side_invalidation" in e
                            for e in seen["errors"]))

    def test_repair_returning_wrong_side_again_refused(self):
        os.environ["BRAIN_INVALIDATION_REPAIR"] = "on"
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_out(inval=698.0))
            return _callrec(_out(inval=697.0))   # still poisoned
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["invalidation_repair_attempted"])
        self.assertFalse(res["invalidation_repair_fixed"])
        self.assertIsNone(res["output"]["invalidation_level"])   # honest null


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for parts in (("risk", "risk_governor.py"),
                      ("paper_execution", "order_builder.py"),
                      ("paper_execution", "paper_broker.py"),
                      ("execution_gate", "execution_gate.py")):
            with open(os.path.join(src, *parts), encoding="utf-8") as fh:
                self.assertNotIn("BRAIN_INVALIDATION_SIDE_CHECK", fh.read())


if __name__ == "__main__":
    unittest.main()
