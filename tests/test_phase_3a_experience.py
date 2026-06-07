"""
Phase 3A — Experience Intelligence unit tests.

Verifies:
  * similarity scoring and matching
  * metrics computation including edge cases
  * sample-size quality thresholds
  * authority_level always 'observe_only'
  * confidence_modifier always 0
  * no execution, decision, or confidence changes
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import experience_intelligence.experience_summary  as es_mod
import experience_intelligence.experience_query    as eq_mod

from experience_intelligence.experience_similarity import (
    extract_current_attrs, score_record_similarity, find_matching_records,
)
from experience_intelligence.experience_metrics import compute_metrics
from experience_intelligence.experience_summary import build_experience_summary
from experience_intelligence.experience_report  import (
    build_experience_report, _quality_label,
)
from ai_layer.ai_snapshot_formatter import format_experience_line


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _snapshot(playbook="bullish_po3_reversal", direction="bullish",
              tool="bullish_fvg", qual="qualified", session="open"):
    return {
        "playbook":      {"selected_playbook": playbook, "direction": direction},
        "qualification": {"status": qual},
        "trade_intent":  {"preferred_tool": tool},
        "session":       session,
    }


def _intent_record(playbook="bullish_po3_reversal", direction="bullish",
                   tool="bullish_fvg", quality="qualified"):
    return {
        "playbook":            playbook,
        "direction":           direction,
        "preferred_tool":      tool,
        "quality_at_creation": quality,
        "session_at_creation": "",
        "status":              "expired",
        "mfe":                 2.5,
        "mae":                 0.8,
    }


def _closed_trade(pnl=100.0, risk=100.0, ts="20260601T100000", closed_at="20260601T103000"):
    return {
        "order_status":  "closed",
        "realized_pnl":  pnl,
        "risk_dollars":  risk,
        "timestamp":     ts,
        "closed_at":     closed_at,
        "snapshot_summary": {},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Similarity Scoring
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimilarityScoring(unittest.TestCase):

    def test_perfect_match_scores_high(self):
        snap = _snapshot()
        rec  = _intent_record()
        attrs = extract_current_attrs(snap)
        score = score_record_similarity(rec, attrs)
        # playbook(40) + direction(20) + tool(25) + qual(10) = 95/100 = 0.95
        self.assertGreaterEqual(score, 0.90)

    def test_no_match_scores_zero(self):
        snap = _snapshot(playbook="bearish_sweep_reversal", direction="bearish",
                         tool="bearish_ob", qual="no_trade")
        rec  = _intent_record()
        attrs = extract_current_attrs(snap)
        score = score_record_similarity(rec, attrs)
        self.assertLessEqual(score, 0.15)

    def test_partial_tool_family_credit(self):
        snap = _snapshot(tool="bullish_fvg")
        rec  = _intent_record(tool="bearish_fvg")   # same family, opposite direction
        attrs = extract_current_attrs(snap)
        score = score_record_similarity(rec, attrs)
        # tool partial credit (25//2=12) when direction differs
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_find_matching_records_filters_by_threshold(self):
        snap    = _snapshot()
        records = [_intent_record(), _intent_record(playbook="unrelated", direction="bearish")]
        attrs   = extract_current_attrs(snap)
        matches = find_matching_records(records, attrs, min_score=0.8)
        self.assertEqual(len(matches), 1)
        self.assertIn("similarity_score", matches[0])

    def test_find_matching_records_sorted_descending(self):
        snap = _snapshot()
        records = [
            _intent_record(tool="bearish_fvg"),           # partial tool match
            _intent_record(),                              # full match
        ]
        attrs   = extract_current_attrs(snap)
        matches = find_matching_records(records, attrs, min_score=0.0)
        self.assertGreaterEqual(
            matches[0]["similarity_score"], matches[-1]["similarity_score"]
        )

    def test_extract_current_attrs_fields(self):
        snap  = _snapshot(playbook="bp", direction="bearish", tool="t", qual="elite", session="mid_day")
        attrs = extract_current_attrs(snap)
        self.assertEqual(attrs["playbook"],           "bp")
        self.assertEqual(attrs["direction"],          "bearish")
        self.assertEqual(attrs["preferred_tool"],     "t")
        self.assertEqual(attrs["qualification_tier"], "elite")
        self.assertEqual(attrs["session"],            "mid_day")

    def test_unknown_fields_do_not_crash(self):
        score = score_record_similarity({}, {})
        self.assertEqual(score, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics Computation
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetricsComputation(unittest.TestCase):

    def test_empty_trades_returns_zero_sample(self):
        m = compute_metrics([])
        self.assertEqual(m["sample_size"], 0)
        self.assertIsNone(m["win_rate"])
        self.assertIsNone(m["loss_rate"])
        self.assertIsNone(m["average_r"])

    def test_single_win_trade(self):
        trades = [_closed_trade(pnl=150.0, risk=100.0)]
        m = compute_metrics(trades)
        self.assertEqual(m["sample_size"], 1)
        self.assertAlmostEqual(m["average_r"], 1.5, places=2)
        self.assertIsNone(m["win_rate"])     # needs >= 3 for rate metrics

    def test_win_rate_computed_at_3_trades(self):
        trades = [
            _closed_trade(pnl=100.0, risk=100.0),
            _closed_trade(pnl=100.0, risk=100.0),
            _closed_trade(pnl=-50.0, risk=100.0),
        ]
        m = compute_metrics(trades)
        self.assertIsNotNone(m["win_rate"])
        self.assertAlmostEqual(m["win_rate"], 66.7, places=0)
        self.assertAlmostEqual(m["loss_rate"], 33.3, places=0)

    def test_average_r_computed(self):
        trades = [
            _closed_trade(pnl=200.0, risk=100.0),   # +2R
            _closed_trade(pnl=-100.0, risk=100.0),  # -1R
        ]
        m = compute_metrics(trades)
        self.assertAlmostEqual(m["average_r"], 0.5, places=2)

    def test_hold_time_computed(self):
        trades = [_closed_trade(ts="20260601T100000", closed_at="20260601T103000")]
        m = compute_metrics(trades)
        self.assertIsNotNone(m["average_hold_time"])
        self.assertAlmostEqual(m["average_hold_time"], 30.0, places=1)

    def test_average_mfe_mae_are_none_phase_3a(self):
        trades = [_closed_trade()]
        m = compute_metrics(trades)
        self.assertIsNone(m["average_mfe"])   # Phase 3B: intent archive linkage
        self.assertIsNone(m["average_mae"])

    def test_all_losses_win_rate_zero(self):
        trades = [_closed_trade(pnl=-50.0) for _ in range(5)]
        m = compute_metrics(trades)
        self.assertIsNotNone(m["win_rate"])
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["loss_rate"], 100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Sample-Size Quality Thresholds
# ═══════════════════════════════════════════════════════════════════════════════

class TestQualityThresholds(unittest.TestCase):

    def test_insufficient_below_20(self):
        for n in (0, 1, 10, 19):
            self.assertEqual(_quality_label(n), "insufficient", f"n={n}")

    def test_developing_20_to_49(self):
        for n in (20, 30, 49):
            self.assertEqual(_quality_label(n), "developing", f"n={n}")

    def test_meaningful_50_plus(self):
        for n in (50, 100, 500):
            self.assertEqual(_quality_label(n), "meaningful", f"n={n}")

    def test_report_quality_field_matches_threshold(self):
        for n, expected in ((0, "insufficient"), (25, "developing"), (75, "meaningful")):
            summary = {"sample_size": n, "historical_matches": 0, "notes": []}
            report  = build_experience_report(summary)
            self.assertEqual(report["experience_quality"], expected, f"n={n}")


# ═══════════════════════════════════════════════════════════════════════════════
# Authority Always OBSERVE_ONLY / confidence_modifier Always 0
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthorityConstraints(unittest.TestCase):

    @patch.object(es_mod, "load_completed_trades", return_value=[])
    @patch.object(es_mod, "find_similar_setups",   return_value=[])
    def test_authority_always_observe_only_zero_trades(self, *_):
        summary = build_experience_summary(_snapshot(), "QQQ")
        self.assertEqual(summary["authority_level"],     "observe_only")
        self.assertEqual(summary["confidence_modifier"], 0)

    @patch.object(es_mod, "load_completed_trades",
                  return_value=[_closed_trade() for _ in range(55)])
    @patch.object(es_mod, "find_similar_setups", return_value=[_intent_record()])
    def test_authority_still_observe_only_with_many_trades(self, *_):
        summary = build_experience_summary(_snapshot(), "QQQ")
        self.assertEqual(summary["authority_level"],     "observe_only")
        self.assertEqual(summary["confidence_modifier"], 0)

    @patch.object(es_mod, "load_completed_trades", return_value=[])
    @patch.object(es_mod, "find_similar_setups",   return_value=[])
    def test_report_authority_always_observe_only(self, *_):
        summary = build_experience_summary(_snapshot(), "QQQ")
        report  = build_experience_report(summary)
        self.assertEqual(report["authority_level"], "observe_only")

    def test_empty_report_authority_observe_only(self):
        report = build_experience_report({})
        self.assertEqual(report["authority_level"], "observe_only")

    @patch.object(es_mod, "load_completed_trades", return_value=[])
    @patch.object(es_mod, "find_similar_setups",   return_value=[])
    def test_experience_never_modifies_snapshot_decision_fields(self, *_):
        snap    = _snapshot()
        summary = build_experience_summary(snap, "QQQ")
        # Experience must not add or modify any execution/decision key
        forbidden_keys = {
            "decision_authority", "execution_gate", "paper_execution",
            "position_monitor", "stop_enforcer",
        }
        self.assertTrue(forbidden_keys.isdisjoint(set(summary.keys())))

    @patch.object(es_mod, "load_completed_trades", return_value=[])
    @patch.object(es_mod, "find_similar_setups",   return_value=[])
    def test_exception_in_build_returns_safe_default(self, *_):
        # Passing None as snapshot forces AttributeError inside _build
        # We need PAPER_ACTIVATION_MODE irrelevant here — just test safety
        with patch.object(es_mod, "find_similar_setups", side_effect=RuntimeError("boom")):
            summary = build_experience_summary(None, "QQQ")
        self.assertEqual(summary["confidence_modifier"], 0)
        self.assertEqual(summary["authority_level"],     "observe_only")
        self.assertFalse(summary["armed"] if "armed" in summary else False)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatter
# ═══════════════════════════════════════════════════════════════════════════════

class TestExperienceFormatter(unittest.TestCase):

    def test_zero_sample_shows_insufficient(self):
        exp  = {"experience_enabled": True, "sample_size": 0,
                "win_rate": None, "average_r": None}
        line = format_experience_line(exp)
        self.assertIn("OBSERVE_ONLY", line)
        self.assertIn("Insufficient", line)
        self.assertIn("0", line)

    def test_developing_shows_insufficient_label(self):
        exp  = {"experience_enabled": True, "sample_size": 5,
                "win_rate": None, "average_r": None}
        line = format_experience_line(exp)
        self.assertIn("Insufficient", line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_meaningful_shows_stats(self):
        exp  = {"experience_enabled": True, "sample_size": 60,
                "win_rate": 58.0, "average_r": 1.2}
        line = format_experience_line(exp)
        self.assertIn("60 setups",   line)
        self.assertIn("WR 58%",      line)
        self.assertIn("Avg +1.2R",   line)
        self.assertIn("OBSERVE_ONLY", line)

    def test_negative_r_shows_minus(self):
        exp  = {"experience_enabled": True, "sample_size": 50,
                "win_rate": 40.0, "average_r": -0.5}
        line = format_experience_line(exp)
        self.assertIn("-0.5R", line)

    def test_none_returns_empty(self):
        self.assertEqual(format_experience_line(None), "")
        self.assertEqual(format_experience_line({}),   "")

    def test_disabled_returns_empty(self):
        exp = {"experience_enabled": False, "sample_size": 100}
        self.assertEqual(format_experience_line(exp), "")


# ═══════════════════════════════════════════════════════════════════════════════
# Query — file-based (uses temp directories or empty dirs)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExperienceQuery(unittest.TestCase):

    @patch.object(eq_mod, "_ARCHIVE_DIR", "/nonexistent/path")
    def test_no_archive_returns_empty(self):
        from experience_intelligence.experience_query import load_all_intent_records
        records = load_all_intent_records("QQQ", days=5)
        self.assertEqual(records, [])

    @patch.object(eq_mod, "_TRADES_DIR", "/nonexistent/path")
    def test_no_trades_returns_empty(self):
        from experience_intelligence.experience_query import load_completed_trades
        trades = load_completed_trades("QQQ", days=5)
        self.assertEqual(trades, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
