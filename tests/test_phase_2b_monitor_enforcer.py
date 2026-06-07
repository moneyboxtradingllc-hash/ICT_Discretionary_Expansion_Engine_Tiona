"""
Phase 2B — Position Monitor + Stop Enforcer unit tests.

Tests: position_monitor, stop_enforcer, formatter lines, trade_journal lifecycle.
No actual Alpaca API calls — all broker interactions mocked.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal   as tj_mod
import paper_execution.paper_broker    as broker_mod
import paper_execution.position_monitor as pm_mod
import paper_execution.stop_enforcer   as se_mod

from paper_execution.trade_journal   import (
    make_record, append_trade, find_active_trade,
    update_trade_status, mark_exit_submitted, mark_closed,
)
from paper_execution.position_monitor import monitor_paper_position
from paper_execution.stop_enforcer    import enforce_stop
from ai_layer.ai_snapshot_formatter   import (
    format_position_monitor_line, format_stop_enforcer_line,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_trade(trade_id="T001", side="buy", status="filled",
                stop_reference=476.0, exit_submitted=False):
    rec = make_record(
        trade_id=trade_id,
        symbol="QQQ",
        intent_id="intent_001",
        intent_type="long",
        side=side,
        qty=100,
        entry_reference=479.0,
        stop_reference=stop_reference,
        risk_per_share=3.0,
        risk_dollars=300.0,
        order_status=status,
        alpaca_order_id="ALPA_001",
        reason="test",
    )
    rec["exit_submitted"] = exit_submitted
    return rec


def _base_env():
    return {
        "PAPER_TRADING_ONLY":         "true",
        "PAPER_STOP_MONITOR_ENABLED": "true",
        "PAPER_EXIT_ON_STOP":         "false",
        "ALPACA_BASE_URL":            "https://paper-api.alpaca.markets",
        "ALPACA_API_KEY":             "TESTKEY",
        "ALPACA_SECRET_KEY":          "TESTSECRET",
    }


def _fake_position(side="long", qty="100", current_price="477.5",
                   avg_entry="479.0", pnl="-150.0"):
    return {
        "symbol":          "QQQ",
        "qty":             qty,
        "side":            side,
        "avg_entry_price": avg_entry,
        "current_price":   current_price,
        "unrealized_pl":   pnl,
        "market_value":    "47750.0",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Trade Journal Phase 2B lifecycle tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestJournalLifecycle(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        tj_mod._TRADES_DIR = self._tmpdir

    def _save_trade(self, rec, symbol="QQQ"):
        append_trade(rec, symbol)

    def test_find_active_trade_returns_filled(self):
        rec = _make_trade(status="filled")
        self._save_trade(rec)
        found, fp = find_active_trade("QQQ", "buy")
        self.assertIsNotNone(found)
        self.assertEqual(found["trade_id"], "T001")
        self.assertIsNotNone(fp)

    def test_find_active_trade_ignores_exit_submitted(self):
        rec = _make_trade(status="filled", exit_submitted=True)
        self._save_trade(rec)
        found, _ = find_active_trade("QQQ", "buy")
        self.assertIsNone(found)

    def test_find_active_trade_ignores_closed(self):
        rec = _make_trade(status="closed")
        self._save_trade(rec)
        found, _ = find_active_trade("QQQ", "buy")
        self.assertIsNone(found)

    def test_find_active_trade_wrong_side(self):
        rec = _make_trade(side="buy", status="filled")
        self._save_trade(rec)
        found, _ = find_active_trade("QQQ", "sell")
        self.assertIsNone(found)

    def test_update_trade_status(self):
        rec = _make_trade(status="submitted")
        self._save_trade(rec)
        ok = update_trade_status("T001", "filled", {"avg_fill_price": 479.0}, "QQQ")
        self.assertTrue(ok)
        found, _ = find_active_trade("QQQ", "buy")
        self.assertIsNotNone(found)
        self.assertEqual(found["order_status"], "filled")
        self.assertEqual(found["avg_fill_price"], 479.0)

    def test_mark_exit_submitted(self):
        rec = _make_trade(status="filled")
        self._save_trade(rec)
        ok = mark_exit_submitted("T001", "EXIT001", 476.0, "stop_breached", "QQQ")
        self.assertTrue(ok)
        # Find should now return None (exit_submitted=True)
        found, _ = find_active_trade("QQQ", "buy")
        self.assertIsNone(found)

    def test_mark_closed(self):
        rec = _make_trade(status="filled")
        self._save_trade(rec)
        ok = mark_closed("T001", -150.0, "20260604T141500", "stop_hit", "QQQ")
        self.assertTrue(ok)
        found, _ = find_active_trade("QQQ", "buy")
        self.assertIsNone(found)

    def test_update_nonexistent_trade(self):
        ok = update_trade_status("GHOST_ID", "filled", {}, "QQQ")
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════════════════════════
# Position Monitor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionMonitor(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        tj_mod._TRADES_DIR = self._tmpdir

    @patch.dict(os.environ, {**_base_env(), "PAPER_STOP_MONITOR_ENABLED": "false"})
    def test_disabled_when_env_false(self):
        result = monitor_paper_position({}, "QQQ")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["status"], "disabled")

    @patch.dict(os.environ, _base_env())
    @patch.object(broker_mod, "get_position", return_value=None)
    @patch.object(broker_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_no_position_returns_no_position(self, mock_safe, mock_pos):
        result = monitor_paper_position({}, "QQQ")
        self.assertTrue(result["enabled"])
        self.assertFalse(result["has_open_position"])
        self.assertEqual(result["status"], "no_position")

    @patch.dict(os.environ, _base_env())
    @patch.object(broker_mod, "get_position", return_value={"error": "API failure"})
    @patch.object(broker_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_position_error_returns_no_position(self, mock_safe, mock_pos):
        result = monitor_paper_position({}, "QQQ")
        self.assertEqual(result["status"], "no_position")
        self.assertIn("position fetch error", result["warnings"][0])

    @patch.dict(os.environ, _base_env())
    @patch.object(pm_mod, "get_order", return_value=None)
    @patch.object(pm_mod, "get_position", return_value=_fake_position())
    @patch.object(pm_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_open_position_no_journal_trade(self, mock_safe, mock_pos, mock_ord):
        result = monitor_paper_position({}, "QQQ")
        self.assertTrue(result["has_open_position"])
        self.assertEqual(result["status"], "monitoring")
        self.assertEqual(result["side"], "long")
        self.assertEqual(result["qty"], 100)
        self.assertIsNone(result["linked_trade_id"])
        self.assertIn("no linked journal trade", result["warnings"][0])

    @patch.dict(os.environ, _base_env())
    @patch.object(pm_mod, "get_order", return_value={"status": "filled", "filled_avg_price": "479.0", "filled_qty": "100"})
    @patch.object(pm_mod, "get_position", return_value=_fake_position())
    @patch.object(pm_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_open_position_with_journal_trade(self, mock_safe, mock_pos, mock_ord):
        rec = _make_trade(status="submitted")
        append_trade(rec, "QQQ")

        result = monitor_paper_position({}, "QQQ")
        self.assertTrue(result["has_open_position"])
        self.assertEqual(result["linked_trade_id"], "T001")
        self.assertEqual(result["stop_reference"], 476.0)
        # stop_distance: 477.5 - 476.0 = 1.5
        self.assertAlmostEqual(result["stop_distance"], 1.5, places=2)

    @patch.dict(os.environ, _base_env())
    @patch.object(pm_mod, "get_position", return_value=_fake_position(side="short", current_price="482.0", avg_entry="479.0", pnl="-300.0"))
    @patch.object(pm_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_short_position_stop_distance(self, mock_safe, mock_pos):
        rec = _make_trade(side="sell", status="filled", stop_reference=483.0)
        rec["intent_type"] = "short"
        append_trade(rec, "QQQ")

        result = monitor_paper_position({}, "QQQ")
        self.assertEqual(result["side"], "short")
        # stop_distance: 483.0 - 482.0 = 1.0
        self.assertAlmostEqual(result["stop_distance"], 1.0, places=2)

    @patch.dict(os.environ, _base_env())
    @patch.object(pm_mod, "is_paper_account_safe", return_value=(False, "paper check failed"))
    def test_paper_safety_failed(self, mock_safe):
        result = monitor_paper_position({}, "QQQ")
        self.assertEqual(result["status"], "no_position")
        self.assertIn("paper safety failed", result["warnings"][0])

    @patch.dict(os.environ, _base_env())
    @patch.object(pm_mod, "get_position", side_effect=RuntimeError("boom"))
    @patch.object(pm_mod, "is_paper_account_safe", return_value=(True, "ok"))
    def test_exception_returns_error_status(self, mock_safe, mock_pos):
        result = monitor_paper_position({}, "QQQ")
        self.assertEqual(result["status"], "error")
        self.assertIn("monitor error", result["warnings"][0])


# ═══════════════════════════════════════════════════════════════════════════════
# Stop Enforcer tests
# ═══════════════════════════════════════════════════════════════════════════════

def _monitor_result(has_pos=True, side="long", current_price=477.5,
                    stop_reference=476.0, qty=100, linked_trade_id="T001",
                    exit_already=False):
    return {
        "enabled":               True,
        "has_open_position":     has_pos,
        "symbol":                "QQQ",
        "qty":                   qty,
        "side":                  side,
        "avg_entry_price":       479.0,
        "current_price":         current_price,
        "linked_trade_id":       linked_trade_id,
        "stop_reference":        stop_reference,
        "stop_distance":         round(current_price - stop_reference if side == "long" else stop_reference - current_price, 4),
        "unrealized_pnl":        -150.0,
        "exit_already_submitted": exit_already,
        "status":                "monitoring",
        "warnings":              [],
    }


class TestStopEnforcer(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        tj_mod._TRADES_DIR = self._tmpdir

    # ── disabled ──────────────────────────────────────────────────────────────

    @patch.dict(os.environ, {**_base_env(), "PAPER_STOP_MONITOR_ENABLED": "false"})
    def test_disabled_when_env_false(self):
        result = enforce_stop({}, "QQQ", _monitor_result())
        self.assertFalse(result["enabled"])
        self.assertEqual(result["action_taken"], "disabled")

    @patch.dict(os.environ, _base_env())
    def test_disabled_monitor_means_disabled(self):
        mon = _monitor_result()
        mon["enabled"] = False
        result = enforce_stop({}, "QQQ", mon)
        self.assertFalse(result["enabled"])

    @patch.dict(os.environ, _base_env())
    def test_no_position_returns_no_position(self):
        mon = _monitor_result(has_pos=False)
        mon["status"] = "no_position"
        result = enforce_stop({}, "QQQ", mon)
        self.assertEqual(result["action_taken"], "no_position")

    # ── no breach ─────────────────────────────────────────────────────────────

    @patch.dict(os.environ, _base_env())
    def test_long_no_breach_above_stop(self):
        """Price 477.5 above stop 476.0 — no breach."""
        result = enforce_stop({}, "QQQ", _monitor_result(current_price=477.5, stop_reference=476.0))
        self.assertFalse(result["stop_breached"])
        self.assertEqual(result["action_taken"], "monitoring")

    @patch.dict(os.environ, _base_env())
    def test_short_no_breach_below_stop(self):
        """Price 476.0 below stop 483.0 — no breach for short."""
        result = enforce_stop({}, "QQQ", _monitor_result(
            side="short", current_price=476.0, stop_reference=483.0
        ))
        self.assertFalse(result["stop_breached"])

    # ── breach detected, PAPER_EXIT_ON_STOP=false ────────────────────────────

    @patch.dict(os.environ, {**_base_env(), "PAPER_EXIT_ON_STOP": "false"})
    def test_long_breach_no_action_when_exit_disabled(self):
        """Price 475.0 <= stop 476.0 — breach detected, but PAPER_EXIT_ON_STOP=false."""
        result = enforce_stop({}, "QQQ", _monitor_result(current_price=475.0, stop_reference=476.0))
        self.assertTrue(result["stop_breached"])
        self.assertEqual(result["action_taken"], "stop_breached_no_action")
        self.assertFalse(result["exit_submitted"])

    @patch.dict(os.environ, {**_base_env(), "PAPER_EXIT_ON_STOP": "false"})
    def test_short_breach_no_action_when_exit_disabled(self):
        result = enforce_stop({}, "QQQ", _monitor_result(
            side="short", current_price=484.0, stop_reference=483.0
        ))
        self.assertTrue(result["stop_breached"])
        self.assertEqual(result["action_taken"], "stop_breached_no_action")

    # ── breach detected, exit already submitted ───────────────────────────────

    @patch.dict(os.environ, {**_base_env(), "PAPER_EXIT_ON_STOP": "true"})
    def test_exit_already_submitted_skips(self):
        result = enforce_stop({}, "QQQ", _monitor_result(
            current_price=475.0, stop_reference=476.0, exit_already=True
        ))
        self.assertTrue(result["stop_breached"])
        self.assertEqual(result["action_taken"], "exit_already_submitted")
        self.assertFalse(result["exit_submitted"])

    # ── breach + PAPER_EXIT_ON_STOP=true → submit exit ───────────────────────

    @patch.dict(os.environ, {**_base_env(), "PAPER_EXIT_ON_STOP": "true"})
    @patch.object(se_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(se_mod, "submit_paper_exit_order",
                  return_value={"alpaca_order_id": "EXIT_001", "status": "accepted"})
    def test_breach_exits_when_enabled(self, mock_exit, mock_safe):
        rec = _make_trade(status="filled")
        append_trade(rec, "QQQ")

        result = enforce_stop({}, "QQQ", _monitor_result(current_price=475.0, stop_reference=476.0))
        self.assertTrue(result["stop_breached"])
        self.assertTrue(result["exit_submitted"])
        self.assertEqual(result["exit_order_id"], "EXIT_001")
        self.assertEqual(result["action_taken"], "exit_submitted")
        mock_exit.assert_called_once_with("QQQ", 100, "sell")

    @patch.dict(os.environ, {**_base_env(), "PAPER_EXIT_ON_STOP": "true"})
    @patch.object(se_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(se_mod, "submit_paper_exit_order", side_effect=RuntimeError("broker down"))
    def test_breach_exit_failure_captured(self, mock_exit, mock_safe):
        result = enforce_stop({}, "QQQ", _monitor_result(current_price=475.0, stop_reference=476.0))
        self.assertTrue(result["stop_breached"])
        self.assertFalse(result["exit_submitted"])
        self.assertEqual(result["action_taken"], "exit_failed")
        self.assertIn("broker down", result["warnings"][0])

    # ── no stop_reference ────────────────────────────────────────────────────

    @patch.dict(os.environ, _base_env())
    def test_no_stop_reference_skips(self):
        mon = _monitor_result()
        mon["stop_reference"] = None
        result = enforce_stop({}, "QQQ", mon)
        self.assertFalse(result["stop_breached"])
        self.assertIn("no stop_reference", result["warnings"][0])


# ═══════════════════════════════════════════════════════════════════════════════
# Formatter tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatterLines(unittest.TestCase):

    def test_position_monitor_no_position(self):
        pm = {"enabled": True, "has_open_position": False, "status": "no_position", "warnings": []}
        line = format_position_monitor_line(pm)
        self.assertIn("no open position", line)

    def test_position_monitor_monitoring(self):
        pm = {
            "enabled": True,
            "has_open_position": True,
            "status": "monitoring",
            "side": "long",
            "qty": 100,
            "current_price": 477.5,
            "stop_reference": 476.0,
            "stop_distance": 1.5,
            "unrealized_pnl": -150.0,
        }
        line = format_position_monitor_line(pm)
        self.assertIn("long", line)
        self.assertIn("477.5", line)
        self.assertIn("476.0", line)

    def test_position_monitor_disabled(self):
        line = format_position_monitor_line({"enabled": False})
        self.assertEqual(line, "")

    def test_position_monitor_empty(self):
        self.assertEqual(format_position_monitor_line({}), "")

    def test_stop_enforcer_monitoring_no_breach(self):
        se = {"enabled": True, "stop_breached": False, "action_taken": "monitoring"}
        line = format_stop_enforcer_line(se)
        self.assertEqual(line, "")   # no breach → no line

    def test_stop_enforcer_no_action(self):
        se = {
            "enabled": True,
            "stop_breached": True,
            "action_taken": "stop_breached_no_action",
            "warnings": [],
        }
        line = format_stop_enforcer_line(se)
        self.assertIn("PAPER_EXIT_ON_STOP=false", line)

    def test_stop_enforcer_exit_submitted(self):
        se = {
            "enabled": True,
            "stop_breached": True,
            "action_taken": "exit_submitted",
            "exit_order_id": "EXIT_001",
        }
        line = format_stop_enforcer_line(se)
        self.assertIn("EXIT SUBMITTED", line)
        self.assertIn("EXIT_001", line)

    def test_stop_enforcer_already_submitted(self):
        se = {"enabled": True, "stop_breached": True, "action_taken": "exit_already_submitted"}
        line = format_stop_enforcer_line(se)
        self.assertIn("already in flight", line)

    def test_stop_enforcer_disabled(self):
        self.assertEqual(format_stop_enforcer_line({"enabled": False}), "")
        self.assertEqual(format_stop_enforcer_line({}), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
