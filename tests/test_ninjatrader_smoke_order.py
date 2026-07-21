"""MNQ-DEMO8458533-SMOKE-ORDER — safety tests.

Covers the revised (Global-Simulation-Mode-free) doctrine: positive Simulation-
environment proof, one-use authorization, and the 12-point fail-closed preflight.
NO ORDER IS SUBMITTED anywhere here.
"""
import os
import sys
import tempfile
import time
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader import environment_proof as EP          # noqa: E402
from integrations.ninjatrader import smoke_authorization as AUTH      # noqa: E402
from integrations.ninjatrader import smoke_preflight as PRE           # noqa: E402

ACCT = "DEMO8458533"
INSTR = "MNQ SEP26"


def _env(accounts):
    return {"accounts": accounts, "allowed_account": ACCT, "arm_orders": False}


# ── environment proof ─────────────────────────────────────────────────────────
class TestEnvironmentProof(unittest.TestCase):
    def test_simulation_proven(self):
        e = EP.evaluate(_env([{"name": ACCT, "provider": "NinjaTrader", "status": "Connected"}]))
        self.assertTrue(e)

    def test_no_payload_fails_closed(self):
        self.assertFalse(EP.evaluate(None))
        self.assertFalse(EP.evaluate({}))

    def test_demo_absent_fails(self):
        self.assertFalse(EP.evaluate(_env([{"name": "Sim101", "status": "Connected"}])))

    def test_demo_disconnected_fails(self):
        self.assertFalse(EP.evaluate(_env([{"name": ACCT, "status": "Disconnected"}])))

    def test_live_account_present_fails(self):
        e = EP.evaluate(_env([{"name": ACCT, "status": "Connected"},
                              {"name": "APEX-LIVE-1", "status": "Connected"}]))
        self.assertFalse(e)
        self.assertTrue(e.live_suspects)

    def test_wrong_expected_account_fails(self):
        self.assertFalse(EP.evaluate(_env([{"name": ACCT, "status": "Connected"}]),
                                     expected_account="Sim101"))


# ── one-use authorization ─────────────────────────────────────────────────────
class TestAuthorization(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "tok.json")

    def test_issue_validate_consume_burns(self):
        AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=self.path)
        self.assertTrue(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))
        c = AUTH.consume_token(ACCT, INSTR, 1, "intent-1", path=self.path)
        self.assertTrue(c)
        # second consume fails — one-use
        self.assertFalse(AUTH.consume_token(ACCT, INSTR, 1, "intent-2", path=self.path))
        self.assertFalse(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))

    def test_missing_token_fails(self):
        self.assertFalse(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))

    def test_mismatch_fails(self):
        AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=self.path)
        self.assertFalse(AUTH.validate_token("Sim101", INSTR, 1, path=self.path))
        self.assertFalse(AUTH.validate_token(ACCT, "NQ 09-26", 1, path=self.path))
        self.assertFalse(AUTH.validate_token(ACCT, INSTR, 2, path=self.path))

    def test_expired_fails(self):
        AUTH.issue_token(ACCT, INSTR, 1, "unit-test", ttl_seconds=1, path=self.path)
        future = time.time() + 10
        self.assertFalse(AUTH.validate_token(ACCT, INSTR, 1, path=self.path, now=future))

    def test_cannot_overwrite_unused_token(self):
        AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=self.path)
        with self.assertRaises(AUTH.AuthorizationError):
            AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=self.path)


# ── 12-point preflight ────────────────────────────────────────────────────────
class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "tok.json")
        AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=self.path)

    def _good_inputs(self):
        return dict(
            bridge_env=_env([{"name": ACCT, "provider": "NinjaTrader", "status": "Connected"}]),
            account_state={"account": ACCT, "cash_value": 50000},
            position={"known": True, "qty": 0, "flat": True},
            order_summary={"known": True, "working_order_count": 0},
            instrument_metadata={"instrument_name": INSTR, "tick_size": 0.25, "point_value": 2},
            metadata_reconcile={"metadata_verified": True},
            quote={"have_last": True, "have_bid": True, "have_ask": True,
                   "last": 29100, "bid": 29099.75, "ask": 29100.25},
            ati_default_account=ACCT,
            intended_quantity=1,
            token_path=self.path)

    def test_all_pass_is_go(self):
        r = PRE.run(**self._good_inputs())
        self.assertTrue(r.go, [f"{c.n}:{c.name}:{c.detail}" for c in r.failures()])
        self.assertEqual(len(r.checks), 12)

    def test_missing_token_is_nogo(self):
        inp = self._good_inputs()
        AUTH.revoke_token(self.path)
        r = PRE.run(**inp)
        self.assertFalse(r.go)
        self.assertIn(12, [c.n for c in r.failures()])

    def test_not_flat_is_nogo(self):
        inp = self._good_inputs()
        inp["position"] = {"known": True, "qty": 1, "flat": False}
        r = PRE.run(**inp)
        self.assertFalse(r.go)

    def test_unknown_position_is_nogo(self):
        inp = self._good_inputs()
        inp["position"] = {"known": False}
        self.assertFalse(PRE.run(**inp).go)

    def test_working_orders_nonzero_is_nogo(self):
        inp = self._good_inputs()
        inp["order_summary"] = {"known": True, "working_order_count": 1}
        self.assertFalse(PRE.run(**inp).go)

    def test_wrong_instrument_is_nogo(self):
        inp = self._good_inputs()
        inp["instrument_metadata"] = {"instrument_name": "NQ 09-26"}
        self.assertFalse(PRE.run(**inp).go)

    def test_unverified_metadata_is_nogo(self):
        inp = self._good_inputs()
        inp["metadata_reconcile"] = {"metadata_verified": False}
        self.assertFalse(PRE.run(**inp).go)

    def test_qty_two_is_nogo(self):
        inp = self._good_inputs()
        inp["intended_quantity"] = 2
        self.assertFalse(PRE.run(**inp).go)

    def test_ati_default_wrong_is_nogo(self):
        inp = self._good_inputs()
        inp["ati_default_account"] = "Sim101"
        self.assertFalse(PRE.run(**inp).go)

    def test_stale_quote_is_nogo(self):
        inp = self._good_inputs()
        inp["quote"] = {"have_last": False, "have_bid": False, "have_ask": False}
        self.assertFalse(PRE.run(**inp).go)

    def test_live_account_is_nogo(self):
        inp = self._good_inputs()
        inp["bridge_env"] = _env([{"name": ACCT, "status": "Connected"},
                                  {"name": "FUNDED-99", "status": "Connected"}])
        r = PRE.run(**inp)
        self.assertFalse(r.go)


if __name__ == "__main__":
    unittest.main()
