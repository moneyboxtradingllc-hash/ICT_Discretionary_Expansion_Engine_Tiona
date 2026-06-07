"""
Phase 3B — Experience Correlation Engine unit tests.

Verifies:
  1.  empty data returns insufficient sample
  2.  sample confidence buckets (none/low/medium/high)
  3.  dimension grouping works
  4.  win/loss rate calculation works
  5.  average_r calculation works
  6.  strongest positive correlations sorted correctly
  7.  strongest negative correlations sorted correctly
  8.  authority_level always observe_only
  9.  confidence_modifier always 0
  10. no execution/decision side effects
  11. compact snapshot includes experience_correlation
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import experience_intelligence.experience_summary  as es_mod
import experience_intelligence.experience_correlation as ec_mod

from experience_intelligence.experience_correlation import (
    build_correlation, correlation_confidence, _confidence_label,
)
from experience_intelligence.correlation_report import (
    build_correlation_report,
)
from experience_intelligence.experience_summary import build_experience_summary
from experience_intelligence.experience_report  import build_experience_report
from ai_layer.ai_snapshot_formatter import format_correlation_line
from live_scan.snapshot_store import save_snapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _trade(pnl=100.0, risk=100.0,
           playbook="liquidity_sweep_reversal",
           session="open",
           direction="bullish",
           tool="bullish_fvg",
           qual_status="qualified",
           risk_tier="green",
           lifecycle_phase="entry_ready"):
    return {
        "order_status":  "closed",
        "realized_pnl":  pnl,
        "risk_dollars":  risk,
        "timestamp":     "20260601T100000",
        "closed_at":     "20260601T103000",
        "snapshot_summary": {
            "session": session,
            "playbook": {
                "selected_playbook": playbook,
                "direction":         direction,
            },
            "qualification":  {"status": qual_status},
            "risk":           {"risk_tier": risk_tier},
            "toolbox":        {"preferred_tool": tool},
            "decision_authority": {"decision": "execute"},
            "ai_debate":      {"enabled": False},
            "setup_lifecycle": {"current_phase": lifecycle_phase},
            "intent_score":   {"gated_quality": "high_quality"},
        },
    }


def _win(playbook="liquidity_sweep_reversal", **kw):
    return _trade(pnl=100.0, risk=100.0, playbook=playbook, **kw)


def _loss(playbook="range_expansion_fade", **kw):
    return _trade(pnl=-100.0, risk=100.0, playbook=playbook, **kw)


def _snapshot_fixture():
    return {
        "playbook":      {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "qualification": {"status": "qualified"},
        "trade_intent":  {"preferred_tool": "bullish_fvg"},
        "session":       "open",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Empty data
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmptyData(unittest.TestCase):

    def test_no_trades_returns_zero_sample(self):
        corr = build_correlation([])
        self.assertEqual(corr["sample_size"], 0)
        self.assertEqual(corr["dimension_reports"], {})
        self.assertEqual(corr["strongest_positive_correlations"], [])
        self.assertEqual(corr["strongest_negative_correlations"], [])

    def test_no_trades_includes_warning(self):
        corr = build_correlation([])
        self.assertTrue(len(corr["warnings"]) > 0)
        self.assertIn("Insufficient", corr["warnings"][0])

    def test_report_empty_correlation_is_safe(self):
        report = build_correlation_report({})
        self.assertEqual(report["sample_size"],            0)
        self.assertEqual(report["authority_level"],        "observe_only")
        self.assertEqual(report["confidence_modifier"],    0)
        self.assertEqual(report["correlation_confidence"], "none")

    def test_exception_returns_safe_default(self):
        corr = build_correlation(None)   # None iteration raises TypeError
        self.assertEqual(corr["sample_size"],         0)
        self.assertEqual(corr["authority_level"],     "observe_only")
        self.assertEqual(corr["confidence_modifier"], 0)
        self.assertIn("correlation build error", corr["notes"][0])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Confidence buckets
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceBuckets(unittest.TestCase):

    def test_none_when_zero(self):
        self.assertEqual(_confidence_label(0),  "none")

    def test_low_one_to_nineteen(self):
        for n in (1, 5, 19):
            self.assertEqual(_confidence_label(n), "low", f"n={n}")

    def test_medium_twenty_to_fortynine(self):
        for n in (20, 35, 49):
            self.assertEqual(_confidence_label(n), "medium", f"n={n}")

    def test_high_fifty_plus(self):
        for n in (50, 100, 1000):
            self.assertEqual(_confidence_label(n), "high", f"n={n}")

    def test_correlation_confidence_public_function(self):
        self.assertEqual(correlation_confidence(0),  "none")
        self.assertEqual(correlation_confidence(15), "low")
        self.assertEqual(correlation_confidence(30), "medium")
        self.assertEqual(correlation_confidence(60), "high")

    def test_report_confidence_reflects_sample(self):
        for n, expected in ((0, "none"), (10, "low"), (25, "medium"), (75, "high")):
            corr   = {"sample_size": n, "warnings": [], "notes": []}
            report = build_correlation_report(corr)
            self.assertEqual(report["correlation_confidence"], expected, f"n={n}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Dimension grouping
# ═══════════════════════════════════════════════════════════════════════════════

class TestDimensionGrouping(unittest.TestCase):

    def test_playbook_dimension_grouped(self):
        trades = [
            _win(playbook="liquidity_sweep_reversal"),
            _win(playbook="liquidity_sweep_reversal"),
            _loss(playbook="range_expansion_fade"),
        ]
        corr = build_correlation(trades)
        pb   = corr["dimension_reports"]["playbook"]
        self.assertIn("liquidity_sweep_reversal", pb)
        self.assertIn("range_expansion_fade",     pb)
        self.assertEqual(pb["liquidity_sweep_reversal"]["sample_size"], 2)
        self.assertEqual(pb["range_expansion_fade"]["sample_size"],     1)

    def test_session_dimension_grouped(self):
        trades = [
            _trade(pnl=100.0, session="open"),
            _trade(pnl=100.0, session="open"),
            _trade(pnl=-50.0, session="mid_day"),
        ]
        corr     = build_correlation(trades)
        sessions = corr["dimension_reports"]["session"]
        self.assertIn("open",    sessions)
        self.assertIn("mid_day", sessions)

    def test_missing_dimension_value_skipped(self):
        trade = _trade(pnl=100.0)
        trade["snapshot_summary"]["playbook"]["selected_playbook"] = ""
        corr = build_correlation([trade])
        pb   = corr["dimension_reports"]["playbook"]
        self.assertEqual(len(pb), 0)   # empty string not grouped

    def test_all_10_dimensions_present(self):
        from experience_intelligence.experience_correlation import _DIMENSIONS
        corr = build_correlation([_win()])
        for dim in _DIMENSIONS:
            self.assertIn(dim, corr["dimension_reports"], f"dimension missing: {dim}")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Win/loss rate calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWinLossRate(unittest.TestCase):

    def test_win_rate_two_wins_one_loss(self):
        # All 3 trades share session="open" — same group, rates computable at n=3
        trades = [
            _trade(pnl=100.0, session="open"),
            _trade(pnl=100.0, session="open"),
            _trade(pnl=-50.0, session="open"),
        ]
        corr  = build_correlation(trades)
        entry = corr["dimension_reports"]["session"]["open"]
        self.assertIsNotNone(entry.get("win_rate"))
        self.assertAlmostEqual(entry["win_rate"], 66.7, places=0)

    def test_all_losses_win_rate_zero(self):
        trades = [_loss(playbook="test_pb") for _ in range(4)]
        corr   = build_correlation(trades)
        entry  = corr["dimension_reports"]["playbook"]["test_pb"]
        self.assertEqual(entry["win_rate"],  0.0)
        self.assertEqual(entry["loss_rate"], 100.0)

    def test_rate_none_below_min_sample(self):
        # Only 2 trades — below _MIN_SAMPLE_RATE=3
        trades = [_win(), _win()]
        corr   = build_correlation(trades)
        entry  = corr["dimension_reports"]["playbook"]["liquidity_sweep_reversal"]
        self.assertIsNone(entry["win_rate"])
        self.assertIsNone(entry["loss_rate"])

    def test_win_rate_computed_at_three(self):
        trades = [_win(), _win(), _loss()]
        corr   = build_correlation(trades)
        # session="open" for all 3
        entry = corr["dimension_reports"]["session"]["open"]
        self.assertIsNotNone(entry["win_rate"])
        self.assertAlmostEqual(entry["win_rate"],  66.7, places=0)
        self.assertAlmostEqual(entry["loss_rate"], 33.3, places=0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Average R calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAverageR(unittest.TestCase):

    def test_average_r_positive(self):
        trades = [
            _trade(pnl=200.0, risk=100.0, session="open"),   # +2R
            _trade(pnl=200.0, risk=100.0, session="open"),   # +2R
            _trade(pnl=200.0, risk=100.0, session="open"),   # +2R
        ]
        corr  = build_correlation(trades)
        entry = corr["dimension_reports"]["session"]["open"]
        self.assertAlmostEqual(entry["average_r"], 2.0, places=2)

    def test_average_r_mixed(self):
        trades = [
            _trade(pnl=200.0, risk=100.0, session="open"),   # +2R
            _trade(pnl=-100.0, risk=100.0, session="open"),  # -1R
            _trade(pnl=200.0, risk=100.0, session="open"),   # +2R
        ]
        corr  = build_correlation(trades)
        entry = corr["dimension_reports"]["session"]["open"]
        self.assertAlmostEqual(entry["average_r"], 1.0, places=2)

    def test_average_r_none_below_min_sample(self):
        trades = [_trade(pnl=100.0, session="open"), _trade(pnl=100.0, session="open")]
        corr  = build_correlation(trades)
        entry = corr["dimension_reports"]["session"]["open"]
        self.assertIsNone(entry["average_r"])

    def test_average_mfe_mae_always_none_phase_3b(self):
        trades = [_win() for _ in range(5)]
        corr   = build_correlation(trades)
        for entry in corr["dimension_reports"]["playbook"].values():
            self.assertIsNone(entry["average_mfe"])
            self.assertIsNone(entry["average_mae"])


# ═══════════════════════════════════════════════════════════════════════════════
# 6 & 7. Strongest correlations — sort order and thresholds
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrongestCorrelations(unittest.TestCase):

    def _bulk_trades(self, playbook: str, n_wins: int, n_losses: int) -> list:
        return (
            [_win(playbook=playbook) for _ in range(n_wins)] +
            [_loss(playbook=playbook) for _ in range(n_losses)]
        )

    def test_positive_correlations_sorted_desc(self):
        # good_pb: 12/12 wins = 100% WR (n=12 >= _MIN_SAMPLE_STRONG=10)
        # ok_pb:   10/12 = 83% WR
        trades = (
            self._bulk_trades("good_pb", n_wins=12, n_losses=0) +
            self._bulk_trades("ok_pb",   n_wins=10, n_losses=2)
        )
        corr = build_correlation(trades)
        pos  = corr["strongest_positive_correlations"]
        self.assertGreater(len(pos), 0)
        # First entry should have higher WR than second
        if len(pos) >= 2:
            wr0 = float(pos[0].split(":")[1].split("%")[0].strip())
            wr1 = float(pos[1].split(":")[1].split("%")[0].strip())
            self.assertGreaterEqual(wr0, wr1)

    def test_negative_correlations_sorted_asc(self):
        # bad_pb:  2/12 wins = 16% WR
        # worse_pb: 0/12 wins = 0% WR
        trades = (
            self._bulk_trades("bad_pb",   n_wins=2,  n_losses=10) +
            self._bulk_trades("worse_pb", n_wins=0,  n_losses=12)
        )
        corr = build_correlation(trades)
        neg  = corr["strongest_negative_correlations"]
        self.assertGreater(len(neg), 0)
        # First entry should have lower WR than second
        if len(neg) >= 2:
            wr0 = float(neg[0].split(":")[1].split("%")[0].strip())
            wr1 = float(neg[1].split(":")[1].split("%")[0].strip())
            self.assertLessEqual(wr0, wr1)

    def test_positive_requires_wr_above_50(self):
        # 5/10 wins = exactly 50% — break-even, must NOT appear in positive correlations
        trades = self._bulk_trades("borderline_pb", n_wins=5, n_losses=5)
        corr   = build_correlation(trades)
        for entry in corr["strongest_positive_correlations"]:
            self.assertNotIn("borderline_pb", entry)

    def test_below_min_strong_not_in_correlations(self):
        # Only 9 trades — below _MIN_SAMPLE_STRONG=10
        trades = [_win(playbook="small_pb") for _ in range(9)]
        corr   = build_correlation(trades)
        for entry in corr.get("strongest_positive_correlations", []):
            self.assertNotIn("small_pb", entry)

    def test_format_correlation_line_with_data(self):
        trades = self._bulk_trades("great_pb", n_wins=12, n_losses=0)
        corr   = build_correlation(trades)
        report = build_correlation_report(corr)
        line   = format_correlation_line(report)
        self.assertIn("OBSERVE_ONLY", line)
        if report["strongest_positive_correlations"]:
            self.assertIn("+", line)


# ═══════════════════════════════════════════════════════════════════════════════
# 8 & 9. Authority always observe_only / confidence_modifier always 0
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthorityConstraints(unittest.TestCase):

    def test_authority_always_observe_only_empty(self):
        corr = build_correlation([])
        self.assertEqual(corr["authority_level"],     "observe_only")
        self.assertEqual(corr["confidence_modifier"], 0)

    def test_authority_always_observe_only_with_trades(self):
        trades = [_win() for _ in range(60)]
        corr   = build_correlation(trades)
        self.assertEqual(corr["authority_level"],     "observe_only")
        self.assertEqual(corr["confidence_modifier"], 0)

    def test_report_authority_always_observe_only(self):
        report = build_correlation_report(build_correlation([_win() for _ in range(60)]))
        self.assertEqual(report["authority_level"],     "observe_only")
        self.assertEqual(report["confidence_modifier"], 0)

    def test_exception_safe_default_authority(self):
        corr = build_correlation(None)
        self.assertEqual(corr["authority_level"],     "observe_only")
        self.assertEqual(corr["confidence_modifier"], 0)

    @patch.object(es_mod, "load_completed_trades", return_value=[])
    @patch.object(es_mod, "find_similar_setups",   return_value=[])
    def test_summary_correlation_fields_safe_when_empty(self, *_):
        summary = build_experience_summary(_snapshot_fixture(), "QQQ")
        self.assertFalse(summary["correlation_available"])
        self.assertEqual(summary["correlation_confidence"], "none")
        self.assertEqual(summary["confidence_modifier"],    0)
        self.assertEqual(summary["authority_level"],        "observe_only")

    @patch.object(es_mod, "load_completed_trades",
                  return_value=[_win() for _ in range(60)])
    @patch.object(es_mod, "find_similar_setups", return_value=[])
    def test_summary_correlation_available_with_trades(self, *_):
        summary = build_experience_summary(_snapshot_fixture(), "QQQ")
        self.assertTrue(summary["correlation_available"])
        self.assertIn(summary["correlation_confidence"], ("low", "medium", "high"))

    def test_report_correlation_fields_in_empty_report(self):
        report = build_experience_report({})
        self.assertFalse(report["correlation_available"])
        self.assertEqual(report["correlation_confidence"], "none")
        self.assertEqual(report["authority_level"],        "observe_only")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. No execution/decision side effects
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoSideEffects(unittest.TestCase):

    def test_correlation_has_no_forbidden_keys(self):
        trades = [_win() for _ in range(10)]
        corr   = build_correlation(trades)
        forbidden = {
            "decision_authority", "execution_gate", "paper_execution",
            "position_monitor", "stop_enforcer", "paper_activation",
        }
        self.assertTrue(forbidden.isdisjoint(set(corr.keys())))

    def test_report_has_no_forbidden_keys(self):
        report = build_correlation_report(build_correlation([_win()]))
        forbidden = {
            "decision_authority", "execution_gate", "paper_execution",
            "position_monitor", "stop_enforcer",
        }
        self.assertTrue(forbidden.isdisjoint(set(report.keys())))

    def test_build_correlation_does_not_mutate_input(self):
        trades  = [_win(), _loss()]
        orignal = [dict(t) for t in trades]
        build_correlation(trades)
        for original, after in zip(orignal, trades):
            self.assertEqual(original, after)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Compact snapshot includes experience_correlation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotStore(unittest.TestCase):

    def _full_snapshot(self):
        """Minimal snapshot that satisfies save_snapshot's expected keys."""
        return {
            "timestamp":   "20260601T100000",
            "session":     "open",
            "qualification": {},
            "playbook":    {},
            "risk":        {},
            "toolbox":     {"tool_candidates": []},
            "state_transition": {},
            "setup_lifecycle":  {},
            "ai_debate":        {},
            "decision_authority": {},
            "execution_gate":   {},
            "trade_intent":     {},
            "intent_score":     {},
            "intent_archive":   {},
            "paper_execution":  {},
            "position_monitor": {},
            "stop_enforcer":    {},
            "experience_summary": {
                "experience_enabled": True, "authority_level": "observe_only",
                "sample_size": 0, "historical_matches": 0, "confidence_modifier": 0,
                "notes": [], "correlation_available": False, "correlation_confidence": "none",
            },
            "experience_report": {},
            "experience_correlation": {
                "enabled":                         True,
                "authority_level":                  "observe_only",
                "sample_size":                      5,
                "confidence_modifier":              0,
                "correlation_confidence":           "low",
                "strongest_positive_correlations":  ["playbook=good: 80.0% WR over 10 samples"],
                "strongest_negative_correlations":  [],
                "warnings":                         [],
            },
            "paper_activation_plan": {},
            "paper_activation":      {},
            "operational_readiness": {},
            "activation_controller": {},
            "ai_discretionary":      {},
            "confidence_fusion":     {},
            "ai_context": {
                "market_narrative": "", "confidence_score": 0,
                "confidence_tier": "", "summary": "",
            },
        }

    def test_experience_correlation_in_saved_snapshot(self):
        snap = self._full_snapshot()
        with tempfile.TemporaryDirectory() as tmpdir:
            import live_scan.snapshot_store as ss_mod
            original_dir = ss_mod.STORE_DIR
            ss_mod.STORE_DIR = tmpdir
            try:
                fp = save_snapshot(snap, "QQQ")
                with open(fp, "r", encoding="utf-8") as f:
                    saved = json.load(f)
            finally:
                ss_mod.STORE_DIR = original_dir

        self.assertIn("experience_correlation", saved)
        ec = saved["experience_correlation"]
        self.assertEqual(ec["authority_level"],     "observe_only")
        self.assertEqual(ec["confidence_modifier"],  0)
        self.assertEqual(ec["sample_size"],          5)
        self.assertEqual(ec["correlation_confidence"], "low")
        self.assertIn("playbook=good", ec["strongest_positive_correlations"][0])

    def test_experience_correlation_always_in_snapshot_even_empty(self):
        snap = self._full_snapshot()
        snap["experience_correlation"] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            import live_scan.snapshot_store as ss_mod
            original_dir = ss_mod.STORE_DIR
            ss_mod.STORE_DIR = tmpdir
            try:
                fp = save_snapshot(snap, "QQQ")
                with open(fp, "r", encoding="utf-8") as f:
                    saved = json.load(f)
            finally:
                ss_mod.STORE_DIR = original_dir

        self.assertIn("experience_correlation", saved)
        self.assertEqual(saved["experience_correlation"]["confidence_modifier"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatter
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrelationFormatter(unittest.TestCase):

    def test_none_returns_empty(self):
        self.assertEqual(format_correlation_line(None), "")
        self.assertEqual(format_correlation_line({}),   "")

    def test_disabled_returns_empty(self):
        self.assertEqual(format_correlation_line({"enabled": False}), "")

    def test_zero_sample_shows_insufficient(self):
        corr = {"enabled": True, "sample_size": 0,
                "strongest_positive_correlations": [],
                "strongest_negative_correlations": []}
        line = format_correlation_line(corr)
        self.assertIn("insufficient", line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_no_correlations_shows_insufficient(self):
        corr = {"enabled": True, "sample_size": 30,
                "strongest_positive_correlations": [],
                "strongest_negative_correlations": []}
        line = format_correlation_line(corr)
        self.assertIn("insufficient", line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_positive_correlation_shown(self):
        corr = {"enabled": True, "sample_size": 50,
                "strongest_positive_correlations": ["playbook=great: 80.0% WR over 12 samples"],
                "strongest_negative_correlations": []}
        line = format_correlation_line(corr)
        self.assertIn("+", line)
        self.assertIn("playbook=great", line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_negative_correlation_shown(self):
        corr = {"enabled": True, "sample_size": 50,
                "strongest_positive_correlations": [],
                "strongest_negative_correlations": ["session=mid_day: 30.0% WR over 10 samples"]}
        line = format_correlation_line(corr)
        self.assertIn("-", line)
        self.assertIn("session=mid_day", line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_both_positive_and_negative_shown(self):
        corr = {"enabled": True, "sample_size": 60,
                "strongest_positive_correlations": ["playbook=A: 75.0% WR over 20 samples"],
                "strongest_negative_correlations": ["session=B: 25.0% WR over 12 samples"]}
        line = format_correlation_line(corr)
        self.assertIn("+", line)
        self.assertIn("-", line)
        self.assertIn("playbook=A", line)
        self.assertIn("session=B", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
