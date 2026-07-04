"""
CAPITAL-1 — Capital Intelligence Engine regression lock.

The organism understands scars. Now it understands money.

TEST A: growth state detected (tier press, ceiling permitted, no contraction)
TEST B: expansion state detected (tier press_plus)
TEST C: defensive contraction detected (confidence penalty)
TEST D: preservation contraction detected (hard size reduction)
TEST E: critical lock detected (probation lock via trade_block)
TEST F: risk efficiency computed from journal truth
TEST G: confidence scaled correctly through the EXISTING mutation chain
TEST H: size scaled correctly through the EXISTING mutation chain
Plus: precedence (drawdown beats performance), probation baseline (weak
sample contributes nothing), never-boosts lock, fail-safe neutrality,
persist contract.

All I/O under temp dirs — never live capital memory.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.capital_intelligence_engine import (   # noqa: E402
    evaluate_capital_state, build_capital_metrics, track_capital,
    compute_risk_efficiency, compute_drawdown_pressure, compute_equity_health,
    STATE_GROWTH, STATE_EXPANSION, STATE_DEFENSIVE, STATE_PRESERVATION,
    STATE_CRITICAL, STATE_PROBATION, STATE_STABLE, HISTORY_FILE,
)
from adaptive_learning.adaptive_policy_engine import (        # noqa: E402
    generate_adaptive_policy_report,
)
from adaptive_learning.adaptive_mutation_engine import mutate_candidate  # noqa: E402


def _metrics(**over):
    m = {
        "equity": 100_000.0, "peak_equity": 100_000.0, "drawdown_pct": 0.0,
        "daily_pnl": 0.0, "weekly_pnl": 0.0, "daily_loss_limit": 500.0,
        "risk_remaining": 500.0, "risk_efficiency": None,
        "closed_trades": 12, "expectancy": 0.0, "win_rate": 0.5,
        "profit_factor": 1.0,
    }
    m.update(over)
    return m


class TestA_Growth(unittest.TestCase):
    def test_growth_detected_ceiling_permitted(self):
        rep = evaluate_capital_state(_metrics(
            expectancy=0.3, weekly_pnl=800.0, drawdown_pct=0.004))
        self.assertEqual(rep["capital_state"], STATE_GROWTH)
        self.assertEqual(rep["aggression_tier"], "press")
        self.assertEqual(rep["capital_mutation"], {})   # permit, not contract
        self.assertIn("ceiling permitted", " ".join(rep["capital_actions"]))


class TestB_Expansion(unittest.TestCase):
    def test_expansion_detected(self):
        rep = evaluate_capital_state(_metrics(
            expectancy=0.7, profit_factor=2.1, weekly_pnl=1500.0,
            drawdown_pct=0.002))
        self.assertEqual(rep["capital_state"], STATE_EXPANSION)
        self.assertEqual(rep["aggression_tier"], "press_plus")
        self.assertEqual(rep["capital_mutation"], {})


class TestC_Defensive(unittest.TestCase):
    def test_drawdown_triggers_defensive(self):
        rep = evaluate_capital_state(_metrics(drawdown_pct=0.04))
        self.assertEqual(rep["capital_state"], STATE_DEFENSIVE)
        self.assertEqual(rep["capital_mutation"], {"confidence_penalty": True})

    def test_daily_loss_half_limit_triggers_defensive(self):
        rep = evaluate_capital_state(_metrics(daily_pnl=-260.0))
        self.assertEqual(rep["capital_state"], STATE_DEFENSIVE)


class TestD_Preservation(unittest.TestCase):
    def test_deep_drawdown_triggers_preservation(self):
        rep = evaluate_capital_state(_metrics(drawdown_pct=0.07))
        self.assertEqual(rep["capital_state"], STATE_PRESERVATION)
        self.assertTrue(rep["capital_mutation"]["risk_reduction"])
        self.assertTrue(rep["capital_mutation"]["confidence_penalty"])

    def test_weekly_bleed_triggers_preservation(self):
        rep = evaluate_capital_state(_metrics(weekly_pnl=-1100.0))
        self.assertEqual(rep["capital_state"], STATE_PRESERVATION)


class TestE_Critical(unittest.TestCase):
    def test_near_hard_loss_limit_locks(self):
        rep = evaluate_capital_state(_metrics(daily_pnl=-410.0))
        self.assertEqual(rep["capital_state"], STATE_CRITICAL)
        self.assertTrue(rep["capital_mutation"]["trade_block"])
        self.assertEqual(rep["aggression_tier"], "lock")
        self.assertIn("probation lock", " ".join(rep["capital_actions"]))

    def test_ten_percent_drawdown_locks(self):
        rep = evaluate_capital_state(_metrics(drawdown_pct=0.11))
        self.assertEqual(rep["capital_state"], STATE_CRITICAL)

    def test_drawdown_beats_performance(self):
        # excellent stats cannot outvote capital pressure (precedence)
        rep = evaluate_capital_state(_metrics(
            expectancy=1.0, profit_factor=3.0, weekly_pnl=2000.0,
            drawdown_pct=0.07))
        self.assertEqual(rep["capital_state"], STATE_PRESERVATION)


class TestF_RiskEfficiency(unittest.TestCase):
    def test_efficiency_from_journal_truth(self):
        tmp = tempfile.mkdtemp()
        day = {"date": "20260706", "symbol": "QQQ", "trades": [
            {"order_status": "closed", "realized_pnl": 150.0, "risk_dollars": 500.0},
            {"order_status": "closed", "realized_pnl": -50.0, "risk_dollars": 500.0},
            {"order_status": "rejected", "realized_pnl": None, "risk_dollars": 500.0},
        ]}
        with open(os.path.join(tmp, "20260706_QQQ_paper_trades.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(day, fh)
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = tmp
        try:
            eff = compute_risk_efficiency()
            self.assertAlmostEqual(eff, 0.1, places=6)   # +100 / 1000 risked
            m = build_capital_metrics("QQQ", {"equity": 100_100.0},
                                      today="20260706",
                                      base_dir=tempfile.mkdtemp())
            self.assertEqual(m["risk_efficiency"], 0.1)
            self.assertEqual(m["daily_pnl"], 100.0)
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev

    def test_pressure_and_health_scores(self):
        self.assertEqual(compute_drawdown_pressure({"drawdown_pct": 0.05}), 50)
        self.assertEqual(compute_drawdown_pressure({"drawdown_pct": 0.2}), 100)
        self.assertEqual(compute_equity_health(_metrics()), 100)
        self.assertLess(compute_equity_health(_metrics(
            drawdown_pct=0.05, daily_pnl=-100.0)), 50)


class TestGH_ExistingChainScaling(unittest.TestCase):
    """G/H — capital flags flow through the UNCHANGED policy+mutation chain."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._cand = {"symbol": "QQQ", "playbook": "sweep", "tool": "fvg",
                      "session": "morning", "regime": "trend",
                      "volatility": "normal"}

    def _policy(self, capital_metrics):
        return generate_adaptive_policy_report(
            self._cand, base_dir=self._tmp, today="2026-07-06",
            capital=evaluate_capital_state(capital_metrics))

    def test_G_confidence_scaled_correctly(self):
        rep = self._policy(_metrics(drawdown_pct=0.04))          # defensive
        self.assertTrue(rep["confidence_penalty_recommended"])
        mut = mutate_candidate({"confidence": 60, "qty": 4}, rep)
        self.assertEqual(mut["new_confidence"], 54.0)            # -10% exact
        self.assertEqual(mut["new_qty"], 4)                      # size untouched
        self.assertEqual(rep["capital"]["capital_state"], STATE_DEFENSIVE)

    def test_H_size_scaled_correctly(self):
        rep = self._policy(_metrics(drawdown_pct=0.07))          # preservation
        self.assertTrue(rep["risk_reduction_recommended"])
        mut = mutate_candidate({"confidence": 60, "qty": 4}, rep)
        self.assertEqual(mut["new_qty"], 2)                      # halved, exact
        self.assertFalse(mut["trade_blocked"])

    def test_critical_locks_through_chain(self):
        rep = self._policy(_metrics(daily_pnl=-450.0))           # critical
        self.assertTrue(rep["trade_block_recommended"])
        mut = mutate_candidate({"confidence": 60, "qty": 4}, rep)
        self.assertTrue(mut["trade_blocked"])

    def test_growth_never_boosts_never_contracts(self):
        rep = self._policy(_metrics(expectancy=0.4, weekly_pnl=900.0))
        self.assertFalse(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["risk_reduction_recommended"])
        self.assertFalse(rep["trade_block_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])    # NEVER up
        mut = mutate_candidate({"confidence": 60, "qty": 4}, rep)
        self.assertEqual(mut["new_confidence"], 60)              # untouched
        self.assertEqual(mut["new_qty"], 4)                      # ceiling, not above

    def test_probation_weak_sample_contributes_nothing(self):
        rep = self._policy(_metrics(closed_trades=5))
        self.assertEqual(rep["capital"]["capital_state"], STATE_PROBATION)
        self.assertFalse(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["trade_block_recommended"])


class TestFailSafeAndPersistence(unittest.TestCase):
    def test_failsafe_contributes_nothing(self):
        jtmp = tempfile.mkdtemp()
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = jtmp
        try:
            rep = track_capital("QQQ", account={}, base_dir=tempfile.mkdtemp())
            self.assertIn(rep["capital_state"], (STATE_PROBATION, STATE_STABLE))
            self.assertEqual(rep["capital_mutation"], {})
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev

    def test_stale_journal_losses_do_not_contract_fresh_week(self):
        """Three-week-old losses must NOT put a fresh Monday into preservation."""
        jtmp = tempfile.mkdtemp()
        day = {"date": "20260610", "symbol": "QQQ", "trades": [
            {"order_status": "closed", "realized_pnl": -2900.0,
             "risk_dollars": 500.0}]}
        with open(os.path.join(jtmp, "20260610_QQQ_paper_trades.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(day, fh)
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = jtmp
        try:
            m = build_capital_metrics("QQQ", {"equity": 100_000.0},
                                      today="20260706",
                                      base_dir=tempfile.mkdtemp())
            self.assertEqual(m["weekly_pnl"], 0.0)   # outside the 7-day window
            self.assertEqual(m["daily_pnl"], 0.0)
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev

    def test_track_capital_persists_peak_history(self):
        tmp = tempfile.mkdtemp()
        jtmp = tempfile.mkdtemp()
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = jtmp
        try:
            track_capital("QQQ", account={"equity": 101_000.0},
                          today="20260706", base_dir=tmp)
            track_capital("QQQ", account={"equity": 100_400.0},
                          today="20260707", base_dir=tmp)
            hist = json.load(open(os.path.join(tmp, "ACCOUNT", HISTORY_FILE),
                                  encoding="utf-8"))
            self.assertEqual(hist["peak_equity"], 101_000.0)     # peak retained
            self.assertEqual(hist["last_equity"], 100_400.0)
            self.assertIn("20260706", hist["daily_anchors"])
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev

    def test_read_only_when_persist_false(self):
        tmp = tempfile.mkdtemp()
        jtmp = tempfile.mkdtemp()
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = jtmp
        try:
            track_capital("QQQ", account={"equity": 99_000.0},
                          today="20260706", base_dir=tmp, persist=False)
            self.assertFalse(os.path.exists(
                os.path.join(tmp, "ACCOUNT", HISTORY_FILE)))
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev


if __name__ == "__main__":
    unittest.main()
