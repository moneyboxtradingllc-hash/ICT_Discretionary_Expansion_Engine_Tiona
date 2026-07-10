"""
ADAPT-LOOP-3B — Brain Thesis Quality locks (2026-07-10).

A correct thesis ≠ a correct closing price. Locks: draw parsing (honest none);
stop chain invalidation→opposing protected swing; resolution walk (fulfilled
before invalidation wins; invalidation first kills fulfillment; expiry;
protected violations tracked); trade-path milestones with in-bar stop-first
pessimism; per-metric coverage (each metric its own n); report cards refuse
conclusions under min_n; SEPARATE LEDGERS (thesis table never touches the
direction ledger file). Descriptive only — no authority surface exists.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.brain_thesis_quality import (      # noqa: E402
    parse_draw_price, derive_stop, grade_thesis_resolution, grade_trade_path,
    summarize, report_card, build_table, load_rows,
)

_T0 = datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)


def _bar(i, o, h, l, c):
    return {"timestamp": (_T0 + timedelta(minutes=i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c}


class TestExtraction(unittest.TestCase):
    def test_draw_price_parsing(self):
        self.assertEqual(parse_draw_price("sell_side@699.6"), 699.6)
        self.assertEqual(parse_draw_price("draw toward 708.25 then lower"), 708.25)
        self.assertIsNone(parse_draw_price("No active draw identified."))
        self.assertIsNone(parse_draw_price(None))

    def test_stop_chain_invalidation_then_opposing_swing(self):
        self.assertEqual(derive_stop("bearish", 709.1, {"level": 710.0}, None),
                         (709.1, "invalidation_level"))
        self.assertEqual(derive_stop("bearish", None, {"level": 710.0}, None),
                         (710.0, "protected_swing"))
        self.assertEqual(derive_stop("bullish", None, {"level": 710.0},
                                     {"level": 700.0}),
                         (700.0, "protected_swing"))
        self.assertEqual(derive_stop("bullish", None, {"level": 710.0}, None),
                         (None, None))


class TestThesisResolution(unittest.TestCase):
    def test_fulfilled_before_invalidation(self):
        # bearish: draw 699.0 below; price walks down and touches it
        fwd = [_bar(1, 700.5, 700.6, 700.0, 700.1),
               _bar(2, 700.1, 700.2, 698.9, 699.1)]
        out = grade_thesis_resolution(fwd, "bearish", 699.0, 701.0, None, None)
        self.assertEqual(out["resolution"], "fulfilled")
        self.assertTrue(out["liquidity_reached"])
        self.assertEqual(out["bars_to_fulfillment"], 2)
        self.assertFalse(out["thesis_invalidated"])

    def test_invalidated_first_kills_fulfillment(self):
        # THE mission example: stop crossed first, draw touched later — the
        # thesis is dead even though 'direction' eventually delivered
        fwd = [_bar(1, 700.5, 701.2, 700.4, 701.1),     # crosses 701.0 stop
               _bar(2, 701.1, 701.2, 698.9, 699.0)]     # then reaches the draw
        out = grade_thesis_resolution(fwd, "bearish", 699.0, 701.0, None, None)
        self.assertEqual(out["resolution"], "invalidated")
        self.assertEqual(out["bars_to_invalidation"], 1)
        self.assertFalse(out["liquidity_reached"])

    def test_expired_when_nothing_happens(self):
        fwd = [_bar(i, 700.0, 700.2, 699.9, 700.1) for i in range(1, 6)]
        out = grade_thesis_resolution(fwd, "bearish", 695.0, 705.0, None, None)
        self.assertEqual(out["resolution"], "expired")

    def test_protected_violations_tracked(self):
        fwd = [_bar(1, 700.0, 702.6, 699.9, 702.5)]     # violates PH 702.5
        out = grade_thesis_resolution(fwd, "bearish", 695.0, None,
                                      {"level": 702.5}, {"level": 690.0})
        self.assertTrue(out["protected_high_violated"])
        self.assertFalse(out["protected_low_violated"])

    def test_ungradeable_without_draw(self):
        out = grade_thesis_resolution([_bar(1, 1, 1, 1, 1)], "bearish",
                                      None, None, None, None)
        self.assertEqual(out["resolution"], "ungradeable")
        self.assertIsNone(out["liquidity_reached"])


class TestTradePath(unittest.TestCase):
    def test_milestones_before_stop(self):
        # entry 700.0, stop 701.0 (risk 1): reaches 2R (698.0), never 3R, no stop
        fwd = [_bar(1, 700.0, 700.2, 699.5, 699.6),
               _bar(2, 699.6, 699.7, 697.9, 698.2)]
        out = grade_trade_path(fwd, "bearish", 701.0)
        self.assertTrue(out["r1_before_stop"])
        self.assertTrue(out["r2_before_stop"])
        self.assertFalse(out["r3_before_stop"])
        self.assertFalse(out["stop_first"])
        self.assertEqual(out["bars_to_1r"], 2)
        self.assertGreaterEqual(out["mfe_r"], 2.0)

    def test_stop_first_pessimism_in_bar(self):
        # one bar spans stop AND +1R — pessimism books the stop
        fwd = [_bar(1, 700.0, 701.2, 698.8, 700.0)]
        out = grade_trade_path(fwd, "bearish", 701.0)
        self.assertTrue(out["stop_first"])
        self.assertFalse(out["r1_before_stop"])
        self.assertEqual(out["bars_to_stop"], 1)

    def test_none_without_stop_or_bad_side(self):
        self.assertIsNone(grade_trade_path([_bar(1, 1, 1, 1, 1)], "bearish", None))
        self.assertIsNone(grade_trade_path(
            [_bar(1, 700.0, 700.1, 699.9, 700.0)], "bearish", 699.0))


class TestCoverageAndCards(unittest.TestCase):
    def _row(self, resolution="fulfilled", liq=True, path=True, direction="bearish"):
        return {"direction": direction, "family": "liquidity_sweep_reversal",
                "res_resolution": resolution,
                "res_liquidity_reached": liq,
                "res_protected_high_violated": False,
                "res_protected_low_violated": None,
                "res_bars_to_fulfillment": 5 if resolution == "fulfilled" else None,
                "res_bars_to_invalidation": None,
                "path": ({"r1_before_stop": True, "r2_before_stop": False,
                          "r3_before_stop": False, "stop_first": False,
                          "mfe_r": 1.2, "mae_r": 0.4, "bars_to_1r": 4,
                          "bars_to_stop": None} if path else None),
                "realized_r": 1.0 if path else None}

    def test_each_metric_reports_own_n(self):
        rows = [self._row(), self._row(path=False),
                self._row(resolution="ungradeable", liq=None, path=False)]
        s = summarize(rows)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["thesis"]["n_gradeable"], 2)     # ungradeable excluded
        self.assertEqual(s["trade_path"]["n_with_stop"], 1)  # only stop-bearing
        self.assertEqual(s["trade_path"]["r1_before_stop_pct"], 1.0)

    def test_report_card_refuses_conclusions_under_min_n(self):
        rows = [self._row() for _ in range(3)]
        card = report_card(rows, min_n=10, direction="bearish")
        self.assertEqual(card["n"], 3)
        self.assertIn("no conclusions", card["note"])

    def test_report_card_filters(self):
        rows = [self._row(), self._row(direction="bullish")]
        card = report_card(rows, min_n=1, direction="bullish")
        self.assertEqual(card["n"], 1)


class TestSeparateLedgers(unittest.TestCase):
    def test_thesis_table_never_touches_direction_ledger(self):
        tmp = tempfile.mkdtemp()
        cdir = os.path.join(tmp, "candles")
        bdir = os.path.join(tmp, "brain")
        os.makedirs(cdir), os.makedirs(bdir)
        tape = [_bar(i, 700 + i * 0.05, 700.2 + i * 0.05,
                     699.9 + i * 0.05, 700.1 + i * 0.05) for i in range(1, 70)]
        with open(os.path.join(cdir, "20260708_QQQ.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"symbol": "QQQ", "date": "20260708",
                       "bar_count": len(tape), "candles": tape}, fh)
        with open(os.path.join(bdir, "20260708_100000_QQQ.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"timestamp": _T0.isoformat(), "symbol": "QQQ",
                       "source": "llm", "input_payload": {"protected_swings": {}},
                       "parsed_output": {"narrative_direction": "bullish",
                                         "recommended_playbook_family":
                                             "trend_continuation",
                                         "phase_confidence": 75,
                                         "active_draw": "buy_side@702.0",
                                         "invalidation_level": 699.0}}, fh)
        # pre-existing DIRECTION ledger must remain byte-identical
        os.makedirs(os.path.join(tmp, "QQQ"))
        dir_ledger = os.path.join(tmp, "QQQ", "brain_accuracy.json")
        with open(dir_ledger, "w", encoding="utf-8") as fh:
            fh.write('{"sentinel": true}')
        with patch.dict(os.environ, {"REPLAY_CANDLES_DIR": cdir,
                                     "AI_BRAIN_DIR": bdir,
                                     "LIVE_SNAPSHOTS_DIR": os.path.join(tmp, "none")}):
            t = build_table(["20260708"], "QQQ", base_dir=tmp)
        self.assertEqual(t["rows"], 1)
        self.assertEqual(t["ledger"], "brain_thesis_quality")
        self.assertEqual(t["overall"]["thesis"]["fulfilled_pct"], 1.0)
        with open(dir_ledger, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"sentinel": true}')   # untouched
        self.assertEqual(len(load_rows("QQQ", base_dir=tmp)), 1)


if __name__ == "__main__":
    unittest.main()
