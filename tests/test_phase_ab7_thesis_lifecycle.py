"""
Phase AB-7 — Persistent Thesis Lifecycle Engine tests.

Covers the 16 spec cases: a thesis survives one contrary candle, needs N
consecutive contrary scans (past min age) to invalidate, invalidates immediately
on hard material change, tolerates tool rotation, won't flip direction without
invalidation, decays confidence gradually, persists across scans + restart,
expires, exposes metadata, and only yields a trade when executable.
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.thesis_lifecycle import (  # noqa: E402
    ThesisLifecycleEngine, map_thesis_type,
    STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_EXECUTABLE,
    ACT_CREATE_NEW, ACT_INVALIDATE, ACT_EXPIRE, ACT_REPLACE_AFTER_INVALIDATION,
)


def cand(direction="bullish", phase="continuation", conf=70, opportunity=True,
         playbook="trend_continuation", tool="bullish_ifvg",
         invalidation=None, forbidden=None, contradictions=None):
    return {
        "owner": "ai_brain", "source": "llm", "direction": direction,
        "forbidden_direction": forbidden, "opportunity": opportunity,
        "opportunity_type": phase, "playbook_family": playbook,
        "tool_family": tool, "confidence": conf, "dominant_reasoning": "test",
        "brain_block": {"output": {"invalidation_level": invalidation,
                                   "contradiction_flags": contradictions or []}},
    }


class ThesisLifecycleTest(unittest.TestCase):

    def setUp(self):
        os.environ["THESIS_LIFECYCLE_MODE"] = "shadow"
        os.environ["THESIS_MIN_AGE_SCANS"] = "3"
        os.environ["THESIS_INVALIDATION_CONSECUTIVE"] = "2"
        os.environ.pop("THESIS_MAX_AGE_SCANS", None)
        os.environ["THESIS_CONFIDENCE_DECAY_STEP"] = "8"
        os.environ["THESIS_EXECUTABLE_CONFIDENCE"] = "70"

    def tearDown(self):
        for k in ("THESIS_LIFECYCLE_MODE", "THESIS_MIN_AGE_SCANS",
                  "THESIS_INVALIDATION_CONSECUTIVE", "THESIS_MAX_AGE_SCANS",
                  "THESIS_CONFIDENCE_DECAY_STEP", "THESIS_EXECUTABLE_CONFIDENCE",
                  "AI_BRAIN_DIR"):
            os.environ.pop(k, None)

    def _hold(self, eng, scans, **kw):
        out = None
        for _ in range(scans):
            out = eng.update(cand(**kw), {}, "2026-06-15T10:00:00")
        return out

    # 1 ─ bullish thesis survives one contrary candle
    def test_bullish_survives_one_contrary(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish")
        out = eng.update(cand(direction="bearish"), {}, "t")
        self.assertNotEqual(out["status"], STATUS_INVALIDATED)
        self.assertEqual(out["direction"], "bullish")

    # 2 ─ bearish thesis survives one bullish candle
    def test_bearish_survives_one_contrary(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bearish", playbook="liquidity_sweep_reversal", tool="bearish_ifvg")
        out = eng.update(cand(direction="bullish"), {}, "t")
        self.assertNotEqual(out["status"], STATUS_INVALIDATED)
        self.assertEqual(out["direction"], "bearish")

    # 3 ─ one no_playbook scan does not kill an active thesis
    def test_one_no_playbook_does_not_kill(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish")
        out = eng.update(cand(direction="neutral", opportunity=False, playbook="no_playbook", tool=None), {}, "t")
        self.assertNotEqual(out["status"], STATUS_INVALIDATED)
        self.assertEqual(out["direction"], "bullish")

    # 4 ─ N consecutive contrary scans (past min age) invalidate
    def test_consecutive_contrary_invalidates(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish")
        eng.update(cand(direction="bearish"), {}, "t")          # contrary 1 -> weaken
        out = eng.update(cand(direction="bearish"), {}, "t")    # contrary 2 -> invalidate(+replace)
        self.assertIn(out["action"], (ACT_INVALIDATE, ACT_REPLACE_AFTER_INVALIDATION))

    # 5 ─ hard material change (invalidation level breach) invalidates immediately
    def test_hard_invalidation_immediate(self):
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish", invalidation=100.0), {}, "t")   # young, age 1
        out = eng.update(cand(direction="neutral", opportunity=False, playbook="no_playbook", tool=None),
                         {"current_price": 99.0}, "t")
        self.assertEqual(out["action"], ACT_INVALIDATE)
        self.assertEqual(out["status"], STATUS_INVALIDATED)
        self.assertIsNone(eng.as_brain_thesis())   # nothing executable survives

    # 6 ─ tool rotation does not invalidate the direction thesis
    def test_tool_rotation_keeps_thesis(self):
        eng = ThesisLifecycleEngine(persist=False)
        first = eng.update(cand(direction="bearish", tool="bearish_ifvg"), {}, "t")
        out = eng.update(cand(direction="bearish", tool="bearish_breaker"), {}, "t")
        self.assertEqual(out["thesis_id"], first["thesis_id"])
        self.assertEqual(out["active_thesis"]["tool_family"], "bearish_breaker")
        self.assertNotEqual(out["status"], STATUS_INVALIDATED)

    # 7 ─ direction cannot flip without an invalidation first
    def test_direction_does_not_flip_without_invalidation(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish")
        out = eng.update(cand(direction="bearish"), {}, "t")   # single contrary
        self.assertEqual(out["direction"], "bullish")

    # 8 ─ confidence decays gradually, not instant collapse
    def test_confidence_decays_gradually(self):
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish", conf=70), {}, "t")
        out = eng.update(cand(direction="bearish"), {}, "t")
        c = out["active_thesis"]["confidence"]
        self.assertTrue(0 < c < 70, f"expected gradual decay, got {c}")

    # 9 ─ active thesis is loaded next scan (in-memory continuity)
    def test_active_thesis_persists_in_memory(self):
        eng = ThesisLifecycleEngine(persist=False)
        a = eng.update(cand(direction="bullish"), {}, "t")
        b = eng.update(cand(direction="bullish"), {}, "t")
        self.assertEqual(a["thesis_id"], b["thesis_id"])
        self.assertEqual(b["age_scans"], 2)

    # 10 ─ active thesis survives process restart (disk reload)
    def test_active_thesis_survives_restart(self):
        tmp = tempfile.mkdtemp()
        os.environ["AI_BRAIN_DIR"] = tmp
        try:
            e1 = ThesisLifecycleEngine(persist=True, symbol="QQQ")
            first = e1.update(cand(direction="bullish"), {}, "t")
            e1.update(cand(direction="bullish"), {}, "t")
            e2 = ThesisLifecycleEngine(persist=True, symbol="QQQ")   # "restart"
            out = e2.update(cand(direction="bullish"), {}, "t")
            self.assertEqual(out["thesis_id"], first["thesis_id"])
            self.assertGreaterEqual(out["age_scans"], 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # 11 ─ expired thesis does not survive forever
    def test_thesis_expires(self):
        os.environ["THESIS_MAX_AGE_SCANS"] = "3"
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish"), {}, "t")   # age 1
        eng.update(cand(direction="bullish"), {}, "t")   # age 2
        eng.update(cand(direction="bullish"), {}, "t")   # age 3
        out = eng.update(cand(direction="neutral", opportunity=False, playbook="no_playbook", tool=None), {}, "t")
        self.assertEqual(out["action"], ACT_EXPIRE)

    # 12 ─ R1 receives active_thesis metadata
    def test_metadata_exposed(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = eng.update(cand(direction="bullish"), {}, "t")
        for key in ("thesis_id", "direction", "status", "confidence", "age_scans"):
            self.assertIn(key, out)
        meta = eng.as_brain_thesis()
        self.assertEqual(meta["thesis_id"], out["thesis_id"])
        self.assertIn("thesis_age_scans", meta)

    # 13 ─ qualification can consume active thesis (produce_thesis-shaped output)
    def test_as_brain_thesis_shape(self):
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bearish", playbook="liquidity_sweep_reversal", tool="bearish_ifvg"), {}, "t")
        bt = eng.as_brain_thesis()
        for key in ("owner", "source", "direction", "forbidden_direction",
                    "opportunity", "opportunity_type", "playbook_family",
                    "tool_family", "confidence"):
            self.assertIn(key, bt)
        self.assertEqual(bt["owner"], "ai_brain")
        self.assertEqual(bt["direction"], "bearish")

    # 14 ─ playbook family is carried on the stabilized thesis
    def test_playbook_family_carried(self):
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish", playbook="trend_continuation"), {}, "t")
        self.assertEqual(eng.as_brain_thesis()["playbook_family"], "trend_continuation")

    # 15 ─ no trade from a non-trade observation thesis
    def test_no_trade_observation(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = eng.update(cand(direction="neutral", phase="exhaustion", opportunity=False,
                              playbook="no_playbook", tool=None), {}, "t")
        self.assertEqual(out["active_thesis"]["thesis_type"], "trend_exhaustion_monitoring")
        self.assertFalse(out["is_trade_thesis"])
        self.assertFalse(eng.as_brain_thesis()["opportunity"])

    # 16 ─ executable thesis is reachable
    def test_executable_reachable(self):
        os.environ["THESIS_MIN_AGE_SCANS"] = "2"
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish", conf=75), {}, "t")        # age 1, forming
        out = eng.update(cand(direction="bullish", conf=75), {}, "t")  # age 2 -> executable
        self.assertEqual(out["status"], STATUS_EXECUTABLE)
        self.assertTrue(eng.as_brain_thesis()["opportunity"])

    # extra ─ create + type mapping sanity
    def test_create_new_and_mapping(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = eng.update(cand(direction="bullish"), {}, "t")
        self.assertEqual(out["action"], ACT_CREATE_NEW)
        self.assertEqual(map_thesis_type("bearish", "manipulation", True), "bearish_reversal_attempt")
        self.assertEqual(map_thesis_type("neutral", "transition", False), "no_trade_observation")


if __name__ == "__main__":
    unittest.main()
