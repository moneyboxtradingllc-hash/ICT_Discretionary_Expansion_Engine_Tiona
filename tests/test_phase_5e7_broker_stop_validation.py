"""
Phase 5E.7 — Broker Stop Price Validation After Fill.

9 tests covering:
  adjustment for long stop above market, short stop below market,
  no-adjustment when stop is already valid, fill price fallback,
  invalid adjusted price handling, output field presence,
  disabled-mode no-regression, and integration with _submit().

No live Alpaca calls — all broker interactions mocked.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.protective_stop as ps_mod
from paper_execution.protective_stop import (
    _adjust_stop_price,
    _fetch_reference_price,
    build_stop_order,
    submit_protective_stop,
)


# ── Shared env fixtures ───────────────────────────────────────────────────────

_SAFE_ENV = {
    "PAPER_TRADING_ONLY": "true",
    "ALPACA_BASE_URL":    "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY":     "TESTKEY",
    "ALPACA_SECRET_KEY":  "TESTSECRET",
}

_STOP_ENV = {
    **_SAFE_ENV,
    "BROKER_STOP_ENABLED":      "true",
    "BROKER_STOP_PRICE_BUFFER": "0.05",
}


def _mock_position(current_price: float, avg_entry_price: float) -> dict:
    return {
        "symbol":          "QQQ",
        "qty":             "100",
        "side":            "long",
        "avg_entry_price": str(avg_entry_price),
        "current_price":   str(current_price),
        "unrealized_pl":   "0.0",
        "market_value":    str(current_price * 100),
    }


def _mock_submission(order_id: str = "STOP_ORDER_001") -> dict:
    return {
        "alpaca_order_id": order_id,
        "status":          "accepted",
        "symbol":          "QQQ",
        "side":            "sell",
        "qty":             "100",
        "stop_price":      None,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAdjustStopPrice(unittest.TestCase):
    """Unit tests for _adjust_stop_price() in isolation."""

    # ── 1. Long stop below market → no adjustment ─────────────────────────────
    def test_01_long_stop_below_market_no_adjustment(self):
        """
        Long position, stop=$476, current=$479 → stop < current → no adjustment.
        """
        result = _adjust_stop_price(
            stop_price    = 476.0,
            current_price = 479.0,
            fill_price    = 478.5,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 476.0)
        self.assertEqual(result["adjustment_reason"], "no_adjustment_needed")
        self.assertEqual(result["reference_price_used"], 479.0)
        self.assertEqual(result["reference_source"], "current_market_price")

    # ── 2. Long stop above market → adjust downward ───────────────────────────
    def test_02_long_stop_above_market_adjusts_downward(self):
        """
        Long position, stop=$703.47, current=$702.71 → stop > current →
        adjusted = 702.71 - 0.05 = 702.66.
        Reproduces the Day 2 full-stack test failure.
        """
        result = _adjust_stop_price(
            stop_price    = 703.47,
            current_price = 702.71,
            fill_price    = 702.64,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 702.66)
        self.assertEqual(result["adjustment_reason"], "long_stop_above_market")
        self.assertEqual(result["reference_price_used"], 702.71)
        self.assertEqual(result["reference_source"], "current_market_price")

    # ── 3. Short stop above market → no adjustment ────────────────────────────
    def test_03_short_stop_above_market_no_adjustment(self):
        """
        Short position, stop=$482, current=$479 → stop > current → no adjustment.
        """
        result = _adjust_stop_price(
            stop_price    = 482.0,
            current_price = 479.0,
            fill_price    = 479.5,
            position_side = "short",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 482.0)
        self.assertEqual(result["adjustment_reason"], "no_adjustment_needed")

    # ── 4. Short stop below market → adjust upward ────────────────────────────
    def test_04_short_stop_below_market_adjusts_upward(self):
        """
        Short position, stop=$476, current=$479 → stop < current →
        adjusted = 479 + 0.05 = 479.05.
        """
        result = _adjust_stop_price(
            stop_price    = 476.0,
            current_price = 479.0,
            fill_price    = 479.5,
            position_side = "short",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 479.05)
        self.assertEqual(result["adjustment_reason"], "short_stop_below_market")
        self.assertEqual(result["reference_price_used"], 479.0)

    # ── 5. Current price unavailable → falls back to fill price ───────────────
    def test_05_current_price_unavailable_uses_fill_price(self):
        """
        current_price=None, fill_price=702.64, stop=703.47 (long) →
        ref=fill_price → adjusted = 702.64 - 0.05 = 702.59.
        """
        result = _adjust_stop_price(
            stop_price    = 703.47,
            current_price = None,
            fill_price    = 702.64,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 702.59)
        self.assertEqual(result["reference_source"], "fill_price")
        self.assertEqual(result["reference_price_used"], 702.64)

    # ── 6. Both prices unavailable → pass-through, no adjustment ─────────────
    def test_06_both_prices_unavailable_passthrough(self):
        """
        current_price=None, fill_price=None → no reference available →
        stop returned unchanged, stop_adjusted=False.
        """
        result = _adjust_stop_price(
            stop_price    = 703.47,
            current_price = None,
            fill_price    = None,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 703.47)
        self.assertEqual(result["adjustment_reason"], "no_reference_price_available")
        self.assertIsNone(result["reference_price_used"])

    # ── 7. Adjusted stop would be <= 0 → invalid ─────────────────────────────
    def test_07_adjusted_stop_invalid_returns_false(self):
        """
        current_price=0.03, buffer=0.05 → adjusted = 0.03 - 0.05 = -0.02 → invalid.
        """
        result = _adjust_stop_price(
            stop_price    = 0.10,
            current_price = 0.03,
            fill_price    = 0.04,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertFalse(result["valid"])
        self.assertIn("invalid", result["reason"].lower())

    # ── 8. Long stop exactly equal to current → treated as above → adjust ────
    def test_08_long_stop_equal_to_market_adjusts(self):
        """
        stop == current → stop >= current is True → adjustment applies.
        adjusted = 479.00 - 0.05 = 478.95.
        """
        result = _adjust_stop_price(
            stop_price    = 479.0,
            current_price = 479.0,
            fill_price    = 479.0,
            position_side = "long",
            buffer        = 0.05,
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], 478.95)
        self.assertEqual(result["adjustment_reason"], "long_stop_above_market")


class TestSubmitProtectiveStopWithValidation(unittest.TestCase):
    """Integration tests for submit_protective_stop() with 5E.7 validation."""

    # ── 9. Long stop above market → adjusted stop submitted to broker ─────────
    def test_09_full_submit_long_stop_above_market(self):
        """
        Full submit: stop=$703.47, current=$702.71 → adjusted=$702.66.
        Verifies:
          - original_stop_price=703.47
          - adjusted_stop_price=702.66
          - stop_adjusted=True
          - adjustment_reason="long_stop_above_market"
          - stop_order_id returned
          - broker was called with 702.66, NOT 703.47
        """
        position_data = _mock_position(current_price=702.71, avg_entry_price=702.64)
        submission    = _mock_submission("STOP_ADJ_001")

        called_with_price = {}

        def capture_submission(symbol, qty, side, stop_price):
            called_with_price["stop_price"] = stop_price
            return submission

        with patch.dict(os.environ, _STOP_ENV):
            with patch.object(ps_mod, "is_paper_account_safe", return_value=(True, "ok")):
                with patch.object(ps_mod, "get_position", return_value=position_data):
                    with patch.object(ps_mod, "submit_protective_stop_order",
                                      side_effect=capture_submission):
                        with patch.object(ps_mod, "update_broker_stop"):
                            result = submit_protective_stop(
                                trade_id      = "PT_TEST_001",
                                symbol        = "QQQ",
                                position_side = "long",
                                qty           = 570,
                                stop_price    = 703.47,
                            )

        self.assertTrue(result["stop_submitted"])
        self.assertEqual(result["original_stop_price"],  703.47)
        self.assertEqual(result["adjusted_stop_price"],  702.66)
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjustment_reason"],    "long_stop_above_market")
        self.assertEqual(result["reference_price_used"], 702.71)
        self.assertEqual(result["reference_source"],     "current_market_price")
        self.assertEqual(result["stop_order_id"],        "STOP_ADJ_001")
        # Broker was called with the adjusted price
        self.assertEqual(called_with_price["stop_price"], 702.66)

    # ── 10. Long stop already below market → submits unchanged ───────────────
    def test_10_full_submit_long_stop_below_market_unchanged(self):
        """
        Stop=$476, current=$479 → no adjustment → broker receives $476.
        """
        position_data = _mock_position(current_price=479.0, avg_entry_price=478.5)
        submission    = _mock_submission("STOP_OK_002")

        called_with_price = {}

        def capture(symbol, qty, side, stop_price):
            called_with_price["stop_price"] = stop_price
            return submission

        with patch.dict(os.environ, _STOP_ENV):
            with patch.object(ps_mod, "is_paper_account_safe", return_value=(True, "ok")):
                with patch.object(ps_mod, "get_position", return_value=position_data):
                    with patch.object(ps_mod, "submit_protective_stop_order",
                                      side_effect=capture):
                        with patch.object(ps_mod, "update_broker_stop"):
                            result = submit_protective_stop(
                                trade_id      = "PT_TEST_002",
                                symbol        = "QQQ",
                                position_side = "long",
                                qty           = 100,
                                stop_price    = 476.0,
                            )

        self.assertTrue(result["stop_submitted"])
        self.assertFalse(result["stop_adjusted"])
        self.assertEqual(result["original_stop_price"], 476.0)
        self.assertEqual(result["adjusted_stop_price"], 476.0)
        self.assertEqual(called_with_price["stop_price"], 476.0)

    # ── 11. BROKER_STOP_ENABLED=false → disabled result, no network calls ─────
    def test_11_disabled_mode_no_calls(self):
        """
        BROKER_STOP_ENABLED=false → returns disabled result immediately.
        _fetch_reference_price and submit_protective_stop_order must NOT be called.
        """
        fetch_calls  = {"n": 0}
        submit_calls = {"n": 0}

        def count_fetch(*a, **kw):
            fetch_calls["n"] += 1
            return None, None, "unavailable"

        def count_submit(*a, **kw):
            submit_calls["n"] += 1
            return {}

        with patch.dict(os.environ, {**_SAFE_ENV, "BROKER_STOP_ENABLED": "false"}):
            with patch.object(ps_mod, "_fetch_reference_price", side_effect=count_fetch):
                with patch.object(ps_mod, "submit_protective_stop_order",
                                  side_effect=count_submit):
                    result = submit_protective_stop(
                        trade_id="PT_T", symbol="QQQ",
                        position_side="long", qty=100, stop_price=476.0,
                    )

        self.assertFalse(result["enabled"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(fetch_calls["n"],  0, "_fetch_reference_price must not be called")
        self.assertEqual(submit_calls["n"], 0, "submit_protective_stop_order must not be called")

    # ── 12. get_position fails → falls back, still submits ───────────────────
    def test_12_get_position_fails_passthrough(self):
        """
        _fetch_reference_price returns (None, None, 'unavailable') →
        _adjust_stop_price returns stop unchanged (no reference) →
        submission proceeds with original stop price.
        """
        submission = _mock_submission("STOP_FALLBACK_003")

        with patch.dict(os.environ, _STOP_ENV):
            with patch.object(ps_mod, "is_paper_account_safe", return_value=(True, "ok")):
                with patch.object(ps_mod, "_fetch_reference_price",
                                  return_value=(None, None, "unavailable")):
                    with patch.object(ps_mod, "submit_protective_stop_order",
                                      return_value=submission):
                        with patch.object(ps_mod, "update_broker_stop"):
                            result = submit_protective_stop(
                                trade_id="PT_T", symbol="QQQ",
                                position_side="long", qty=100, stop_price=476.0,
                            )

        self.assertTrue(result["stop_submitted"])
        self.assertFalse(result["stop_adjusted"])
        self.assertEqual(result["adjustment_reason"], "no_reference_price_available")
        self.assertIsNone(result["reference_price_used"])

    # ── 13. All Phase 5E.7 output fields present on successful submit ─────────
    def test_13_all_output_fields_present(self):
        """
        Successful submit must include all Phase 5E.7 output fields:
        original_stop_price, adjusted_stop_price, stop_adjusted,
        adjustment_reason, reference_price_used, reference_source.
        """
        position_data = _mock_position(current_price=479.0, avg_entry_price=478.5)

        with patch.dict(os.environ, _STOP_ENV):
            with patch.object(ps_mod, "is_paper_account_safe", return_value=(True, "ok")):
                with patch.object(ps_mod, "get_position", return_value=position_data):
                    with patch.object(ps_mod, "submit_protective_stop_order",
                                      return_value=_mock_submission()):
                        with patch.object(ps_mod, "update_broker_stop"):
                            result = submit_protective_stop(
                                trade_id="PT_T", symbol="QQQ",
                                position_side="long", qty=100, stop_price=476.0,
                            )

        for field in (
            "original_stop_price", "adjusted_stop_price", "stop_adjusted",
            "adjustment_reason", "reference_price_used", "reference_source",
        ):
            self.assertIn(field, result, f"missing field: {field}")

    # ── 14. BROKER_STOP_PRICE_BUFFER env var respected ────────────────────────
    def test_14_custom_buffer_env_var(self):
        """
        BROKER_STOP_PRICE_BUFFER=0.25 → adjusted = current - 0.25.
        """
        env = {**_STOP_ENV, "BROKER_STOP_PRICE_BUFFER": "0.25"}
        # stop=$703.47, current=$702.71 → adjusted = 702.71 - 0.25 = 702.46
        result = _adjust_stop_price(
            stop_price    = 703.47,
            current_price = 702.71,
            fill_price    = 702.64,
            position_side = "long",
            buffer        = 0.25,
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop"], round(702.71 - 0.25, 2))

    # ── 15. build_stop_order unchanged — still validates basic params ─────────
    def test_15_build_stop_order_unchanged(self):
        """
        build_stop_order() still validates qty/position_side/stop_price
        as before — Phase 5E.7 doesn't alter basic param validation.
        """
        self.assertFalse(build_stop_order("QQQ", "long",   0, 476.0)["valid"])
        self.assertFalse(build_stop_order("QQQ", "unknown", 10, 476.0)["valid"])
        self.assertFalse(build_stop_order("QQQ", "long",  10, 0.0)["valid"])
        ok = build_stop_order("QQQ", "long", 10, 476.0)
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["stop_side"], "sell")

    # ── 16. Short position full submit → adjusted upward ─────────────────────
    def test_16_short_stop_below_market_full_submit(self):
        """
        Short position: stop=$476, current=$479, buffer=0.05 →
        adjusted = 479.05. Broker called with 479.05.
        """
        position_data = {
            "symbol": "QQQ", "qty": "50", "side": "short",
            "avg_entry_price": "479.5", "current_price": "479.0",
            "unrealized_pl": "25.0", "market_value": "23950.0",
        }
        called = {}

        def capture(symbol, qty, side, stop_price):
            called["stop_price"] = stop_price
            return _mock_submission("STOP_SHORT_004")

        with patch.dict(os.environ, _STOP_ENV):
            with patch.object(ps_mod, "is_paper_account_safe", return_value=(True, "ok")):
                with patch.object(ps_mod, "get_position", return_value=position_data):
                    with patch.object(ps_mod, "submit_protective_stop_order",
                                      side_effect=capture):
                        with patch.object(ps_mod, "update_broker_stop"):
                            result = submit_protective_stop(
                                trade_id="PT_T", symbol="QQQ",
                                position_side="short", qty=50, stop_price=476.0,
                            )

        self.assertTrue(result["stop_submitted"])
        self.assertTrue(result["stop_adjusted"])
        self.assertEqual(result["adjusted_stop_price"], 479.05)
        self.assertEqual(called["stop_price"], 479.05)


if __name__ == "__main__":
    unittest.main()
