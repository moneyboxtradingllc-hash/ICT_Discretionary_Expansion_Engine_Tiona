"""
Phase 5D — Performance Intelligence Dashboard Tests.
16 tests covering: empty dashboard, sample metrics, dimension analytics,
AI metrics, memory metrics, quality levels, safety invariants.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from performance_intelligence.performance_metrics  import (
    calculate_trade_metrics,
    calculate_regime_metrics,
    calculate_session_metrics,
    calculate_playbook_metrics,
    calculate_ai_metrics,
    find_best_worst,
)
from performance_intelligence.dashboard_builder    import build_dashboard_from_records
from performance_intelligence.performance_report   import build_performance_report
from performance_intelligence.dashboard_summary    import build_dashboard_summary
from live_scan.snapshot_store                      import save_snapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

_CLOSED = {"win", "loss", "breakeven"}


def _trade(
    trade_id="T_001",
    outcome="win",
    realized_r=1.5,
    realized_pnl=150.0,
    playbook="liquidity_sweep_reversal",
    regime="trend_up",
    session="ny_open",
    direction="bullish",
    ai_value_label="helpful",
    ai_was_directionally_correct=True,
    ai_agreement_with_playbook=True,
    close_reason="target_hit",
):
    status = "closed" if outcome in _CLOSED else "open"
    r_val  = realized_r   if outcome in _CLOSED else None
    pnl    = realized_pnl if outcome in _CLOSED else None
    return {
        "trade_id":                    trade_id,
        "symbol":                      "QQQ",
        "outcome":                     outcome,
        "realized_r":                  r_val,
        "realized_pnl":                pnl,
        "mfe":                         abs(r_val) * 1.2 if r_val else None,
        "mae":                         abs(r_val) * 0.3 if r_val else None,
        "playbook":                    playbook,
        "market_regime_label":         regime,
        "session":                     session,
        "direction":                   direction,
        "ai_value_label":              ai_value_label,
        "ai_was_directionally_correct": ai_was_directionally_correct,
        "ai_agreement_with_playbook":  ai_agreement_with_playbook,
        "close_reason":                close_reason,
        "_source":                     "paper_trades",
        "_status":                     status,
    }


def _snapshot(symbol="QQQ"):
    return {
        "symbol":        symbol,
        "session":       "ny_open",
        "qualification": {"status": "candidate", "opportunity_score": 70},
        "playbook":      {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "toolbox":       {"preferred_tool": "bullish_ifvg"},
        "market_regime": {"enabled": True, "regime_label": "trend_up",
                          "regime_family": "trend", "confidence": 65,
                          "volatility_state": "normal", "expansion_state": "neutral"},
        "confidence_fusion": {"mechanical_score": 70},
        "ai_discretionary":  {"ai_confidence": 60},
        "intent_score":      {"gated_score": 70},
    }


def _make_sample_records(n_win=6, n_loss=4, playbook="liquidity_sweep_reversal",
                          regime="trend_up", session="ny_open"):
    records = []
    for i in range(n_win):
        records.append(_trade(f"T_W{i}", outcome="win",  realized_r=1.5,
                              playbook=playbook, regime=regime, session=session))
    for i in range(n_loss):
        records.append(_trade(f"T_L{i}", outcome="loss", realized_r=-1.0,
                              playbook=playbook, regime=regime, session=session,
                              close_reason="stop_loss"))
    return records


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Empty Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmptyDashboard(unittest.TestCase):

    def test_01_dashboard_builds_with_no_trades(self):
        d = build_dashboard_from_records([])
        self.assertTrue(d["enabled"])
        self.assertEqual(d["total_trades"],  0)
        self.assertEqual(d["closed_trades"], 0)
        self.assertIsNone(d["win_rate"])
        self.assertIsNone(d["average_r"])
        self.assertIsNone(d["best_playbook"])
        self.assertIsNone(d["best_regime"])
        self.assertIsNone(d["best_session"])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Sample Trade Metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestSampleMetrics(unittest.TestCase):

    def test_02_dashboard_builds_with_sample_trades(self):
        records = _make_sample_records(6, 4)
        d = build_dashboard_from_records(records)
        self.assertEqual(d["total_trades"],  10)
        self.assertEqual(d["closed_trades"], 10)
        self.assertEqual(d["wins"],          6)
        self.assertEqual(d["losses"],        4)

    def test_03_win_rate_calculated_correctly(self):
        records = _make_sample_records(7, 3)
        m = calculate_trade_metrics(records)
        self.assertAlmostEqual(m["win_rate"], 70.0, places=0)

    def test_04_average_r_calculated_correctly(self):
        # 4 wins at +1.5R, 2 losses at -1.0R → avg = (4*1.5 + 2*(-1.0)) / 6 = 4.0/6
        records = [
            _trade("W1", outcome="win",  realized_r=1.5),
            _trade("W2", outcome="win",  realized_r=1.5),
            _trade("W3", outcome="win",  realized_r=1.5),
            _trade("W4", outcome="win",  realized_r=1.5),
            _trade("L1", outcome="loss", realized_r=-1.0),
            _trade("L2", outcome="loss", realized_r=-1.0),
        ]
        m = calculate_trade_metrics(records)
        self.assertAlmostEqual(m["average_r"], round((4*1.5 + 2*(-1.0)) / 6, 2), places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Dimension Analytics
# ═══════════════════════════════════════════════════════════════════════════════

class TestDimensionAnalytics(unittest.TestCase):

    def _mixed_records(self):
        return [
            # Good playbook: 4W/1L = 80%
            _trade("A1", playbook="lsr",   regime="trend_up",  session="ny_open",
                   outcome="win",  realized_r=1.5),
            _trade("A2", playbook="lsr",   regime="trend_up",  session="ny_open",
                   outcome="win",  realized_r=1.5),
            _trade("A3", playbook="lsr",   regime="trend_up",  session="ny_open",
                   outcome="win",  realized_r=1.5),
            _trade("A4", playbook="lsr",   regime="trend_up",  session="ny_open",
                   outcome="win",  realized_r=1.5),
            _trade("A5", playbook="lsr",   regime="trend_up",  session="ny_open",
                   outcome="loss", realized_r=-1.0),
            # Bad playbook: 1W/4L = 20%
            _trade("B1", playbook="chop_trade", regime="chop", session="london",
                   outcome="win",  realized_r=1.0),
            _trade("B2", playbook="chop_trade", regime="chop", session="london",
                   outcome="loss", realized_r=-1.0),
            _trade("B3", playbook="chop_trade", regime="chop", session="london",
                   outcome="loss", realized_r=-1.0),
            _trade("B4", playbook="chop_trade", regime="chop", session="london",
                   outcome="loss", realized_r=-1.0),
            _trade("B5", playbook="chop_trade", regime="chop", session="london",
                   outcome="loss", realized_r=-1.0),
        ]

    def test_05_best_playbook_detected(self):
        records = self._mixed_records()
        pb_m = calculate_playbook_metrics(records)
        best, _ = find_best_worst(pb_m)
        self.assertEqual(best, "lsr")

    def test_06_worst_playbook_detected(self):
        records = self._mixed_records()
        pb_m = calculate_playbook_metrics(records)
        _, worst = find_best_worst(pb_m)
        self.assertEqual(worst, "chop_trade")

    def test_07_best_regime_detected(self):
        records = self._mixed_records()
        r_m = calculate_regime_metrics(records)
        best, _ = find_best_worst(r_m)
        self.assertEqual(best, "trend_up")

    def test_08_worst_regime_detected(self):
        records = self._mixed_records()
        r_m = calculate_regime_metrics(records)
        _, worst = find_best_worst(r_m)
        self.assertEqual(worst, "chop")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AI and Memory Metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiAndMemoryMetrics(unittest.TestCase):

    def test_09_ai_metrics_handled_safely_when_missing(self):
        records = [_trade("T1", ai_value_label="unknown", ai_was_directionally_correct=None,
                          ai_agreement_with_playbook=None)]
        m = calculate_ai_metrics(records)
        self.assertFalse(m["ai_outcome_available"])
        self.assertIsNone(m["ai_helpful_rate"])

    def test_09b_ai_metrics_computed_when_available(self):
        records = [
            _trade("T1", ai_value_label="helpful",  ai_was_directionally_correct=True),
            _trade("T2", ai_value_label="helpful",  ai_was_directionally_correct=True),
            _trade("T3", ai_value_label="harmful",  ai_was_directionally_correct=False),
            _trade("T4", ai_value_label="helpful",  ai_was_directionally_correct=True),
        ]
        m = calculate_ai_metrics(records)
        self.assertTrue(m["ai_outcome_available"])
        self.assertAlmostEqual(m["ai_helpful_rate"], 75.0, places=0)
        self.assertAlmostEqual(m["ai_correct_rate"], 75.0, places=0)

    def test_10_memory_metrics_handled_safely(self):
        d = build_dashboard_from_records([], memory_summary=None)
        self.assertEqual(d["memory_quality"],     "none")
        self.assertEqual(d["closed_match_count"], 0)

    def test_10b_memory_quality_passed_through(self):
        ms = {"memory_quality": "developing", "closed_match_count": 7, "best_similarity": 0.85}
        d  = build_dashboard_from_records([], memory_summary=ms)
        self.assertEqual(d["memory_quality"], "developing")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Performance Quality Levels
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerformanceQuality(unittest.TestCase):

    def _dashboard_with_n(self, n):
        recs = [_trade(f"T{i}", outcome="win" if i % 2 == 0 else "loss",
                        realized_r=1.0 if i % 2 == 0 else -1.0) for i in range(n)]
        return build_dashboard_from_records(recs)

    def test_11_quality_none_with_zero_trades(self):
        report = build_performance_report(build_dashboard_from_records([]))
        self.assertEqual(report["performance_quality"], "none")

    def test_11b_quality_limited_under_25(self):
        report = build_performance_report(self._dashboard_with_n(10))
        self.assertEqual(report["performance_quality"], "limited")

    def test_11c_quality_developing_25_to_99(self):
        report = build_performance_report(self._dashboard_with_n(30))
        self.assertEqual(report["performance_quality"], "developing")

    def test_11d_quality_meaningful_100_plus(self):
        report = build_performance_report(self._dashboard_with_n(100))
        self.assertEqual(report["performance_quality"], "meaningful")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Safety Invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def test_12_authority_level_always_observe_only(self):
        for records in [[], _make_sample_records(6, 4)]:
            d = build_dashboard_from_records(records)
            self.assertEqual(d["authority_level"],     "observe_only")
            self.assertEqual(d["confidence_modifier"], 0)
            s = build_dashboard_summary(d)
            self.assertEqual(s["authority_level"],     "observe_only")
            self.assertEqual(s["confidence_modifier"], 0)

    def test_13_confidence_modifier_always_zero(self):
        d = build_dashboard_from_records(_make_sample_records())
        self.assertEqual(d["confidence_modifier"], 0)
        s = build_dashboard_summary(d)
        self.assertEqual(s["confidence_modifier"], 0)

    def test_16_no_execution_behavior_changed(self):
        d = build_dashboard_from_records(_make_sample_records())
        self.assertNotIn("allow_execution",    d)
        self.assertNotIn("trade_authorized",   d)
        self.assertNotIn("gate_status",        d)
        self.assertNotIn("risk_tier",          d)
        self.assertNotIn("confidence_modifier_delta", d)
        s = build_dashboard_summary(d)
        self.assertNotIn("allow_execution",    s)
        self.assertNotIn("trade_authorized",   s)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. AI Input and Snapshot Store
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):

    def test_15_snapshot_store_contains_dashboard(self):
        import live_scan.snapshot_store as ss_mod
        snap = _snapshot()
        # DECON-3: save_snapshot is post-runtime-only — model a resolved runtime
        snap.update({"decision_authority": {}, "execution_gate": {},
                     "paper_execution": {}, "position_monitor": {},
                     "trade_reconciliation": {}})
        snap["performance_dashboard"] = build_dashboard_summary(
            build_dashboard_from_records(_make_sample_records(6, 4))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(ss_mod, "STORE_DIR", tmpdir):
                fpath = save_snapshot(snap, "QQQ")
            with open(fpath) as f:
                saved = json.load(f)
        self.assertIn("performance_dashboard", saved)
        pd = saved["performance_dashboard"]
        self.assertEqual(pd["authority_level"],     "observe_only")
        self.assertEqual(pd["confidence_modifier"],  0)
        self.assertIn("performance_quality",         pd)


if __name__ == "__main__":
    unittest.main()
