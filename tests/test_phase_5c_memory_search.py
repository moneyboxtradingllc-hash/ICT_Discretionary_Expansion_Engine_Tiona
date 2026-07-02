"""
Phase 5C — Memory Similarity Search Tests.
17 tests covering: record loading, feature vectors, similarity scoring,
outcome summary, memory quality, AI input, snapshot store, safety invariants.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from memory_search.memory_record_builder import (
    load_memory_records,
    _normalize_intent,
    _normalize_trade,
)
from memory_search.feature_vector import (
    build_query_features,
    build_record_features,
    score_similarity,
)
from memory_search.similarity_search import find_similar_setups
from memory_search.memory_summary    import build_memory_summary
from ai_layer.ai_input_builder       import build_compact_ai_input
from live_scan.snapshot_store        import save_snapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _intent(
    intent_id="I_001",
    direction="bullish",
    playbook="liquidity_sweep_reversal",
    tool="bullish_ifvg",
    session="ny_open",
    regime="trend_up",
    vol="high",
    expansion="expanding",
    score=74,
    status="open",
    realized_r=None,
):
    rec = {
        "intent_id":              intent_id,
        "direction":              direction,
        "playbook":               playbook,
        "preferred_tool":         tool,
        "session":                session,
        "market_regime_label":    regime,
        "market_regime_family":   "trend",
        "volatility_state":       vol,
        "expansion_state":        expansion,
        "gated_score_at_creation": score,
        "quality_at_creation":    "candidate",
        "status":                 status,
    }
    if realized_r is not None:
        rec["realized_r"] = realized_r
        rec["status"]     = "closed"
    return rec


def _trade(
    trade_id="T_001",
    intent_id="I_001",
    direction="long",
    playbook="liquidity_sweep_reversal",
    tool="bullish_ifvg",
    session="ny_open",
    regime="trend_up",
    vol="high",
    expansion="expanding",
    score=74,
    realized_r=None,
    order_status="submitted",
    symbol="QQQ",
):
    rec = {
        "trade_id":             trade_id,
        "intent_id":            intent_id,
        "symbol":               symbol,
        "direction":            direction,
        "playbook":             playbook,
        "preferred_tool":       tool,
        "session":              session,
        "market_regime_label":  regime,
        "market_regime_family": "trend",
        "volatility_state":     vol,
        "expansion_state":      expansion,
        "intent_score_gated":   score,
        "qualification_status": "candidate",
        "order_status":         order_status,
    }
    if realized_r is not None:
        rec["realized_r"]   = realized_r
        rec["order_status"] = "closed"
    return rec


def _snapshot(
    symbol="QQQ",
    session="ny_open",
    regime="trend_up",
    playbook="liquidity_sweep_reversal",
    direction="bullish",
    tool="bullish_ifvg",
    qual_status="candidate",
    score=74,
    vol="high",
    expansion="expanding",
):
    return {
        "symbol":  symbol,
        "session": session,
        "qualification": {"status": qual_status, "direction": direction, "opportunity_score": score},
        "playbook": {"selected_playbook": playbook, "direction": direction},
        "toolbox": {"preferred_tool": tool},
        "market_regime": {
            "enabled":        True,
            "regime_label":   regime,
            "regime_family":  "trend",
            "confidence":     70,
            "volatility_state": vol,
            "expansion_state":  expansion,
        },
        "confidence_fusion": {"mechanical_score": score},
        "ai_discretionary":  {"ai_confidence": 60},
        "intent_score":      {"gated_score": score},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Record Loading
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordLoading(unittest.TestCase):

    def test_01_records_load_from_intent_archive(self):
        intent_data = {
            "date":    "20260610",
            "symbol":  "QQQ",
            "intents": [_intent("I_A"), _intent("I_B")],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "20260610_QQQ_intents.json")
            with open(fpath, "w") as f:
                json.dump(intent_data, f)
            import memory_search.memory_record_builder as mrb
            with patch.object(mrb, "_INTENT_DIR", tmpdir), \
                 patch.object(mrb, "_TRADES_DIR", tmpdir):
                records = load_memory_records("QQQ")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["intent_id"], "I_A")

    def test_02_records_load_from_paper_trades(self):
        trades_data = [_trade("T_001"), _trade("T_002")]
        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            fpath = os.path.join(trades_dir, "20260610_QQQ_trades.json")
            with open(fpath, "w") as f:
                json.dump(trades_data, f)
            import memory_search.memory_record_builder as mrb
            with patch.object(mrb, "_INTENT_DIR", intent_dir), \
                 patch.object(mrb, "_TRADES_DIR", trades_dir):
                records = load_memory_records("QQQ")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["trade_id"], "T_001")

    def test_03_malformed_json_skipped_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "20260610_QQQ_intents.json")
            with open(fpath, "w") as f:
                f.write("{not valid json!!!")
            import memory_search.memory_record_builder as mrb
            with patch.object(mrb, "_INTENT_DIR", tmpdir), \
                 patch.object(mrb, "_TRADES_DIR", tmpdir):
                records = load_memory_records("QQQ")
        self.assertEqual(records, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Feature Vectors
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureVectors(unittest.TestCase):

    def test_04_query_features_built_from_snapshot(self):
        snap = _snapshot()
        q    = build_query_features(snap)
        self.assertEqual(q["symbol"],              "QQQ")
        self.assertEqual(q["market_regime_label"], "trend_up")
        self.assertEqual(q["playbook"],            "liquidity_sweep_reversal")
        self.assertEqual(q["direction"],           "bullish")
        self.assertEqual(q["preferred_tool"],      "bullish_ifvg")
        self.assertEqual(q["session"],             "ny_open")

    def test_05_same_regime_playbook_direction_scores_high(self):
        q = build_query_features(_snapshot())
        r = build_record_features(_normalize_intent(_intent(realized_r=1.5), "QQQ"))
        sim = score_similarity(q, r)
        self.assertGreater(sim["similarity_score"], 0.70)
        self.assertIn("regime", sim["reason"])

    def test_06_different_regime_playbook_scores_lower(self):
        q = build_query_features(_snapshot())
        r = build_record_features(_normalize_intent(_intent(
            regime="chop",
            playbook="mean_reversion",
            direction="bearish",
        ), "QQQ"))
        sim_high = score_similarity(q, build_record_features(_normalize_intent(_intent(realized_r=1.5), "QQQ")))
        sim_low  = score_similarity(q, r)
        self.assertGreater(sim_high["similarity_score"], sim_low["similarity_score"])

    def test_07_numeric_proximity_affects_score(self):
        q_close = {"symbol": "QQQ", "market_regime_label": "trend_up",
                   "playbook": "lsr", "direction": "bullish",
                   "preferred_tool": "ifvg", "session": "ny_open",
                   "qualification": "candidate", "volatility_state": "high",
                   "expansion_state": "expanding",
                   "intent_score_gated": 74, "ai_confidence": 60,
                   "mechanical_score": 74}
        q_far   = {**q_close, "intent_score_gated": 10, "ai_confidence": 10,
                   "mechanical_score": 10}
        r       = {**q_close}
        sim_close = score_similarity(q_close, r)
        sim_far   = score_similarity(q_far,   r)
        self.assertGreater(sim_close["similarity_score"], sim_far["similarity_score"])


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Similarity Search
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimilaritySearch(unittest.TestCase):

    def _search_with_records(self, snap, records, **kw):
        with patch("memory_search.similarity_search.load_memory_records",
                   return_value=records):
            return find_similar_setups(snap, symbol="QQQ", **kw)

    def test_08_top_matches_sorted_descending(self):
        snap    = _snapshot()
        records = [
            _normalize_intent(_intent("I_low",  regime="chop",     realized_r=1.0), "QQQ"),
            _normalize_intent(_intent("I_high",  regime="trend_up", realized_r=1.5), "QQQ"),
            _normalize_intent(_intent("I_mid",   regime="trend_up",
                                      playbook="other",             realized_r=0.5), "QQQ"),
        ]
        result = self._search_with_records(snap, records, min_similarity=0.0)
        scores = [m["similarity_score"] for m in result["top_matches"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_09_duplicate_records_removed(self):
        # Two intent archive entries with the same intent_id should yield one match.
        # Deduplication now lives in load_memory_records, so test through the real loader.
        snap = _snapshot()
        intent_data = {
            "date": "20260608", "symbol": "QQQ",
            "intents": [_intent("I_DUP", realized_r=1.0), _intent("I_DUP", realized_r=0.5)],
        }
        import memory_search.memory_record_builder as mrb
        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            with open(os.path.join(intent_dir, "20260608_QQQ_intents.json"), "w") as f:
                json.dump(intent_data, f)
            with patch.object(mrb, "_INTENT_DIR", intent_dir), \
                 patch.object(mrb, "_TRADES_DIR", trades_dir):
                result = find_similar_setups(snap, symbol="QQQ", min_similarity=0.0)
        intent_ids = [m.get("intent_id") for m in result["top_matches"]]
        self.assertEqual(intent_ids.count("I_DUP"), 1)

    def test_10_closed_trades_count_in_outcome_summary(self):
        snap    = _snapshot()
        records = [
            _normalize_intent(_intent("I_W1", realized_r= 1.5), "QQQ"),
            _normalize_intent(_intent("I_W2", realized_r= 2.0), "QQQ"),
            _normalize_intent(_intent("I_L1", realized_r=-0.8), "QQQ"),
            _normalize_intent(_intent("I_W3", realized_r= 1.0), "QQQ"),
        ]
        result = self._search_with_records(snap, records, min_similarity=0.0)
        summary = result["similar_outcome_summary"]
        self.assertEqual(summary["sample_size"], 4)
        self.assertIsNotNone(summary["win_rate"])
        self.assertAlmostEqual(summary["win_rate"], 75.0, places=0)

    def test_11_open_unknown_trades_not_in_outcome_summary(self):
        snap    = _snapshot()
        records = [
            _normalize_intent(_intent("I_OPEN",    status="open"), "QQQ"),   # no realized_r
            _normalize_intent(_intent("I_UNKNOWN"), "QQQ"),                   # no realized_r
            _normalize_intent(_intent("I_WIN",     realized_r=1.5), "QQQ"),
        ]
        result = self._search_with_records(snap, records, min_similarity=0.0)
        summary = result["similar_outcome_summary"]
        # Only 1 closed trade should count
        self.assertEqual(summary["sample_size"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Memory Summary — Quality Labels
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemorySummary(unittest.TestCase):

    def _result(self, closed_count, win_rate=None, avg_r=None, match_count=None):
        matches = []
        for i in range(closed_count):
            matches.append({"similarity_score": 0.8, "reason": "test", "outcome": "win",
                            "realized_r": 1.0})
        return {
            "match_count":        match_count or closed_count,
            "closed_match_count": closed_count,
            "top_matches":        matches[:3],
            "similar_outcome_summary": {
                "sample_size": closed_count,
                "win_rate":    win_rate,
                "average_r":   avg_r,
            },
            "notes": [],
        }

    def test_12_quality_none_when_zero_closed(self):
        s = build_memory_summary(self._result(0))
        self.assertEqual(s["memory_quality"], "none")

    def test_12b_quality_thin_1_to_4(self):
        for n in [1, 2, 4]:
            s = build_memory_summary(self._result(n))
            self.assertEqual(s["memory_quality"], "thin", f"n={n}")

    def test_12c_quality_developing_5_to_19(self):
        for n in [5, 10, 19]:
            s = build_memory_summary(self._result(n))
            self.assertEqual(s["memory_quality"], "developing", f"n={n}")

    def test_12d_quality_useful_20_plus(self):
        for n in [20, 50]:
            s = build_memory_summary(self._result(n))
            self.assertEqual(s["memory_quality"], "useful", f"n={n}")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. AI Input Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestAiInputIntegration(unittest.TestCase):

    def test_15_ai_input_includes_memory_search(self):
        snap = _snapshot()
        snap["memory_search"] = {
            "enabled":             True,
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
            "match_count":         12,
            "closed_match_count":  8,
            "best_similarity":     0.91,
            "similar_win_rate":    62.5,
            "similar_average_r":   0.84,
            "memory_quality":      "developing",
            "top_match_reasons":   ["same regime, playbook, direction"],
        }
        ai_input = build_compact_ai_input(snap)
        self.assertIn("memory_search", ai_input)
        ms = ai_input["memory_search"]
        self.assertEqual(ms["authority_level"],    "observe_only")
        self.assertEqual(ms["match_count"],        12)
        self.assertEqual(ms["closed_match_count"], 8)
        self.assertAlmostEqual(ms["best_similarity"], 0.91)
        self.assertEqual(ms["memory_quality"],     "developing")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Snapshot Store Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotStoreIntegration(unittest.TestCase):

    def test_16_snapshot_store_includes_memory_search(self):
        import live_scan.snapshot_store as ss_mod
        snap = _snapshot()
        # DECON-3: save_snapshot is post-runtime-only — model a resolved runtime
        snap.update({"decision_authority": {}, "execution_gate": {},
                     "paper_execution": {}, "position_monitor": {},
                     "trade_reconciliation": {}})
        snap["memory_search"] = {
            "enabled":             True,
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
            "match_count":         5,
            "closed_match_count":  3,
            "best_similarity":     0.78,
            "similar_win_rate":    66.7,
            "similar_average_r":   1.1,
            "memory_quality":      "thin",
            "notes":               ["observe-only"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(ss_mod, "STORE_DIR", tmpdir):
                fpath = save_snapshot(snap, "QQQ")
            with open(fpath) as f:
                saved = json.load(f)
        self.assertIn("memory_search", saved)
        ms = saved["memory_search"]
        self.assertEqual(ms["authority_level"],    "observe_only")
        self.assertEqual(ms["confidence_modifier"], 0)
        self.assertEqual(ms["match_count"],         5)
        self.assertEqual(ms["memory_quality"],      "thin")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Safety Invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def test_13_authority_level_always_observe_only(self):
        for snap in [{}, _snapshot()]:
            result = find_similar_setups(snap)
            self.assertEqual(result["authority_level"],     "observe_only")
            self.assertEqual(result["confidence_modifier"], 0)

        for n in [0, 1, 20]:
            summary = build_memory_summary({
                "match_count": n, "closed_match_count": n,
                "top_matches": [], "similar_outcome_summary": {}, "notes": [],
            })
            self.assertEqual(summary["authority_level"],     "observe_only")
            self.assertEqual(summary["confidence_modifier"], 0)

    def test_14_confidence_modifier_always_zero(self):
        result = find_similar_setups(_snapshot())
        self.assertEqual(result["confidence_modifier"], 0)

        summary = build_memory_summary(result)
        self.assertEqual(summary["confidence_modifier"], 0)

    def test_17_no_execution_behavior_changed(self):
        result = find_similar_setups(_snapshot())
        self.assertNotIn("allow_execution",    result)
        self.assertNotIn("trade_authorized",   result)
        self.assertNotIn("gate_status",        result)
        self.assertNotIn("risk_tier",          result)
        self.assertNotIn("confidence_modifier_delta", result)

        summary = build_memory_summary(result)
        self.assertNotIn("allow_execution",    summary)
        self.assertNotIn("trade_authorized",   summary)
        self.assertNotIn("confidence_modifier_delta", summary)


if __name__ == "__main__":
    unittest.main()
