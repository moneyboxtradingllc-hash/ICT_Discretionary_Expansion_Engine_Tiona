"""
Phase AB-7.3 — Authority Integration tests (a/b/c only).

AB-7.3a — thesis_state is a read-only projection of the lifecycle block.
AB-7.3b — execution gate inherits a mature thesis's age for the setup-age check.
AB-7.3c — qualification floors its status from a valid persistent thesis.

All three consumers are gated by their own env flag and default OFF, so with the
flags unset the pipeline is bit-for-bit unchanged. NO R1/council/narrative
authority is touched here.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.thesis_lifecycle import thesis_state  # noqa: E402
from execution_gate.execution_gate import evaluate_gate  # noqa: E402
from qualification.trade_qualification_engine import qualify_trade  # noqa: E402


def lifecycle_block(status="EXECUTABLE", age=10, direction="bullish",
                    is_trade=True, pb="trend_continuation", pb_status="EXECUTABLE",
                    enabled=True):
    """Shape of ThesisLifecycleEngine.update()'s return block."""
    return {
        "enabled": enabled, "mode": "shadow", "action": "PROMOTE_TO_EXECUTABLE",
        "status": status, "thesis_id": "TH_test", "direction": direction,
        "thesis_type": f"{direction}_continuation", "confidence": 70, "age_scans": age,
        "is_trade_thesis": is_trade, "playbook_family": pb, "playbook_status": pb_status,
        "playbook_age_scans": age, "confidence_trend": "rising",
        "active_thesis": {"status": status},
    }


# ── AB-7.3a — read-only projection ────────────────────────────────────────────
class ThesisStateTest(unittest.TestCase):

    def test_projection_fields(self):
        ts = thesis_state(lifecycle_block(status="EXECUTABLE", age=12))
        self.assertTrue(ts["present"])
        self.assertEqual(ts["thesis_status"], "EXECUTABLE")
        self.assertEqual(ts["thesis_age_scans"], 12)
        self.assertEqual(ts["playbook_family"], "trend_continuation")
        self.assertEqual(ts["playbook_status"], "EXECUTABLE")
        self.assertEqual(ts["confidence_trend"], "rising")
        for k in ("present", "enabled", "thesis_status", "thesis_age_scans",
                  "thesis_confidence", "confidence_trend", "direction",
                  "is_trade_thesis", "playbook_status", "playbook_age_scans",
                  "playbook_family"):
            self.assertIn(k, ts)

    def test_absent_when_none_or_terminal(self):
        self.assertFalse(thesis_state(None)["present"])
        self.assertFalse(thesis_state({})["present"])
        self.assertFalse(thesis_state(lifecycle_block(status="INVALIDATED"))["present"])
        self.assertFalse(thesis_state(lifecycle_block(enabled=False))["present"])

    def test_projection_does_not_mutate_source(self):
        lc = lifecycle_block()
        before = dict(lc)
        thesis_state(lc)
        self.assertEqual(lc, before)


