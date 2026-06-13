"""
Phase AB-2C — PO3 structure-bias fallback removal + provenance.

Proves PO3 directional outputs derive only from sweep/liquidity semantics, never
from structure bias, and that the generation firewall rejects PO3 directions with
missing or structure-tainted provenance.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.po3_engine import analyze_po3, _directions
from generation_firewall.authorship import authored_direction, nonstructure_direction

_DIRECTIONAL = ("bullish", "bearish")
_EXP_DISTRIB = {"state": "mature_expansion", "expansion_score": 60,
                "directional_efficiency": 0.6, "body_dominance": 0.6,
                "displacement_detected": True, "exhaustion_risk": "low"}
_VOL = {"state": "stable", "atr_trend": "stable"}


class TestDirectionsUnit(unittest.TestCase):
    def test_no_sweep_distribution_bias_does_not_author(self):
        # the exact removed leak: distribution + no sweep + structure bias
        m, ms, d, ds = _directions("distribution", None, "bullish")
        self.assertIsNone(d)
        self.assertEqual(ds, "fallback_none")
        m, ms, d, ds = _directions("distribution", None, "bearish")
        self.assertIsNone(d)

    def test_sweep_authors_with_provenance(self):
        m, ms, d, ds = _directions("distribution", "below_low", "neutral")
        self.assertEqual((m, ms), ("bullish", "sweep_semantics"))
        self.assertEqual((d, ds), ("bullish", "sweep_semantics"))

    def test_sweep_overrides_structure_bias(self):
        # bias bullish but sweep above_high → bearish, sweep wins, source sweep
        m, ms, d, ds = _directions("distribution", "above_high", "bullish")
        self.assertEqual(d, "bearish")
        self.assertEqual(ds, "sweep_semantics")


class TestExperiments(unittest.TestCase):
    """Controlled experiments A-D from the directive."""

    def test_A_structure_disabled_sweep_authors(self):
        r = analyze_po3({}, {"sweep_detected": True, "reclaim_detected": True,
                             "sweep_direction": "below_low"}, _VOL, _EXP_DISTRIB)
        self.assertEqual(r["distribution_direction"], "bullish")
        self.assertEqual(r["distribution_direction_source"], "sweep_semantics")

    def test_B_structure_bias_only_no_direction(self):
        # distribution phase, bias bullish, NO sweep → no direction
        r = analyze_po3({"state": "bullish_continuation", "bias": "bullish"},
                        {}, _VOL, _EXP_DISTRIB)
        self.assertEqual(r["phase"], "distribution")
        self.assertIsNone(r["distribution_direction"])
        self.assertEqual(r["distribution_direction_source"], "fallback_none")
        self.assertIsNone(r["delivery_direction"])
        self.assertEqual(r["delivery_direction_source"], "fallback_none")

    def test_C_bos_mss_only_no_direction(self):
        r = analyze_po3({"bos": True, "mss": True, "bias": "bullish",
                         "state": "bullish_reversal"}, {}, _VOL, _EXP_DISTRIB)
        self.assertIsNone(r["distribution_direction"])
        self.assertIsNone(r["manipulation_direction"])

    def test_D_conflict_sweep_stands_structure_witness(self):
        r = analyze_po3({"state": "bullish_continuation", "bias": "bullish", "bos": True},
                        {"sweep_detected": True, "reclaim_detected": True,
                         "sweep_direction": "above_high"}, _VOL, _EXP_DISTRIB)
        self.assertEqual(r["distribution_direction"], "bearish")  # sweep wins
        self.assertEqual(r["distribution_direction_source"], "sweep_semantics")


class TestFirewallRejectsTaintedProvenance(unittest.TestCase):
    """Experiment E."""

    def test_missing_provenance_rejected(self):
        d, src = nonstructure_direction({"15m": {"distribution_direction": "bearish"}}, {})
        self.assertIsNone(d)

    def test_structure_source_rejected(self):
        for tainted in ("structure", "structure_bias", "bias", "bos", "mss",
                        "swing_sequence", "directional_bias", "bias_only"):
            d, src = nonstructure_direction(
                {"15m": {"distribution_direction": "bearish",
                         "distribution_direction_source": tainted}}, {})
            self.assertIsNone(d, f"tainted source {tainted} was accepted")

    def test_valid_provenance_accepted(self):
        d, src = nonstructure_direction(
            {"15m": {"distribution_direction": "bearish",
                     "distribution_direction_source": "sweep_semantics"}}, {})
        self.assertEqual(d, "bearish")

    def test_authored_direction_rejects_tainted_po3(self):
        d, src = authored_direction("bullish",
                                    {"15m": {"distribution_direction": "bullish",
                                             "distribution_direction_source": "structure_bias"}},
                                    {})
        # tainted PO3 ignored; structure-only bias → never bullish
        self.assertNotEqual(d, "bullish")


class TestJune11Provenance(unittest.TestCase):
    """June 11 reads must trace to sweep evidence; no-sweep distribution must
    return insufficient (None), never structure."""

    def test_1000_buyside_raid_sweep_sourced(self):
        # 10:00 above_high raid + reclaim → bearish, sweep_semantics
        r = analyze_po3({"bias": "bullish"},
                        {"sweep_detected": True, "reclaim_detected": True,
                         "sweep_direction": "above_high"}, _VOL, _EXP_DISTRIB)
        self.assertEqual(r["delivery_direction"], "bearish")
        self.assertEqual(r["delivery_direction_source"], "sweep_semantics")

    def test_1100_protected_low_sweep_sourced(self):
        # 11:00 below_low raid + reclaim → bullish, sweep_semantics
        r = analyze_po3({"bias": "bearish"},
                        {"sweep_detected": True, "reclaim_detected": True,
                         "sweep_direction": "below_low"}, _VOL, _EXP_DISTRIB)
        self.assertEqual(r["delivery_direction"], "bullish")
        self.assertEqual(r["delivery_direction_source"], "sweep_semantics")

    def test_nosweep_distribution_returns_insufficient(self):
        # any no-sweep distribution scan with structure bias → no direction
        r = analyze_po3({"bias": "bullish", "state": "bullish_continuation"},
                        {}, _VOL, _EXP_DISTRIB)
        self.assertIsNone(r["delivery_direction"])
        self.assertEqual(r["delivery_direction_source"], "fallback_none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
