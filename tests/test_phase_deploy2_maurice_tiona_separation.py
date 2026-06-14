"""
Phase DEPLOY-2 — Maurice (Alpaca/QQQ) vs Tiona (Topstep) separation audit.

Reproducible proof of the 9 Phase-5 safety properties. Built from the COMMITTED
templates in a temp dir (so it passes on any checkout and never writes to the
real maurice_alpaca / tiona_topstep stores). The live audit of the actual
deployed instances is recorded in docs/deploy2_maurice_tiona_separation.md.

Maurice-style instance: paper adapter (= Alpaca paper), QQQ.
Tiona instance: topstep_150k template, Topstep adapter (stub).
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from deployment.instance_config import InstanceConfig
from deployment.instance_context import InstanceContext
from deployment.data_paths import SUBSYSTEM_ENV
from broker.factory import get_adapter
from broker.base import NotConnectedError
import paper_execution.trade_journal as tj
import ai_retrieval.vector_store as vs

_ISOLATED_ENV = list(SUBSYSTEM_ENV.values()) + ["BOT_INSTANCE_ID"]
_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "instances", "templates")


def _clean_env():
    for v in _ISOLATED_ENV:
        os.environ.pop(v, None)


def _from_template(template, instance_id, root, **over):
    cfg = InstanceConfig.load(os.path.join(_TEMPLATES, f"{template}.yaml"))
    cfg.instance_id = instance_id
    for k, v in over.items():
        setattr(cfg, k, v)
    for f in ("memory_path", "vector_store_path", "journal_path",
              "log_path", "state_path", "news_memory_path"):
        setattr(cfg, f, "")
    base = os.path.join(root, instance_id)
    cfg.memory_path = os.path.join(base, "memory")
    cfg.vector_store_path = os.path.join(base, "vector_store")
    cfg.journal_path = os.path.join(base, "journal")
    cfg.log_path = os.path.join(base, "logs")
    cfg.state_path = os.path.join(base, "state")
    cfg.news_memory_path = os.path.join(base, "news_memory")
    return InstanceContext(cfg)


class TestMauriceTionaSeparation(unittest.TestCase):
    def setUp(self):
        _clean_env()
        self.root = tempfile.mkdtemp()
        self.maurice = _from_template("paper", "maurice_alpaca", self.root,
                                      owner_name="Maurice", account_id="alpaca_paper",
                                      symbol="QQQ")
        self.tiona = _from_template("topstep_150k", "tiona_topstep", self.root,
                                    owner_name="Tiona", account_id="TIONA-TS-150K-PRACTICE")
        self.maurice.ensure_dirs()
        self.tiona.ensure_dirs()

    def tearDown(self):
        _clean_env()

    # 7 + 8 — brokers
    def test_07_maurice_broker_is_alpaca_paper(self):
        self.assertEqual(self.maurice.config.broker, "paper")
        a = get_adapter(self.maurice.config)
        self.assertEqual(a.name, "paper")
        self.assertTrue(a.capability().paper_only)   # Alpaca paper endpoint

    def test_08_tiona_broker_is_topstep_stub(self):
        self.assertEqual(self.tiona.config.broker, "topstep")
        a = get_adapter(self.tiona.config)
        self.assertEqual(a.name, "topstep")
        self.assertFalse(a.is_connected())            # stub — cannot submit
        with self.assertRaises(NotConnectedError):
            a.submit_order({"symbol": "QQQ", "qty": 1})

    # 6 — Tiona journal starts empty
    def test_06_tiona_journal_starts_empty(self):
        with self.tiona:
            self.assertEqual(tj.load_today_trades("QQQ"), [])

    # 2 + 5 — Tiona writes to Tiona only; Maurice journal untouched
    def test_02_05_journal_isolation(self):
        with self.maurice:
            tj.append_trade({"trade_id": "M1", "symbol": "QQQ", "side": "long"}, "QQQ")
        # snapshot Maurice's journal AFTER his own write, BEFORE any Tiona activity
        m_dir = self.maurice.paths["journal"]
        before = _dirstate(m_dir)
        with self.tiona:
            tj.append_trade({"trade_id": "T1", "symbol": "QQQ", "side": "short"}, "QQQ")
            t_ids = {t["trade_id"] for t in tj.load_today_trades("QQQ")}
        after = _dirstate(m_dir)
        self.assertEqual(before, after, "Tiona activity modified Maurice's journal")
        self.assertEqual(t_ids, {"T1"})               # Tiona sees only its own
        with self.maurice:
            m_ids = {t["trade_id"] for t in tj.load_today_trades("QQQ")}
        self.assertEqual(m_ids, {"M1"})               # Maurice sees only its own

    # 1 — Maurice writes to Maurice memory only (directed to his store, not Tiona's)
    def test_01_maurice_writes_land_in_maurice_store(self):
        with self.maurice:
            self.assertEqual(tj._trades_dir(), self.maurice.paths["journal"])
            self.assertNotEqual(tj._trades_dir(), self.tiona.paths["journal"])

    # 3 + 4 — vector records invisible across instances
    def test_03_04_vector_isolation(self):
        with self.tiona:
            vs.add_record({"id": "tiona-vec-1", "vector": [0.1], "meta": {"src": "tiona"}})
            self.assertEqual(vs.count(), 1)
        with self.maurice:
            m_ids = {r.get("id") for r in vs.load_records()}
            self.assertNotIn("tiona-vec-1", m_ids)    # Maurice cannot see Tiona's vector
            vs.add_record({"id": "maurice-vec-1", "vector": [0.2], "meta": {"src": "maurice"}})
        with self.tiona:
            t_ids = {r.get("id") for r in vs.load_records()}
            self.assertNotIn("maurice-vec-1", t_ids)  # Tiona cannot see Maurice's vector

    # 9 — no shared account state / writable paths
    def test_09_no_shared_state(self):
        self.assertNotEqual(self.maurice.config.account_id, self.tiona.config.account_id)
        self.assertNotEqual(self.maurice.config.broker, self.tiona.config.broker)
        shared = set(self.maurice.env_map().values()) & set(self.tiona.env_map().values())
        self.assertEqual(shared, set(), f"shared writable paths: {shared}")
        for key in ("brain", "vector_store", "journal", "snapshots", "news_memory", "ops"):
            self.assertNotEqual(self.maurice.paths[key], self.tiona.paths[key])


def _dirstate(d):
    if not os.path.isdir(d):
        return frozenset()
    out = []
    for name in os.listdir(d):
        fp = os.path.join(d, name)
        out.append((name, os.path.getsize(fp)))
    return frozenset(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
