"""
Phase 2A — Paper Execution Layer unit tests.

Tests: trade_journal, order_builder, position_guard, execution_engine.
No actual Alpaca API calls — all broker interactions are mocked.
"""
import os
import sys
import json
import math
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal  as tj_mod
import paper_execution.paper_broker   as broker_mod
import paper_execution.position_guard as guard_mod
import paper_execution.execution_engine as eng_mod

from paper_execution.trade_journal  import (
    append_trade, load_today_trades, count_submitted_today,
    total_risk_today, intent_already_journaled, make_record,
)
from paper_execution.order_builder  import build_order, meets_score_threshold, quality_rank
from paper_execution.paper_broker   import is_paper_account_safe
from paper_execution.execution_engine import attempt_paper_execution
from ai_layer.ai_snapshot_formatter  import format_paper_execution_line


# ── Snapshot fixtures ─────────────────────────────────────────────────────────

def _full_snap(
    intent_type="long",
    direction="bullish",
    gated_score=75,
    gated_quality="strong_watch",
    exec_ready=True,
    decision="trade_authorized_false",
    allow_execution=True,
    would_authorize=True,
):
    """Full snapshot with all layers populated for a long/short intent."""
    midpoint = 479.0
    return {
        "playbook": {"selected_playbook": "liq_sweep", "direction": direction},
        "toolbox": {
            "preferred_tool": f"{direction}_ifvg",
            "tool_candidates": [
                {
                    "tool": f"{direction}_ifvg",
                    "score": 80,
                    "raw_status": "actionable",
                    "effective_status": "actionable",
                    "price_level": {
                        "level_type": "ifvg_zone",
                        "direction": direction,
                        "zone_low": 478.0,
                        "zone_high": 480.0,
                        "midpoint": midpoint,
                        "current_price": 479.5,
                        "price_relation": "inside_zone",
                        "invalidation_level": 476.0 if direction == "bullish" else 482.0,
                    },
                    "trigger_prep": {
                        "raw_trigger_status": "confirmed",
                        "effective_trigger_status": "confirmed",
                        "execution_ready": exec_ready,
                    },
                }
            ],
        },
        "trade_intent": {
            "intent_created": True,
            "intent_type": intent_type,
            "direction": direction,
            "preferred_tool": f"{direction}_ifvg",
            "entry_zone": {
                "zone_low": 478.0,
                "zone_high": 480.0,
                "midpoint": midpoint,
                "current_price": 479.5,
                "price_relation": "inside_zone",
            },
            "trigger_status": "confirmed",
        },
        "intent_score": {
            "scored": True,
            "gated_score": gated_score,
            "gated_quality": gated_quality,
            "raw_score": gated_score,
            "gated_grade": "B",
        },
        "execution_gate": {
            "allow_execution": allow_execution,
            "would_authorize_if_enabled": would_authorize,
            "gate_status": "authorized" if allow_execution else "locked",
        },
        "decision_authority": {
            "decision": decision,
            "direction": direction,
            "trade_authorized": False,
        },
        "setup_lifecycle": {
            "active": True,
            "invalidated": False,
            "setup_id": "QQQ_20260605_liq_sweep_bullish_bullish_ifvg_47800_48000",
        },
        "risk": {"trade_allowed": True, "risk_tier": "normal"},
        "intent_archive": {"active_intent_id": "QQQ_20260605T092315"},
        "ai_context": {"summary": ""},
    }


# ── trade_journal tests ───────────────────────────────────────────────────────

