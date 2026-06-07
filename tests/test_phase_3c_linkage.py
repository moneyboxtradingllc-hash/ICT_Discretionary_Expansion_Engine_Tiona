"""
Phase 3C tests — Intent-to-Trade Linkage Engine.
13 tests covering linking priority, outcome metrics, quality, and safety constraints.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import experience_intelligence.experience_summary as es_mod

from experience_intelligence.intent_trade_linker    import link_intents_to_trades
from experience_intelligence.linked_outcome_metrics import compute_linked_metrics
from experience_intelligence.experience_metrics     import compute_metrics
from experience_intelligence.experience_summary     import build_experience_summary


# ── Helpers ──────────────────────────────────────────────────────────────────

def _intent(intent_id="I1", setup_id=None, direction="long",
            tool="fib_retracement", playbook="liquidity_sweep_reversal",
            created_at="20240101T093000"):
    d = {
        "intent_id":      intent_id,
        "direction":      direction,
        "preferred_tool": tool,
        "playbook":       playbook,
        "created_at":     created_at,
    }
    if setup_id:
        d["setup_id"] = setup_id
    return d


def _trade(trade_id="T1", intent_id=None, setup_id=None,
           direction="long", tool="fib_retracement",
           playbook="liquidity_sweep_reversal",
           order_status="closed", timestamp="20240101T093500",
           realized_pnl=None, risk_dollars=None,
           mfe=None, mae=None, closed_at=None):
    d = {
        "trade_id":     trade_id,
        "order_status": order_status,
        "timestamp":    timestamp,
        "snapshot_summary": {
            "playbook": {
                "direction":         direction,
                "selected_playbook": playbook,
            },
            "toolbox": {"preferred_tool": tool},
        },
    }
    if intent_id:
        d["intent_id"] = intent_id
    if setup_id:
        d["setup_id"] = setup_id
    if realized_pnl is not None:
        d["realized_pnl"] = realized_pnl
    if risk_dollars is not None:
        d["risk_dollars"] = risk_dollars
    if mfe is not None:
        d["mfe"] = mfe
    if mae is not None:
        d["mae"] = mae
    if closed_at:
        d["closed_at"] = closed_at
    return d


def _snapshot():
    return {
        "qualification": {"status": "qualified", "grade": "B", "opportunity_score": 70},
        "playbook":      {"selected_playbook": "liquidity_sweep_reversal", "direction": "long"},
        "risk":          {"risk_tier": "standard"},
        "toolbox":       {"preferred_tool": "fib_retracement", "tool_candidates": []},
        "session":       "open",
    }


# ── Test 1: Exact intent_id match ────────────────────────────────────────────

class TestExactIntentIdLink(unittest.TestCase):

    def test_exact_intent_id_link(self):
        intents = [_intent(intent_id="I1")]
        trades  = [_trade(trade_id="T1", intent_id="I1")]
        results = link_intents_to_trades(intents, trades)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r["linked"])
        self.assertEqual(r["link_method"], "intent_id")
        self.assertEqual(r["confidence"],  "high")
        self.assertEqual(r["trade_id"],    "T1")
        self.assertEqual(r["intent_id"],   "I1")


# ── Test 2: Setup ID match ────────────────────────────────────────────────────

class TestSetupIdLink(unittest.TestCase):

    def test_setup_id_link(self):
        intents = [_intent(intent_id="I2", setup_id="SU1")]
        trades  = [_trade(trade_id="T2", setup_id="SU1")]  # no intent_id
        results = link_intents_to_trades(intents, trades)
        r = results[0]
        self.assertTrue(r["linked"])
        self.assertEqual(r["link_method"], "setup_id")
        self.assertEqual(r["confidence"],  "high")
        self.assertEqual(r["trade_id"],    "T2")


# ── Test 3: Proximity via direction + tool ────────────────────────────────────

class TestProximityToolLink(unittest.TestCase):

    def test_proximity_tool_link(self):
        # intent at 09:30, trade at 09:35 (5 min apart), same direction + tool
        intents = [_intent(intent_id="I3", created_at="20240101T093000")]
        trades  = [_trade(trade_id="T3", timestamp="20240101T093500")]
        results = link_intents_to_trades(intents, trades)
        r = results[0]
        self.assertTrue(r["linked"])
        self.assertEqual(r["link_method"], "proximity_tool")
        self.assertEqual(r["confidence"],  "medium")
        self.assertEqual(r["trade_id"],    "T3")


# ── Test 4: Multiple-match warning ───────────────────────────────────────────

class TestMultipleMatchWarning(unittest.TestCase):

    def test_multiple_intent_id_match_adds_warning(self):
        intents = [_intent(intent_id="I4")]
        trades  = [
            _trade(trade_id="T4a", intent_id="I4"),
            _trade(trade_id="T4b", intent_id="I4"),
        ]
        results = link_intents_to_trades(intents, trades)
        r = results[0]
        self.assertTrue(r["linked"])
        self.assertIn("multiple possible matches", r["warnings"])


# ── Test 5: No-match behavior ─────────────────────────────────────────────────

class TestNoMatchBehavior(unittest.TestCase):

    def test_no_match_returns_unlinked(self):
        # Different direction, different tool/playbook, timestamps 150 min apart
        intents = [_intent(
            intent_id="I5", direction="long",
            tool="fib_retracement", playbook="liquidity_sweep_reversal",
            created_at="20240101T093000",
        )]
        trades = [_trade(
            trade_id="T5", intent_id=None,
            direction="short", tool="order_block",
            playbook="range_expansion_fade",
            timestamp="20240101T120000",  # 150 min away
        )]
        results = link_intents_to_trades(intents, trades)
        r = results[0]
        self.assertFalse(r["linked"])
        self.assertEqual(r["confidence"],  "none")
        self.assertIsNone(r["trade_id"])
        self.assertIsNone(r["link_method"])


# ── Test 6: Closed trade computes realized_r ──────────────────────────────────

class TestLinkedClosedRealizedR(unittest.TestCase):

    def test_closed_trade_computes_realized_r(self):
        intents = [_intent(intent_id="I6")]
        trades  = [_trade(
            trade_id="T6", intent_id="I6",
            order_status="closed",
            realized_pnl=200.0, risk_dollars=100.0,
        )]
        links    = link_intents_to_trades(intents, trades)
        outcomes = compute_linked_metrics(links, intents, trades)
        self.assertEqual(len(outcomes), 1)
        o = outcomes[0]
        self.assertTrue(o["linked"])
        self.assertTrue(o["closed"])
        self.assertEqual(o["realized_r"], 2.0)


# ── Test 7: Open linked trade excluded from closed metrics ────────────────────

class TestOpenLinkedTradeExcludedFromClosedMetrics(unittest.TestCase):

    def test_open_linked_trade_not_in_closed_count_or_average_mfe(self):
        lo_open = {
            "linked": True, "closed": False,
            "intent_id": "I7", "trade_id": "T7",
            "mfe": 1.5, "mae": 0.5,
        }
        metrics = compute_metrics([], [lo_open])
        self.assertEqual(metrics["closed_trade_count"], 0)
        self.assertEqual(metrics["linked_trade_count"], 1)
        self.assertEqual(metrics["open_trade_count"],   1)
        self.assertIsNone(metrics["average_mfe"])


# ── Test 8: Closed linked trade included in closed metrics ───────────────────

class TestClosedLinkedTradeIncludedInClosedMetrics(unittest.TestCase):

    def test_closed_linked_trade_in_closed_count_and_average_mfe(self):
        lo_closed = {
            "linked": True, "closed": True,
            "intent_id": "I8", "trade_id": "T8",
            "mfe": 2.0, "mae": 0.8,
        }
        metrics = compute_metrics([], [lo_closed])
        self.assertEqual(metrics["closed_trade_count"], 1)
        self.assertEqual(metrics["linked_trade_count"], 1)
        self.assertEqual(metrics["open_trade_count"],   0)
        self.assertEqual(metrics["average_mfe"],        2.0)
        self.assertEqual(metrics["average_mae"],        0.8)


# ── Test 9: MFE/MAE source preference ────────────────────────────────────────

class TestMfeMaeSourcePreference(unittest.TestCase):

    def test_mfe_pulled_from_intent_when_available(self):
        i = _intent(intent_id="I9a")
        i["mfe"] = 3.5
        i["mae"] = 0.5
        t = _trade(trade_id="T9a", intent_id="I9a", mfe=1.0, mae=0.2)
        links    = link_intents_to_trades([i], [t])
        outcomes = compute_linked_metrics(links, [i], [t])
        o = outcomes[0]
        self.assertTrue(o["linked"])
        self.assertEqual(o["mfe"], 3.5)
        self.assertEqual(o["mae"], 0.5)

    def test_mfe_falls_back_to_trade_when_intent_has_none(self):
        i = _intent(intent_id="I9b")  # no mfe/mae on intent
        t = _trade(trade_id="T9b", intent_id="I9b", mfe=2.2, mae=0.7)
        links    = link_intents_to_trades([i], [t])
        outcomes = compute_linked_metrics(links, [i], [t])
        o = outcomes[0]
        self.assertEqual(o["mfe"], 2.2)
        self.assertEqual(o["mae"], 0.7)


# ── Test 10: Linkage quality thresholds ──────────────────────────────────────

class TestLinkageQuality(unittest.TestCase):

    def setUp(self):
        from experience_intelligence.experience_summary import _linkage_quality
        self._lq = _linkage_quality

    def test_none_when_no_intents(self):
        self.assertEqual(self._lq(0, 0), "none")

    def test_none_when_zero_linked(self):
        self.assertEqual(self._lq(0, 5), "none")

    def test_high_when_ratio_ge_80(self):
        self.assertEqual(self._lq(8, 10), "high")

    def test_medium_when_ratio_ge_50(self):
        self.assertEqual(self._lq(5, 10), "medium")

    def test_low_when_ratio_below_50(self):
        self.assertEqual(self._lq(3, 10), "low")


# ── Test 11: authority_level always observe_only ──────────────────────────────

class TestAuthorityObserveOnly(unittest.TestCase):

    @patch.object(es_mod, "load_completed_trades",   return_value=[])
    @patch.object(es_mod, "load_all_intent_records", return_value=[])
    @patch.object(es_mod, "find_similar_setups",     return_value=[])
    @patch.object(es_mod, "build_correlation",       return_value={"sample_size": 0})
    def test_authority_always_observe_only(self, *_):
        summary = build_experience_summary(_snapshot(), "QQQ")
        self.assertEqual(summary["authority_level"], "observe_only")


# ── Test 12: confidence_modifier always 0 ────────────────────────────────────

class TestConfidenceModifierZero(unittest.TestCase):

    @patch.object(es_mod, "load_completed_trades",   return_value=[])
    @patch.object(es_mod, "load_all_intent_records", return_value=[])
    @patch.object(es_mod, "find_similar_setups",     return_value=[])
    @patch.object(es_mod, "build_correlation",       return_value={"sample_size": 0})
    def test_confidence_modifier_always_zero(self, *_):
        summary = build_experience_summary(_snapshot(), "QQQ")
        self.assertEqual(summary["confidence_modifier"], 0)


# ── Test 13: No execution/decision side effects ───────────────────────────────

class TestNoExecutionSideEffects(unittest.TestCase):

    _EXECUTION_KEYS = {
        "decision_authority", "execution_gate", "paper_execution",
        "position_monitor", "stop_enforcer", "paper_activation",
        "ai_confidence", "intent_score",
    }

    def test_link_results_contain_no_execution_keys(self):
        intents = [_intent(intent_id="I13")]
        trades  = [_trade(trade_id="T13", intent_id="I13")]
        links   = link_intents_to_trades(intents, trades)
        for link in links:
            for key in self._EXECUTION_KEYS:
                self.assertNotIn(
                    key, link,
                    msg=f"Execution key '{key}' must not appear in link result",
                )

    def test_linked_outcomes_contain_no_execution_keys(self):
        intents  = [_intent(intent_id="I13b")]
        trades   = [_trade(trade_id="T13b", intent_id="I13b")]
        links    = link_intents_to_trades(intents, trades)
        outcomes = compute_linked_metrics(links, intents, trades)
        for outcome in outcomes:
            for key in self._EXECUTION_KEYS:
                self.assertNotIn(
                    key, outcome,
                    msg=f"Execution key '{key}' must not appear in linked outcome",
                )


if __name__ == "__main__":
    unittest.main()
