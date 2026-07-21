"""MNQ-DEMO8458533-SMOKE-ORDER — order-path proofs (mock wire, temp tokens).

NO real token is touched and NO order leaves the process. Proves every control
the smoke order depends on. TRANSMIT_LATCH stays False except where a test
explicitly passes transmit_latch=True into a MOCK wire.
"""
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader import smoke_authorization as AUTH        # noqa: E402
from integrations.ninjatrader import smoke_order_path as OP             # noqa: E402

ACCT, INSTR = "DEMO8458533", "MNQ SEP26"


class MockWire:
    def __init__(self, fill=29100.0, oco_ok=True, flat_ok=True):
        self.fill, self.oco_ok, self.flat_ok = fill, oco_ok, flat_ok
        self.calls = []
        self.pos = {"known": True, "qty": 0, "flat": True}
        self.orders = {"known": True, "working_order_count": 0}

    def submit_market_entry(self, intent):
        self.calls.append(("entry", intent))
        return {"accepted": True, "avg_fill_price": self.fill, "order_ref": "E1"}

    def submit_oco(self, stop, target):
        self.calls.append(("oco", stop, target))
        return {"ok": self.oco_ok, "stop_ref": "S1", "target_ref": "T1"}

    def flatten(self, instrument):
        self.calls.append(("flatten", instrument))
        return {"ok": self.flat_ok}

    def position(self, instrument):
        return self.pos

    def order_summary(self):
        return self.orders


def _token(path, **kw):
    return AUTH.issue_token(ACCT, INSTR, 1, "unit-test", path=path, **kw)


def _intent():
    return OP.build_entry_intent("AUTH1", "INTENT1", "THESIS1", "COID1")


class TestBuilders(unittest.TestCase):
    def test_tick_normalization(self):
        self.assertEqual(OP.normalize_tick(29100.13), 29100.25)
        self.assertEqual(OP.normalize_tick(29100.10), 29100.0)
        self.assertEqual(OP.normalize_tick(29099.80), 29099.75)

    def test_stop_target_and_oco(self):
        p = OP.build_protective_orders(29100.0, "OCO-1")
        self.assertEqual(p["stop"]["stop_price"], 29095.0)     # 5 below
        self.assertEqual(p["target"]["limit_price"], 29105.0)  # 5 above
        self.assertEqual(p["stop"]["oco_id"], p["target"]["oco_id"])  # common OCO
        self.assertEqual(p["stop"]["quantity"], 1)
        self.assertEqual(p["target"]["quantity"], 1)
        self.assertEqual(p["stop"]["action"], "sell")
        self.assertEqual(p["target"]["action"], "sell")

    def test_stop_target_normalized_from_odd_fill(self):
        p = OP.build_protective_orders(29100.13, "OCO-2")   # fill off-tick
        # 29100.13-5 = 29095.13 -> 29095.25 ; +5 = 29105.13 -> 29105.25
        self.assertEqual(p["stop"]["stop_price"], 29095.25)
        self.assertEqual(p["target"]["limit_price"], 29105.25)

    def test_entry_intent_is_long_market_one(self):
        i = _intent()
        self.assertEqual(i["direction"], "long")
        self.assertEqual(i["entry_type"], "market")
        self.assertEqual(i["quantity"], 1)
        self.assertEqual(i["account"], ACCT)
        self.assertEqual(i["instrument"], INSTR)


class TestTransmitGates(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "tok.json")
        _token(self.path)

    def _path(self, wire):
        return OP.SmokeOrderPath(wire=wire, token_path=self.path)

    def test_latch_false_blocks_and_does_not_burn_token(self):
        w = MockWire()
        r = self._path(w).transmit(_intent(), preflight_go=True, transmit_latch=False)
        self.assertFalse(r.transmitted)
        self.assertIn("LATCH", r.reason)
        self.assertEqual(w.calls, [])               # nothing sent
        self.assertTrue(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))  # token intact

    def test_preflight_not_go_blocks_and_no_burn(self):
        w = MockWire()
        r = self._path(w).transmit(_intent(), preflight_go=False, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertEqual(w.calls, [])
        self.assertTrue(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))

    def test_full_go_transmits_with_protection(self):
        w = MockWire(fill=29100.0)
        r = self._path(w).transmit(_intent(), preflight_go=True, transmit_latch=True)
        self.assertTrue(r.transmitted, r.reason)
        self.assertTrue(r.protection_established)
        self.assertEqual(r.protective["stop"]["stop_price"], 29095.0)
        self.assertEqual(r.protective["target"]["limit_price"], 29105.0)
        # token burned
        self.assertFalse(AUTH.validate_token(ACCT, INSTR, 1, path=self.path))
        # entry then oco
        self.assertEqual(w.calls[0][0], "entry")
        self.assertEqual(w.calls[1][0], "oco")

    def test_account_pin(self):
        w = MockWire()
        i = _intent(); i["account"] = "Sim101"
        r = self._path(w).transmit(i, preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertIn("account pin", r.reason)
        self.assertEqual(w.calls, [])

    def test_instrument_pin(self):
        i = _intent(); i["instrument"] = "NQ 09-26"
        r = self._path(MockWire()).transmit(i, preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertIn("instrument pin", r.reason)

    def test_quantity_pin(self):
        i = _intent(); i["quantity"] = 2
        r = self._path(MockWire()).transmit(i, preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertIn("quantity pin", r.reason)

    def test_direction_pin(self):
        i = _intent(); i["direction"] = "short"
        r = self._path(MockWire()).transmit(i, preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertIn("direction pin", r.reason)

    def test_duplicate_and_redisarm(self):
        w = MockWire()
        p = self._path(w)
        r1 = p.transmit(_intent(), preflight_go=True, transmit_latch=True)
        self.assertTrue(r1.transmitted)
        # second attempt (even a fresh token) is re-disarmed
        _token(self.path.replace("tok.json", "tok2.json"))  # unrelated
        r2 = p.transmit(_intent(), preflight_go=True, transmit_latch=True)
        self.assertFalse(r2.transmitted)
        self.assertIn("re-disarm", r2.reason)

    def test_emergency_flatten_when_protection_fails(self):
        w = MockWire(oco_ok=False, flat_ok=True)
        r = self._path(w).transmit(_intent(), preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertFalse(r.protection_established)
        self.assertTrue(r.emergency_flattened)
        self.assertIn(("flatten", INSTR), [(c[0], c[1]) for c in w.calls if c[0] == "flatten"])

    def test_no_token_fails_after_gates(self):
        AUTH.revoke_token(self.path)
        r = self._path(MockWire()).transmit(_intent(), preflight_go=True, transmit_latch=True)
        self.assertFalse(r.transmitted)
        self.assertIn("authorization", r.reason)

    def test_reconcile(self):
        rec = self._path(MockWire()).reconcile()
        self.assertTrue(rec["reconciled"])
        self.assertTrue(rec["position"]["flat"])


if __name__ == "__main__":
    unittest.main()
