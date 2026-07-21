"""
Phase DEPLOY-1 — Cloneable multi-instance architecture tests.

Covers config, runtime context, path isolation, broker adapters, the clone
command, and the Phase-10 independence test (two instances, same input, no
cross-contamination; modifying Bot A's memory does not reach Bot B).
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from deployment.instance_config import InstanceConfig
from deployment.instance_context import InstanceContext, current
from deployment.data_paths import resolve, SUBSYSTEM_ENV
from broker.factory import get_adapter, available_brokers
from broker.base import NotConnectedError
from news.news_memory import NewsMemory, NewsMemoryRecord
import paper_execution.trade_journal as tj

_ISOLATED_ENV = list(SUBSYSTEM_ENV.values()) + ["BOT_INSTANCE_ID"]


def _clean_env():
    for v in _ISOLATED_ENV:
        os.environ.pop(v, None)


def _cfg(instance_id, root, **kw):
    base = os.path.join(root, instance_id)
    return InstanceConfig(instance_id=instance_id,
                          memory_path=os.path.join(base, "memory"),
                          vector_store_path=os.path.join(base, "vector_store"),
                          journal_path=os.path.join(base, "journal"),
                          log_path=os.path.join(base, "logs"),
                          state_path=os.path.join(base, "state"),
                          news_memory_path=os.path.join(base, "news_memory"),
                          **kw)


# ── Phase 2 — config ──────────────────────────────────────────────────────────
class TestInstanceConfig(unittest.TestCase):
    def test_defaults_isolated_per_instance(self):
        a = InstanceConfig(instance_id="aaa")
        b = InstanceConfig(instance_id="bbb")
        self.assertIn("aaa", a.journal_path)
        self.assertIn("bbb", b.journal_path)
        self.assertNotEqual(a.vector_store_path, b.vector_store_path)

    def test_roundtrip_yaml(self):
        d = tempfile.mkdtemp()
        cfg = InstanceConfig(instance_id="rt", owner_name="Maurice", broker="tradestation")
        cfg.risk_profile.max_daily_loss = 750
        path = os.path.join(d, "config.yaml")
        cfg.save(path)
        loaded = InstanceConfig.load(path)
        self.assertEqual(loaded.owner_name, "Maurice")
        self.assertEqual(loaded.broker, "tradestation")
        self.assertEqual(loaded.risk_profile.max_daily_loss, 750)

    def test_live_mode_rejected(self):
        cfg = InstanceConfig(instance_id="x", execution_mode="live")
        self.assertTrue(any("live" in p for p in cfg.validate()))


# ── Phase 3 — runtime context & path isolation ────────────────────────────────
class TestInstanceContext(unittest.TestCase):
    def setUp(self): _clean_env()
    def tearDown(self): _clean_env()

    def test_activate_redirects_env(self):
        root = tempfile.mkdtemp()
        ctx = InstanceContext(_cfg("inst1", root))
        with ctx:
            self.assertIs(current(), ctx)
            self.assertIn("inst1", os.environ["PAPER_TRADES_DIR"])
            self.assertIn("inst1", os.environ["AI_RETRIEVAL_DIR"])
            self.assertEqual(os.environ["BOT_INSTANCE_ID"], "inst1")
        # restored after context exit
        self.assertIsNone(current())
        self.assertNotIn("PAPER_TRADES_DIR", os.environ)

    def test_journal_dir_follows_active_instance(self):
        root = tempfile.mkdtemp()
        with InstanceContext(_cfg("ja", root)):
            self.assertIn(os.path.join("ja", "journal"), tj._trades_dir())
        with InstanceContext(_cfg("jb", root)):
            self.assertIn(os.path.join("jb", "journal"), tj._trades_dir())

    def test_legacy_default_when_no_instance(self):
        # regression-safe: env unset ⇒ resolver returns the module's legacy
        # default unchanged; setting the env var overrides it per-instance.
        os.environ.pop("PAPER_TRADES_DIR", None)
        self.assertEqual(tj._trades_dir(), tj._TRADES_DIR)
        os.environ["PAPER_TRADES_DIR"] = os.path.join("x", "inst", "journal")
        self.assertEqual(tj._trades_dir(), os.path.join("x", "inst", "journal"))
        os.environ.pop("PAPER_TRADES_DIR", None)


# ── Phase 7 — broker adapters ─────────────────────────────────────────────────
class TestBrokerAdapters(unittest.TestCase):
    def test_factory_maps_brokers(self):
        self.assertEqual(get_adapter(broker="paper").name, "paper")
        self.assertEqual(get_adapter(broker="tradestation").name, "tradestation")
        self.assertEqual(get_adapter(broker="unknown").name, "paper")  # safe default

    def test_available(self):
        # ninjatrader registered by NINJATRADER-MNQ-INTEGRATION-FOUNDATION
        # (DEMO8458533 MNQ, DISARMED); default remains paper.
        self.assertEqual(set(available_brokers()),
                         {"paper", "tradestation", "ninjatrader"})

    def test_stub_adapters_not_connected_and_refuse(self):
        for b in ("tradestation",):
            a = get_adapter(broker=b)
            self.assertFalse(a.is_connected())
            with self.assertRaises(NotConnectedError):
                a.submit_order({"symbol": "QQQ", "qty": 1})

    def test_core_is_broker_agnostic(self):
        cfg = InstanceConfig(instance_id="z", broker="tradestation", account_id="TS1")
        a = get_adapter(cfg)
        self.assertEqual(a.account_id, "TS1")
        self.assertIn("name", a.describe())


# ── Phase 10 — independence test ──────────────────────────────────────────────
class TestIndependence(unittest.TestCase):
    def setUp(self): _clean_env()
    def tearDown(self): _clean_env()

    def test_two_instances_no_cross_contamination(self):
        root = tempfile.mkdtemp()
        ctx_a = InstanceContext(_cfg("test_bot_a", root))
        ctx_b = InstanceContext(_cfg("test_bot_b", root))

        # same "market input" → each writes only to its OWN journal + memory
        rec = {"trade_id": "T1", "symbol": "QQQ", "side": "long", "status": "submitted"}
        with ctx_a:
            tj.append_trade(dict(rec, trade_id="A1"), "QQQ")
            NewsMemory().record(NewsMemoryRecord(event="CPI", market_response="A-rallied"))
        with ctx_b:
            tj.append_trade(dict(rec, trade_id="B1"), "QQQ")
            NewsMemory().record(NewsMemoryRecord(event="CPI", market_response="B-dumped"))

        # journals are separate
        with ctx_a:
            a_trades = tj.load_today_trades("QQQ")
        with ctx_b:
            b_trades = tj.load_today_trades("QQQ")
        a_ids = {t["trade_id"] for t in a_trades}
        b_ids = {t["trade_id"] for t in b_trades}
        self.assertIn("A1", a_ids)
        self.assertIn("B1", b_ids)
        self.assertNotIn("B1", a_ids)   # A cannot see B's trade
        self.assertNotIn("A1", b_ids)   # B cannot see A's trade

        # separate state dirs on disk, no overlap
        self.assertNotEqual(ctx_a.paths["journal"], ctx_b.paths["journal"])
        self.assertNotEqual(ctx_a.paths["vector_store"], ctx_b.paths["vector_store"])
        self.assertNotEqual(ctx_a.paths["news_memory"], ctx_b.paths["news_memory"])

    def test_modifying_bot_a_memory_not_seen_by_b(self):
        root = tempfile.mkdtemp()
        ctx_a = InstanceContext(_cfg("test_bot_a", root))
        ctx_b = InstanceContext(_cfg("test_bot_b", root))
        with ctx_a:
            NewsMemory().record(NewsMemoryRecord(event="FOMC", market_response="A-only"))
            self.assertEqual(len(NewsMemory().by_event("FOMC")), 1)
        with ctx_b:
            self.assertEqual(len(NewsMemory().by_event("FOMC")), 0)   # B unaffected

    def test_divergence_config_is_per_instance(self):
        a = InstanceConfig(instance_id="da")
        b = InstanceConfig(instance_id="db")
        a.divergence.confidence_calibration = 1.3
        b.divergence.confidence_calibration = 0.8
        self.assertNotEqual(a.divergence.confidence_calibration,
                            b.divergence.confidence_calibration)


# ── Phase 4 — global vs instance memory ───────────────────────────────────────
class TestGlobalMemory(unittest.TestCase):
    def test_rejects_instance_scoped_payload(self):
        from deployment import global_memory
        # broad lesson ok
        self.assertTrue(global_memory.record_lesson("news raises whipsaw risk", ["news"]))
        # instance-scoped data refused
        self.assertFalse(global_memory.record_lesson("bad", extra={"trade_id": "T1"}))
        self.assertFalse(global_memory.record_lesson("bad", extra={"account_id": "A1"}))


# ── Phase 8 — clone command ───────────────────────────────────────────────────
class TestCloneCommand(unittest.TestCase):
    def setUp(self): _clean_env()
    def tearDown(self): _clean_env()

    def test_create_instance_builds_isolated_tree(self):
        import importlib.util
        root = tempfile.mkdtemp()
        tool = os.path.join(os.path.dirname(__file__), "..", "tools", "create_instance.py")
        spec = importlib.util.spec_from_file_location("create_instance", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(["--template", "paper", "--instance", "clone_test",
                       "--owner", "Maurice", "--instances-root", root])
        self.assertEqual(rc, 0)
        inst = os.path.join(root, "clone_test")
        self.assertTrue(os.path.exists(os.path.join(inst, "config.yaml")))
        ctx = InstanceContext.for_instance("clone_test", instances_root=root)
        for p in ctx.paths.values():
            self.assertTrue(os.path.isdir(p), f"missing isolated dir: {p}")
            # every isolated path must carry the instance_id (no shared collapse)
            self.assertIn("clone_test", p, f"instance_id missing from path: {p}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
