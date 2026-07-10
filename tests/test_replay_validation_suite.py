"""
REPLAY VALIDATION SUITE — comparator locks (2026-07-09).

compare_runs diffs two deterministic replay runs scan-by-scan and attributes the
FIRST divergent stage. The ablation matrix pins each campaign repair to its
config flag; repairs not exercisable in recorded replay are declared
NOT_MEASURABLE (never inferred).
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.validation_suite import (          # noqa: E402
    compare_runs, ABLATIONS, NOT_MEASURABLE, BASE_0708, BASE_0709,
)
from replay_validation.stage_trace import build_stage_trace  # noqa: E402


def _run(traces):
    return {"scans": [{"timestamp": f"t{i}", "trace": t}
                      for i, t in enumerate(traces)]}


class TestCompareRuns(unittest.TestCase):
    def test_identical_runs_zero_divergence(self):
        t = build_stage_trace({"qualification": {"status": "no_trade"}})
        out = compare_runs(_run([t, t]), _run([dict(t), dict(t)]))
        self.assertEqual(out["scans_diverged"], 0)
        self.assertEqual(out["scans_compared"], 2)

    def test_divergence_attributed_to_first_stage(self):
        a = build_stage_trace({"qualification": {"status": "no_trade"},
                               "trade_intent": {"intent_created": False}})
        b = build_stage_trace({"qualification": {"status": "candidate"},
                               "trade_intent": {"intent_created": True}})
        out = compare_runs(_run([a]), _run([b]))
        self.assertEqual(out["scans_diverged"], 1)
        self.assertEqual(out["first_divergence_by_stage"], {"qualification": 1})
        self.assertIn("owner", out["samples"][0])


class TestAblationMatrix(unittest.TestCase):
    def test_every_ablation_flips_exactly_one_flag(self):
        for name, date, base, flag, off_v, on_v in ABLATIONS:
            self.assertNotEqual(off_v, on_v, name)
            self.assertIn(date, ("20260708", "20260709"), name)

    def test_campaign_repairs_covered_or_declared(self):
        flags = {a[3] for a in ABLATIONS}
        for expected in ("REGIME_AUTHORITY_MODE", "MARKET_COMMANDER_AUTHORITY_MODE",
                         "EXPANSION_STABILITY_MODE", "EXPANSION_STABILITY_CONFIRM",
                         "SETUP_NO_PLAYBOOK_GRACE", "VOLATILITY_AUTHORITY_MODE",
                         "MECHANICAL_JUDGES_MODE", "EXPANSION_CONTINUATION_TRIGGER"):
            self.assertIn(expected, flags)
        declared = {r for r, _ in NOT_MEASURABLE}
        self.assertEqual(declared, {"BRAIN-FAMILY-REPAIR", "THESIS-PERSIST"})

    def test_day_bases_reflect_shipped_flags(self):
        # 0709 base includes every repair shipped by that evening; 0708 doesn't
        self.assertNotIn("REGIME_AUTHORITY_MODE", BASE_0708)
        self.assertEqual(BASE_0709["REGIME_AUTHORITY_MODE"], "observe_only")
        self.assertEqual(BASE_0709["MECHANICAL_JUDGES_MODE"], "telemetry_only")


if __name__ == "__main__":
    unittest.main()
