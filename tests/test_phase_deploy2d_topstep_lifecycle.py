"""
DEPLOY-2D — Topstep reconciliation + bracket execution + adaptive scars.

Proves the full Topstep lifecycle on Topstep infrastructure only:
  no bracket → no trade; bracket order routes with native stopLoss/takeProfit;
  Trade/search reconciliation finds fills + realized PnL; realized R is computed
  correctly; a CLOSED trade writes an adaptive scar; an OPEN trade does not;
  Maurice's Alpaca path is untouched; the Topstep path imports no Alpaca; and
  practice-only / execution-off defaults remain. Network mocked.
"""
import inspect
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

from broker.runtime import TopstepRuntime, AlpacaPaperRuntime, get_runtime, _instrument_meta


class FakeClient:
    def __init__(self, trades=None, orders=None, contract_id="CON.F.US.MNQ.U25"):
        self._trades = trades or []
        self._orders = orders or []
        self._cid = contract_id
        self.placed = []
    def search_contract(self, symbol, live=False): return [{"id": self._cid, "name": symbol}]
    def search_trades(self, account_id, start, end=None): return list(self._trades)
    def search_orders(self, account_id, start, end=None): return list(self._orders)
    def place_order(self, body): self.placed.append(body); return {"orderId": 555, "success": True}


class FakeAdapter:
    def __init__(self, practice=True, simulated=True, connected=True,
                 positions=None, client=None, accept_orders=True):
        self._practice, self._sim, self._conn = practice, simulated, connected
        self._positions = positions or []
        self.client = client or FakeClient()
        self.submitted = []
        self._accept = accept_orders
    def _is_practice(self): return self._practice
    def _resolve_account(self): return {"id": 99, "simulated": self._sim}
    def get_account(self): return {"connected": self._conn, "simulated": self._sim, "account_id": 99}
    def get_positions(self): return list(self._positions)
    def get_open_orders(self): return []
    def submit_order(self, order):
        self.submitted.append(order)
        return self.client.place_order(order)


def _runtime(adapter=None, config=None, symbol="MNQU"):
    rt = TopstepRuntime.__new__(TopstepRuntime)
    rt.symbol = symbol
    rt.config = config or SimpleNamespace(execution_enabled=True, contract_size=1)
    rt.adapter = adapter or FakeAdapter()
    return rt


def _planned_snapshot(direction="bullish", entry=20000.0, stop=19990.0):
    return {
        "timestamp": "2026-06-16T15:30:00+00:00", "session": "afternoon",
        "market_regime": {"regime_label": "expansion_up", "volatility_state": "stable",
                          "expansion_state": "healthy_expansion"},
        "narrative_authority": {"active_liquidity_draw": "sell_side"},
        "ai_brain": {"output": {"narrative_phase": "distribution", "phase_confidence": 71,
                                "dominant_reasoning": "bullish continuation"}},
        "playbook": {"direction": direction, "selected_playbook": "expansion_continuation"},
        "qualification": {"status": "valid_setup", "direction": direction},
        "risk": {"trade_allowed": True},
        "toolbox": {"preferred_tool": "fvg",
                    "tool_candidates": [{"tool": "fvg",
                                         "price_level": {"midpoint": entry,
                                                         "invalidation_level": stop}}]},
    }


