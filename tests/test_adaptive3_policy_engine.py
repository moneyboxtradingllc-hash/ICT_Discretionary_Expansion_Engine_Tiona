"""
Adaptive Learning — Phase 3B: Adaptive policy engine (DEFENSIVE_ONLY).

Proves the policy engine reads the performance tables and emits the correct
recommendation flags: strong expectancy -> boost, weak -> penalty, severe ->
risk_reduction, a 4-loss streak -> trade_block, insufficient sample -> nothing,
symbol isolation holds, and any defensive signal suppresses a boost. The report
is hard-locked observe_only / DEFENSIVE_ONLY and never mutates anything.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.performance_tables import record_result   # noqa: E402
from adaptive_learning.adaptive_policy_engine import (            # noqa: E402
    generate_adaptive_policy_report, AUTHORITY_LEVEL, POSTURE, MIN_SAMPLE,
)


def _seed(tmp, symbol, dimension, key, result, r, n):
    for _ in range(n):
        record_result(symbol, dimension, key, result, r, base_dir=tmp)


class TestPolicyFlags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_strong_expectancy_creates_boost(self):
        _seed(self._tmp, "MNQ", "playbook", "strong", "win", 0.30, MIN_SAMPLE)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "playbook": "strong"}, base_dir=self._tmp)
        self.assertEqual(rep["playbook_grade"], "strong")
        self.assertTrue(rep["confidence_boost_recommended"])
        self.assertFalse(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["trade_block_recommended"])

    def test_weak_expectancy_creates_penalty(self):
        _seed(self._tmp, "MNQ", "playbook", "strong", "loss", -0.20, MIN_SAMPLE)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "playbook": "strong"}, base_dir=self._tmp)
        self.assertEqual(rep["playbook_grade"], "weak")
        self.assertTrue(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["risk_reduction_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])

    def test_severe_degradation_creates_risk_reduction(self):
        _seed(self._tmp, "MNQ", "tool", "breaker", "loss", -0.35, MIN_SAMPLE)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "tool": "breaker"}, base_dir=self._tmp)
        self.assertEqual(rep["tool_grade"], "severe")
        self.assertTrue(rep["risk_reduction_recommended"])
        self.assertTrue(rep["confidence_penalty_recommended"])   # severe implies weak
        self.assertFalse(rep["confidence_boost_recommended"])

    def test_loss_streak_creates_block(self):
        # 4 consecutive losses at a shallow R (expectancy above the penalty band)
        _seed(self._tmp, "MNQ", "session", "new_york", "loss", -0.10, 4)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "session": "new_york"}, base_dir=self._tmp)
        self.assertTrue(rep["trade_block_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])
        self.assertTrue(any("trade_block" in a for a in rep["recommended_adjustments"]))

    def test_insufficient_sample_produces_nothing(self):
        _seed(self._tmp, "MNQ", "playbook", "strong", "win", 0.50, MIN_SAMPLE - 1)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "playbook": "strong"}, base_dir=self._tmp)
        self.assertEqual(rep["playbook_grade"], "insufficient_data")
        self.assertFalse(rep["confidence_boost_recommended"])
        self.assertFalse(rep["confidence_penalty_recommended"])

    def test_defensive_precedence_suppresses_boost(self):
        # playbook strong (would boost) but session severe (defensive) -> no boost
        _seed(self._tmp, "MNQ", "playbook", "strong", "win", 0.30, MIN_SAMPLE)
        _seed(self._tmp, "MNQ", "session", "new_york", "loss", -0.40, MIN_SAMPLE)
        rep = generate_adaptive_policy_report(
            {"symbol": "MNQ", "playbook": "strong", "session": "new_york"},
            base_dir=self._tmp)
        self.assertEqual(rep["playbook_grade"], "strong")
        self.assertEqual(rep["session_grade"], "severe")
        self.assertTrue(rep["risk_reduction_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])


class TestSymbolIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_policy_is_symbol_isolated(self):
        _seed(self._tmp, "MNQ", "playbook", "strong", "win", 0.40, MIN_SAMPLE)
        # same playbook key, different symbol -> no history -> neutral
        rep = generate_adaptive_policy_report(
            {"symbol": "MES", "playbook": "strong"}, base_dir=self._tmp)
        self.assertEqual(rep["playbook_grade"], "insufficient_data")
        self.assertFalse(rep["confidence_boost_recommended"])


class TestSafetyContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_report_is_observe_only_defensive(self):
        rep = generate_adaptive_policy_report({"symbol": "MNQ"}, base_dir=self._tmp)
        self.assertEqual(rep["authority_level"], "observe_only")
        self.assertEqual(AUTHORITY_LEVEL, "observe_only")
        self.assertEqual(rep["posture"], "DEFENSIVE_ONLY")
        self.assertEqual(POSTURE, "DEFENSIVE_ONLY")
        # neutral candidate (no history) never recommends anything
        for flag in ("confidence_boost_recommended", "confidence_penalty_recommended",
                     "risk_reduction_recommended", "trade_block_recommended"):
            self.assertFalse(rep[flag], flag)


if __name__ == "__main__":
    unittest.main()
