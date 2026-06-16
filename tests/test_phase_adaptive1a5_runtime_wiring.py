"""
Adaptive Learning — Phase 1A.5: Runtime Scar Collection wiring.

Proves the closed-trade reconciliation event now becomes a retrievable scar in the
existing vector store: a closed trade writes once, an open trade writes nothing,
duplicate/restart reconciliation never double-writes (deterministic memory_id),
malformed outcomes are rejected with telemetry, and the written memory is
retrievable via retrieve_analogs(). Store + journal are redirected to temp dirs so
the real corpus is untouched.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _entry_record(**over) -> dict:
    """A journal-shaped CLOSED entry record (post-PIPE-1/Vector-3 entry context)."""
    rec = {
        "trade_id": "T-1001",
        "timestamp": "20260615T113000",
        "symbol": "QQQ",
        "side": "buy",
        "intent_type": "expansion_continuation",
        "order_status": "closed",
        "entry_reference": 740.5,
        "stop_reference": 739.8,
        "entry_price": 740.5,
        "exit_price": 742.1,
        "realized_r": 2.3,
        "realized_pnl": 320.0,
        "close_reason": "take_profit",
        "market_regime_label": "expansion_up",
        "volatility_state": "stable",
        "expansion_state": "healthy_expansion",
        "narrative_direction_at_entry": "bullish",
        "narrative_phase_at_entry": "distribution",
        "ai_confidence_at_entry": 72,
        "liquidity_draw_at_entry": "sell_side",
        "snapshot_summary": {"session": "afternoon", "playbook": "expansion_continuation"},
        "mfe": 2.6, "mae": 0.4,
    }
    rec.update(over)
    return rec


def _recon(**over) -> dict:
    r = {"status": "closed", "trade_id": "T-1001", "realized_r": 2.3,
         "realized_pnl": 320.0, "entry_price": 740.5, "exit_price": 742.1,
         "close_reason": "take_profit"}
    r.update(over)
    return r


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._prev = {k: os.environ.get(k) for k in ("AI_RETRIEVAL_DIR", "PAPER_TRADES_DIR")}
        os.environ["AI_RETRIEVAL_DIR"] = self._tmp
        os.environ["PAPER_TRADES_DIR"] = self._tmp

    def tearDown(self):
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _journal(self, **over):
        from paper_execution.trade_journal import append_trade
        append_trade(_entry_record(**over), "QQQ")


class TestAssembler(_Isolated):
    def test_pure_assembly_maps_entry_and_recon(self):
        from adaptive_learning.outcome_assembler import assemble_closed_trade_outcome
        out = assemble_closed_trade_outcome(_recon(), _entry_record(), None)
        self.assertEqual(out["instrument"], "QQQ")
        self.assertEqual(out["entry_timestamp"], "20260615T113000")
        self.assertEqual(out["source_type"], "closed_trade")
        self.assertEqual(out["session"], "afternoon")
        self.assertEqual(out["regime"], "expansion_up")
        self.assertEqual(out["direction"], "bullish")
        self.assertEqual(out["stop_price"], 739.8)
        self.assertEqual(out["exit_price"], 742.1)
        self.assertEqual(out["realized_r"], 2.3)
        self.assertEqual(out["result"], "win")
        self.assertEqual(out["management_path"], "take_profit")
        self.assertEqual(out["direction_source"], "ai_brain")


class TestRuntimeWiring(_Isolated):
    def test_1_closed_trade_writes_memory(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        self._journal()
        tel = record_closed_trade_scar(_recon(), "QQQ")
        self.assertTrue(tel["memory_written"], tel)
        self.assertEqual(len(tel["memory_id"]), 64)
        self.assertEqual(tel["validation_errors"], [])
        self.assertEqual(len(load_records()), 1)

    def test_2_open_trade_does_not_write(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        self._journal(order_status="filled")
        tel = record_closed_trade_scar(_recon(status="open"), "QQQ")
        self.assertFalse(tel["memory_written"])
        self.assertIn("not_closed", tel["validation_errors"])
        self.assertEqual(len(load_records()), 0)

    def test_3_duplicate_reconciliation_does_not_double_write(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        self._journal()
        first = record_closed_trade_scar(_recon(), "QQQ")
        second = record_closed_trade_scar(_recon(), "QQQ")
        self.assertTrue(first["memory_written"])
        self.assertFalse(second["memory_written"])
        self.assertTrue(second["duplicate_skipped"])
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(len(load_records()), 1)

    def test_4_restart_scenario_does_not_double_write(self):
        # "restart" = a fresh process re-running reconciliation over the SAME
        # persisted store + journal. Deterministic memory_id must still dedup.
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        self._journal()
        record_closed_trade_scar(_recon(), "QQQ")
        # simulate restart: store file persists; new reconciliation pass
        tel = record_closed_trade_scar(_recon(), "QQQ")
        self.assertTrue(tel["duplicate_skipped"])
        self.assertEqual(len(load_records()), 1)

    def test_5_written_memory_retrievable(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.retrieval import retrieve_analogs
        self._journal()
        record_closed_trade_scar(_recon(), "QQQ")
        ctx = {"timestamp": "2026-06-16T15:30:00+00:00", "session": "afternoon",
               "market_regime": {"regime_label": "expansion_up", "volatility_state": "stable"},
               "narrative_authority": {"narrative_direction": "bullish",
                                       "narrative_phase": "distribution"},
               "shared_context": {"delivery_state": "bullish_delivery"}}
        res = retrieve_analogs(ctx, k=5, authoritative_only=True, min_similarity=0.0,
                               persist_log=False)
        hit = next((a for a in res["analogs"]
                    if a.get("timestamp") == "20260615T113000"), None)
        self.assertIsNotNone(hit, res["analogs"])
        self.assertEqual(hit["outcome"], "win")

    def test_6_malformed_outcome_rejected(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        # entry record with no realized_r and recon with none -> rejected
        self._journal(realized_r=None)
        tel = record_closed_trade_scar(_recon(realized_r=None), "QQQ")
        self.assertFalse(tel["memory_written"])
        self.assertIn("missing_realized_r", tel["validation_errors"])
        self.assertEqual(len(load_records()), 0)

    def test_7_telemetry_populated(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        self._journal()
        tel = record_closed_trade_scar(_recon(), "QQQ")
        for k in ("memory_written", "memory_id", "source_type",
                  "duplicate_skipped", "validation_errors"):
            self.assertIn(k, tel)
        self.assertEqual(tel["source_type"], "closed_trade")

    def test_8_hook_triggers_exactly_once_net(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        from ai_retrieval.vector_store import load_records
        self._journal()
        for _ in range(5):                       # repeated scans over same close
            record_closed_trade_scar(_recon(), "QQQ")
        self.assertEqual(len(load_records()), 1)  # exactly one scar net

    def test_entry_record_not_found(self):
        from adaptive_learning.outcome_assembler import record_closed_trade_scar
        tel = record_closed_trade_scar(_recon(trade_id="GHOST"), "QQQ")  # no journal
        self.assertFalse(tel["memory_written"])
        self.assertIn("entry_record_not_found", tel["validation_errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
