"""
Adaptive Learning — Phase 3A: Symbol-native performance tables.

Proves closed outcomes aggregate into per-symbol expectancy tables: symbol
folders + the five table files are created on write, win/loss/breakeven counts
and expectancy math are correct, loss streaks increment and reset, and there is
ZERO symbol contamination (a write for one instrument never touches another).
All writes are redirected to a temp dir so the real store is untouched.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.performance_tables import (   # noqa: E402
    update_performance_tables, record_result, get_bucket, load_symbol_tables,
    TABLE_FILES,
)


def _outcome(result=None, r=None, symbol="MNQ", playbook="strong", tool="breaker",
             session="new_york", regime="trend", volatility="high") -> tuple:
    """Return (outcome_dict, entry_record) shaped like the scar-writer inputs."""
    outcome = {
        "instrument":       symbol,
        "playbook":         playbook,
        "session":          session,
        "regime":           regime,
        "volatility_state": volatility,
        "realized_r":       r,
        "result":           result,
    }
    entry = {
        "symbol":               symbol,
        "market_regime_family": regime,
        "volatility_state":     volatility,
        "snapshot_summary":     {"tool": tool, "playbook": playbook, "session": session},
    }
    return outcome, entry


class TestTableCreation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_symbol_folder_and_all_five_files_created(self):
        outcome, entry = _outcome(result="win", r=1.0, symbol="MNQ")
        res = update_performance_tables(outcome, entry, base_dir=self._tmp)
        self.assertFalse(res["skipped"])
        self.assertEqual(res["symbol"], "MNQ")
        self.assertEqual(sorted(res["updated"]), sorted(TABLE_FILES.keys()))
        sym_dir = os.path.join(self._tmp, "MNQ")
        self.assertTrue(os.path.isdir(sym_dir))
        for fname in TABLE_FILES.values():
            self.assertTrue(os.path.isfile(os.path.join(sym_dir, fname)), fname)


class TestBucketMath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_win_loss_counts(self):
        for res, r in [("win", 1.0), ("win", 0.5), ("loss", -1.0)]:
            o, e = _outcome(result=res, r=r, playbook="strong")
            update_performance_tables(o, e, base_dir=self._tmp)
        b = get_bucket("MNQ", "playbook", "strong", base_dir=self._tmp)
        self.assertEqual(b["wins"], 2)
        self.assertEqual(b["losses"], 1)
        self.assertEqual(b["trades"], 3)

    def test_expectancy_average_r(self):
        for res, r in [("win", 1.0), ("loss", -0.5), ("win", 0.5)]:
            o, e = _outcome(result=res, r=r, playbook="strong")
            update_performance_tables(o, e, base_dir=self._tmp)
        b = get_bucket("MNQ", "playbook", "strong", base_dir=self._tmp)
        # sum_r = 1.0 - 0.5 + 0.5 = 1.0 over 3 trades -> 0.3333...
        self.assertAlmostEqual(b["sum_r"], 1.0, places=6)
        self.assertAlmostEqual(b["expectancy"], 1.0 / 3.0, places=5)

    def test_loss_streak_increments_and_resets(self):
        seq = [("loss", -0.3), ("loss", -0.3), ("loss", -0.3)]
        for res, r in seq:
            o, e = _outcome(result=res, r=r, tool="breaker")
            update_performance_tables(o, e, base_dir=self._tmp)
        b = get_bucket("MNQ", "tool", "breaker", base_dir=self._tmp)
        self.assertEqual(b["loss_streak"], 3)
        # a win resets the streak to zero
        o, e = _outcome(result="win", r=1.0, tool="breaker")
        update_performance_tables(o, e, base_dir=self._tmp)
        b = get_bucket("MNQ", "tool", "breaker", base_dir=self._tmp)
        self.assertEqual(b["loss_streak"], 0)

    def test_breakeven_does_not_touch_streak(self):
        record_result("MNQ", "session", "new_york", "loss", -0.2, base_dir=self._tmp)
        record_result("MNQ", "session", "new_york", "breakeven", 0.0, base_dir=self._tmp)
        b = get_bucket("MNQ", "session", "new_york", base_dir=self._tmp)
        self.assertEqual(b["loss_streak"], 1)
        self.assertEqual(b["breakevens"], 1)

    def test_result_derived_from_r_when_absent(self):
        o, e = _outcome(result=None, r=0.8, playbook="strong")
        res = update_performance_tables(o, e, base_dir=self._tmp)
        self.assertEqual(res["result"], "win")
        b = get_bucket("MNQ", "playbook", "strong", base_dir=self._tmp)
        self.assertEqual(b["wins"], 1)

    def test_unclassifiable_outcome_skipped(self):
        o, e = _outcome(result=None, r=None)
        res = update_performance_tables(o, e, base_dir=self._tmp)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "unclassifiable_outcome")


class TestSymbolIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_no_cross_symbol_contamination(self):
        # write 3 MNQ trades; MES must remain completely empty
        for _ in range(3):
            o, e = _outcome(result="win", r=0.5, symbol="MNQ", playbook="strong")
            update_performance_tables(o, e, base_dir=self._tmp)
        mnq = get_bucket("MNQ", "playbook", "strong", base_dir=self._tmp)
        self.assertEqual(mnq["trades"], 3)

        mes_tables = load_symbol_tables("MES", base_dir=self._tmp)
        self.assertEqual(mes_tables["playbook"], {})
        self.assertFalse(os.path.isdir(os.path.join(self._tmp, "MES")))

        # a later MES write must not disturb MNQ's totals
        o, e = _outcome(result="loss", r=-1.0, symbol="MES", playbook="strong")
        update_performance_tables(o, e, base_dir=self._tmp)
        mnq_after = get_bucket("MNQ", "playbook", "strong", base_dir=self._tmp)
        self.assertEqual(mnq_after["trades"], 3)
        mes_after = get_bucket("MES", "playbook", "strong", base_dir=self._tmp)
        self.assertEqual(mes_after["trades"], 1)


if __name__ == "__main__":
    unittest.main()
