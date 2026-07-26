"""
Phase 5A — Regime Classifier Tests.
16 tests covering all 10 regime labels and 6 safety invariants.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from regime_classification.regime_classifier import classify_regime, _FAMILIES
from regime_classification.regime_features   import extract_regime_features
from regime_classification.regime_summary    import build_regime_summary


def _snap(**kw):
    """Build a minimal snapshot with keyword overrides."""
    return {
        "structure": {
            "15m": {
                "bias": kw.get("bias_15", "neutral"),
                "bos":  kw.get("bos_15",  False),
                "mss":  kw.get("mss_15",  False),
            },
            "5m": {
                "bias": kw.get("bias_5",  "neutral"),
                "bos":  kw.get("bos_5",   False),
                "mss":  kw.get("mss_5",   False),
            },
            "alignment": kw.get("alignment", "neutral"),
        },
        "volatility": {
            "15m": {"state": kw.get("vol_state", "normal")},
        },
        "expansion": {
            "15m": {
                "state":                 kw.get("exp_state",  "normal"),
                "expansion_score":       kw.get("exp_score",  0),
                "displacement_detected": kw.get("disp_15",    False),
            },
            "5m": {
                "state":                 kw.get("exp_state_5", "normal"),
                "displacement_detected": kw.get("disp_5",      False),
            },
        },
        "liquidity": {
            "15m": {
                "sweep_detected":   kw.get("sweep_15",   False),
                "reclaim_detected": kw.get("reclaim_15", False),
            },
            "5m": {
                "sweep_detected":   kw.get("sweep_5",    False),
                "reclaim_detected": kw.get("reclaim_5",  False),
            },
        },
        "po3": {
            "15m": {"distribution_direction": kw.get("po3_15", "")},
            "5m":  {"distribution_direction": kw.get("po3_5",  "")},
            "alignment": kw.get("po3_align", ""),
        },
        "ai_context": {
            "directional_bias": kw.get("db", "neutral"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Regime Labels (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeLabels(unittest.TestCase):

    def test_01_unknown_regime(self):
        # trend=50 (both aligned+bos_15) — too low for trend_up (needs >=55),
        # too high for range_rotation (needs <50), chop=5 too low — all fall through
        snap = _snap(bias_15="bullish", bias_5="bullish", bos_15=True)
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "unknown")

    def test_02_reversal_attempt(self):
        # sweep+reclaim on 15m, MSS on both TFs, structure contradicts ai bias
        snap = _snap(
            sweep_15=True, reclaim_15=True,
            mss_15=True, mss_5=True,
            bias_15="bullish", bias_5="bullish",
            db="bearish",
        )
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "reversal_attempt")

    def test_03_high_volatility(self):
        # extreme volatility + no trend (no aligned bias, no BOS) → high_volatility
        # supersedes chop because vol is extreme and trend < 50
        snap = _snap(vol_state="extreme")
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "high_volatility")

    def test_04_expansion_up(self):
        # expanding + high exp_score + displacement + bullish alignment + trend >= 50
        snap = _snap(
            bias_15="bullish", bias_5="bullish",
            bos_15=True, bos_5=True,
            # detect_expansion._state() emits healthy_expansion / mature_expansion /
            # early_expansion / compression / exhaustion_risk. "expanding" belongs to
            # the VOLATILITY vocabulary and was never producible here — the fixture
            # asserted against a state production cannot generate, which is why
            # is_expanding stayed permanently False without any test noticing.
            exp_state="healthy_expansion", exp_score=70, disp_15=True,
        )
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "expansion_up")

    def test_05_expansion_down(self):
        snap = _snap(
            bias_15="bearish", bias_5="bearish",
            bos_15=True, bos_5=True,
            # detect_expansion._state() emits healthy_expansion / mature_expansion /
            # early_expansion / compression / exhaustion_risk. "expanding" belongs to
            # the VOLATILITY vocabulary and was never producible here — the fixture
            # asserted against a state production cannot generate, which is why
            # is_expanding stayed permanently False without any test noticing.
            exp_state="healthy_expansion", exp_score=70, disp_15=True,
        )
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "expansion_down")

    def test_06_trend_up(self):
        # both TFs bullish + BOS on both = trend_score 60, chop ~ 5
        snap = _snap(
            bias_15="bullish", bias_5="bullish",
            bos_15=True, bos_5=True,
        )
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "trend_up")

    def test_07_trend_down(self):
        snap = _snap(
            bias_15="bearish", bias_5="bearish",
            bos_15=True, bos_5=True,
        )
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "trend_down")

    def test_08_low_volatility(self):
        # vol=low + no structure = trend_score 0 < 40 → low_volatility before chop
        snap = _snap(vol_state="low")
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "low_volatility")

    def test_09_chop(self):
        # both TFs neutral + no BOS + normal vol → chop_score 65
        snap = _snap(vol_state="normal", bias_15="neutral", bias_5="neutral")
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "chop")

    def test_10_range_rotation(self):
        # one TF neutral, one bullish, no BOS, no strong chop → catchall
        snap = _snap(vol_state="normal", bias_15="neutral", bias_5="bullish")
        result = classify_regime(snap)
        self.assertEqual(result["regime_label"], "range_rotation")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Safety Invariants (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def test_11_authority_always_observe_only(self):
        for snap in [{}, _snap(bias_15="bullish", bos_15=True)]:
            result = classify_regime(snap)
            self.assertEqual(result["authority_level"], "observe_only",
                             f"authority_level wrong for snap={snap}")

    def test_12_confidence_modifier_always_zero(self):
        for snap in [{}, _snap(vol_state="extreme"), _snap(bias_15="bullish", bos_15=True)]:
            result = classify_regime(snap)
            self.assertEqual(result["confidence_modifier"], 0,
                             f"confidence_modifier wrong for snap={snap}")

    def test_13_enabled_always_true(self):
        result = classify_regime({})
        self.assertTrue(result["enabled"])

    def test_14_regime_family_mapping_complete(self):
        expected = {
            "trend_up": "trend",      "trend_down": "trend",
            "expansion_up": "expansion", "expansion_down": "expansion",
            "reversal_attempt": "reversal",
            "high_volatility": "volatility", "low_volatility": "volatility",
            "chop": "chop", "range_rotation": "range", "unknown": "unknown",
        }
        for label, family in expected.items():
            self.assertEqual(_FAMILIES[label], family, f"label={label}")

    def test_15_build_regime_summary_required_keys(self):
        summary = build_regime_summary({})
        required = {
            "regime_label", "regime_family", "confidence",
            "volatility_state", "expansion_state",
            "authority_level", "confidence_modifier",
        }
        self.assertTrue(required.issubset(summary.keys()),
                        f"missing keys: {required - summary.keys()}")
        self.assertEqual(summary["authority_level"],     "observe_only")
        self.assertEqual(summary["confidence_modifier"], 0)

    def test_16_classify_regime_never_raises(self):
        bad_inputs = [
            None,
            {},
            {"structure": None},
            {"volatility": "not_a_dict"},
            {"expansion": {"15m": None}},
        ]
        for inp in bad_inputs:
            try:
                result = classify_regime(inp)
                self.assertIn("regime_label", result,
                              f"regime_label missing for input {inp!r}")
                self.assertEqual(result["confidence_modifier"], 0)
                self.assertEqual(result["authority_level"],     "observe_only")
            except Exception as exc:
                self.fail(f"classify_regime raised on input {inp!r}: {exc}")


if __name__ == "__main__":
    unittest.main()
