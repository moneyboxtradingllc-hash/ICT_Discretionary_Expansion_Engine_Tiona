"""
OPS-1 — Startup Authority & Operational Hardening test suite.

Drills (mandated by the OPS-1 approval):
  - wrong-config drill         -> DENIED
  - duplicate-instance drill   -> DENIED
  - restart-with-open-position -> MANAGEMENT_ONLY
  - stale-state drill          -> prior-day entry orders cancelled, stops kept
  - end-of-day drill           -> cutoff + flatten semantics
Plus: verdict logic (observe-only failures DEGRADE, never DENY),
attestation persistence, heartbeat, lock lifecycle.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import operational_readiness.startup_authority as sa
import operational_readiness.eod_authority as eod
from operational_readiness.startup_authority import (
    run_startup_authority, acquire_instance_lock, release_instance_lock,
    attest_config, write_heartbeat,
)
from operational_readiness.eod_authority import check_eod_state

_GOOD_ENV = {
    "PAPER_TRADING_ONLY":       "true",
    "MAX_TRADES_PER_DAY":       "2",
    "RISK_PER_TRADE_DOLLARS":   "500",
    "DAILY_LOSS_LIMIT_DOLLARS": "500",
    "PAPER_EXIT_ON_STOP":       "true",
}


class _OpsBase(unittest.TestCase):
    """Isolated OPS_DIR + clean env per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["OPS_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("OPS_DIR", None))
        self._saved = {}
        for k, v in _GOOD_ENV.items():
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        self.addCleanup(self._restore)
        self.addCleanup(release_instance_lock)

    def _restore(self):
        for k, old in self._saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


# ══════════════════════════════════════════════════════════════════════════════
# Verdict logic (offline: skip_network)
# ══════════════════════════════════════════════════════════════════════════════

class TestVerdictLogic(_OpsBase):

    def test_clean_config_grants_authority(self):
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "GRANTED")
        self.assertEqual(auth["mode"], "NORMAL")
        self.assertEqual(auth["mandatory_failures"], [])

    def test_no_scores_no_percentages(self):
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertNotIn("score", auth)
        self.assertNotIn("ready", auth)
        self.assertIn(auth["verdict"], ("GRANTED", "DENIED", "DEGRADED"))

    def test_observe_only_failure_degrades_never_denies(self):
        """Constitutional: the measurement plane has no execution veto."""
        with patch.object(sa, "_check_observe_plane",
                          return_value=(False, "ledger dir on fire")):
            auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DEGRADED")
        self.assertTrue(any("ledger dir on fire" in r
                            for r in auth["degraded_reasons"]))

    def test_governance_quarantine_degrades(self):
        with patch.object(sa, "_check_governance_plane",
                          return_value=(False, "quarantined records")):
            auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DEGRADED")

    def test_intelligence_smoke_crash_denies(self):
        with patch.object(sa, "_smoke_intelligence",
                          return_value=(False, "gate crashed on smoke")):
            auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")

    def test_decision_persisted_to_ops_dir(self):
        run_startup_authority("QQQ", skip_network=True)
        date_str = datetime.now().strftime("%Y%m%d")
        path = os.path.join(self.tmp.name, f"startup_authority_{date_str}.json")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn(saved["verdict"], ("GRANTED", "DEGRADED", "DENIED"))


# ══════════════════════════════════════════════════════════════════════════════
# Wrong-config drill
# ══════════════════════════════════════════════════════════════════════════════

class TestWrongConfigDrill(_OpsBase):

    def test_live_trading_flag_denies(self):
        os.environ["PAPER_TRADING_ONLY"] = "false"
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")
        self.assertTrue(any("PAPER_TRADING_ONLY" in f
                            for f in auth["mandatory_failures"]))

    def test_risk_above_ceiling_denies(self):
        os.environ["RISK_PER_TRADE_DOLLARS"] = "750"
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")
        self.assertTrue(any("exceeds ceiling" in f
                            for f in auth["mandatory_failures"]))

    def test_max_trades_above_ceiling_denies(self):
        os.environ["MAX_TRADES_PER_DAY"] = "5"
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")

    def test_stop_enforcement_off_denies(self):
        os.environ["PAPER_EXIT_ON_STOP"] = "false"
        auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")
        self.assertTrue(any("PAPER_EXIT_ON_STOP" in f
                            for f in auth["mandatory_failures"]))

    def test_attestation_records_effective_config(self):
        att = attest_config()
        self.assertTrue(att["ok"])
        self.assertEqual(att["effective"]["MAX_TRADES_PER_DAY"], "2")
        date_str = datetime.now().strftime("%Y%m%d")
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, f"config_attestation_{date_str}.json")))


