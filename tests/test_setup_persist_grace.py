"""
SETUP-PERSIST — setup lifecycle transient-flicker grace window: regression lock.

2026-07-08 lifecycle assassination: the primary setup killer was
"Playbook dropped to no_playbook" (15 of 20 invalidation deaths), firing on a
SINGLE scan of no_playbook while qualification flickered to no_trade on 123/163
scans (75%). Result: 71% of setups died at age 1, average lifespan 1.45 scans —
no setup ever survived a confirmation window.

Repair (config-gated, default 0 = legacy immediate-kill): SETUP_NO_PLAYBOOK_GRACE
lets a setup remain DORMANT (age/lifecycle preserved, NOT tradeable that scan)
for up to N consecutive no_playbook scans before it is killed. Genuine
invalidations (state-transition, entry-trigger invalidated, toxic risk) and
SUSTAINED no_playbook past the window still kill immediately.

Locks:
  * default (grace 0): single no_playbook kills immediately — byte-identical legacy
  * grace 2: transient no_playbook -> dormant, setup preserved (active, age kept)
  * grace 2: recovery within window -> setup resumes, age continues, dormancy cleared
  * grace 2: sustained no_playbook past the window -> killed
  * other invalidation reasons kill immediately even under grace
  * dormant setup is NOT fabricated as tradeable (quality unchanged; scan is no_trade)
  * FC-0B / risk / broker / sizing untouched (source guard)
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from setup_lifecycle.setup_tracker import SetupTracker           # noqa: E402


def _snap(ts, playbook="liquidity_sweep_reversal", direction="bearish",
          tool="bearish_ifvg", qual="qualified", zl=709.0, zh=709.5,
          trigger_inval=False, state_inval=False, risk_tier="normal"):
    tb = {"preferred_tool": tool,
          "best_available_effective_status": "actionable",
          "tool_candidates": [{"tool": tool,
              "trigger_prep": {"effective_trigger_status":
                               "invalidated" if trigger_inval else "confirmation_needed"},
              "price_level": {
              "zone_low": zl, "zone_high": zh, "midpoint": (zl + zh) / 2,
              "price_relation": "inside_zone", "invalidated": trigger_inval,
              "level_type": "fvg_zone"}}]}
    if playbook == "no_playbook":
        tb = {"preferred_tool": None, "tool_candidates": [],
              "best_available_effective_status": "no_tool"}
    return {
        "timestamp": ts,
        "qualification": {"status": qual, "opportunity_score": 80},
        "playbook": {"selected_playbook": playbook, "direction": direction},
        "toolbox": tb,
        "risk": {"risk_tier": risk_tier, "trade_allowed": risk_tier != "blocked"},
        "state_transition": {"invalidated": state_inval, "transition_type": "stable",
                             "setup_lifecycle": "actionable_candidate", "warnings": []},
        "ai_context": {"confidence_score": 70},
    }


class TestLegacyDefault(unittest.TestCase):
    @patch.dict(os.environ, {"SETUP_NO_PLAYBOOK_GRACE": "0"})
    def test_single_no_playbook_kills_immediately(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")                       # born, age 1
        out = tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")
        self.assertTrue(out["invalidated"])
        self.assertEqual(out["reason"], "Playbook dropped to no_playbook")

    @patch.dict(os.environ, {}, clear=False)
    def test_absent_env_is_legacy(self):
        os.environ.pop("SETUP_NO_PLAYBOOK_GRACE", None)
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        out = tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")
        self.assertTrue(out["invalidated"])


class TestGracePreserves(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"SETUP_NO_PLAYBOOK_GRACE": "2"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_transient_no_playbook_goes_dormant_not_dead(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")                       # born, age 1
        out = tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")
        self.assertFalse(out["invalidated"])
        self.assertTrue(out.get("dormant"))
        self.assertEqual(out["current_phase"], "dormant")
        self.assertEqual(out["age_scans"], 1)               # age preserved, not reset

    def test_recovery_within_window_resumes_and_ages(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")                       # born age 1
        tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")  # dormant
        out = tr.update(_snap("t3"), "QQQ")                 # recover
        self.assertFalse(out["invalidated"])
        self.assertFalse(out.get("dormant", False))
        self.assertEqual(out["age_scans"], 2)               # aged through the dip
        self.assertTrue(out["active"])

    def test_sustained_no_playbook_past_window_kills(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")  # dormant 1
        tr.update(_snap("t3", playbook="no_playbook", qual="no_trade"), "QQQ")  # dormant 2
        out = tr.update(_snap("t4", playbook="no_playbook", qual="no_trade"), "QQQ")  # kill
        self.assertTrue(out["invalidated"])
        self.assertEqual(out["reason"], "Playbook dropped to no_playbook")

    def test_grace_resets_after_recovery(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")  # dormant 1
        tr.update(_snap("t3"), "QQQ")                       # recover -> dormancy cleared
        out = tr.update(_snap("t4", playbook="no_playbook", qual="no_trade"), "QQQ")  # dormant 1 again
        self.assertFalse(out["invalidated"])
        self.assertTrue(out.get("dormant"))


class TestGenuineInvalidationsStillKill(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"SETUP_NO_PLAYBOOK_GRACE": "2"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_trigger_invalidated_kills_under_grace(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        out = tr.update(_snap("t2", trigger_inval=True), "QQQ")
        self.assertTrue(out["invalidated"])
        self.assertEqual(out["reason"], "Entry trigger invalidated")

    def test_state_transition_invalidation_kills_under_grace(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        out = tr.update(_snap("t2", state_inval=True), "QQQ")
        self.assertTrue(out["invalidated"])
        self.assertEqual(out["reason"], "State transition flagged invalidated")

    def test_toxic_risk_kills_under_grace(self):
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        out = tr.update(_snap("t2", risk_tier="dangerous"), "QQQ")
        self.assertTrue(out["invalidated"])
        self.assertIn("Risk tier", out["reason"])

    def test_dormant_setup_not_fabricated_tradeable(self):
        """Dormancy preserves bookkeeping only — it must not invent a tradeable
        quality. The scan itself is still no_trade upstream."""
        tr = SetupTracker()
        tr.update(_snap("t1"), "QQQ")
        out = tr.update(_snap("t2", playbook="no_playbook", qual="no_trade"), "QQQ")
        self.assertTrue(out.get("dormant"))
        # highest_quality_reached is historical; current scan is not upgraded
        self.assertEqual(out["current_phase"], "dormant")


class TestSafetyUntouched(unittest.TestCase):
    def test_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("paper_execution", "execution_engine.py")):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("SETUP_NO_PLAYBOOK_GRACE", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
