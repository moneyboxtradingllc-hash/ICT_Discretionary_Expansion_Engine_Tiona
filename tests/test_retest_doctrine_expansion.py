"""
RETEST-DOCTRINE (2026-07-09) — expansion-continuation trigger path.

The retest trial proved the trigger applied ONE retest-only rule to every family:
any price_relation other than inside/touching → waiting_for_retest forever, with
no path to confirm a CONTINUATION entry once price displaced past the zone. Scan
095457 (trend_continuation, price 2.2pt above the FVG in mature_expansion) waited
all day; the reversal scans (094951/104851) were correctly waiting (094951's tape
reversed up — a short would have lost).

Repair: EXPANSION_CONTINUATION_TRIGGER=on lets a CONTINUATION family in a
directional expansion confirm on a genuine displacement candle (directional
momentum close beyond the far zone edge in the trade direction) instead of a
pullback retest. REVERSAL setups keep their retest requirement. Confirmation is
not removed; FC-0B's chase cap stays the backstop. Default off = legacy.

Mission-required locks (1-11).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.entry_trigger_prep import build_trigger_prep                # noqa: E402


def _snap(playbook, o, c, expansion="mature_expansion"):
    return {"risk": {"trade_allowed": True},
            "playbook": {"selected_playbook": playbook},
            "market_regime": {"expansion_state": expansion},
            "timeframes": {"1m": {"last_candle": {"open": o, "close": c}}}}


def _pl(direction, zl, zh, relation, current):
    return {"level_type": "fvg_zone", "direction": direction, "zone_low": zl,
            "zone_high": zh, "midpoint": round((zl + zh) / 2, 3),
            "current_price": current, "price_relation": relation, "invalidated": False}


def _prep(tool, snap, pl, raw="actionable", eff="actionable"):
    return build_trigger_prep(tool, snap, pl, {"prerequisites_missing": False}, raw, eff)


class TestAuditTruth(unittest.TestCase):
    def test_1_waiting_reports_exact_missing_condition(self):
        # Repair G: waiting_for_retest must say WHY, not just that it is waiting.
        with patch.dict(os.environ, {"EXPANSION_CONTINUATION_TRIGGER": "off"}):
            tp = _prep("bullish_fvg", _snap("trend_continuation", 722.0, 722.4),
                       _pl("bullish", 718.89, 719.98, "above_zone", 722.4))
            self.assertEqual(tp["raw_trigger_status"], "waiting_for_retest")
            self.assertIn("above_zone", tp["trigger_wait_reason"])
            self.assertIn("retest", tp["trigger_wait_reason"].lower())


class TestRetestAndConfirmationStillWork(unittest.TestCase):
    def test_2_valid_zone_retest_detected(self):
        # price touching the zone → progresses past waiting_for_retest
        tp = _prep("bullish_fvg", _snap("trend_continuation", 719.5, 719.9),
                   _pl("bullish", 718.89, 719.98, "touching_zone", 719.9))
        self.assertNotEqual(tp["raw_trigger_status"], "waiting_for_retest")

    def test_3_valid_wick_rejection_confirmation_detected(self):
        # inside zone + directional close beyond midpoint → confirmed
        tp = _prep("bullish_fvg", _snap("trend_continuation", 719.2, 719.9),
                   _pl("bullish", 718.89, 719.98, "inside_zone", 719.9))
        self.assertIn(tp["raw_trigger_status"], ("confirmation_needed", "confirmed"))


class TestExpansionPath(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"EXPANSION_CONTINUATION_TRIGGER": "on"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_4_displacement_away_from_zone_detected(self):
        tp = _prep("bullish_fvg", _snap("trend_continuation", 722.05, 722.46),
                   _pl("bullish", 718.89, 719.98, "above_zone", 722.46))
        self.assertTrue(tp["expansion_confirmed"])

    def test_5_continuation_not_trapped_forever(self):
        # scan 095457: trend_continuation displaced above the FVG → now confirms
        tp = _prep("bullish_fvg", _snap("trend_continuation", 722.05, 722.46),
                   _pl("bullish", 718.89, 719.98, "above_zone", 722.46))
        self.assertEqual(tp["raw_trigger_status"], "confirmed")
        self.assertTrue(tp["execution_ready"])

    def test_5b_bearish_continuation_displacement(self):
        tp = _prep("bearish_fvg", _snap("manipulation_to_distribution", 719.0, 718.4),
                   _pl("bearish", 719.5, 720.5, "below_zone", 718.4))
        self.assertEqual(tp["raw_trigger_status"], "confirmed")
        self.assertTrue(tp["execution_ready"])

    def test_6_reversal_still_requires_retest(self):
        # 094951/104851: liquidity_sweep_reversal keeps retest even when displaced
        tp = _prep("bearish_ifvg", _snap("liquidity_sweep_reversal", 720.49, 720.39),
                   _pl("bearish", 721.32, 721.34, "below_zone", 720.39))
        self.assertEqual(tp["raw_trigger_status"], "waiting_for_retest")
        self.assertFalse(tp["execution_ready"])
        self.assertFalse(tp["expansion_path_available"])

    def test_6b_reversing_candle_never_confirms_continuation(self):
        # a bearish setup with an UP candle must never confirm (094951 reversal)
        tp = _prep("bearish_fvg", _snap("trend_continuation", 720.19, 720.53),
                   _pl("bearish", 721.32, 721.34, "below_zone", 720.53))
        self.assertFalse(tp["expansion_confirmed"])
        self.assertEqual(tp["raw_trigger_status"], "waiting_for_retest")

    def test_expansion_requires_directional_expansion_state(self):
        # continuation playbook but NOT an expansion state → no path
        tp = _prep("bullish_fvg", _snap("trend_continuation", 722.05, 722.46, expansion="compression"),
                   _pl("bullish", 718.89, 719.98, "above_zone", 722.46))
        self.assertFalse(tp["expansion_path_available"])
        self.assertEqual(tp["raw_trigger_status"], "waiting_for_retest")


class TestDefaultOffLegacy(unittest.TestCase):
    def test_default_off_byte_identical_status(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EXPANSION_CONTINUATION_TRIGGER", None)
            tp = _prep("bullish_fvg", _snap("trend_continuation", 722.05, 722.46),
                       _pl("bullish", 718.89, 719.98, "above_zone", 722.46))
            self.assertEqual(tp["raw_trigger_status"], "waiting_for_retest")
            self.assertFalse(tp["execution_ready"])
            self.assertFalse(tp["expansion_confirmed"])


class TestSafeguardsUntouched(unittest.TestCase):
    def test_7_to_11_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py"),
                           ("execution_gate", "execution_gate.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("EXPANSION_CONTINUATION_TRIGGER", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()
