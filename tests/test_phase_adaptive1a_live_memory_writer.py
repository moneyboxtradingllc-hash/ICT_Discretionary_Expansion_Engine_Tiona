"""
Adaptive Learning — Phase 1A: Live Memory Writer.

Proves the scar-tissue recorder: a resolved closed outcome validates, gets a
deterministic memory_id, normalizes, appends to the EXISTING vector store, is
de-duplicated, and is retrievable via retrieve_analogs(). Incomplete/open
outcomes are rejected. Recording only — no behavioural influence is asserted or
required.

The store path is redirected to a temp dir (AI_RETRIEVAL_DIR) so the real
667-record corpus is never touched.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _closed_trade(**over) -> dict:
    base = {
        "instrument": "QQQ",
        "entry_timestamp": "2026-06-15T15:30:00+00:00",
        "status": "closed",
        "session": "afternoon",
        "regime": "expansion_up",
        "volatility_state": "stable",
        "direction": "bullish",
        "narrative_direction": "bullish",
        "delivery_direction": "bullish",
        "narrative_phase": "distribution",
        "playbook": "expansion_continuation",
        "ai_thesis_summary": "bullish continuation after sweep+reclaim",
        "ai_confidence_at_entry": 72,
        "direction_source": "ai_brain",
        "entry_price": 740.5,
        "stop_price": 739.8,
        "target_price": 742.5,
        "exit_price": 742.1,
        "realized_r": 2.3,
        "mfe": 2.6,
        "mae": 0.4,
        "management_path": "scaled_at_1R_trail",
        "success_or_failure_reason": "target_reached",
    }
    base.update(over)
    return base


class _StoreIsolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("AI_RETRIEVAL_DIR")
        os.environ["AI_RETRIEVAL_DIR"] = self._tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("AI_RETRIEVAL_DIR", None)
        else:
            os.environ["AI_RETRIEVAL_DIR"] = self._prev


class TestLiveMemoryWriter(_StoreIsolated):
    def test_closed_trade_writes_successfully(self):
        from adaptive_learning.live_memory_writer import write_outcome
        from ai_retrieval.vector_store import load_records
        res = write_outcome(_closed_trade(), "closed_trade")
        self.assertTrue(res["written"], res)
        self.assertEqual(len(res["memory_id"]), 64)   # sha256 hex
        recs = load_records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        # required flat contract fields present
        for f in ("memory_id", "source_type", "instrument", "session", "regime",
                  "playbook", "direction", "ai_thesis_summary", "ai_confidence_at_entry",
                  "entry_price", "stop_price", "target_price", "exit_price", "result",
                  "realized_r", "mfe", "mae", "management_path",
                  "success_or_failure_reason", "is_authoritative"):
            self.assertIn(f, r, f"missing field {f}")
        self.assertTrue(r["is_authoritative"])
        self.assertEqual(r["result"], "win")
        self.assertIn("embedding", r)              # embedded by the existing store
        # nested contexts the embedding/provenance layer needs
        self.assertEqual(r["market_context"]["regime"], "expansion_up")
        self.assertEqual(r["narrative_context"]["narrative_direction"], "bullish")

    def test_open_trade_is_rejected(self):
        from adaptive_learning.live_memory_writer import write_outcome
        from ai_retrieval.vector_store import load_records
        res = write_outcome(_closed_trade(status="open"), "closed_trade")
        self.assertFalse(res["written"])
        self.assertEqual(res["reason"], "open_trade")
        self.assertEqual(len(load_records()), 0)

    def test_missing_exit_is_rejected(self):
        from adaptive_learning.live_memory_writer import write_outcome
        o = _closed_trade()
        o.pop("exit_price")
        res = write_outcome(o, "closed_trade")
        self.assertFalse(res["written"])
        self.assertEqual(res["reason"], "missing_exit")

    def test_missing_realized_r_is_rejected(self):
        from adaptive_learning.live_memory_writer import write_outcome
        o = _closed_trade()
        o.pop("realized_r")
        res = write_outcome(o, "closed_trade")
        self.assertFalse(res["written"])
        self.assertEqual(res["reason"], "missing_realized_r")

    def test_duplicate_memory_id_is_ignored(self):
        from adaptive_learning.live_memory_writer import write_outcome
        from ai_retrieval.vector_store import load_records
        first = write_outcome(_closed_trade(), "closed_trade")
        self.assertTrue(first["written"])
        # same instrument + entry_timestamp + source_type → same id, even if
        # other fields differ
        second = write_outcome(_closed_trade(realized_r=-1.0, exit_price=739.0),
                               "closed_trade")
        self.assertFalse(second["written"])
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(len(load_records()), 1)     # not double-written

    def test_incomplete_market_state_is_rejected(self):
        from adaptive_learning.live_memory_writer import write_outcome
        from ai_retrieval.vector_store import load_records
        o = _closed_trade()
        o.pop("regime")
        res = write_outcome(o, "closed_trade")
        self.assertFalse(res["written"])
        self.assertEqual(res["reason"], "incomplete_market_state:regime")
        self.assertEqual(len(load_records()), 0)

    def test_written_memory_is_retrievable(self):
        from adaptive_learning.live_memory_writer import write_outcome
        from ai_retrieval.retrieval import retrieve_analogs
        w = write_outcome(_closed_trade(), "closed_trade")
        self.assertTrue(w["written"])
        # query context shaped like a live snapshot, same market state
        ctx = {
            "timestamp": "2026-06-16T15:30:00+00:00",
            "session": "afternoon",
            "market_regime": {"regime_label": "expansion_up", "volatility_state": "stable"},
            "narrative_authority": {"narrative_direction": "bullish",
                                    "narrative_phase": "distribution"},
            "shared_context": {"delivery_state": "bullish_delivery"},
            "protected_swings": {},
        }
        res = retrieve_analogs(ctx, k=5, authoritative_only=True,
                               min_similarity=0.0, persist_log=False)
        self.assertGreaterEqual(res["returned"], 1, res)
        # the retrieved analog is our written trade (matched by timestamp + outcome)
        hit = next((a for a in res["analogs"]
                    if a.get("timestamp") == "2026-06-15T15:30:00+00:00"), None)
        self.assertIsNotNone(hit, res["analogs"])
        self.assertEqual(hit["outcome"], "win")
        self.assertGreater(hit["similarity"], 0.9)   # same state → near-identical vector

    def test_deterministic_memory_id_formula(self):
        from adaptive_learning.live_memory_writer import compute_memory_id
        import hashlib
        mid = compute_memory_id("QQQ", "2026-06-15T15:30:00+00:00", "closed_trade")
        expect = hashlib.sha256(
            "QQQ*2026-06-15T15:30:00+00:00*closed_trade".encode("utf-8")).hexdigest()
        self.assertEqual(mid, expect)


if __name__ == "__main__":
    unittest.main(verbosity=2)