class TestTradeJournal(unittest.TestCase):

    def _run_with_tmp(self, fn):
        """Run fn with trade journal pointing to a temp file."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                return fn(tmp)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _make_rec(self, status="submitted", intent_id="I1", risk=250.0, alpaca_id=None):
        return make_record(
            trade_id="T1", symbol="QQQ", intent_id=intent_id,
            intent_type="long", side="buy", qty=2,
            entry_reference=479.0, stop_reference=476.0,
            risk_per_share=3.0, risk_dollars=risk,
            order_status=status, alpaca_order_id=alpaca_id,
            reason="test",
        )

    def test_01_append_and_load(self):
        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                append_trade(self._make_rec(), "QQQ")
                trades = load_today_trades("QQQ")
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["order_status"], "submitted")
        self._run_with_tmp(fn)

    def test_02_count_submitted_only(self):
        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                append_trade(self._make_rec(status="submitted", alpaca_id="ALPA_001"), "QQQ")
                append_trade(self._make_rec(status="rejected",  alpaca_id=None),       "QQQ")
                append_trade(self._make_rec(status="skipped",   alpaca_id=None),       "QQQ")
                count = count_submitted_today("QQQ")
            self.assertEqual(count, 1)
        self._run_with_tmp(fn)

    def test_02b_count_includes_filled_and_closed(self):
        """Filled and closed trades still count toward the daily limit."""
        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                append_trade(self._make_rec(status="filled", alpaca_id="ALPA_001"), "QQQ")
                append_trade(self._make_rec(status="closed", alpaca_id="ALPA_002"), "QQQ")
                count = count_submitted_today("QQQ")
            self.assertEqual(count, 2)
        self._run_with_tmp(fn)

    def test_03_total_risk_submitted_only(self):
        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                append_trade(self._make_rec(status="submitted", risk=300.0, alpaca_id="ALPA_001"), "QQQ")
                append_trade(self._make_rec(status="submitted", risk=200.0, alpaca_id="ALPA_002"), "QQQ")
                append_trade(self._make_rec(status="rejected",  risk=500.0, alpaca_id=None),       "QQQ")
                total = total_risk_today("QQQ")
            self.assertAlmostEqual(total, 500.0, places=2)
        self._run_with_tmp(fn)

    def test_04_intent_duplicate_detection(self):
        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                append_trade(self._make_rec(status="submitted", intent_id="A"), "QQQ")
                dup = intent_already_journaled("A", "QQQ")
                new = intent_already_journaled("B", "QQQ")
            self.assertTrue(dup)
            self.assertFalse(new)
        self._run_with_tmp(fn)


# ── order_builder tests ───────────────────────────────────────────────────────

class TestOrderBuilder(unittest.TestCase):

    def test_05_valid_long_order(self):
        snap = _full_snap(intent_type="long", direction="bullish")
        with patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "500"}):
            result = build_order(snap, "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["side"], "buy")
        # midpoint=479, invalidation=476 → risk_per_share=3.0 → qty=floor(500/3)=166
        self.assertAlmostEqual(result["risk_per_share"], 3.0, places=4)
        self.assertEqual(result["qty"], math.floor(500 / 3.0))
        self.assertGreater(result["qty"], 0)
        self.assertIsNotNone(result["order_request"])

    def test_06_valid_short_order(self):
        snap = _full_snap(intent_type="short", direction="bearish")
        with patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "500"}):
            result = build_order(snap, "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["side"], "sell")
        # midpoint=479, invalidation=482 → risk_per_share=3.0
        self.assertAlmostEqual(result["risk_per_share"], 3.0, places=4)

    def test_07_rejects_non_directional_intent(self):
        snap = _full_snap()
        snap["trade_intent"]["intent_type"] = "none"
        result = build_order(snap, "QQQ")
        self.assertFalse(result["valid"])
        self.assertIn("none", result["reject_reason"])

    def test_08_rejects_zero_risk_per_share(self):
        snap = _full_snap()
        snap["toolbox"]["tool_candidates"][0]["price_level"]["invalidation_level"] = 479.0  # == midpoint
        result = build_order(snap, "QQQ")
        self.assertFalse(result["valid"])

    def test_09_rejects_when_qty_is_zero(self):
        snap = _full_snap()
        # risk_per_share = 479-476=3, budget=1 → qty=0
        with patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "1"}):
            result = build_order(snap, "QQQ")
        self.assertFalse(result["valid"])
        self.assertIn("qty=0", result["reject_reason"])

    def test_10_quality_rank_ordering(self):
        self.assertLess(quality_rank("poor"),         quality_rank("weak_watch"))
        self.assertLess(quality_rank("weak_watch"),   quality_rank("moderate_watch"))
        self.assertLess(quality_rank("moderate_watch"), quality_rank("strong_watch"))
        self.assertLess(quality_rank("strong_watch"), quality_rank("elite_intent"))

    def test_11_meets_score_threshold(self):
        snap = _full_snap(gated_score=75, gated_quality="strong_watch")
        env  = {"MIN_INTENT_GATED_SCORE": "70", "MIN_INTENT_QUALITY": "strong_watch"}
        with patch.dict(os.environ, env):
            ok, _ = meets_score_threshold(snap)
        self.assertTrue(ok)

    def test_12_fails_score_threshold(self):
        snap = _full_snap(gated_score=65, gated_quality="moderate_watch")
        env  = {"MIN_INTENT_GATED_SCORE": "70", "MIN_INTENT_QUALITY": "strong_watch"}
        with patch.dict(os.environ, env):
            ok, reason = meets_score_threshold(snap)
        self.assertFalse(ok)
        self.assertIn("65", reason)


# ── paper_broker safety tests ─────────────────────────────────────────────────

class TestPaperBrokerSafety(unittest.TestCase):

    def test_13_safe_with_paper_url(self):
        env = {
            "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
            "PAPER_TRADING_ONLY": "true",
        }
        with patch.dict(os.environ, env):
            safe, reason = is_paper_account_safe()
        self.assertTrue(safe)

    def test_14_unsafe_with_live_url(self):
        env = {
            "ALPACA_BASE_URL":    "https://api.alpaca.markets",
            "PAPER_TRADING_ONLY": "true",
        }
        with patch.dict(os.environ, env):
            safe, reason = is_paper_account_safe()
        self.assertFalse(safe)
        self.assertIn("Unsafe", reason)

    def test_15_unsafe_when_paper_trading_only_false(self):
        env = {
            "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
            "PAPER_TRADING_ONLY": "false",
        }
        with patch.dict(os.environ, env):
            safe, reason = is_paper_account_safe()
        self.assertFalse(safe)

    def test_16_unsafe_with_empty_url(self):
        with patch.dict(os.environ, {"ALPACA_BASE_URL": "", "PAPER_TRADING_ONLY": "true"}):
            safe, reason = is_paper_account_safe()
        self.assertFalse(safe)


# ── execution_engine tests ────────────────────────────────────────────────────

class TestExecutionEngine(unittest.TestCase):

    def test_17_disabled_when_execution_enabled_false(self):
        snap = _full_snap()
        env  = {
            "EXECUTION_ENABLED":  "false",
            "PAPER_TRADING_ONLY": "true",
            "ALLOW_PAPER_ORDERS": "false",
        }
        with patch.dict(os.environ, env):
            result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "disabled")
        self.assertIn("EXECUTION_ENABLED=false", result["reason"])

    def test_18_disabled_when_allow_paper_orders_false(self):
        snap = _full_snap()
        env  = {
            "EXECUTION_ENABLED":  "true",
            "PAPER_TRADING_ONLY": "true",
            "ALLOW_PAPER_ORDERS": "false",
        }
        with patch.dict(os.environ, env):
            result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "disabled")
        self.assertIn("ALLOW_PAPER_ORDERS", result["reason"])

    def test_19_skipped_when_gate_locked(self):
        snap = _full_snap(allow_execution=False, would_authorize=False)
        env  = {
            "EXECUTION_ENABLED":  "true",
            "PAPER_TRADING_ONLY": "true",
            "ALLOW_PAPER_ORDERS": "true",
            "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
        }
        with patch.dict(os.environ, env):
            result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("gate", result["reason"])

    def test_20_skipped_when_score_below_threshold(self):
        snap = _full_snap(gated_score=60, gated_quality="moderate_watch")
        env  = {
            "EXECUTION_ENABLED":     "true",
            "PAPER_TRADING_ONLY":    "true",
            "ALLOW_PAPER_ORDERS":    "true",
            "ALPACA_BASE_URL":       "https://paper-api.alpaca.markets",
            "MIN_INTENT_GATED_SCORE": "70",
            "MIN_INTENT_QUALITY":    "strong_watch",
        }
        with patch.dict(os.environ, env):
            result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("score", result["reason"])

    def test_21_skipped_when_position_guard_blocks(self):
        """Position guard blocks when ONE_POSITION_AT_A_TIME=true and open position exists."""
        snap = _full_snap()
        env  = {
            "EXECUTION_ENABLED":       "true",
            "PAPER_TRADING_ONLY":      "true",
            "ALLOW_PAPER_ORDERS":      "true",
            "ALPACA_BASE_URL":         "https://paper-api.alpaca.markets",
            "MIN_INTENT_GATED_SCORE":  "70",
            "MIN_INTENT_QUALITY":      "strong_watch",
            "RISK_PER_TRADE_DOLLARS":  "500",
            "ONE_POSITION_AT_A_TIME":  "true",
            "MAX_TRADES_PER_DAY":      "2",
            "DAILY_LOSS_LIMIT_DOLLARS": "1000",
        }
        with patch.dict(os.environ, env):
            # Mock open positions to simulate an existing position
            with patch.object(guard_mod, "get_open_positions", return_value=[{"symbol": "QQQ", "qty": "10", "side": "long"}]):
                with patch.object(tj_mod, "_journal_filepath", return_value=tempfile.mktemp(suffix=".json")):
                    result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("position", result["reason"])

    def test_22_submitted_when_all_conditions_met(self):
        """Full happy path — all conditions met, order submitted successfully."""
        snap = _full_snap()
        tmp  = tempfile.mktemp(suffix=".json")
        env  = {
            "EXECUTION_ENABLED":       "true",
            "PAPER_TRADING_ONLY":      "true",
            "ALLOW_PAPER_ORDERS":      "true",
            "ALPACA_BASE_URL":         "https://paper-api.alpaca.markets",
            "MIN_INTENT_GATED_SCORE":  "70",
            "MIN_INTENT_QUALITY":      "strong_watch",
            "RISK_PER_TRADE_DOLLARS":  "500",
            "ONE_POSITION_AT_A_TIME":  "true",
            "MAX_TRADES_PER_DAY":      "5",
            "DAILY_LOSS_LIMIT_DOLLARS": "5000",
        }
        mock_submission = {
            "alpaca_order_id": "alpaca-uuid-123",
            "status": "accepted",
            "symbol": "QQQ",
            "side": "buy",
            "qty": "166",
            "limit_price": "479.0",
            "submitted_at": "2026-06-05T09:23:15Z",
        }
        with patch.dict(os.environ, env):
            with patch.object(guard_mod, "get_open_positions", return_value=[]):
            # No open positions
                with patch.object(eng_mod, "submit_paper_order", return_value=mock_submission):
                    with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                        result = attempt_paper_execution(snap, "QQQ")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["alpaca_order_id"], "alpaca-uuid-123")
        self.assertIn("buy", result["order_summary"])
        self.assertIn("QQQ", result["order_summary"])
        # Verify journal was written
        if os.path.exists(tmp):
            with open(tmp, encoding="utf-8") as f:
                journal = json.load(f)
            self.assertEqual(len(journal["trades"]), 1)
            self.assertEqual(journal["trades"][0]["order_status"], "submitted")
            os.unlink(tmp)

    def test_23_default_env_cannot_place_orders(self):
        """With default .env values (all false), no orders can be placed."""
        snap = _full_snap()
        env  = {
            "EXECUTION_ENABLED":  "false",
            "PAPER_TRADING_ONLY": "true",
            "ALLOW_PAPER_ORDERS": "false",
        }
        with patch.dict(os.environ, env):
            result = attempt_paper_execution(snap, "QQQ")
        self.assertNotEqual(result["status"], "submitted")
        self.assertIsNone(result["alpaca_order_id"])


# ── format_paper_execution_line tests ────────────────────────────────────────

class TestFormatPaperExecutionLine(unittest.TestCase):

    def test_24_disabled_line(self):
        line = format_paper_execution_line({"status": "disabled", "reason": "EXECUTION_ENABLED=false"})
        self.assertIn("DISABLED", line)
        self.assertIn("EXECUTION_ENABLED", line)

    def test_25_submitted_line(self):
        line = format_paper_execution_line({
            "status": "submitted",
            "order_summary": "buy 166 QQQ limit 479.0",
        })
        self.assertIn("SUBMITTED", line)
        self.assertIn("buy 166 QQQ", line)

    def test_26_skipped_line(self):
        line = format_paper_execution_line({"status": "skipped", "reason": "execution gate locked"})
        self.assertIn("SKIPPED", line)

    def test_27_empty_on_none(self):
        self.assertEqual(format_paper_execution_line({}), "")
        self.assertEqual(format_paper_execution_line(None), "")


if __name__ == "__main__":
    unittest.main()
