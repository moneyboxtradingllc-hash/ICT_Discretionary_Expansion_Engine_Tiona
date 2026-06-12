"""
Phase FC-1 — Promoted Authority tests (Council veto + R-001 enforcement).

June 11 evidence: at order submission (10:29:53), REGIME voted NO@95,
DELIVERY voted NO@75, and shadow rule R-001 fired "compound hostility (3)"
— none of which had a wire into the execution gate. The gate authorized;
the trade resolved -1.34R. The identical pattern recurred at 13:17.

Replay proof uses the REAL archived snapshot
data/live_snapshots/20260611_102955_QQQ.json (tracked in git) plus the
council votes and shared context recorded in the governance ledger event
EV_QQQ_20260611T102955_R-001.
"""
import json
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shared_context.council import run_council, evaluate_veto
from rule_governance.promoted_rules import evaluate_promoted_rules
from execution_gate.execution_gate import evaluate_gate

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_JUNE11_SNAPSHOT = os.path.join(
    _REPO_ROOT, "data", "live_snapshots", "20260611_102955_QQQ.json"
)

# SharedMarketContext exactly as recorded in the ledger context_digest of
# EV_QQQ_20260611T102955_R-001 (the entry-scan shadow event).
JUNE11_CTX = {
    "context_version":      "5G.1",
    "symbol":               "QQQ",
    "session":              "morning_continuation",
    "regime":               "range_rotation",
    "regime_confidence":    0,
    "volatility_state":     "unstable",
    "expansion_state":      "exhaustion_risk",
    "delivery_state":       "bearish_delivery",
    "delivery_confidence":  25,
    "continuation_intact":  False,
    "exhaustion_present":   True,
    "reversal_present":     True,
    "qualification_status": "candidate",
    "qualification_score":  62,
    "playbook":             "liquidity_sweep_reversal",
    "playbook_direction":   "bullish",
    "toolbox_tool":         "bullish_ifvg",
    "trigger_status":       "confirmed",
    "setup_age":            3,
    "risk_multiplier":      0.5,
    "current_price":        701.42,
}


def _clear_env():
    for k in ("COUNCIL_AUTHORITY", "COUNCIL_VETO_MIN_NO_VOTES",
              "COUNCIL_VETO_MIN_CONFIDENCE", "RULE_GOVERNANCE_MODE",
              "PROMOTED_RULES"):
        os.environ.pop(k, None)


class TestCouncilVeto(unittest.TestCase):

    def tearDown(self):
        _clear_env()

    def test_june11_council_votes_trigger_veto(self):
        """The real June 11 context produces >= 2 high-confidence NO votes."""
        council = run_council(JUNE11_CTX)
        votes = {m["member"]: (m["vote"], m["confidence"])
                 for m in council["members"]}
        self.assertEqual(votes["REGIME"][0], "no")
        self.assertGreaterEqual(votes["REGIME"][1], 90)
        self.assertEqual(votes["DELIVERY"][0], "no")
        self.assertGreaterEqual(votes["DELIVERY"][1], 70)
        self.assertTrue(council["veto"]["veto_triggered"])

    def test_authority_default_is_observe_only(self):
        _clear_env()
        council = run_council(JUNE11_CTX)
        self.assertEqual(council["authority_level"], "observe_only")

    def test_authority_enforce_via_env(self):
        os.environ["COUNCIL_AUTHORITY"] = "enforce"
        council = run_council(JUNE11_CTX)
        self.assertEqual(council["authority_level"], "enforce")

    def test_veto_threshold_confidence(self):
        members = [
            {"member": "REGIME",   "vote": "no",  "confidence": 60},
            {"member": "DELIVERY", "vote": "no",  "confidence": 60},
            {"member": "TOOLBOX",  "vote": "yes", "confidence": 85},
        ]
        veto = evaluate_veto(members, {"dominant_position": "divided", "confidence": 60})
        self.assertFalse(veto["veto_triggered"])   # NOs below 70 confidence

    def test_consensus_no_triggers_veto(self):
        members = [{"member": "REGIME", "vote": "no", "confidence": 90}]
        veto = evaluate_veto(members, {"dominant_position": "no", "confidence": 88})
        self.assertTrue(veto["veto_triggered"])

    def test_veto_fail_open_on_garbage(self):
        veto = evaluate_veto(None, None)
        self.assertFalse(veto["veto_triggered"])


