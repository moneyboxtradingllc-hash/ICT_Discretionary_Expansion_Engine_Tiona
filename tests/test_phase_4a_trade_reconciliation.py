"""
Phase 4A tests — Trade Lifecycle Closure Engine.
12 tests covering the full reconciliation path: fill detection, closure,
P&L computation, terminal order handling, and experience-layer integration.

No actual Alpaca API calls — all broker interactions mocked at recon_mod level.
(trade_reconciliation imports functions by reference; patch the importing module.)
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal        as tj_mod
import paper_execution.trade_reconciliation as recon_mod
import experience_intelligence.experience_query as eq_mod

from paper_execution.trade_journal       import make_record, append_trade
from paper_execution.trade_reconciliation import reconcile_trade
from experience_intelligence.experience_query import load_completed_trades


# ── Shared fixtures ───────────────────────────────────────────────────────────

_SAFE_ENV = {
    "PAPER_TRADING_ONLY": "true",
    "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY":     "TESTKEY",
    "ALPACA_SECRET_KEY":  "TESTSECRET",
}


def _trade(order_status="submitted", alpaca_order_id="ALPA_001",
           side="buy", qty=10, entry_ref=479.0, stop_ref=476.0,
           risk_dollars=300.0, exit_submitted=False, exit_order_id=None,
           avg_fill_price=None, filled_qty=None, timestamp=None):
    rec = make_record(
        trade_id="PT_QQQ_20240101T093000", symbol="QQQ",
        intent_id="intent_001", intent_type="long",
        side=side, qty=qty, entry_reference=entry_ref, stop_reference=stop_ref,
        risk_per_share=abs(entry_ref - stop_ref), risk_dollars=risk_dollars,
        order_status=order_status, alpaca_order_id=alpaca_order_id,
        reason="test trade",
    )
    if timestamp:
        rec["timestamp"]      = timestamp
    rec["exit_submitted"]     = exit_submitted
    rec["exit_order_id"]      = exit_order_id
    if avg_fill_price is not None:
        rec["avg_fill_price"] = avg_fill_price
    if filled_qty is not None:
        rec["filled_qty"]     = filled_qty
    return rec


def _order_filled_entry():
    return {"id": "ALPA_001", "status": "filled", "side": "buy",
            "qty": "10", "filled_qty": "10", "filled_avg_price": "479.50",
            "submitted_at": "2024-01-01T09:30:00Z"}


def _order_filled_exit(avg_price="482.00"):
    return {"id": "ALPA_EXIT_001", "status": "filled", "side": "sell",
            "qty": "10", "filled_qty": "10", "filled_avg_price": avg_price,
            "submitted_at": "2024-01-01T09:45:00Z"}


def _order_terminal(status="canceled"):
    return {"id": "ALPA_001", "status": status, "side": "buy",
            "qty": "10", "filled_qty": "0", "filled_avg_price": None,
            "submitted_at": "2024-01-01T09:30:00Z"}


def _write(tmpdir, trade):
    with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
        append_trade(trade, "QQQ")


# ── Test 1: Filled order recognized ──────────────────────────────────────────

class TestFilledOrderRecognized(unittest.TestCase):

    def test_submitted_entry_synced_to_filled(self):
        """Entry order Alpaca-filled → journal status updated to 'filled'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="submitted"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod, "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order", return_value=_order_filled_entry()), \
                 patch.object(recon_mod, "get_position",
                              return_value={"symbol": "QQQ", "qty": "10",
                                            "side": "long", "avg_entry_price": "479.50",
                                            "current_price": "480.00",
                                            "unrealized_pl": "5.0"}):
                result = reconcile_trade("QQQ")

            self.assertTrue(result["trade_found"])
            self.assertIn(result["status"], ("open", "closed"))

            # Journal must now show "filled"
            with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
                from paper_execution.trade_journal import find_any_active_trade
                t, _ = find_any_active_trade("QQQ")
            self.assertIsNotNone(t)
            self.assertEqual(t.get("order_status"), "filled")


# ── Test 2: Closed position recognized ───────────────────────────────────────

class TestClosedPositionRecognized(unittest.TestCase):

    def test_exit_fill_returns_closed(self):
        """Exit order filled → reconcile returns status='closed'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod, "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_filled_exit()):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed")
        self.assertTrue(result["trade_found"])
        self.assertTrue(result["journal_updated"])


# ── Test 3: mark_closed is called ────────────────────────────────────────────

class TestMarkClosedCalled(unittest.TestCase):

    def test_mark_closed_invoked(self):
        """mark_closed is called once when exit order fills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order", return_value=_order_filled_exit()), \
                 patch.object(recon_mod, "mark_closed",
                              wraps=tj_mod.mark_closed) as mc_spy:
                reconcile_trade("QQQ")

        mc_spy.assert_called_once()


# ── Test 4: realized_pnl stored ──────────────────────────────────────────────

class TestRealizedPnlStored(unittest.TestCase):

    def test_pnl_computed_correctly(self):
        """Long: (exit=482 − entry=479.50) × 10 = 25.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_filled_exit("482.00")):
                result = reconcile_trade("QQQ")

            self.assertEqual(result["status"], "closed")
            self.assertAlmostEqual(result["realized_pnl"], 25.0, places=1)

            # Verify stored in journal
            with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
                from paper_execution.trade_journal import load_today_trades
                t = load_today_trades("QQQ")[0]
            self.assertEqual(t["order_status"], "closed")
            self.assertAlmostEqual(float(t["realized_pnl"]), 25.0, places=1)


# ── Test 5: realized_r stored ─────────────────────────────────────────────────

class TestRealizedRStored(unittest.TestCase):

    def test_realized_r_computed(self):
        """realized_r = pnl / risk_dollars = 25 / 300 ≈ 0.0833."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
                risk_dollars=300.0,
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_filled_exit("482.00")):
                result = reconcile_trade("QQQ")

        self.assertIsNotNone(result["realized_r"])
        self.assertAlmostEqual(result["realized_r"], round(25.0 / 300.0, 4), places=3)


