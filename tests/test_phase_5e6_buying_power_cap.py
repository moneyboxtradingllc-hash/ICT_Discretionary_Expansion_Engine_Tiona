"""
Phase 5E.6 — Buying-Power-Aware Sizing Cap.

Targeted tests for the buying-power cap logic added to build_order().
Verifies: risk-cap, affordable-cap, boundary, zero-BP, tiny stop, normal trade,
account-lookup failure, and Day 2 exact reproduction.
"""
import os
import math
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.order_builder as ob_mod
from paper_execution.order_builder import build_order


# ── Snapshot builder ──────────────────────────────────────────────────────────

def _snap(entry: float, stop: float, direction: str = "bullish") -> dict:
    """Minimal snapshot with price_level populated for a long or short intent."""
    intent_type = "long" if direction == "bullish" else "short"
    return {
        "trade_intent": {
            "intent_created": True,
            "intent_type": intent_type,
            "direction": direction,
            "preferred_tool": f"{direction}_ifvg",
            "entry_zone": {
                "zone_low":  min(entry, stop),
                "zone_high": max(entry, stop),
                "midpoint":  entry,
            },
        },
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
                        "zone_low":  min(entry, stop),
                        "zone_high": max(entry, stop),
                        "midpoint":  entry,
                        "invalidation_level": stop,
                    },
                    "trigger_prep": {"execution_ready": True},
                }
            ],
        },
    }


def _acct(buying_power: float) -> dict:
    return {
        "buying_power": buying_power,
        "cash": buying_power,
        "equity": buying_power,
        "status": "ACTIVE",
        "account_number": "TEST",
    }


