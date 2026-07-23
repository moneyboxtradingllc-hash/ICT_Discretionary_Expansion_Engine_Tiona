"""
NARRATIVE-AUDIT — narrative decision-reason transparency: regression lock.

2026-07-08 narrative trial: the mechanical market_narrative flickers
(exhaustion_risk / conflicted / liquidity_sweep_reversal ...) across the
session. Definitive test — 54 of 55 narrative transitions had a genuinely
CHANGED market-evidence summary: the narrative faithfully tracks perception, it
does NOT manufacture states from internal heuristics/cache/state-resets. The
residual flicker originates upstream in the expansion-exhaustion perception
(threshold-boundary state flips) and is outcome-neutral (the prior mission
proved opportunity score <=22 on all no_trade scans regardless of narrative).

Repair: AUDIT-TRUTH only (option G) — record WHICH cascade rule + timeframe
produced each narrative, closing the attribution gap that forced parsing a
truncated text summary. Narrative output is byte-identical.

Locks:
  * narrative_reason mirrors _market_narrative's cascade EXACTLY (they never
    disagree on which branch fired) for every rule
  * the driving timeframe is recorded for the sweep and exhaustion overrides
  * build_narrative output narrative_reason is present and behavior-neutral
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_layer.narrative_builder import (                        # noqa: E402
    _market_narrative, _narrative_reason, build_narrative,
)

_RULE_TO_NARR = {
    "sweep_reclaim(rule1)":        "liquidity_sweep_reversal",
    "exhaustion_override(rule2)":  "exhaustion_risk",
    "dangerous_state(rule3)":      "conflicted",
    "po3_full_distribution_alignment": "distribution_in_progress",
    "po3_accumulation_building":   "accumulation_before_expansion",
    "bias_conflicted":             "conflicted",
}


class TestReasonMirrorsCascade(unittest.TestCase):
    def _check(self, bias, state, structure, liquidity, expansion, po3):
        narr = _market_narrative(bias, state, structure, liquidity, expansion, po3)
        reason = _narrative_reason(bias, state, structure, liquidity, expansion, po3)
        return narr, reason

    def test_sweep_rule(self):
        liq = {"5m": {"sweep_detected": True, "reclaim_detected": True}}
        narr, r = self._check("neutral", "ranging", {}, liq, {}, {})
        self.assertEqual(narr, "liquidity_sweep_reversal")
        self.assertEqual(r["rule"], "sweep_reclaim(rule1)")
        self.assertEqual(r["driver_tf"], "5m")

    def test_exhaustion_rule_records_tf(self):
        # Operator ruling 2026-07-23: exhaustion needs >= 2 of 15m/5m/3m — a lone
        # timeframe may no longer veto. Two still trigger rule2 and record both.
        exp = {"5m": {"state": "exhaustion_risk"}, "3m": {"state": "exhaustion_risk"}}
        narr, r = self._check("bearish", "trending", {}, {}, exp, {})
        self.assertEqual(narr, "exhaustion_risk")
        self.assertEqual(r["rule"], "exhaustion_override(rule2)")
        self.assertEqual(r["driver_tf"], "5m,3m")

    def test_single_timeframe_exhaustion_does_not_veto(self):
        # The ruling itself: one timeframe cannot stand the bot down, and the
        # reason must agree with the narrative (no exhaustion_override).
        for tf in ("15m", "5m", "3m"):
            with self.subTest(tf=tf):
                exp = {tf: {"state": "exhaustion_risk"}}
                narr, r = self._check("bearish", "trending", {}, {}, exp, {})
                self.assertNotEqual(narr, "exhaustion_risk")
                self.assertNotEqual(r["rule"], "exhaustion_override(rule2)")

    def test_dangerous_rule(self):
        narr, r = self._check("neutral", "dangerous", {}, {}, {}, {})
        self.assertEqual(narr, "conflicted")
        self.assertEqual(r["rule"], "dangerous_state(rule3)")

    def test_po3_full_distribution(self):
        narr, r = self._check("neutral", "trending", {}, {}, {},
                              {"alignment": "full_distribution_alignment"})
        self.assertEqual(narr, "distribution_in_progress")
        self.assertEqual(r["rule"], "po3_full_distribution_alignment")

    def test_base_directional(self):
        narr, r = self._check("bearish", "trending", {}, {}, {}, {})
        self.assertEqual(narr, "bearish_continuation")
        self.assertEqual(r["rule"], "base_directional")

    def test_conflicted_bias(self):
        narr, r = self._check("conflicted", "ranging", {}, {}, {}, {})
        self.assertEqual(narr, "conflicted")
        self.assertEqual(r["rule"], "bias_conflicted")

    def test_cascade_priority_sweep_over_exhaustion(self):
        # sweep (rule1) must win over exhaustion (rule2). Uses TWO exhaustion
        # timeframes so rule2 genuinely fires — with one it would not trigger
        # at all and this would prove nothing.
        liq = {"5m": {"sweep_detected": True, "reclaim_detected": True}}
        exp = {"5m": {"state": "exhaustion_risk"}, "3m": {"state": "exhaustion_risk"}}
        narr, r = self._check("bearish", "trending", {}, liq, exp, {})
        self.assertEqual(narr, "liquidity_sweep_reversal")
        self.assertEqual(r["rule"], "sweep_reclaim(rule1)")

    def test_reason_consistent_with_narrative_across_matrix(self):
        """For a matrix of inputs, whenever the reason maps to a specific
        narrative, _market_narrative must produce that narrative."""
        states = ["trending", "ranging", "dangerous", "expanding", ""]
        biases = ["bullish", "bearish", "conflicted", "neutral"]
        for st in states:
            for b in biases:
                for exh in ({},
                            {"5m": {"state": "exhaustion_risk"}},                  # 1 TF: must NOT veto
                            {"5m": {"state": "exhaustion_risk"},                    # 2 TFs: must veto
                             "3m": {"state": "exhaustion_risk"}}):
                    for al in ("", "full_distribution_alignment", "accumulation_building"):
                        narr = _market_narrative(b, st, {}, {}, exh, {"alignment": al})
                        r = _narrative_reason(b, st, {}, {}, exh, {"alignment": al})
                        exp_narr = _RULE_TO_NARR.get(r["rule"])
                        if exp_narr is not None:
                            self.assertEqual(narr, exp_narr,
                                             f"{b}/{st}/{exh}/{al}: reason={r['rule']} narr={narr}")


class TestBuildNarrativeSurfacesReason(unittest.TestCase):
    def test_reason_in_output(self):
        # >= 2 timeframes required (operator ruling 2026-07-23).
        out = build_narrative({}, {}, {"5m": {"state": "exhaustion_risk"},
                                       "3m": {"state": "exhaustion_risk"}},
                              {}, {}, "ny_open", {})
        self.assertEqual(out["market_narrative"], "exhaustion_risk")
        self.assertEqual(out["narrative_reason"], "exhaustion_override(rule2)")
        self.assertEqual(out["narrative_driver_tf"], "5m,3m")

    def test_output_still_has_all_legacy_keys(self):
        out = build_narrative({}, {}, {}, {}, {}, "ny_open", {})
        for k in ("market_narrative", "market_state", "directional_bias",
                  "trade_personality", "coherence", "warnings"):
            self.assertIn(k, out)


if __name__ == "__main__":
    unittest.main()