# ══════════════════════════════════════════════════════════════════════════════
# Duplicate-instance drill
# ══════════════════════════════════════════════════════════════════════════════

class TestDuplicateInstanceDrill(_OpsBase):

    def test_second_instance_denied_while_first_alive(self):
        with open(os.path.join(self.tmp.name, "bot.lock"), "w",
                  encoding="utf-8") as f:
            json.dump({"pid": 99999, "acquired": "x"}, f)
        with patch.object(sa, "_pid_alive", return_value=True):
            ok, reason = acquire_instance_lock()
        self.assertFalse(ok)
        self.assertIn("another bot instance is alive", reason)
        with patch.object(sa, "_pid_alive", return_value=True):
            auth = run_startup_authority("QQQ", skip_network=True)
        self.assertEqual(auth["verdict"], "DENIED")

    def test_stale_lock_from_dead_process_reclaimed(self):
        with open(os.path.join(self.tmp.name, "bot.lock"), "w",
                  encoding="utf-8") as f:
            json.dump({"pid": 99999, "acquired": "x"}, f)
        with patch.object(sa, "_pid_alive", return_value=False):
            ok, reason = acquire_instance_lock()
        self.assertTrue(ok)
        self.assertIn("lock acquired", reason)

    def test_release_only_removes_own_lock(self):
        with open(os.path.join(self.tmp.name, "bot.lock"), "w",
                  encoding="utf-8") as f:
            json.dump({"pid": 99999, "acquired": "x"}, f)
        release_instance_lock()    # not ours — must remain
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "bot.lock")))
        acquire_instance_lock()    # reclaim (dead pid)
        release_instance_lock()    # ours — removed
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "bot.lock")))


# ══════════════════════════════════════════════════════════════════════════════
# Restart-with-open-position drill
# ══════════════════════════════════════════════════════════════════════════════

class TestRestartDrill(_OpsBase):

    def test_open_position_with_journal_trade_management_only(self):
        from operational_readiness.startup_authority import _detect_restart_position
        with patch("paper_execution.paper_broker.get_position",
                   return_value={"qty": "88", "symbol": "QQQ"}), \
             patch("paper_execution.trade_journal.find_any_active_trade",
                   return_value=({"trade_id": "PT_X"}, "f.json")):
            management_only, detail = _detect_restart_position("QQQ")
        self.assertTrue(management_only)
        self.assertIn("MANAGEMENT_ONLY", detail)
        self.assertIn("PT_X", detail)

    def test_orphan_position_without_journal_also_management_only(self):
        from operational_readiness.startup_authority import _detect_restart_position
        with patch("paper_execution.paper_broker.get_position",
                   return_value={"qty": "88", "symbol": "QQQ"}), \
             patch("paper_execution.trade_journal.find_any_active_trade",
                   return_value=(None, None)):
            management_only, detail = _detect_restart_position("QQQ")
        self.assertTrue(management_only)
        self.assertIn("NO journal", detail)

    def test_flat_account_normal_mode(self):
        from operational_readiness.startup_authority import _detect_restart_position
        with patch("paper_execution.paper_broker.get_position",
                   return_value=None):
            management_only, detail = _detect_restart_position("QQQ")
        self.assertFalse(management_only)


# ══════════════════════════════════════════════════════════════════════════════
# Stale-state drill
# ══════════════════════════════════════════════════════════════════════════════

