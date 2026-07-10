"""
ADAPT-LOOP-4 — Earn-Back Governance locks (2026-07-10).

The symmetric actuation path, equally bounded: an APPROVED (evidence →
replay-gate → explicit approval) promotion may LIFT one of the adaptive
layer's OWN per-bucket restrictions; ceiling = NEUTRAL (no boosts, ever);
capital locks + hard safety caps are never targets; EARNBACK_MODE ladder
off (byte-identical) → shadow (records only) → enforce.

Locks: proposal generation thresholds (below-evidence → nothing); NO
self-approval (approve refused until the gate validates); gate re-verifies
CURRENT evidence incl. net counterfactual R; mode ladder at the policy
engine's restriction birth sites (off keeps restriction; shadow keeps it +
records would-lift; enforce lifts it + records); unapproved bucket never
lifts; capital-driven flags untouched by earn-back; safety files clean.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.earnback import (                     # noqa: E402
    generate_proposals, load_proposals, set_status, active_promotions,
    earnback_check,
)
from replay_validation.earnback_gate import validate_proposal  # noqa: E402


def _write_tables(base, symbol="QQQ", playbook_bucket=None, sup_bucket=None,
                  resolved_rows=None):
    d = os.path.join(base, symbol)
    os.makedirs(d, exist_ok=True)
    if playbook_bucket is not None:
        with open(os.path.join(d, "playbook_performance.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"opening_drive": playbook_bucket}, fh)
    if sup_bucket is not None:
        with open(os.path.join(d, "suppression_metrics.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"playbook": {"opening_drive": sup_bucket}}, fh)
    if resolved_rows is not None:
        with open(os.path.join(d, "suppression_resolved.jsonl"), "w",
                  encoding="utf-8") as fh:
            for r in resolved_rows:
                fh.write(json.dumps(r) + "\n")


_SUP_STRONG = {"suppressed_total": 30, "correct_suppressions": 5,
               "false_suppressions": 20, "neutral_suppressions": 3,
               "expired_suppressions": 2}
_RESOLVED_POSITIVE = [{"dimensions": {"playbook": "opening_drive"},
                       "suppression_cost": 1.5}] * 10


class TestProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_below_evidence_no_proposals(self):
        _write_tables(self.tmp, playbook_bucket={"trades": 5, "expectancy": 0.5,
                                                 "loss_streak": 0},
                      sup_bucket={"suppressed_total": 5,
                                  "correct_suppressions": 3,
                                  "false_suppressions": 2})
        self.assertEqual(generate_proposals("QQQ", base_dir=self.tmp), [])

    def test_suppression_evidence_generates_and_is_idempotent(self):
        _write_tables(self.tmp, playbook_bucket={"trades": 2, "expectancy": -1.0,
                                                 "loss_streak": 4},
                      sup_bucket=_SUP_STRONG)
        new = generate_proposals("QQQ", base_dir=self.tmp)
        self.assertEqual({p["action"] for p in new},
                         {"trade_block", "risk_reduction"})
        self.assertTrue(all(p["status"] == "proposed" and not p["validated"]
                            for p in new))
        self.assertEqual(generate_proposals("QQQ", base_dir=self.tmp), [])

    def test_performance_recovery_generates(self):
        _write_tables(self.tmp, playbook_bucket={"trades": 25, "expectancy": 0.3,
                                                 "loss_streak": 0})
        new = generate_proposals("QQQ", base_dir=self.tmp)
        self.assertEqual({p["action"] for p in new},
                         {"risk_reduction", "confidence_penalty"})


class TestGovernanceLadder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_tables(self.tmp, playbook_bucket={"trades": 2, "expectancy": -1.0,
                                                 "loss_streak": 4},
                      sup_bucket=_SUP_STRONG,
                      resolved_rows=_RESOLVED_POSITIVE)
        generate_proposals("QQQ", base_dir=self.tmp)
        self.pid = "EB_QQQ_playbook_opening_drive_trade_block"

    def test_no_self_approval_without_gate(self):
        self.assertFalse(set_status("QQQ", self.pid, "approved",
                                    approved_by="test", base_dir=self.tmp))
        self.assertEqual(active_promotions("QQQ", base_dir=self.tmp), {})

    def test_gate_validates_then_approval_works(self):
        report = validate_proposal("QQQ", self.pid, base_dir=self.tmp)
        self.assertTrue(report["passed"], report["checks"])
        self.assertTrue(set_status("QQQ", self.pid, "approved",
                                   approved_by="maurice", base_dir=self.tmp))
        promos = active_promotions("QQQ", base_dir=self.tmp)
        self.assertIn(("playbook", "opening_drive"), promos)

    def test_gate_fails_when_evidence_decayed(self):
        # evidence weakens after proposal: gate must refuse
        _write_tables(self.tmp, sup_bucket={"suppressed_total": 30,
                                            "correct_suppressions": 20,
                                            "false_suppressions": 5})
        report = validate_proposal("QQQ", self.pid, base_dir=self.tmp)
        self.assertFalse(report["passed"])
        self.assertFalse(set_status("QQQ", self.pid, "approved",
                                    base_dir=self.tmp))

    def test_gate_fails_without_positive_net_counterfactual(self):
        _write_tables(self.tmp, resolved_rows=[
            {"dimensions": {"playbook": "opening_drive"},
             "suppression_cost": -2.0}] * 5)
        report = validate_proposal("QQQ", self.pid, base_dir=self.tmp)
        self.assertFalse(report["passed"])


class TestModeLadderAtPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_tables(self.tmp, playbook_bucket={"trades": 2, "expectancy": -1.0,
                                                 "loss_streak": 4},
                      sup_bucket=_SUP_STRONG,
                      resolved_rows=_RESOLVED_POSITIVE)
        generate_proposals("QQQ", base_dir=self.tmp)
        pid = "EB_QQQ_playbook_opening_drive_trade_block"
        validate_proposal("QQQ", pid, base_dir=self.tmp)
        set_status("QQQ", pid, "approved", approved_by="maurice",
                   base_dir=self.tmp)

    def _policy(self):
        from adaptive_learning.adaptive_policy_engine import (
            generate_adaptive_policy_report,
        )
        return generate_adaptive_policy_report(
            {"symbol": "QQQ", "playbook": "opening_drive"}, base_dir=self.tmp)

    def test_off_mode_restriction_stands(self):
        with patch.dict(os.environ, {"EARNBACK_MODE": "off"}):
            rep = self._policy()
        self.assertTrue(rep["trade_block_recommended"])
        self.assertEqual(rep.get("earnback_events", []), [])

    def test_shadow_mode_records_but_keeps_restriction(self):
        with patch.dict(os.environ, {"EARNBACK_MODE": "shadow"}):
            rep = self._policy()
        self.assertTrue(rep["trade_block_recommended"])       # still blocks
        self.assertTrue(any("would lift" in e for e in rep["earnback_events"]))

    def test_enforce_mode_lifts_approved_restriction(self):
        with patch.dict(os.environ, {"EARNBACK_MODE": "enforce"}):
            rep = self._policy()
        self.assertFalse(rep["trade_block_recommended"])      # lifted
        self.assertTrue(any("LIFTED" in e for e in rep["earnback_events"]))

    def test_enforce_never_lifts_unapproved_bucket(self):
        # a different bucket with the same streak stays blocked
        d = os.path.join(self.tmp, "QQQ")
        with open(os.path.join(d, "playbook_performance.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"opening_drive": {"trades": 2, "expectancy": -1.0,
                                         "loss_streak": 4},
                       "range_expansion": {"trades": 2, "expectancy": -1.0,
                                           "loss_streak": 4}}, fh)
        from adaptive_learning.adaptive_policy_engine import (
            generate_adaptive_policy_report,
        )
        with patch.dict(os.environ, {"EARNBACK_MODE": "enforce"}):
            rep = generate_adaptive_policy_report(
                {"symbol": "QQQ", "playbook": "range_expansion"},
                base_dir=self.tmp)
        self.assertTrue(rep["trade_block_recommended"])       # not promoted

    def test_check_helper_never_boosts(self):
        with patch.dict(os.environ, {"EARNBACK_MODE": "enforce"}):
            rec = earnback_check("QQQ", "playbook", "opening_drive",
                                 "confidence_boost", base_dir=self.tmp)
        self.assertFalse(rec["lift"])   # boost is not a liftable restriction


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py"),
                           ("execution_gate", "execution_gate.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("EARNBACK", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
