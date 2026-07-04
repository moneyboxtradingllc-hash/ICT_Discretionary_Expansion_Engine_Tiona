"""
DECON-2 — Performance table purification: strict write gate + idempotency.

Proves the adaptive substrate can only learn from real, reconciled, forward
trades: unreconciled / synthetic / null-execution / timestamp-less /
pnl-less / dimensionless writes are rejected at the gate; a valid trade folds
exactly once (idempotency ledger) no matter how many times it is replayed; and
the exact fixture shape that contaminated the live tables (the 1A.5 runtime
test entry, which has no execution id) can no longer write at all.

All writes go to a temp dir — this suite never touches live adaptive state.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.performance_tables import (   # noqa: E402
    update_performance_tables, validate_performance_write, compute_write_key,
    get_bucket, LEDGER_FILE,
)


def _real_trade(**over) -> tuple:
    """(outcome, entry) mirroring a REAL reconciled Alpaca paper trade
    (modeled on PT_QQQ_20260710T115837 from the live journal)."""
    outcome = {
        "instrument":       "QQQ",
        "status":           "closed",
        "entry_timestamp":  "20260710T115838",
        "session":          "lunch",
        "regime":           "range_bound",
        "volatility_state": "unstable",
        "playbook":         "liquidity_sweep_reversal",
        "realized_r":       -0.7173,
        "realized_pnl":     -358.55,
        "result":           None,
    }
    entry = {
        "symbol":               "QQQ",
        "trade_id":             "PT_QQQ_20260710T115837",
        "alpaca_order_id":      "60dd2291-e100-4b73-a001-000000000000",
        "timestamp":            "20260710T115838",
        "closed_at":            "20260710T145032",
        "market_regime_family": "range",
        "volatility_state":     "unstable",
        "snapshot_summary":     {"tool": "bearish_ifvg",
                                 "playbook": "liquidity_sweep_reversal",
                                 "session": "lunch"},
    }
    outcome.update({k: v for k, v in over.items() if k in outcome})
    entry.update({k: v for k, v in over.items() if k in entry})
    return outcome, entry


class _Sandboxed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def _write(self, outcome, entry):
        return update_performance_tables(outcome, entry, base_dir=self._tmp)


class TestStrictWriteGate(_Sandboxed):
    def test_real_reconciled_trade_is_accepted(self):
        res = self._write(*_real_trade())
        self.assertFalse(res["skipped"])
        self.assertEqual(res["result"], "loss")
        self.assertEqual(sorted(res["updated"]),
                         ["playbook", "regime", "session", "tool", "volatility"])
        b = get_bucket("QQQ", "playbook", "liquidity_sweep_reversal", base_dir=self._tmp)
        self.assertEqual(b["trades"], 1)
        self.assertEqual(b["losses"], 1)

    def test_unreconciled_trade_rejected(self):
        o, e = _real_trade()
        o["status"] = "open"
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:not_a_reconciled_closed_trade")

    def test_missing_execution_id_rejected(self):
        o, e = _real_trade()
        e["alpaca_order_id"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:missing_execution_id")

    def test_synthetic_execution_id_rejected(self):
        # the 5E8 validation-harness record in the live journal has exactly
        # this shape — it must never reach the tables
        o, e = _real_trade()
        e["alpaca_order_id"] = "SYNTHETIC_VALIDATION_ORDER"
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:synthetic_execution_id")

    def test_missing_entry_timestamp_rejected(self):
        o, e = _real_trade()
        e["timestamp"] = None
        o["entry_timestamp"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:missing_entry_timestamp")

    def test_missing_exit_timestamp_rejected(self):
        o, e = _real_trade()
        e["closed_at"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:missing_exit_timestamp")

    def test_invalid_pnl_rejected(self):
        o, e = _real_trade()
        o["realized_pnl"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:invalid_realized_pnl")

    def test_zero_pnl_is_valid(self):
        # breakeven trades have pnl 0.0 — numeric zero must pass the gate
        o, e = _real_trade()
        o["realized_pnl"] = 0.0
        o["realized_r"] = 0.0
        res = self._write(o, e)
        self.assertFalse(res["skipped"])
        self.assertEqual(res["result"], "be")

    def test_missing_playbook_rejected(self):
        o, e = _real_trade()
        o["playbook"] = None
        e["snapshot_summary"]["playbook"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:invalid_playbook")

    def test_missing_session_rejected(self):
        o, e = _real_trade()
        o["session"] = None
        e["snapshot_summary"]["session"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:invalid_session")

    def test_missing_symbol_rejected(self):
        o, e = _real_trade()
        o["instrument"] = None
        e["symbol"] = None
        res = self._write(o, e)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:invalid_symbol")

    def test_contamination_fixture_shape_cannot_write(self):
        """The exact 1A.5 test-fixture shape (no alpaca_order_id) that wrote
        132 fake wins into the live tables must be rejected at the gate."""
        outcome = {
            "instrument": "QQQ", "status": "closed", "session": "afternoon",
            "regime": "expansion_up", "volatility_state": "stable",
            "playbook": "expansion_continuation",
            "realized_r": 2.3, "realized_pnl": 320.0,
            "entry_timestamp": "20260615T113000",
        }
        entry = {  # journal-shaped but NO broker execution id
            "trade_id": "T-1001", "symbol": "QQQ",
            "timestamp": "20260615T113000", "closed_at": "20260615T120000",
            "snapshot_summary": {"session": "afternoon",
                                 "playbook": "expansion_continuation"},
        }
        res = update_performance_tables(outcome, entry, base_dir=self._tmp)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:missing_execution_id")
        b = get_bucket("QQQ", "playbook", "expansion_continuation", base_dir=self._tmp)
        self.assertEqual(b["trades"], 0)


class TestIdempotency(_Sandboxed):
    def test_same_trade_never_folds_twice(self):
        o, e = _real_trade()
        first = self._write(o, e)
        second = self._write(o, e)
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "duplicate_write")
        self.assertEqual(first["write_key"], second["write_key"])
        b = get_bucket("QQQ", "playbook", "liquidity_sweep_reversal", base_dir=self._tmp)
        self.assertEqual(b["trades"], 1)   # not 2

    def test_replay_of_ten_duplicates_folds_once(self):
        o, e = _real_trade()
        results = [self._write(o, e) for _ in range(10)]
        self.assertEqual(sum(1 for r in results if not r["skipped"]), 1)
        b = get_bucket("QQQ", "session", "lunch", base_dir=self._tmp)
        self.assertEqual(b["trades"], 1)

    def test_distinct_trades_both_fold(self):
        o1, e1 = _real_trade()
        o2, e2 = _real_trade()
        e2["alpaca_order_id"] = "c2adfa47-0000-4b73-a001-000000000000"
        e2["timestamp"] = "20260711T102954"
        e2["closed_at"] = "20260711T104549"
        o2["entry_timestamp"] = "20260711T102954"
        self.assertFalse(self._write(o1, e1)["skipped"])
        self.assertFalse(self._write(o2, e2)["skipped"])
        b = get_bucket("QQQ", "playbook", "liquidity_sweep_reversal", base_dir=self._tmp)
        self.assertEqual(b["trades"], 2)

    def test_write_key_composition(self):
        k1 = compute_write_key("QQQ", "e1", "x1", "oid1")
        self.assertNotEqual(k1, compute_write_key("QQQ", "e1", "x1", "oid2"))
        self.assertNotEqual(k1, compute_write_key("QQQ", "e2", "x1", "oid1"))
        self.assertNotEqual(k1, compute_write_key("QQQ", "e1", "x2", "oid1"))
        self.assertNotEqual(k1, compute_write_key("MNQ", "e1", "x1", "oid1"))

    def test_ledger_persisted_next_to_tables(self):
        o, e = _real_trade()
        self._write(o, e)
        self.assertTrue(os.path.isfile(os.path.join(self._tmp, "QQQ", LEDGER_FILE)))


class TestGateIsPure(unittest.TestCase):
    def test_validator_never_raises(self):
        for bad in (None, {}, {"status": 7}, {"status": "closed"}):
            ok, reason, ev = validate_performance_write(bad, None)
            self.assertFalse(ok)
            self.assertIsInstance(reason, str)

    def test_valid_evidence_shape(self):
        o, e = _real_trade()
        ok, reason, ev = validate_performance_write(o, e)
        self.assertTrue(ok)
        self.assertEqual(ev["symbol"], "QQQ")
        self.assertEqual(ev["entry_ts"], "20260710T115838")
        self.assertEqual(ev["exit_ts"], "20260710T145032")
        self.assertIn("60dd2291", ev["execution_id"])


if __name__ == "__main__":
    unittest.main()