class TestStaleStateDrill(_OpsBase):

    def _run_hygiene(self, orders, positions):
        from operational_readiness.startup_authority import _stale_state_hygiene
        cancelled = []
        with patch("paper_execution.trade_reconciliation.reconcile_trade",
                   return_value={"status": "no_active_trade"}), \
             patch("paper_execution.paper_broker.get_open_orders",
                   return_value=orders), \
             patch("paper_execution.paper_broker.get_open_positions",
                   return_value=positions), \
             patch("paper_execution.paper_broker.cancel_order",
                   side_effect=lambda oid: cancelled.append(oid) or
                   {"canceled": True}):
            ok, detail = _stale_state_hygiene("QQQ")
        return ok, detail, cancelled

    def test_prior_day_entry_order_cancelled(self):
        ok, detail, cancelled = self._run_hygiene(
            orders=[{"order_id": "OLD1", "order_type": "limit",
                     "submitted_at": "2026-06-09T10:00:00Z"}],
            positions=[],
        )
        self.assertTrue(ok)
        self.assertEqual(cancelled, ["OLD1"])
        self.assertIn("stale orders cancelled: 1", detail)

    def test_protective_stop_for_live_position_kept(self):
        ok, detail, cancelled = self._run_hygiene(
            orders=[{"order_id": "STOP1", "order_type": "stop",
                     "submitted_at": "2026-06-09T10:00:00Z"}],
            positions=[{"symbol": "QQQ", "qty": "88"}],
        )
        self.assertTrue(ok)
        self.assertEqual(cancelled, [])   # never touch a live stop

    def test_todays_orders_left_alone(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, detail, cancelled = self._run_hygiene(
            orders=[{"order_id": "NEW1", "order_type": "limit",
                     "submitted_at": f"{today}T10:00:00Z"}],
            positions=[],
        )
        self.assertEqual(cancelled, [])
        self.assertIn("no stale orders", detail)


# ══════════════════════════════════════════════════════════════════════════════
# End-of-day drill
# ══════════════════════════════════════════════════════════════════════════════

class TestEndOfDayDrill(_OpsBase):

    @staticmethod
    def _at(hh, mm):
        import pytz
        tz = pytz.timezone("America/New_York")
        return tz.localize(datetime(2026, 6, 11, hh, mm))

    def test_entries_allowed_midday(self):
        state = check_eod_state(self._at(13, 0))
        self.assertTrue(state["entries_allowed"])
        self.assertFalse(state["should_flatten"])

    def test_entry_cutoff_at_1550(self):
        state = check_eod_state(self._at(15, 50))
        self.assertFalse(state["entries_allowed"])
        self.assertFalse(state["should_flatten"])

    def test_flatten_at_1555_default_policy(self):
        state = check_eod_state(self._at(15, 55))
        self.assertFalse(state["entries_allowed"])
        self.assertTrue(state["should_flatten"])

    def test_hold_policy_is_explicit_attestation(self):
        os.environ["EOD_POLICY"] = "hold"
        self.addCleanup(lambda: os.environ.pop("EOD_POLICY", None))
        state = check_eod_state(self._at(15, 56))
        self.assertFalse(state["should_flatten"])
        self.assertEqual(state["policy"], "hold")

    def test_invalid_policy_defaults_to_flatten(self):
        os.environ["EOD_POLICY"] = "yolo"
        self.addCleanup(lambda: os.environ.pop("EOD_POLICY", None))
        self.assertEqual(check_eod_state(self._at(12, 0))["policy"], "flatten")

    def test_flatten_cancels_stop_before_closing(self):
        """The June 10 lesson: the stop holds the shares — cancel it FIRST."""
        order_of_ops = []
        with patch("paper_execution.paper_broker.get_position",
                   return_value={"qty": "88", "current_price": 700.0}), \
             patch("paper_execution.trade_journal.find_any_active_trade",
                   return_value=({"trade_id": "PT_X",
                                  "broker_stop_order_id": "STOP1"}, "f")), \
             patch("paper_execution.paper_broker.cancel_order",
                   side_effect=lambda oid: order_of_ops.append(("cancel", oid))
                   or {"canceled": True}), \
             patch("paper_execution.paper_broker.close_position_market",
                   side_effect=lambda s: order_of_ops.append(("close", s))
                   or {"alpaca_order_id": "EXIT1"}), \
             patch("paper_execution.trade_journal.mark_exit_submitted",
                   return_value=True) as mes:
            result = eod.flatten_position_eod("QQQ")

        self.assertTrue(result["flattened"])
        self.assertEqual(order_of_ops[0], ("cancel", "STOP1"))
        self.assertEqual(order_of_ops[1], ("close", "QQQ"))
        self.assertTrue(result["stop_cancelled"])
        self.assertEqual(mes.call_args.kwargs["reason"], "eod_flatten")

    def test_flatten_with_no_position_is_noop(self):
        with patch("paper_execution.paper_broker.get_position",
                   return_value=None):
            result = eod.flatten_position_eod("QQQ")
        self.assertFalse(result["flattened"])
        self.assertIn("no open position", result["reason"])

    def test_flatten_never_raises(self):
        with patch("paper_execution.paper_broker.get_position",
                   side_effect=RuntimeError("boom")):
            result = eod.flatten_position_eod("QQQ")
        self.assertFalse(result["flattened"])
        self.assertIn("error", result["reason"])


# ══════════════════════════════════════════════════════════════════════════════
# Heartbeat
# ══════════════════════════════════════════════════════════════════════════════

class TestHeartbeat(_OpsBase):

    def test_heartbeat_written_with_scan_and_mode(self):
        write_heartbeat(42, status="normal")
        path = os.path.join(self.tmp.name, "heartbeat.json")
        with open(path, encoding="utf-8") as f:
            hb = json.load(f)
        self.assertEqual(hb["scan"], 42)
        self.assertEqual(hb["status"], "normal")
        self.assertEqual(hb["pid"], os.getpid())

    def test_heartbeat_never_raises(self):
        os.environ["OPS_DIR"] = "Z:\\\\nonexistent\\\\ops"
        write_heartbeat(1)    # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