ENV = {"RISK_PER_TRADE_DOLLARS": "500"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBuyingPowerCap(unittest.TestCase):

    # ── 1. Risk qty > buying power cap → affordable qty wins ─────────────────

    def test_01_risk_qty_exceeds_buying_power_cap(self):
        """
        risk_per_share=3, budget=500 → risk_qty=166
        buying_power=50000, entry=479 → max_affordable=floor(50000/479)=104
        Expected: qty=104 (cap applied)
        """
        snap = _snap(entry=479.0, stop=476.0)
        bp   = 50_000.0
        expected_risk  = math.floor(500 / 3.0)            # 166
        expected_afford = math.floor(bp / 479.0)           # 104
        expected_qty   = min(expected_risk, expected_afford)  # 104

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["qty"], expected_qty)
        self.assertEqual(result["risk_qty"], expected_risk)
        self.assertEqual(result["affordable_qty"], expected_afford)
        self.assertLess(result["qty"], result["risk_qty"])

    # ── 2. Risk qty < buying power cap → risk qty wins ────────────────────────

    def test_02_risk_qty_within_buying_power(self):
        """
        risk_per_share=3, budget=500 → risk_qty=166
        buying_power=1_000_000, entry=479 → max_affordable=2087
        Expected: qty=166 (risk is limiting factor, cap not triggered)
        """
        snap = _snap(entry=479.0, stop=476.0)
        bp   = 1_000_000.0
        expected_risk   = math.floor(500 / 3.0)   # 166
        expected_afford = math.floor(bp / 479.0)   # 2087

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["qty"], expected_risk)
        self.assertEqual(result["affordable_qty"], expected_afford)
        self.assertGreater(result["affordable_qty"], result["qty"])

    # ── 3. Exact buying power boundary ────────────────────────────────────────

    def test_03_exact_buying_power_boundary(self):
        """
        entry=100, stop=99 → risk_per_share=1 → risk_qty=500
        buying_power=50000 → max_affordable=floor(50000/100)=500
        Expected: qty=500, min(500,500)=500 (exact tie → no cap)
        """
        snap = _snap(entry=100.0, stop=99.0)
        bp   = 50_000.0

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["risk_qty"], 500)
        self.assertEqual(result["affordable_qty"], 500)
        self.assertEqual(result["qty"], 500)

    # ── 4. Zero buying power → reject ────────────────────────────────────────

    def test_04_zero_buying_power_rejects(self):
        """
        buying_power=0 → max_affordable=0 → order rejected with
        insufficient_buying_power reason.
        """
        snap = _snap(entry=479.0, stop=476.0)

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(0.0)):
                result = build_order(snap, "QQQ")

        self.assertFalse(result["valid"])
        self.assertIn("insufficient_buying_power", result["reject_reason"])

    # ── 5. Tiny stop distance → large risk_qty, capped by buying power ────────

    def test_05_tiny_stop_distance_day2_reproduction(self):
        """
        Exact Day 2 rejection reproduction.
        entry=721.675, stop=721.41 → risk_per_share=0.265 → risk_qty=1886
        buying_power=400655.20 → max_affordable=floor(400655.20/721.675)=555
        Expected: qty=555 (cap prevents $1.36M order), order valid.
        """
        snap = _snap(entry=721.675, stop=721.41)
        bp   = 400_655.20

        expected_risk   = math.floor(500 / 0.265)          # 1886
        expected_afford = math.floor(bp / 721.675)          # 555

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["risk_qty"], expected_risk)
        self.assertEqual(result["affordable_qty"], expected_afford)
        self.assertEqual(result["qty"], expected_afford)

        # Position value must be within buying power
        position_value = result["qty"] * result["entry_reference"]
        self.assertLessEqual(position_value, bp)

        # Risk dollars must be within budget
        self.assertLessEqual(result["risk_dollars"], 500.0)

    # ── 6. Normal trade — both values healthy ─────────────────────────────────

    def test_06_normal_trade_no_cap(self):
        """
        entry=100, stop=95 → risk_per_share=5 → risk_qty=100
        buying_power=20000 → max_affordable=200
        Expected: qty=100, risk wins, position_value=$10000 within $20000 BP.
        """
        snap = _snap(entry=100.0, stop=95.0)
        bp   = 20_000.0

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"], result.get("reject_reason"))
        self.assertEqual(result["qty"], 100)
        self.assertLessEqual(result["qty"] * result["entry_reference"], bp)

    # ── 7. Account lookup failure → clean reject ──────────────────────────────

    def test_07_account_lookup_failure_rejects_cleanly(self):
        """
        _get_account() returns {"error": "connection failed"} →
        build_order() returns valid=False with buying_power_lookup_failed reason.
        No crash, no submission attempt.
        """
        snap = _snap(entry=479.0, stop=476.0)

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value={"error": "connection failed"}):
                result = build_order(snap, "QQQ")

        self.assertFalse(result["valid"])
        self.assertIn("buying_power_lookup_failed", result["reject_reason"])
        self.assertIn("connection failed", result["reject_reason"])

    # ── 8. Return dict contains all sizing fields ─────────────────────────────

    def test_08_return_dict_has_sizing_fields(self):
        """
        Successful build_order result must contain risk_qty, affordable_qty,
        buying_power fields for journal and logging.
        """
        snap = _snap(entry=479.0, stop=476.0)
        bp   = 500_000.0

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"])
        self.assertIn("risk_qty",       result)
        self.assertIn("affordable_qty", result)
        self.assertIn("buying_power",   result)
        self.assertIsInstance(result["risk_qty"],       int)
        self.assertIsInstance(result["affordable_qty"], int)
        self.assertIsInstance(result["buying_power"],   float)

    # ── 9. risk_dollars reflects capped qty, not risk_qty ─────────────────────

    def test_09_risk_dollars_uses_capped_qty(self):
        """
        When cap is applied, risk_dollars must be risk_per_share * qty (capped),
        not risk_per_share * risk_qty (uncapped).
        """
        snap = _snap(entry=479.0, stop=476.0)
        bp   = 40_000.0  # tight → affordable=floor(40000/479)=83 < risk_qty=166

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
                result = build_order(snap, "QQQ")

        self.assertTrue(result["valid"])
        expected_risk_dollars = round(result["risk_per_share"] * result["qty"], 2)
        self.assertAlmostEqual(result["risk_dollars"], expected_risk_dollars, places=2)
        self.assertLess(result["qty"], result["risk_qty"])

    # ── 10. Negative buying power treated as zero ─────────────────────────────

    def test_10_negative_buying_power_rejects(self):
        """
        Negative buying_power (margin call / over-extended account) →
        max_affordable=0 → reject with insufficient_buying_power.
        """
        snap = _snap(entry=479.0, stop=476.0)

        with patch.dict(os.environ, ENV):
            with patch.object(ob_mod, "_get_account", return_value=_acct(-1000.0)):
                result = build_order(snap, "QQQ")

        self.assertFalse(result["valid"])
        self.assertIn("insufficient_buying_power", result["reject_reason"])

    # ── 11. qty=0 (budget too small) still rejects before BP check ────────────

    def test_11_qty_zero_from_budget_rejects_before_bp_check(self):
        """
        risk_budget=1, risk_per_share=3 → risk_qty=0 →
        rejected at qty=0 check before _get_account() is ever called.
        """
        snap = _snap(entry=479.0, stop=476.0)
        call_count = {"n": 0}

        def mock_acct():
            call_count["n"] += 1
            return _acct(1_000_000.0)

        with patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "1"}):
            with patch.object(ob_mod, "_get_account", side_effect=mock_acct):
                result = build_order(snap, "QQQ")

        self.assertFalse(result["valid"])
        self.assertIn("qty=0", result["reject_reason"])
        self.assertEqual(call_count["n"], 0, "_get_account must not be called when risk_qty=0")


if __name__ == "__main__":
    unittest.main()
