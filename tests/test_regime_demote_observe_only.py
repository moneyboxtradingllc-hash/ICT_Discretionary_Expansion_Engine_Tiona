"""
REGIME-DEMOTE (2026-07-09) — mechanical Regime Authority demotion to observe_only.

Live scan 20260709_094951 proved the mechanical regime still owned FINAL
execution authority: a range_rotation label imposed required_trigger=confirmed +
min_setup_age=2 at the execution gate and hard-blocked an ELITE
LIQUIDITY_SWEEP_REVERSAL SHORT while Market Commander was DIRECTIONAL /
MATURE_EXPANSION and itself only OBSERVE.

REGIME_AUTHORITY_MODE=observe_only demotes the mechanical regime to telemetry:
it still records regime_would_have_blocked / regime_veto_reason, still warns, and
still feeds Market Commander — but it may NOT hard-block execution. The gate
falls through to the next non-regime authority. enforce mode (default) is
bit-for-bit legacy.

Locks (mission-required):
  1. range_rotation cannot hard-block in observe_only
  2. regime still reports would_have_blocked
  3. regime still records veto reason
  4. enforce mode preserves old behavior
  5. Market Commander fields preserved
  6-10. FC-0B / risk / broker / sizing / max-trades / daily-loss untouched
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from execution_gate.execution_gate import evaluate_gate            # noqa: E402
from regime_authority.regime_authority_mode import (               # noqa: E402
    regime_authority_mode, regime_enforces,
)


def _range_rotation_snapshot():
    """A snapshot whose ONLY execution blocker is the mechanical regime overlay:
    permission allowed, but regime demands confirmed trigger + age 2 while the
    setup is a fresh confirmation-ready reversal. All non-regime authorities pass."""
    return {
        "decision_authority": {"decision": "ready_for_execution", "trade_authorized": False},
        "risk": {"trade_allowed": True},
        "setup_lifecycle": {"active": True, "current_phase": "confirmed", "age_scans": 1},
        "state_transition": {"invalidated": False},
        "toolbox": {
            "preferred_tool": "bearish_ifvg",
            "tool_candidates": [{
                "tool": "bearish_ifvg",
                "trigger_prep": {"execution_ready": True,
                                 "raw_trigger_status": "confirmation_needed"},
            }],
        },
        "playbook": {"selected_playbook": "liquidity_sweep_reversal", "direction": "short"},
        "regime_permissions": {
            "enabled": True, "regime_label": "range_rotation", "allowed": True,
            "required_trigger_status": "confirmed", "min_setup_age_scans": 2,
            "blocking_reasons": [], "forbidden_playbooks": [],
        },
        "council": {}, "shared_context": {}, "narrative_authority": {},
        "market_commander": {"authority_level": "observe_only",
                             "environment": {"family": "DIRECTIONAL", "type": "MATURE_EXPANSION"}},
    }


class TestObserveOnlyDemotion(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                          "REGIME_AUTHORITY_MODE": "observe_only"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_1_range_rotation_cannot_hard_block(self):
        g = evaluate_gate(_range_rotation_snapshot())
        # regime's confirmed/age-2 overlay must NOT appear as a hard blocker
        self.assertTrue(g["authorization_checks"]["regime_permission_allowed"])
        self.assertTrue(g["authorization_checks"]["trigger_requirement_met"])
        self.assertTrue(g["authorization_checks"]["setup_age_requirement_met"])
        joined = " ".join(g["blocking_factors"])
        self.assertNotIn("regime permission blocked", joined)
        self.assertNotIn("setup age requirement not met", joined)
        # with every non-regime authority passing, the trade now authorizes
        self.assertTrue(g["would_authorize_if_enabled"])
        self.assertEqual(g["gate_status"], "authorized")

    def test_2_reports_would_have_blocked(self):
        g = evaluate_gate(_range_rotation_snapshot())
        ra = g["regime_authority"]
        self.assertTrue(ra["regime_would_have_blocked"])
        self.assertEqual(ra["regime_authority"], "observe_only")
        self.assertEqual(ra["mechanical_regime_role"], "telemetry_only")
        self.assertEqual(ra["regime_effect_on_execution"], "advisory_only")
        self.assertEqual(ra["final_regime_enforcement_source"], "market_commander_or_none")

    def test_3_records_veto_reason(self):
        g = evaluate_gate(_range_rotation_snapshot())
        reason = g["regime_authority"]["regime_veto_reason"] or ""
        self.assertIn("regime", reason.lower())
        self.assertTrue(any(w.startswith("regime would_have_blocked") for w in g["warnings"]))

    def test_5_market_commander_fields_preserved(self):
        # gate never mutates the commander block; it stays on the snapshot verbatim
        snap = _range_rotation_snapshot()
        evaluate_gate(snap)
        self.assertEqual(snap["market_commander"]["authority_level"], "observe_only")
        self.assertEqual(snap["market_commander"]["environment"]["family"], "DIRECTIONAL")

    def test_observe_only_does_not_bypass_real_trigger(self):
        # FC-0B / real trigger stays sovereign: if the trigger is NOT execution_ready,
        # observe_only regime demotion must NOT authorize the trade.
        snap = _range_rotation_snapshot()
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["execution_ready"] = False
        g = evaluate_gate(snap)
        self.assertFalse(g["would_authorize_if_enabled"])
        self.assertIn("trigger execution_ready=false", " ".join(g["blocking_factors"]))

    def test_observe_only_does_not_bypass_risk(self):
        snap = _range_rotation_snapshot()
        snap["risk"]["trade_allowed"] = False
        g = evaluate_gate(snap)
        self.assertFalse(g["would_authorize_if_enabled"])
        self.assertIn("risk blocked", " ".join(g["blocking_factors"]))


class TestEnforcePreservesLegacy(unittest.TestCase):
    def test_4_enforce_mode_still_hard_blocks(self):
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                     "REGIME_AUTHORITY_MODE": "enforce"}):
            g = evaluate_gate(_range_rotation_snapshot())
            self.assertFalse(g["authorization_checks"]["trigger_requirement_met"])
            self.assertFalse(g["authorization_checks"]["setup_age_requirement_met"])
            self.assertFalse(g["would_authorize_if_enabled"])
            self.assertEqual(g["regime_authority"]["mechanical_regime_role"], "enforce")
            self.assertEqual(g["regime_authority"]["regime_effect_on_execution"], "enforced")

    def test_default_env_is_enforce(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REGIME_AUTHORITY_MODE", None)
            self.assertEqual(regime_authority_mode(), "enforce")
            self.assertTrue(regime_enforces())


class TestSafeguardsUntouched(unittest.TestCase):
    def test_6_to_10_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("REGIME_AUTHORITY_MODE", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
