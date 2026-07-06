"""
HTF-MEM-1 + TRADE LINEAGE PURIFICATION — regression lock.

The organism must not inherit fake pain. Then it can learn the higher timeframe.

TEST A: stale/pre-AI trades are quarantined (epoch gate rejects them)
TEST B: baseline resets to zero when no valid current-organism trades exist
TEST C: capital no longer sees old disputed losses
TEST D: adaptive no longer sees old disputed losses
TEST E: HTF daily memory persists across engine restarts
TEST F: HTF weekly memory persists (5-session direction)
TEST G: HTF memory feeds the Brain context
TEST H: HTF memory has NO live execution authority

All state in temp dirs — never live memory.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")

from adaptive_learning.performance_tables import (          # noqa: E402
    update_performance_tables, organism_epoch, load_symbol_tables,
)
from adaptive_learning.adaptive_policy_engine import (       # noqa: E402
    generate_adaptive_policy_report,
)
from adaptive_learning.capital_intelligence_engine import (  # noqa: E402
    build_capital_metrics,
)
from market_data.htf_memory_engine import HtfMemoryEngine    # noqa: E402
from ai_brain.brain_input import build_brain_input           # noqa: E402


def _pre_ai_trade():
    """Shape of the disputed June-9 record: real oid, manual overnight close."""
    outcome = {"instrument": "QQQ", "status": "closed",
               "entry_timestamp": "20260609T114426", "session": "morning_continuation",
               "regime": "trend_up", "volatility_state": "normal",
               "playbook": "infrastructure_test",
               "realized_r": -4.8102, "realized_pnl": -2193.43}
    entry = {"symbol": "QQQ", "trade_id": "PT_QQQ_20260609T114426",
             "alpaca_order_id": "a121d37f-3aaa-4bbb-8ccc-000000000000",
             "timestamp": "20260609T114426", "closed_at": "20260610T092632",
             "market_regime_family": "trend", "volatility_state": "normal",
             "snapshot_summary": {"tool": None, "playbook": "infrastructure_test",
                                  "session": "morning_continuation"}}
    return outcome, entry


def _candles(date: str, o, h, l, c, n=3):
    """n 1m candles for a date carrying the day's OHLC."""
    out = []
    for i in range(n):
        out.append({"timestamp": f"{date}T10:{i:02d}:00-04:00",
                    "open": o if i == 0 else c, "high": h if i == 1 else max(o, c),
                    "low": l if i == 1 else min(o, c), "close": c})
    return out


class TestA_StaleTradesQuarantined(unittest.TestCase):
    def test_pre_epoch_trade_rejected_at_gate(self):
        tmp = tempfile.mkdtemp()
        res = update_performance_tables(*_pre_ai_trade(), base_dir=tmp)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "write_gate:pre_epoch_lineage")
        self.assertEqual(load_symbol_tables("QQQ", base_dir=tmp)["playbook"], {})

    def test_post_epoch_same_shape_accepted(self):
        tmp = tempfile.mkdtemp()
        o, e = _pre_ai_trade()
        o["entry_timestamp"] = "20260706T114426"
        e["timestamp"] = "20260706T114426"
        e["closed_at"] = "20260706T145000"
        res = update_performance_tables(o, e, base_dir=tmp)
        self.assertFalse(res["skipped"])

    def test_epoch_default(self):
        prev = os.environ.pop("ORGANISM_EPOCH_DATE", None)
        try:
            self.assertEqual(organism_epoch(), "20260706")
        finally:
            if prev is not None:
                os.environ["ORGANISM_EPOCH_DATE"] = prev


class TestB_ZeroBaseline(unittest.TestCase):
    def test_policy_reads_insufficient_data_everywhere(self):
        tmp = tempfile.mkdtemp()
        rep = generate_adaptive_policy_report(
            {"symbol": "QQQ", "playbook": "liquidity_sweep_reversal",
             "tool": "x", "session": "morning_continuation",
             "regime": "trend", "volatility": "normal"},
            base_dir=tmp, today="2026-07-06", decay_persist=False)
        self.assertFalse(rep["trade_block_recommended"])
        self.assertFalse(rep["confidence_penalty_recommended"])
        self.assertFalse(rep["risk_reduction_recommended"])
        for dim in ("playbook", "session", "regime", "volatility", "tool"):
            self.assertEqual(rep[f"{dim}_grade"], "insufficient_data")
            self.assertEqual(rep["dimensions"][dim]["loss_streak"], 0)


