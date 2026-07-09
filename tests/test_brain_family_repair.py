"""
BRAIN-FAMILY-REPAIR (2026-07-09) — fix the playbook_family='none' sovereignty gap.

The 2026-07-09 sovereignty audit: the LLM emitted a directional narrative with
recommended_playbook_family='none' on 60/80 directional scans, violating the
AB-5C mandate and blocking sovereign_conversion (75% of directional reads could
never become sovereign). Three-part repair:
  1. directional_family_gap() detector (brain_validation)
  2. SOFT repair turn in narrative_brain (BRAIN_FAMILY_REPAIR=on): one LLM
     round-trip asking for the family the story implies. Guards: repaired output
     must keep the SAME direction, still pass hard validation, and close the
     gap — else the ORIGINAL output stands. Never falls back, never fabricates.
  3. Prompt salience: mandate inline in the schema lines + repair template.

Locks: detector truth table; default off = zero extra calls; gap triggers one
repair; adopted only when fixed; direction-flip rejected; failed repair keeps
original (NO fallback); no gap = no call; prompt carries the mandate; safety
files untouched.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.narrative_brain as nb                                    # noqa: E402
from ai_brain.narrative_brain import run_narrative_brain                 # noqa: E402
from ai_brain.stance_memory import StanceMemory                          # noqa: E402
from ai_brain.brain_validation import directional_family_gap             # noqa: E402
from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT, REPAIR_PROMPT_TEMPLATE  # noqa: E402

_FULL_REASON = ("Buy-side liquidity was swept and reclaimed; price is trading near "
                "the protected high at 702.5 while delivery is bearish; the draw "
                "remains sell-side liquidity at 699.6 in a manipulation phase; "
                "invalidation is a reclaim above 702.5; the bot must not take "
                "bullish positions.")


def _good(direction="bearish", pb="liquidity_sweep_reversal", tools=None):
    return {
        "market_story": "bearish delivery into a protected high",
        "narrative_direction": direction, "narrative_phase": "manipulation",
        "phase_confidence": 60, "delivery_interpretation": "bearish",
        "liquidity_interpretation": "sell-side draw",
        "protected_high_interpretation": "approaching",
        "protected_low_interpretation": "none", "active_draw": "sell_side@699.6",
        "allowed_direction": direction, "forbidden_direction": "bullish",
        "preferred_trade_family": pb, "preferred_playbooks": [pb],
        "preferred_tools": ["ifvg"], "invalidation_level": 702.5,
        "thesis_health": "n/a", "contradiction_flags": [], "warnings": [],
        "confidence_by_component": {"delivery": 25, "liquidity": 60, "structure": 40},
        "current_action": "avoid_bullish", "reason": "x",
        "must_not_do": ["do not trade bullish"], "protected_high_status": "approaching",
        "protected_low_status": "none", "dominant_reasoning": _FULL_REASON,
        "recommended_playbook_family": pb,
        "recommended_tool_family": tools if tools is not None else ["ifvg"],
    }


def _callrec(parsed, ok=True, reason=None):
    return {"parsed": parsed, "ok": ok, "model": "gpt-4o-mini", "prompt": "P",
            "user_content": "{}", "raw_response": "{...}",
            "usage": {"total_tokens": 2000}, "fallback_reason": reason,
            "is_repair": False}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                           "AI_BRAIN_DIR": self.tmp, "AI_RETRIEVAL_DIR": self.tmp})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR",
                  "AI_RETRIEVAL_DIR", "BRAIN_FAMILY_REPAIR"):
            os.environ.pop(k, None)

    def _run(self):
        return run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))


class TestDetector(unittest.TestCase):
    def test_directional_none_is_gap(self):
        gap, errs = directional_family_gap(_good(pb="none", tools=["none"]))
        self.assertTrue(gap)
        self.assertEqual(len(errs), 2)  # playbook + tool

    def test_directional_real_family_no_gap(self):
        gap, _ = directional_family_gap(_good())
        self.assertFalse(gap)

    def test_conflicted_none_is_legal(self):
        gap, _ = directional_family_gap(_good(direction="conflicted",
                                              pb="none", tools=["none"]))
        self.assertFalse(gap)

    def test_never_raises(self):
        self.assertEqual(directional_family_gap(None)[0], False)
        self.assertEqual(directional_family_gap({"narrative_direction": 42})[0], False)


class TestDefaultOff(_Base):
    def test_off_no_extra_call_and_none_passes_through(self):
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(_good(pb="none", tools=["none"]))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertEqual(calls["n"], 1)                 # no repair round-trip
        self.assertFalse(res["family_repair_attempted"])
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["output"]["recommended_playbook_family"], "none")


class TestSoftRepair(_Base):
    def setUp(self):
        super().setUp()
        os.environ["BRAIN_FAMILY_REPAIR"] = "on"

    def test_gap_triggers_one_repair_and_adopts_fix(self):
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            if repair is None:
                return _callrec(_good(pb="none", tools=["none"]))
            return _callrec(_good())                    # repaired: real family
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertEqual(calls["n"], 2)
        self.assertTrue(res["family_repair_attempted"])
        self.assertTrue(res["family_repair_fixed"])
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["output"]["recommended_playbook_family"],
                         "liquidity_sweep_reversal")

    def test_direction_flip_rejected_original_kept(self):
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_good(pb="none", tools=["none"]))
            return _callrec(_good(direction="bullish"))  # smuggled flip
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["family_repair_attempted"])
        self.assertFalse(res["family_repair_fixed"])
        self.assertEqual(res["source"], "llm")           # NO fallback
        self.assertEqual(res["output"]["narrative_direction"], "bearish")
        self.assertEqual(res["output"]["recommended_playbook_family"], "none")

    def test_failed_repair_call_keeps_original_no_fallback(self):
        def seq(bi, repair=None):
            if repair is None:
                return _callrec(_good(pb="none", tools=["none"]))
            return _callrec(None, ok=False, reason="timeout")
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertTrue(res["family_repair_attempted"])
        self.assertFalse(res["family_repair_fixed"])
        self.assertEqual(res["source"], "llm")           # healthy read preserved
        self.assertEqual(res["output"]["narrative_direction"], "bearish")

    def test_stubborn_none_keeps_original(self):
        def seq(bi, repair=None):
            return _callrec(_good(pb="none", tools=["none"]))
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertFalse(res["family_repair_fixed"])
        self.assertEqual(res["source"], "llm")

    def test_no_gap_no_extra_call(self):
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(_good())
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = self._run()
        self.assertEqual(calls["n"], 1)
        self.assertFalse(res["family_repair_attempted"])


class TestPromptMandate(unittest.TestCase):
    def test_schema_lines_carry_inline_mandate(self):
        self.assertIn("'none' is ONLY legal when narrative_direction is "
                      "conflicted/neutral", BRAIN_SYSTEM_PROMPT)

    def test_incomplete_answer_warning_present(self):
        self.assertIn("INCOMPLETE answer and will be sent back for repair",
                      BRAIN_SYSTEM_PROMPT)

    def test_repair_template_carries_family_requirement(self):
        self.assertIn("recommended_playbook_family MUST", REPAIR_PROMPT_TEMPLATE)
        self.assertIn("Do NOT", REPAIR_PROMPT_TEMPLATE)


class TestSafetyUntouched(unittest.TestCase):
    def test_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py"),
                           ("execution_gate", "execution_gate.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("BRAIN_FAMILY_REPAIR", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
