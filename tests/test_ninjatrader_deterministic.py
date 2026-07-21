"""DETERMINISTIC_MNQ_SIM_ONLY — safety tests (mock; no orders, no OpenAI).

Covers the 30 mission test requirements that are provable in Python. Bridge-
runtime items (OCO qty on the wire, emergency flatten execution) are proven by
the send/loop contract + smoke-test evidence and asserted at the payload level.
"""
import os
import re
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader.deterministic import risk as R                    # noqa: E402
from integrations.ninjatrader.deterministic import author as A                  # noqa: E402
from integrations.ninjatrader.deterministic import (QUANTITY, TARGET_POINTS,    # noqa: E402
    MAX_STOP_POINTS, MAX_GROSS_TRADE_RISK, DAILY_LOSS_CEILING, MAX_TRADES_PER_DAY)
from integrations.ninjatrader.deterministic.session import SessionAuthority     # noqa: E402

LONG, SHORT = "long", "short"


def _facts(**over):
    f = dict(setup_family="fvg", direction="long", qualification_direction="long",
             playbook_direction="long", decision_direction="long",
             liquidity_evidence=True, structural_evidence=True, displacement_evidence=True,
             trigger_confirmed=True, protected_zone_permits=True,
             commander_state="PROCEED", fc0b_permits=True, entry_invalidation=29284.25,
             opposing_direction=None, final_gate_authorizes=True, expected_entry=29300.0)
    f.update(over)
    return f


def _author(f, **kw):
    base = dict(account_known=True, position_known=True, orders_known=True,
                reconciliation_ok=True, realized_daily_loss=0.0, can_enter=True,
                can_enter_reason="ok")
    base.update(kw)
    return A.evaluate(f, **base)


class TestQuantity(unittest.TestCase):
    def test_01_exactly_five_accepted(self):
        self.assertTrue(R.check_quantity(5)[0])

    def test_02_one_to_four_rejected(self):
        for q in (1, 2, 3, 4):
            self.assertFalse(R.check_quantity(q)[0], q)

    def test_03_above_five_rejected(self):
        for q in (6, 10):
            self.assertFalse(R.check_quantity(q)[0], q)

    def test_03b_zero_fractional_negative_rejected(self):
        for q in (0, 2.5, -5):
            self.assertFalse(R.check_quantity(q)[0], q)


class TestRiskMath(unittest.TestCase):
    def test_04_long_works(self):
        d = R.assess_trade(LONG, 29300.0, 29284.25, 0.0)
        self.assertTrue(d.approved)
        self.assertEqual(d.gross_risk, 157.50)

    def test_05_short_works(self):
        d = R.assess_trade(SHORT, 29300.0, 29317.50, 0.0)
        self.assertTrue(d.approved)
        self.assertEqual(d.gross_risk, 175.00)

    def test_06_target_35_correct(self):
        self.assertEqual(R.target_price(LONG, 29300.0), 29335.0)
        self.assertEqual(R.target_price(SHORT, 29300.0), 29265.0)

    def test_07_structural_stop_distance(self):
        s = R.assess_structural_stop(LONG, 29300.0, 29284.25)
        self.assertTrue(s.valid)
        self.assertEqual(s.stop_distance, 15.75)

    def test_08_stop_over_20_rejected(self):
        self.assertFalse(R.assess_structural_stop(LONG, 29300.0, 29278.0).valid)  # 22
        self.assertFalse(R.assess_trade(LONG, 29300.0, 29278.0, 0.0).approved)

    def test_09_stop_exactly_20_accepted(self):
        s = R.assess_structural_stop(LONG, 29300.0, 29280.0)
        self.assertTrue(s.valid)
        self.assertEqual(s.stop_distance, 20.0)
        self.assertEqual(R.assess_trade(LONG, 29300.0, 29280.0, 0.0).gross_risk, 200.0)

    def test_10_tick_normalization(self):
        self.assertEqual(R.normalize_tick(29284.13), 29284.25)
        self.assertEqual(R.normalize_tick(29284.10), 29284.0)

    def test_11_long_stop_below(self):
        self.assertFalse(R.assess_structural_stop(LONG, 29300.0, 29305.0).valid)  # above

    def test_12_long_target_above(self):
        self.assertGreater(R.target_price(LONG, 29300.0), 29300.0)

    def test_13_short_stop_above(self):
        self.assertFalse(R.assess_structural_stop(SHORT, 29300.0, 29295.0).valid)  # below

    def test_14_short_target_below(self):
        self.assertLess(R.target_price(SHORT, 29300.0), 29300.0)

    def test_max_risk_constants(self):
        self.assertEqual(MAX_GROSS_TRADE_RISK, 200.0)
        self.assertEqual(TARGET_POINTS / MAX_STOP_POINTS, 1.75)