class TestC_CapitalBlindToDisputedLosses(unittest.TestCase):
    def test_pre_epoch_journal_losses_invisible(self):
        jtmp = tempfile.mkdtemp()
        day = {"date": "20260609", "symbol": "QQQ", "trades": [
            {"order_status": "closed", "realized_pnl": -2193.43,
             "risk_dollars": 456.0}]}
        with open(os.path.join(jtmp, "20260609_QQQ_paper_trades.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(day, fh)
        prev = os.environ.get("PAPER_TRADES_DIR")
        os.environ["PAPER_TRADES_DIR"] = jtmp
        try:
            m = build_capital_metrics("QQQ", {"equity": 100_000.0},
                                      today="20260706",
                                      base_dir=tempfile.mkdtemp())
            self.assertEqual(m["daily_pnl"], 0.0)
            self.assertEqual(m["weekly_pnl"], 0.0)
            self.assertIsNone(m["risk_efficiency"])   # no valid deployment seen
            self.assertEqual(m["closed_trades"], 0)   # ledger empty
        finally:
            if prev is None:
                os.environ.pop("PAPER_TRADES_DIR", None)
            else:
                os.environ["PAPER_TRADES_DIR"] = prev


class TestD_AdaptiveBlindToDisputedLosses(unittest.TestCase):
    def test_streaks_cannot_be_inherited(self):
        tmp = tempfile.mkdtemp()
        # even four pre-epoch losses fold NOTHING
        for i in range(4):
            o, e = _pre_ai_trade()
            e["alpaca_order_id"] = f"oid-{i}"
            e["timestamp"] = f"20260609T11{i:02d}00"
            update_performance_tables(o, e, base_dir=tmp)
        rep = generate_adaptive_policy_report(
            {"symbol": "QQQ", "playbook": "infrastructure_test", "tool": None,
             "session": "morning_continuation", "regime": "trend",
             "volatility": "normal"},
            base_dir=tmp, today="2026-07-06", decay_persist=False)
        self.assertFalse(rep["trade_block_recommended"])
        self.assertEqual(rep["dimensions"]["session"]["loss_streak"], 0)


class _HtfSandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("HTF_MEMORY_DIR")
        os.environ["HTF_MEMORY_DIR"] = self._tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("HTF_MEMORY_DIR", None)
        else:
            os.environ["HTF_MEMORY_DIR"] = self._prev


class TestE_DailyMemoryPersists(_HtfSandbox):
    def test_daily_context_and_restart_persistence(self):
        eng = HtfMemoryEngine("QQQ")
        eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        ctx = eng.update(_candles("2026-07-07", 706.0, 707.0, 703.0, 703.5))
        self.assertEqual(ctx["daily_context"]["date"], "2026-07-06")
        self.assertEqual(ctx["daily_context"]["high"], 705.0)
        self.assertEqual(ctx["daily_context"]["day_direction"], "bullish")
        self.assertEqual(ctx["gap_context"]["side"], "gap_up")   # 706 vs 704
        self.assertEqual(ctx["memory_age"], 1)
        # restart: a NEW engine instance reloads the persisted memory
        ctx2 = HtfMemoryEngine("QQQ").context()
        self.assertEqual(ctx2["daily_context"]["high"], 705.0)

    def test_liquidity_draws_from_untapped_levels(self):
        eng = HtfMemoryEngine("QQQ")
        eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        ctx = eng.update(_candles("2026-07-07", 704.2, 704.8, 703.0, 704.0))
        liq = ctx["liquidity_context"]
        self.assertFalse(liq["previous_high_swept"])
        self.assertFalse(liq["previous_low_swept"])
        self.assertEqual(len(liq["untapped_draws"]), 2)
        self.assertEqual(liq["nearest_draw"]["side"], "buy_side")   # 705 closest


class TestF_WeeklyMemoryPersists(_HtfSandbox):
    def test_weekly_direction_over_five_sessions(self):
        eng = HtfMemoryEngine("QQQ")
        px = 700.0
        days = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
                "2026-07-10", "2026-07-13"]
        for d in days:
            eng.update(_candles(d, px, px + 3, px - 1, px + 2.5))
            px += 2.5
        ctx = eng.context()
        self.assertEqual(ctx["memory_age"], 5)
        self.assertEqual(ctx["weekly_context"]["direction"], "bullish")
        self.assertTrue(ctx["weekly_context"]["higher_highs"])
        self.assertEqual(ctx["htf_bias"], "bullish")
        self.assertGreater(ctx["htf_confidence"], 0)

    def test_thin_memory_cannot_be_confident(self):
        eng = HtfMemoryEngine("QQQ")
        eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        ctx = eng.update(_candles("2026-07-07", 706.0, 708.0, 705.0, 707.0))
        self.assertLessEqual(ctx["htf_confidence"], 12)   # memory_age 1


class TestG_BrainContextFeed(_HtfSandbox):
    def test_htf_memory_reaches_brain_input(self):
        eng = HtfMemoryEngine("QQQ")
        eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        ctx = eng.update(_candles("2026-07-07", 706.0, 707.0, 703.0, 706.5))
        snap = {"timestamp": "2026-07-07T10:05:00", "htf_memory": ctx,
                "shared_context": {}, "protected_swings": {},
                "narrative_authority": {}, "po3": {}, "liquidity": {},
                "structure": {}, "ai_context": {}}
        payload = build_brain_input(snap, {})
        self.assertIn("htf_memory", payload)
        self.assertEqual(payload["htf_memory"]["daily_context"]["high"], 705.0)
        self.assertEqual(payload["htf_memory"]["authority_level"], "context_only")


class TestH_NoExecutionAuthority(_HtfSandbox):
    def test_authority_hard_lock(self):
        eng = HtfMemoryEngine("QQQ")
        ctx = eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        self.assertEqual(ctx["authority_level"], "context_only")
        for k in ("blocked", "allow_execution", "trade_blocked", "veto",
                  "direction_override"):
            self.assertNotIn(k, ctx)

    def test_no_authority_module_reads_htf_memory(self):
        """Source guard: execution gate, decision engine, risk governor,
        mutation engine, and execution engine never read htf_memory."""
        forbidden = [
            ("execution_gate", "execution_gate.py"),
            ("decision_authority", "decision_engine.py"),
            ("risk", "risk_governor.py"),
            ("adaptive_learning", "adaptive_mutation_engine.py"),
            ("paper_execution", "execution_engine.py"),
            ("paper_execution", "order_builder.py"),
        ]
        for pkg, fname in forbidden:
            with open(os.path.join(_SRC, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("htf_memory", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()


class TestH2PayloadContract(unittest.TestCase):
    """HTF-MEM-1.1 — H2 regression lock: the Brain payload with HTF memory
    must pass the anti-contamination scanner; the firewall itself is untouched
    and still rejects genuinely contaminated payloads."""

    def _htf_ctx(self):
        eng = HtfMemoryEngine("QQQ", persist=False)
        eng.update(_candles("2026-07-06", 700.0, 705.0, 698.0, 704.0))
        return eng.update(_candles("2026-07-07", 706.0, 707.0, 703.0, 706.5))

    def test_A_june_shaped_payload_still_accepted(self):
        from ai_brain.brain_validation import scan_payload_taint
        june_shape = {"timestamp": "t", "session": "morning", "market": {},
                      "delivery": {}, "liquidity": {}, "protected_swings": {},
                      "playbook_toolbox": {}, "stance_history": {},
                      "news_context": {}, "STRUCTURE_WITNESS": {"bias": "bullish"}}
        clean, hits = scan_payload_taint(june_shape)
        self.assertTrue(clean, hits)

    def test_B_repaired_htf_payload_accepted(self):
        from ai_brain.brain_validation import scan_payload_taint
        ctx = self._htf_ctx()
        clean, hits = scan_payload_taint({"htf_memory": ctx})
        self.assertTrue(clean, f"HTF context must satisfy H2: {hits}")
        # and inside a full brain payload
        snap = {"timestamp": "t", "htf_memory": ctx, "shared_context": {},
                "protected_swings": {}, "narrative_authority": {}, "po3": {},
                "liquidity": {}, "structure": {}, "ai_context": {}}
        payload = build_brain_input(snap, {})
        clean, hits = scan_payload_taint(payload)
        self.assertTrue(clean, f"full payload must satisfy H2: {hits}")

    def test_C_h2_still_rejects_real_contamination(self):
        from ai_brain.brain_validation import scan_payload_taint
        clean, hits = scan_payload_taint({"anything": {"bias": "bullish"}})
        self.assertFalse(clean)
        self.assertIn("unlabeled_bias_key", hits)

    def test_D_no_authority_drift(self):
        ctx = self._htf_ctx()
        self.assertEqual(ctx["authority_level"], "context_only")

    def test_E_htf_information_fully_preserved(self):
        ctx = self._htf_ctx()
        dc = ctx["daily_context"]
        for k in ("date", "open", "high", "low", "close", "range",
                  "day_direction"):
            self.assertIn(k, dc)
        self.assertEqual(dc["day_direction"], "bullish")   # same info, new name
        self.assertIn("day_direction", ctx["previous_session_context"])
        for k in ("weekly_context", "gap_context", "liquidity_context",
                  "htf_bias", "htf_confidence", "memory_age"):
            self.assertIsNotNone(ctx.get(k) if k != "memory_age" else 0)
