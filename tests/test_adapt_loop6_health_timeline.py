"""
ADAPT-LOOP-6 — Evolution Timeline + Organism Health locks (2026-07-10).

Timeline: schema keyed to evidence (bad verdict raises; missing evidence_ref
forces PENDING visibly); append/load round trip; rendering gives REJECTED and
NO CHANGE the same prominence as wins; git spine parses the one-line mission
commits. Health: every metric carries its own n; missing sources report
no_data (silence is never health); descriptive only.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.evolution_timeline import (        # noqa: E402
    normalize_milestone, add_milestone, load_milestones, render_markdown,
    git_spine, VERDICTS,
)
from replay_validation.organism_health import (           # noqa: E402
    brain_trend, governance, posture_drift,
)


class TestMilestoneSchema(unittest.TestCase):
    def test_bad_verdict_raises(self):
        with self.assertRaises(ValueError):
            normalize_milestone({"date": "20260710", "mission": "X",
                                 "verdict": "amazing"})

    def test_missing_evidence_forces_pending_visibly(self):
        m = normalize_milestone({"date": "20260710", "mission": "X",
                                 "change": "c", "verdict": "validated",
                                 "evidence_ref": None})
        self.assertEqual(m["verdict"], "pending")
        self.assertIn("forced_pending", m)

    def test_all_verdicts_accepted_with_evidence(self):
        for v in VERDICTS:
            m = normalize_milestone({"date": "20260710", "mission": "X",
                                     "change": "c", "verdict": v,
                                     "evidence_ref": "r.json"})
            self.assertEqual(m["verdict"], v)

    def test_needs_date_and_mission(self):
        with self.assertRaises(ValueError):
            normalize_milestone({"mission": "X"})


class TestTimelineRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_append_load_render(self):
        add_milestone({"date": "20260709", "mission": "WIN", "change": "w",
                       "metric_before": "0", "metric_after": "7",
                       "evidence_ref": "suite.json", "verdict": "validated"},
                      base_dir=self.tmp)
        add_milestone({"date": "20260710", "mission": "CONTROL", "change": "c",
                       "evidence_ref": "lab.json", "verdict": "rejected"},
                      base_dir=self.tmp)
        add_milestone({"date": "20260708", "mission": "STABILITY", "change": "s",
                       "evidence_ref": "suite.json", "verdict": "no_change"},
                      base_dir=self.tmp)
        add_milestone({"date": "20260710", "mission": "ARMED", "change": "a",
                       "verdict": "pending"}, base_dir=self.tmp)
        ms = load_milestones(base_dir=self.tmp)
        self.assertEqual(len(ms), 4)
        self.assertEqual(ms[0]["date"], "20260708")   # date-sorted

        md = render_markdown(base_dir=self.tmp)
        # negative verdicts render with the SAME badge prominence as wins
        for badge in ("[VALIDATED]", "[REJECTED]", "[NO CHANGE]", "[PENDING]"):
            self.assertIn(badge, md)
        self.assertIn("0 → 7", md)
        self.assertIn("_none — pending until an artifact exists_", md)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "TIMELINE.md")))


class TestGitSpine(unittest.TestCase):
    def test_spine_parses_mission_commits(self):
        spine = git_spine(limit=50)
        self.assertTrue(spine, "expected commits in this repo")
        for c in spine[:3]:
            self.assertIn("hash", c)
            self.assertIn("date", c)
            self.assertIn("subject", c)


class TestConfigEraLabel(unittest.TestCase):
    """HEALTH-ERA-LABEL — a mid-session config change makes the baseline
    nonstationary: mixed_config_era / trend_eligible=false, derived from
    commit timestamps, never mistaken for replay deterioration."""

    def test_in_session_commit_marks_mixed_era(self):
        from replay_validation.organism_health import config_era_quality
        out = config_era_quality("20260709", commits=[
            ("2026-07-09T10:12:00-04:00", "REGIME-DEMOTE - ..."),
            ("2026-07-09T22:00:00-04:00", "EVENING - ..."),
        ])
        self.assertEqual(out["calibration_quality"], "mixed_config_era")
        self.assertFalse(out["trend_eligible"])
        self.assertEqual(len(out["in_session_commits"]), 1)

    def test_evening_commits_stay_clean_era(self):
        from replay_validation.organism_health import config_era_quality
        out = config_era_quality("20260708", commits=[
            ("2026-07-08T18:45:00-04:00", "PERCEPTION-1 - ..."),
            ("2026-07-08T23:10:00-04:00", "PERCEPTION-2 - ..."),
        ])
        self.assertEqual(out["calibration_quality"], "clean_era")
        self.assertTrue(out["trend_eligible"])

    def test_other_days_commits_ignored(self):
        from replay_validation.organism_health import config_era_quality
        out = config_era_quality("20260709", commits=[
            ("2026-07-08T10:00:00-04:00", "X"),
        ])
        self.assertTrue(out["trend_eligible"])

    def test_real_0709_is_mixed_era(self):
        # the real repo spine: REGIME-DEMOTE/MC-ENFORCE landed in-session 0709
        from replay_validation.organism_health import config_era_quality
        out = config_era_quality("20260709")
        self.assertEqual(out["calibration_quality"], "mixed_config_era")


class TestHealthNoSilentHealth(unittest.TestCase):
    def test_brain_trend_no_data_under_min_n(self):
        tmp = tempfile.mkdtemp()
        out = brain_trend("NOPE", base_dir=tmp)
        self.assertEqual(out["status"], "no_data")

    def test_governance_reports_no_data_not_zero_health(self):
        tmp = tempfile.mkdtemp()
        out = governance("NOPE", base_dir=tmp)
        self.assertEqual(out["proposals"], "no_data")
        self.assertEqual(out["adaptive_effect"], "no_data")

    def test_posture_drift_handles_empty_sources(self):
        tmp = tempfile.mkdtemp()
        out = posture_drift("NOPE", base_dir=tmp)
        self.assertIsNone(out["conservatism"]["false_rate"])
        self.assertEqual(out["confidence_calibration_recent"], "no_data")


if __name__ == "__main__":
    unittest.main()
