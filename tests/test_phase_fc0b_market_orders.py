"""
Phase FC-0B — Market-Order Execution Doctrine tests.

Doctrine: decision time = execution time. Market order at the price that
exists when authority is granted. ENTRY_ORDER_TYPE=limit is rollback only.

June 11 lesson: a limit at zone midpoint only fills when price moves AGAINST
the thesis — the order filled 2 minutes after authority, in a context the
bot had already declared dead.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.order_builder as ob_mod
from paper_execution.order_builder import build_order, entry_order_type
from paper_execution.trade_journal import make_record
import paper_execution.trade_reconciliation as recon_mod


def _snapshot(current_price=701.42, price_relation="inside_zone",
              midpoint=701.14, zone_low=700.79, zone_high=701.49,
              intent_type="long"):
    """Snapshot shaped like June 11 10:29:53 (PT_QQQ_20260611T102953)."""
    return {
        "risk": {"risk_multiplier": 0.5, "trade_allowed": True},
        "regime_permissions": {"risk_multiplier_cap": 0.5, "enabled": True},
        "trade_intent": {
            "intent_type": intent_type,
            "direction":   "bullish" if intent_type == "long" else "bearish",
            "entry_zone": {
                "zone_low":       zone_low,
                "zone_high":      zone_high,
                "midpoint":       midpoint,
                "current_price":  current_price,
                "price_relation": price_relation,
            },
        },
        "toolbox": {
            "preferred_tool": "bullish_ifvg",
            "tool_candidates": [{
                "tool": "bullish_ifvg",
                "price_level": {
                    "midpoint":           midpoint,
                    "invalidation_level": zone_low if intent_type == "long" else zone_high,
                },
            }],
        },
    }


_ACCOUNT = {"buying_power": "399963"}


class TestEntryOrderType(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("ENTRY_ORDER_TYPE", None)

    def test_default_is_market_doctrine(self):
        os.environ.pop("ENTRY_ORDER_TYPE", None)
        self.assertEqual(entry_order_type(), "market")

    def test_limit_rollback(self):
        os.environ["ENTRY_ORDER_TYPE"] = "limit"
        self.assertEqual(entry_order_type(), "limit")

    def test_garbage_falls_back_to_market(self):
        os.environ["ENTRY_ORDER_TYPE"] = "stop_limit"
        self.assertEqual(entry_order_type(), "market")


class TestMarketOrderBuild(unittest.TestCase):

    def setUp(self):
        os.environ["ENTRY_ORDER_TYPE"] = "market"
        os.environ["RISK_PER_TRADE_DOLLARS"] = "500"

    def tearDown(self):
        for k in ("ENTRY_ORDER_TYPE", "RISK_PER_TRADE_DOLLARS", "MAX_CHASE_RISK_MULT"):
            os.environ.pop(k, None)

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_june11_market_build(self, _acct):
        """
        June 11 counterfactual: market at 701.42 against stop 700.79.
        risk/share 0.63 -> qty floor(250/0.63) = 396, risk-bound (not
        buying-power-bound like the actual 571-share limit order was).
        """
        result = build_order(_snapshot(), "QQQ")
        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["order_type"], "market")
        self.assertEqual(result["entry_reference"], 701.42)
        self.assertEqual(result["decision_price"], 701.42)
        self.assertEqual(result["stop_reference"], 700.79)
        self.assertAlmostEqual(result["risk_per_share"], 0.63, places=4)
        self.assertEqual(result["qty"], 396)
        self.assertAlmostEqual(result["risk_dollars"], 249.48, places=2)
        # Market order request carries no limit price
        self.assertFalse(hasattr(result["order_request"], "limit_price")
                         and result["order_request"].limit_price is not None)

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_zone_guard_rejects_price_outside_zone(self, _acct):
        """The limit price used to bound WHERE we execute; this guard does now."""
        result = build_order(_snapshot(current_price=702.54,
                                       price_relation="above_zone"), "QQQ")
        self.assertFalse(result["valid"])
        self.assertIn("price_relation", result["reject_reason"])

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_zone_guard_accepts_touching_zone(self, _acct):
        result = build_order(_snapshot(price_relation="touching_zone"), "QQQ")
        self.assertTrue(result["valid"])

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_missing_current_price_rejects(self, _acct):
        result = build_order(_snapshot(current_price=None), "QQQ")
        self.assertFalse(result["valid"])
        self.assertIn("current_price", result["reject_reason"])

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_chase_cap_rejects_ballooned_risk(self, _acct):
        # zone risk = |701.14 - 700.79| = 0.35; live risk would be
        # |701.49 - 700.79| = 0.70 at the very top of the zone -> exactly 2.0x
        # passes, so tighten the cap to prove the guard.
        os.environ["MAX_CHASE_RISK_MULT"] = "1.5"
        result = build_order(_snapshot(current_price=701.49,
                                       price_relation="touching_zone"), "QQQ")
        self.assertFalse(result["valid"])
        self.assertIn("chase cap", result["reject_reason"])

    @patch.object(ob_mod, "_get_account", return_value=_ACCOUNT)
    def test_limit_rollback_reproduces_legacy_build(self, _acct):
        """ENTRY_ORDER_TYPE=limit must reproduce June 11's actual order."""
        os.environ["ENTRY_ORDER_TYPE"] = "limit"
        result = build_order(_snapshot(), "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["order_type"], "limit")
        self.assertEqual(result["entry_reference"], 701.14)     # zone midpoint
        self.assertAlmostEqual(result["risk_per_share"], 0.35, places=4)
        self.assertEqual(result["order_request"].limit_price, 701.14)
        # June 11 actual: risk qty 714 capped by buying power to 570
        self.assertEqual(result["qty"],
                         min(714, int(float(_ACCOUNT["buying_power"]) / 701.14)))


class TestJournalDoctrineFields(unittest.TestCase):

    def test_make_record_carries_execution_mode_and_decision_price(self):
        rec = make_record(
            trade_id="PT_TEST", symbol="QQQ", intent_id=None,
            intent_type="long", side="buy", qty=396,
            entry_reference=701.42, stop_reference=700.79,
            risk_per_share=0.63, risk_dollars=249.48,
            order_status="submitted", alpaca_order_id="x", reason="test",
            execution_mode="market", decision_price=701.42,
        )
        self.assertEqual(rec["execution_mode"], "market")
        self.assertEqual(rec["decision_price"], 701.42)
        self.assertIsNone(rec["planned_risk_per_share"])
        self.assertIsNone(rec["entry_slippage"])

    def test_make_record_defaults_stay_legacy(self):
        rec = make_record(
            trade_id="PT_TEST", symbol="QQQ", intent_id=None,
            intent_type="long", side="buy", qty=571,
            entry_reference=701.14, stop_reference=700.79,
            risk_per_share=0.35, risk_dollars=199.85,
            order_status="submitted", alpaca_order_id="x", reason="test",
        )
        self.assertEqual(rec["execution_mode"], "limit")
        self.assertIsNone(rec["decision_price"])


class TestFillTruthRisk(unittest.TestCase):

    def test_recomputes_risk_from_fill(self):
        trade = {"risk_per_share": 0.63, "risk_dollars": 249.48,
                 "stop_reference": 700.79, "decision_price": 701.42,
                 "side": "buy", "qty": 396}
        order_info = {"filled_avg_price": "701.45", "filled_qty": "396"}
        out = recon_mod._fill_truth_risk(trade, order_info)
        self.assertEqual(out["planned_risk_per_share"], 0.63)
        self.assertAlmostEqual(out["risk_per_share"], 0.66, places=4)
        self.assertAlmostEqual(out["risk_dollars"], 261.36, places=2)
        self.assertAlmostEqual(out["entry_slippage"], 0.03, places=4)  # adverse

    def test_favorable_slippage_is_negative(self):
        trade = {"risk_per_share": 0.63, "stop_reference": 700.79,
                 "decision_price": 701.42, "side": "buy", "qty": 396}
        order_info = {"filled_avg_price": "701.40", "filled_qty": "396"}
        out = recon_mod._fill_truth_risk(trade, order_info)
        self.assertAlmostEqual(out["entry_slippage"], -0.02, places=4)

    def test_short_side_slippage_sign(self):
        trade = {"risk_per_share": 0.07, "stop_reference": 699.42,
                 "decision_price": 699.35, "side": "sell", "qty": 100}
        order_info = {"filled_avg_price": "699.30", "filled_qty": "100"}
        out = recon_mod._fill_truth_risk(trade, order_info)
        self.assertAlmostEqual(out["entry_slippage"], 0.05, places=4)  # adverse

    def test_missing_inputs_return_empty(self):
        self.assertEqual(recon_mod._fill_truth_risk({}, {}), {})
        self.assertEqual(
            recon_mod._fill_truth_risk({"stop_reference": None},
                                       {"filled_avg_price": "701.45"}),
            {},
        )

    def test_fill_at_stop_returns_empty(self):
        trade = {"stop_reference": 700.79, "side": "buy", "qty": 396}
        order_info = {"filled_avg_price": "700.79", "filled_qty": "396"}
        self.assertEqual(recon_mod._fill_truth_risk(trade, order_info), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
