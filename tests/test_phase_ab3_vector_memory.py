"""
Phase AB-3 — Vector Memory & Narrative Retrieval tests (T1-T8).

Observe-only. Real embedding-based retrieval over market-state vectors with
provenance hygiene: structure-tainted/unknown-provenance records are stored
(auditable) but never returned as authoritative analogs.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_retrieval import vector_store, retrieval, backfill
from ai_retrieval.embedding import embed, cosine, EMBED_DIM
from ai_retrieval.memory_schema import make_record, is_authoritative


def _market(direction="bearish", phase="manipulation", regime="range_rotation",
            source="sweep_semantics", ts="t", draw=True, ph=702.5):
    return make_record(
        timestamp=ts, symbol="QQQ", session="morning_continuation",
        regime=regime, volatility_state="unstable",
        narrative_direction=direction, narrative_phase=phase,
        active_liquidity_draw={"side": "sell_side"} if draw else None,
        protected_high={"level": ph} if ph else None,
        delivery_direction=direction, delivery_direction_source=source,
        active_playbook="liquidity_sweep_reversal",
        direction_source=source,
    )


def _ctx(direction="bearish", phase="manipulation", regime="range_rotation"):
    return {"timestamp": "probe", "session": "morning_continuation",
            "market_regime": {"regime_label": regime, "volatility_state": "unstable"},
            "shared_context": {"delivery_state": f"{direction}_delivery",
                               "delivery_confidence": 25, "exhaustion_present": True},
            "narrative_authority": {"narrative_direction": direction,
                                    "narrative_phase": phase,
                                    "active_liquidity_draw": {"side": "sell_side"}},
            "protected_swings": {"protected_high": {"level": 702.5}}}


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["AI_RETRIEVAL_DIR"] = self.tmp
        vector_store.clear()

    def tearDown(self):
        os.environ.pop("AI_RETRIEVAL_DIR", None)
        os.environ.pop("AI_RETRIEVAL_ENABLED", None)


class T1_VectorRetrieval(_StoreCase):
    def test_nearest_analogs_returned_by_similarity(self):
        vector_store.add_record(_market(direction="bearish", regime="range_rotation"))
        vector_store.add_record(_market(direction="bullish", regime="trend_up",
                                        source="sweep_semantics", draw=False, ph=None))
        r = retrieve_analogs = retrieval.retrieve_analogs(_ctx("bearish"), k=2,
                                                          min_similarity=0.0, persist_log=False)
        self.assertGreaterEqual(r["returned"], 1)
        # the bearish/range analog must outrank the bullish/trend one
        self.assertEqual(r["analogs"][0]["narrative_direction"], "bearish")

    def test_embedding_is_state_vector_not_label(self):
        self.assertEqual(len(embed(_ctx())), EMBED_DIM)
        # two different directions → different vectors
        self.assertNotEqual(embed(_ctx("bearish")), embed(_ctx("bullish")))


class T2_TaintedNeverAuthoritative(_StoreCase):
    def test_structure_tainted_excluded(self):
        vector_store.add_record(_market(direction="bearish", source="structure_bias"))
        vector_store.add_record(_market(direction="bearish", source="bos"))
        r = retrieval.retrieve_analogs(_ctx("bearish"), authoritative_only=True,
                                       min_similarity=0.0, persist_log=False)
        self.assertEqual(r["returned"], 0)
        self.assertEqual(r["rejected_count"], 2)

    def test_unknown_provenance_excluded(self):
        vector_store.add_record(_market(direction="bearish", source=None))
        r = retrieval.retrieve_analogs(_ctx("bearish"), authoritative_only=True,
                                       min_similarity=0.0, persist_log=False)
        self.assertEqual(r["returned"], 0)

    def test_valid_provenance_included(self):
        vector_store.add_record(_market(direction="bearish", source="sweep_semantics"))
        r = retrieval.retrieve_analogs(_ctx("bearish"), authoritative_only=True,
                                       min_similarity=0.0, persist_log=False)
        self.assertEqual(r["returned"], 1)

    def test_is_authoritative_classification(self):
        self.assertTrue(is_authoritative(_market(source="sweep_semantics")))
        self.assertFalse(is_authoritative(_market(source="structure_bias")))
        self.assertFalse(is_authoritative(_market(source=None)))


class T3_PersistAcrossRestart(_StoreCase):
    def test_memory_survives_reload(self):
        vector_store.add_record(_market(ts="persist1"))
        vector_store.add_record(_market(ts="persist2"))
        # simulate restart: fresh load from disk
        recs = vector_store.load_records()
        self.assertEqual(len(recs), 2)
        self.assertTrue(all("embedding" in r for r in recs))

    def test_trade_memory_persists(self):
        tr = make_record(timestamp="tr1", symbol="QQQ", record_type="trade",
                         trade_taken=True, trade_direction="long", win_loss_be="loss",
                         r_multiple=-1.34, management_path="broker_stop_triggered",
                         direction_source="sweep_semantics")
        vector_store.add_record(tr)
        recs = vector_store.load_records()
        self.assertEqual(recs[0]["outcome_context"]["win_loss_be"], "loss")
        self.assertEqual(recs[0]["outcome_context"]["r_multiple"], -1.34)


class T4_NarrativeRetrievalNoEntryModel(_StoreCase):
    def test_retrieval_keys_on_narrative_not_entry_model(self):
        # two records, same entry-model-less narrative state, different playbooks
        a = _market(direction="bearish", phase="manipulation")
        a["playbook_context"]["entry_model"] = None
        a["playbook_context"]["active_playbook"] = "liquidity_sweep_reversal"
        b = _market(direction="bearish", phase="manipulation")
        b["playbook_context"]["active_playbook"] = "manipulation_to_distribution"
        vector_store.add_record(a)
        vector_store.add_record(b)
        # query has NO entry model / playbook — pure narrative state
        r = retrieval.retrieve_analogs(_ctx("bearish"), k=2, min_similarity=0.0,
                                       authoritative_only=True, persist_log=False)
        self.assertEqual(r["returned"], 2)   # both retrieved on narrative state alone


class T5_June1011Corpus(_StoreCase):
    def test_backfill_loads(self):
        res = backfill.backfill_dates(("20260610", "20260611"), "QQQ")
        self.assertGreater(res["market_records"], 100)
        self.assertGreaterEqual(res["trade_records"], 1)
        self.assertEqual(vector_store.count(), res["total"])

    def test_june11_long_trade_is_in_corpus_as_loss(self):
        backfill.backfill_dates(("20260611",), "QQQ")
        recs = [r for r in vector_store.load_records()
                if r["record_type"] == "trade" and r["outcome_context"]["r_multiple"]]
        self.assertTrue(any(r["outcome_context"]["win_loss_be"] == "loss" for r in recs))


class T6_ObserveOnly(_StoreCase):
    def test_disabled_hook_returns_inert(self):
        os.environ.pop("AI_RETRIEVAL_ENABLED", None)
        r = retrieval.retrieve_for_snapshot(_ctx(), "QQQ")
        self.assertFalse(r["enabled"])
        self.assertEqual(r["analogs"], [])

    def test_retrieval_module_imports_no_authority_modules(self):
        root = os.path.join(os.path.dirname(__file__), "..", "src", "ai_retrieval")
        forbidden = ("execution_gate", "order_builder", "paper_broker",
                     "risk_governor", "submit_paper_order", "qualify_trade",
                     "classify_playbook", "run_toolbox")
        for fn in os.listdir(root):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            for f in forbidden:
                self.assertNotIn(f, src, f"ai_retrieval/{fn} references {f}")


class T7_RetrievalLogging(_StoreCase):
    def test_log_persisted_with_accepted_and_rejected(self):
        vector_store.add_record(_market(source="sweep_semantics"))
        vector_store.add_record(_market(source="structure_bias"))
        r = retrieval.retrieve_analogs(_ctx("bearish"), authoritative_only=True,
                                       min_similarity=0.0, persist_log=True)
        self.assertIsNotNone(r["log_path"])
        log = json.load(open(r["log_path"], encoding="utf-8"))
        self.assertIn("query_vector", log)
        self.assertIn("accepted_memories", log)
        self.assertIn("rejected_memories", log)
        self.assertEqual(log["provenance_status"]["rejected_non_authoritative"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
