"""A SINGLE timeframe in exhaustion_risk must not veto the whole market narrative.

`_market_narrative` returning "exhaustion_risk" is a hard no-trade disqualifier
downstream (_NO_TRADE_NARRATIVES in trade_qualification_engine), so a lone
exhaustion reading was standing the bot down through full MTF alignment,
confirmed displacement and an identified liquidity draw. The veto now requires
>= 2 of 15m/5m/3m — the same bar _market_state uses to call the environment
"dangerous". (Operator ruling, 2026-07-23.)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_layer.narrative_builder import _market_narrative  # noqa: E402


def _exp(**states):
    """expansion dict with the given per-timeframe states."""
    return {tf: {"state": states.get(tf, "healthy_expansion")} for tf in ("15m", "5m", "3m")}


_NO_SWEEP = {tf: {"sweep_detected": False, "reclaim_detected": False}
             for tf in ("15m", "5m", "3m", "1m")}


class TestExhaustionNeedsTwoTimeframes(unittest.TestCase):
    def _narrative(self, expansion):
        return _market_narrative(bias="bearish", market_state="expanding",
                                 structure={}, liquidity=_NO_SWEEP,
                                 expansion=expansion, po3={})

    def test_single_timeframe_exhaustion_does_not_veto(self):
        for tf in ("15m", "5m", "3m"):
            with self.subTest(tf=tf):
                self.assertNotEqual(
                    self._narrative(_exp(**{tf: "exhaustion_risk"})), "exhaustion_risk",
                    f"a lone {tf} exhaustion must not set the no-trade narrative")

    def test_two_timeframes_still_veto(self):
        self.assertEqual(self._narrative(_exp(**{"15m": "exhaustion_risk",
                                                 "5m": "exhaustion_risk"})),
                         "exhaustion_risk")

    def test_all_three_still_veto(self):
        self.assertEqual(self._narrative(_exp(**{"15m": "exhaustion_risk",
                                                 "5m": "exhaustion_risk",
                                                 "3m": "exhaustion_risk"})),
                         "exhaustion_risk")

    def test_no_exhaustion_is_not_vetoed(self):
        self.assertNotEqual(self._narrative(_exp()), "exhaustion_risk")

    def test_sweep_reclaim_still_takes_priority(self):
        # sweep+reclaim outranks exhaustion even on 2 timeframes (unchanged)
        liq = dict(_NO_SWEEP)
        liq["5m"] = {"sweep_detected": True, "reclaim_detected": True}
        self.assertEqual(
            _market_narrative(bias="bearish", market_state="expanding", structure={},
                              liquidity=liq,
                              expansion=_exp(**{"15m": "exhaustion_risk", "5m": "exhaustion_risk"}),
                              po3={}),
            "liquidity_sweep_reversal")


if __name__ == "__main__":
    unittest.main()