# ── AB-7.3b — gate inherits thesis age ────────────────────────────────────────
class GateAgeInheritanceTest(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("THESIS_FEEDS_READINESS", None)

    def _snap(self, setup_age, ts_block):
        return {
            "setup_lifecycle": {"active": True, "age_scans": setup_age, "current_phase": "developing"},
            "state_transition": {"invalidated": False},
            "regime_permissions": {"enabled": True, "allowed": True,
                                   "required_trigger_status": "confirmation_needed",
                                   "min_setup_age_scans": 3},
            "decision_authority": {}, "risk": {}, "ai_debate": {},
            "confidence_fusion": {}, "toolbox": {}, "council": {},
            "shared_context": {}, "narrative_authority": {}, "playbook": {},
            "thesis_state": thesis_state(ts_block) if ts_block else {},
        }

    def test_flag_off_uses_mechanical_age(self):
        snap = self._snap(setup_age=0, ts_block=lifecycle_block(status="EXECUTABLE", age=20))
        out = evaluate_gate(snap)
        self.assertFalse(out["setup_age_requirement_met"])      # 0 < 3
        self.assertFalse(out["thesis_age_applied"])
        self.assertEqual(out["setup_age_effective"], 0)

    def test_flag_on_executable_inherits_age(self):
        os.environ["THESIS_FEEDS_READINESS"] = "true"
        snap = self._snap(setup_age=0, ts_block=lifecycle_block(status="EXECUTABLE", age=20))
        out = evaluate_gate(snap)
        self.assertTrue(out["setup_age_requirement_met"])       # max(0,20)=20 >= 3
        self.assertTrue(out["thesis_age_applied"])
        self.assertEqual(out["setup_age_effective"], 20)

    def test_flag_on_threatened_does_not_inherit(self):
        os.environ["THESIS_FEEDS_READINESS"] = "true"
        snap = self._snap(setup_age=0, ts_block=lifecycle_block(status="THREATENED", age=20))
        out = evaluate_gate(snap)
        self.assertFalse(out["setup_age_requirement_met"])      # THREATENED lends no age
        self.assertFalse(out["thesis_age_applied"])

    def test_flag_on_no_thesis_unchanged(self):
        os.environ["THESIS_FEEDS_READINESS"] = "true"
        snap = self._snap(setup_age=1, ts_block=None)
        out = evaluate_gate(snap)
        self.assertFalse(out["setup_age_requirement_met"])      # 1 < 3, no thesis
        self.assertFalse(out["thesis_age_applied"])


# ── AB-7.3c — qualification stability floor ───────────────────────────────────
class QualificationFloorTest(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("QUALIFICATION_THESIS_FLOOR", None)

    def _snap(self, ts_block, narrative=""):
        return {
            "ai_context": {"market_narrative": narrative},
            "volatility": {}, "structure": {}, "po3": {}, "liquidity": {},
            "thesis_state": thesis_state(ts_block) if ts_block else {},
        }

    def test_flag_off_no_floor(self):
        snap = self._snap(lifecycle_block(status="EXECUTABLE"))
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")            # mechanical, unfloored
        self.assertFalse(out["thesis_floor_applied"])

    def test_executable_floors_to_qualified(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        snap = self._snap(lifecycle_block(status="EXECUTABLE"))
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "qualified")
        self.assertEqual(out["mechanical_status"], "no_trade")
        self.assertTrue(out["thesis_floor_applied"])

    def test_active_floors_to_candidate(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        snap = self._snap(lifecycle_block(status="ACTIVE"))
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "candidate")
        self.assertTrue(out["thesis_floor_applied"])

    def test_threatened_no_floor(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        snap = self._snap(lifecycle_block(status="THREATENED"))
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")
        self.assertFalse(out["thesis_floor_applied"])

    def test_floor_never_overrides_disqualification(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        snap = self._snap(lifecycle_block(status="EXECUTABLE"), narrative="conflicted")
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")            # true danger wins
        self.assertFalse(out["thesis_floor_applied"])

    def test_floor_does_not_apply_against_opposing_direction(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        from qualification.trade_qualification_engine import _apply_thesis_floor
        # bullish mechanical direction vs bearish thesis → floor withheld
        status, applied = _apply_thesis_floor(
            "no_trade", "bullish", False,
            thesis_state(lifecycle_block(status="EXECUTABLE", direction="bearish")))
        self.assertEqual(status, "no_trade")
        self.assertFalse(applied)
        # same direction → floor applies
        status, applied = _apply_thesis_floor(
            "no_trade", "bullish", False,
            thesis_state(lifecycle_block(status="EXECUTABLE", direction="bullish")))
        self.assertEqual(status, "qualified")
        self.assertTrue(applied)

    def test_floor_only_raises_never_lowers(self):
        os.environ["QUALIFICATION_THESIS_FLOOR"] = "true"
        # An ACTIVE thesis (floor=candidate) must not pull a higher mechanical
        # status down. We simulate by checking index logic via a strong status.
        from qualification.trade_qualification_engine import _apply_thesis_floor
        status, applied = _apply_thesis_floor(
            "elite", "bullish", False,
            thesis_state(lifecycle_block(status="ACTIVE", direction="bullish")))
        self.assertEqual(status, "elite")
        self.assertFalse(applied)


if __name__ == "__main__":
    unittest.main()
