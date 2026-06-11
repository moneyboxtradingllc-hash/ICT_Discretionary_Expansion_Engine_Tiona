"""
Phase 5E.8 — Trade Management Layer: targeted tests.

All broker/journal calls are mocked. No live Alpaca connection needed.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_manager as tm_mod
from paper_execution.trade_manager import (
    manage_open_trade,
    replace_broker_stop,
    _calc_unrealized_r,
    _get_structure_trail_stop,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_trade_record(**overrides) -> dict:
    base = {
        "trade_id":            "T001",
        "symbol":              "QQQ",
        "side":                "buy",
        "order_status":        "filled",
        "risk_per_share":      1.0,
        "stop_reference":      99.0,
        "broker_stop_order_id": None,
        "breakeven_triggered": False,
        "take_profit_triggered": False,
    }
    base.update(overrides)
    return base


def _make_snapshot(
    has_position: bool = True,
    current_price: float = 100.50,
    avg_entry_price: float = 100.0,
    side: str = "long",
    qty: int = 10,
    trade_id: str = "T001",
    exit_submitted: bool = False,
    toolbox: dict | None = None,
) -> dict:
    pm = {
        "has_open_position":     has_position,
        "current_price":         current_price,
        "avg_entry_price":       avg_entry_price,
        "side":                  side,
        "qty":                   qty,
        "linked_trade_id":       trade_id if has_position else None,
        "exit_already_submitted": exit_submitted,
    }
    return {
        "position_monitor": pm,
        "toolbox": toolbox or {},
    }


def _make_toolbox(direction: str = "bullish", zone_low: float = 101.1, zone_high: float = 102.0) -> dict:
    return {
        "tool_candidates": [
            {
                "price_level": {
                    "direction": direction,
                    "zone_low":  zone_low,
                    "zone_high": zone_high,
                }
            }
        ]
    }


# ── Unit tests: config / R calc / structure trail ─────────────────────────────

class TestCalcUnrealizedR(unittest.TestCase):

    def test_long_positive_r(self):
        r = _calc_unrealized_r(101.0, 100.0, 1.0, "long")
        self.assertAlmostEqual(r, 1.0)

    def test_long_zero_r(self):
        r = _calc_unrealized_r(100.0, 100.0, 1.0, "long")
        self.assertAlmostEqual(r, 0.0)

    def test_short_positive_r(self):
        r = _calc_unrealized_r(99.0, 100.0, 1.0, "short")
        self.assertAlmostEqual(r, 1.0)

    def test_zero_risk_returns_none(self):
        self.assertIsNone(_calc_unrealized_r(101.0, 100.0, 0.0, "long"))

    def test_none_inputs_return_none(self):
        self.assertIsNone(_calc_unrealized_r(None, 100.0, 1.0, "long"))


class TestGetStructureTrailStop(unittest.TestCase):

    def test_no_candidates_returns_none(self):
        snap = {"toolbox": {"tool_candidates": []}}
        stop, reason = _get_structure_trail_stop(snap, "long", 99.0, 100.0)
        self.assertIsNone(stop)
        self.assertIn("no_tool_candidates", reason)

    def test_no_matching_direction_returns_none(self):
        snap = {"toolbox": _make_toolbox(direction="bearish")}
        stop, reason = _get_structure_trail_stop(snap, "long", 99.0, 100.0)
        self.assertIsNone(stop)
        self.assertIn("no_matching_direction", reason)

    def test_long_improvement_accepted(self):
        snap = {"toolbox": _make_toolbox(direction="bullish", zone_low=100.5)}
        # current_stop=100.0, entry=100.0 → 100.5 > 100.0 stop ✓, 100.5 >= 100.0 entry ✓
        stop, reason = _get_structure_trail_stop(snap, "long", 100.0, 100.0)
        self.assertAlmostEqual(stop, 100.5)
        self.assertEqual(reason, "structure_trail_improved")

    def test_long_no_improvement_rejected(self):
        snap = {"toolbox": _make_toolbox(direction="bullish", zone_low=98.0)}
        # zone_low=98.0 < current_stop=100.0 → not an improvement
        stop, reason = _get_structure_trail_stop(snap, "long", 100.0, 100.0)
        self.assertIsNone(stop)
        self.assertIn("no_improvement", reason)

    def test_long_below_entry_rejected(self):
        snap = {"toolbox": _make_toolbox(direction="bullish", zone_low=99.5)}
        # zone_low=99.5 > current_stop=99.0 (improvement) but < entry=100.0 → rejected
        stop, reason = _get_structure_trail_stop(snap, "long", 99.0, 100.0)
        self.assertIsNone(stop)
        self.assertIn("below_entry", reason)

    def test_short_improvement_accepted(self):
        snap = {"toolbox": _make_toolbox(direction="bearish", zone_high=99.5)}
        # current_stop=100.5, entry=100.0 → 99.5 < 100.5 (improves) and 99.5 <= 100.0 ✓
        stop, reason = _get_structure_trail_stop(snap, "short", 100.5, 100.0)
        self.assertAlmostEqual(stop, 99.5)
        self.assertEqual(reason, "structure_trail_improved")


# ── manage_open_trade: gate conditions ────────────────────────────────────────

class TestManageOpenTradeGates(unittest.TestCase):

    def test_disabled_returns_disabled(self):
        with patch.dict(os.environ, {"TRADE_MANAGEMENT_ENABLED": "false"}):
            result = manage_open_trade(_make_snapshot(), "QQQ")
        self.assertEqual(result["action"], "none")
        self.assertEqual(result["status"], "disabled")

    def test_no_open_position_returns_no_trade(self):
        snap = _make_snapshot(has_position=False)
        with patch.dict(os.environ, {"TRADE_MANAGEMENT_ENABLED": "true"}):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(None, None)):
                result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "no_trade")

    def test_exit_already_submitted_returns_no_action(self):
        snap = _make_snapshot(exit_submitted=True)
        with patch.dict(os.environ, {"TRADE_MANAGEMENT_ENABLED": "true"}):
            result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "none")
        self.assertIn("exit_already_submitted", result["reason"])

    def test_not_filled_with_open_position_manages_anyway(self):
        """Broker Position Supremacy (2026-06-11): a stale journal status
        must never stop management of real broker exposure. The old behavior
        (return no_action 'not_filled') left +6.77R unmanaged into a loss."""
        import paper_execution.management_policies as mp_mod
        snap   = _make_snapshot(current_price=101.0)
        record = _make_trade_record(order_status="submitted")
        with patch.dict(os.environ, {"TRADE_MANAGEMENT_ENABLED": "true"}):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "update_trade_management", return_value=True):
                    with patch.object(mp_mod, "update_trade_management", return_value=True):
                        result = manage_open_trade(snap, "QQQ")
        self.assertNotIn("not_filled", result.get("reason", ""))
        self.assertIn("INVARIANT VIOLATION", result.get("invariant_violation", ""))
        self.assertIn(result["action"], ("hold", "breakeven", "take_profit",
                                         "partial_take_profit", "trail_stop"))


# ── manage_open_trade: Rule 1 — Breakeven ─────────────────────────────────────

class TestBreakevenRule(unittest.TestCase):

    def _run(self, current_price, be_triggered=False, **env):
        snap   = _make_snapshot(current_price=current_price, avg_entry_price=100.0)
        record = _make_trade_record(
            order_status="filled",
            risk_per_share=1.0,
            stop_reference=99.0,
            breakeven_triggered=be_triggered,
        )
        env.setdefault("TRADE_MANAGEMENT_ENABLED", "true")
        env.setdefault("BREAKEVEN_ENABLED", "true")
        env.setdefault("BREAKEVEN_TRIGGER_R", "1.0")
        env.setdefault("TAKE_PROFIT_ENABLED", "true")
        env.setdefault("TAKE_PROFIT_R", "2.0")
        with patch.dict(os.environ, env):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "update_trade_management", return_value=True) as utm:
                    with patch.object(tm_mod, "replace_broker_stop") as rbs:
                        result = manage_open_trade(snap, "QQQ")
        return result, utm, rbs

    def test_breakeven_triggers_at_1R_long(self):
        result, utm, rbs = self._run(current_price=101.0)
        self.assertEqual(result["action"], "breakeven")
        self.assertEqual(result["new_stop"], 100.0)
        utm.assert_called_once()
        # No broker stop on record → replace not called
        rbs.assert_not_called()

    def test_breakeven_not_triggered_below_1R(self):
        result, utm, rbs = self._run(current_price=100.9)
        self.assertEqual(result["action"], "hold")
        utm.assert_not_called()

    def test_breakeven_already_triggered_skip(self):
        result, utm, rbs = self._run(current_price=101.0, be_triggered=True)
        # Should be hold (not BE again), no trail candidate in snapshot
        self.assertNotEqual(result["action"], "breakeven")
        utm.assert_not_called()

    def test_breakeven_calls_replace_broker_stop_when_stop_exists(self):
        snap   = _make_snapshot(current_price=101.0, avg_entry_price=100.0)
        record = _make_trade_record(
            order_status="filled",
            risk_per_share=1.0,
            stop_reference=99.0,
            broker_stop_order_id="STOP_OLD",
        )
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED": "true",
            "BREAKEVEN_ENABLED": "true",
            "BREAKEVEN_TRIGGER_R": "1.0",
            "TAKE_PROFIT_ENABLED": "true",
            "TAKE_PROFIT_R": "2.0",
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "update_trade_management", return_value=True):
                    with patch.object(tm_mod, "replace_broker_stop", return_value={"replaced": True}) as rbs:
                        result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "breakeven")
        rbs.assert_called_once_with("T001", "QQQ", "long", 10, 100.0)


# ── manage_open_trade: Rule 2 — Take Profit ───────────────────────────────────

class TestTakeProfitRule(unittest.TestCase):

    def _run(self, current_price, tp_triggered=False):
        snap   = _make_snapshot(current_price=current_price, avg_entry_price=100.0, qty=5)
        record = _make_trade_record(
            order_status="filled",
            risk_per_share=1.0,
            take_profit_triggered=tp_triggered,
        )
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED": "true",
            "BREAKEVEN_ENABLED": "true",
            "BREAKEVEN_TRIGGER_R": "1.0",
            "TAKE_PROFIT_ENABLED": "true",
            "TAKE_PROFIT_R": "2.0",
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "is_paper_account_safe", return_value=(True, "ok")):
                    with patch.object(tm_mod, "submit_paper_exit_order",
                                      return_value={"alpaca_order_id": "EXIT001"}) as spe:
                        with patch.object(tm_mod, "mark_exit_submitted") as mes:
                            with patch.object(tm_mod, "update_trade_management", return_value=True) as utm:
                                result = manage_open_trade(snap, "QQQ")
        return result, spe, mes, utm

    def test_take_profit_triggers_at_2R(self):
        result, spe, mes, utm = self._run(current_price=102.0)
        self.assertEqual(result["action"], "take_profit")
        self.assertAlmostEqual(result["unrealized_r"], 2.0)
        spe.assert_called_once_with("QQQ", 5, "sell")
        mes.assert_called_once()
        utm.assert_called_once()

    def test_take_profit_not_triggered_below_2R(self):
        result, spe, mes, utm = self._run(current_price=101.9)
        self.assertNotEqual(result["action"], "take_profit")
        spe.assert_not_called()

    def test_take_profit_already_triggered_skip(self):
        result, spe, mes, utm = self._run(current_price=103.0, tp_triggered=True)
        self.assertEqual(result["action"], "none")
        self.assertIn("take_profit_already_triggered", result["reason"])
        spe.assert_not_called()

    def test_take_profit_has_priority_over_breakeven(self):
        # At 2R, take profit fires even though breakeven hasn't triggered yet
        result, spe, mes, utm = self._run(current_price=102.0)
        self.assertEqual(result["action"], "take_profit")
        # BE action must NOT have fired
        self.assertNotEqual(result["action"], "breakeven")

    def test_take_profit_short_side(self):
        snap   = _make_snapshot(current_price=98.0, avg_entry_price=100.0, side="short", qty=5)
        record = _make_trade_record(side="sell", order_status="filled", risk_per_share=1.0)
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED": "true",
            "TAKE_PROFIT_ENABLED": "true",
            "TAKE_PROFIT_R": "2.0",
            "BREAKEVEN_ENABLED": "true",
            "BREAKEVEN_TRIGGER_R": "1.0",
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "is_paper_account_safe", return_value=(True, "ok")):
                    with patch.object(tm_mod, "submit_paper_exit_order",
                                      return_value={"alpaca_order_id": "EX002"}) as spe:
                        with patch.object(tm_mod, "mark_exit_submitted"):
                            with patch.object(tm_mod, "update_trade_management", return_value=True):
                                result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "take_profit")
        spe.assert_called_once_with("QQQ", 5, "buy")   # short → buy to close


# ── manage_open_trade: Rule 3 — Structure Trail ───────────────────────────────

class TestStructureTrailRule(unittest.TestCase):

    def _run_with_toolbox(self, toolbox, be_triggered=True, current_stop=100.0, trail_after_be="true"):
        snap   = _make_snapshot(current_price=101.5, avg_entry_price=100.0, toolbox=toolbox)
        record = _make_trade_record(
            order_status="filled",
            risk_per_share=1.0,
            stop_reference=current_stop,
            breakeven_triggered=be_triggered,
        )
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED":        "true",
            "BREAKEVEN_ENABLED":               "true",
            "BREAKEVEN_TRIGGER_R":             "1.0",
            "TAKE_PROFIT_ENABLED":             "true",
            "TAKE_PROFIT_R":                   "2.0",
            "STRUCTURE_TRAIL_ENABLED":         "true",
            "STRUCTURE_TRAIL_AFTER_BREAKEVEN": trail_after_be,
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "update_trade_management", return_value=True) as utm:
                    with patch.object(tm_mod, "replace_broker_stop",
                                      return_value={"replaced": False}) as rbs:
                        result = manage_open_trade(snap, "QQQ")
        return result, utm, rbs

    def test_structure_trail_updates_stop_after_be(self):
        toolbox = _make_toolbox(direction="bullish", zone_low=101.1)
        result, utm, _ = self._run_with_toolbox(toolbox, be_triggered=True, current_stop=100.0)
        self.assertEqual(result["action"], "trail_stop")
        self.assertAlmostEqual(result["new_stop"], 101.1)
        utm.assert_called_once()

    def test_structure_trail_no_improvement_holds(self):
        # zone_low=99.0 is below current_stop=100.0 → no improvement
        toolbox = _make_toolbox(direction="bullish", zone_low=99.0)
        result, utm, _ = self._run_with_toolbox(toolbox, be_triggered=True, current_stop=100.0)
        self.assertEqual(result["action"], "hold")
        utm.assert_not_called()

    def test_structure_trail_blocked_before_breakeven(self):
        # STRUCTURE_TRAIL_AFTER_BREAKEVEN=true, be_triggered=False → no trail
        toolbox = _make_toolbox(direction="bullish", zone_low=101.1)
        result, utm, _ = self._run_with_toolbox(
            toolbox, be_triggered=False, current_stop=99.0, trail_after_be="true"
        )
        # Rule 1 triggers first (price=101.5, r=1.5 >= 1.0, be_triggered=False)
        self.assertEqual(result["action"], "breakeven")
        utm.assert_called_once()

    def test_structure_trail_allowed_before_be_when_configured(self):
        # STRUCTURE_TRAIL_AFTER_BREAKEVEN=false → trail even without BE
        toolbox = _make_toolbox(direction="bullish", zone_low=100.5)
        # price=101.5, r=1.5, be_triggered=False, BE disabled
        snap   = _make_snapshot(current_price=101.5, avg_entry_price=100.0, toolbox=toolbox)
        record = _make_trade_record(
            order_status="filled",
            risk_per_share=1.0,
            stop_reference=100.0,
            breakeven_triggered=False,
        )
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED":        "true",
            "BREAKEVEN_ENABLED":               "false",
            "TAKE_PROFIT_ENABLED":             "true",
            "TAKE_PROFIT_R":                   "2.0",
            "STRUCTURE_TRAIL_ENABLED":         "true",
            "STRUCTURE_TRAIL_AFTER_BREAKEVEN": "false",
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                with patch.object(tm_mod, "update_trade_management", return_value=True):
                    with patch.object(tm_mod, "replace_broker_stop", return_value={"replaced": False}):
                        result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "trail_stop")

    def test_structure_trail_no_candidates_holds(self):
        toolbox = {"tool_candidates": []}
        result, utm, _ = self._run_with_toolbox(toolbox, be_triggered=True, current_stop=100.0)
        self.assertEqual(result["action"], "hold")

    def test_hold_below_all_thresholds(self):
        toolbox = _make_toolbox(direction="bullish", zone_low=99.0)
        snap   = _make_snapshot(current_price=100.5, avg_entry_price=100.0, toolbox=toolbox)
        record = _make_trade_record(order_status="filled", risk_per_share=1.0, stop_reference=99.0)
        with patch.dict(os.environ, {
            "TRADE_MANAGEMENT_ENABLED": "true",
            "BREAKEVEN_TRIGGER_R":      "1.0",
            "TAKE_PROFIT_R":            "2.0",
        }):
            with patch.object(tm_mod, "find_any_active_trade", return_value=(record, "f.json")):
                result = manage_open_trade(snap, "QQQ")
        self.assertEqual(result["action"], "hold")
        self.assertAlmostEqual(result["unrealized_r"], 0.5)


# ── replace_broker_stop ───────────────────────────────────────────────────────

class TestReplaceBrokerStop(unittest.TestCase):

    def test_replace_submits_new_then_cancels_old(self):
        old_record = _make_trade_record(broker_stop_order_id="OLD_001")
        with patch.object(tm_mod, "find_any_active_trade", return_value=(old_record, "f.json")):
            with patch.object(tm_mod, "submit_protective_stop",
                              return_value={"enabled": True, "stop_submitted": True, "stop_order_id": "NEW_002"}) as sps:
                with patch.object(tm_mod, "cancel_order",
                                  return_value={"canceled": True}) as co:
                    result = replace_broker_stop("T001", "QQQ", "long", 10, 100.0)

        self.assertTrue(result["replaced"])
        self.assertEqual(result["new_stop_order_id"], "NEW_002")
        self.assertTrue(result["old_stop_canceled"])
        # Submit called before cancel
        sps.assert_called_once_with("T001", "QQQ", "long", 10, 100.0)
        co.assert_called_once_with("OLD_001")

    def test_replace_no_old_stop(self):
        old_record = _make_trade_record(broker_stop_order_id=None)
        with patch.object(tm_mod, "find_any_active_trade", return_value=(old_record, "f.json")):
            with patch.object(tm_mod, "submit_protective_stop",
                              return_value={"enabled": True, "stop_submitted": True, "stop_order_id": "NEW_003"}):
                with patch.object(tm_mod, "cancel_order") as co:
                    result = replace_broker_stop("T001", "QQQ", "long", 10, 100.0)

        self.assertTrue(result["replaced"])
        co.assert_not_called()

    def test_replace_fails_when_new_stop_not_submitted(self):
        old_record = _make_trade_record(broker_stop_order_id="OLD_004")
        with patch.object(tm_mod, "find_any_active_trade", return_value=(old_record, "f.json")):
            with patch.object(tm_mod, "submit_protective_stop",
                              return_value={"enabled": True, "stop_submitted": False, "reason": "price_invalid"}):
                with patch.object(tm_mod, "cancel_order") as co:
                    result = replace_broker_stop("T001", "QQQ", "long", 10, 100.0)

        self.assertFalse(result["replaced"])
        self.assertIn("new_stop_not_submitted", result["reason"])
        co.assert_not_called()

    def test_replace_returns_safe_on_exception(self):
        with patch.object(tm_mod, "find_any_active_trade", side_effect=RuntimeError("boom")):
            result = replace_broker_stop("T001", "QQQ", "long", 10, 100.0)
        self.assertFalse(result["replaced"])
        self.assertIn("replace_broker_stop_error", result["reason"])


# ── Mocked simulation ─────────────────────────────────────────────────────────

def run_simulation():
    """
    Mocked price-path simulation:
      Long QQQ  entry=100  stop=99  risk_per_share=1

      step 1: price=100.50 → r=0.50 → HOLD
      step 2: price=101.00 → r=1.00 → BREAKEVEN  (stop → 100.00)
      step 3: price=101.50 → r=1.50 → TRAIL STOP (stop → 101.10, structure zone_low)
      step 4: price=102.00 → r=2.00 → TAKE PROFIT
    """
    ENTRY    = 100.0
    RISK     = 1.0
    SYMBOL   = "SIMTEST"
    TRADE_ID = "SIM001"

    # mutable state representing the journal trade record
    trade_state = {
        "trade_id":              TRADE_ID,
        "symbol":                SYMBOL,
        "side":                  "buy",
        "order_status":          "filled",
        "risk_per_share":        RISK,
        "stop_reference":        99.0,
        "broker_stop_order_id":  None,
        "breakeven_triggered":   False,
        "take_profit_triggered": False,
    }

    env_overrides = {
        "TRADE_MANAGEMENT_ENABLED":        "true",
        "BREAKEVEN_ENABLED":               "true",
        "BREAKEVEN_TRIGGER_R":             "1.0",
        "TAKE_PROFIT_ENABLED":             "true",
        "TAKE_PROFIT_R":                   "2.0",
        "STRUCTURE_TRAIL_ENABLED":         "true",
        "STRUCTURE_TRAIL_AFTER_BREAKEVEN": "true",
    }

    steps = [
        (100.50, {"tool_candidates": []}),          # step 1: hold
        (101.00, {"tool_candidates": []}),          # step 2: breakeven
        (101.50, _make_toolbox("bullish", 101.10)), # step 3: trail
        (102.00, {"tool_candidates": []}),          # step 4: take profit
    ]

    expected_actions = ["hold", "breakeven", "trail_stop", "take_profit"]

    print("\n" + "=" * 60)
    print("Phase 5E.8 — Mocked Trade Management Simulation")
    print("=" * 60)
    print(f"  Entry={ENTRY}  Stop=99.0  Risk={RISK}  Symbol={SYMBOL}")
    print("-" * 60)

    all_passed = True

    for i, ((price, toolbox), expected) in enumerate(zip(steps, expected_actions), 1):
        snap = _make_snapshot(
            current_price=price,
            avg_entry_price=ENTRY,
            qty=10,
            trade_id=TRADE_ID,
            toolbox=toolbox,
        )

        # capture update_trade_management calls to evolve trade_state
        def capture_utm(tid, fields, sym, _state=trade_state):
            _state.update(fields)
            return True

        with patch.dict(os.environ, env_overrides):
            with patch.object(tm_mod, "find_any_active_trade",
                              return_value=(dict(trade_state), "sim.json")):
                with patch.object(tm_mod, "update_trade_management",
                                  side_effect=capture_utm):
                    with patch.object(tm_mod, "is_paper_account_safe",
                                      return_value=(True, "ok")):
                        with patch.object(tm_mod, "submit_paper_exit_order",
                                          return_value={"alpaca_order_id": "SIM_EXIT"}):
                            with patch.object(tm_mod, "mark_exit_submitted"):
                                result = manage_open_trade(snap, SYMBOL)

        action = result.get("action")
        r_val  = result.get("unrealized_r", _calc_unrealized_r(price, ENTRY, RISK, "long"))
        match  = "PASS" if action == expected else "FAIL"
        if action != expected:
            all_passed = False
        print(f"  Step {i}: price={price:.2f}  r={r_val:.2f}  action={action:<12}  [{match}]  ({result.get('details', '')})")

    print("-" * 60)
    print("  Simulation result:", "ALL PASSED" if all_passed else "FAILURES DETECTED")
    print("=" * 60 + "\n")
    return all_passed


if __name__ == "__main__":
    passed = run_simulation()
    # Also run unit tests
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)
    sys.exit(0 if (passed and test_result.wasSuccessful()) else 1)
