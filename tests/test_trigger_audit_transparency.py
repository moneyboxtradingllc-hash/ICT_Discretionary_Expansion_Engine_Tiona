"""
TRIGGER-AUDIT — confirmation transparency: regression lock.

2026-07-08 candle-by-candle trial of all 10 observe_only intents:
  * DISC-but-not-CODE = 1/10 (below the >=3 overbuilt threshold) — the
    confirmation RULE (directional close beyond zone midpoint) is NOT overbuilt
    and keeps its authority.
  * BUT 4/10 intents had a code-confirming candle in replay yet 0 confirmed
    LIVE. Root cause is UPSTREAM: (a) qualification/toolbox flicker vanishes the
    setup (tool_cands=0) on the confirming scan, and (b) the confirming candle
    closes past the zone edge, flipping price_relation to above/below_zone and
    reverting the trigger to waiting_for_retest.

This repair is AUDIT-TRUTH ONLY (option A): it records WHY confirmation did or
did not complete each scan without changing the trigger verdict. It does not
weaken the rule, force trades, or touch FC-0B / risk / sizing / broker.

Locks:
  * the exact confirmation rule is documented + tested (directional AND beyond
    midpoint), for both directions
  * every confirmation_needed scan reports confirmation_candle_met + the exact
    failed condition (not_directional / directional_but_not_beyond_midpoint /
    no_candle_data)
  * the trigger STATUS is byte-identical to pre-repair (no behavior change)
  * the wick-rejection axis (directional but not beyond midpoint) is explicitly
    labeled so the next session can measure rule strictness
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.entry_trigger_prep import (                       # noqa: E402
    build_trigger_prep, _confirmation_candle_ok, _confirmation_detail,
)


def _snap(last_1m):
    return {"risk": {"trade_allowed": True},
            "timeframes": {"1m": {"last_candle": last_1m}}}


def _plevel(zl=709.0, zh=710.0, invalid=False):
    return {"zone_low": zl, "zone_high": zh, "midpoint": round((zl + zh) / 2, 3),
            "price_relation": "inside_zone", "invalidated": invalid,
            "level_type": "fvg_zone"}


def _prep(tool, snap, plevel, raw_status="actionable"):
    readiness = {"prerequisites_missing": []}
    return build_trigger_prep(tool, snap, plevel, readiness, raw_status, raw_status)


class TestRuleDocumented(unittest.TestCase):
    def test_bearish_rule_directional_and_beyond_midpoint(self):
        pl = _plevel(709.0, 710.0)  # mid 709.5
        # bearish confirm: close < open AND close < 709.5
        self.assertTrue(_confirmation_candle_ok(
            _snap({"open": 709.8, "close": 709.3}), "bearish", pl))
        # directional but NOT beyond midpoint -> no confirm
        self.assertFalse(_confirmation_candle_ok(
            _snap({"open": 709.9, "close": 709.7}), "bearish", pl))
        # beyond midpoint but NOT directional (green) -> no confirm
        self.assertFalse(_confirmation_candle_ok(
            _snap({"open": 709.2, "close": 709.4}), "bearish", pl))

    def test_bullish_rule_directional_and_beyond_midpoint(self):
        pl = _plevel(709.0, 710.0)  # mid 709.5
        self.assertTrue(_confirmation_candle_ok(
            _snap({"open": 709.2, "close": 709.8}), "bullish", pl))
        self.assertFalse(_confirmation_candle_ok(
            _snap({"open": 709.1, "close": 709.3}), "bullish", pl))  # not beyond mid


class TestFailedConditionReported(unittest.TestCase):
    def test_met(self):
        d = _confirmation_detail(_snap({"open": 709.8, "close": 709.3}), "bearish", _plevel())
        self.assertTrue(d["confirmation_candle_met"])
        self.assertIsNone(d["failed_condition"])

    def test_not_directional(self):
        d = _confirmation_detail(_snap({"open": 709.2, "close": 709.4}), "bearish", _plevel())
        self.assertFalse(d["confirmation_candle_met"])
        self.assertEqual(d["failed_condition"], "candle_not_directional")

    def test_directional_but_not_beyond_midpoint(self):
        # the wick-rejection axis: red candle, but closes above midpoint
        d = _confirmation_detail(_snap({"open": 709.9, "close": 709.7}), "bearish", _plevel())
        self.assertFalse(d["confirmation_candle_met"])
        self.assertEqual(d["failed_condition"], "directional_but_not_beyond_midpoint")

    def test_no_candle_data(self):
        d = _confirmation_detail({"timeframes": {}}, "bearish", _plevel())
        self.assertEqual(d["failed_condition"], "no_candle_data")

    def test_never_raises_on_garbage(self):
        d = _confirmation_detail(_snap({"open": "x", "close": None}), "bearish", _plevel())
        self.assertFalse(d["confirmation_candle_met"])
        self.assertIsNotNone(d["failed_condition"])


class TestPrepSurfacesAudit(unittest.TestCase):
    def test_confirmed_when_candle_met(self):
        out = _prep("bearish_ifvg", _snap({"open": 709.8, "close": 709.3}), _plevel())
        self.assertEqual(out["raw_trigger_status"], "confirmed")
        self.assertTrue(out["confirmation_candle_met"])
        self.assertIsNone(out["confirmation_failed_condition"])
        self.assertEqual(out["confirmation_candle_tf"], "1m")

    def test_confirmation_needed_reports_failed_condition(self):
        out = _prep("bearish_ifvg", _snap({"open": 709.9, "close": 709.7}), _plevel())
        self.assertEqual(out["raw_trigger_status"], "confirmation_needed")
        self.assertFalse(out["confirmation_candle_met"])
        self.assertEqual(out["confirmation_failed_condition"],
                         "directional_but_not_beyond_midpoint")


class TestBehaviorUnchanged(unittest.TestCase):
    def test_trigger_status_identical_to_rule(self):
        """The audit block must not change the trigger verdict — status is
        exactly what _confirmation_candle_ok dictates."""
        for candle, expect_confirmed in (
                ({"open": 709.8, "close": 709.3}, True),    # confirm
                ({"open": 709.9, "close": 709.7}, False),   # not beyond mid
                ({"open": 709.2, "close": 709.4}, False)):  # not directional
            out = _prep("bearish_ifvg", _snap(candle), _plevel())
            self.assertEqual(out["raw_trigger_status"] == "confirmed",
                             expect_confirmed, candle)

    def test_invalidated_zone_still_invalidated(self):
        out = _prep("bearish_ifvg", _snap({"open": 709.8, "close": 709.3}),
                    _plevel(invalid=True))
        self.assertEqual(out["raw_trigger_status"], "invalidated")


if __name__ == "__main__":
    unittest.main()