# ── Test 6: holding_minutes stored ───────────────────────────────────────────

class TestHoldingMinutesStored(unittest.TestCase):

    def test_holding_minutes_positive(self):
        """holding_minutes > 0 for a trade with a past entry timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
                timestamp="20240101T093000",  # well in the past
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_filled_exit()):
                result = reconcile_trade("QQQ")

        self.assertIsNotNone(result["holding_minutes"])
        self.assertGreater(result["holding_minutes"], 0)


# ── Test 7: Cancelled order handled ──────────────────────────────────────────

class TestCancelledOrderHandled(unittest.TestCase):

    def test_canceled_entry_no_crash(self):
        """canceled → status in (canceled, cancelled), pnl=None, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="submitted"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_terminal("canceled")):
                result = reconcile_trade("QQQ")

        self.assertTrue(result["trade_found"])
        self.assertIn(result["status"], ("canceled", "cancelled"))
        self.assertIsNone(result["realized_pnl"])
        self.assertFalse(result["journal_updated"])


# ── Test 8: Rejected order handled ───────────────────────────────────────────

class TestRejectedOrderHandled(unittest.TestCase):

    def test_rejected_entry_no_crash(self):
        """rejected → status='rejected', pnl=None, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="submitted"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_terminal("rejected")):
                result = reconcile_trade("QQQ")

        self.assertTrue(result["trade_found"])
        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(result["realized_pnl"])


# ── Test 9: Expired order handled ────────────────────────────────────────────

class TestExpiredOrderHandled(unittest.TestCase):

    def test_expired_entry_no_crash(self):
        """expired → status='expired', pnl=None, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="submitted"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_order_terminal("expired")):
                result = reconcile_trade("QQQ")

        self.assertTrue(result["trade_found"])
        self.assertEqual(result["status"], "expired")
        self.assertIsNone(result["realized_pnl"])


# ── Test 10: Position disappears scenario ────────────────────────────────────

class TestPositionDisappearsScenario(unittest.TestCase):

    def test_position_gone_no_exit_externally_closed(self):
        """Position gone + no tracked exit + no closed orders → externally_closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled",
                avg_fill_price="479.50", filled_qty="10",
                exit_submitted=False,
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[]):
                result = reconcile_trade("QQQ")

            self.assertTrue(result["trade_found"])
            self.assertEqual(result["status"], "externally_closed")
            self.assertTrue(result["journal_updated"])

            with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
                from paper_execution.trade_journal import load_today_trades
                t = load_today_trades("QQQ")[0]
            self.assertEqual(t["order_status"], "closed")


# ── Test 11: Experience layer receives closed trade ───────────────────────────

class TestExperienceLayerReceivesClosedTrade(unittest.TestCase):

    def test_load_completed_trades_sees_reconciled_trade(self):
        """After reconciliation, load_completed_trades returns the closed trade."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(tj_mod, "_TRADES_DIR", tmpdir), \
             patch.object(eq_mod, "_TRADES_DIR", tmpdir), \
             patch.dict(os.environ, _SAFE_ENV):

            _write(tmpdir, _trade(
                order_status="filled", exit_submitted=True,
                exit_order_id="ALPA_EXIT_001",
                avg_fill_price="479.50", filled_qty="10",
                timestamp="20240101T093000",
            ))

            # Not visible before reconciliation
            self.assertEqual(load_completed_trades("QQQ", days=7), [])

            with patch.object(recon_mod, "get_order",
                              return_value=_order_filled_exit("482.00")):
                result = reconcile_trade("QQQ")

            self.assertEqual(result["status"], "closed")

            after = load_completed_trades("QQQ", days=7)
            self.assertEqual(len(after), 1)
            ct = after[0]
            self.assertEqual(ct["order_status"], "closed")
            self.assertIsNotNone(ct.get("realized_pnl"))
            self.assertIsNotNone(ct.get("realized_r"))


# ── Test 12: No execution behavior regression ─────────────────────────────────

class TestNoExecutionBehaviorRegression(unittest.TestCase):

    _EXEC_KEYS = {
        "decision_authority", "execution_gate", "paper_execution",
        "position_monitor", "stop_enforcer", "paper_activation",
        "ai_confidence", "intent_score", "order_request",
    }

    def test_result_contains_no_execution_keys(self):
        """reconcile_trade result must not contain execution-side snapshot keys."""
        with patch.dict(os.environ, _SAFE_ENV), \
             patch.object(recon_mod, "find_any_active_trade",
                          return_value=(None, None)):
            result = reconcile_trade("QQQ")

        for key in self._EXEC_KEYS:
            self.assertNotIn(key, result,
                             msg=f"Execution key '{key}' must not appear in result")

    def test_never_raises(self):
        """reconcile_trade must never raise regardless of internal failures."""
        with patch.dict(os.environ, _SAFE_ENV), \
             patch.object(recon_mod, "find_any_active_trade",
                          side_effect=RuntimeError("simulated failure")):
            result = reconcile_trade("QQQ")

        self.assertFalse(result["trade_found"])
        self.assertEqual(result["status"], "error")
        self.assertGreater(len(result["warnings"]), 0)


if __name__ == "__main__":
    unittest.main()
