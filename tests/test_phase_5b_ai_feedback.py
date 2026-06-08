"""
Phase 5B — AI Outcome Feedback Tests.
17 tests covering: extraction, scoring, aggregation, correlation, safety invariants.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.trade_journal        as tj_mod
import paper_execution.trade_reconciliation as recon_mod

from ai_feedback.ai_feedback_builder  import build_ai_feedback_from_snapshot
from ai_feedback.ai_outcome_scorer    import score_ai_outcome
from ai_feedback.ai_feedback_summary  import build_ai_feedback_summary
from paper_execution.trade_journal    import make_record, append_trade, load_today_trades
from experience_intelligence.experience_correlation import _DIMENSIONS


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _snapshot(
    ai_dir="bullish", ai_conf=60,
    agree_pb=True, agree_risk=True,
    ai_mode="external", fallback=False,
    model="gpt-5-mini",
    mech_score=52, fusion_status="agreement",
    bull=70, bear=20, neut=10,
    stance="prepare_long", dom="bullish",
):
    return {
        "ai_discretionary": {
            "ai_direction":              ai_dir,
            "ai_confidence":             ai_conf,
            "agreement_with_playbook":   agree_pb,
            "agreement_with_risk":       agree_risk,
            "ai_mode":                   ai_mode,
            "fallback_used":             fallback,
            "model":                     model,
        },
        "confidence_fusion": {
            "mechanical_score":    mech_score,
            "ai_confidence":       ai_conf,
            "fusion_status":       fusion_status,
        },
        "ai_debate": {
            "bullish_thesis": {"case_strength": bull},
            "bearish_thesis": {"case_strength": bear},
            "neutral_thesis": {"case_strength": neut},
            "final_verdict":  {
                "dominant_thesis":      dom,
                "recommended_stance":   stance,
            },
        },
    }


def _trade_record(
    side="buy", realized_r=1.0,
    agree_pb=True, agree_risk=True,
    ai_dir="bullish", ai_conf=60,
    fusion_st="agreement",
    order_status="closed",
    ai_value_label="unknown",
):
    return {
        "order_status":                    order_status,
        "realized_r":                      realized_r,
        "side":                            side,
        "intent_type":                     "long" if side == "buy" else "short",
        "ai_direction_at_entry":           ai_dir,
        "ai_confidence_at_entry":          ai_conf,
        "ai_agreement_with_playbook":      agree_pb,
        "ai_agreement_with_risk":          agree_risk,
        "confidence_fusion_status_at_entry": fusion_st,
        "ai_debate_recommended_stance":    "prepare_long",
        "ai_value_label":                  ai_value_label,
    }


def _journal_trade(**kw):
    rec = make_record(
        trade_id="PT_QQQ_T1", symbol="QQQ",
        intent_id="I1", intent_type="long",
        side="buy", qty=2,
        entry_reference=479.0, stop_reference=476.0,
        risk_per_share=3.0, risk_dollars=300.0,
        order_status="submitted", alpaca_order_id="ALPA_001",
        reason="test",
        ai_feedback=kw.get("ai_feedback"),
    )
    rec.update(kw.get("updates", {}))
    return rec


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AI Feedback Builder
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiFeedbackBuilder(unittest.TestCase):

    def test_01_extracts_feedback_from_snapshot(self):
        snap   = _snapshot()
        result = build_ai_feedback_from_snapshot(snap)
        self.assertEqual(result["ai_direction_at_entry"],  "bullish")
        self.assertEqual(result["ai_confidence_at_entry"], 60)
        self.assertTrue(result["ai_agreement_with_playbook"])
        self.assertTrue(result["ai_agreement_with_risk"])
        self.assertTrue(result["ai_external_used"])
        self.assertFalse(result["ai_fallback_used"])
        self.assertEqual(result["ai_model_used"],              "gpt-5-mini")
        self.assertEqual(result["mechanical_confidence_at_entry"], 52)
        self.assertEqual(result["confidence_fusion_status_at_entry"], "agreement")
        self.assertEqual(result["ai_debate_dominant_thesis"],  "bullish")
        self.assertEqual(result["ai_debate_recommended_stance"], "prepare_long")

    def test_02_missing_ai_fields_default_safely(self):
        result = build_ai_feedback_from_snapshot({})
        # direction defaults to "neutral" when no ai_discretionary data present
        self.assertEqual(result["ai_direction_at_entry"],  "neutral")
        self.assertEqual(result["ai_confidence_at_entry"], 0)
        self.assertIsNone(result["ai_agreement_with_playbook"])
        self.assertFalse(result["ai_external_used"])
        self.assertEqual(result["authority_level"],     "observe_only")
        self.assertEqual(result["confidence_modifier"], 0)

    def test_03_internal_mode_not_flagged_as_external(self):
        snap   = _snapshot(ai_mode="internal")
        result = build_ai_feedback_from_snapshot(snap)
        self.assertFalse(result["ai_external_used"])

    def test_04_hybrid_mode_flagged_as_external(self):
        snap   = _snapshot(ai_mode="hybrid")
        result = build_ai_feedback_from_snapshot(snap)
        self.assertTrue(result["ai_external_used"])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AI Outcome Scorer
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiOutcomeScorer(unittest.TestCase):

    def test_05_winning_trade_ai_agreement_is_helpful(self):
        t = _trade_record(side="buy", realized_r=1.5, agree_pb=True, ai_dir="bullish")
        r = score_ai_outcome(t)
        self.assertTrue(r["scored"])
        self.assertEqual(r["ai_value_label"], "helpful")

    def test_06_losing_trade_ai_agreement_is_harmful(self):
        t = _trade_record(side="buy", realized_r=-0.8, agree_pb=True, ai_dir="bullish")
        r = score_ai_outcome(t)
        self.assertTrue(r["scored"])
        self.assertEqual(r["ai_value_label"], "harmful")

    def test_07_winning_trade_ai_disagreement_is_harmful(self):
        t = _trade_record(side="buy", realized_r=1.2, agree_pb=False, ai_dir="bearish")
        r = score_ai_outcome(t)
        self.assertTrue(r["scored"])
        self.assertEqual(r["ai_value_label"], "harmful")

    def test_08_losing_trade_ai_disagreement_is_helpful(self):
        t = _trade_record(side="buy", realized_r=-1.0, agree_pb=False, ai_dir="bearish")
        r = score_ai_outcome(t)
        self.assertTrue(r["scored"])
        self.assertEqual(r["ai_value_label"], "helpful")

    def test_09_breakeven_trade_is_neutral(self):
        t = _trade_record(side="buy", realized_r=0.0, agree_pb=True)
        r = score_ai_outcome(t)
        self.assertTrue(r["scored"])
        self.assertEqual(r["ai_value_label"], "neutral")

    def test_10_open_trade_returns_unknown(self):
        t = _trade_record(order_status="submitted", realized_r=None)
        r = score_ai_outcome(t)
        self.assertFalse(r["scored"])
        self.assertEqual(r["ai_value_label"], "unknown")

    def test_11_missing_agree_pb_returns_unknown(self):
        t = _trade_record(realized_r=1.0, agree_pb=True)
        t["ai_agreement_with_playbook"] = None   # override to missing
        r = score_ai_outcome(t)
        self.assertFalse(r["scored"])
        self.assertEqual(r["ai_value_label"], "unknown")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AI Feedback Summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiFeedbackSummary(unittest.TestCase):

    def _make_trades(self, n, value_label, agree_pb, realized_r, side="buy"):
        return [
            _trade_record(
                side=side, realized_r=realized_r,
                agree_pb=agree_pb, ai_value_label=value_label
            )
            for _ in range(n)
        ]

    def test_12_summary_aggregates_helpful_harmful_counts(self):
        trades  = (
            self._make_trades(4, "helpful", True,  1.0)
            + self._make_trades(2, "harmful", True, -1.0)
        )
        summary = build_ai_feedback_summary(trades)
        self.assertEqual(summary["ai_helpful_count"], 4)
        self.assertEqual(summary["ai_harmful_count"], 2)
        self.assertEqual(summary["sample_size"],      6)

    def test_13_agreement_win_rate_calculated_correctly(self):
        # 5 agree+win, 5 agree+loss → 50% agreement win rate
        trades = (
            self._make_trades(5, "helpful", True,  1.0)   # agree wins
            + self._make_trades(5, "harmful", True, -1.0)  # agree losses
        )
        summary = build_ai_feedback_summary(trades)
        self.assertIsNotNone(summary["agreement_win_rate"])
        self.assertAlmostEqual(summary["agreement_win_rate"], 50.0, places=0)

    def test_14_disagreement_win_rate_calculated_correctly(self):
        # 4 disagree+win, 2 disagree+loss → 66.7% disagreement win rate
        trades = (
            self._make_trades(4, "harmful", False, 1.0)   # disagree+win
            + self._make_trades(2, "helpful", False, -1.0) # disagree+loss
        )
        summary = build_ai_feedback_summary(trades)
        self.assertIsNotNone(summary["disagreement_win_rate"])
        self.assertAlmostEqual(summary["disagreement_win_rate"], 66.7, places=0)

    def test_15_external_ai_win_rate(self):
        # 3 external trades: 2 win, 1 loss
        trades = [
            {**_trade_record(realized_r=1.0,  agree_pb=True, ai_dir="bullish",
                              ai_value_label="helpful"), "ai_external_used": True},
            {**_trade_record(realized_r=1.0,  agree_pb=True, ai_dir="bullish",
                              ai_value_label="helpful"), "ai_external_used": True},
            {**_trade_record(realized_r=-1.0, agree_pb=True, ai_dir="bullish",
                              ai_value_label="harmful"), "ai_external_used": True},
        ]
        summary = build_ai_feedback_summary(trades)
        self.assertIsNotNone(summary["external_ai_win_rate"])
        self.assertAlmostEqual(summary["external_ai_win_rate"], 66.7, places=0)

    def test_16_fallback_ai_win_rate(self):
        trades = [
            {**_trade_record(realized_r=1.0,  ai_value_label="helpful"), "ai_fallback_used": True},
            {**_trade_record(realized_r=-1.0, ai_value_label="harmful"), "ai_fallback_used": True},
            {**_trade_record(realized_r=-1.0, ai_value_label="harmful"), "ai_fallback_used": True},
        ]
        summary = build_ai_feedback_summary(trades)
        self.assertIsNotNone(summary["fallback_ai_win_rate"])
        self.assertAlmostEqual(summary["fallback_ai_win_rate"], 33.3, places=0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Journal and Correlation Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestJournalAndCorrelation(unittest.TestCase):

    def _run_with_tmp(self, fn):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        try:
            fn(tmp)
        finally:
            import os
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_17_closed_trade_journal_gets_ai_feedback_fields(self):
        fb = build_ai_feedback_from_snapshot(_snapshot())

        def fn(tmp):
            with patch.object(tj_mod, "_journal_filepath", return_value=tmp):
                rec = make_record(
                    trade_id="T1", symbol="QQQ",
                    intent_id="I1", intent_type="long",
                    side="buy", qty=2,
                    entry_reference=479.0, stop_reference=476.0,
                    risk_per_share=3.0, risk_dollars=300.0,
                    order_status="submitted", alpaca_order_id="ALPA_001",
                    reason="test", ai_feedback=fb,
                )
                append_trade(rec, "QQQ")
                trades = load_today_trades("QQQ")
            self.assertEqual(len(trades), 1)
            t = trades[0]
            self.assertEqual(t["ai_direction_at_entry"],  "bullish")
            self.assertEqual(t["ai_confidence_at_entry"], 60)
            self.assertTrue(t["ai_agreement_with_playbook"])
            self.assertFalse(t["ai_outcome_scored"])   # not yet scored

        self._run_with_tmp(fn)

    def test_18_ai_feedback_dimensions_in_correlation(self):
        required = {
            "ai_agreement_with_playbook",
            "ai_agreement_with_risk",
            "ai_debate_dominant_thesis",
            "ai_debate_recommended_stance",
            "confidence_fusion_status_at_entry",
            "ai_value_label",
        }
        self.assertTrue(required.issubset(_DIMENSIONS))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Safety Invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def test_19_builder_authority_always_observe_only(self):
        for snap in [{}, _snapshot()]:
            r = build_ai_feedback_from_snapshot(snap)
            self.assertEqual(r["authority_level"],     "observe_only")
            self.assertEqual(r["confidence_modifier"], 0)

    def test_20_scorer_authority_always_observe_only(self):
        for t in [
            {},
            _trade_record(realized_r=1.0, agree_pb=True),
            _trade_record(realized_r=-1.0, agree_pb=False),
        ]:
            r = score_ai_outcome(t)
            self.assertEqual(r["authority_level"],     "observe_only")
            self.assertEqual(r["confidence_modifier"], 0)

    def test_21_summary_authority_always_observe_only(self):
        for trades in [[], [_trade_record(realized_r=1.0, agree_pb=True)]]:
            s = build_ai_feedback_summary(trades)
            self.assertEqual(s["authority_level"],     "observe_only")
            self.assertEqual(s["confidence_modifier"], 0)
            self.assertTrue(s["enabled"])

    def test_22_no_execution_behavior_change(self):
        """AI feedback fields must not be confidence_modifier or affect decisions."""
        fb = build_ai_feedback_from_snapshot(_snapshot())
        self.assertEqual(fb["confidence_modifier"], 0)
        self.assertNotIn("allow_execution", fb)
        self.assertNotIn("trade_authorized", fb)
        self.assertNotIn("gate_status",      fb)
        self.assertNotIn("risk_tier",        fb)

    def test_23_scorer_never_raises(self):
        bad_inputs = [None, {}, {"realized_r": None, "order_status": "closed"},
                      {"order_status": "closed", "realized_r": 1.0}]
        for inp in bad_inputs:
            try:
                r = score_ai_outcome(inp)
                self.assertIn("ai_value_label", r)
                self.assertEqual(r["confidence_modifier"], 0)
            except Exception as exc:
                self.fail(f"score_ai_outcome raised on {inp!r}: {exc}")


if __name__ == "__main__":
    unittest.main()
