"""
Phase TOPSTEP-1 — Topstep adapter safety tests.

Proves the adapter's guards WITHOUT credentials or network: practice-only writes,
execution-gated submits, credential masking, graceful no-cred behavior, and that
Maurice's Alpaca (paper) adapter is unaffected. No orders, no live money.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from broker.factory import get_adapter
from broker.base import NotConnectedError
from broker.topstep_adapter import TopstepBrokerAdapter, TopstepConfig
from deployment.instance_config import InstanceConfig

_ENV_VARS = ["TOPSTEP_API_KEY", "TOPSTEP_USERNAME", "TOPSTEP_ACCOUNT_ID",
             "TOPSTEP_ENV", "TOPSTEP_BASE_URL", "TOPSTEP_EXECUTION_ENABLED"]


def _clear():
    for v in _ENV_VARS:
        os.environ.pop(v, None)


class TestTopstepAdapter(unittest.TestCase):
    def setUp(self):
        _clear()

    def tearDown(self):
        _clear()

    def test_factory_returns_real_adapter(self):
        a = get_adapter(broker="topstep")
        self.assertIsInstance(a, TopstepBrokerAdapter)
        self.assertEqual(a.name, "topstep")

    def test_credentials_masked_never_full(self):
        os.environ["TOPSTEP_API_KEY"] = "pjx_SECRET_1234567890ABCDEF"
        os.environ["TOPSTEP_USERNAME"] = "tiona"
        cfg = TopstepConfig.from_env()
        masked = cfg.masked_key()
        self.assertNotIn("SECRET_1234567890ABCDEF", masked)
        self.assertNotEqual(masked, cfg.api_key)
        self.assertTrue(cfg.credentials_present())

    def test_no_credentials_is_graceful(self):
        a = TopstepBrokerAdapter()
        self.assertFalse(a.authenticate().get("ok"))      # no crash
        self.assertFalse(a.is_connected())
        self.assertFalse(a.health_check().get("healthy"))
        self.assertEqual(a.get_positions(), [])
        self.assertEqual(a.get_open_orders(), [])

    def test_practice_guard_blocks_writes_when_not_practice(self):
        os.environ["TOPSTEP_ENV"] = "funded"   # live-ish — must be refused
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        a = TopstepBrokerAdapter()
        for call in (lambda: a.submit_order({"side": "buy", "size": 1}),
                     lambda: a.cancel_order("123"),
                     lambda: a.flatten_position("CON.F.US.MNQ")):
            with self.assertRaises(NotConnectedError):
                call()

    def test_submit_blocked_when_execution_disabled_even_in_practice(self):
        os.environ["TOPSTEP_ENV"] = "practice"
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "false"
        a = TopstepBrokerAdapter()
        with self.assertRaises(NotConnectedError):
            a.submit_order({"side": "buy", "size": 1})

    def test_capability_reflects_gating(self):
        os.environ["TOPSTEP_ENV"] = "practice"
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "false"
        self.assertFalse(TopstepBrokerAdapter().capability().supports_orders)
        os.environ["TOPSTEP_EXECUTION_ENABLED"] = "true"
        self.assertTrue(TopstepBrokerAdapter().capability().supports_orders)
        self.assertTrue(TopstepBrokerAdapter().capability().paper_only)  # practice

    def test_account_id_from_instance_config(self):
        cfg = InstanceConfig(instance_id="tiona_topstep", broker="topstep",
                             account_id="TIONA-TS-150K")
        a = TopstepBrokerAdapter(cfg)
        self.assertEqual(a.cfg.account_id, "TIONA-TS-150K")

    def test_maurice_paper_adapter_unaffected(self):
        # Maurice's broker resolves to the Alpaca paper adapter, not Topstep
        m = InstanceConfig(instance_id="maurice_alpaca", broker="paper")
        a = get_adapter(m)
        self.assertEqual(a.name, "paper")
        self.assertTrue(a.capability().paper_only)


if __name__ == "__main__":
    unittest.main(verbosity=2)
