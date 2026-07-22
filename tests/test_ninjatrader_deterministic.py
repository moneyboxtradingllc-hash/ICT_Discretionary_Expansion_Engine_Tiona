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
from integrations.ninjatrader.deterministic import (TARGET_POINTS, MAX_STOP_POINTS,  # noqa: E402
    MAX_RISK_DOLLARS, MAX_CONTRACTS, POINT_VALUE, DAILY_LOSS_CEILING, MAX_TRADES_PER_DAY)
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


class TestSizing(unittest.TestCase):
    def test_01_check_quantity_range(self):
        for q in (1, 10, 15, MAX_CONTRACTS):
            self.assertTrue(R.check_quantity(q)[0], q)
        for q in (0, MAX_CONTRACTS + 1, 40, 2.5, -1):
            self.assertFalse(R.check_quantity(q)[0], q)

    def test_02_risk_based_sizing(self):
        # contracts = floor($500 / (stop x $2)), capped at MAX_CONTRACTS
        self.assertEqual(R.contracts_for_stop(12.0), 20)   # 500 / 24
        self.assertEqual(R.contracts_for_stop(16.5), 15)   # 500 / 33
        self.assertEqual(R.contracts_for_stop(20.0), 12)   # 500 / 40
        self.assertEqual(R.contracts_for_stop(25.0), 10)   # 500 / 50
        self.assertEqual(R.contracts_for_stop(25.1), 0)    # over cap -> no trade
        self.assertEqual(R.contracts_for_stop(0), 0)
        self.assertEqual(R.contracts_for_stop(-5), 0)
        self.assertLessEqual(R.contracts_for_stop(4.0), MAX_CONTRACTS)  # tight -> ceiling

    def test_03_risk_never_exceeds_budget(self):
        for stop in (4.0, 8.0, 12.0, 16.5, 20.0, 25.0):
            q = R.contracts_for_stop(stop)
            self.assertLessEqual(stop * POINT_VALUE * q, MAX_RISK_DOLLARS + 1e-9, stop)


class TestRiskMath(unittest.TestCase):
    def test_04_long_works(self):
        d = R.assess_trade(LONG, 29300.0, 29284.25, 0.0)   # 15.75pt x $30
        self.assertTrue(d.approved)
        self.assertEqual(d.gross_risk, 472.50)

    def test_05_short_works(self):
        d = R.assess_trade(SHORT, 29300.0, 29315.00, 0.0)  # 15.0pt -> 16 contracts
        self.assertTrue(d.approved)
        self.assertEqual(d.quantity, 16)
        self.assertEqual(d.gross_risk, 480.00)             # 15 x $2 x 16

    def test_06_target_35_correct(self):
        self.assertEqual(R.target_price(LONG, 29300.0), 29335.0)
        self.assertEqual(R.target_price(SHORT, 29300.0), 29265.0)

    def test_07_structural_stop_distance(self):
        s = R.assess_structural_stop(LONG, 29300.0, 29284.25)
        self.assertTrue(s.valid)
        self.assertEqual(s.stop_distance, 15.75)

    def test_08_stop_over_cap_rejected(self):
        self.assertFalse(R.assess_structural_stop(LONG, 29300.0, 29274.0).valid)  # 26pt > 25
        d = R.assess_trade(LONG, 29300.0, 29274.0, 0.0)
        self.assertFalse(d.approved)
        self.assertEqual(R.contracts_for_stop(26.0), 0)      # over cap -> size 0

    def test_09_stop_exactly_cap_accepted(self):
        s = R.assess_structural_stop(LONG, 29300.0, 29275.0)   # exactly 25pt
        self.assertTrue(s.valid)
        self.assertEqual(s.stop_distance, 25.0)
        d = R.assess_trade(LONG, 29300.0, 29275.0, 0.0)
        self.assertEqual(d.quantity, 10)                       # 500 / (25 x $2)
        self.assertEqual(d.gross_risk, 500.0)                  # 25 x $2 x 10

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
        self.assertEqual(MAX_STOP_POINTS, 25.0)
        self.assertEqual(MAX_RISK_DOLLARS, 500.0)
        # the widest allowed stop still sizes to a valid, in-budget position
        q = R.contracts_for_stop(MAX_STOP_POINTS)
        self.assertGreaterEqual(q, 1)
        self.assertLessEqual(MAX_STOP_POINTS * POINT_VALUE * q, MAX_RISK_DOLLARS + 1e-9)


