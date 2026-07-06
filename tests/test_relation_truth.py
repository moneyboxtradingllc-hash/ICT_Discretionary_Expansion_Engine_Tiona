"""
RELATION-TRUTH — regression lock for the truthful price_relation measurement.

The old absolute `_TOUCH_TOLERANCE = 1.5` (Phase-1L mock era, NQ-scale)
classified QQQ prices up to 1.5 points beyond a zone as "touching_zone",
feeding false adjacency to FC-0B's in-zone guard, trigger prep, intent
building, and the Brain payload. All four fully-authorized trades on
2026-07-06 died in the resulting guaranteed-kill band.

Locks:
  * truth table at live QQQ volatility (inside / touching / above / below)
  * ALL FOUR 2026-07-06 replay geometries now classify truthfully
  * legacy high-price (mock NQ-scale) instruments stay proportionally sane
  * unknown volatility -> zero tolerance (never manufacture adjacency)
  * FC-0B unchanged: honest out-of-zone rejection; chase cap still enforces
  * downstream authorities untouched (source-level)
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")

from toolbox.price_levels import (            # noqa: E402
    _price_relation, _touch_tolerance, _make_zone, _TOUCH_TOLERANCE_FRACTION,
)


def _candles(rng: float, n: int = 5) -> list:
    return [{"range": rng, "open": 1, "high": 1 + rng, "low": 1, "close": 1 + rng,
             "direction": "bullish"} for _ in range(n)]


QQQ_TOL = round(0.20 * _TOUCH_TOLERANCE_FRACTION, 4)   # avg 1m range 0.20 -> 0.07


class TestTruthTable(unittest.TestCase):
    """Live QQQ volatility: avg 1m range 0.20 -> tolerance 0.07."""

    def setUp(self):
        self.tol = _touch_tolerance(_candles(0.20))
        self.assertEqual(self.tol, QQQ_TOL)

    def test_inside(self):
        self.assertEqual(_price_relation(724.60, 724.55, 724.67, self.tol),
                         "inside_zone")

    def test_touching_genuinely_adjacent(self):
        self.assertEqual(_price_relation(724.70, 724.55, 724.67, self.tol),
                         "touching_zone")      # 0.03 beyond edge, tol 0.07
        self.assertEqual(_price_relation(724.50, 724.55, 724.67, self.tol),
                         "touching_zone")      # 0.05 below zone_low

    def test_above(self):
        self.assertEqual(_price_relation(724.80, 724.55, 724.67, self.tol),
                         "above_zone")          # 0.13 beyond edge > 0.07

    def test_below(self):
        self.assertEqual(_price_relation(724.40, 724.55, 724.67, self.tol),
                         "below_zone")

    def test_unknown_price(self):
        self.assertEqual(_price_relation(None, 1, 2, self.tol), "unknown")


class TestLiveReplayFixtures(unittest.TestCase):
    """The four 2026-07-06 authorized kills — exact recorded geometry.
    Old classifier said touching_zone for ALL FOUR. Truth below."""

    TOL = QQQ_TOL   # 0.07 at that day's ~0.20 1m ranges

    def test_104715_price_017_above_micro_zone(self):
        # zone 724.55-724.67, current 724.84 (+0.17 beyond edge)
        self.assertEqual(_price_relation(724.84, 724.55, 724.67, self.TOL),
                         "above_zone")

    def test_110924_short_price_below_zone(self):
        # zone 723.83-724.46 (short), current 723.77 (0.06 below zone_low)
        # genuinely adjacent -> touching is the TRUTH here (tol 0.07)
        self.assertEqual(_price_relation(723.77, 723.83, 724.46, self.TOL),
                         "touching_zone")

    def test_112735_price_110_above_zone(self):
        # zone 723.48-723.67, current 724.77 (+1.10!) — the flagship lie
        self.assertEqual(_price_relation(724.77, 723.48, 723.67, self.TOL),
                         "above_zone")

    def test_112931_price_021_above_zone(self):
        # zone 723.82-724.48, current 724.69 (+0.21 beyond edge)
        self.assertEqual(_price_relation(724.69, 723.82, 724.48, self.TOL),
                         "above_zone")

    def test_true_retest_still_classifies_correctly(self):
        # when price genuinely returns to the 112735 zone, it must read inside
        self.assertEqual(_price_relation(723.60, 723.48, 723.67, self.TOL),
                         "inside_zone")


class TestAdaptiveTolerance(unittest.TestCase):
    def test_legacy_high_price_instrument_proportional(self):
        # mock-era NQ-scale candles (range ~8.0) -> tol 2.8: 1.4 beyond a
        # zone edge is still adjacent at that volatility; 5.0 is not.
        tol = _touch_tolerance(_candles(8.0))
        self.assertEqual(tol, 2.8)
        self.assertEqual(_price_relation(19501.4, 19495.0, 19500.0, tol),
                         "touching_zone")
        self.assertEqual(_price_relation(19505.0, 19495.0, 19500.0, tol),
                         "above_zone")

    def test_unknown_volatility_never_manufactures_adjacency(self):
        self.assertEqual(_touch_tolerance([]), 0.0)
        self.assertEqual(_touch_tolerance([{"open": 1}]), 0.0)
        self.assertEqual(_price_relation(724.68, 724.55, 724.67, 0.0),
                         "above_zone")   # 1 cent beyond edge, no data -> strict

    def test_make_zone_carries_truthful_relation_and_entered(self):
        z = _make_zone("ifvg_zone", "bullish", 723.48, 723.67, 723.48,
                       724.77, "1m", touch_tol=QQQ_TOL)
        self.assertEqual(z["price_relation"], "above_zone")
        self.assertFalse(z["entered_zone"])
        self.assertEqual(z["distance_to_zone"], 1.10)


class TestFC0BUnchanged(unittest.TestCase):
    """FC-0B doctrine byte-identical: it now simply receives truth."""

    def _snapshot(self, relation, current, zone_low=723.48, zone_high=723.67,
                  inv=723.48):
        return {
            "risk": {"risk_multiplier": 1.0},
            "regime_permissions": {"risk_multiplier_cap": 1.0},
            "trade_intent": {"intent_type": "long", "direction": "bullish",
                             "entry_zone": {"zone_low": zone_low,
                                            "zone_high": zone_high,
                                            "midpoint": round((zone_low+zone_high)/2, 3),
                                            "current_price": current,
                                            "price_relation": relation}},
            "toolbox": {"preferred_tool": "bullish_ifvg", "tool_candidates": [{
                "tool": "bullish_ifvg",
                "price_level": {"midpoint": round((zone_low+zone_high)/2, 3),
                                "invalidation_level": inv}}]},
        }

    @patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "500",
                             "ENTRY_ORDER_TYPE": "market"})
    def test_out_of_zone_now_rejected_with_the_honest_reason(self):
        from paper_execution.order_builder import build_order
        res = build_order(self._snapshot("above_zone", 724.77), "QQQ")
        self.assertFalse(res["valid"])
        self.assertIn("price has left the planned entry zone",
                      res["reject_reason"])          # guard, not chase-cap janitor

    @patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "500",
                             "ENTRY_ORDER_TYPE": "market"})
    @patch("paper_execution.order_builder._get_account",
           return_value={"buying_power": 400000.0})
    def test_genuine_inside_zone_entry_passes_guard_and_cap(self, _acct):
        from paper_execution.order_builder import build_order
        res = build_order(self._snapshot("inside_zone", 723.60), "QQQ")
        self.assertTrue(res["valid"], res.get("reject_reason"))
        self.assertEqual(res["side"], "buy")
        self.assertGreater(res["qty"], 0)

    @patch.dict(os.environ, {"RISK_PER_TRADE_DOLLARS": "500",
                             "ENTRY_ORDER_TYPE": "market"})
    def test_chase_cap_still_enforces_on_inside_relation(self):
        # inside a wide zone but far from the stop: cap must still refuse —
        # the backstop is untouched
        from paper_execution.order_builder import build_order
        snap = self._snapshot("inside_zone", 700.90, zone_low=700.0,
                              zone_high=701.0, inv=700.40)
        res = build_order(snap, "QQQ")
        self.assertFalse(res["valid"])
        self.assertIn("chase cap", res["reject_reason"])


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_no_downstream_file_changed_semantics(self):
        """Source guard: the consumers still read the same field the same way;
        no authority module gained tolerance logic."""
        for pkg, fname, must_not_contain in (
                ("paper_execution", "order_builder.py", "_touch_tolerance"),
                ("toolbox", "entry_trigger_prep.py", "_touch_tolerance"),
                ("trade_intent", "intent_builder.py", "_touch_tolerance"),
                ("execution_gate", "execution_gate.py", "price_relation")):
            with open(os.path.join(_SRC, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn(must_not_contain, fh.read(), f"{pkg}/{fname}")

    def test_old_absolute_is_gone(self):
        import re
        with open(os.path.join(_SRC, "toolbox", "price_levels.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        # the retired constant may be QUOTED in the tombstone comment, but no
        # code line may define an absolute touch tolerance again
        self.assertIsNone(re.search(r"^_TOUCH_TOLERANCE\s*=", src, re.M))


if __name__ == "__main__":
    unittest.main()