def _decision(side="buy", direction="bullish"):
    return {"side": side, "direction": direction, "actionable": True,
            "playbook": "expansion_continuation", "qty": 1}


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._saved = {k: os.environ.get(k) for k in
                       ("TOPSTEP_EXECUTION_ENABLED", "TOPSTEP_PRACTICE_ONLY",
                        "TOPSTEP_STATE_DIR", "AI_RETRIEVAL_DIR", "TAKE_PROFIT_R",
                        "ALPACA_API_KEY", "ALPACA_SECRET_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)
        os.environ["TOPSTEP_STATE_DIR"] = self._tmp
        os.environ["AI_RETRIEVAL_DIR"] = self._tmp

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestBracketExecution(_Sandbox):
    def test_1_no_bracket_no_trade(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        rt = _runtime()  # snapshot has no toolbox plan
        res = rt.submit_order(_decision(), {"toolbox": {}})
        self.assertFalse(res["placed"])
        self.assertIn("no_trade_plan", res["reason"])
        self.assertEqual(rt.adapter.submitted, [])

    def test_2_bracket_order_routes_with_native_legs(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        rt = _runtime(config=SimpleNamespace(execution_enabled=True, contract_size=1))
        res = rt.submit_order(_decision(), _planned_snapshot(entry=20000.0, stop=19990.0))
        self.assertTrue(res["placed"], res)
        order = rt.adapter.submitted[0]
        self.assertEqual(order["contractId"], "CON.F.US.MNQ.U25")
        self.assertIn("stopLossBracket", order)
        self.assertIn("takeProfitBracket", order)
        # risk 10pt / 0.25 tick = 40 ticks stop; 2R target = 80 ticks
        self.assertEqual(order["stopLossBracket"], {"ticks": 40, "type": 4})
        self.assertEqual(order["takeProfitBracket"], {"ticks": 80, "type": 1})

    def test_unknown_instrument_blocks(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        rt = _runtime(symbol="ZZZ9")   # no instrument metadata
        res = rt.submit_order(_decision(), _planned_snapshot())
        self.assertFalse(res["placed"])
        self.assertIn("unknown_instrument", res["reason"])


class TestRealizedR(unittest.TestCase):
    def test_5_realized_r_formula(self):
        # pnl 40, risk 10pt * $2 * 1 = $20 → R = 2.0
        self.assertEqual(TopstepRuntime._realized_r(40.0, 20000.0, 19990.0, 2.0, 1), 2.0)
        # loss: pnl -20 → R = -1.0
        self.assertEqual(TopstepRuntime._realized_r(-20.0, 20000.0, 19990.0, 2.0, 1), -1.0)
        # zero risk guarded
        self.assertIsNone(TopstepRuntime._realized_r(40.0, 20000.0, 20000.0, 2.0, 1))

    def test_mnq_instrument_meta(self):
        self.assertEqual(_instrument_meta("MNQU")["point_value"], 2.0)
        self.assertEqual(_instrument_meta("MNQU")["tick_size"], 0.25)
        self.assertIsNone(_instrument_meta("ZZZ"))


_CID = "CON.F.US.MNQ.U25"


def _exec(side, size, price, pnl=None, ts="2026-06-16T15:40:00+00:00", oid=1):
    return {"id": oid, "contractId": _CID, "side": side, "size": size, "price": price,
            "profitAndLoss": pnl, "voided": False, "creationTimestamp": ts, "orderId": oid}


def _journal_entry(ts="2026-06-16T15:30:00+00:00", oid=555, entry=20000.0, stop=19990.0):
    from broker.topstep_entry_store import record_entry
    record_entry({
        "provider": "topstep", "entry_key": f"{_CID}|{oid}|{ts}", "order_id": oid,
        "contract_id": _CID, "symbol": "MNQU", "timestamp": ts, "side": "buy",
        "entry_reference": entry, "stop_reference": stop, "target_price": entry + 20,
        "qty": 1, "point_value": 2.0,
        "market_regime_label": "expansion_up", "volatility_state": "stable",
        "expansion_state": "healthy_expansion",
        "narrative_direction_at_entry": "bullish", "narrative_phase_at_entry": "distribution",
        "ai_confidence_at_entry": 71, "liquidity_draw_at_entry": "sell_side",
        "snapshot_summary": {"session": "afternoon", "playbook": "expansion_continuation"},
        "ai_thesis_summary": "bullish continuation", "reconciled": False,
    })


class TestReconciliationAndScar(_Sandbox):
    def test_3_4_5_6_scenario_A_open_close_scars_once(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()
        execs = [_exec(0, 1, 20000.0, None, "2026-06-16T15:35:00+00:00"),   # open (buy)
                 _exec(1, 1, 20020.0, 40.0, "2026-06-16T15:45:00+00:00")]   # close (sell) +40
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["status"], "reconciled")
        self.assertEqual(rec["closed_trades"], 1)
        self.assertEqual(rec["scars_written"], 1)
        r0 = next(r for r in rec["results"] if r.get("matched"))
        self.assertEqual(r0["opened_size"], 1)
        self.assertEqual(r0["realized_pnl"], 40.0)
        self.assertEqual(r0["realized_r"], 2.0)            # 40 / (10pt*$2*1)
        recs = load_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["result"], "win")
        self.assertEqual(recs[0]["instrument"], "MNQU")
        self.assertTrue(recs[0]["is_authoritative"])

    def test_7_open_position_writes_no_scar(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()
        execs = [_exec(0, 1, 20000.0, None, "2026-06-16T15:35:00+00:00")]   # buy only → net 1
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["closed_trades"], 0)          # not flat → unsettled
        self.assertEqual(rec["scars_written"], 0)
        self.assertEqual(len(load_records()), 0)

    def test_dedup_and_lifecycle_on_rerun(self):
        from ai_retrieval.vector_store import load_records
        from broker.topstep_entry_store import load_entries
        _journal_entry()
        execs = [_exec(0, 1, 20000.0, None, "2026-06-16T15:35:00+00:00"),
                 _exec(1, 1, 20020.0, 40.0, "2026-06-16T15:45:00+00:00")]
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rt.reconcile()
        # entry is now marked reconciled (lifecycle state, not just dedup)
        self.assertTrue(all(e.get("reconciled") for e in load_entries()))
        rt.reconcile()      # rerun / restart
        self.assertEqual(len(load_records()), 1)


class TestSettlementScenarios(_Sandbox):
    def test_B_F_two_round_trips_two_scars(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry(ts="2026-06-16T15:30:00+00:00", oid=1, entry=20000.0, stop=19990.0)
        _journal_entry(ts="2026-06-16T16:00:00+00:00", oid=2, entry=20100.0, stop=20090.0)
        execs = [
            _exec(0, 1, 20000.0, None, "2026-06-16T15:35:00+00:00"),     # RT1 open
            _exec(1, 1, 20020.0, 40.0, "2026-06-16T15:45:00+00:00"),     # RT1 close +40
            _exec(0, 1, 20100.0, None, "2026-06-16T16:05:00+00:00"),     # RT2 open
            _exec(1, 1, 20090.0, -20.0, "2026-06-16T16:10:00+00:00"),    # RT2 close -20
        ]
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["closed_trades"], 2)
        self.assertEqual(rec["scars_written"], 2)          # BOTH trades scar'd (FIFO)
        recs = sorted(load_records(), key=lambda r: r["timestamp"])
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["result"], "win")         # RT1 +2R
        self.assertEqual(recs[1]["result"], "loss")        # RT2 -1R
        self.assertEqual(recs[1]["realized_r"], -1.0)

    def test_E_scale_out_one_round_trip_size_aware_r(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()
        execs = [
            _exec(0, 2, 20000.0, None, "2026-06-16T15:35:00+00:00"),     # open 2
            _exec(1, 1, 20010.0, 20.0, "2026-06-16T15:40:00+00:00"),     # scale-out 1 (+20)
            _exec(1, 1, 20020.0, 40.0, "2026-06-16T15:45:00+00:00"),     # final out 1 (+40)
        ]
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["closed_trades"], 1)          # ONE round-trip, not two
        self.assertEqual(rec["scars_written"], 1)
        r0 = next(r for r in rec["results"] if r.get("matched"))
        self.assertEqual(r0["opened_size"], 2)             # size-aware
        self.assertEqual(r0["realized_pnl"], 60.0)         # 20 + 40
        self.assertEqual(r0["realized_r"], 1.5)            # 60 / (10pt*$2*2 = $40)
        self.assertEqual(len(load_records()), 1)

    def test_D_scale_in_one_round_trip(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()
        execs = [
            _exec(0, 1, 20000.0, None, "2026-06-16T15:35:00+00:00"),     # open 1
            _exec(0, 1, 20010.0, None, "2026-06-16T15:38:00+00:00"),     # scale-in 1 (now 2)
            _exec(1, 2, 20030.0, 50.0, "2026-06-16T15:45:00+00:00"),     # close 2
        ]
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["closed_trades"], 1)
        self.assertEqual(rec["scars_written"], 1)
        r0 = next(r for r in rec["results"] if r.get("matched"))
        self.assertEqual(r0["opened_size"], 2)             # both scale-in lots
        self.assertEqual(r0["realized_pnl"], 50.0)
        self.assertEqual(len(load_records()), 1)

    def test_C_partial_open_no_settle_no_scar(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()
        execs = [
            _exec(0, 2, 20000.0, None, "2026-06-16T15:35:00+00:00"),     # open 2
            _exec(1, 1, 20010.0, 20.0, "2026-06-16T15:40:00+00:00"),     # partial out 1 → net 1
        ]
        rt = _runtime(adapter=FakeAdapter(client=FakeClient(trades=execs)))
        rec = rt.reconcile()
        self.assertEqual(rec["closed_trades"], 0)          # still open → NOT settled
        self.assertEqual(rec["scars_written"], 0)
        self.assertEqual(len(load_records()), 0)


class TestSilentFailures(_Sandbox):
    def test_trade_search_error_surfaced_no_scar(self):
        from ai_retrieval.vector_store import load_records
        _journal_entry()

        class ErrClient(FakeClient):
            def search_trades(self, *a, **k): raise RuntimeError("api down")
        rt = _runtime(adapter=FakeAdapter(client=ErrClient()))
        rec = rt.reconcile()
        self.assertEqual(rec["status"], "trade_search_error")   # surfaced, not silent
        self.assertTrue(any("trade_search_failed" in e for e in rec["errors"]))
        self.assertEqual(rec["scars_written"], 0)
        self.assertEqual(len(load_records()), 0)

    def test_entry_journal_failure_surfaced(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        rt = _runtime(config=SimpleNamespace(execution_enabled=True, contract_size=1))
        from unittest import mock
        # journaling fails → order still placed, but the failure is SURFACED loudly
        with mock.patch("broker.topstep_entry_store.record_entry", return_value=False):
            res = rt.submit_order(_decision(), _planned_snapshot())
        self.assertTrue(res["placed"])
        self.assertFalse(res["entry_journaled"])
        self.assertIn("entry_journal_failed", res["warning"])


class TestSafetyDefaults(_Sandbox):
    def test_10_practice_only_and_execution_off_default(self):
        rt = _runtime(config=SimpleNamespace(execution_enabled=False, contract_size=1))
        self.assertFalse(rt.is_execution_enabled())
        res = rt.submit_order(_decision(), _planned_snapshot())
        self.assertEqual(res["action"], "observe")
        self.assertEqual(rt.adapter.submitted, [])

    def test_enabled_but_not_practice_blocked(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        os.environ["TOPSTEP_PRACTICE_ONLY"] = "true"
        rt = _runtime(adapter=FakeAdapter(practice=False, simulated=False),
                      config=SimpleNamespace(execution_enabled=True, contract_size=1))
        res = rt.submit_order(_decision(), _planned_snapshot())
        self.assertFalse(res["placed"])
        self.assertIn("practice", res["reason"])


class TestNoAlpacaAndMauriceIntact(unittest.TestCase):
    def test_8_maurice_alpaca_runtime_and_signature(self):
        self.assertIsInstance(get_runtime("alpaca_paper"), AlpacaPaperRuntime)
        from live_scan.scan_loop import run_scan_loop
        self.assertIn("data_provider", inspect.signature(run_scan_loop).parameters)

    def test_9_topstep_runtime_no_alpaca_import(self):
        with open(os.path.join(_ROOT, "src", "broker", "runtime.py"), encoding="utf-8") as fh:
            src = fh.read()
        ts = src.split("class TopstepRuntime")[1].split("def get_runtime")[0]
        self.assertNotIn("alpaca", ts.lower())
        self.assertNotIn("paper_execution", ts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
