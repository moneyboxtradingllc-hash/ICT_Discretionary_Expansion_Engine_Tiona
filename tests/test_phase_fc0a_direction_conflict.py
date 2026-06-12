"""
Phase FC-0A — Direction-Conflict Veto tests.

June 11 root cause: qualification._direction() took structure bias first and
never consulted sweep semantics. A confirmed above_high sweep + reclaim
(bearish by ICT semantics) was traded long because 3/4 timeframes carried a
bullish structure bias.

Required behavior: sweep semantics vs structure bias disagreement returns
CONFLICTED. Rollback: DIRECTION_CONFLICT_VETO=false restores legacy behavior.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qualification.trade_qualification_engine import (
    _direction,
    _sweep_semantic_direction,
    qualify_trade,
)


def _liq(tf: str, sweep_direction: str, reclaim: bool = True) -> dict:
    return {
        tf: {
            "sweep_detected":   True,
            "sweep_direction":  sweep_direction,
            "reclaim_detected": reclaim,
        }
    }


class TestSweepSemanticDirection(unittest.TestCase):

    def test_above_high_is_bearish(self):
        self.assertEqual(_sweep_semantic_direction(_liq("15m", "above_high")), "bearish")

    def test_below_low_is_bullish(self):
        self.assertEqual(_sweep_semantic_direction(_liq("15m", "below_low")), "bullish")

    def test_no_sweep_is_none(self):
        self.assertIsNone(_sweep_semantic_direction({"15m": {"sweep_detected": False}}))
        self.assertIsNone(_sweep_semantic_direction({}))
        self.assertIsNone(_sweep_semantic_direction(None))

    def test_sweep_without_reclaim_is_none(self):
        self.assertIsNone(
            _sweep_semantic_direction(_liq("15m", "above_high", reclaim=False))
        )

    def test_higher_timeframe_wins(self):
        liq = {}
        liq.update(_liq("15m", "above_high"))
        liq.update(_liq("5m", "below_low"))
        self.assertEqual(_sweep_semantic_direction(liq), "bearish")


class TestDirectionConflictVeto(unittest.TestCase):

    def setUp(self):
        os.environ["DIRECTION_CONFLICT_VETO"] = "true"

    def tearDown(self):
        os.environ.pop("DIRECTION_CONFLICT_VETO", None)

    def test_bullish_bias_vs_bearish_sweep_is_conflicted(self):
        d = _direction({"directional_bias": "bullish"}, {}, {},
                       _liq("15m", "above_high"))
        self.assertEqual(d, "conflicted")

    def test_bearish_bias_vs_bullish_sweep_is_conflicted(self):
        d = _direction({"directional_bias": "bearish"}, {}, {},
                       _liq("15m", "below_low"))
        self.assertEqual(d, "conflicted")

    def test_agreeing_sweep_passes(self):
        d = _direction({"directional_bias": "bullish"}, {}, {},
                       _liq("15m", "below_low"))
        self.assertEqual(d, "bullish")

    def test_no_sweep_keeps_bias(self):
        d = _direction({"directional_bias": "bullish"}, {}, {}, {})
        self.assertEqual(d, "bullish")

    def test_neutral_bias_unaffected(self):
        # With neutral bias the legacy fallback chain runs unchanged.
        d = _direction({"directional_bias": "neutral"}, {}, {},
                       _liq("15m", "above_high"))
        self.assertIn(d, ("neutral", "bullish", "bearish"))

    def test_rollback_env_restores_legacy(self):
        os.environ["DIRECTION_CONFLICT_VETO"] = "false"
        d = _direction({"directional_bias": "bullish"}, {}, {},
                       _liq("15m", "above_high"))
        self.assertEqual(d, "bullish")   # exact June 11 (wrong) behavior

    def test_po3_conflict_path_still_works(self):
        d = _direction(
            {"directional_bias": "bullish"}, {},
            {"15m": {"distribution_direction": "bearish"}}, {},
        )
        self.assertEqual(d, "conflicted")


class TestJune11Replay(unittest.TestCase):
    """
    Replay proof: the documented June 11 10:29 inputs.

    From the forensic reconstruction (snapshot 20260611_102955 + engine code):
      - ai_context directional_bias: bullish (3/4 timeframes bullish structure)
      - 15m liquidity: sweep above_high, reclaim confirmed
      - PO3: 15m manipulation, no distribution_direction (no PO3 conflict)
    Legacy result: bullish -> long traded -> -1.34R.
    Required result: conflicted.
    """

    JUNE11_AI_CONTEXT = {
        "directional_bias": "bullish",
        "market_narrative": "liquidity_sweep_reversal",
    }
    JUNE11_LIQUIDITY = {
        "15m": {
            "sweep_detected":   True,
            "sweep_direction":  "above_high",
            "reclaim_detected": True,
        },
        "5m":  {"sweep_detected": False},
        "3m":  {"sweep_detected": False},
        "1m":  {"sweep_detected": False},
    }
    JUNE11_PO3 = {
        "15m": {"phase": "manipulation"},
        "5m":  {"phase": "accumulation"},
        "3m":  {"phase": "accumulation"},
        "1m":  {"phase": "accumulation"},
        "alignment": "mixed",
    }

    def setUp(self):
        os.environ["DIRECTION_CONFLICT_VETO"] = "true"

    def tearDown(self):
        os.environ.pop("DIRECTION_CONFLICT_VETO", None)

    def test_june11_direction_is_conflicted(self):
        d = _direction(self.JUNE11_AI_CONTEXT, {}, self.JUNE11_PO3,
                       self.JUNE11_LIQUIDITY)
        self.assertEqual(d, "conflicted")

    def test_june11_full_qualify_trade_is_conflicted(self):
        snapshot = {
            "ai_context": self.JUNE11_AI_CONTEXT,
            "structure":  {"alignment": "strong"},
            "volatility": {"15m": {"state": "unstable"}},
            "po3":        self.JUNE11_PO3,
            "liquidity":  self.JUNE11_LIQUIDITY,
        }
        result = qualify_trade(snapshot)
        self.assertEqual(result["direction"], "conflicted")

    def test_june11_legacy_mode_reproduces_the_bug(self):
        os.environ["DIRECTION_CONFLICT_VETO"] = "false"
        d = _direction(self.JUNE11_AI_CONTEXT, {}, self.JUNE11_PO3,
                       self.JUNE11_LIQUIDITY)
        self.assertEqual(d, "bullish")


if __name__ == "__main__":
    unittest.main(verbosity=2)
