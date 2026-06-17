"""
DEPLOY-2C — Topstep runtime execution wiring.

Proves the Topstep runtime path is Alpaca-free and safe-by-default: execution off
unless explicitly enabled, practice/sim only, no bracket faking, read-only
reconciliation that writes no scar, MNQU not QQQ, and no Alpaca dependency — while
Maurice's Alpaca paper path is preserved.
"""
import inspect
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

from broker.runtime import (
    get_runtime, TopstepRuntime, AlpacaPaperRuntime,
)
from deployment.instance_config import InstanceConfig

_TOPSTEP_FLAGS = ("TOPSTEP_EXECUTION_ENABLED", "TOPSTEP_PRACTICE_ONLY",
                  "TOPSTEP_ALLOW_UNBRACKETED_ENTRY")
_ALPACA_ENV = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")


class FakeAdapter:
    def __init__(self, practice=True, simulated=True, connected=True,
                 positions=None, orders=None, submit=None):
        self._practice, self._sim, self._conn = practice, simulated, connected
        self._positions = positions or []
        self._orders = orders or []
        self._submit = submit if submit is not None else {"ok": True, "orderId": "TS-1"}
        self.submitted = []

    def _is_practice(self): return self._practice
    def _resolve_account(self): return {"id": 99, "simulated": self._sim}
    def get_account(self): return {"connected": self._conn, "simulated": self._sim, "account_id": "PRAC-1"}
    def get_positions(self): return list(self._positions)
    def get_open_orders(self): return list(self._orders)
    def submit_order(self, order): self.submitted.append(order); return self._submit
    def cancel_order(self, oid): return {"ok": True}
    def flatten_position(self, cid): return {"ok": True}

    @property
    def client(self):
        orders = self._orders
        return SimpleNamespace(
            search_trades=lambda *a, **k: [],
            search_orders=lambda *a, **k: list(orders),
            search_contract=lambda *a, **k: [{"id": "C", "name": "MNQU"}])


def _topstep_runtime(adapter=None, config=None):
    """Build a TopstepRuntime with a fake adapter (no network, no real ProjectX)."""
    rt = TopstepRuntime.__new__(TopstepRuntime)
    rt.symbol = "MNQU"
    rt.config = config
    rt.adapter = adapter or FakeAdapter()
    return rt


def _decision_snapshot(direction="bullish", allowed=True):
    return {"playbook": {"direction": direction, "selected_playbook": "expansion_continuation"},
            "qualification": {"status": "valid_setup", "direction": direction},
            "risk": {"trade_allowed": allowed}}


class _EnvSandbox(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _TOPSTEP_FLAGS + _ALPACA_ENV}
        for k in _TOPSTEP_FLAGS + _ALPACA_ENV:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestRuntimeSelection(_EnvSandbox):
    def test_11_maurice_alpaca_runtime(self):
        self.assertIsInstance(get_runtime("alpaca_paper"), AlpacaPaperRuntime)

    def test_topstep_runtime_selected(self):
        rt = get_runtime("topstep", "MNQU", SimpleNamespace(contract_size=1))
        self.assertIsInstance(rt, TopstepRuntime)
        self.assertNotIsInstance(rt, AlpacaPaperRuntime)

    def test_1_13_topstep_runtime_needs_no_alpaca_env(self):
        # No ALPACA_* present; constructing/using the topstep runtime still works.
        self.assertIsNone(os.environ.get("ALPACA_API_KEY"))
        rt = _topstep_runtime(config=SimpleNamespace(contract_size=2, execution_enabled=False))
        out = rt.run_cycle(_decision_snapshot(), "MNQU")
        self.assertEqual(out["provider"], "topstep")


