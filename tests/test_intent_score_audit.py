"""
INTENT-SCORE-AUDIT (2026-07-10) — the last un-audited judge, demoted on evidence.

Replay evidence (0709, lifecycle-enforce): the intent-score gate would have
blocked 2/7 of the Brain's authorized trades — and the blocked pair
outcome-scored BETTER (0.0R) than the five it passed (−4.0R). Its penalties
(minimal risk tier, young setups) re-litigate authorized trades with
mechanical-era weights. INTENT_SCORE_MODE=observe_only demotes it to a
witness: verdict computed + recorded as would_have_blocked, never a veto.
Default enforce = byte-identical legacy.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from paper_execution.order_builder import meets_score_threshold  # noqa: E402


def _snap(score=62, quality="moderate_watch"):
    return {"intent_score": {"gated_score": score, "gated_quality": quality}}


class TestLegacyEnforceDefault(unittest.TestCase):
    def test_default_enforce_blocks_below_threshold(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INTENT_SCORE_MODE", None)
            ok, reason = meets_score_threshold(_snap(62))
        self.assertFalse(ok)
        self.assertIn("62 < minimum 70", reason)

    def test_default_enforce_passes_above_threshold(self):
        ok, reason = meets_score_threshold(_snap(85, "elite_intent"))
        self.assertTrue(ok)

    def test_quality_floor_still_enforced_in_enforce(self):
        ok, reason = meets_score_threshold(_snap(90, "moderate_watch"))
        self.assertFalse(ok)
        self.assertIn("below minimum", reason)


class TestObserveOnlyDemotion(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"INTENT_SCORE_MODE": "observe_only"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_below_threshold_passes_with_witness_record(self):
        s = _snap(62)
        ok, reason = meets_score_threshold(s)
        self.assertTrue(ok)                                # never vetoes
        self.assertIn("would_have_blocked", reason)
        self.assertTrue(s["intent_score"]["would_have_blocked"])
        self.assertIn("62 < minimum 70",
                      s["intent_score"]["would_have_blocked_reason"])
        self.assertEqual(s["intent_score"]["authority_mode"], "observe_only")

    def test_above_threshold_records_no_block(self):
        s = _snap(85, "elite_intent")
        ok, _ = meets_score_threshold(s)
        self.assertTrue(ok)
        self.assertFalse(s["intent_score"]["would_have_blocked"])

    def test_observe_only_never_blocks_any_input(self):
        for score, qual in ((0, "no_intent"), (40, "weak_watch"),
                            (69, "moderate_watch")):
            ok, _ = meets_score_threshold(_snap(score, qual))
            self.assertTrue(ok, f"{score}/{qual}")


class TestSafetyBoundary(unittest.TestCase):
    def test_mode_flag_only_in_this_gate(self):
        # the demotion touches the QUALITY gate only — risk sizing, stops,
        # and the broker path in the same file never read the mode flag
        with open(os.path.join("src", "paper_execution", "order_builder.py"),
                  encoding="utf-8") as fh:
            txt = fh.read()
        self.assertEqual(txt.count("INTENT_SCORE_MODE"), 2)  # docstring + check
        for f in (("risk", "risk_governor.py"), ("broker", "broker_adapter.py")):
            path = os.path.join("src", *f)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("INTENT_SCORE_MODE", fh.read())


if __name__ == "__main__":
    unittest.main()