class TestPromotedRules(unittest.TestCase):

    def tearDown(self):
        _clear_env()

    def test_shadow_mode_never_blocks(self):
        os.environ["RULE_GOVERNANCE_MODE"] = "shadow"
        result = evaluate_promoted_rules(JUNE11_CTX)
        self.assertFalse(result["enforced"])
        self.assertFalse(result["blocked"])

    def test_enforce_mode_blocks_on_june11_context(self):
        """R-001 fired 'compound hostility (3)' on this exact context."""
        os.environ["RULE_GOVERNANCE_MODE"] = "enforce"
        os.environ["PROMOTED_RULES"] = "R-001"
        result = evaluate_promoted_rules(JUNE11_CTX)
        self.assertTrue(result["enforced"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["fired"][0]["rule_id"], "R-001")
        self.assertIn("compound hostility", result["fired"][0]["reason"])

    def test_enforce_mode_passes_healthy_context(self):
        os.environ["RULE_GOVERNANCE_MODE"] = "enforce"
        healthy = {
            "regime": "trend_up", "volatility_state": "stable",
            "exhaustion_present": False,
        }
        result = evaluate_promoted_rules(healthy)
        self.assertTrue(result["enforced"])
        self.assertFalse(result["blocked"])

    def test_unknown_rule_fails_open(self):
        os.environ["RULE_GOVERNANCE_MODE"] = "enforce"
        os.environ["PROMOTED_RULES"] = "R-999"
        result = evaluate_promoted_rules(JUNE11_CTX)
        self.assertFalse(result["blocked"])


class TestJune11GateReplay(unittest.TestCase):
    """
    THE replay proof: the archived 10:29:55 snapshot — the scan that
    submitted PT_QQQ_20260611T102953 — re-evaluated through the promoted
    gate. Legacy env authorized it; FC-1 env must block it, twice over.
    """

    @classmethod
    def setUpClass(cls):
        with open(_JUNE11_SNAPSHOT, encoding="utf-8") as fh:
            cls.snapshot = json.load(fh)
        # The archived snapshot predates FC-1 and carries no council/
        # shared_context keys — rebuild both from the ledger-recorded
        # context, exactly as scan_loop builds them before the gate.
        cls.snapshot["shared_context"] = dict(JUNE11_CTX)
        cls.snapshot["council"]        = run_council(JUNE11_CTX)
        # The snapshot store also trims trigger_prep from tool_candidates;
        # restore it from the recorded execution_gate values of that scan
        # (actual_trigger_status=confirmed, trigger_execution_ready passed).
        for cand in cls.snapshot["toolbox"]["tool_candidates"]:
            if cand.get("tool") == cls.snapshot["toolbox"]["preferred_tool"]:
                cand["trigger_prep"] = {
                    "execution_ready":    True,
                    "raw_trigger_status": "confirmed",
                }

    def setUp(self):
        os.environ["EXECUTION_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("EXECUTION_ENABLED", None)
        _clear_env()

    def test_legacy_env_reproduces_the_authorization(self):
        """Pre-FC behavior: the gate authorized this trade. It must still
        do so with promotions off — that is the rollback guarantee."""
        _clear_env()
        self.snapshot["council"] = run_council(JUNE11_CTX)   # observe_only
        gate = evaluate_gate(self.snapshot)
        self.assertTrue(gate["allow_execution"])
        self.assertEqual(gate["gate_status"], "authorized")

    def test_promoted_env_blocks_the_june11_trade(self):
        os.environ["COUNCIL_AUTHORITY"]    = "enforce"
        os.environ["RULE_GOVERNANCE_MODE"] = "enforce"
        os.environ["PROMOTED_RULES"]       = "R-001"
        self.snapshot["council"] = run_council(JUNE11_CTX)   # enforce
        gate = evaluate_gate(self.snapshot)
        self.assertFalse(gate["allow_execution"])
        self.assertEqual(gate["gate_status"], "blocked")
        self.assertFalse(gate["authorization_checks"]["council_permits_trade"])
        self.assertFalse(gate["authorization_checks"]["no_promoted_rule_block"])
        blocking = " | ".join(gate["blocking_factors"])
        self.assertIn("council veto", blocking)
        self.assertIn("R-001", blocking)

    def test_council_alone_blocks(self):
        os.environ["COUNCIL_AUTHORITY"] = "enforce"
        self.snapshot["council"] = run_council(JUNE11_CTX)
        gate = evaluate_gate(self.snapshot)
        self.assertFalse(gate["allow_execution"])
        self.assertFalse(gate["authorization_checks"]["council_permits_trade"])
        self.assertTrue(gate["authorization_checks"]["no_promoted_rule_block"])

    def test_r001_alone_blocks(self):
        os.environ["RULE_GOVERNANCE_MODE"] = "enforce"
        self.snapshot["council"] = run_council(JUNE11_CTX)   # observe_only
        gate = evaluate_gate(self.snapshot)
        self.assertFalse(gate["allow_execution"])
        self.assertTrue(gate["authorization_checks"]["council_permits_trade"])
        self.assertFalse(gate["authorization_checks"]["no_promoted_rule_block"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
