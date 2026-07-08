"""
Phase 5E.1 — Data Integrity Patch Tests.
18 tests covering:
  - Deduplication fix (linked intent + paper trade → one record, correct preference)
  - record_source and data_completeness fields
  - closed_match_count / outcome_summary alignment (both use top-K population)
  - Dashboard pass-through in recommendation builder
  - Intent archive regime/session enrichment
  - Recommendation persistence (write, append, failure handling)
  - Safety invariants (authority_level, confidence_modifier, no execution fields)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import memory_search.memory_record_builder as mrb
from memory_search.memory_record_builder import (
    load_memory_records,
    _normalize_intent,
    _normalize_trade,
)
from memory_search.similarity_search import find_similar_setups
from recommendation_engine.recommendation_builder    import (
    build_recommendations,
    build_recommendations_from_context,
)
from recommendation_engine.recommendation_persistence import save_recommendations
from intent_archive.intent_archive import _make_new_record


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _intent_raw(intent_id="I_001", linked_trade_id=None, realized_r=None, status="open"):
    rec = {
        "intent_id":    intent_id,
        "direction":    "bullish",
        "playbook":     "liquidity_sweep_reversal",
        "preferred_tool": "bullish_ifvg",
        "quality_at_creation": "candidate",
        "status":       status,
    }
    if linked_trade_id:
        rec["linked_trade_id"] = linked_trade_id
    if realized_r is not None:
        rec["realized_r"] = realized_r
    return rec


def _trade_raw(trade_id="T_001", intent_id="I_001", realized_r=None, order_status="submitted"):
    rec = {
        "trade_id":   trade_id,
        "intent_id":  intent_id,
        "symbol":     "QQQ",
        "direction":  "long",
        "playbook":   "liquidity_sweep_reversal",
        "preferred_tool": "bullish_ifvg",
        "order_status": order_status,
    }
    if realized_r is not None:
        rec["realized_r"] = realized_r
        rec["order_status"] = "closed"
    return rec


def _intent_archive_file(symbol="QQQ", intents=None):
    return {"date": "20260608", "symbol": symbol, "intents": intents or []}


def _dashboard(closed=30):
    return {
        "closed_trades": closed,
        "win_rate":      55.0,
        "best_regime":   "trend_up",
        "worst_regime":  "chop",
        "regime_metrics": {
            "trend_up": {"win_rate": 70.0, "sample_size": 12, "average_r": 0.8},
            "chop":     {"win_rate": 35.0, "sample_size": 11, "average_r": -0.3},
        },
        "best_playbook":  "lsr",
        "worst_playbook": "chop_trade",
        "playbook_metrics": {
            "lsr":        {"win_rate": 68.0, "sample_size": 15, "average_r": 0.7},
            "chop_trade": {"win_rate": 28.0, "sample_size": 12, "average_r": -0.5},
        },
    }


def _snapshot(symbol="QQQ"):
    return {
        "symbol":        symbol,
        "session":       "ny_open",
        "qualification": {"status": "candidate", "opportunity_score": 70},
        "playbook":      {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "toolbox":       {"preferred_tool": "bullish_ifvg"},
        "market_regime": {
            "enabled":          True,
            "regime_label":     "trend_up",
            "regime_family":    "trend",
            "confidence":       68,
            "volatility_state": "normal",
            "expansion_state":  "neutral",
        },
        "confidence_fusion": {"mechanical_score": 70},
        "ai_discretionary":  {"ai_confidence": 60},
        "intent_score":      {"gated_score": 70},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Deduplication — Linked Record Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeduplication(unittest.TestCase):

    def _load_both(self, intent_dir, trades_dir):
        with patch.object(mrb, "_INTENT_DIR", intent_dir), \
             patch.object(mrb, "_TRADES_DIR", trades_dir):
            # DASHBOARD-BASELINE: these tests exercise load/dedup MECHANICS with
            # pre-epoch fixture timestamps — use the raw-loading accessor so the
            # baseline epoch gate does not filter the fixtures.
            return load_memory_records("QQQ", include_pre_epoch=True)

    def test_01_linked_intent_and_trade_dedupes_to_one_record(self):
        """A paper trade that claims intent I_001 should produce exactly 1 record total."""
        intent_data = _intent_archive_file(intents=[
            _intent_raw("I_001", linked_trade_id="T_001"),
        ])
        trade_data = [_trade_raw("T_001", intent_id="I_001")]

        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            with open(os.path.join(intent_dir, "20260608_QQQ_intents.json"), "w") as f:
                json.dump(intent_data, f)
            with open(os.path.join(trades_dir, "20260608_QQQ_trades.json"), "w") as f:
                json.dump(trade_data, f)
            records = self._load_both(intent_dir, trades_dir)

        self.assertEqual(len(records), 1)

    def test_02_paper_trade_preferred_over_intent_archive_when_linked(self):
        """When a paper trade claims intent I_001, the returned record must be the trade record."""
        intent_data = _intent_archive_file(intents=[
            _intent_raw("I_001"),
        ])
        trade_data = [_trade_raw("T_001", intent_id="I_001")]

        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            with open(os.path.join(intent_dir, "20260608_QQQ_intents.json"), "w") as f:
                json.dump(intent_data, f)
            with open(os.path.join(trades_dir, "20260608_QQQ_trades.json"), "w") as f:
                json.dump(trade_data, f)
            records = self._load_both(intent_dir, trades_dir)

        self.assertEqual(len(records), 1)
        # The surviving record must be the paper trade (has trade_id, record_source=paper_trade)
        self.assertEqual(records[0]["trade_id"],      "T_001")
        self.assertEqual(records[0]["record_source"], "paper_trade")

    def test_03_intent_only_record_preserved_when_no_trade_exists(self):
        """An intent with no linked paper trade must appear as its own record."""
        intent_data = _intent_archive_file(intents=[
            _intent_raw("I_002"),  # no linked_trade_id
        ])

        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            with open(os.path.join(intent_dir, "20260608_QQQ_intents.json"), "w") as f:
                json.dump(intent_data, f)
            # trades_dir is empty
            records = self._load_both(intent_dir, trades_dir)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["intent_id"],     "I_002")
        self.assertIsNone(records[0]["trade_id"])
        self.assertEqual(records[0]["record_source"], "intent_archive")

    def test_04_multiple_independent_records_all_preserved(self):
        """Two unlinked intents + one unlinked trade = 3 records, no deduplication."""
        intent_data = _intent_archive_file(intents=[
            _intent_raw("I_010"),
            _intent_raw("I_011"),
        ])
        trade_data = [_trade_raw("T_020", intent_id=None)]
        trade_data[0].pop("intent_id", None)

        with tempfile.TemporaryDirectory() as intent_dir, \
             tempfile.TemporaryDirectory() as trades_dir:
            with open(os.path.join(intent_dir, "20260608_QQQ_intents.json"), "w") as f:
                json.dump(intent_data, f)
            with open(os.path.join(trades_dir, "20260608_QQQ_trades.json"), "w") as f:
                json.dump(trade_data, f)
            records = self._load_both(intent_dir, trades_dir)

        self.assertEqual(len(records), 3)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. record_source and data_completeness Fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordMetaFields(unittest.TestCase):

    def test_05_paper_trade_record_source(self):
        rec = _normalize_trade(_trade_raw("T_001"))
        self.assertEqual(rec["record_source"], "paper_trade")

    def test_05b_intent_archive_record_source(self):
        rec = _normalize_intent(_intent_raw("I_001"), "QQQ")
        self.assertEqual(rec["record_source"], "intent_archive")

    def test_05c_data_completeness_full_for_closed_paper_trade(self):
        closed = _trade_raw("T_001", realized_r=1.5)
        rec = _normalize_trade(closed)
        self.assertEqual(rec["data_completeness"], "full")

    def test_05d_data_completeness_partial_for_open_paper_trade(self):
        open_trade = _trade_raw("T_001")  # no realized_r
        rec = _normalize_trade(open_trade)
        self.assertEqual(rec["data_completeness"], "partial")

    def test_05e_data_completeness_partial_for_intent_archive(self):
        # Intent archive records are always partial (may lack regime/session)
        closed_intent = _intent_raw("I_001", realized_r=1.0)
        rec = _normalize_intent(closed_intent, "QQQ")
        self.assertEqual(rec["data_completeness"], "partial")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. closed_match_count / outcome_summary Alignment
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutcomeSummaryAlignment(unittest.TestCase):

    def _make_records(self, n_closed, n_open, symbol="QQQ"):
        """Create n_closed closed + n_open open trade records for symbol."""
        records = []
        for i in range(n_closed):
            records.append({
                "trade_id":           f"T_C{i:03d}",
                "symbol":             symbol,
                "direction":          "long",
                "playbook":           "liquidity_sweep_reversal",
                "preferred_tool":     "bullish_ifvg",
                "market_regime_label": "trend_up",
                "session":            "ny_open",
                "volatility_state":   "high",
                "expansion_state":    "expanding",
                "order_status":       "closed",
                "realized_r":         1.0,
            })
        for i in range(n_open):
            records.append({
                "trade_id":           f"T_O{i:03d}",
                "symbol":             symbol,
                "direction":          "long",
                "playbook":           "liquidity_sweep_reversal",
                "preferred_tool":     "bullish_ifvg",
                "market_regime_label": "trend_up",
                "session":            "ny_open",
                "volatility_state":   "high",
                "expansion_state":    "expanding",
                "order_status":       "submitted",
            })
        return records

    def test_06_closed_match_count_matches_outcome_summary_sample_size(self):
        """closed_match_count must equal similar_outcome_summary.sample_size."""
        records = self._make_records(n_closed=8, n_open=4)

        with tempfile.TemporaryDirectory() as trades_dir, \
             tempfile.TemporaryDirectory() as intent_dir:
            with open(os.path.join(trades_dir, "20260608_QQQ_trades.json"), "w") as f:
                json.dump(records, f)
            snap = _snapshot()
            import memory_search.similarity_search as ss_mod
            with patch.object(mrb, "_INTENT_DIR", intent_dir), \
                 patch.object(mrb, "_TRADES_DIR", trades_dir):
                result = find_similar_setups(snap, "QQQ", limit=10, min_similarity=0.0)

        closed_count   = result["closed_match_count"]
        summary_sample = result["similar_outcome_summary"].get("sample_size", 0)
        self.assertEqual(closed_count, summary_sample,
            f"closed_match_count={closed_count} != summary sample_size={summary_sample}")

    def test_07_outcome_summary_uses_top_k_closed_only(self):
        """With limit=3 and 6 closed records, outcome_summary.sample_size must be ≤ 3."""
        records = self._make_records(n_closed=6, n_open=0)

        with tempfile.TemporaryDirectory() as trades_dir, \
             tempfile.TemporaryDirectory() as intent_dir:
            with open(os.path.join(trades_dir, "20260608_QQQ_trades.json"), "w") as f:
                json.dump(records, f)
            snap = _snapshot()
            with patch.object(mrb, "_INTENT_DIR", intent_dir), \
                 patch.object(mrb, "_TRADES_DIR", trades_dir):
                result = find_similar_setups(snap, "QQQ", limit=3, min_similarity=0.0)

        self.assertLessEqual(result["similar_outcome_summary"]["sample_size"], 3)
        self.assertLessEqual(result["closed_match_count"], 3)
        # total_closed_above_threshold may be larger (all 6 were above threshold)
        self.assertGreaterEqual(result["total_closed_above_threshold"], result["closed_match_count"])

    def test_07b_total_closed_above_threshold_field_present(self):
        """Result must include total_closed_above_threshold."""
        result = find_similar_setups(_snapshot(), "QQQ")
        self.assertIn("total_closed_above_threshold", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Recommendation Builder Dashboard Pass-Through
# ═══════════════════════════════════════════════════════════════════════════════

class TestDashboardPassThrough(unittest.TestCase):

    def test_08_build_recommendations_uses_provided_dashboard(self):
        """When dashboard is passed explicitly, build_dashboard must not be called."""
        from performance_intelligence import dashboard_builder as db_mod
        call_count = {"n": 0}
        original = db_mod.build_dashboard

        def counting_build(*a, **kw):
            call_count["n"] += 1
            return original(*a, **kw)

        dash = _dashboard(closed=30)
        with patch.object(db_mod, "build_dashboard", side_effect=counting_build):
            result = build_recommendations(symbol="QQQ", snapshot={}, dashboard=dash)

        self.assertEqual(call_count["n"], 0,
            "build_dashboard was called despite an explicit dashboard being passed")
        self.assertEqual(result["authority_level"], "observe_only")

    def test_09_build_recommendations_fallback_builds_dashboard_when_none(self):
        """When no dashboard is passed and no snapshot intelligence exists, build_dashboard is called."""
        import recommendation_engine.recommendation_builder as rb_mod
        call_count = {"n": 0}
        original = rb_mod.build_dashboard

        def counting_build(*a, **kw):
            call_count["n"] += 1
            return original(*a, **kw)

        with patch.object(rb_mod, "build_dashboard", side_effect=counting_build):
            result = build_recommendations(symbol="QQQ", snapshot={}, dashboard=None)

        self.assertGreaterEqual(call_count["n"], 1,
            "build_dashboard was not called when no dashboard was provided")
        self.assertEqual(result["authority_level"], "observe_only")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Intent Archive Regime/Session Enrichment
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentArchiveEnrichment(unittest.TestCase):

    def _make_record(self, session="ny_open", regime="trend_up", family="trend",
                     confidence=70, vol="normal", expansion="neutral"):
        snap = {
            "session": session,
            "trade_intent":   {"intent_type": "long", "direction": "bullish", "preferred_tool": "bullish_ifvg"},
            "intent_score":   {"raw_score": 70, "gated_score": 70, "gated_quality": "candidate"},
            "setup_lifecycle": {},
            "playbook":       {"selected_playbook": "liquidity_sweep_reversal"},
            "market_regime": {
                "regime_label":    regime,
                "regime_family":   family,
                "confidence":      confidence,
                "volatility_state": vol,
                "expansion_state":  expansion,
            },
        }
        return _make_new_record("QQQ", snap, "test_archive_key")

    def test_10_intent_archive_stores_session(self):
        rec = self._make_record(session="london_open")
        self.assertEqual(rec["session"], "london_open")

    def test_11_intent_archive_stores_market_regime_label(self):
        rec = self._make_record(regime="range_rotation")
        self.assertEqual(rec["market_regime_label"], "range_rotation")

    def test_11b_intent_archive_stores_all_regime_fields(self):
        rec = self._make_record(
            regime="high_volatility", family="volatility",
            confidence=80, vol="extreme", expansion="expanding"
        )
        self.assertEqual(rec["market_regime_label"],  "high_volatility")
        self.assertEqual(rec["market_regime_family"], "volatility")
        self.assertEqual(rec["regime_confidence"],    80)
        self.assertEqual(rec["volatility_state"],     "extreme")
        self.assertEqual(rec["expansion_state"],      "expanding")

    def test_11c_intent_archive_defaults_when_regime_absent(self):
        snap = {
            "session": "",
            "trade_intent":    {"intent_type": "long", "direction": "bullish", "preferred_tool": "tool"},
            "intent_score":    {"raw_score": 60, "gated_score": 60, "gated_quality": "candidate"},
            "setup_lifecycle": {},
            "playbook":        {"selected_playbook": "lsr"},
            # no market_regime key
        }
        rec = _make_new_record("QQQ", snap, "key")
        self.assertEqual(rec["market_regime_label"], "unknown")
        self.assertEqual(rec["session"],             "")

    def test_12_normalizer_reads_top_level_regime_fields(self):
        """_normalize_intent must use top-level session/regime rather than defaulting to unknown."""
        intent = {
            "intent_id":           "I_ENRICH_01",
            "direction":           "bullish",
            "playbook":            "trend_continuation",
            "preferred_tool":      "bullish_ifvg",
            "quality_at_creation": "candidate",
            "status":              "open",
            "session":             "ny_midday",
            "market_regime_label": "trend_down",
            "market_regime_family": "trend",
            "volatility_state":    "low",
            "expansion_state":     "contracting",
        }
        rec = _normalize_intent(intent, "QQQ")
        self.assertEqual(rec["session"],             "ny_midday")
        self.assertEqual(rec["market_regime_label"], "trend_down")
        self.assertEqual(rec["volatility_state"],    "low")
        self.assertEqual(rec["expansion_state"],     "contracting")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Recommendation Persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendationPersistence(unittest.TestCase):

    def _rec_result(self, count=2):
        recs = [
            {
                "type":              "regime",
                "severity":          "moderate",
                "finding":           "Chop underperforming",
                "evidence":          "35% WR over 11 trades",
                "recommendation":    "Reduce chop participation",
                "status":            "human_review_required",
                "authority_level":   "observe_only",
                "confidence_modifier": 0,
            }
        ] * count
        return {
            "enabled":              True,
            "authority_level":      "observe_only",
            "confidence_modifier":  0,
            "recommendation_count": count,
            "recommendations":      recs,
            "notes":                [],
            "warnings":             [],
        }

    def test_13_persistence_writes_daily_file(self):
        from recommendation_engine import recommendation_persistence as rp_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(rp_mod, "_REC_DIR", tmpdir):
                status = save_recommendations("QQQ", self._rec_result(2))

            self.assertTrue(status["saved"])
            self.assertIn("filepath", status)
            self.assertTrue(os.path.exists(status["filepath"]))

            with open(status["filepath"]) as f:
                data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(entry["symbol"],               "QQQ")
        self.assertEqual(entry["recommendation_count"], 2)
        self.assertEqual(entry["authority_level"],      "observe_only")
        self.assertEqual(entry["confidence_modifier"],  0)

    def test_14_persistence_appends_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from recommendation_engine import recommendation_persistence as rp_mod
            with patch.object(rp_mod, "_REC_DIR", tmpdir):
                save_recommendations("QQQ", self._rec_result(1))
                save_recommendations("QQQ", self._rec_result(2))
                status = save_recommendations("QQQ", self._rec_result(3))

            with open(status["filepath"]) as f:
                data = json.load(f)

        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["recommendation_count"], 1)
        self.assertEqual(data[1]["recommendation_count"], 2)
        self.assertEqual(data[2]["recommendation_count"], 3)

    def test_15_persistence_failure_returns_warning_not_crash(self):
        # Patch os.makedirs to raise PermissionError to simulate an unwritable directory
        from recommendation_engine import recommendation_persistence as rp_mod
        import builtins
        original_open = builtins.open

        def failing_open(path, *a, **kw):
            if "recommendations" in str(path):
                raise PermissionError("simulated write failure")
            return original_open(path, *a, **kw)

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(rp_mod, "_REC_DIR", tmpdir), \
             patch("builtins.open", side_effect=failing_open):
            status = save_recommendations("QQQ", self._rec_result())

        self.assertFalse(status["saved"])
        self.assertIn("warning", status)
        self.assertIn("non-blocking", status["warning"])

    def test_15b_persisted_entries_never_contain_forbidden_fields(self):
        dirty_result = self._rec_result(1)
        dirty_result["recommendations"][0]["allow_execution"]      = True
        dirty_result["recommendations"][0]["risk_multiplier"]      = 2.0
        dirty_result["recommendations"][0]["confidence_modifier_delta"] = 5

        with tempfile.TemporaryDirectory() as tmpdir:
            from recommendation_engine import recommendation_persistence as rp_mod
            with patch.object(rp_mod, "_REC_DIR", tmpdir):
                status = save_recommendations("QQQ", dirty_result)
            with open(status["filepath"]) as f:
                data = json.load(f)

        forbidden = {"allow_execution", "risk_multiplier", "confidence_modifier_delta"}
        for entry in data:
            for rec in entry.get("recommendations", []):
                self.assertFalse(
                    forbidden & set(rec.keys()),
                    f"Forbidden field found in persisted recommendation: {set(rec.keys()) & forbidden}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Safety Invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyInvariants(unittest.TestCase):

    def test_16_authority_level_remains_observe_only(self):
        # Normalizers
        trade_rec  = _normalize_trade(_trade_raw("T_001"))
        intent_rec = _normalize_intent(_intent_raw("I_001"), "QQQ")
        self.assertNotIn("authority_level", trade_rec)   # records don't carry authority
        self.assertNotIn("authority_level", intent_rec)

        # Search result
        result = find_similar_setups(_snapshot(), "QQQ")
        self.assertEqual(result["authority_level"], "observe_only")

        # Recommendations
        ctx = {
            "dashboard":     _dashboard(closed=30),
            "ai_feedback":   {},
            "memory_search": {},
        }
        rec_result = build_recommendations_from_context(ctx)
        self.assertEqual(rec_result["authority_level"], "observe_only")

    def test_17_confidence_modifier_always_zero(self):
        result = find_similar_setups(_snapshot(), "QQQ")
        self.assertEqual(result["confidence_modifier"], 0)

        ctx = {
            "dashboard":     _dashboard(closed=30),
            "ai_feedback":   {},
            "memory_search": {},
        }
        rec_result = build_recommendations_from_context(ctx)
        self.assertEqual(rec_result["confidence_modifier"], 0)
        for rec in rec_result["recommendations"]:
            self.assertEqual(rec["confidence_modifier"], 0)

    def test_18_no_execution_behavior_changed(self):
        """Normalized records and search results must not contain execution gate fields."""
        trade_rec  = _normalize_trade(_trade_raw("T_001"))
        intent_rec = _normalize_intent(_intent_raw("I_001"), "QQQ")
        forbidden  = {"allow_execution", "trade_authorized", "gate_status",
                      "risk_multiplier", "position_size"}
        self.assertFalse(forbidden & set(trade_rec.keys()))
        self.assertFalse(forbidden & set(intent_rec.keys()))

        result = find_similar_setups(_snapshot(), "QQQ")
        self.assertFalse(forbidden & set(result.keys()))


if __name__ == "__main__":
    unittest.main()
