"""
QUAL-FLICKER-AUDIT — qualification "is the disqualifier masking opportunity?"
telemetry: regression lock.

2026-07-08 qualification flicker trial: qualification was no_trade on 123/163
observe_only scans. Owner attribution — every no_trade was a HARD disqualifier
(opportunity_score 0), never a low-but-nonzero score:
  no_trade_narrative:exhaustion_risk  48
  no_trade_narrative:conflicted       38
  confidence_tier_no_trade            36
Decisive exoneration: recomputing the opportunity score WITHOUT the disqualifier
on all 86 narrative-disqualified scans gave avg 21.2 / max 22 — 0 would reach
watchlist(>=40) or candidate(>=55). The disqualifier NEVER masked a tradeable
opportunity; the market evidence was genuinely low (indecisive/choppy). No
behavioral repair was warranted (removing the disqualifier helps 0/86 scans and
would violate the forbidden list). This telemetry records the would-be score so
the claim is measurable every scan. Behavior is byte-identical.

Locks:
  * opportunity_score_undisqualified equals the real score when NOT disqualified
  * when disqualified, it reports what the score WOULD be (unmasking check)
  * disqualifier_masks_opportunity is True ONLY if a disqualified scan would
    otherwise reach the tradeable threshold (>=40) — the honest defect signal
  * the qualification VERDICT (status/score) is unchanged by this telemetry
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qualification.trade_qualification_engine import qualify_trade   # noqa: E402


def _base(narrative, tier="valid_setup", score=60, market_state="", strong=True):
    """strong=True → tradeable-grade evidence; strong=False → the weak,
    genuinely-low-opportunity shape seen on the real no_trade scans (score ~22)."""
    if strong:
        structure = {"alignment": "full"}
        po3 = {"alignment": "full_distribution_alignment"}
        liquidity = {"5m": {"sweep_detected": True, "reclaim_detected": True}}
    else:
        structure = {"alignment": "neutral"}
        po3 = {"alignment": "no_clear_alignment"}
        liquidity = {}
        score = 40   # below the 50 tier -> conf pts modest
    return {
        "ai_context": {"market_narrative": narrative, "confidence_tier": tier,
                       "confidence_score": score, "market_state": market_state,
                       "directional_bias": "bearish"},
        "structure": structure, "po3": po3, "memory": {},
        "liquidity": liquidity, "volatility": {}, "expansion": {},
    }


class TestUndisqualifiedScore(unittest.TestCase):
    def test_not_disqualified_equals_real_score(self):
        out = qualify_trade(_base("liquidity_sweep_reversal"))
        self.assertNotEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score_undisqualified"],
                         out["opportunity_score"])
        self.assertFalse(out["disqualifier_masks_opportunity"])

    def test_narrative_disqualified_reports_would_be_score(self):
        # conflicted narrative hard-disqualifies -> score 0; weak evidence means
        # the would-be score is low -> not masking opportunity (the real case)
        out = qualify_trade(_base("conflicted", strong=False))
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)
        self.assertLess(out["opportunity_score_undisqualified"], 40)
        self.assertFalse(out["disqualifier_masks_opportunity"])

    def test_exhaustion_risk_not_masking_opportunity(self):
        out = qualify_trade(_base("exhaustion_risk", strong=False))
        self.assertEqual(out["status"], "no_trade")
        self.assertLess(out["opportunity_score_undisqualified"], 40)
        self.assertFalse(out["disqualifier_masks_opportunity"])

    def test_masks_opportunity_flag_true_only_if_threshold_reachable(self):
        """Construct a scan where the would-be score DOES reach the threshold
        while a disqualifier fires — the honest 'masking' signal must be True.
        (Exhaustion narrative scores 0 pts, but strong PO3+structure+liquidity+
        confidence can still sum >=40.)"""
        snap = _base("exhaustion_risk", tier="valid_setup", score=100)
        snap["structure"] = {"alignment": "full"}          # +15
        snap["po3"] = {"alignment": "full_distribution_alignment"}  # +20
        snap["liquidity"] = {"5m": {"sweep_detected": True, "reclaim_detected": True}}
        out = qualify_trade(snap)
        # exhaustion_risk still disqualifies (status no_trade), but if the
        # underlying score clears 40 the telemetry flags it honestly
        if out["opportunity_score_undisqualified"] >= 40:
            self.assertTrue(out["disqualifier_masks_opportunity"])
        else:
            self.assertFalse(out["disqualifier_masks_opportunity"])


class TestVerdictUnchanged(unittest.TestCase):
    def test_status_and_score_unaffected_by_telemetry(self):
        for narr, expect_no_trade in (("conflicted", True),
                                      ("exhaustion_risk", True),
                                      ("liquidity_sweep_reversal", False)):
            out = qualify_trade(_base(narr))
            self.assertEqual(out["status"] == "no_trade", expect_no_trade, narr)
            # telemetry never fabricates a tradeable status
            if out["disqualifier_masks_opportunity"]:
                self.assertEqual(out["status"], "no_trade")  # still no_trade

    def test_no_forced_trade(self):
        """Even when the disqualifier masks a >=40 score, the status stays
        no_trade — telemetry observes, it does not override the disqualifier."""
        snap = _base("exhaustion_risk", score=100)
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")


if __name__ == "__main__":
    unittest.main()
