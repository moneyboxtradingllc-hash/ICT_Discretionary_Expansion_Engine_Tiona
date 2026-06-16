"""
DEPLOY-2A/2B — Topstep data-feed cleanup + MNQU.

Proves the Topstep deployment path uses a Topstep market-data provider for MNQU,
never instantiates Alpaca, never requires Alpaca env, never defaults to QQQ, and
fails with a clear Topstep error when the feed is missing — while Maurice's QQQ
paper path still resolves Alpaca. Network is mocked.
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

from data_feed import get_provider
from data_feed.provider_interface import DataFeedError
from data_feed.alpaca_provider import AlpacaProvider
from data_feed.topstep_provider import TopstepBarsProvider
from deployment.instance_config import InstanceConfig

_TOPSTEP_ENV = ("PROJECTX_TOPSTEPX_API_KEY", "PROJECTX_TOPSTEPX_USERNAME",
                "PROJECTX_TOPSTEPX_BASE_URL", "TOPSTEP_API_KEY", "TOPSTEP_USERNAME")
_ALPACA_ENV = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")

_FAKE_BARS = [
    {"t": "2026-06-16T14:30:00+00:00", "o": 20100.0, "h": 20110.0, "l": 20095.0, "c": 20105.0, "v": 1200},
    {"t": "2026-06-16T14:31:00+00:00", "o": 20105.0, "h": 20120.0, "l": 20104.0, "c": 20118.0, "v": 1500},
]


class _EnvSandbox(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _TOPSTEP_ENV + _ALPACA_ENV + ("DATA_PROVIDER",)}
        for k in _TOPSTEP_ENV + _ALPACA_ENV + ("DATA_PROVIDER",):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _set_topstep_creds(self):
        os.environ["PROJECTX_TOPSTEPX_USERNAME"] = "TionaRivera"
        os.environ["PROJECTX_TOPSTEPX_API_KEY"] = "fake-key"

    def _patch_topstep_client(self):
        return mock.patch.multiple(
            "broker.topstep_adapter.TopstepClient",
            authenticate=lambda self: {"ok": True},
            search_contract=lambda self, symbol, live=False: [{"id": "CON.F.US.MNQ.U25", "name": symbol}],
            retrieve_bars=lambda self, contract_id, **kw: list(_FAKE_BARS),
        )


class TestProviderRouting(_EnvSandbox):
    def test_1_topstep_uses_topstep_provider(self):
        self._set_topstep_creds()
        with self._patch_topstep_client():
            p = get_provider("topstep")
        self.assertIsInstance(p, TopstepBarsProvider)

    def test_2_topstep_does_not_instantiate_alpaca(self):
        self._set_topstep_creds()
        with self._patch_topstep_client():
            p = get_provider("topstep")
        self.assertNotIsInstance(p, AlpacaProvider)

    def test_3_topstep_does_not_require_alpaca_env(self):
        # No ALPACA_* present at all (sandbox cleared them); topstep still works.
        self.assertIsNone(os.environ.get("ALPACA_API_KEY"))
        self._set_topstep_creds()
        with self._patch_topstep_client():
            p = get_provider("topstep")
        self.assertIsInstance(p, TopstepBarsProvider)

    def test_5_topstep_fails_clearly_when_feed_missing(self):
        # No topstep creds → clear Topstep error, NOT the Alpaca key error.
        with self.assertRaises(DataFeedError) as ctx:
            get_provider("topstep")
        msg = str(ctx.exception)
        self.assertIn("Topstep data feed unavailable", msg)
        self.assertNotIn("ALPACA_API_KEY", msg)   # did not fall into the Alpaca path

    def test_6_maurice_alpaca_path_intact(self):
        # alpaca path still resolves; with no keys it raises the ALPACA-specific
        # error (proves the alpaca branch is intact and distinct from topstep).
        with self.assertRaises(DataFeedError) as ctx:
            get_provider("alpaca")
        self.assertIn("ALPACA_API_KEY", str(ctx.exception))

    def test_unknown_provider_no_alpaca_fallback(self):
        with self.assertRaises(DataFeedError) as ctx:
            get_provider("bogus")
        self.assertIn("Unknown DATA_PROVIDER", str(ctx.exception))


class TestTopstepFetch(_EnvSandbox):
    def test_fetch_returns_candle_contract_for_mnqu(self):
        self._set_topstep_creds()
        with self._patch_topstep_client():
            p = get_provider("topstep")
            candles = p.fetch_1m_candles("MNQU", 300)
        self.assertEqual(len(candles), 2)
        c = candles[0]
        for k in ("timestamp", "open", "high", "low", "close", "volume"):
            self.assertIn(k, c)
        self.assertEqual(c["open"], 20100.0)
        # oldest-first
        self.assertLessEqual(candles[0]["timestamp"], candles[1]["timestamp"])

    def test_4_no_qqq_default_on_topstep(self):
        # empty symbol must NOT silently become QQQ — it must error
        self._set_topstep_creds()
        with self._patch_topstep_client():
            p = get_provider("topstep")
            with self.assertRaises(DataFeedError) as ctx:
                p.fetch_1m_candles("", 300)
        self.assertIn("no QQQ default", str(ctx.exception))


class TestInstanceConfig(unittest.TestCase):
    def _topstep_cfg(self):
        return InstanceConfig.from_dict({
            "instance_id": "tiona_topstep", "broker": "topstep",
            "data_provider": "topstep", "symbol": "MNQU",
        })

    def test_4_symbol_mnqu_not_qqq(self):
        cfg = self._topstep_cfg()
        self.assertEqual(cfg.symbol, "MNQU")
        self.assertNotEqual(cfg.symbol, "QQQ")
        self.assertEqual(cfg.resolved_data_provider(), "topstep")

    def test_topstep_broker_derives_topstep_provider(self):
        cfg = InstanceConfig.from_dict({"instance_id": "x", "broker": "topstep", "symbol": "MNQU"})
        self.assertEqual(cfg.resolved_data_provider(), "topstep")  # derived, no explicit field

    def test_validate_rejects_topstep_with_alpaca(self):
        cfg = InstanceConfig.from_dict({"instance_id": "x", "broker": "topstep",
                                        "data_provider": "alpaca", "symbol": "MNQU"})
        self.assertTrue(any("topstep broker must not use the alpaca" in p for p in cfg.validate()))

    def test_paper_still_alpaca_qqq(self):
        cfg = InstanceConfig.from_dict({"instance_id": "m", "broker": "paper", "symbol": "QQQ"})
        self.assertEqual(cfg.resolved_data_provider(), "alpaca")
        self.assertEqual(cfg.symbol, "QQQ")

    def test_templates_on_disk_are_clean(self):
        for name in ("topstep_150k", "topstep_50k"):
            cfg = InstanceConfig.load(os.path.join(_ROOT, "instances", "templates", f"{name}.yaml"))
            self.assertEqual(cfg.broker, "topstep")
            self.assertEqual(cfg.symbol, "MNQU", f"{name} symbol must be MNQU")
            self.assertEqual(cfg.resolved_data_provider(), "topstep")


class TestRunInstanceRouting(unittest.TestCase):
    def test_7_topstep_routes_to_topstep_provider(self):
        from run_instance import resolve_start_params
        cfg = InstanceConfig.from_dict({"instance_id": "tiona_topstep", "broker": "topstep",
                                        "data_provider": "topstep", "symbol": "MNQU"})
        ctx = SimpleNamespace(config=cfg)
        symbol, dp = resolve_start_params(ctx)
        self.assertEqual(symbol, "MNQU")
        self.assertEqual(dp, "topstep")

    def test_maurice_routes_to_alpaca(self):
        from run_instance import resolve_start_params
        cfg = InstanceConfig.from_dict({"instance_id": "maurice", "broker": "paper", "symbol": "QQQ"})
        ctx = SimpleNamespace(config=cfg)
        symbol, dp = resolve_start_params(ctx)
        self.assertEqual((symbol, dp), ("QQQ", "alpaca"))


class TestScanLoopInjection(unittest.TestCase):
    def test_8_scan_loop_accepts_symbol_and_provider(self):
        from live_scan.scan_loop import run_scan_loop
        params = inspect.signature(run_scan_loop).parameters
        self.assertIn("symbol", params)
        self.assertIn("data_provider", params)
        # binding the injected args must not raise (we do not invoke the loop)
        bound = inspect.signature(run_scan_loop).bind(symbol="MNQU", data_provider="topstep")
        self.assertEqual(bound.arguments["data_provider"], "topstep")


class TestNoAlpacaCoupling(unittest.TestCase):
    def test_topstep_provider_has_no_alpaca_coupling(self):
        # Doctrine comments may *mention* Alpaca (to say it's excluded); what must
        # be absent is any Alpaca IMPORT or ALPACA_* env READ.
        with open(os.path.join(_ROOT, "src", "data_feed", "topstep_provider.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("alpaca_provider", src)          # no import of the alpaca module
        self.assertNotIn("AlpacaProvider", src)
        self.assertNotIn('getenv("ALPACA', src)           # no ALPACA_* env read
        self.assertNotIn("getenv('ALPACA", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
