"""
R-001-AUDIT (2026-07-11) — promoted rule demoted enforce→shadow on evidence.

22 sessions / ~13,000 scans: R-001 fired on 58.8% of ALL scans and its 110
binding vetoes suppressed 87 scoreable trades that went 28W/48L/11BE for a
NET-POSITIVE +3.06R — zero discrimination (vs council −2.0R and narrative
−1.0R, both measurably protective). Its regime input is the DEMOTED
classifier's label. Shadow keeps the divergence ledger recording every fire;
re-promotion is its own governance mission (no automatic path back).
Evidence: data/replay/reports/r001_audit_20260711.json
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rule_governance.promoted_rules import evaluate_promoted_rules  # noqa: E402

_JUNE11_HOSTILE_CTX = {
    "regime": "range_rotation",
    "volatility_state": "unstable",
    "exhaustion_present": True,
}


class TestLauncherCarriesDemotion(unittest.TestCase):
    def test_launcher_sets_shadow(self):
        launcher = os.path.join(os.path.dirname(__file__), "..",
                                "launch_paper_session_fc.ps1")
        with open(launcher, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn('$env:RULE_GOVERNANCE_MODE          = "shadow"', txt)
        # the rule stays REGISTERED (the ledger keeps measuring it) — only
        # its blocking authority is revoked
        self.assertIn('$env:PROMOTED_RULES                = "R-001"', txt)


class TestShadowIsWitnessNotVeto(unittest.TestCase):
    def test_shadow_never_blocks_even_on_founding_context(self):
        # the June-11 compound-hostility context that justified promotion
        with patch.dict(os.environ, {"RULE_GOVERNANCE_MODE": "shadow",
                                     "PROMOTED_RULES": "R-001"}):
            r = evaluate_promoted_rules(_JUNE11_HOSTILE_CTX)
        self.assertFalse(r["enforced"])
        self.assertFalse(r["blocked"])

    def test_enforce_rollback_still_blocks(self):
        # rollback path stays intact: RULE_GOVERNANCE_MODE=enforce restores
        # the pre-audit behavior byte-for-byte
        with patch.dict(os.environ, {"RULE_GOVERNANCE_MODE": "enforce",
                                     "PROMOTED_RULES": "R-001"}):
            r = evaluate_promoted_rules(_JUNE11_HOSTILE_CTX)
        self.assertTrue(r["blocked"])
        self.assertEqual(r["fired"][0]["rule_id"], "R-001")


if __name__ == "__main__":
    unittest.main()
