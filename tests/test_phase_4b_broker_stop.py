"""
Phase 4B tests — Broker-Side Stop Protection.
13 tests covering:
  disabled mode, side derivation, validation, paper-safety, journal writes,
  verify/missing detection, position_monitor integration, duplicate-stop guard,
  stop_enforcer deferred exit, cancel-on-close, and no-regression when disabled.

No actual Alpaca API calls — broker interactions mocked at module level.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal        as tj_mod
import paper_execution.protective_stop      as ps_mod
import paper_execution.position_monitor     as pm_mod
import paper_execution.stop_enforcer        as se_mod

from paper_execution.trade_journal       import make_record, append_trade, load_today_trades
from paper_execution.protective_stop     import (
    build_stop_order, submit_protective_stop,
    verify_protective_stop_exists, cancel_protective_stop_if_position_closed,
)
from paper_execution.position_monitor    import monitor_paper_position
from paper_execution.stop_enforcer       import enforce_stop


# ── Shared helpers ────────────────────────────────────────────────────────────

_SAFE_ENV = {
    "PAPER_TRADING_ONLY": "true",
    "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY":     "TESTKEY",
    "ALPACA_SECRET_KEY":  "TESTSECRET",
    # Explicit false: other test modules import code that calls load_dotenv(),
    # which leaks BROKER_STOP_ENABLED=true from .env into the process env and
    # made these tests order-dependent in full-suite runs.
    "BROKER_STOP_ENABLED": "false",
}

_STOP_ENV = {**_SAFE_ENV, "BROKER_STOP_ENABLED": "true"}


def _trade(order_status="filled", side="buy", qty=10,
           entry_ref=479.0, stop_ref=476.0,
           avg_fill_price=None, filled_qty=None,
           broker_stop_order_id=None):
    rec = make_record(
        trade_id="PT_QQQ_20240101T093000", symbol="QQQ",
        intent_id="intent_001", intent_type="long",
        side=side, qty=qty,
        entry_reference=entry_ref, stop_reference=stop_ref,
        risk_per_share=abs(entry_ref - stop_ref), risk_dollars=300.0,
        order_status=order_status, alpaca_order_id="ALPA_001",
        reason="test trade",
    )
    if avg_fill_price is not None:
        rec["avg_fill_price"] = avg_fill_price
    if filled_qty is not None:
        rec["filled_qty"] = filled_qty
    if broker_stop_order_id is not None:
        rec["broker_stop_order_id"] = broker_stop_order_id
        rec["broker_stop_status"]   = "broker_stop_submitted"
    return rec


def _write(tmpdir, trade):
    with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
        append_trade(trade, "QQQ")


def _position(qty="10", side="long", avg_entry="479.50", current="480.00"):
    return {
        "symbol":          "QQQ",
        "qty":             qty,
        "side":            side,
        "avg_entry_price": avg_entry,
        "current_price":   current,
        "unrealized_pl":   "5.00",
    }


def _monitor_open(broker_stop=None):
    """Minimal monitor result indicating an open long position."""
    bs = broker_stop or {"enabled": False, "status": "disabled",
                         "stop_order_id": None, "stop_price": None}
    return {
        "enabled":               True,
        "has_open_position":     True,
        "status":                "monitoring",
        "side":                  "long",
        "qty":                   10,
        "current_price":         479.0,
        "stop_reference":        476.0,
        "exit_already_submitted": False,
        "linked_trade_id":       "PT_QQQ_20240101T093000",
        "broker_stop":           bs,
        "warnings":              [],
    }


def _monitor_no_pos():
    return {
        "enabled": True, "has_open_position": False, "status": "no_position",
        "broker_stop": {"enabled": False, "status": "disabled",
                        "stop_order_id": None, "stop_price": None},
        "warnings": [],
    }


# ── Test 1: BROKER_STOP_ENABLED=false returns disabled ───────────────────────

class TestDisabledWhenEnvFalse(unittest.TestCase):

    def test_submit_returns_disabled(self):
        with patch.dict(os.environ, _SAFE_ENV):  # BROKER_STOP_ENABLED not set
            result = submit_protective_stop("T1", "QQQ", "long", 10, 476.0)
        self.assertFalse(result["enabled"])
        self.assertFalse(result["stop_submitted"])
        self.assertEqual(result["status"], "disabled")

    def test_verify_returns_disabled(self):
        with patch.dict(os.environ, _SAFE_ENV):
            result = verify_protective_stop_exists("T1", "QQQ", "long", 476.0)
        self.assertFalse(result["enabled"])
        self.assertEqual(result["status"], "disabled")


# ── Test 2: Long stop side is sell ────────────────────────────────────────────

class TestLongStopSideIsSell(unittest.TestCase):

    def test_long_stop_side_sell(self):
        result = build_stop_order("QQQ", "long", 10, 476.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["stop_side"], "sell")
        self.assertEqual(result["stop_price"], 476.0)


# ── Test 3: Short stop side is buy ───────────────────────────────────────────

class TestShortStopSideIsBuy(unittest.TestCase):

    def test_short_stop_side_buy(self):
        result = build_stop_order("QQQ", "short", 10, 482.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["stop_side"], "buy")


# ── Test 4: Invalid stop price rejected ──────────────────────────────────────

class TestInvalidStopPriceRejected(unittest.TestCase):

    def test_zero_stop_price(self):
        result = build_stop_order("QQQ", "long", 10, 0)
        self.assertFalse(result["valid"])
        self.assertIn("invalid stop_price", result["reason"])

    def test_negative_stop_price(self):
        result = build_stop_order("QQQ", "long", 10, -1.0)
        self.assertFalse(result["valid"])

    def test_none_stop_price(self):
        result = build_stop_order("QQQ", "long", 10, None)
        self.assertFalse(result["valid"])


# ── Test 5: qty <= 0 rejected ─────────────────────────────────────────────────

class TestQtyZeroRejected(unittest.TestCase):

    def test_zero_qty_build(self):
        result = build_stop_order("QQQ", "long", 0, 476.0)
        self.assertFalse(result["valid"])
        self.assertIn("qty must be > 0", result["reason"])

    def test_negative_qty_build(self):
        result = build_stop_order("QQQ", "long", -5, 476.0)
        self.assertFalse(result["valid"])

    def test_zero_qty_submit_graceful(self):
        with patch.dict(os.environ, _STOP_ENV):
            result = submit_protective_stop("T1", "QQQ", "long", 0, 476.0)
        self.assertFalse(result["stop_submitted"])


# ── Test 6: Paper endpoint validation required ────────────────────────────────

class TestPaperEndpointRequired(unittest.TestCase):

    def test_unsafe_endpoint_blocked(self):
        with patch.dict(os.environ, {**_STOP_ENV, "ALPACA_BASE_URL": "https://api.alpaca.markets"}):
            result = submit_protective_stop("T1", "QQQ", "long", 10, 476.0)
        self.assertFalse(result["stop_submitted"])
        self.assertIn("safety", result["reason"].lower())

    def test_paper_trading_only_false_blocked(self):
        with patch.dict(os.environ, {**_STOP_ENV, "PAPER_TRADING_ONLY": "false"}):
            result = submit_protective_stop("T1", "QQQ", "long", 10, 476.0)
        self.assertFalse(result["stop_submitted"])


# ── Test 7: submit_protective_stop writes journal fields ─────────────────────

class TestSubmitWritesJournalFields(unittest.TestCase):

    def test_journal_updated_after_submit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade())

            with patch.dict(os.environ, _STOP_ENV), \
                 patch.object(tj_mod,  "_TRADES_DIR", tmpdir), \
                 patch.object(ps_mod, "submit_protective_stop_order", return_value={
                     "alpaca_order_id": "STOP001",
                     "status":          "pending_new",
                     "symbol":          "QQQ",
                     "side":            "sell",
                     "qty":             "10",
                     "stop_price":      "476.0",
                     "submitted_at":    "2024-01-01T09:31:00Z",
                 }):
                result = submit_protective_stop(
                    "PT_QQQ_20240101T093000", "QQQ", "long", 10, 476.0
                )

            self.assertTrue(result["stop_submitted"])
            self.assertEqual(result["stop_order_id"], "STOP001")

            with patch.object(tj_mod, "_TRADES_DIR", tmpdir):
                t = load_today_trades("QQQ")[0]
            self.assertEqual(t["broker_stop_order_id"], "STOP001")
            self.assertEqual(t["broker_stop_status"], "broker_stop_submitted")
            self.assertAlmostEqual(float(t["broker_stop_price"]), 476.0)


# ── Test 8: verify_protective_stop_exists detects existing stop ───────────────

class TestVerifyDetectsExistingStop(unittest.TestCase):

    _EXISTING_STOP = {
        "id": "STOP001", "symbol": "QQQ", "side": "sell",
        "type": "stop", "stop_price": "476.0", "status": "accepted",
    }

    def test_verify_returns_verified_when_found(self):
        with patch.dict(os.environ, _STOP_ENV), \
             patch.object(ps_mod, "find_open_stop_order",
                          return_value=self._EXISTING_STOP):
            result = verify_protective_stop_exists("", "QQQ", "long", 476.0)
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["stop_submitted"])
        self.assertEqual(result["stop_order_id"], "STOP001")

    def test_verify_returns_missing_when_not_found(self):
        with patch.dict(os.environ, _STOP_ENV), \
             patch.object(ps_mod, "find_open_stop_order", return_value=None):
            result = verify_protective_stop_exists("", "QQQ", "long", 476.0)
        self.assertEqual(result["status"], "missing")
        self.assertFalse(result["stop_submitted"])


# ── Test 9: position_monitor submits stop after fill if missing ───────────────

class TestPositionMonitorSubmitsBrokerStop(unittest.TestCase):

    def test_submits_when_filled_and_no_stop(self):
        """position_monitor calls submit_protective_stop when entry is filled and no broker stop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="filled",
                                  avg_fill_price="479.50", filled_qty="10"))

            with patch.dict(os.environ, {**_STOP_ENV, "PAPER_STOP_MONITOR_ENABLED": "true"}), \
                 patch.object(tj_mod,  "_TRADES_DIR", tmpdir), \
                 patch.object(pm_mod, "get_position", return_value=_position()), \
                 patch.object(pm_mod, "get_order",    return_value=None), \
                 patch.object(pm_mod, "submit_protective_stop", return_value={
                     "enabled": True, "stop_submitted": True,
                     "stop_order_id": "STOP001", "stop_price": 476.0,
                     "status": "submitted", "reason": "ok", "warnings": [],
                 }) as spy:
                result = monitor_paper_position({}, "QQQ")

        broker_stop = result.get("broker_stop", {})
        self.assertEqual(broker_stop.get("status"), "submitted")
        self.assertEqual(broker_stop.get("stop_order_id"), "STOP001")
        spy.assert_called_once()


