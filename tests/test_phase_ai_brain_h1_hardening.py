"""
Phase AI-BRAIN-H1 — LLM Brain hardening tests (T1-T13).

LLM mocked (no network). Proves normalization (enum/tool/forbidden/citation),
repair-detection (completeness/depth), explicit logged fallback, and June 11
key-point coherence.
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
from ai_brain.brain_schema import validate_brain_output
from ai_brain.brain_validation import (
    normalize_output, needs_repair, reasoning_depth_ok, PHASE_NORMALIZATION,
)

_FULL_REASON = ("Buy-side liquidity was swept and reclaimed; price is trading near "
                "the protected high at 702.5 while delivery is bearish; the draw "
                "remains sell-side liquidity at 699.6 in a manipulation phase; "
                "invalidation is a reclaim above 702.5; the bot must not take "
                "bullish positions.")


def _good(direction="bearish", phase="manipulation", reason=_FULL_REASON,
          tools=None, forbidden="bullish"):
    return {
        "market_story": "bearish delivery into a protected high",
        "narrative_direction": direction, "narrative_phase": phase,
        "phase_confidence": 60, "delivery_interpretation": "bearish",
        "liquidity_interpretation": "sell-side draw", "protected_high_interpretation": "approaching",
        "protected_low_interpretation": "none", "active_draw": "sell_side@699.6",
        "allowed_direction": direction, "forbidden_direction": forbidden,
        "preferred_trade_family": "reversal", "preferred_playbooks": ["liquidity_sweep_reversal"],
        "preferred_tools": ["bearish_ifvg"], "invalidation_level": 702.5,
        "thesis_health": "n/a", "contradiction_flags": [], "warnings": [],
        "confidence_by_component": {"delivery": 25, "liquidity": 60, "structure": 40},
        "current_action": "avoid_bullish", "reason": "x",
        "must_not_do": ["do not trade bullish"], "protected_high_status": "approaching",
        "protected_low_status": "none", "dominant_reasoning": reason,
        "recommended_playbook_family": "liquidity_sweep_reversal",
        "recommended_tool_family": tools if tools is not None else ["bearish_ifvg"],
    }


def _callrec(parsed, ok=True, reason=None):
    return {"parsed": parsed, "ok": ok, "model": "gpt-4o-mini", "prompt": "P",
            "user_content": "{}", "raw_response": "{...}",
            "usage": {"total_tokens": 2000}, "fallback_reason": reason, "is_repair": False}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                           "AI_BRAIN_DIR": self.tmp, "AI_RETRIEVAL_DIR": self.tmp})

    def tearDown(self):
        for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR"):
            os.environ.pop(k, None)


# ── T1 enum normalization ──────────────────────────────────────────────────────
class T1Enum(_Base):
    def test_synonym_normalized_not_fallback(self):
        with patch.object(nb, "_call_llm", side_effect=lambda bi, repair=None:
                          _callrec(_good(phase="early_expansion"))):
            res = run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        self.assertEqual(res["source"], "llm")          # not a fallback
        self.assertEqual(res["output"]["narrative_phase"], "continuation")
        self.assertTrue(any(n["field"] == "narrative_phase" for n in res["normalization_notes"]))

    def test_normalization_map_unit(self):
        out, notes = normalize_output(_good(phase="range_rotation"))
        self.assertEqual(out["narrative_phase"], "accumulation")
        self.assertEqual(PHASE_NORMALIZATION["no_trade"], "neutral")


# ── T2/T3 repair triggers ──────────────────────────────────────────────────────
class T2T3Repair(_Base):
    def test_missing_reasoning_triggers_repair(self):
        # empty dominant_reasoning is a genuine content gap → repair (tool/
        # playbook families are filled deterministically, not repaired).
        bad = _good(reason="")
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(bad) if repair is None else _callrec(_good())
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        self.assertEqual(calls["n"], 2)                  # repair call happened
        self.assertEqual(res["source"], "llm")
        self.assertTrue(res["repair_attempted"])

    def test_empty_tool_family_filled_not_repaired(self):
        # completable fields are normalized, NOT sent to repair
        bad = _good(tools=[]); bad["recommended_playbook_family"] = ""
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(bad)
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        self.assertEqual(calls["n"], 1)                  # no repair call
        self.assertEqual(res["source"], "llm")
        self.assertTrue(res["output"]["recommended_tool_family"])   # filled

    def test_shallow_reasoning_triggers_repair(self):
        shallow = _good(reason="Bearish manipulation.")
        calls = {"n": 0}
        def seq(bi, repair=None):
            calls["n"] += 1
            return _callrec(shallow) if repair is None else _callrec(_good())
        with patch.object(nb, "_call_llm", side_effect=seq):
            res = run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        self.assertEqual(calls["n"], 2)
        self.assertTrue(res["repair_attempted"])

    def test_reasoning_depth_unit(self):
        self.assertFalse(reasoning_depth_ok("Conflicted.")[0])
        self.assertFalse(reasoning_depth_ok("Bearish manipulation.")[0])
        self.assertTrue(reasoning_depth_ok(_FULL_REASON)[0])


# ── T4/T5/T6 tool coherence ─────────────────────────────────────────────────────
class T4T5T6Tools(_Base):
    def test_bearish_cannot_recommend_bullish_tools(self):
        out, notes = normalize_output(_good(direction="bearish", tools=["bullish_ifvg", "bullish_breaker"]))
        self.assertNotIn("bullish_ifvg", out["recommended_tool_family"])
        self.assertEqual(out["recommended_tool_family"], ["confirmation_required"])

    def test_bullish_cannot_recommend_bearish_tools(self):
        out, _ = normalize_output(_good(direction="bullish", forbidden="bearish",
                                        tools=["bearish_ifvg"]))
        self.assertEqual(out["recommended_tool_family"], ["confirmation_required"])

    def test_conflicted_uses_neutral_family(self):
        out, _ = normalize_output(_good(direction="conflicted", forbidden=None,
                                        tools=["bearish_ifvg"]))
        self.assertEqual(out["recommended_tool_family"], ["confirmation_required"])

    def test_forbidden_cannot_equal_own_direction(self):
        out, _ = normalize_output(_good(direction="bearish", forbidden="bearish"))
        self.assertEqual(out["forbidden_direction"], "bullish")


# ── T7 citation sanity ──────────────────────────────────────────────────────────
class T7Citations(_Base):
    def test_unsupported_analog_stripped(self):
        g = _good(reason=_FULL_REASON + " As in analog 20260101T120000 which fell.")
        out, notes = normalize_output(g, memory_matches=[{"timestamp": "20260611T103000"}])
        self.assertIn("[unverified-analog]", out["dominant_reasoning"])
        self.assertTrue(any("unsupported_analogs" in str(n.get("reason")) for n in notes))

    def test_supported_analog_kept(self):
        g = _good(reason=_FULL_REASON + " Similar to 20260611T103000.")
        out, notes = normalize_output(g, memory_matches=[{"timestamp": "20260611T103000"}])
        self.assertIn("20260611T103000", out["dominant_reasoning"])


# ── T8/T9 logging + explicit fallback ──────────────────────────────────────────
class T8T9Logging(_Base):
    def test_repair_incomplete_explicit_fallback_logged(self):
        bad = _good(reason="Unclear.")          # always shallow
        with patch.object(nb, "_call_llm", side_effect=lambda bi, repair=None: _callrec(bad)):
            with self.assertLogs("ai_brain.narrative_brain", level="WARNING") as cm:
                res = run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        self.assertEqual(res["source"], "llm_failed_fallback")
        self.assertTrue(any("repair incomplete" in m for m in cm.output))
        self.assertIn("repair_incomplete", res["fallback_reason"])

    def test_normalization_notes_persisted(self):
        import json, glob
        with patch.object(nb, "_call_llm", side_effect=lambda bi, repair=None:
                          _callrec(_good(phase="expansion"))):
            run_narrative_brain({"timestamp": "t"}, "QQQ", StanceMemory(persist=False))
        rec = json.load(open(glob.glob(os.path.join(self.tmp, "*_QQQ.json"))[0], encoding="utf-8"))
        self.assertIn("normalization_notes", rec)
        self.assertIn("repair_attempted", rec)
        self.assertIn("repair_errors", rec)


# ── T10/T11 June 11 coherence (mocked good outputs) ─────────────────────────────
class T10T11June11(_Base):
    def test_1029_full_bearish_accepted(self):
        with patch.object(nb, "_call_llm", side_effect=lambda bi, repair=None: _callrec(_good("bearish"))):
            res = run_narrative_brain({"timestamp": "20260611T142800Z"}, "QQQ", StanceMemory(persist=False))
        o = res["output"]
        self.assertEqual(res["source"], "llm")
        self.assertEqual(o["narrative_direction"], "bearish")
        self.assertNotEqual(o["recommended_tool_family"], ["bullish_ifvg"])  # coherent
        self.assertTrue(reasoning_depth_ok(o["dominant_reasoning"])[0])
        ok, _ = validate_brain_output(o); self.assertTrue(ok)

    def test_1317_no_short_coherent(self):
        bull = _good("bullish", forbidden="bearish", tools=["bullish_ifvg"])
        bull["dominant_reasoning"] = ("Sell-side liquidity was swept below the low and "
            "reclaimed; price trades near 702 targeting buy-side liquidity; delivery is "
            "bullish in a reversal phase; invalidation is a close back below the low; the "
            "bot must not commit to bearish trades.")
        with patch.object(nb, "_call_llm", side_effect=lambda bi, repair=None: _callrec(bull)):
            res = run_narrative_brain({"timestamp": "20260611T171700Z"}, "QQQ", StanceMemory(persist=False))
        o = res["output"]
        self.assertNotEqual(o["narrative_direction"], "bearish")
        self.assertEqual(o["forbidden_direction"], "bearish")


if __name__ == "__main__":
    unittest.main(verbosity=2)
