"""
Phase 5G — Shared Context Intelligence test suite.

5G.1 — SharedMarketContext aggregation
5G.2 — Council member opinions
5G.3 — Council report / consensus
5G.4 — Snapshot integration (observe-only invariants)
5G.5 — Retroactive replay of the 2026-06-10 losing QQQ trade
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shared_context.shared_market_context import build_shared_market_context
from shared_context.council import (
    run_council,
    generate_council_report,
    regime_opinion,
    delivery_opinion,
    opportunity_opinion,
    qualification_opinion,
    toolbox_opinion,
    risk_opinion,
)

_SNAPSHOT_20260610 = os.path.join(
    os.path.dirname(__file__), "..", "data", "live_snapshots",
    "20260610_115839_QQQ.json",
)

_CONTEXT_FIELDS = [
    "regime", "regime_confidence", "volatility_state", "expansion_state",
    "delivery_state", "delivery_confidence", "continuation_intact",
    "exhaustion_present", "reversal_present",
    "qualification_status", "qualification_score",
    "playbook", "toolbox_tool", "trigger_status", "setup_age",
    "risk_multiplier", "session", "symbol", "current_price",
]


def _full_snapshot():
    """Healthy trend snapshot covering every context source."""
    return {
        "symbol": "QQQ",
        "timestamp": "2026-06-10 10:00",
        "session": "ny_am",
        "timeframes": {"1m": {"last_candle": {"open": 700.0, "close": 700.5}}},
        "market_regime": {
            "regime_label": "trend_up", "confidence": 72,
            "volatility_state": "stable", "expansion_state": "expanding",
        },
        "po3": {
            "alignment": "full_distribution_alignment",
            "15m": {"distribution_direction": "bullish"},
            "5m":  {"distribution_direction": "bullish"},
        },
        "structure": {"alignment": "strong",
                      "15m": {"mss": False}, "5m": {"mss": False}},
        "liquidity": {"15m": {"sweep_detected": False, "reclaim_detected": False}},
        "expansion": {"15m": {"state": "expanding", "exhaustion_risk": "low"}},
        "ai_context": {"directional_bias": "bullish"},
        "qualification": {"status": "qualified", "opportunity_score": 78},
        "playbook": {"selected_playbook": "trend_continuation", "direction": "bullish"},
        "setup_lifecycle": {"active": True, "age_scans": 3},
        "risk": {"risk_tier": "normal", "risk_multiplier": 1.0},
        "toolbox": {
            "preferred_tool": "bullish_fvg",
            "tool_candidates": [{
                "tool": "bullish_fvg",
                "trigger_prep": {"raw_trigger_status": "confirmed",
                                 "execution_ready": True},
                "price_level": {"current_price": 700.5},
            }],
        },
        "position_monitor": {"current_price": 700.4},
    }


def _ctx(**overrides):
    """Bare context with overrides for direct member tests."""
    base = build_shared_market_context({}, "QQQ")
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# 5G.1 — SharedMarketContext
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedContextCreation(unittest.TestCase):

    def test_all_required_fields_present(self):
        ctx = build_shared_market_context(_full_snapshot(), "QQQ")
        for field in _CONTEXT_FIELDS:
            self.assertIn(field, ctx, f"missing field: {field}")

    def test_full_snapshot_values(self):
        ctx = build_shared_market_context(_full_snapshot(), "QQQ")
        self.assertEqual(ctx["regime"], "trend_up")
        self.assertEqual(ctx["regime_confidence"], 72)
        self.assertEqual(ctx["volatility_state"], "stable")
        self.assertEqual(ctx["delivery_state"], "bullish_delivery")
        self.assertEqual(ctx["delivery_confidence"], 85)
        self.assertTrue(ctx["continuation_intact"])
        self.assertFalse(ctx["exhaustion_present"])
        self.assertFalse(ctx["reversal_present"])
        self.assertEqual(ctx["qualification_status"], "qualified")
        self.assertEqual(ctx["qualification_score"], 78)
        self.assertEqual(ctx["playbook"], "trend_continuation")
        self.assertEqual(ctx["toolbox_tool"], "bullish_fvg")
        self.assertEqual(ctx["trigger_status"], "confirmed")
        self.assertEqual(ctx["setup_age"], 3)
        self.assertEqual(ctx["risk_multiplier"], 1.0)
        self.assertEqual(ctx["session"], "ny_am")
        self.assertEqual(ctx["symbol"], "QQQ")

    def test_current_price_prefers_1m_candle(self):
        ctx = build_shared_market_context(_full_snapshot(), "QQQ")
        self.assertEqual(ctx["current_price"], 700.5)

    def test_current_price_falls_back_to_position_monitor(self):
        snap = _full_snapshot()
        snap["timeframes"] = {}
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertEqual(ctx["current_price"], 700.4)

    def test_empty_snapshot_degrades_safely(self):
        ctx = build_shared_market_context({}, "QQQ")
        self.assertEqual(ctx["regime"], "unknown")
        self.assertEqual(ctx["delivery_state"], "unknown")
        self.assertEqual(ctx["qualification_status"], "no_trade")
        self.assertEqual(ctx["setup_age"], 0)
        self.assertIsNone(ctx["current_price"])

    def test_none_snapshot_never_raises(self):
        ctx = build_shared_market_context(None, "QQQ")
        self.assertEqual(ctx["symbol"], "QQQ")

    def test_missing_po3_falls_back_to_ai_bias(self):
        snap = _full_snapshot()
        del snap["po3"]
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertEqual(ctx["delivery_state"], "bullish_bias_only")
        self.assertEqual(ctx["delivery_confidence"], 30)
        self.assertFalse(ctx["continuation_intact"])

    def test_inactive_setup_age_is_zero(self):
        snap = _full_snapshot()
        snap["setup_lifecycle"] = {"active": False, "age_scans": 9}
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertEqual(ctx["setup_age"], 0)

    def test_risk_multiplier_tier_fallback(self):
        snap = _full_snapshot()
        snap["risk"] = {"risk_tier": "minimal"}     # no explicit multiplier
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertEqual(ctx["risk_multiplier"], 0.5)

    def test_exhaustion_detected_from_regime_state(self):
        snap = _full_snapshot()
        snap["market_regime"]["expansion_state"] = "exhaustion_risk"
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertTrue(ctx["exhaustion_present"])

    def test_reversal_detected_from_sweep_reclaim(self):
        snap = _full_snapshot()
        snap["liquidity"] = {"5m": {"sweep_detected": True, "reclaim_detected": True}}
        ctx = build_shared_market_context(snap, "QQQ")
        self.assertTrue(ctx["reversal_present"])


# ══════════════════════════════════════════════════════════════════════════════
# 5G.2 — Council member opinions
# ══════════════════════════════════════════════════════════════════════════════

class TestCouncilMembers(unittest.TestCase):

    def test_regime_votes_no_in_range_rotation_with_exhaustion(self):
        op = regime_opinion(_ctx(regime="range_rotation",
                                 exhaustion_present=True,
                                 volatility_state="unstable"))
        self.assertEqual(op["vote"], "no")
        self.assertGreaterEqual(op["confidence"], 80)
        self.assertTrue(op["concerns"])

    def test_regime_votes_yes_in_healthy_trend(self):
        op = regime_opinion(_ctx(regime="trend_up", regime_confidence=70,
                                 volatility_state="stable",
                                 exhaustion_present=False))
        self.assertEqual(op["vote"], "yes")
        self.assertGreaterEqual(op["confidence"], 55)

    def test_regime_votes_neutral_when_no_signal(self):
        op = regime_opinion(_ctx(regime="low_volatility",
                                 volatility_state="low",
                                 exhaustion_present=False))
        self.assertEqual(op["vote"], "neutral")

    def test_delivery_votes_yes_when_intact_and_confident(self):
        op = delivery_opinion(_ctx(delivery_state="bullish_delivery",
                                   delivery_confidence=85,
                                   continuation_intact=True))
        self.assertEqual(op["vote"], "yes")
        self.assertEqual(op["confidence"], 85)

    def test_delivery_votes_no_when_weak(self):
        op = delivery_opinion(_ctx(delivery_state="mixed",
                                   delivery_confidence=25,
                                   continuation_intact=False))
        self.assertEqual(op["vote"], "no")
        self.assertIn("continuation weakened", op["reasons"][0])

    def test_opportunity_votes_no_without_playbook(self):
        op = opportunity_opinion(_ctx(playbook="no_playbook"))
        self.assertEqual(op["vote"], "no")

    def test_opportunity_votes_no_continuation_in_range(self):
        op = opportunity_opinion(_ctx(playbook="trend_continuation",
                                      regime="range_rotation"))
        self.assertEqual(op["vote"], "no")
        self.assertIn("playbook fights the regime", op["concerns"])

    def test_opportunity_votes_yes_reversal_with_evidence(self):
        op = opportunity_opinion(_ctx(playbook="liquidity_sweep_reversal",
                                      regime="range_rotation",
                                      reversal_present=True))
        self.assertEqual(op["vote"], "yes")

    def test_opportunity_neutral_reversal_without_evidence(self):
        op = opportunity_opinion(_ctx(playbook="liquidity_sweep_reversal",
                                      regime="range_rotation",
                                      reversal_present=False))
        self.assertEqual(op["vote"], "neutral")
        self.assertTrue(op["concerns"])

    def test_qualification_votes_yes_when_qualified(self):
        op = qualification_opinion(_ctx(qualification_status="qualified",
                                        qualification_score=73, setup_age=3))
        self.assertEqual(op["vote"], "yes")
        self.assertEqual(op["confidence"], 73)

    def test_qualification_flags_newborn_setup(self):
        op = qualification_opinion(_ctx(qualification_status="qualified",
                                        qualification_score=73, setup_age=1))
        self.assertEqual(op["vote"], "yes")
        self.assertTrue(any("newborn" in c for c in op["concerns"]))

    def test_qualification_votes_no_on_no_trade(self):
        op = qualification_opinion(_ctx(qualification_status="no_trade"))
        self.assertEqual(op["vote"], "no")

    def test_toolbox_votes_yes_on_confirmed(self):
        op = toolbox_opinion(_ctx(toolbox_tool="bullish_ifvg",
                                  trigger_status="confirmed"))
        self.assertEqual(op["vote"], "yes")
        self.assertEqual(op["confidence"], 85)

    def test_toolbox_flags_unconfirmed_trigger(self):
        op = toolbox_opinion(_ctx(toolbox_tool="bullish_rejection_block",
                                  trigger_status="confirmation_needed"))
        self.assertEqual(op["vote"], "yes")
        self.assertIn("trigger not yet confirmed", op["concerns"])

    def test_toolbox_votes_no_without_tool(self):
        op = toolbox_opinion(_ctx(toolbox_tool="no_tool"))
        self.assertEqual(op["vote"], "no")

    def test_risk_votes_neutral_at_half_risk(self):
        op = risk_opinion(_ctx(risk_multiplier=0.5))
        self.assertEqual(op["vote"], "neutral")
        self.assertIn("0.5x maximum risk", op["reasons"][0])
        self.assertTrue(op["concerns"])

    def test_risk_votes_no_when_blocked(self):
        op = risk_opinion(_ctx(risk_multiplier=0.0))
        self.assertEqual(op["vote"], "no")

    def test_risk_votes_yes_at_full_risk(self):
        op = risk_opinion(_ctx(risk_multiplier=1.0))
        self.assertEqual(op["vote"], "yes")

    def test_every_member_returns_required_shape(self):
        ctx = _ctx()
        for fn in (regime_opinion, delivery_opinion, opportunity_opinion,
                   qualification_opinion, toolbox_opinion, risk_opinion):
            op = fn(ctx)
            self.assertIn(op["vote"], ("yes", "no", "neutral"))
            self.assertTrue(0 <= op["confidence"] <= 100)
            self.assertIsInstance(op["reasons"], list)
            self.assertIsInstance(op["concerns"], list)
            self.assertTrue(op["member"].isupper())


# ══════════════════════════════════════════════════════════════════════════════
# 5G.3 — Council report
# ══════════════════════════════════════════════════════════════════════════════

class TestCouncilReport(unittest.TestCase):

    @staticmethod
    def _op(member, vote, conf, concerns=None):
        return {"member": member, "vote": vote, "confidence": conf,
                "reasons": [], "concerns": concerns or []}

    def test_vote_counting(self):
        rep = generate_council_report([
            self._op("A", "yes", 70), self._op("B", "no", 80),
            self._op("C", "no", 60), self._op("D", "neutral", 50),
        ])
        self.assertEqual(rep["yes_votes"], 1)
        self.assertEqual(rep["no_votes"], 2)
        self.assertEqual(rep["neutral_votes"], 1)

    def test_dominant_no_with_strength(self):
        rep = generate_council_report([
            self._op("A", "yes", 70), self._op("B", "no", 80),
            self._op("C", "no", 60),
        ])
        self.assertEqual(rep["dominant_position"], "no")
        self.assertEqual(rep["consensus_strength"], 67)   # 2/3 of decided
        self.assertEqual(rep["confidence"], 70)            # avg of no-voters

    def test_dominant_yes(self):
        rep = generate_council_report([
            self._op("A", "yes", 80), self._op("B", "yes", 60),
            self._op("C", "no", 90),
        ])
        self.assertEqual(rep["dominant_position"], "yes")
        self.assertEqual(rep["consensus_strength"], 67)

    def test_divided_council(self):
        rep = generate_council_report([
            self._op("A", "yes", 80), self._op("B", "no", 80),
        ])
        self.assertEqual(rep["dominant_position"], "divided")
        self.assertEqual(rep["consensus_strength"], 50)

    def test_all_neutral(self):
        rep = generate_council_report([
            self._op("A", "neutral", 50), self._op("B", "neutral", 60),
        ])
        self.assertEqual(rep["dominant_position"], "neutral")

    def test_concerns_aggregated_and_deduplicated(self):
        rep = generate_council_report([
            self._op("A", "no", 70, concerns=["exhaustion risk present"]),
            self._op("B", "no", 70, concerns=["exhaustion risk present",
                                              "volatility unstable"]),
        ])
        self.assertEqual(rep["critical_concerns"],
                         ["exhaustion risk present", "volatility unstable"])

    def test_report_never_raises(self):
        rep = generate_council_report([{"bad": "opinion"}])
        self.assertIn("dominant_position", rep)


# ══════════════════════════════════════════════════════════════════════════════
# 5G.4 — Snapshot integration + observe-only invariants
# ══════════════════════════════════════════════════════════════════════════════

class TestSnapshotIntegration(unittest.TestCase):

    def test_run_council_full_output(self):
        ctx     = build_shared_market_context(_full_snapshot(), "QQQ")
        council = run_council(ctx)
        self.assertTrue(council["enabled"])
        self.assertEqual(council["authority_level"], "observe_only")
        self.assertEqual(len(council["members"]), 6)
        names = [m["member"] for m in council["members"]]
        self.assertEqual(names, ["REGIME", "DELIVERY", "OPPORTUNITY",
                                 "QUALIFICATION", "TOOLBOX", "RISK"])
        self.assertIn("report", council)

    def test_council_output_is_json_serializable(self):
        ctx     = build_shared_market_context(_full_snapshot(), "QQQ")
        council = run_council(ctx)
        json.dumps({"shared_context": ctx, "council": council})  # must not raise

    def test_observe_only_does_not_mutate_snapshot(self):
        snap   = _full_snapshot()
        before = copy.deepcopy(snap)
        ctx    = build_shared_market_context(snap, "QQQ")
        run_council(ctx)
        self.assertEqual(snap, before)

    def test_healthy_trend_council_approves(self):
        ctx     = build_shared_market_context(_full_snapshot(), "QQQ")
        council = run_council(ctx)
        rep     = council["report"]
        self.assertEqual(rep["dominant_position"], "yes")
        self.assertEqual(rep["no_votes"], 0)

    def test_council_never_raises_on_garbage(self):
        council = run_council(None)
        self.assertEqual(len(council["members"]), 6)
        council = run_council({"regime": 12345})
        self.assertEqual(len(council["members"]), 6)

    def test_backward_compat_old_snapshot_without_new_keys(self):
        """Old snapshots (pre-5G) build a context and council without errors."""
        with open(_SNAPSHOT_20260610, encoding="utf-8") as f:
            old_snap = json.load(f)
        self.assertNotIn("shared_context", old_snap)
        self.assertNotIn("council", old_snap)
        ctx     = build_shared_market_context(old_snap, "QQQ")
        council = run_council(ctx)
        self.assertEqual(len(council["members"]), 6)

    def test_gate_output_unchanged_by_council_keys(self):
        """Decision/execution layers are blind to council output."""
        from execution_gate.execution_gate import evaluate_gate
        with open(_SNAPSHOT_20260610, encoding="utf-8") as f:
            snap = json.load(f)
        eg_without = evaluate_gate(copy.deepcopy(snap))
        snap["shared_context"] = build_shared_market_context(snap, "QQQ")
        snap["council"]        = run_council(snap["shared_context"])
        eg_with = evaluate_gate(snap)
        self.assertEqual(eg_without, eg_with)


# ══════════════════════════════════════════════════════════════════════════════
# 5G.5 — Retroactive replay: the 2026-06-10 losing QQQ trade
# ══════════════════════════════════════════════════════════════════════════════

class TestRetroactiveReplay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(_SNAPSHOT_20260610, encoding="utf-8") as f:
            snap = json.load(f)
        # Saved snapshots strip candidate trigger detail — restore what the
        # live log recorded at entry (CONFIRMATION_NEEDED).
        for cand in snap["toolbox"]["tool_candidates"]:
            if cand["tool"] == snap["toolbox"]["preferred_tool"]:
                cand["trigger_prep"] = {
                    "execution_ready":    True,
                    "raw_trigger_status": "confirmation_needed",
                }
        cls.ctx     = build_shared_market_context(snap, "QQQ")
        cls.council = run_council(cls.ctx)
        cls.report  = cls.council["report"]
        cls.votes   = {m["member"]: m["vote"] for m in cls.council["members"]}

    def test_context_captures_the_hostile_environment(self):
        self.assertEqual(self.ctx["regime"], "range_rotation")
        self.assertEqual(self.ctx["volatility_state"], "unstable")
        self.assertEqual(self.ctx["expansion_state"], "exhaustion_risk")
        self.assertTrue(self.ctx["exhaustion_present"])
        self.assertEqual(self.ctx["setup_age"], 1)
        self.assertEqual(self.ctx["risk_multiplier"], 0.5)   # minimal tier

    def test_regime_member_voted_no(self):
        self.assertEqual(self.votes["REGIME"], "no")

    def test_delivery_member_voted_no(self):
        self.assertEqual(self.votes["DELIVERY"], "no")

    def test_risk_member_did_not_endorse(self):
        self.assertIn(self.votes["RISK"], ("neutral", "no"))

    def test_council_would_not_have_approved(self):
        self.assertNotEqual(self.report["dominant_position"], "yes")

    def test_consensus_warned_with_critical_concerns(self):
        self.assertTrue(self.report["critical_concerns"])
        joined = " ".join(self.report["critical_concerns"])
        self.assertTrue(
            "range_rotation" in joined or "exhaustion" in joined,
            f"concerns did not mention the regime problem: {joined}",
        )

    def test_replay_is_observe_only(self):
        self.assertEqual(self.council["authority_level"], "observe_only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