class TestAuthor(unittest.TestCase):
    def test_full_agreement_authorizes_five(self):
        d = _author(_facts())
        self.assertTrue(d.authorized, d.blockers())
        self.assertEqual(d.quantity, 15)   # 15.75pt stop -> 500 / (15.75 x $2) = 15
        self.assertEqual(d.structural_stop, 29284.25)
        self.assertEqual(d.target_price, 29335.0)

    def test_short_authorizes(self):
        d = _author(_facts(direction="short", qualification_direction="short",
                           playbook_direction="short", decision_direction="short",
                           entry_invalidation=29315.00))
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

    def test_stop_over_cap_blocks(self):
        self.assertFalse(_author(_facts(entry_invalidation=29273.0)).authorized)  # 27pt > 25 cap

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
        # 15pt stop = $450 risk; realized $600 already => $1050+ > $1000 ceiling.
        d = R.assess_trade(LONG, 29300.0, 29285.0, realized_daily_loss=600.0)
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


class TestFactsWiring(unittest.TestCase):
    """The facts provider maps the REAL subsystem outputs to author facts."""

    def _snapshot(self, direction="bullish", entry=29300.0, invalid=29288.0,
                  relation="inside_zone"):
        mid = round((entry + invalid) / 2, 2)   # zone_risk ~= risk/2 -> within chase cap
        zlow, zhigh = min(entry, invalid), max(entry, invalid)
        return {
            "qualification": {"status": "qualified", "direction": direction},
            "playbook": {"selected_playbook": "fvg_reclaim", "direction": direction},
            "narrative_authority": {"invalidation_level": invalid},
            "structure": {"1m": {"bos": True, "last_swing_low": invalid,
                                 "last_swing_high": entry + 12}},
            "liquidity": {"1m": {"sweep_detected": True}},
            "expansion": {"1m": {"displacement_detected": True}},
            "toolbox": {"preferred_tool": "t1", "tool_candidates": [
                {"tool": "t1", "price_level": {"invalidation_level": invalid, "midpoint": mid}}]},
            "trade_intent": {"entry_zone": {"price_relation": relation,
                                            "current_price": entry, "midpoint": mid,
                                            "zone_low": zlow, "zone_high": zhigh}},
        }

    def _gate(self, ok=True):
        return {k: ok for k in ("trigger_requirement_met", "narrative_permits_trade",
                                "commander_permits_trade", "council_permits_trade",
                                "regime_permission_allowed", "no_promoted_rule_block")}

    def test_wired_long_authorizes(self):
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish", 29300.0, 29288.0)   # 12pt structural stop
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(True), 29300.0)
        self.assertEqual(facts["direction"], "long")
        self.assertEqual(facts["setup_family"], "fvg_reclaim")
        self.assertEqual(facts["entry_invalidation"], 29288.0)
        self.assertTrue(facts["fc0b_permits"])       # real evaluate_fc0b permit
        d = _author(facts)
        self.assertTrue(d.authorized, d.blockers())
        self.assertEqual(d.quantity, 20)   # 12pt stop -> 500 / (12 x $2) = 20

    def test_wired_short_authorizes(self):
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bearish", 29300.0, 29314.0)   # 14pt stop above
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bearish"},
                                             self._gate(True), 29300.0)
        self.assertEqual(facts["direction"], "short")
        self.assertTrue(_author(facts).authorized)

    def test_fc0b_reject_blocks_even_with_small_stop(self):
        # Price LEFT the zone (above_zone) -> FC-0B denies, even though the stop
        # is only 12pt (well within the 16.5pt cap). Proves FC-0B is independent.
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish", 29300.0, 29288.0, relation="above_zone")
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(True), 29300.0)
        self.assertFalse(facts["fc0b_permits"])      # real FC-0B verdict = deny
        self.assertFalse(_author(facts).authorized)

    def test_stop_cap_reject_independent_of_fc0b(self):
        # Stop 27pt (>25 cap) but FC-0B PERMITS (in zone, chase within cap).
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish", 29300.0, 29273.0)   # 27pt stop
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(True), 29300.0)
        self.assertTrue(facts["fc0b_permits"])       # FC-0B permits
        d = _author(facts)
        self.assertFalse(d.authorized)               # blocked by the 25pt stop cap
        self.assertTrue(any(f"stop_within_{MAX_STOP_POINTS:g}pts" in b for b in d.blockers()))

    def test_fc0b_unknown_is_no_trade(self):
        # No trade_intent/price_level -> FC-0B indeterminable -> None -> NO_TRADE.
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish")
        snap.pop("trade_intent"); snap.pop("toolbox"); snap["narrative_authority"] = {}
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(True), 29300.0)
        self.assertIsNone(facts["fc0b_permits"])
        self.assertFalse(_author(facts).authorized)

    def test_fc0b_falls_back_to_price_level_when_entry_zone_empty(self):
        # Real-world condition: entry_zone is empty even when price is AT the zone,
        # but the candidate price_level carries the location data. FC-0B must still
        # compute (not None) instead of blocking every authorization. (Regression.)
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish", 29300.0, 29288.0, relation="inside_zone")
        snap["trade_intent"]["entry_zone"] = {}                       # empty like live
        pl = snap["toolbox"]["tool_candidates"][0]["price_level"]
        pl["price_relation"] = "inside_zone"
        pl["current_price"] = 29300.0
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(True), 29300.0)
        self.assertIsNotNone(facts["fc0b_permits"])   # was None -> now computes

    def test_zone_displacement_trigger(self):
        # Operator rule (2026-07-22): a candle closing beyond the zone midpoint
        # in-direction is the entry even if it exits the zone edge.
        from integrations.ninjatrader.deterministic.facts_provider import (
            _zone_displacement_confirmed as Z)
        pl = {"level_type": "fvg_zone", "zone_low": 29288.0, "zone_high": 29296.0,
              "midpoint": 29292.0, "invalidated": False}
        # bullish: opened in zone, closed ABOVE the far edge, beyond midpoint -> confirm
        exit_up = {"timeframes": {"1m": {"last_candle":
                   {"open": 29290.0, "high": 29300.0, "low": 29289.0, "close": 29299.0}}}}
        self.assertTrue(Z(exit_up, "long", pl))
        # not directional (bearish body) -> no confirm
        down = {"timeframes": {"1m": {"last_candle":
                {"open": 29299.0, "high": 29300.0, "low": 29289.0, "close": 29290.0}}}}
        self.assertFalse(Z(down, "long", pl))
        # candle entirely away from the zone (no overlap) -> no confirm
        far = {"timeframes": {"1m": {"last_candle":
               {"open": 29350.0, "high": 29360.0, "low": 29349.0, "close": 29359.0}}}}
        self.assertFalse(Z(far, "long", pl))
        # no zone -> no confirm
        self.assertFalse(Z(exit_up, "long", {"level_type": "no_zone"}))

    def test_gate_block_no_trade(self):
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish")
        facts = FP.build_facts_from_snapshot(snap, {"direction": "bullish"},
                                             self._gate(False), 29300.0)
        self.assertFalse(_author(facts).authorized)   # commander/trigger/etc blocked

    def test_neutral_decision_no_trade(self):
        from integrations.ninjatrader.deterministic import facts_provider as FP
        snap = self._snapshot("bullish")
        facts = FP.build_facts_from_snapshot(snap, {"direction": "neutral"},
                                             self._gate(True), 29300.0)
        self.assertIsNone(facts["direction"])
        self.assertFalse(_author(facts).authorized)


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
