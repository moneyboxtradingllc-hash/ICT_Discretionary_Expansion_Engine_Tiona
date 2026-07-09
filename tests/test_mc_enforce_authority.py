"""
MC-ENFORCE (2026-07-09) — Market Commander becomes final environment authority.

Live scans 20260709_094304/094349/095057 showed the mechanical council voices
(REGIME/OPPORTUNITY/TOOLBOX) vetoing the execution gate while Market Commander
read DIRECTIONAL/MATURE_EXPANSION — an indirect channel restoring the mechanical
regime veto after REGIME-DEMOTE. MARKET_COMMANDER_AUTHORITY_MODE=enforce splits
the council into safety-class (RISK — may still veto) and advisory-class
(demoted to would_have_vetoed). Default observe_only = bit-for-bit legacy.

Mission-required locks:
  - Commander enforce mode exists (+ default observe_only rollback)
  - Commander owns final environment (commander_* fields present)
  - Mechanical regime cannot overrule Commander (regime demoted; telemetry only)
  - Council cannot indirectly restore mechanical regime veto (advisory demotion)
  - Advisory dissent logged; would_have_vetoed preserved
  - Safety-class (RISK) dissent CAN still veto
  - FC-0B / risk / broker / stops / sizing / max-trades / daily-loss untouched
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from execution_gate.execution_gate import evaluate_gate                 # noqa: E402
from market_commander.commander_authority import (                      # noqa: E402
    build_commander_authority, commander_authority_mode, commander_enforces,
    review_council_authority, SAFETY_COUNCIL_MEMBERS, ADVISORY_COUNCIL_MEMBERS,
)


def _clean_snapshot():
    """Every non-council authority passes; the ONLY blocker is the council veto."""
    return {
        "decision_authority": {"decision": "ready_for_execution", "trade_authorized": False},
        "risk": {"trade_allowed": True},
        "setup_lifecycle": {"active": True, "current_phase": "confirmed", "age_scans": 3},
        "state_transition": {"invalidated": False},
        "toolbox": {
            "preferred_tool": "bearish_ifvg",
            "tool_candidates": [{
                "tool": "bearish_ifvg",
                "trigger_prep": {"execution_ready": True, "raw_trigger_status": "confirmed"},
            }],
        },
        "playbook": {"selected_playbook": "liquidity_sweep_reversal", "direction": "short"},
        "regime_permissions": {"enabled": True, "regime_label": "range_rotation",
                               "allowed": True, "required_trigger_status": "confirmation_needed",
                               "min_setup_age_scans": 1},
        "shared_context": {}, "narrative_authority": {},
        "market_commander": {
            "authority_level": "observe_only",
            "final_state": "COMMAND_OBSERVE",
            "environment": {"family": "DIRECTIONAL", "type": "MATURE_EXPANSION",
                            "confidence": 64, "conflict_index": 37,
                            "commander_vs_regime_status": "COGNITIVE_OVERRIDE_ACTIVE",
                            "disagreement_reason": "Commander DIRECTIONAL; regime range_rotation"},
            "participation": {"decision": "OBSERVE"},
        },
        "council": {
            "authority_level": "enforce",
            "veto": {
                "veto_triggered": True,
                "strong_no_votes": [
                    {"member": "REGIME", "confidence": 70},
                    {"member": "OPPORTUNITY", "confidence": 75},
                    {"member": "TOOLBOX", "confidence": 80},
                ],
                "consensus_no": False,
                "veto_reason": "council veto: high-confidence NO from REGIME@70, OPPORTUNITY@75, TOOLBOX@80",
                "min_no_votes": 2, "min_confidence": 70,
            },
        },
    }


class TestCommanderMode(unittest.TestCase):
    def test_enforce_mode_exists(self):
        with patch.dict(os.environ, {"MARKET_COMMANDER_AUTHORITY_MODE": "enforce"}):
            self.assertEqual(commander_authority_mode(), "enforce")
            self.assertTrue(commander_enforces())

    def test_default_is_observe_only(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MARKET_COMMANDER_AUTHORITY_MODE", None)
            self.assertEqual(commander_authority_mode(), "observe_only")
            self.assertFalse(commander_enforces())

    def test_commander_outputs_required_fields(self):
        auth = build_commander_authority(_clean_snapshot())
        for f in ("commander_authority_mode", "commander_final_environment",
                  "commander_final_bias", "commander_final_permission",
                  "commander_confidence", "commander_conflict_score",
                  "commander_override_active", "commander_override_reason",
                  "commander_blocks_trade", "commander_allows_trade"):
            self.assertIn(f, auth)
        self.assertEqual(auth["commander_final_environment"], "DIRECTIONAL/MATURE_EXPANSION")
        self.assertTrue(auth["commander_override_active"])


class TestCouncilDemotion(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                          "COUNCIL_AUTHORITY": "enforce",
                                          "REGIME_AUTHORITY_MODE": "observe_only",
                                          "MARKET_COMMANDER_AUTHORITY_MODE": "enforce"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_advisory_council_veto_demoted(self):
        g = evaluate_gate(_clean_snapshot())
        # advisory-only council veto must NOT block; trade authorizes
        self.assertTrue(g["authorization_checks"]["council_permits_trade"])
        self.assertTrue(g["would_authorize_if_enabled"])
        self.assertNotIn("council veto", " ".join(g["blocking_factors"]))

    def test_advisory_dissent_logged_and_would_have_vetoed_preserved(self):
        g = evaluate_gate(_clean_snapshot())
        cr = g["council_authority_review"]
        self.assertTrue(cr["council_would_have_vetoed"])
        self.assertTrue(cr["advisory_veto_demoted"])
        members = {m["member"] for m in cr["advisory_dissent"]}
        self.assertEqual(members, {"REGIME", "OPPORTUNITY", "TOOLBOX"})
        self.assertTrue(any("would_have_vetoed" in w for w in g["warnings"]))

    def test_mechanical_regime_is_telemetry_only(self):
        g = evaluate_gate(_clean_snapshot())
        self.assertEqual(g["mechanical_regime"]["mechanical_regime_role"], "telemetry_only")


class TestSafetyClassStillVetoes(unittest.TestCase):
    def test_risk_safety_dissent_can_still_veto(self):
        # a safety-class (RISK) strong-NO meeting min_no still blocks under enforce
        council = {"authority_level": "enforce", "veto": {
            "veto_triggered": True,
            "strong_no_votes": [{"member": "RISK", "confidence": 90}],
            "veto_reason": "risk veto", "min_no_votes": 1, "min_confidence": 70}}
        review = review_council_authority(council, enforce=True)
        self.assertTrue(review["council_veto_effective"])
        self.assertEqual([m["member"] for m in review["safety_dissent"]], ["RISK"])

    def test_member_class_partition(self):
        self.assertIn("RISK", SAFETY_COUNCIL_MEMBERS)
        self.assertEqual(ADVISORY_COUNCIL_MEMBERS,
                         {"REGIME", "DELIVERY", "OPPORTUNITY", "QUALIFICATION", "TOOLBOX"})


class TestCommanderBlocksHostile(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                          "MARKET_COMMANDER_AUTHORITY_MODE": "enforce"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_commander_stand_down_blocks(self):
        snap = _clean_snapshot()
        snap["market_commander"]["participation"] = {"decision": "STAND_DOWN"}
        snap["market_commander"]["environment"]["family"] = "HOSTILE"
        snap["market_commander"]["environment"]["type"] = "NEWS_CHAOS"
        snap["council"]["veto"]["veto_triggered"] = False
        g = evaluate_gate(snap)
        self.assertFalse(g["authorization_checks"]["commander_permits_trade"])
        self.assertFalse(g["would_authorize_if_enabled"])
        self.assertIn("market commander STAND_DOWN", " ".join(g["blocking_factors"]))

    def test_commander_directional_does_not_block(self):
        g = evaluate_gate(_clean_snapshot())
        self.assertTrue(g["authorization_checks"]["commander_permits_trade"])


class TestRollbackAndSafety(unittest.TestCase):
    def test_observe_only_preserves_full_council_veto(self):
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                     "COUNCIL_AUTHORITY": "enforce",
                                     "MARKET_COMMANDER_AUTHORITY_MODE": "observe_only"}):
            g = evaluate_gate(_clean_snapshot())
            # legacy: the full advisory council veto still blocks
            self.assertFalse(g["authorization_checks"]["council_permits_trade"])
            self.assertFalse(g["would_authorize_if_enabled"])

    def test_enforce_does_not_bypass_real_trigger(self):
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                     "MARKET_COMMANDER_AUTHORITY_MODE": "enforce"}):
            snap = _clean_snapshot()
            snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["execution_ready"] = False
            g = evaluate_gate(snap)
            self.assertFalse(g["would_authorize_if_enabled"])
            self.assertIn("trigger execution_ready=false", " ".join(g["blocking_factors"]))

    def test_enforce_does_not_bypass_risk(self):
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "true",
                                     "MARKET_COMMANDER_AUTHORITY_MODE": "enforce"}):
            snap = _clean_snapshot()
            snap["risk"]["trade_allowed"] = False
            g = evaluate_gate(snap)
            self.assertFalse(g["would_authorize_if_enabled"])
            self.assertIn("risk blocked", " ".join(g["blocking_factors"]))

    def test_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("MARKET_COMMANDER_AUTHORITY_MODE", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
