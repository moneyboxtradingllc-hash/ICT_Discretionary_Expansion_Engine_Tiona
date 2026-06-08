"""
Phase 4C tests — Reconciliation Completion.

Resolves three audit blockers identified in the post-Phase-4B audit:

  Finding 1: Timestamp comparison bug — Alpaca ISO timestamps (hyphens, tz offset)
             were compared against compact entry timestamps using string slicing,
             causing the comparison to always fail. External fills were never found.

  Finding 2: Orphaned GTC broker stops — when a trade closed via software exit,
             the broker stop order was never canceled. cancel_protective_stop_if_position_closed
             now runs inside _close_from_exit and _handle_externally_closed.

  Finding 3: Missing broker_stop_order_id reconciliation path — if the broker stop
             itself triggered (position closed at broker), reconcile_trade had no path
             to detect it. Step 4b now queries broker_stop_order_id and closes the
             trade with reason='broker_stop_triggered'.

No actual Alpaca API calls — all broker interactions mocked at recon_mod level.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal        as tj_mod
import paper_execution.trade_reconciliation as recon_mod

from paper_execution.trade_journal       import make_record, append_trade
from paper_execution.trade_reconciliation import reconcile_trade


# ── Shared fixtures ───────────────────────────────────────────────────────────

_SAFE_ENV = {
    "PAPER_TRADING_ONLY":  "true",
    "ALPACA_BASE_URL":     "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY":      "TESTKEY",
    "ALPACA_SECRET_KEY":   "TESTSECRET",
    "BROKER_STOP_ENABLED": "true",
}


def _trade(order_status="filled", alpaca_order_id="ALPA_001",
           side="buy", qty=10, entry_ref=479.0, stop_ref=476.0,
           risk_dollars=300.0, exit_submitted=False, exit_order_id=None,
           avg_fill_price="479.50", filled_qty="10",
           broker_stop_order_id=None, timestamp="20240101T093000"):
    rec = make_record(
        trade_id="PT_QQQ_20240101T093000", symbol="QQQ",
        intent_id="intent_001", intent_type="long",
        side=side, qty=qty, entry_reference=entry_ref, stop_reference=stop_ref,
        risk_per_share=abs(entry_ref - stop_ref), risk_dollars=risk_dollars,
        order_status=order_status, alpaca_order_id=alpaca_order_id,
        reason="test trade",
    )
    rec["timestamp"]      = timestamp
    rec["exit_submitted"] = exit_submitted
    rec["exit_order_id"]  = exit_order_id
    if avg_fill_price is not None:
        rec["avg_fill_price"] = avg_fill_price
    if filled_qty is not None:
        rec["filled_qty"] = filled_qty
    if broker_stop_order_id is not None:
        rec["broker_stop_order_id"] = broker_stop_order_id
    return rec


def _write(tmpdir, trade):
    with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
        append_trade(trade, "QQQ")


def _stop_filled_order(avg_price="476.00"):
    return {
        "id": "ALPA_STOP_001", "status": "filled", "side": "sell",
        "qty": "10", "filled_qty": "10", "filled_avg_price": avg_price,
        "submitted_at": "2024-01-01T09:50:00-05:00",
    }


def _stop_open_order():
    return {
        "id": "ALPA_STOP_001", "status": "accepted", "side": "sell",
        "qty": "10", "filled_qty": "0", "filled_avg_price": None,
        "submitted_at": "2024-01-01T09:31:00-05:00",
    }


def _exit_filled(avg_price="482.00"):
    return {
        "id": "ALPA_EXIT_001", "status": "filled", "side": "sell",
        "qty": "10", "filled_qty": "10", "filled_avg_price": avg_price,
        "submitted_at": "2024-01-01T09:45:00-05:00",
    }


def _external_closed_order(avg_price="476.50"):
    """Simulates an externally executed sell found in Alpaca's closed order history."""
    return {
        "id": "ALPA_EXT_001", "status": "filled", "side": "sell",
        "qty": "10", "filled_qty": "10", "filled_avg_price": avg_price,
        "submitted_at": "2024-01-01T09:40:00-05:00",  # 09:40 Eastern — after entry at 09:30
    }