# ── Test 10: Duplicate stop not submitted ─────────────────────────────────────

class TestDuplicateStopNotSubmitted(unittest.TestCase):

    def test_verify_called_not_submit_when_order_id_present(self):
        """When broker_stop_order_id already in journal, verify is called, not submit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(
                order_status="filled", avg_fill_price="479.50", filled_qty="10",
                broker_stop_order_id="STOP001",
            ))

            with patch.dict(os.environ, {**_STOP_ENV, "PAPER_STOP_MONITOR_ENABLED": "true"}), \
                 patch.object(tj_mod,  "_TRADES_DIR", tmpdir), \
                 patch.object(pm_mod, "get_position", return_value=_position()), \
                 patch.object(pm_mod, "get_order",    return_value=None), \
                 patch.object(pm_mod, "submit_protective_stop", return_value={}) as submit_spy, \
                 patch.object(pm_mod, "verify_protective_stop_exists", return_value={
                     "enabled": True, "stop_submitted": True, "stop_order_id": "STOP001",
                     "stop_price": 476.0, "status": "verified", "reason": "ok", "warnings": [],
                 }) as verify_spy:
                monitor_paper_position({}, "QQQ")

        submit_spy.assert_not_called()
        verify_spy.assert_called_once()


# ── Test 11: stop_enforcer defers to active broker stop ──────────────────────

class TestStopEnforcerDeferstoBrokerStop(unittest.TestCase):

    def test_no_emergency_exit_when_broker_stop_verified(self):
        """When broker stop is verified active, software stop defers and does not send market exit."""
        monitor_result = _monitor_open(broker_stop={
            "enabled": True, "status": "verified",
            "stop_order_id": "STOP001", "stop_price": 476.0,
        })
        monitor_result["current_price"] = 475.0  # below stop — breached

        with patch.dict(os.environ, {**_SAFE_ENV, "PAPER_EXIT_ON_STOP": "true",
                                      "PAPER_STOP_MONITOR_ENABLED": "true"}):
            result = enforce_stop({}, "QQQ", monitor_result)

        self.assertEqual(result.get("action_taken"), "broker_stop_active")
        self.assertFalse(result.get("exit_submitted", False))

    def test_no_emergency_exit_when_broker_stop_submitted(self):
        """Broker stop in 'submitted' state also defers the software stop."""
        monitor_result = _monitor_open(broker_stop={
            "enabled": True, "status": "submitted",
            "stop_order_id": "STOP001", "stop_price": 476.0,
        })
        monitor_result["current_price"] = 475.0

        with patch.dict(os.environ, {**_SAFE_ENV, "PAPER_EXIT_ON_STOP": "true",
                                      "PAPER_STOP_MONITOR_ENABLED": "true"}):
            result = enforce_stop({}, "QQQ", monitor_result)

        self.assertEqual(result.get("action_taken"), "broker_stop_active")
        self.assertFalse(result.get("exit_submitted", False))


# ── Test 12: Broker stop canceled when position closed ────────────────────────

class TestCancelBrokerStopOnClose(unittest.TestCase):

    def test_cancel_returns_canceled_true(self):
        with patch.dict(os.environ, _STOP_ENV), \
             patch.object(ps_mod, "cancel_order", return_value={"canceled": True}):
            result = cancel_protective_stop_if_position_closed("T1", "QQQ", "STOP001")
        self.assertTrue(result["canceled"])

    def test_no_order_id_returns_no_cancel(self):
        with patch.dict(os.environ, _STOP_ENV):
            result = cancel_protective_stop_if_position_closed("T1", "QQQ", None)
        self.assertFalse(result["canceled"])
        self.assertIn("no stop order ID", result["reason"])

    def test_already_triggered_graceful(self):
        """When stop was already triggered (not cancelable), no crash."""
        with patch.dict(os.environ, _STOP_ENV), \
             patch.object(ps_mod, "cancel_order",
                          return_value={"canceled": False, "reason": "order not cancelable"}):
            result = cancel_protective_stop_if_position_closed("T1", "QQQ", "STOP001")
        self.assertFalse(result["canceled"])
        self.assertIn("not cancelable", result["reason"])


# ── Test 13: No behavior changes when BROKER_STOP_ENABLED=false ───────────────

class TestNoBehaviorChangeWhenDisabled(unittest.TestCase):

    def test_position_monitor_has_disabled_broker_stop(self):
        """position_monitor returns disabled broker_stop when BROKER_STOP_ENABLED=false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, _trade(order_status="filled",
                                  avg_fill_price="479.50", filled_qty="10"))

            with patch.dict(os.environ, {**_SAFE_ENV, "PAPER_STOP_MONITOR_ENABLED": "true"}), \
                 patch.object(tj_mod,  "_TRADES_DIR", tmpdir), \
                 patch.object(pm_mod, "get_position", return_value=_position()), \
                 patch.object(pm_mod, "get_order",    return_value=None):
                result = monitor_paper_position({}, "QQQ")

        broker_stop = result.get("broker_stop", {})
        self.assertFalse(broker_stop.get("enabled", True))
        self.assertEqual(broker_stop.get("status"), "disabled")

    def test_stop_enforcer_still_works_without_broker_stop(self):
        """With no broker stop, stop_enforcer normal flow is unchanged."""
        monitor_result = _monitor_open(
            broker_stop={"enabled": False, "status": "disabled",
                         "stop_order_id": None, "stop_price": None}
        )
        monitor_result["current_price"] = 475.0  # breached

        with patch.dict(os.environ, {**_SAFE_ENV, "PAPER_EXIT_ON_STOP": "false",
                                      "PAPER_STOP_MONITOR_ENABLED": "true"}):
            result = enforce_stop({}, "QQQ", monitor_result)

        # stop_breached detected; exit not sent because PAPER_EXIT_ON_STOP=false
        self.assertTrue(result.get("stop_breached", False))
        self.assertFalse(result.get("exit_submitted", False))
        self.assertEqual(result.get("action_taken"), "stop_breached_no_action")

    def test_protective_stop_submit_never_raises(self):
        """submit_protective_stop never raises even with bad inputs."""
        with patch.dict(os.environ, _SAFE_ENV):
            try:
                result = submit_protective_stop("", "", "invalid", -1, -1.0)
            except Exception as exc:
                self.fail(f"submit_protective_stop raised: {exc}")
        self.assertFalse(result.get("stop_submitted", True))


if __name__ == "__main__":
    unittest.main()
