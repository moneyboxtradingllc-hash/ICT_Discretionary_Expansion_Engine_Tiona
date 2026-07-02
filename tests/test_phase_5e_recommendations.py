"""
Phase 5E — Recommendation Engine Tests.
17 tests covering: insufficient sample guard, all rule types, report,
summary, AI input, snapshot store, safety invariants, determinism.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from recommendation_engine.recommendation_rules   import check_all_rules
from recommendation_engine.recommendation_builder import build_recommendations_from_context
from recommendation_engine.recommendation_report  import build_recommendation_report
from recommendation_engine.recommendation_summary import build_recommendation_summary
from ai_layer.ai_input_builder                    import build_compact_ai_input
from live_scan.snapshot_store                     import save_snapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _dim(win_rate: float, sample_size: int, average_r: float = 0.5) -> dict:
    return {"win_rate": win_rate, "sample_size": sample_size, "average_r": average_r}


def _dashboard(
    closed=30,
    win_rate=55.0,
    best_regime="trend_up",
    worst_regime="chop",
    best_regime_wr=70.0,
    worst_regime_wr=35.0,
    best_regime_n=12,
    worst_regime_n=11,
    best_playbook="lsr",
    worst_playbook="chop_trade",
    best_pb_wr=68.0,
    worst_pb_wr=28.0,
    best_pb_n=15,
    worst_pb_n=12,
    ai_helpful_rate=None,
):
    return {
        "closed_trades":   closed,
        "win_rate":        win_rate,
        "best_regime":     best_regime,
        "worst_regime":    worst_regime,
        "regime_metrics": {
            best_regime:  _dim(best_regime_wr,  best_regime_n),
            worst_regime: _dim(worst_regime_wr, worst_regime_n),
        },
        "best_playbook":    best_playbook,
        "worst_playbook":   worst_playbook,
        "playbook_metrics": {
            best_playbook:  _dim(best_pb_wr, best_pb_n),
            worst_playbook: _dim(worst_pb_wr, worst_pb_n),
        },
        "ai_helpful_rate": ai_helpful_rate,
    }


def _ai_feedback(agree_wr=72.0, disagree_wr=43.0, sample=20, helpful=70.0):
    return {
        "sample_size":           sample,
        "agreement_win_rate":    agree_wr,
        "disagreement_win_rate": disagree_wr,
        "ai_helpful_rate":       helpful,
    }


def _memory(quality="useful", n=25, wr=67.0):
    return {
        "memory_quality":      quality,
        "closed_match_count":  n,
        "similar_win_rate":    wr,
    }


def _context(**kw) -> dict:
    return {
        "dashboard":     kw.get("dashboard",    _dashboard()),
        "ai_feedback":   kw.get("ai_feedback",  {}),
        "memory_search": kw.get("memory_search", {}),
    }


def _snapshot(symbol="QQQ"):
    return {
        "symbol":        symbol,
        "session":       "ny_open",
        "qualification": {"status": "candidate", "opportunity_score": 70},
        "playbook":      {"selected_playbook": "lsr", "direction": "bullish"},
        "toolbox":       {"preferred_tool": "bullish_ifvg"},
        "market_regime": {"enabled": True, "regime_label": "trend_up",
                          "regime_family": "trend", "confidence": 65,
                          "volatility_state": "normal", "expansion_state": "neutral"},
        "confidence_fusion": {"mechanical_score": 70},
        "ai_discretionary":  {"ai_confidence": 60},
        "intent_score":      {"gated_score": 70},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Insufficient Sample Guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficientSample(unittest.TestCase):

    def test_01_no_recommendations_when_insufficient_sample(self):
        ctx = _context(dashboard=_dashboard(closed=10))
        recs, notes = check_all_rules(ctx)
        self.assertEqual(recs, [])
        self.assertTrue(any("insufficient" in n.lower() for n in notes))

    def test_01b_threshold_at_exactly_25(self):
        # 24 → insufficient, 25 → allowed
        ctx_24 = _context(dashboard=_dashboard(closed=24))
        ctx_25 = _context(dashboard=_dashboard(closed=25))
        recs_24, _ = check_all_rules(ctx_24)
        recs_25, _ = check_all_rules(ctx_25)
        self.assertEqual(len(recs_24), 0)
        # 25 trades with qualifying dimensions can produce recs
        self.assertIsInstance(recs_25, list)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Regime Rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeRules(unittest.TestCase):

    def test_02_regime_negative_recommendation_generated(self):
        ctx  = _context(dashboard=_dashboard(worst_regime_wr=35.0, worst_regime_n=12))
        recs, _ = check_all_rules(ctx)
        regime_recs = [r for r in recs if r["type"] == "regime" and "chop" in r["finding"].lower()]
        self.assertTrue(len(regime_recs) >= 1)
        self.assertEqual(regime_recs[0]["status"], "human_review_required")

    def test_03_regime_positive_recommendation_generated(self):
        ctx  = _context(dashboard=_dashboard(best_regime_wr=72.0, best_regime_n=15))
        recs, _ = check_all_rules(ctx)
        pos_recs = [r for r in recs if r["type"] == "regime" and "outperform" in r["finding"].lower()]
        self.assertTrue(len(pos_recs) >= 1)
        self.assertIn("trend", pos_recs[0]["finding"].lower())

    def test_02b_no_regime_rec_when_samples_below_threshold(self):
        ctx = _context(dashboard=_dashboard(worst_regime_wr=20.0, worst_regime_n=5))
        recs, _ = check_all_rules(ctx)
        regime_recs = [r for r in recs if r["type"] == "regime"
                       and "chop" in r.get("finding", "").lower()]
        self.assertEqual(len(regime_recs), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Playbook Rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlaybookRules(unittest.TestCase):

    def test_04_playbook_positive_recommendation_generated(self):
        ctx  = _context(dashboard=_dashboard(best_pb_wr=68.0, best_pb_n=15))
        recs, _ = check_all_rules(ctx)
        pb_recs = [r for r in recs if r["type"] == "playbook"
                   and "strongest" in r["finding"].lower()]
        self.assertTrue(len(pb_recs) >= 1)
        self.assertIn("lsr", pb_recs[0]["finding"].lower())

    def test_04b_no_rec_when_best_playbook_wr_below_threshold(self):
        ctx  = _context(dashboard=_dashboard(best_pb_wr=55.0, best_pb_n=15))
        recs, _ = check_all_rules(ctx)
        pb_pos = [r for r in recs if r["type"] == "playbook"
                  and "strongest" in r.get("finding", "").lower()]
        self.assertEqual(len(pb_pos), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AI Rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiRules(unittest.TestCase):

    def test_05_ai_recommendation_generated_on_agreement_edge(self):
        ctx  = _context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(agree_wr=72.0, disagree_wr=43.0, sample=20),
        )
        recs, _ = check_all_rules(ctx)
        ai_recs = [r for r in recs if r["type"] == "ai"]
        self.assertTrue(len(ai_recs) >= 1)

    def test_05b_no_ai_rec_when_gap_below_threshold(self):
        ctx = _context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(agree_wr=55.0, disagree_wr=50.0, sample=20),
        )
        recs, _ = check_all_rules(ctx)
        ai_recs = [r for r in recs if r["type"] == "ai"
                   and "agreement" in r.get("finding", "").lower()]
        self.assertEqual(len(ai_recs), 0)

    def test_05c_no_ai_rec_with_insufficient_ai_sample(self):
        ctx = _context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(agree_wr=80.0, disagree_wr=30.0, sample=5),
        )
        recs, _ = check_all_rules(ctx)
        ai_recs = [r for r in recs if r["type"] == "ai"]
        self.assertEqual(len(ai_recs), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Memory Rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryRules(unittest.TestCase):

    def test_06_memory_recommendation_generated_when_useful(self):
        ctx  = _context(
            dashboard=_dashboard(),
            memory_search=_memory(quality="useful", n=25, wr=67.0),
        )
        recs, _ = check_all_rules(ctx)
        mem_recs = [r for r in recs if r["type"] == "memory"]
        self.assertTrue(len(mem_recs) >= 1)

    def test_06b_no_memory_rec_when_quality_not_useful(self):
        for q in ["none", "thin", "developing"]:
            ctx = _context(
                dashboard=_dashboard(),
                memory_search=_memory(quality=q, n=25, wr=67.0),
            )
            recs, _ = check_all_rules(ctx)
            mem_recs = [r for r in recs if r["type"] == "memory"]
            self.assertEqual(len(mem_recs), 0, f"quality={q}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Report and Summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportAndSummary(unittest.TestCase):

    def _full_context(self):
        return _context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(),
            memory_search=_memory(),
        )

    def test_07_report_builds_correctly(self):
        result = build_recommendations_from_context(self._full_context())
        report = build_recommendation_report(result)
        self.assertIn("recommendation_quality", report)
        self.assertIn("recommendation_count",   report)
        self.assertIn("highest_priority",       report)
        self.assertIn("recommendations",        report)
        self.assertEqual(report["authority_level"],     "observe_only")
        self.assertEqual(report["confidence_modifier"], 0)

    def test_08_summary_builds_correctly(self):
        result  = build_recommendations_from_context(self._full_context())
        summary = build_recommendation_summary(result)
        self.assertIn("recommendation_count",   summary)
        self.assertIn("top_recommendation",     summary)
        self.assertIn("recommendation_quality", summary)
        self.assertEqual(summary["authority_level"],     "observe_only")
        self.assertEqual(summary["confidence_modifier"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Snapshot and AI Input
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):

    def _snap_with_recs(self):
        snap = _snapshot()
        result = build_recommendations_from_context(_context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(),
        ))
        snap["recommendations"] = build_recommendation_summary(result)
        return snap

    def test_09_snapshot_includes_recommendations(self):
        import live_scan.snapshot_store as ss_mod
        snap = self._snap_with_recs()
        # DECON-3: save_snapshot is post-runtime-only — model a resolved runtime
        snap.update({"decision_authority": {}, "execution_gate": {},
                     "paper_execution": {}, "position_monitor": {},
                     "trade_reconciliation": {}})
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(ss_mod, "STORE_DIR", tmpdir):
                fpath = save_snapshot(snap, "QQQ")
            with open(fpath) as f:
                saved = json.load(f)
        self.assertIn("recommendations", saved)
        rec = saved["recommendations"]
        self.assertEqual(rec["authority_level"],     "observe_only")
        self.assertEqual(rec["confidence_modifier"], 0)
        self.assertIn("recommendation_count",        rec)

    def test_10_ai_input_includes_recommendations(self):
        snap = self._snap_with_recs()
        ai_in = build_compact_ai_input(snap)
        self.assertIn("recommendations", ai_in)
        rec = ai_in["recommendations"]
        self.assertEqual(rec["authority_level"],     "observe_only")
        self.assertIn("recommendation_count",        rec)
        self.assertIn("top_recommendation",          rec)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Safety Invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def _full_result(self):
        return build_recommendations_from_context(_context(
            dashboard=_dashboard(),
            ai_feedback=_ai_feedback(),
            memory_search=_memory(),
        ))

    def test_11_authority_level_always_observe_only(self):
        result  = self._full_result()
        summary = build_recommendation_summary(result)
        report  = build_recommendation_report(result)
        self.assertEqual(result["authority_level"],  "observe_only")
        self.assertEqual(summary["authority_level"], "observe_only")
        self.assertEqual(report["authority_level"],  "observe_only")
        for rec in result["recommendations"]:
            self.assertEqual(rec["authority_level"], "observe_only")

    def test_12_confidence_modifier_always_zero(self):
        result  = self._full_result()
        summary = build_recommendation_summary(result)
        report  = build_recommendation_report(result)
        self.assertEqual(result["confidence_modifier"],  0)
        self.assertEqual(summary["confidence_modifier"], 0)
        self.assertEqual(report["confidence_modifier"],  0)
        for rec in result["recommendations"]:
            self.assertEqual(rec["confidence_modifier"], 0)

    def test_13_no_execution_fields_in_recommendations(self):
        result = self._full_result()
        forbidden = {
            "allow_execution", "trade_authorized", "gate_status",
            "risk_multiplier", "position_size", "confidence_modifier_delta",
        }
        self.assertFalse(forbidden & set(result.keys()))
        for rec in result["recommendations"]:
            self.assertFalse(forbidden & set(rec.keys()))

    def test_14_no_decision_authority_change(self):
        result = self._full_result()
        self.assertNotIn("decision", result)
        self.assertNotIn("trade_authorized", result)

    def test_15_no_risk_governor_change(self):
        result = self._full_result()
        self.assertNotIn("risk_tier", result)
        self.assertNotIn("risk_multiplier", result)
        self.assertNotIn("position_size", result)

    def test_16_recommendations_are_deterministic(self):
        """Same inputs must produce identical outputs every time."""
        ctx  = _context(dashboard=_dashboard(), ai_feedback=_ai_feedback())
        out1 = build_recommendations_from_context(ctx)
        out2 = build_recommendations_from_context(ctx)
        self.assertEqual(out1["recommendation_count"], out2["recommendation_count"])
        for r1, r2 in zip(out1["recommendations"], out2["recommendations"]):
            self.assertEqual(r1["type"],       r2["type"])
            self.assertEqual(r1["finding"],    r2["finding"])
            self.assertEqual(r1["severity"],   r2["severity"])

    def test_17_all_statuses_are_human_review_required(self):
        result = self._full_result()
        for rec in result["recommendations"]:
            self.assertEqual(rec["status"], "human_review_required")


if __name__ == "__main__":
    unittest.main()
