"""
Adaptive Learning — Phase 1B: Learning Signal Generator.

Proves the deterministic distillation of retrieved analogs into a LearningSignal:
observe_only neutrality, sample-size / coin-flip / flat-expectancy gating, capped
positive & floored negative adjustments, correct rate math, mae_risk skipping,
warning-tag generation, authoritative/similarity/direction filtering, safe empty
behavior, and the three ADDENDUM math-safety rules (zero stop-distance, floored
negative penalty, UTC→NY lunch mapping).
"""
import math
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.learning_signal import (
    build_learning_signal, calculate_confidence_adjustment, LearningSignal,
    _in_ny_lunch,
)


def _analog(r, sim=0.9, **over):
    a = {"similarity": sim, "r_multiple": r, "regime": "expansion_up",
         "active_playbook": "expansion_continuation", "timestamp": "2026-06-15T15:30:00+00:00"}
    a.update(over)
    return a


def _set(rs, sim=0.9, **over):
    return [_analog(r, sim=sim, **over) for r in rs]


class TestConfidenceAdjustment(unittest.TestCase):
    def test_observe_only_always_zero(self):
        self.assertEqual(
            calculate_confidence_adjustment(50, 0.9, 3.0, "observe_only"), 0)

    def test_sample_below_10_zero(self):
        self.assertEqual(
            calculate_confidence_adjustment(9, 0.9, 3.0, "bounded_modifier"), 0)

    def test_mixed_winrate_zero(self):
        self.assertEqual(
            calculate_confidence_adjustment(40, 0.50, 1.5, "bounded_modifier"), 0)

    def test_flat_expectancy_zero(self):
        self.assertEqual(
            calculate_confidence_adjustment(40, 0.70, 0.1, "bounded_modifier"), 0)

    def test_positive_edge_capped_at_plus_5(self):
        adj = calculate_confidence_adjustment(40, 0.80, 10.0, "bounded_modifier")
        self.assertEqual(adj, 5)                       # min(int(2+5),5) -> 5
        adj2 = calculate_confidence_adjustment(40, 0.70, 1.4, "advisory")
        self.assertEqual(adj2, 2)                      # int(2+0.7)=2

    def test_negative_edge_floored_and_capped_at_minus_5(self):
        adj = calculate_confidence_adjustment(40, 0.20, -10.0, "bounded_modifier")
        self.assertEqual(adj, -5)
        # ADDENDUM #2 — floor, not truncate. mean_r=-0.7 -> floor(-3.7)=-4
        adj2 = calculate_confidence_adjustment(40, 0.30, -0.7, "bounded_modifier")
        self.assertEqual(adj2, -4)
        self.assertNotEqual(adj2, -3)                  # int() would have given -3


class TestRateMath(unittest.TestCase):
    def test_rates_and_avg_r(self):
        # 6 wins, 4 losses -> win 0.6, fail 0.4; avg of [2,2,2,2,2,2,-1,-1,-1,-1]=0.8
        rs = [2, 2, 2, 2, 2, 2, -1, -1, -1, -1]
        sig = build_learning_signal(_set(rs), authority_level="bounded_modifier")
        self.assertEqual(sig.sample_size, 10)
        self.assertAlmostEqual(sig.win_rate, 0.6)
        self.assertAlmostEqual(sig.failure_rate, 0.4)
        self.assertEqual(sig.success_rate, sig.win_rate)
        self.assertAlmostEqual(sig.avg_r, 0.8)

    def test_positive_sample_positive_adjustment(self):
        rs = [3.0] * 8 + [-0.5] * 2          # win 0.8, avg 2.3
        sig = build_learning_signal(_set(rs), authority_level="bounded_modifier")
        self.assertGreater(sig.confidence_adjustment, 0)
        self.assertLessEqual(sig.confidence_adjustment, 5)
        self.assertIn("positive_historical_expectancy", sig.warning_tags)

    def test_negative_sample_negative_adjustment(self):
        rs = [-1.5] * 8 + [0.5] * 2          # win 0.2, avg -1.1
        sig = build_learning_signal(_set(rs), authority_level="bounded_modifier")
        self.assertLess(sig.confidence_adjustment, 0)
        self.assertGreaterEqual(sig.confidence_adjustment, -5)
        self.assertIn("negative_historical_expectancy", sig.warning_tags)