class TestExecutionGates(_EnvSandbox):
    def test_5_execution_disabled_by_default(self):
        rt = _topstep_runtime(config=SimpleNamespace(execution_enabled=False, contract_size=1))
        self.assertFalse(rt.is_execution_enabled())

    def test_6_disabled_observes_no_order(self):
        rt = _topstep_runtime(config=SimpleNamespace(execution_enabled=False, contract_size=1))
        res = rt.submit_order({"side": "buy", "qty": 1})
        self.assertFalse(res["placed"])
        self.assertEqual(res["action"], "observe")
        self.assertIn("would", res)
        out = rt.run_cycle(_decision_snapshot(), "MNQU")
        self.assertEqual(out["mode"], "observe")
        self.assertEqual(rt.adapter.submitted, [])      # nothing placed

    def test_7_enabled_but_not_practice_is_blocked(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        os.environ["TOPSTEP_PRACTICE_ONLY"] = "true"
        adapter = FakeAdapter(practice=False, simulated=False)   # live/funded-like
        rt = _topstep_runtime(adapter, SimpleNamespace(execution_enabled=True, contract_size=1))
        res = rt.submit_order({"side": "buy", "qty": 1})
        self.assertFalse(res["placed"])
        self.assertEqual(res["action"], "blocked")
        self.assertIn("practice", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_8_no_plan_no_bracket_no_trade(self):
        # DEPLOY-2D RULE #1: enabled+practice but no trade plan/bracket → blocked.
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        adapter = FakeAdapter(practice=True, simulated=True)
        rt = _topstep_runtime(adapter, SimpleNamespace(execution_enabled=True, contract_size=1))
        res = rt.submit_order({"side": "buy", "qty": 1})   # no snapshot → no plan
        self.assertFalse(res["placed"])
        self.assertIn("no_trade_plan", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_8b_unbracketed_override_removed(self):
        # RULE #1: the legacy override no longer exists — setting it does nothing.
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        os.environ["TOPSTEP_PRACTICE_ONLY"] = "true"
        os.environ["TOPSTEP_ALLOW_UNBRACKETED_ENTRY"] = "true"   # legacy; must be ignored
        adapter = FakeAdapter(practice=True, simulated=True)
        rt = _topstep_runtime(adapter, SimpleNamespace(execution_enabled=True, contract_size=1))
        res = rt.submit_order({"side": "buy", "qty": 1})   # still no plan → still blocked
        self.assertFalse(res["placed"])
        self.assertEqual(adapter.submitted, [])
        # and the override token is gone from the source entirely
        with open(os.path.join(_ROOT, "src", "broker", "runtime.py"), encoding="utf-8") as fh:
            self.assertNotIn("TOPSTEP_ALLOW_UNBRACKETED_ENTRY", fh.read())


def _toolbox_snapshot(entry=None, stop=None, pref="fvg",
                      with_tool=True, with_candidate=True, with_price_level=True):
    """Build a snapshot whose toolbox plan source is selectively incomplete, to
    drive each precise no_trade_plan reason."""
    cand = {"tool": pref}
    if with_price_level:
        pl = {}
        if entry is not None:
            pl["midpoint"] = entry
        if stop is not None:
            pl["invalidation_level"] = stop
        cand["price_level"] = pl
    tb = {"preferred_tool": pref if with_tool else None,
          "tool_candidates": [cand] if with_candidate else []}
    return {"toolbox": tb}


class TestTradePlanDiagnostics(_EnvSandbox):
    """Every block names the EXACT missing field; no broker call on incomplete plan;
    a complete plan routes a native bracket with positive ticks. No synthetic stop."""

    def _rt(self):
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        adapter = FakeAdapter(practice=True, simulated=True)
        rt = _topstep_runtime(adapter, SimpleNamespace(execution_enabled=True, contract_size=1))
        return rt, adapter

    def _buy(self):
        return {"side": "buy", "qty": 1}

    def test_missing_stop_blocks_and_names_invalidation(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(), _toolbox_snapshot(entry=20000.0, stop=None))
        self.assertFalse(res["placed"])
        self.assertIn("no_trade_plan", res["reason"])
        self.assertIn("stop", res["reason"])
        self.assertIn("invalidation_level", res["reason"])
        self.assertEqual(adapter.submitted, [])          # no broker call

    def test_missing_entry_blocks_and_names_entry(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(), _toolbox_snapshot(entry=None, stop=19990.0))
        self.assertFalse(res["placed"])
        self.assertIn("entry unavailable", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_no_preferred_tool_blocks_and_names_it(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(),
                              _toolbox_snapshot(entry=20000.0, stop=19990.0, with_tool=False))
        self.assertFalse(res["placed"])
        self.assertIn("preferred_tool", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_no_toolbox_blocks(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(), {})
        self.assertIn("toolbox absent", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_zero_risk_distance_blocks(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(), _toolbox_snapshot(entry=20000.0, stop=20000.0))
        self.assertFalse(res["placed"])
        self.assertIn("zero risk distance", res["reason"])
        self.assertEqual(adapter.submitted, [])

    def test_complete_plan_routes_native_bracket_positive_ticks(self):
        rt, adapter = self._rt()
        res = rt.submit_order(self._buy(), _toolbox_snapshot(entry=20000.0, stop=19990.0))
        self.assertTrue(res["placed"])
        self.assertEqual(len(adapter.submitted), 1)       # broker called once
        order = adapter.submitted[0]
        self.assertIn("stopLossBracket", order)
        self.assertIn("takeProfitBracket", order)
        self.assertGreater(order["stopLossBracket"]["ticks"], 0)
        self.assertGreater(order["takeProfitBracket"]["ticks"], 0)
        self.assertEqual(order["stopLossBracket"]["type"], 4)   # Stop
        self.assertEqual(order["takeProfitBracket"]["type"], 1)  # Limit

    def test_complete_plan_only_after_execution_and_practice_gates(self):
        # gates still precede the plan: execution off → observe, not a plan error
        rt = _topstep_runtime(FakeAdapter(practice=True),
                              SimpleNamespace(execution_enabled=False, contract_size=1))
        res = rt.submit_order(self._buy(), _toolbox_snapshot(entry=20000.0, stop=19990.0))
        self.assertEqual(res["action"], "observe")
        self.assertFalse(res["placed"])


class TestReconciliation(_EnvSandbox):
    def test_9_reconcile_reads_account_positions_orders(self):
        adapter = FakeAdapter(positions=[{"id": 1}, {"id": 2}], orders=[{"id": 9}])
        rt = _topstep_runtime(adapter, SimpleNamespace(contract_size=1))
        rec = rt.reconcile()
        self.assertEqual(rec["provider"], "topstep")
        self.assertEqual(rec["status"], "reconciled")     # used Trade/search + Order/search
        self.assertEqual(rec["open_positions"], 2)
        self.assertEqual(rec["open_orders"], 1)
        self.assertTrue(rec["account"]["connected"])

    def test_4_10_reconcile_no_alpaca_no_scar_when_no_closed(self):
        # No closed trades (Trade/search empty) → zero scars, never touches Alpaca.
        adapter = FakeAdapter(positions=[], orders=[])
        rt = _topstep_runtime(adapter, SimpleNamespace(contract_size=1))
        rec = rt.reconcile()
        self.assertEqual(rec["provider"], "topstep")
        self.assertEqual(rec["closed_trades"], 0)
        self.assertEqual(rec["scars_written"], 0)


class TestNoAlpacaCoupling(unittest.TestCase):
    def _src(self, rel):
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_3_topstep_loop_has_no_alpaca_import(self):
        # Doctrine prose may name Alpaca/paper_execution (to say they're excluded);
        # the real check is that no IMPORT line pulls them in.
        src = self._src(os.path.join("src", "live_scan", "topstep_scan_loop.py"))
        imports = [l for l in src.splitlines() if l.lstrip().startswith(("import ", "from "))]
        joined = "\n".join(imports)
        for forbidden in ("alpaca", "paper_execution"):
            self.assertNotIn(forbidden, joined, f"topstep loop imports {forbidden}")

    def test_4_topstep_runtime_class_has_no_paper_execution(self):
        src = self._src(os.path.join("src", "broker", "runtime.py"))
        # isolate the TopstepRuntime class body
        ts = src.split("class TopstepRuntime")[1].split("def get_runtime")[0]
        self.assertNotIn("paper_execution", ts)
        self.assertNotIn("alpaca", ts.lower())
        self.assertNotIn("record_closed_trade_scar", ts)   # writes no scar


class TestInstanceConfig(unittest.TestCase):
    def test_topstep_resolves_topstep_execution(self):
        cfg = InstanceConfig.load(os.path.join(_ROOT, "instances", "templates", "topstep_150k.yaml"))
        self.assertEqual(cfg.resolved_execution_provider(), "topstep")
        self.assertEqual(cfg.symbol, "MNQU")
        self.assertTrue(cfg.practice_only)
        self.assertFalse(cfg.execution_enabled)

    def test_12_no_qqq_in_topstep_config(self):
        for name in ("topstep_150k", "topstep_50k"):
            cfg = InstanceConfig.load(os.path.join(_ROOT, "instances", "templates", f"{name}.yaml"))
            self.assertNotEqual(cfg.symbol, "QQQ")
            self.assertEqual(cfg.symbol, "MNQU")

    def test_maurice_resolves_alpaca_paper(self):
        cfg = InstanceConfig.load(os.path.join(_ROOT, "instances", "templates", "paper.yaml"))
        self.assertEqual(cfg.resolved_execution_provider(), "alpaca_paper")
        self.assertEqual(cfg.symbol, "QQQ")

    def test_validate_rejects_topstep_with_alpaca_execution(self):
        cfg = InstanceConfig.from_dict({"instance_id": "x", "broker": "topstep",
                                        "execution_provider": "alpaca_paper", "symbol": "MNQU"})
        self.assertTrue(any("alpaca_paper execution_provider" in p for p in cfg.validate()))


class TestScanRouting(_EnvSandbox):
    def test_2_topstep_loop_uses_topstep_provider_and_mnqu(self):
        import live_scan.topstep_scan_loop as L
        os.environ["MAX_SCAN_ITERATIONS"] = "1"
        os.environ["SCAN_INTERVAL_SECONDS"] = "0"
        calls = {}

        class FakeProvider:
            def fetch_1m_candles(self, symbol, lookback):
                calls["fetch"] = (symbol, lookback); return []

        fake_runtime = SimpleNamespace(
            is_execution_enabled=lambda: False,
            run_cycle=lambda snap, sym: {"mode": "observe", "account_ok": False,
                                         "practice_safe": True,
                                         "decision": {"direction": "neutral"},
                                         "order_action": "none", "order_result": {"reason": ""}})
        def _fake_get_provider(name):
            calls["provider"] = name
            return FakeProvider()

        with mock.patch.object(L, "get_provider", _fake_get_provider), \
             mock.patch.object(L, "build_timeframes", lambda c: {}), \
             mock.patch.object(L, "build_snapshot", lambda *a, **k: {}), \
             mock.patch.object(L, "get_runtime", lambda *a, **k: fake_runtime), \
             mock.patch.object(L, "Po3StabilityManager", lambda: None):
            L.run_topstep_scan_loop(symbol="MNQU", data_provider="topstep")
        self.assertEqual(calls["provider"], "topstep")
        self.assertEqual(calls["fetch"], ("MNQU", 300))
        os.environ.pop("MAX_SCAN_ITERATIONS", None)
        os.environ.pop("SCAN_INTERVAL_SECONDS", None)

    def test_1_run_instance_routes_topstep(self):
        from run_instance import resolve_start_params
        cfg = InstanceConfig.from_dict({"instance_id": "tiona_topstep", "broker": "topstep",
                                        "data_provider": "topstep", "execution_provider": "topstep",
                                        "symbol": "MNQU"})
        symbol, dp = resolve_start_params(SimpleNamespace(config=cfg))
        self.assertEqual(symbol, "MNQU")
        self.assertEqual(dp, "topstep")
        self.assertEqual(cfg.resolved_execution_provider(), "topstep")

    def test_11_run_scan_loop_signature_intact(self):
        from live_scan.scan_loop import run_scan_loop
        params = inspect.signature(run_scan_loop).parameters
        self.assertIn("symbol", params)
        self.assertIn("data_provider", params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