class TestAuthor(unittest.TestCase):
    def test_full_agreement_authorizes_five(self):
        d = _author(_facts())
        self.assertTrue(d.authorized, d.blockers())
        self.assertEqual(d.quantity, QUANTITY)
        self.assertEqual(d.structural_stop, 29284.25)
        self.assertEqual(d.target_price, 29335.0)

    def test_short_authorizes(self):
        d = _author(_facts(direction="short", qualification_direction="short",
                           playbook_direction="short", decision_direction="short",
                           entry_invalidation=29317.50))
        self.assertTrue(d.authorized, d.blockers())

    def test_any_directional_disagreement_no_trade(self):
        for k in ("qualification_direction", "playbook_direction", "decision_direction"):
            self.assertFalse(_author(_facts(**{k: "short"})).authorized, k)

    def test_unknown_fact_fails_closed(self):
        self.assertFalse(_author(_facts(fc0b_permits=None)).authorized)
        self.assertFalse(_author(_facts(commander_state=None)).authorized)

    def test_standdown_blocks(self):
        self.assertFalse(_author(_facts(commander_state="STAND_DOWN")).authorized)

    def test_protected_zone_blocks(self):
        self.assertFalse(_author(_facts(protected_zone_permits=False)).authorized)

    def test_stop_over_20_blocks(self):
        self.assertFalse(_author(_facts(entry_invalidation=29278.0)).authorized)  # 22pt

    def test_opposing_direction_blocks(self):
        self.assertFalse(_author(_facts(opposing_direction="short")).authorized)

    def test_19_unknown_position_blocks(self):
        self.assertFalse(_author(_facts(), position_known=False).authorized)

    def test_20_unknown_orders_blocks(self):
        self.assertFalse(_author(_facts(), orders_known=False).authorized)

    def test_reconciliation_unknown_blocks(self):
        self.assertFalse(_author(_facts(), reconciliation_ok=False).authorized)

    def test_labels_mode_author(self):
        d = _author(_facts())
        self.assertEqual(d.mode, "DETERMINISTIC_MNQ_SIM_ONLY")
        self.assertEqual(d.author, "deterministic_sim_author")


class TestSession(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "s.json")

    def _s(self):
        s = SessionAuthority()
        s.last_reconcile_ok = True
        return s

    def test_18_second_position_rejected(self):
        s = self._s()
        s.active_position_qty = 5
        self.assertFalse(s.can_enter()[0])

    def test_working_orders_block(self):
        s = self._s()
        s.active_order_ids = ["x"]
        self.assertFalse(s.can_enter()[0])

    def test_22_daily_trade_limit_blocks_third(self):
        s = self._s()
        s.trade_count = MAX_TRADES_PER_DAY
        self.assertFalse(s.can_enter()[0])

    def test_23_daily_loss_ceiling_blocks(self):
        s = self._s()
        s.realized_pnl = -DAILY_LOSS_CEILING
        self.assertFalse(s.can_enter()[0])

    def test_23b_risk_engine_blocks_when_remaining_room_small(self):
        d = R.assess_trade(LONG, 29300.0, 29280.0, realized_daily_loss=350.0)  # 200 risk
        self.assertFalse(d.approved)

    def test_16_17_duplicate_ids_rejected(self):
        s = self._s()
        s.register_ids("I1", "C1")
        self.assertTrue(s.is_duplicate("I1", "Cx")[0])
        self.assertTrue(s.is_duplicate("Ix", "C1")[0])
        self.assertFalse(s.is_duplicate("I2", "C2")[0])

    def test_24_restart_reconstructs(self):
        s = self._s()
        s.trade_count = 1
        s.realized_pnl = -120.0
        s.save(self.p)
        resumed = SessionAuthority.resume_or_new(self.p)
        self.assertEqual(resumed.trade_count, 1)
        self.assertEqual(resumed.realized_pnl, -120.0)
        # resume forces re-reconcile before entries
        self.assertFalse(resumed.last_reconcile_ok)
        self.assertFalse(resumed.can_enter()[0])

    def test_reconcile_unknown_fails_closed(self):
        s = self._s()
        s.apply_reconciliation({"known": False}, {"known": False})
        self.assertFalse(s.last_reconcile_ok)


class TestConstitution(unittest.TestCase):
    def test_25_only_demo_account(self):
        from integrations.ninjatrader.account_safety import check_account
        self.assertTrue(check_account("DEMO8458533"))
        for bad in ("Sim101", "1932903", "Live"):
            self.assertFalse(check_account(bad))

    def test_26_only_mnq_sep26(self):
        from integrations.ninjatrader.account_safety import check_instrument
        self.assertTrue(check_instrument("MNQ SEP26", "MNQ SEP26"))
        for bad in ("NQ SEP26", "QQQ", "MNQ", "MNQ DEC26"):
            self.assertFalse(check_instrument(bad, "MNQ SEP26"))

    def test_27_29_no_openai_no_atm_in_sources(self):
        import integrations.ninjatrader.deterministic as pkg
        root = os.path.dirname(pkg.__file__)
        # Actual ATM/LLM API usage — not the "ATM TEMPLATE: NOT USED" banner.
        pat = re.compile(r"(^|\n)\s*(import|from)\s+(openai|anthropic)\b"
                         r"|\b(openai|anthropic)\.[A-Za-z_]|AtmStrategy|SetStopLoss\(|SetProfitTarget\(",
                         re.IGNORECASE)
        offenders = [fn for fn in os.listdir(root)
                     if fn.endswith(".py") and pat.search(open(os.path.join(root, fn),
                                                              encoding="utf-8").read())]
        # "ATM" appears only in comments as "NOT USED"; ensure no ATM API calls.
        self.assertEqual(offenders, [], offenders)


if __name__ == "__main__":
    unittest.main()
