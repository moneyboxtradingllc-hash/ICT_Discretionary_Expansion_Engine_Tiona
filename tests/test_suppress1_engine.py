"""
SUPPRESS-1 — Suppression Cost Engine regression lock.

Blocked trades are not dead — they are unrealized evidence.

TEST A: blocked trade registers (owners + reasons + real price plan)
TEST B: shadow outcome resolves TARGET  -> false_suppression, cost +TP_R
TEST C: shadow outcome resolves STOP    -> correct_suppression, cost -1R
TEST D: neutral outcome resolves at session end (triggered, neither hit)
TEST E: expired suppression resolves (entry never triggered)
TEST F: false suppression increments the right buckets
TEST G: correct suppression increments the right buckets
TEST H: adaptive memory receives suppression evidence (policy report),
        with ZERO effect on policy flags

All state in temp dirs — never live adaptive memory.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.suppression_cost_engine import (            # noqa: E402
    register_blocked_candidate, resolve_shadow_outcome, score_suppression,
    track_suppression, load_open_suppressions, load_suppression_metrics,
    get_suppression_stats,
    OUTCOME_CORRECT, OUTCOME_FALSE, OUTCOME_NEUTRAL, OUTCOME_EXPIRED,
)
from adaptive_learning.adaptive_policy_engine import (              # noqa: E402
    generate_adaptive_policy_report,
)

_BLOCKS = [{"layer": "adaptive_live_authority",
            "reason": "session(morning): weak", "field": "adaptive_block"},
           {"layer": "risk_governor", "reason": "blocked: qualification watchlist",
            "field": "risk.blocks"}]


def _snap(ts="2026-07-06T10:00:00", high=701.0, low=699.5, close=700.2,
          entry=700.0, stop=698.0, **over):
    """Blocked-opportunity snapshot: bullish fvg plan entry 700 / stop 698
    (risk 2.0 -> target 704 at TP_R=2)."""
    snap = {
        "timestamp": ts,
        "session": "morning",
        "qualification": {"status": "qualified"},
        "decision_authority": {"decision": "prepare_long", "direction": "bullish"},
        "playbook": {"selected_playbook": "sweep_reversal"},
        "market_regime": {"regime_family": "trend", "volatility_state": "normal"},
        "toolbox": {"preferred_tool": "bullish_fvg", "tool_candidates": [{
            "tool": "bullish_fvg",
            "price_level": {"midpoint": entry, "invalidation_level": stop},
        }]},
        "trade_intent": {"intent_created": False},
        "paper_execution": {"status": "skipped", "reason": "adaptive: soft veto"},
        "confidence_fusion": {"combined_confidence": 58},
        "timeframes": {"1m": {"last_candle": {
            "high": high, "low": low, "close": close, "timestamp": ts}}},
    }
    snap.update(over)
    return snap


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ.pop("TAKE_PROFIT_R", None)

    def _register(self, snap=None):
        return register_blocked_candidate(snap or _snap(), "QQQ", _BLOCKS,
                                          base_dir=self._tmp)


class TestA_Registration(_Sandbox):
    def test_blocked_trade_registers_with_full_evidence(self):
        res = self._register()
        self.assertTrue(res["registered"])
        recs = load_open_suppressions("QQQ", base_dir=self._tmp)
        rec = list(recs.values())[0]
        self.assertEqual(rec["direction"], "bullish")
        self.assertEqual(rec["entry"], 700.0)
        self.assertEqual(rec["stop"], 698.0)
        self.assertEqual(rec["target"], 704.0)           # 2R at TP_R=2
        self.assertIn("adaptive_live_authority", rec["block_owners"])
        self.assertIn("risk_governor", rec["block_owners"])
        self.assertTrue(rec["suppression_id"].startswith("SUP_QQQ_"))
        self.assertEqual(rec["dimensions"]["session"], "morning")

    def test_same_setup_dedupes_and_counts(self):
        self._register()
        res2 = self._register()
        self.assertFalse(res2["registered"])
        self.assertEqual(res2["reason"], "already_open")
        rec = list(load_open_suppressions("QQQ", base_dir=self._tmp).values())[0]
        self.assertEqual(rec["times_blocked"], 2)

    def test_no_registration_without_blocks_or_plan_or_opportunity(self):
        self.assertFalse(register_blocked_candidate(
            _snap(), "QQQ", [], base_dir=self._tmp)["registered"])
        broken = _snap()
        broken["toolbox"]["tool_candidates"][0]["price_level"] = {}
        broken["trade_intent"] = {}
        self.assertEqual(self._register(broken)["reason"], "no_complete_price_plan")
        dead = _snap(qualification={"status": "no_trade"},
                     decision_authority={"decision": "stand_down"})
        self.assertEqual(self._register(dead)["reason"], "no_real_opportunity")

    def test_submitted_trade_never_registers(self):
        snap = _snap(paper_execution={"status": "submitted"})
        self.assertEqual(self._register(snap)["reason"], "trade_submitted")


class TestB_TargetResolution(_Sandbox):
    def test_target_hit_is_false_suppression(self):
        self._register()
        # trigger: price dips to entry
        resolve_shadow_outcome(_snap(ts="2026-07-06T10:05:00",
                                     high=700.5, low=699.9, close=700.1),
                               "QQQ", base_dir=self._tmp)
        # rally through target 704
        resolved = resolve_shadow_outcome(
            _snap(ts="2026-07-06T11:00:00", high=704.5, low=701.0, close=704.2),
            "QQQ", base_dir=self._tmp)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["shadow_outcome"], OUTCOME_FALSE)
        self.assertEqual(resolved[0]["suppression_cost"], 2.0)   # missed +2R
        self.assertEqual(load_open_suppressions("QQQ", base_dir=self._tmp), {})


class TestC_StopResolution(_Sandbox):
    def test_stop_hit_is_correct_suppression(self):
        self._register()
        resolved = resolve_shadow_outcome(
            _snap(ts="2026-07-06T10:30:00", high=700.2, low=697.5, close=697.8),
            "QQQ", base_dir=self._tmp)   # triggers at 700 and stops at 698
        self.assertEqual(resolved[0]["shadow_outcome"], OUTCOME_CORRECT)
        self.assertEqual(resolved[0]["suppression_cost"], -1.0)  # 1R avoided

    def test_ambiguous_candle_resolves_stop_first(self):
        self._register()
        resolved = resolve_shadow_outcome(
            _snap(ts="2026-07-06T10:30:00", high=705.0, low=697.0, close=701.0),
            "QQQ", base_dir=self._tmp)   # spans stop AND target
        self.assertEqual(resolved[0]["shadow_outcome"], OUTCOME_CORRECT,
                         "conservative fill: stop must win ambiguous candles")


class TestD_NeutralResolution(_Sandbox):
    def test_triggered_but_unresolved_settles_neutral_at_session_end(self):
        self._register()
        resolve_shadow_outcome(_snap(ts="2026-07-06T10:05:00",
                                     high=700.4, low=699.8, close=700.4),
                               "QQQ", base_dir=self._tmp)      # triggered
        resolved = resolve_shadow_outcome(
            _snap(ts="2026-07-07T09:35:00"), "QQQ", base_dir=self._tmp)
        self.assertEqual(resolved[0]["shadow_outcome"], OUTCOME_NEUTRAL)
        self.assertAlmostEqual(resolved[0]["suppression_cost"], 0.2, places=4)


class TestE_ExpiredResolution(_Sandbox):
    def test_never_triggered_expires_costless(self):
        self._register(_snap(high=705.0, low=702.0, close=703.0))  # never dips to 700
        resolved = resolve_shadow_outcome(
            _snap(ts="2026-07-07T09:35:00"), "QQQ", base_dir=self._tmp)
        self.assertEqual(resolved[0]["shadow_outcome"], OUTCOME_EXPIRED)
        self.assertEqual(resolved[0]["suppression_cost"], 0.0)


class TestFG_MetricsBuckets(_Sandbox):
    def _run_outcome(self, candle_kwargs):
        self._register()
        resolve_shadow_outcome(_snap(ts="2026-07-06T10:30:00", **candle_kwargs),
                               "QQQ", base_dir=self._tmp)

    def test_F_false_suppression_increments_buckets(self):
        self._run_outcome({"high": 700.2, "low": 699.9, "close": 700.0})  # trigger
        resolve_shadow_outcome(_snap(ts="2026-07-06T11:00:00",
                                     high=704.5, low=701.0), "QQQ",
                               base_dir=self._tmp)                        # target
        for dim, key in (("session", "morning"), ("playbook", "sweep_reversal"),
                         ("tool", "bullish_fvg"), ("regime", "trend"),
                         ("volatility", "normal")):
            stats = get_suppression_stats("QQQ", dim, key, base_dir=self._tmp)
            self.assertEqual(stats["suppressed_total"], 1, dim)
            self.assertEqual(stats["false_suppressions"], 1, dim)
            self.assertEqual(stats["suppression_accuracy"], 0.0, dim)

    def test_G_correct_suppression_increments_buckets(self):
        self._run_outcome({"high": 700.2, "low": 697.5, "close": 698.0})  # stop
        stats = get_suppression_stats("QQQ", "session", "morning",
                                      base_dir=self._tmp)
        self.assertEqual(stats["correct_suppressions"], 1)
        self.assertEqual(stats["suppression_accuracy"], 1.0)
        metrics = load_suppression_metrics("QQQ", base_dir=self._tmp)
        self.assertEqual(set(metrics.keys()),
                         {"playbook", "tool", "session", "regime", "volatility"})


class TestH_AdaptiveMemoryFeed(_Sandbox):
    def test_policy_report_carries_suppression_evidence_without_flag_changes(self):
        # resolve one false suppression into the metrics store
        self._register()
        resolve_shadow_outcome(_snap(ts="2026-07-06T10:30:00",
                                     high=700.2, low=699.9), "QQQ",
                               base_dir=self._tmp)
        resolve_shadow_outcome(_snap(ts="2026-07-06T11:00:00",
                                     high=704.5, low=701.0), "QQQ",
                               base_dir=self._tmp)
        cand = {"symbol": "QQQ", "playbook": "sweep_reversal",
                "tool": "bullish_fvg", "session": "morning",
                "regime": "trend", "volatility": "normal"}
        rep = generate_adaptive_policy_report(cand, base_dir=self._tmp,
                                              today="2026-07-06")
        sup = rep["dimensions"]["session"]["suppression"]
        self.assertEqual(sup["false_suppressions"], 1)
        self.assertEqual(sup["suppression_accuracy"], 0.0)
        # OBSERVATION ONLY: no policy flag moved (empty tables -> all False)
        self.assertFalse(rep["trade_block_recommended"])
        self.assertFalse(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["risk_reduction_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])


class TestTrackCycle(_Sandbox):
    def test_track_suppression_full_cycle_and_telemetry(self):
        snap = _snap(high=702.0, low=700.5, close=701.0,   # no trigger yet
                     block_trace_stub=None,
                     risk={"trade_allowed": False,
                           "blocks": ["blocked: qualification is watchlist"]})
        tel = track_suppression(snap, "QQQ", base_dir=self._tmp)
        self.assertEqual(tel["authority_level"], "observe_only")
        self.assertTrue(tel["registered"])
        self.assertEqual(tel["open_count"], 1)
        # next scan resolves nothing, keeps tracking
        tel2 = track_suppression(
            _snap(ts="2026-07-06T10:06:00", high=702.0, low=700.6,
                  risk={"trade_allowed": False,
                        "blocks": ["blocked: qualification is watchlist"]}),
            "QQQ", base_dir=self._tmp)
        self.assertEqual(tel2["open_count"], 1)

    def test_score_suppression_pure(self):
        rec = score_suppression({"a": 1}, OUTCOME_FALSE)
        self.assertEqual(rec["suppression_cost"], 2.0)
        rec = score_suppression({}, OUTCOME_CORRECT)
        self.assertEqual(rec["suppression_cost"], -1.0)
        rec = score_suppression({}, OUTCOME_NEUTRAL, unrealized_r=0.7)
        self.assertEqual(rec["suppression_cost"], 0.7)
        rec = score_suppression({}, OUTCOME_EXPIRED)
        self.assertEqual(rec["suppression_cost"], 0.0)


if __name__ == "__main__":
    unittest.main()
