"""
Phase AB-7.2 — Playbook Lifecycle Integration tests.

AB-7.1 persisted the thesis but overwrote the playbook with the candidate every
scan, so the brain's literal "none" (emitted ~66% of the time) wiped the active
playbook. These tests pin the AB-7.2 contract: the playbook persists WITH the
thesis, carries its own lifecycle, survives single no_playbook flicker, rotates
only on sustained alternative evidence, and conflicted/neutral theses decay
faster than directional ones.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.thesis_lifecycle import (  # noqa: E402
    ThesisLifecycleEngine, _norm_playbook,
    STATUS_FORMING, STATUS_ACTIVE, STATUS_EXECUTABLE,
    STATUS_WEAKENING, STATUS_THREATENED, STATUS_INVALIDATED,
    ACT_EXPIRE,
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


class PlaybookLifecycleTest(unittest.TestCase):

    def setUp(self):
        os.environ["THESIS_LIFECYCLE_MODE"] = "shadow"
        os.environ["THESIS_MIN_AGE_SCANS"] = "3"
        os.environ["THESIS_INVALIDATION_CONSECUTIVE"] = "2"
        os.environ.pop("THESIS_MAX_AGE_SCANS", None)
        os.environ["THESIS_CONFIDENCE_DECAY_STEP"] = "8"
        os.environ["THESIS_EXECUTABLE_CONFIDENCE"] = "70"
        os.environ["PLAYBOOK_ABSENT_INVALIDATION"] = "4"
        os.environ["PLAYBOOK_SWITCH_CONSECUTIVE"] = "2"
        os.environ["THESIS_MAX_AGE_NONDIRECTIONAL"] = "12"

    def tearDown(self):
        for k in ("THESIS_LIFECYCLE_MODE", "THESIS_MIN_AGE_SCANS",
                  "THESIS_INVALIDATION_CONSECUTIVE", "THESIS_MAX_AGE_SCANS",
                  "THESIS_CONFIDENCE_DECAY_STEP", "THESIS_EXECUTABLE_CONFIDENCE",
                  "PLAYBOOK_ABSENT_INVALIDATION", "PLAYBOOK_SWITCH_CONSECUTIVE",
                  "THESIS_MAX_AGE_NONDIRECTIONAL", "AI_BRAIN_DIR"):
            os.environ.pop(k, None)

    def _hold(self, eng, scans, **kw):
        out = None
        for _ in range(scans):
            out = eng.update(cand(**kw), {}, "2026-06-15T10:00:00")
        return out

    # ── normalization (the actual AB-7.1 bug) ──────────────────────────────────
    def test_norm_playbook_treats_none_string_as_absent(self):
        self.assertIsNone(_norm_playbook("none"))
        self.assertIsNone(_norm_playbook(""))
        self.assertIsNone(_norm_playbook("no_playbook"))
        self.assertIsNone(_norm_playbook(None))
        self.assertIsNone(_norm_playbook([]))
        self.assertEqual(_norm_playbook("trend_continuation"), "trend_continuation")
        self.assertEqual(_norm_playbook(["liquidity_sweep_reversal"]), "liquidity_sweep_reversal")

    # ── Rule 1 — one no_playbook scan does NOT wipe the playbook ────────────────
    def test_single_no_playbook_holds_playbook(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation")
        out = eng.update(cand(direction="bullish", playbook="none"), {}, "t")
        self.assertEqual(out["playbook_family"], "trend_continuation")
        self.assertNotEqual(out["playbook_status"], STATUS_INVALIDATED)
        self.assertEqual(out["playbook_status"], STATUS_WEAKENING)
        # the exact end-to-end symptom: stabilized thesis still carries the playbook
        self.assertEqual(eng.as_brain_thesis()["playbook_family"], "trend_continuation")

    # ── the AB-7.1 flicker sequence: continuation -> none -> continuation ───────
    def test_continuation_playbook_survives_flicker(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 3, direction="bullish", playbook="trend_continuation")
        seq = ["none", "trend_continuation", "none", "none", "trend_continuation"]
        for pb in seq:
            out = eng.update(cand(direction="bullish", playbook=pb), {}, "t")
            self.assertEqual(out["playbook_family"], "trend_continuation",
                             f"playbook dropped on '{pb}' scan")

    # ── Rule 3 — repeated absence eventually retires the playbook ───────────────
    def test_repeated_absence_invalidates_playbook(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation")
        out = None
        for _ in range(4):   # PLAYBOOK_ABSENT_INVALIDATION = 4
            out = eng.update(cand(direction="bullish", playbook="none"), {}, "t")
        self.assertEqual(out["playbook_status"], STATUS_INVALIDATED)
        self.assertIsNone(out["playbook_family"])
        # the thesis itself is still alive and bullish (direction outlives playbook)
        self.assertEqual(out["direction"], "bullish")
        self.assertNotEqual(out["status"], STATUS_INVALIDATED)

    # ── Rule 2/hardness — playbook rotates only on a SUSTAINED alternative ──────
    def test_single_different_playbook_does_not_rotate(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation")
        out = eng.update(cand(direction="bullish", playbook="liquidity_sweep_reversal"), {}, "t")
        self.assertEqual(out["playbook_family"], "trend_continuation")
        self.assertEqual(out["playbook_status"], STATUS_THREATENED)

    def test_sustained_different_playbook_rotates(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation")
        eng.update(cand(direction="bullish", playbook="liquidity_sweep_reversal"), {}, "t")   # pending 1
        out = eng.update(cand(direction="bullish", playbook="liquidity_sweep_reversal"), {}, "t")  # pending 2 -> rotate
        self.assertEqual(out["playbook_family"], "liquidity_sweep_reversal")
        self.assertEqual(out["playbook_status"], STATUS_FORMING)

    # ── tool rotates freely without disturbing the playbook ────────────────────
    def test_tool_rotation_does_not_change_playbook(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation", tool="bullish_ifvg")
        out = eng.update(cand(direction="bullish", playbook="trend_continuation", tool="bullish_breaker"), {}, "t")
        self.assertEqual(out["active_thesis"]["tool_family"], "bullish_breaker")
        self.assertEqual(out["playbook_family"], "trend_continuation")

    # ── an opposing-direction scan never rotates the playbook to the other side ─
    def test_opposing_scan_does_not_rotate_playbook(self):
        eng = ThesisLifecycleEngine(persist=False)
        self._hold(eng, 4, direction="bullish", playbook="trend_continuation")
        out = eng.update(cand(direction="bearish", playbook="distribution"), {}, "t")  # single opposing
        self.assertEqual(out["direction"], "bullish")
        self.assertEqual(out["playbook_family"], "trend_continuation")
        self.assertEqual(out["playbook_status"], STATUS_THREATENED)

    # ── playbook status progresses with age / thesis state ─────────────────────
    def test_playbook_status_progresses_to_active(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = None
        for _ in range(3):   # min_age = 3, conf 60 keeps thesis ACTIVE (not executable)
            out = eng.update(cand(direction="bullish", conf=60, playbook="trend_continuation"), {}, "t")
        self.assertEqual(out["playbook_status"], STATUS_ACTIVE)

    def test_playbook_status_reaches_executable(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = None
        for _ in range(3):
            out = eng.update(cand(direction="bullish", conf=75, playbook="trend_continuation"), {}, "t")
        self.assertEqual(out["status"], STATUS_EXECUTABLE)
        self.assertEqual(out["playbook_status"], STATUS_EXECUTABLE)

    # ── conflicted/neutral theses decay faster than directional ────────────────
    def test_nondirectional_thesis_expires_faster(self):
        os.environ["THESIS_MAX_AGE_NONDIRECTIONAL"] = "3"
        eng = ThesisLifecycleEngine(persist=False)
        actions = []
        for _ in range(5):
            out = eng.update(cand(direction="neutral", phase="transition",
                                  opportunity=False, playbook="none", tool=None), {}, "t")
            actions.append(out["action"])
        self.assertIn(ACT_EXPIRE, actions)

    def test_directional_thesis_not_subject_to_tight_cap(self):
        os.environ["THESIS_MAX_AGE_NONDIRECTIONAL"] = "3"
        eng = ThesisLifecycleEngine(persist=False)
        out = None
        for _ in range(6):
            out = eng.update(cand(direction="bullish", playbook="trend_continuation"), {}, "t")
        self.assertNotEqual(out["action"], ACT_EXPIRE)
        self.assertEqual(out["direction"], "bullish")

    # ── R1 / qualification consumption surface ─────────────────────────────────
    def test_exposed_fields_present(self):
        eng = ThesisLifecycleEngine(persist=False)
        out = eng.update(cand(direction="bullish", playbook="trend_continuation"), {}, "t")
        for key in ("playbook_status", "playbook_age_scans", "confidence_trend"):
            self.assertIn(key, out)
        bt = eng.as_brain_thesis()
        for key in ("playbook_status", "playbook_age_scans", "confidence_trend"):
            self.assertIn(key, bt)

    def test_confidence_trend(self):
        eng = ThesisLifecycleEngine(persist=False)
        eng.update(cand(direction="bullish", conf=55), {}, "t")
        out = eng.update(cand(direction="bullish", conf=90), {}, "t")  # strengthening
        self.assertEqual(out["confidence_trend"], "rising")
        out = eng.update(cand(direction="bearish"), {}, "t")           # contrary -> decay
        self.assertEqual(out["confidence_trend"], "falling")


if __name__ == "__main__":
    unittest.main()