class TestMaeRisk(unittest.TestCase):
    def test_mae_risk_skips_missing(self):
        # two valid (mae/stop), one missing mae, one zero stop_distance
        analogs = [
            _analog(2.0, mae=0.5, entry_price=100.0, stop_price=99.0),   # 0.5/1.0=0.5
            _analog(2.0, mae=0.9, entry_price=100.0, stop_price=99.0),   # 0.9/1.0=0.9
            _analog(2.0, entry_price=100.0, stop_price=99.0),            # no mae -> skip
            _analog(2.0, mae=0.4, entry_price=100.0, stop_price=100.0),  # zero stop -> skip
        ]
        sig = build_learning_signal(analogs, authority_level="bounded_modifier")
        self.assertEqual(sig.sample_size, 4)
        self.assertAlmostEqual(sig.mae_risk, 0.7)       # mean(0.5,0.9)
        self.assertEqual(sig.risk_adjustment, 0)

    def test_zero_stop_distance_does_not_crash(self):
        analogs = [_analog(1.0, mae=0.5, entry_price=50.0, stop_price=50.0)]
        sig = build_learning_signal(analogs, authority_level="bounded_modifier")
        self.assertIsNone(sig.mae_risk)                 # only record was skipped
        self.assertEqual(sig.sample_size, 1)

    def test_mae_risk_warning_tag(self):
        analogs = [_analog(1.0, mae=0.95, entry_price=100.0, stop_price=99.0)]  # 0.95>0.85
        sig = build_learning_signal(analogs, authority_level="bounded_modifier")
        self.assertIn("prior_success_requires_stronger_delivery", sig.warning_tags)


class TestWarningTags(unittest.TestCase):
    def test_mixed_and_insufficient(self):
        rs = [1, 1, 1, 1, 1, -1, -1, -1, -1, -1]        # win 0.5
        sig = build_learning_signal(_set(rs), authority_level="bounded_modifier")
        self.assertIn("mixed_historical_outcomes", sig.warning_tags)

    def test_lunch_failures_tag_utc_converted(self):
        # All failures at 16:30 UTC == 12:30 NY (EDT) -> lunch
        fails = _set([-1, -1, -1], timestamp="2026-06-15T16:30:00+00:00")
        wins = _set([2, 2], timestamp="2026-06-15T18:00:00+00:00")
        sig = build_learning_signal(fails + wins, authority_level="bounded_modifier")
        self.assertIn("similar_setups_failed_during_lunch", sig.warning_tags)

    def test_regime_underperformance_tag(self):
        # current regime expansion_up; that regime win-rate < 0.30
        rs = [-1, -1, -1, -1, 2]                          # win 0.2
        snap = {"market_regime": {"regime_label": "expansion_up"}}
        sig = build_learning_signal(_set(rs), current_snapshot=snap,
                                    authority_level="bounded_modifier")
        self.assertIn("playbook_underperformed_in_current_regime", sig.warning_tags)


class TestFiltering(unittest.TestCase):
    def test_non_authoritative_ignored_when_field_present(self):
        analogs = [
            _analog(2.0, is_authoritative=True),
            _analog(2.0, is_authoritative=False),       # dropped
            _analog(2.0, is_authoritative=False),       # dropped
        ]
        sig = build_learning_signal(analogs, authority_level="bounded_modifier")
        self.assertEqual(sig.sample_size, 1)

    def test_below_similarity_threshold_ignored(self):
        analogs = _set([2.0, 2.0], sim=0.80) + _set([2.0], sim=0.95)
        sig = build_learning_signal(analogs)            # default threshold 0.82
        self.assertEqual(sig.sample_size, 1)

    def test_direction_incompatible_ignored(self):
        snap = {"playbook": {"direction": "bullish"}}
        analogs = [_analog(2.0, narrative_direction="bullish"),
                   _analog(2.0, narrative_direction="bearish")]   # dropped
        sig = build_learning_signal(analogs, current_snapshot=snap)
        self.assertEqual(sig.sample_size, 1)

    def test_missing_result_ignored(self):
        analogs = [_analog(2.0), {"similarity": 0.9, "regime": "x"}]  # 2nd has no r
        sig = build_learning_signal(analogs)
        self.assertEqual(sig.sample_size, 1)


class TestEmptyAndDefaults(unittest.TestCase):
    def test_empty_returns_safe_neutral(self):
        sig = build_learning_signal([])
        self.assertEqual(sig.sample_size, 0)
        self.assertEqual(sig.confidence_adjustment, 0)
        self.assertEqual(sig.win_rate, 0.0)
        self.assertIsNone(sig.mae_risk)
        self.assertIn("insufficient_sample_size", sig.warning_tags)

    def test_authority_defaults_observe_only(self):
        sig = build_learning_signal(_set([3.0] * 20))   # strong edge…
        self.assertEqual(sig.authority_level, "observe_only")
        self.assertEqual(sig.confidence_adjustment, 0)   # …but observe_only forces 0
        self.assertEqual(LearningSignal().authority_level, "observe_only")


class TestNyLunchMapping(unittest.TestCase):
    def test_utc_maps_to_ny_lunch(self):
        self.assertTrue(_in_ny_lunch("2026-06-15T16:30:00+00:00"))   # 12:30 EDT
        self.assertFalse(_in_ny_lunch("2026-06-15T15:30:00+00:00"))  # 11:30 EDT
        self.assertFalse(_in_ny_lunch("2026-06-15T17:30:00+00:00"))  # 13:30 EDT

    def test_naive_treated_as_ny(self):
        self.assertTrue(_in_ny_lunch("2026-06-15T12:30:00"))         # naive -> NY
        self.assertFalse(_in_ny_lunch("2026-06-15T09:30:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