# ══════════════════════════════════════════════════════════════════════════════
# Finding 1 — Timestamp comparison bug
# ══════════════════════════════════════════════════════════════════════════════

class TestTimestampFix_ISOFormatParsed(unittest.TestCase):
    """ISO timestamp after entry is now correctly recognized as a valid exit fill."""

    def test_iso_timestamp_after_entry_matches(self):
        """submitted_at='2024-01-01T09:40:00-05:00' > entry '20240101T093000' → match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(timestamp="20240101T093000"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[_external_closed_order("476.50")]):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed",
                         "ISO timestamp after entry must be matched — trade must close")
        self.assertIsNotNone(result["realized_pnl"],
                             "P&L must be computed when exit fill is found via ISO timestamp")


class TestTimestampFix_ISOBeforeEntryNotMatched(unittest.TestCase):
    """ISO timestamp strictly before entry must not be matched as an exit fill."""

    def test_stale_order_before_entry_not_matched(self):
        """submitted_at='2024-01-01T09:20:00-05:00' < entry '20240101T093000' → no match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(timestamp="20240101T093000"))

            stale = {
                "id": "ALPA_OLD_001", "status": "filled", "side": "sell",
                "qty": "10", "filled_qty": "10", "filled_avg_price": "470.00",
                "submitted_at": "2024-01-01T09:20:00-05:00",  # before entry
            }

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[stale]):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "externally_closed",
                         "Order before entry must not close the trade")
        self.assertIsNone(result["realized_pnl"])


