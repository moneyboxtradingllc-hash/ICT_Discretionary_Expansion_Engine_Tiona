"""
BRAIN-RELIABILITY (2026-07-09, Mission 3 organism examination).

R1 — shallow prose must not beat AI authority: when the ONLY residual repair
errors are shallow_reasoning (prose depth) and the read carries a real
direction, phase, and non-empty reasoning, the LLM output is KEPT with a
warning instead of being replaced by the deterministic fallback (an authority
inversion found on 12 records + dozens of live-replay scans). Content gaps
(empty direction/phase/reasoning) still fall back. Default off = legacy.

R2 — BRAIN_JSON_MODE=on requests OpenAI structured JSON output, eliminating
the JSONDecodeError failure class (2 in the audited records + live replays).
Default off = legacy request shape.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.narrative_brain as nb                       # noqa: E402
from ai_brain.narrative_brain import run_narrative_brain    # noqa: E402
from ai_brain.stance_memory import StanceMemory             # noqa: E402

_SHALLOW = "Bearish delivery continues lower today."   # < depth threshold


def _out(reason=_SHALLOW, direction="bearish", phase="manipulation"):
    return {
        "market_story": "bearish delivery into a protected high",
        "narrative_direction": direction, "narrative_phase": phase,
        "phase_confidence": 60, "delivery_interpretation": "bearish",
        "liquidity_interpretation": "sell-side draw",
        "protected_high_interpretation": "approaching",
        "protected_low_interpretation": "none", "active_draw": "sell_side@699.6",
        "allowed_direction": direction, "forbidden_direction": "bullish",
        "preferred_trade_family": "reversal",
        "preferred_playbooks": ["liquidity_sweep_reversal"],
        "preferred_tools": ["ifvg"], "invalidation_level": 702.5,
        "thesis_health": "n/a", "contradiction_flags": [], "warnings": [],
        "confidence_by_component": {"delivery": 25, "liquidity": 60, "structure": 40},
        "current_action": "avoid_bullish", "reason": "x",
        "must_not_do": ["do not trade bullish"],
        "protected_high_status": "approaching", "protected_low_status": "none",
        "dominant_reasoning": reason,
        "recommended_playbook_family": "liquidity_sweep_reversal",
        "recommended_tool_family": ["ifvg"],
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
                  "AI_RETRIEVAL_DIR", "BRAIN_KEEP_SHALLOW_REASONING",
                  "BRAIN_JSON_MODE"):
            os.environ.pop(k, None)

    def _run(self):
        return run_narrative_brain({"timestamp": "t"}, "QQQ",
                                   StanceMemory(persist=False))


class TestShallowKept(_Base):
    def test_default_off_shallow_still_falls_back(self):
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out())):
            res = self._run()
        self.assertEqual(res["source"], "llm_failed_fallback")   # legacy

    def test_on_shallow_directional_read_is_kept(self):
        os.environ["BRAIN_KEEP_SHALLOW_REASONING"] = "true"
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out())):
            res = self._run()
        self.assertEqual(res["source"], "llm")                   # AI keeps authority
        self.assertTrue(res["shallow_reasoning_kept"])
        self.assertEqual(res["output"]["narrative_direction"], "bearish")
        self.assertTrue(any("shallow_reasoning_kept" in w
                            for w in res["output"].get("warnings", [])))

    def test_on_empty_reasoning_still_falls_back(self):
        # a CONTENT gap (empty reasoning) is a real failure — never kept
        os.environ["BRAIN_KEEP_SHALLOW_REASONING"] = "true"
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out(reason=""))):
            res = self._run()
        self.assertEqual(res["source"], "llm_failed_fallback")
        self.assertFalse(res["shallow_reasoning_kept"])

    def test_on_deep_reasoning_unaffected(self):
        os.environ["BRAIN_KEEP_SHALLOW_REASONING"] = "true"
        deep = ("Buy-side liquidity was swept and reclaimed; price is trading "
                "near the protected high at 702.5 while delivery is bearish; "
                "the draw remains sell-side at 699.6 in a manipulation phase; "
                "invalidation is a reclaim above 702.5; the bot must not take "
                "bullish positions.")
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(_out(reason=deep))):
            res = self._run()
        self.assertEqual(res["source"], "llm")
        self.assertFalse(res["shallow_reasoning_kept"])          # no keep needed


class TestJsonMode(_Base):
    def _fake_openai(self, captured):
        class _Msg:  # minimal OpenAI response shape
            content = '{"narrative_direction": "bearish"}'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]
            usage = None

        class _Completions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _Resp()

        class _Chat:
            completions = _Completions()

        class _Client:
            def __init__(self, **_kw):
                self.chat = _Chat()

        class _OpenAIModule:
            OpenAI = _Client

        return _OpenAIModule()

    def test_json_mode_off_by_default(self):
        captured = {}
        import ai_layer.ai_api_adapter as adapter
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}), \
             patch.object(adapter, "_openai", self._fake_openai(captured)), \
             patch.object(adapter, "_OPENAI_AVAILABLE", True):
            nb._call_llm({"timestamp": "t"})
        self.assertNotIn("response_format", captured)

    def test_json_mode_on_requests_structured_output(self):
        captured = {}
        import ai_layer.ai_api_adapter as adapter
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k",
                                     "BRAIN_JSON_MODE": "on"}), \
             patch.object(adapter, "_openai", self._fake_openai(captured)), \
             patch.object(adapter, "_OPENAI_AVAILABLE", True):
            nb._call_llm({"timestamp": "t"})
        self.assertEqual(captured.get("response_format"), {"type": "json_object"})


class TestPhaseSynonymTolerance(_Base):
    """BRAIN-RELIABILITY-3 — validate-before-normalize seam. The core validator
    rejected phases the normalizer maps deterministically one step later
    ('manipulation_to_distribution'->distribution, 'mixed'->conflicted),
    destroying healthy reads. Tolerance accepts KNOWN synonyms only."""

    def test_default_off_synonym_rejected(self):
        from ai_brain.brain_schema import validate_llm_core
        ok, reason = validate_llm_core(_out(phase="manipulation_to_distribution"))
        self.assertFalse(ok)
        self.assertIn("manipulation_to_distribution", reason)

    def test_on_known_synonym_accepted(self):
        from ai_brain.brain_schema import validate_llm_core
        with patch.dict(os.environ, {"BRAIN_PHASE_SYNONYM_TOLERANCE": "on"}):
            for phase in ("manipulation_to_distribution", "mixed",
                          "early_expansion", "range_rotation"):
                ok, reason = validate_llm_core(_out(phase=phase))
                self.assertTrue(ok, f"{phase}: {reason}")

    def test_on_unknown_phase_still_rejected(self):
        from ai_brain.brain_schema import validate_llm_core
        with patch.dict(os.environ, {"BRAIN_PHASE_SYNONYM_TOLERANCE": "on"}):
            ok, _ = validate_llm_core(_out(phase="sideways_voodoo"))
            self.assertFalse(ok)

    def test_end_to_end_synonym_survives_and_normalizes(self):
        # a synonym-phase LLM response now reaches the normalizer (source=llm)
        # and is mapped to the canonical phase instead of falling back
        deep = ("Buy-side liquidity was swept and reclaimed; price is trading "
                "near the protected high at 702.5 while delivery is bearish; "
                "the draw remains sell-side at 699.6 in a manipulation phase; "
                "invalidation is a reclaim above 702.5; the bot must not take "
                "bullish positions.")
        os.environ["BRAIN_PHASE_SYNONYM_TOLERANCE"] = "on"
        out = _out(reason=deep, phase="manipulation_to_distribution")
        with patch.object(nb, "_call_llm",
                          side_effect=lambda bi, repair=None: _callrec(out)):
            res = self._run()
        os.environ.pop("BRAIN_PHASE_SYNONYM_TOLERANCE", None)
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["output"]["narrative_phase"], "distribution")


if __name__ == "__main__":
    unittest.main()
