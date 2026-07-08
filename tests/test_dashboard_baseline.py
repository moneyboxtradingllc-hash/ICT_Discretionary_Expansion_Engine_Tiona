"""
DASHBOARD-BASELINE — clean-baseline enforcement: regression lock.

2026-07-08 defect: the live scan printed "Dashboard: 5 trades | WR 0.0% |
AvgR -1.40". Source: load_memory_records surfaced the STALE_PRE_AI June batch
(5 closed losses: -4.81/-0.03/-0.12/-0.72/-1.34 -> avg -1.40, WR 0%) from
data/paper_trades + data/intent_archive. HTF-MEM-1 quarantined those from the
performance TABLES but this OBSERVE_ONLY read path was never epoch-gated, so
they polluted the dashboard, memory-search, recommendations, experience, and
the Brain's context summary. No authority (all observe_only) — a source-of-
truth repair. Fix: epoch-gate load_memory_records at the source using the
EXISTING organism_epoch() boundary; pre-epoch is excluded from the active
baseline (retained on disk, reachable only via include_pre_epoch=True).

Locks:
  * stale pre-epoch trades excluded from active memory + dashboard
  * post-baseline trades DO count
  * shadow/observe-only nature preserved (authority_level unchanged)
  * archival accessor (include_pre_epoch=True) still returns everything
  * CLEAN_BASELINE audit line + baseline field emitted
  * timestampless records fail closed to pre-epoch (conservative)
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import memory_search.memory_record_builder as mrb                       # noqa: E402
from memory_search.memory_record_builder import (                       # noqa: E402
    load_memory_records, load_memory_records_partitioned, _is_pre_epoch,
)
from performance_intelligence.dashboard_builder import (                # noqa: E402
    build_dashboard, build_dashboard_from_records,
)
from performance_intelligence.dashboard_summary import build_dashboard_summary  # noqa: E402
from ai_layer.ai_snapshot_formatter import format_dashboard_line        # noqa: E402


def _trade(tid, day, realized_r=-1.0, status="closed"):
    return {"trade_id": tid, "symbol": "QQQ",
            "timestamp": f"{day}T100000", "order_status": status,
            "realized_r": realized_r, "playbook": "trend_continuation",
            "direction": "short", "session": "morning_continuation"}


EPOCH = "20260706"


class TestEpochPredicate(unittest.TestCase):
    @patch.dict(os.environ, {"ORGANISM_EPOCH_DATE": EPOCH})
    def test_pre_epoch_trade_flagged(self):
        self.assertTrue(_is_pre_epoch(_trade("A", "20260609")))
        self.assertTrue(_is_pre_epoch(_trade("B", "20260705")))

    @patch.dict(os.environ, {"ORGANISM_EPOCH_DATE": EPOCH})
    def test_post_epoch_trade_kept(self):
        self.assertFalse(_is_pre_epoch(_trade("C", "20260706")))
        self.assertFalse(_is_pre_epoch(_trade("D", "20260708")))

    def test_timestampless_fails_closed_to_pre_epoch(self):
        self.assertTrue(_is_pre_epoch({"trade_id": "X", "timestamp": ""}))
        self.assertTrue(_is_pre_epoch({"trade_id": "Y"}))


class TestSourceGate(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"ORGANISM_EPOCH_DATE": EPOCH})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _fixture(self, intent_dir, trades_dir, days):
        import json
        trades = [_trade(f"T_{d}", d) for d in days]
        with open(os.path.join(trades_dir, "20260101_QQQ_trades.json"), "w") as f:
            json.dump(trades, f)

    def test_stale_june_excluded_valid_july_kept(self):
        import tempfile
        with tempfile.TemporaryDirectory() as idir, \
             tempfile.TemporaryDirectory() as tdir:
            self._fixture(idir, tdir,
                          ["20260609", "20260610", "20260611", "20260708"])
            with patch.object(mrb, "_INTENT_DIR", idir), \
                 patch.object(mrb, "_TRADES_DIR", tdir):
                active = load_memory_records("QQQ")
                allrec = load_memory_records("QQQ", include_pre_epoch=True)
                part_active, part_pre = load_memory_records_partitioned("QQQ")
        self.assertEqual(len(active), 1)                 # only the July trade
        self.assertEqual(active[0]["trade_id"], "T_20260708")
        self.assertEqual(len(allrec), 4)                 # archival sees all
        self.assertEqual(len(part_active), 1)
        self.assertEqual(len(part_pre), 3)


class TestDashboardMetrics(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"ORGANISM_EPOCH_DATE": EPOCH})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_stale_5_trade_dashboard_purged_from_live_line(self):
        """The reported symptom: 5 June losses must not surface."""
        import tempfile, json
        june = [_trade(f"T{i}", d, realized_r=r) for i, (d, r) in enumerate([
            ("20260609", -4.81), ("20260609", -0.03), ("20260609", -0.12),
            ("20260610", -0.72), ("20260611", -1.34)])]
        with tempfile.TemporaryDirectory() as idir, \
             tempfile.TemporaryDirectory() as tdir:
            with open(os.path.join(tdir, "20260101_QQQ_trades.json"), "w") as f:
                json.dump(june, f)
            with patch.object(mrb, "_INTENT_DIR", idir), \
                 patch.object(mrb, "_TRADES_DIR", tdir):
                dash = build_dashboard("QQQ")
                summary = build_dashboard_summary(dash)
        self.assertEqual(dash["closed_trades"], 0)
        self.assertEqual(dash["pre_epoch_excluded"], 5)
        self.assertEqual(summary["sample_size"], 0)
        self.assertEqual(summary["baseline"], "clean_baseline")
        line = format_dashboard_line(summary)
        self.assertIn("CLEAN_BASELINE", line)
        self.assertIn("0 validated trades", line)
        self.assertIn("5 pre-baseline archived", line)
        self.assertNotIn("WR 0.0%", line)
        self.assertNotIn("-1.40", line)

    def test_post_baseline_trades_do_count(self):
        import tempfile, json
        july = [_trade("J1", "20260708", realized_r=2.0),
                _trade("J2", "20260708", realized_r=-1.0)]
        with tempfile.TemporaryDirectory() as idir, \
             tempfile.TemporaryDirectory() as tdir:
            with open(os.path.join(tdir, "20260101_QQQ_trades.json"), "w") as f:
                json.dump(july, f)
            with patch.object(mrb, "_INTENT_DIR", idir), \
                 patch.object(mrb, "_TRADES_DIR", tdir):
                dash = build_dashboard("QQQ")
                summary = build_dashboard_summary(dash)
        self.assertEqual(dash["closed_trades"], 2)
        self.assertEqual(dash["pre_epoch_excluded"], 0)
        self.assertEqual(summary["baseline"], "active")
        self.assertNotIn("CLEAN_BASELINE", format_dashboard_line(summary))

    def test_dashboard_stays_observe_only(self):
        dash = build_dashboard("QQQ")
        self.assertEqual(dash["authority_level"], "observe_only")
        self.assertEqual(dash["confidence_modifier"], 0)
        self.assertEqual(build_dashboard_summary(dash)["authority_level"],
                         "observe_only")

    def test_from_records_path_unchanged_counts_explicit_records(self):
        """build_dashboard_from_records (tests/pipeline) counts what it's given
        — the epoch gate lives at the disk-loading source, not here."""
        recs = [{"trade_id": "T1", "outcome": "loss", "realized_r": -1.0,
                 "record_source": "paper_trade", "_status": "closed"}]
        dash = build_dashboard_from_records(recs)
        self.assertEqual(dash["closed_trades"], 1)


class TestCleanBaselineLine(unittest.TestCase):
    def test_line_with_no_exclusions(self):
        summary = build_dashboard_summary(
            {"enabled": True, "closed_trades": 0, "pre_epoch_excluded": 0})
        line = format_dashboard_line(summary)
        self.assertEqual(line,
                         "Dashboard: CLEAN_BASELINE | 0 validated trades | OBSERVE_ONLY")


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_no_baseline_logic_in_authorities(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution",  "order_builder.py"),
                ("risk",             "risk_governor.py"),
                ("shared_context",   "council.py"),
                ("decision_authority", "decision_engine.py"),
                ("qualification",    "trade_qualification_engine.py"),
        ):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("DASHBOARD-BASELINE", body, f"{pkg}/{fname}")
            self.assertNotIn("load_memory_records", body, f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
