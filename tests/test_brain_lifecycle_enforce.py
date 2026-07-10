"""
BRAIN-LIFECYCLE-ENFORCE (2026-07-10) — promotion locks.

Replay ablation (recorded, 0708+0709) measured: brain-direction flicker HALVED
(70→41, 48→24), sovereignty 27→49 / 18→38, intents +7/+10, confirmed triggers
14→23, would_authorize UNCHANGED (0→0, 7→7 — no discipline erosion), 0 errors.
Launcher promotes THESIS_LIFECYCLE_MODE to enforce on that evidence.

Locks: mode ladder (default shadow; enforce detected); the stabilized thesis
renders in produce_thesis shape with source=ab7_active_thesis and persists the
family; sovereignty health-check accepts the stabilized source ONLY when the
scan's own candidate is llm-healthy (degraded LLM still fails closed — the
stabilized thesis may not launder a dead Brain).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.thesis_lifecycle import (      # noqa: E402
    ThesisLifecycleEngine, enforce_mode, _mode,
)
from ai_brain.ecu import healthy_directional_thesis, sovereign_conversion  # noqa: E402


def _candidate(direction="bearish", family="liquidity_sweep_reversal"):
    return {"owner": "ai_brain", "source": "llm", "direction": direction,
            "forbidden_direction": "bullish", "opportunity": True,
            "opportunity_type": "reversal", "playbook_family": family,
            "tool_family": ["ifvg"], "confidence": 70,
            "dominant_reasoning": "sweep and reclaim"}


def _evidence():
    return {"confidence": 70, "supports": True}


class TestModeLadder(unittest.TestCase):
    def test_default_is_shadow_not_enforce(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("THESIS_LIFECYCLE_MODE", None)
            self.assertEqual(_mode(), "shadow")
            self.assertFalse(enforce_mode())

    def test_enforce_detected(self):
        with patch.dict(os.environ, {"THESIS_LIFECYCLE_MODE": "enforce"}):
            self.assertTrue(enforce_mode())


class TestStabilizedThesisShape(unittest.TestCase):
    def _engine_with_thesis(self):
        eng = ThesisLifecycleEngine(symbol="QQQ", persist=False) \
            if "persist" in ThesisLifecycleEngine.__init__.__code__.co_varnames \
            else ThesisLifecycleEngine(symbol="QQQ")
        for i in range(4):   # feed consistent candidates to mature a thesis
            eng.update(_candidate(), _evidence(), f"2026-07-10T14:0{i}:00+00:00")
        return eng

    def test_as_brain_thesis_persists_family_in_canonical_shape(self):
        eng = self._engine_with_thesis()
        t = eng.as_brain_thesis()
        self.assertIsNotNone(t)
        self.assertEqual(t["source"], "ab7_active_thesis")
        self.assertEqual(t["direction"], "bearish")
        self.assertEqual(t["playbook_family"], "liquidity_sweep_reversal")
        self.assertTrue(t["opportunity"])

    def test_sovereignty_accepts_stabilized_only_with_healthy_candidate(self):
        eng = self._engine_with_thesis()
        stabilized = eng.as_brain_thesis()
        healthy_snap = {"brain_thesis": stabilized,
                        "candidate_thesis": _candidate()}      # llm-healthy scan
        ok, detail = healthy_directional_thesis(healthy_snap)
        self.assertTrue(ok, detail)
        self.assertTrue(sovereign_conversion(healthy_snap)[0])
        # a DEGRADED scan may not launder sovereignty through the stabilized thesis
        degraded_snap = {"brain_thesis": stabilized,
                         "candidate_thesis": dict(_candidate(),
                                                  source="llm_failed_fallback")}
        ok2, detail2 = healthy_directional_thesis(degraded_snap)
        self.assertFalse(ok2, detail2)


class TestLauncherPromotion(unittest.TestCase):
    def test_launcher_sets_enforce_with_evidence_note(self):
        with open("launch_paper_session_fc.ps1", encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("THESIS_LIFECYCLE_MODE", txt)
        self.assertIn('"enforce"', txt.split("THESIS_LIFECYCLE_MODE", 1)[1][:80])


if __name__ == "__main__":
    unittest.main()
