"""
Phase 2D — Activation Plan + Runner unit tests.

No Alpaca API calls — broker interactions mocked.
No orders placed.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_activation.activation_plan   as plan_mod
import paper_activation.activation_runner as runner_mod

from paper_activation.activation_plan   import build_activation_plan
from paper_activation.activation_runner import run_activation
from ai_layer.ai_snapshot_formatter     import format_paper_activation_line


# ── Helpers ───────────────────────────────────────────────────────────────────

def _armed_env():
    """Env that satisfies all 14 requirements when market_hours=True."""
    return {
        "PAPER_ACTIVATION_MODE":             "true",
        "PAPER_ACTIVATION_MAX_TRADES":       "1",
        "PAPER_ACTIVATION_RISK_DOLLARS":     "100",
        "PAPER_ACTIVATION_REQUIRE_MARKET_HOURS": "false",  # bypass time check
        "PAPER_ACTIVATION_SYMBOL":           "QQQ",
        "EXECUTION_ENABLED":                 "true",
        "ALLOW_PAPER_ORDERS":                "true",
        "PAPER_TRADING_ONLY":                "true",
        "PAPER_EXIT_ON_STOP":                "true",
        "MAX_TRADES_PER_DAY":                "1",
        "RISK_PER_TRADE_DOLLARS":            "100",
        "DAILY_LOSS_LIMIT_DOLLARS":          "100",
        "ONE_POSITION_AT_A_TIME":            "true",
        "ALPACA_BASE_URL":                   "https://paper-api.alpaca.markets",
        "SCAN_START_TIME":                   "08:30",
        "SCAN_END_TIME":                     "15:00",
    }


def _no_position_snapshot():
    return {
        "position_monitor": {"has_open_position": False, "enabled": True},
        "execution_gate":   {"gate_status": "locked"},
        "intent_score":     {"scored": False},
    }


def _open_position_snapshot():
    snap = _no_position_snapshot()
    snap["position_monitor"]["has_open_position"] = True
    return snap


# ═══════════════════════════════════════════════════════════════════════════════
# Activation Plan
# ═══════════════════════════════════════════════════════════════════════════════

class TestActivationPlan(unittest.TestCase):

    # ── activation mode off ───────────────────────────────────────────────────

    @patch.dict(os.environ, {"PAPER_ACTIVATION_MODE": "false"})
    def test_disabled_when_mode_off(self):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertFalse(plan["activation_mode"])
        self.assertFalse(plan["armed"])
        self.assertEqual(plan["reason"], "PAPER_ACTIVATION_MODE=false")
        self.assertEqual(plan["requirements"], {})

    # ── all requirements pass ─────────────────────────────────────────────────

    @patch.dict(os.environ, _armed_env())
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_all_pass_armed(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertTrue(plan["activation_mode"])
        self.assertTrue(plan["requirements_passed"])
        self.assertTrue(plan["armed"])
        self.assertEqual(plan["blocking_issues"], [])

    # ── EXECUTION_ENABLED failure ─────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "EXECUTION_ENABLED": "false"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_execution_disabled(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertFalse(plan["requirements_passed"])
        self.assertIn("execution_enabled", plan["blocking_issues"])
        self.assertIn("activation_controller_ok", plan["blocking_issues"])

    # ── PAPER_EXIT_ON_STOP failure ────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "PAPER_EXIT_ON_STOP": "false"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_exit_on_stop_disabled(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("exit_on_stop_enabled", plan["blocking_issues"])

    # ── Risk too high ─────────────────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "RISK_PER_TRADE_DOLLARS": "500"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_risk_too_high(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("risk_dollars_safe", plan["blocking_issues"])

    # ── Daily loss limit too high ─────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "DAILY_LOSS_LIMIT_DOLLARS": "1000"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_daily_loss_too_high(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("daily_loss_safe", plan["blocking_issues"])

    # ── Open position blocks ──────────────────────────────────────────────────

    @patch.dict(os.environ, _armed_env())
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_open_position(self, *_):
        plan = build_activation_plan(_open_position_snapshot(), "QQQ")
        self.assertIn("no_open_position", plan["blocking_issues"])

    # ── Market hours enforcement ──────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(),
                              "PAPER_ACTIVATION_REQUIRE_MARKET_HOURS": "true",
                              "SCAN_START_TIME": "08:30",
                              "SCAN_END_TIME": "09:00"})  # narrow window — we're outside
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    @patch.object(plan_mod, "is_within_scan_window", return_value=False)
    def test_fails_when_outside_market_hours(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("within_market_hours", plan["blocking_issues"])

    # ── Trades below max ──────────────────────────────────────────────────────

    @patch.dict(os.environ, _armed_env())
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=1)  # 1 >= max(1)
    def test_fails_when_max_trades_reached(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("trades_below_max", plan["blocking_issues"])

    # ── Wrong symbol ──────────────────────────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "PAPER_ACTIVATION_SYMBOL": "SPY"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_wrong_symbol(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("correct_symbol", plan["blocking_issues"])

    # ── Max trades system limit too high ─────────────────────────────────────

    @patch.dict(os.environ, {**_armed_env(), "MAX_TRADES_PER_DAY": "2"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_fails_when_system_max_trades_exceeds_activation(self, *_):
        plan = build_activation_plan(_no_position_snapshot(), "QQQ")
        self.assertIn("max_trades_safe", plan["blocking_issues"])

    # ── Exception safety ─────────────────────────────────────────────────────

    @patch.dict(os.environ, {"PAPER_ACTIVATION_MODE": "true",
                              "PAPER_TRADING_ONLY": "true",
                              "ALPACA_BASE_URL": "https://paper-api.alpaca.markets"})
    @patch.object(plan_mod, "is_paper_account_safe", return_value=(True, "ok"))
    @patch.object(plan_mod, "count_submitted_today", return_value=0)
    def test_exception_returns_safe_plan(self, *_):
        # None.get() at snapshot["position_monitor"] raises AttributeError
        # build_activation_plan outer try/except catches it → safe blocked plan
        plan = build_activation_plan(None, "QQQ")
        self.assertFalse(plan["armed"])
        self.assertFalse(plan["requirements_passed"])
        self.assertTrue(len(plan["blocking_issues"]) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Activation Runner
# ═══════════════════════════════════════════════════════════════════════════════

def _make_plan(passed=True, blocking=None, activation_mode=True, reason="all requirements passed"):
    return {
        "activation_mode":     activation_mode,
        "requirements_passed": passed,
        "blocking_issues":     blocking or [],
        "warnings":            [],
        "reason":              reason,
        "symbol":              "QQQ",
        "max_trades":          1,
        "risk_dollars":        100.0,
    }


class TestActivationRunner(unittest.TestCase):

    def test_disabled_when_mode_off(self):
        result = run_activation(_make_plan(activation_mode=False), "QQQ")
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["allow_order_attempts"])
        self.assertFalse(result["paper_trading_armed"])

    def test_armed_when_all_pass(self):
        result = run_activation(_make_plan(passed=True), "QQQ")
        self.assertEqual(result["status"], "armed")
        self.assertTrue(result["allow_order_attempts"])
        self.assertTrue(result["paper_trading_armed"])

    def test_blocked_when_outside_market_hours(self):
        result = run_activation(
            _make_plan(passed=False, blocking=["within_market_hours"], reason="outside market hours"),
            "QQQ",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["allow_order_attempts"])
        self.assertIn("market hours", result["reason"])

    def test_blocked_when_open_position(self):
        result = run_activation(
            _make_plan(passed=False, blocking=["no_open_position"]),
            "QQQ",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["allow_order_attempts"])

    def test_completed_for_day_when_max_trades_reached(self):
        result = run_activation(
            _make_plan(passed=False, blocking=["trades_below_max"],
                       reason="max trades for day reached (1)"),
            "QQQ",
        )
        self.assertEqual(result["status"], "completed_for_day")
        self.assertFalse(result["allow_order_attempts"])

    def test_not_ready_when_execution_disabled(self):
        result = run_activation(
            _make_plan(passed=False, blocking=["execution_enabled"],
                       reason="EXECUTION_ENABLED=false"),
            "QQQ",
        )
        self.assertEqual(result["status"], "not_ready")
        self.assertFalse(result["allow_order_attempts"])

    def test_not_ready_for_multiple_infra_failures(self):
        result = run_activation(
            _make_plan(passed=False,
                       blocking=["execution_enabled", "paper_orders_allowed", "exit_on_stop_enabled"]),
            "QQQ",
        )
        self.assertEqual(result["status"], "not_ready")

    def test_blocked_takes_priority_when_mixed_with_infra(self):
        """Market hours + infra failure → blocked (time will resolve first)."""
        result = run_activation(
            _make_plan(passed=False,
                       blocking=["execution_enabled", "within_market_hours"]),
            "QQQ",
        )
        self.assertEqual(result["status"], "blocked")

    def test_exception_returns_not_ready(self):
        result = run_activation(None, "QQQ")
        self.assertEqual(result["status"], "not_ready")
        self.assertFalse(result["allow_order_attempts"])


# ═══════════════════════════════════════════════════════════════════════════════
# Formatter
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaperActivationFormatter(unittest.TestCase):

    def test_disabled_line(self):
        pa = {"status": "disabled", "reason": "activation mode disabled"}
        line = format_paper_activation_line(pa)
        self.assertIn("DISABLED", line)
        self.assertIn("PAPER_ACTIVATION_MODE=false", line)

    def test_armed_line(self):
        pa = {"status": "armed", "reason": "all requirements passed"}
        line = format_paper_activation_line(pa)
        self.assertIn("ARMED", line)

    def test_blocked_line(self):
        pa = {"status": "blocked", "reason": "outside market hours"}
        line = format_paper_activation_line(pa)
        self.assertIn("BLOCKED", line)
        self.assertIn("outside market hours", line)

    def test_not_ready_line(self):
        pa = {"status": "not_ready", "reason": "EXECUTION_ENABLED=false"}
        line = format_paper_activation_line(pa)
        self.assertIn("NOT_READY", line)

    def test_completed_for_day_line(self):
        pa = {"status": "completed_for_day", "reason": "max trades for day reached (1)"}
        line = format_paper_activation_line(pa)
        self.assertIn("COMPLETED_FOR_DAY", line)

    def test_empty_returns_empty(self):
        self.assertEqual(format_paper_activation_line({}), "")
        self.assertEqual(format_paper_activation_line(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
