"""
Phase 5E.5 — Pending Entry Order Lifecycle Cancellation Tests.

Defect: When a setup dies (invalidated, dormant, expired, no_trade), any
pending unfilled LIMIT entry order at Alpaca remains live until 16:00 ET.
A price reversal can fill it in a dead-setup context, producing an
unintended position with its stop already breached (confirmed stale fill
scenario: scan #59, Day 1 paper trading).

Patch: pending_order_lifecycle.cancel_pending_entry_order_if_setup_dead()
       is called every scan after trade_reconciliation. It cancels pending
       entry orders when the setup has died.

Tests:
  01  find_pending_entry_order returns submitted order
  02  find_pending_entry_order returns None when no pending order
  03  invalidated setup (sl["invalidated"]=True) cancels pending entry
  04  dormant current_phase cancels pending entry
  05  expired current_phase cancels pending entry (defensive)
  06  no_trade qualification cancels pending entry
  07  active/forming setup does NOT cancel
  08  maturing setup does NOT cancel
  09  waiting_for_retest with active setup does NOT cancel
  10  retest_in_progress with active setup does NOT cancel
  11  confirmation_needed with active setup does NOT cancel
  12  filled order is NOT cancelled (returns live result)
  13  closed/terminal order not returned by find_pending_entry_order
  14  open position prevents cancellation
  15  broker protective stop order is NOT what cancel_order is called with
  16  cancel_order failure returns cancel_failed, does not raise
  17  journal updated with correct Phase 5E.5 fields on success
  18  cancelled unfilled order does NOT consume MAX_TRADES_PER_DAY
  19  full regression — all Phase 5E.5 modules importable

All tests use mocks — no live Alpaca calls, no real journal files.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _dead_snapshot_invalidated():
    return {
        "setup_lifecycle": {
            "active":        False,
            "invalidated":   True,
            "current_phase": "invalidated",
            "reason":        "State transition flagged invalidated",
        },
        "state_transition": {
            "invalidated":    True,
            "setup_lifecycle": "invalidated",
        },
        "qualification": {"status": "no_trade"},
    }


def _dead_snapshot_dormant():
    return {
        "setup_lifecycle": {
            "active":        False,
            "invalidated":   False,
            "current_phase": "dormant",
        },
        "state_transition": {
            "invalidated":    False,
            "setup_lifecycle": "dormant",
        },
        "qualification": {"status": "no_trade"},
    }


def _dead_snapshot_expired():
    return {
        "setup_lifecycle": {
            "active":        False,
            "invalidated":   False,
            "current_phase": "expired",
        },
        "state_transition": {
            "invalidated":    False,
            "setup_lifecycle": "expired",
        },
        "qualification": {"status": "no_trade"},
    }


def _dead_snapshot_no_trade():
    return {
        "setup_lifecycle": {
            "active":        False,
            "invalidated":   False,
            "current_phase": "forming",
        },
        "state_transition": {
            "invalidated":    False,
            "setup_lifecycle": "dormant",
        },
        "qualification": {"status": "no_trade"},
    }


def _alive_snapshot(trigger="forming"):
    return {
        "setup_lifecycle": {
            "active":        True,
            "invalidated":   False,
            "current_phase": trigger,
        },
        "state_transition": {
            "invalidated":    False,
            "setup_lifecycle": "maturing",
        },
        "qualification": {"status": "qualified"},
    }


def _pending_trade_record():
    return {
        "trade_id":            "PT_QQQ_20260608T124837",
        "symbol":              "QQQ",
        "alpaca_order_id":     "alpaca-uuid-scan59",
        "order_status":        "submitted",
        "exit_submitted":      False,
        "final_status":        None,
        "broker_stop_order_id": None,
        "risk_dollars":        100.0,
        "pending_order_cancelled": False,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPhase5E5PendingOrderLifecycle(unittest.TestCase):

    # 01 — find_pending_entry_order returns a submitted order from the journal
    def test_01_find_pending_entry_order_returns_submitted(self):
        from paper_execution.trade_journal import find_pending_entry_order
        trade = _pending_trade_record()
        fake_files = [("20260608", "/fake/path.json", [trade])]
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=fake_files):
            result = find_pending_entry_order("QQQ")
        self.assertIsNotNone(result)
        self.assertEqual(result["trade_id"], "PT_QQQ_20260608T124837")
        self.assertEqual(result["order_status"], "submitted")

    # 02 — find_pending_entry_order returns None when no pending order exists
    def test_02_find_pending_entry_order_returns_none_when_empty(self):
        from paper_execution.trade_journal import find_pending_entry_order
        # No trades at all
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=[]):
            result = find_pending_entry_order("QQQ")
        self.assertIsNone(result)

    # 02b — find_pending_entry_order returns None when only a filled order exists
    def test_02b_find_pending_entry_order_ignores_filled_order(self):
        from paper_execution.trade_journal import find_pending_entry_order
        filled = dict(_pending_trade_record())
        filled["order_status"] = "filled"
        fake_files = [("20260608", "/fake/path.json", [filled])]
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=fake_files):
            result = find_pending_entry_order("QQQ")
        self.assertIsNone(result)

    # 03 — invalidated setup (sl["invalidated"]=True) cancels pending entry
    def test_03_invalidated_setup_cancels_pending_entry(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}) as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  return_value=True),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["reason"], "setup_lifecycle_dead")
        mock_cancel.assert_called_once_with("alpaca-uuid-scan59")

    # 04 — dormant current_phase cancels pending entry
    def test_04_dormant_phase_cancels_pending_entry(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_dormant()
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}),
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  return_value=True),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["status"], "cancelled")

    # 05 — expired current_phase cancels pending entry (defensive guard)
    def test_05_expired_phase_cancels_pending_entry(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_expired()
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}),
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  return_value=True),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])

    # 06 — no_trade qualification cancels pending entry
    def test_06_no_trade_qualification_cancels_pending_entry(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_no_trade()
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}),
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  return_value=True),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["status"], "cancelled")

    # 07 — active/forming setup does NOT cancel
    def test_07_active_forming_setup_does_not_cancel(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _alive_snapshot("forming")
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "live")
        mock_cancel.assert_not_called()

    # 08 — maturing setup does NOT cancel
    def test_08_maturing_setup_does_not_cancel(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _alive_snapshot("maturing")
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        mock_cancel.assert_not_called()

    # 09 — waiting_for_retest with active setup does NOT cancel
    def test_09_waiting_for_retest_active_setup_does_not_cancel(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap = {
            "setup_lifecycle": {
                "active":        True,
                "invalidated":   False,
                "current_phase": "forming",
            },
            "state_transition": {
                "invalidated":    False,
                "setup_lifecycle": "maturing",
            },
            "qualification": {"status": "candidate"},
        }
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        mock_cancel.assert_not_called()

    # 10 — retest_in_progress with active setup does NOT cancel
    def test_10_retest_in_progress_active_setup_does_not_cancel(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap = {
            "setup_lifecycle": {
                "active":        True,
                "invalidated":   False,
                "current_phase": "actionable",
            },
            "state_transition": {
                "invalidated":    False,
                "setup_lifecycle": "actionable_candidate",
            },
            "qualification": {"status": "qualified"},
        }
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        mock_cancel.assert_not_called()

    # 11 — confirmation_needed with active setup does NOT cancel
    def test_11_confirmation_needed_active_setup_does_not_cancel(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap = {
            "setup_lifecycle": {
                "active":        True,
                "invalidated":   False,
                "current_phase": "maturing",
            },
            "state_transition": {
                "invalidated":    False,
                "setup_lifecycle": "maturing",
            },
            "qualification": {"status": "qualified"},
        }
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        mock_cancel.assert_not_called()

    # 12 — filled order is NOT cancelled (returns live result)
    def test_12_filled_order_is_not_cancelled(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = dict(_pending_trade_record())
        trade["order_status"] = "filled"
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "live")
        mock_cancel.assert_not_called()

    # 13 — closed/terminal order not returned by find_pending_entry_order
    def test_13_terminal_order_not_returned_by_find_pending(self):
        from paper_execution.trade_journal import find_pending_entry_order
        for terminal_status in ("canceled", "cancelled", "rejected", "expired",
                                "done_for_day", "stopped", "closed"):
            with self.subTest(status=terminal_status):
                t = dict(_pending_trade_record())
                t["order_status"] = terminal_status
                fake_files = [("20260608", "/fake/path.json", [t])]
                with patch("paper_execution.trade_journal._search_recent_files",
                           return_value=fake_files):
                    result = find_pending_entry_order("QQQ")
                self.assertIsNone(
                    result,
                    f"Terminal status '{terminal_status}' must not be returned"
                )

    # 14 — open position prevents cancellation
    def test_14_open_position_prevents_cancellation(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = _pending_trade_record()
        open_pos = {"symbol": "QQQ", "qty": "1", "side": "long"}
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=open_pos),
            patch("paper_execution.pending_order_lifecycle.cancel_order") as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "live")
        self.assertIn("open position", result["reason"])
        mock_cancel.assert_not_called()

    # 15 — cancel_order is called with entry alpaca_order_id, not broker_stop_order_id
    def test_15_cancel_uses_entry_order_id_not_broker_stop_id(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = dict(_pending_trade_record())
        trade["broker_stop_order_id"] = "stop-order-uuid-999"
        entry_id = trade["alpaca_order_id"]  # "alpaca-uuid-scan59"
        stop_id  = trade["broker_stop_order_id"]

        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}) as mock_cancel,
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  return_value=True),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])
        mock_cancel.assert_called_once_with(entry_id)
        called_with = mock_cancel.call_args[0][0]
        self.assertNotEqual(called_with, stop_id,
                            "cancel_order must NOT be called with broker_stop_order_id")

    # 16 — cancel_order failure returns cancel_failed, does not raise
    def test_16_cancel_order_failure_returns_cancel_failed_no_raise(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = _pending_trade_record()
        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": False, "reason": "order already filled"}),
            patch("paper_execution.pending_order_lifecycle.update_trade_status"),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "cancel_failed")
        self.assertTrue(len(result["warnings"]) > 0)
        self.assertIn("order already filled", result["warnings"][0])

    # 17 — journal updated with correct Phase 5E.5 fields on success
    def test_17_journal_updated_with_correct_fields(self):
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
        )
        snap  = _dead_snapshot_invalidated()
        trade = _pending_trade_record()
        captured_fields = {}

        def fake_update(trade_id, status, fields, symbol):
            captured_fields.update(fields)
            captured_fields["__status__"] = status
            captured_fields["__trade_id__"] = trade_id
            return True

        with (
            patch("paper_execution.pending_order_lifecycle.is_paper_account_safe",
                  return_value=(True, "")),
            patch("paper_execution.pending_order_lifecycle.find_pending_entry_order",
                  return_value=trade),
            patch("paper_execution.pending_order_lifecycle.get_position",
                  return_value=None),
            patch("paper_execution.pending_order_lifecycle.cancel_order",
                  return_value={"canceled": True}),
            patch("paper_execution.pending_order_lifecycle.update_trade_status",
                  side_effect=fake_update),
        ):
            result = cancel_pending_entry_order_if_setup_dead(snap, "QQQ")

        self.assertTrue(result["cancelled"])
        self.assertTrue(result["journal_updated"])
        self.assertEqual(captured_fields["__status__"], "canceled")
        self.assertEqual(captured_fields["__trade_id__"], "PT_QQQ_20260608T124837")
        self.assertEqual(captured_fields["cancel_reason"], "setup_lifecycle_dead")
        self.assertTrue(captured_fields["pending_order_cancelled"])
        self.assertIn("cancelled_at", captured_fields)
        self.assertIn("setup_lifecycle_at_cancel", captured_fields)

    # 18 — cancelled unfilled order does NOT consume MAX_TRADES_PER_DAY
    def test_18_cancelled_unfilled_order_does_not_consume_max_trades(self):
        from paper_execution.trade_journal import count_submitted_today

        cancelled_trade = {
            "trade_id":              "PT_QQQ_20260608T124837",
            "alpaca_order_id":       "alpaca-uuid-scan59",
            "order_status":          "canceled",
            "pending_order_cancelled": True,
            "risk_dollars":          100.0,
        }
        live_trade = {
            "trade_id":              "PT_QQQ_20260608T140000",
            "alpaca_order_id":       "alpaca-uuid-another",
            "order_status":          "submitted",
            "pending_order_cancelled": False,
            "risk_dollars":          100.0,
        }

        with patch("paper_execution.trade_journal.load_today_trades") as mock_load:
            # Only the lifecycle-cancelled trade
            mock_load.return_value = [cancelled_trade]
            count = count_submitted_today("QQQ")
            self.assertEqual(count, 0,
                "Lifecycle-cancelled order must NOT count against MAX_TRADES_PER_DAY")

            # Only the live submitted trade
            mock_load.return_value = [live_trade]
            count = count_submitted_today("QQQ")
            self.assertEqual(count, 1,
                "Active submitted order must still count")

            # Both: cancelled + live = 1 (not 2)
            mock_load.return_value = [cancelled_trade, live_trade]
            count = count_submitted_today("QQQ")
            self.assertEqual(count, 1,
                "Cancelled + active must equal 1, not 2")

            # Record with no alpaca_order_id — should not count
            no_id_trade = {"trade_id": "PT_QQQ_early", "alpaca_order_id": None}
            mock_load.return_value = [no_id_trade]
            count = count_submitted_today("QQQ")
            self.assertEqual(count, 0,
                "Trade without alpaca_order_id must not count")

    # 19 — full regression: all Phase 5E.5 modules importable, no side effects
    def test_19_full_regression_imports(self):
        import importlib
        modules = [
            "paper_execution.pending_order_lifecycle",
            "paper_execution.trade_journal",
            "paper_execution.paper_broker",
            "paper_execution.trade_reconciliation",
            "paper_execution.position_monitor",
            "paper_execution.execution_engine",
            "paper_execution.position_guard",
            "paper_execution.protective_stop",
            "live_scan.scan_loop",
            "setup_lifecycle.setup_tracker",
            "state_transitions.transition_engine",
            "ai_layer.ai_debate_engine",
            "execution_gate.execution_gate",
            "decision_authority.decision_engine",
        ]
        for mod in modules:
            with self.subTest(module=mod):
                importlib.import_module(mod)

        # Verify the new function signatures are correct
        from paper_execution.pending_order_lifecycle import (
            cancel_pending_entry_order_if_setup_dead,
            _is_setup_dead,
        )
        from paper_execution.trade_journal import find_pending_entry_order

        # _is_setup_dead on an empty snapshot returns False (safe default)
        # when qualification is absent (defaults to "no_trade", which IS dead)
        # — but with no pending order, cancel won't fire anyway
        result = _is_setup_dead({"qualification": {"status": "qualified"},
                                 "setup_lifecycle": {},
                                 "state_transition": {}})
        self.assertFalse(result,
            "_is_setup_dead with active qual and empty lifecycle must be False")

        result = _is_setup_dead({"setup_lifecycle": {"invalidated": True},
                                 "state_transition": {},
                                 "qualification": {"status": "no_trade"}})
        self.assertTrue(result,
            "_is_setup_dead with invalidated=True must be True")


if __name__ == "__main__":
    unittest.main()
