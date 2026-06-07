"""
Phase 2C — Operational Readiness + Activation Controller unit tests.

No Alpaca API calls — broker interactions mocked.
No orders, no execution changes.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import operational_readiness.readiness_checklist  as rc_mod
import operational_readiness.activation_controller as ac_mod
import paper_execution.paper_broker as broker_mod

from operational_readiness.readiness_checklist  import run_readiness_check, _WEIGHTS, _CRITICAL
from operational_readiness.activation_controller import determine_activation
from ai_layer.ai_snapshot_formatter import (
    format_operational_readiness_line,
    format_activation_line,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _good_env():
    return {
        "ALPACA_BASE_URL":            "https://paper-api.alpaca.markets",
        "PAPER_TRADING_ONLY":         "true",
        "EXECUTION_ENABLED":          "false",
        "ALLOW_PAPER_ORDERS":         "false",
        "MAX_TRADES_PER_DAY":         "2",
        "DAILY_LOSS_LIMIT_DOLLARS":   "1000",
        "RISK_PER_TRADE_DOLLARS":     "500",
        "MIN_INTENT_GATED_SCORE":     "70",
    }


def _full_snapshot():
    """Minimal snapshot that satisfies all snapshot-derived checks."""
    return {
        "execution_gate":    {"gate_status": "locked"},
        "position_monitor":  {"enabled": True, "status": "no_position"},
        "stop_enforcer":     {"enabled": True, "action_taken": "no_position"},
        "intent_score":      {"scored": False, "raw_score": 0},
        "timeframes": {
            "1m": {"last_candle": {"close": 479.0}},
        },
    }


def _good_account():
    return {"equity": 100000.0, "cash": 100000.0, "status": "ACTIVE"}


# ═══════════════════════════════════════════════════════════════════════════════
# Weights and structure sanity
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadinessStructure(unittest.TestCase):

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(_WEIGHTS.values()), 100)

    def test_all_critical_keys_in_weights(self):
        for k in _CRITICAL:
            self.assertIn(k, _WEIGHTS, f"critical key '{k}' missing from _WEIGHTS")

    def test_13_checks_defined(self):
        self.assertEqual(len(_WEIGHTS), 13)


# ═══════════════════════════════════════════════════════════════════════════════
# Readiness checklist
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadinessChecklist(unittest.TestCase):

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_all_pass_returns_100_ready(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertTrue(result["ready"])
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["blocking_issues"], [])
        self.assertEqual(result["warnings"], [])

    @patch.dict(os.environ, {**_good_env(), "ALPACA_BASE_URL": "https://api.alpaca.markets"})
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_bad_endpoint_sets_not_ready(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertFalse(result["ready"])
        self.assertIn("paper_endpoint_verified", result["blocking_issues"])

    @patch.dict(os.environ, {**_good_env(), "PAPER_TRADING_ONLY": "false"})
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_paper_only_false_sets_not_ready(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertFalse(result["ready"])
        self.assertIn("paper_only_mode", result["blocking_issues"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=False)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_broker_down_sets_not_ready(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertFalse(result["ready"])
        self.assertIn("alpaca_connected", result["blocking_issues"])
        self.assertEqual(result["score"], 100 - _WEIGHTS["alpaca_connected"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=False)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_journal_not_writable_sets_not_ready(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertFalse(result["ready"])
        self.assertIn("journal_writable", result["blocking_issues"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_missing_execution_gate_sets_not_ready(self, *_):
        snap = _full_snapshot()
        del snap["execution_gate"]
        result = run_readiness_check(snap)
        self.assertFalse(result["ready"])
        self.assertIn("execution_gate_present", result["blocking_issues"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_missing_position_monitor_sets_not_ready(self, *_):
        snap = _full_snapshot()
        del snap["position_monitor"]
        result = run_readiness_check(snap)
        self.assertFalse(result["ready"])
        self.assertIn("position_monitor_present", result["blocking_issues"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_missing_stop_enforcer_sets_not_ready(self, *_):
        snap = _full_snapshot()
        del snap["stop_enforcer"]
        result = run_readiness_check(snap)
        self.assertFalse(result["ready"])
        self.assertIn("stop_enforcer_present", result["blocking_issues"])

    @patch.dict(os.environ, {**_good_env(), "MAX_TRADES_PER_DAY": ""})
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_missing_daily_limit_is_warning_not_blocking(self, *_):
        result = run_readiness_check(_full_snapshot())
        self.assertTrue(result["ready"])          # still ready
        self.assertIn("daily_limits_present check failed", result["warnings"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_no_market_data_is_warning_not_blocking(self, *_):
        snap = _full_snapshot()
        snap["timeframes"] = {}   # empty → check fails
        result = run_readiness_check(snap)
        self.assertTrue(result["ready"])
        self.assertIn("market_data_available check failed", result["warnings"])

    @patch.dict(os.environ, _good_env())
    @patch.object(rc_mod, "_check_alpaca_connected", return_value=True)
    @patch.object(rc_mod, "_check_journal_writable", return_value=True)
    @patch.object(rc_mod, "_check_trade_journal_present", return_value=True)
    @patch.object(rc_mod, "_check_recovery_available", return_value=True)
    def test_score_deducted_for_non_critical_fail(self, *_):
        snap = _full_snapshot()
        snap["timeframes"] = {}   # market_data_available fails (-5 pts)
        result = run_readiness_check(snap)
        self.assertEqual(result["score"], 100 - _WEIGHTS["market_data_available"])

    def test_exception_returns_safe_result(self):
        result = run_readiness_check(None)   # None snapshot causes AttributeError
        self.assertFalse(result["ready"])
        self.assertEqual(result["score"], 0)
        self.assertTrue(len(result["blocking_issues"]) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Activation controller
# ═══════════════════════════════════════════════════════════════════════════════

def _passing_readiness():
    """Readiness result with everything passing."""
    checks = {k: True for k in _WEIGHTS}
    return {
        "ready":           True,
        "score":           100,
        "checks":          checks,
        "warnings":        [],
        "blocking_issues": [],
    }


def _failing_readiness(issue="alpaca_connected"):
    checks = {k: True for k in _WEIGHTS}
    checks[issue] = False
    return {
        "ready":           False,
        "score":           100 - _WEIGHTS.get(issue, 5),
        "checks":          checks,
        "warnings":        [],
        "blocking_issues": [issue],
    }


class TestActivationController(unittest.TestCase):

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false"})
    def test_not_ready_when_readiness_fails(self):
        result = determine_activation(_failing_readiness())
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("alpaca_connected", result["requirements_remaining"])

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false"})
    def test_safe_but_disabled_when_execution_off(self):
        result = determine_activation(_passing_readiness())
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(result["status"], "safe_but_disabled")
        self.assertIn("EXECUTION_ENABLED=false", result["reason"])

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "true", "ALLOW_PAPER_ORDERS": "false"})
    def test_activation_blocked_when_paper_orders_off(self):
        result = determine_activation(_passing_readiness())
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(result["status"], "activation_blocked")
        self.assertIn("ALLOW_PAPER_ORDERS=false", result["reason"])

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "true", "ALLOW_PAPER_ORDERS": "true"})
    def test_ready_for_activation_when_all_pass(self):
        result = determine_activation(_passing_readiness())
        self.assertTrue(result["activation_allowed"])
        self.assertEqual(result["status"], "ready_for_activation")
        self.assertEqual(result["requirements_remaining"], [])

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "true", "ALLOW_PAPER_ORDERS": "true"})
    def test_not_ready_overrides_enabled_flags(self):
        result = determine_activation(_failing_readiness("paper_endpoint_verified"))
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(result["status"], "not_ready")

    def test_exception_in_readiness_returns_not_ready(self):
        result = determine_activation(None)
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(result["status"], "not_ready")

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false"})
    def test_requirements_remaining_empty_when_safe_but_disabled(self):
        result = determine_activation(_passing_readiness())
        self.assertEqual(result["requirements_remaining"], [])

    @patch.dict(os.environ, {"EXECUTION_ENABLED": "true", "ALLOW_PAPER_ORDERS": "true"})
    def test_activation_allowed_is_certification_only(self):
        """activation_allowed=True must not change EXECUTION_ENABLED or place orders."""
        result = determine_activation(_passing_readiness())
        self.assertTrue(result["activation_allowed"])
        # env flags unchanged
        self.assertEqual(os.getenv("EXECUTION_ENABLED"), "true")
        self.assertEqual(os.getenv("ALLOW_PAPER_ORDERS"), "true")


# ═══════════════════════════════════════════════════════════════════════════════
# Formatter tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadinessFormatterLines(unittest.TestCase):

    def test_ready_100_line(self):
        orr = {"ready": True, "score": 100, "blocking_issues": [], "warnings": []}
        line = format_operational_readiness_line(orr)
        self.assertIn("100/100", line)
        self.assertIn("Ready", line)

    def test_ready_96_line(self):
        orr = {"ready": True, "score": 96, "blocking_issues": [], "warnings": ["market_data check failed"]}
        line = format_operational_readiness_line(orr)
        self.assertIn("96/100", line)
        self.assertNotIn("Blocking", line)

    def test_not_ready_shows_blocking_issue(self):
        orr = {"ready": False, "score": 72, "blocking_issues": ["alpaca_connected"], "warnings": []}
        line = format_operational_readiness_line(orr)
        self.assertIn("NOT READY", line)
        self.assertIn("alpaca_connected", line)

    def test_empty_returns_empty_string(self):
        self.assertEqual(format_operational_readiness_line({}), "")
        self.assertEqual(format_operational_readiness_line(None), "")

    def test_activation_safe_but_disabled(self):
        ac = {"status": "safe_but_disabled", "reason": "EXECUTION_ENABLED=false"}
        line = format_activation_line(ac)
        self.assertIn("SAFE_BUT_DISABLED", line)
        self.assertIn("EXECUTION_ENABLED=false", line)

    def test_activation_ready_for_activation(self):
        ac = {"status": "ready_for_activation", "reason": "all operational checks passed"}
        line = format_activation_line(ac)
        self.assertIn("READY_FOR_ACTIVATION", line)

    def test_activation_not_ready(self):
        ac = {"status": "not_ready", "reason": "alpaca_connected failed"}
        line = format_activation_line(ac)
        self.assertIn("NOT_READY", line)

    def test_activation_empty_returns_empty(self):
        self.assertEqual(format_activation_line({}), "")
        self.assertEqual(format_activation_line(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
