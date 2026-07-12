"""
Phase AB-2B — Structure Contamination Cleanup (surviving scope).

TIER-2A (2026-07-10): the legacy AI wrapper (debate engine + deterministic
_ai_direction) was RETIRED, so the wrapper-side contamination proofs died with
the defendant. What survives is the live shared-context rule this phase also
established: delivery state requires PO3 evidence — a directional bias alone
may never manufacture a delivery verdict.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shared_context.shared_market_context import build_shared_market_context


def _on():  os.environ["STRUCTURE_AUTHORSHIP_FIREWALL"] = "true"
def _clear(): os.environ.pop("STRUCTURE_AUTHORSHIP_FIREWALL", None)


class TestDeliveryFallback(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def _snap_no_po3(self, bias):
        return {
            "ai_context": {"directional_bias": bias},
            "structure": {"15m": {"bias": bias}, "alignment": "strong"},
            "market_regime": {}, "qualification": {}, "playbook": {},
            "setup_lifecycle": {}, "toolbox": {},
        }

    def test_no_po3_is_insufficient_not_bullish(self):
        ctx = build_shared_market_context(self._snap_no_po3("bullish"), "QQQ")
        self.assertEqual(ctx["delivery_state"], "insufficient_delivery_evidence")
        self.assertEqual(ctx["delivery_confidence"], 0)

    def test_no_po3_bearish_bias_also_insufficient(self):
        ctx = build_shared_market_context(self._snap_no_po3("bearish"), "QQQ")
        self.assertNotIn("bias_only", ctx["delivery_state"])
        self.assertNotIn("bearish_delivery", ctx["delivery_state"])


if __name__ == "__main__":
    unittest.main()