class TestTimestampFix_SpaceSeparatorHandled(unittest.TestCase):
    """ISO timestamp with space separator (not T) is parsed and matched correctly."""

    def test_space_separator_timestamp_parsed(self):
        """submitted_at='2024-01-01 09:40:00-05:00' → parseable and matched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(timestamp="20240101T093000"))

            space_order = {
                "id": "ALPA_SP_001", "status": "filled", "side": "sell",
                "qty": "10", "filled_qty": "10", "filled_avg_price": "476.50",
                "submitted_at": "2024-01-01 09:40:00-05:00",  # space separator
            }

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[space_order]):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed",
                         "Space-separated ISO timestamp must be parsed and matched")


# ══════════════════════════════════════════════════════════════════════════════
# Finding 2 — Orphaned GTC broker stops
# ══════════════════════════════════════════════════════════════════════════════

class TestBrokerStopCancellation_OnSoftwareExitFill(unittest.TestCase):
    """Software exit fills → cancel_protective_stop_if_position_closed is called."""

    def test_cancel_called_with_correct_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                exit_submitted=True, exit_order_id="ALPA_EXIT_001",
                broker_stop_order_id="ALPA_STOP_001",
            ))

            cancel_mock = MagicMock(return_value={"canceled": True})

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",  return_value=_exit_filled()), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              cancel_mock):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed")
        cancel_mock.assert_called_once_with(
            "PT_QQQ_20240101T093000", "QQQ", "ALPA_STOP_001"
        )


class TestBrokerStopCancellation_OnExternallyClosed_WithFillFound(unittest.TestCase):
    """Position externally closed with matching fill → cancel_protective_stop called."""

    def test_cancel_called_when_external_fill_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                broker_stop_order_id="ALPA_STOP_001",
                timestamp="20240101T093000",
            ))

            cancel_mock = MagicMock(return_value={"canceled": True})

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[_external_closed_order()]), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              cancel_mock):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed")
        cancel_mock.assert_called_once()


class TestBrokerStopCancellation_OnExternallyClosed_NoFillData(unittest.TestCase):
    """Position gone with no fill data → cancel_protective_stop still called."""

    def test_cancel_called_when_no_fill_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                broker_stop_order_id="ALPA_STOP_001",
                timestamp="20240101T093000",
            ))

            cancel_mock = MagicMock(return_value={"canceled": True})

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_position", return_value=None), \
                 patch.object(recon_mod, "get_recent_closed_orders_for_symbol",
                              return_value=[]), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              cancel_mock):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "externally_closed")
        cancel_mock.assert_called_once_with(
            "PT_QQQ_20240101T093000", "QQQ", "ALPA_STOP_001"
        )


class TestBrokerStopCancellation_SkippedWhenNoBrokerStopId(unittest.TestCase):
    """When no broker_stop_order_id in journal, cancel is never called."""

    def test_cancel_not_called_without_broker_stop_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                exit_submitted=True, exit_order_id="ALPA_EXIT_001",
                broker_stop_order_id=None,
            ))

            cancel_mock = MagicMock()

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order", return_value=_exit_filled()), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              cancel_mock):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed")
        cancel_mock.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Finding 3 — Broker stop order fill reconciliation path
# ══════════════════════════════════════════════════════════════════════════════

class TestBrokerStopPath_FillDetected(unittest.TestCase):
    """Broker stop order fills → trade closed with reason='broker_stop_triggered'."""

    def test_broker_stop_fill_closes_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(broker_stop_order_id="ALPA_STOP_001"))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_stop_filled_order("476.00")), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              return_value={"canceled": False}):
                result = reconcile_trade("QQQ")

        self.assertTrue(result["trade_found"])
        self.assertEqual(result["status"],      "closed")
        self.assertEqual(result["close_reason"], "broker_stop_triggered")
        self.assertTrue(result["journal_updated"])


class TestBrokerStopPath_PnlComputed(unittest.TestCase):
    """Broker stop fill P&L: (476.00 − 479.50) × 10 = −35.00 (stop-loss)."""

    def test_pnl_and_r_computed_from_stop_fill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                risk_dollars=30.0,
                broker_stop_order_id="ALPA_STOP_001",
            ))

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_stop_filled_order("476.00")), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              return_value={"canceled": False}):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["status"], "closed")
        self.assertIsNotNone(result["realized_pnl"])
        self.assertAlmostEqual(result["realized_pnl"], -35.0, places=1)
        self.assertIsNotNone(result["realized_r"])
        self.assertAlmostEqual(result["realized_r"], round(-35.0 / 30.0, 4), places=3)


class TestBrokerStopPath_StopNotYetFilled(unittest.TestCase):
    """Broker stop still open (accepted, not filled) → falls through, trade stays open."""

    def test_unfilled_stop_does_not_close_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(broker_stop_order_id="ALPA_STOP_001"))

            position = {
                "symbol": "QQQ", "qty": "10", "side": "long",
                "avg_entry_price": "479.50", "current_price": "480.00",
                "unrealized_pl": "5.0",
            }

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",    return_value=_stop_open_order()), \
                 patch.object(recon_mod, "get_position", return_value=position):
                result = reconcile_trade("QQQ")

        self.assertTrue(result["trade_found"])
        self.assertEqual(result["status"], "open",
                         "Unfilled broker stop must leave trade open")


class TestBrokerStopPath_QueryError(unittest.TestCase):
    """Error querying broker stop order → warning added, position check still runs."""

    def test_query_error_adds_warning_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(broker_stop_order_id="ALPA_STOP_001"))

            position = {
                "symbol": "QQQ", "qty": "10", "side": "long",
                "avg_entry_price": "479.50", "current_price": "480.00",
                "unrealized_pl": "5.0",
            }

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value={"error": "order not found"}), \
                 patch.object(recon_mod, "get_position", return_value=position):
                result = reconcile_trade("QQQ")

        self.assertIn("broker stop order query error", " ".join(result.get("warnings", [])))
        self.assertEqual(result["status"], "open")


class TestBrokerStopPath_CancelNotCalledWhenBrokerStopTriggers(unittest.TestCase):
    """Broker stop itself triggered → do NOT call cancel on the already-executed stop."""

    def test_cancel_not_called_on_broker_stop_trigger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(broker_stop_order_id="ALPA_STOP_001"))

            cancel_mock = MagicMock()

            with patch.dict(os.environ, _SAFE_ENV), \
                 patch.object(tj_mod,    "_TRADES_DIR", tmpdir), \
                 patch.object(recon_mod, "get_order",
                              return_value=_stop_filled_order("476.00")), \
                 patch.object(recon_mod, "cancel_protective_stop_if_position_closed",
                              cancel_mock):
                result = reconcile_trade("QQQ")

        self.assertEqual(result["close_reason"], "broker_stop_triggered")
        cancel_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
