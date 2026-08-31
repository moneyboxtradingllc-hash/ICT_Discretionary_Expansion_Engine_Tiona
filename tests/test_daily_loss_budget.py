"""LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 — a spending limit on the NEXT entry.

THE MISMATCH THIS CLOSES. Project doctrine said "normal Luna daily loss $725".
The TopstepX organism had no such thing: `725` appeared nowhere, `topstep_limits`
was wired only to the NinjaTrader lane, `.env DAILY_LOSS_LIMIT_DOLLARS` belonged
to paper, and session end was triggered by ATTEMPT COUNT alone. What actually
constrained a session was 2 attempts x $350 PLANNED -- which would authorize a
full second $350 trade after the first one slipped well past its planned loss.

WHAT IS ASSERTED HERE, hardest first:

  1. IT IS NOT A GUARANTEE. A stop becomes a market order when it triggers. At
     15 contracts every point beyond it costs $30, so a -$760 session is
     reachable and this governor must never claim it prevented that. It refuses
     the NEXT entry. That is the whole promise.
  2. OWNERSHIP IS PROVEN, NEVER ASSUMED. Only venue trades whose order is OWNED
     by certified lineage count. An unattributable in-session fill is
     CONTAMINATED, not ignored -- this very account carries four 15-lot manual
     fills from 2026-08-28 that no lineage would claim.
  3. FAILING TO KNOW COSTS NOTHING. A venue read failure, incomplete discovery
     or an unsigned budget refuses entry WITHOUT consuming an attempt.
  4. MANAGEMENT IS NEVER GOVERNED.
  5. WINS DO NOT COMPOUND.

D1-D29 are the mission's cases, named inline.
"""
from __future__ import annotations

import os
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import broker.daily_loss_budget as DLB                                  # noqa: E402
import broker.topstepx_session_authorization as SA                      # noqa: E402
from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD        # noqa: E402

CID = "CON.F.US.MNQ.U26"
BUDGET = 725.00
MAXR = PRODUCTION_MAX_RISK_USD
START = "2026-08-31T13:00:00+00:00"          # 09:00 ET
LATER = "2026-08-31T14:30:00+00:00"
BEFORE = "2026-08-31T11:00:00+00:00"         # prior to the window


class Mission:
    """The durable facts the governor reads off a trade mission."""

    def __init__(self, mission_id="M1", order_id=1001, exit_order_id=None,
                 protective_order_ids=(), token_id="prod-abc", custom_tag=""):
        self.mission_id = mission_id
        self.order_id = order_id
        self.exit_order_id = exit_order_id
        self.protective_order_ids = list(protective_order_ids)
        self.token_id = token_id
        self.custom_tag = custom_tag


def order(oid, *, parent=None, tag=None, contract=CID):
    o = {"id": oid, "contract_id": contract}
    if parent is not None:
        o["parent_order_id"] = parent
    if tag is not None:
        o["custom_tag"] = tag
    return o


def trade(oid, pnl=None, fees=0.36, commissions=0.25, *, size=1,
          created=LATER, voided=False):
    return {"order_id": oid, "pnl": pnl, "fees": fees,
            "commissions": commissions, "size": size,
            "created": created, "voided": voided}


def run(*, trades, orders=None, missions=None, budget=BUDGET, complete=True,
        start=START):
    return DLB.compute(budget_usd=budget, orders=orders if orders is not None else [],
                       trades=trades, missions=missions or [Mission()],
                       contract_id=CID, session_start=start,
                       max_risk_usd=MAXR, discovery_complete=complete)


# ── the arithmetic ────────────────────────────────────────────────────────────

class TestBudgetArithmetic:
    def test_D1_fresh_session_allows_the_normal_cap(self):
        r = run(trades=[])
        assert r["state"] == DLB.OK
        assert r["remaining_daily_room"] == BUDGET
        assert r["allowed_planned_risk"] == MAXR == 350.0

    def test_D2_a_full_planned_loser_leaves_room_for_another(self):
        r = run(trades=[trade(1001, pnl=-350.0, fees=0.0, commissions=0.0)])
        assert r["loss_used"] == 350.0
        assert r["remaining_daily_room"] == 375.0
        assert r["allowed_planned_risk"] == 350.0      # still the normal cap

    def test_D3_a_slipped_loser_caps_the_next_trade_below_350(self):
        """THE CASE THE OLD LAW MISSED. Trade one planned $350 and realized
        $410; the previous organism would still authorize a full $350 second
        trade."""
        r = run(trades=[trade(1001, pnl=-410.0, fees=0.0, commissions=0.0)])
        assert r["loss_used"] == 410.0
        assert r["remaining_daily_room"] == 315.0
        assert r["allowed_planned_risk"] == 315.0

    def test_D4_a_dollar_of_room_is_not_a_trade(self):
        r = run(trades=[trade(1001, pnl=-724.0, fees=0.0, commissions=0.0)])
        assert r["remaining_daily_room"] == 1.0
        assert r["allowed_planned_risk"] == 1.0
        # sizing turns $1 into zero contracts; proven in TestSizeDown below

    def test_D5_exactly_the_budget_closes_entry(self):
        r = run(trades=[trade(1001, pnl=-725.0, fees=0.0, commissions=0.0)])
        assert r["state"] == DLB.EXHAUSTED
        assert r["entry_permitted"] is False
        assert r["allowed_planned_risk"] == 0.0

    def test_D6_an_overshoot_closes_entry_and_claims_no_prevention(self):
        r = run(trades=[trade(1001, pnl=-760.0, fees=0.0, commissions=0.0)])
        assert r["state"] == DLB.EXHAUSTED
        assert r["loss_used"] == 760.0
        assert r["remaining_daily_room"] == 0.0        # floored, never negative
        assert r["guarantees_max_realized_loss"] is False

    def test_D7_wins_do_not_compound_risk(self):
        r = run(trades=[trade(1001, pnl=500.0, fees=0.0, commissions=0.0)])
        assert r["loss_used"] == 0.0                   # max(0, -pnl)
        assert r["remaining_daily_room"] == BUDGET     # not 1225
        assert r["allowed_planned_risk"] == 350.0

    def test_D26_a_winner_never_raises_the_per_trade_cap(self):
        big = run(trades=[trade(1001, pnl=5000.0, fees=0.0, commissions=0.0)])
        assert big["allowed_planned_risk"] == MAXR

    def test_a_win_offsets_an_earlier_loss(self):
        m = Mission(order_id=1001, exit_order_id=1002)
        r = run(trades=[trade(1001, pnl=-400.0, fees=0.0, commissions=0.0),
                        trade(1002, pnl=150.0, fees=0.0, commissions=0.0)],
                orders=[order(1001), order(1002)], missions=[m])
        assert r["state"] == DLB.OK
        assert r["loss_used"] == 250.0
        assert r["remaining_daily_room"] == 475.0


# ── accounting ────────────────────────────────────────────────────────────────

class TestEconomicAccounting:
    def test_D23_both_actual_costs_are_charged(self):
        """`pnl - fees` alone was NOT conservative: it omitted the commission
        the venue also charges, handing Luna room she does not economically
        have. This unit exists because $700 planned and $725 realized are
        different numbers; closing that with a smaller mismatch of the same
        shape would have been the same error."""
        r = run(trades=[trade(1001, pnl=-300.0, fees=5.40, commissions=3.75)])
        acct = r["accounting"]
        assert acct["gross_session_pnl"] == -300.0
        assert acct["actual_exchange_fees"] == 5.40
        assert acct["commission_cost"] == 3.75
        assert acct["budget_session_pnl"] == -309.15
        assert r["loss_used"] == 309.15

    def test_fees_alone_would_have_overstated_the_room(self):
        r = run(trades=[trade(1001, pnl=-300.0, fees=5.40, commissions=3.75)])
        assert r["accounting"]["budget_session_pnl"] < -300.0 - 5.40

    def test_D8_costs_are_charged_on_winners_too(self):
        r = run(trades=[trade(1001, pnl=200.0, fees=5.40, commissions=3.75)])
        assert r["accounting"]["budget_session_pnl"] == 190.85

    def test_sign_conventions_cannot_widen_room(self):
        r = run(trades=[trade(1001, pnl=-100.0, fees=-5.40, commissions=-3.75)])
        assert r["accounting"]["budget_session_pnl"] == -109.15

    def test_a_row_that_states_no_cost_is_recorded_not_assumed_free(self):
        r = DLB.budget_pnl([{"pnl": -50.0, "fees": None, "commissions": None}])
        assert r["rows_missing_cost_fields"] == 1
        assert r["total_transaction_cost"] == 0.0

    def test_the_label_is_economic_and_names_its_inputs(self):
        acct = run(trades=[trade(1001, pnl=-10.0)])["accounting"]
        assert acct["label"] == "ECONOMIC_BUDGET_PNL"
        assert "PROVEN GROSS" in acct["note"]

    def test_slippage_reserve_is_never_subtracted(self):
        """Real slippage is already inside the fill prices that produced
        profitAndLoss. The sizing reserve is a forecast for a trade not yet
        taken; charging both would bill the session twice for one thing."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "broker",
                                           "daily_loss_budget.py"),
                              encoding="utf-8").read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for banned in ("SLIPPAGE_RESERVE_TICKS_PER_SIDE", "friction_per_contract",
                       "slippage_reserve"):
            assert banned not in names, banned

    def test_the_proven_venue_convention_is_recorded(self):
        """THE REAL ROWS, traded 2026-08-28, read from the venue 2026-08-31:
        (29765.00-29773.75)x$2x15 = -$262.50 == venue pnl -262.50
        (29782.75-29732.25)x$2x15 = +$1515.00 == venue pnl +1515.00
        fees $5.40/leg = $0.72/contract RT · commissions $3.75/leg = $0.50 RT
        `pnl` null on the opening leg, populated on the closing leg."""
        rows = [trade(1, pnl=None, fees=5.40, commissions=3.75, size=15),
                trade(2, pnl=-262.5, fees=5.40, commissions=3.75, size=15),
                trade(3, pnl=None, fees=5.40, commissions=3.75, size=15),
                trade(4, pnl=1515.0, fees=5.40, commissions=3.75, size=15)]
        acct = DLB.budget_pnl(rows)
        assert acct["gross_session_pnl"] == 1252.5
        assert acct["actual_exchange_fees"] == 21.6
        assert acct["commission_cost"] == 15.0
        assert acct["budget_session_pnl"] == 1215.9
        assert acct["rows_with_pnl"] == 2      # opening legs carry no pnl

    def test_the_venue_costs_confirm_the_certified_model(self):
        """Both halves of the repo's measured fixed-cost model were confirmed
        independently by the venue read, so the actual fields and the model
        agree rather than merely coexisting."""
        from broker import topstepx_combine_risk as R
        assert round(5.40 / 15 * 2, 4) == R.FIXED_ROUND_TRIP_FEES_PER_CONTRACT
        assert round(3.75 / 15 * 2, 4) == \
            R.FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT


# ── ownership ─────────────────────────────────────────────────────────────────

class TestOwnership:
    def test_D16_entry_and_owned_children_are_attributed(self):
        m = Mission(order_id=1001, exit_order_id=1003,
                    protective_order_ids=[1002])
        r = run(trades=[trade(1001, pnl=None), trade(1002, pnl=-120.0),
                        trade(1003, pnl=-40.0)],
                orders=[order(1001), order(1002), order(1003)], missions=[m])
        assert r["state"] == DLB.OK
        assert r["attributed_trades"] == 3
        # 3 rows x ($0.36 fees + $0.25 commissions) on top of $160 gross loss
        assert r["loss_used"] == pytest.approx(160.0 + 3 * (0.36 + 0.25))

    def test_a_venue_linked_child_is_owned_without_being_recorded(self):
        """`protective_order_ids` was EMPTY on the real 2026-08-25 T1 because
        that trade auto-flattened before protection established. The venue's own
        parent link still proves the child is ours."""
        m = Mission(order_id=1001, protective_order_ids=[])
        r = run(trades=[trade(2002, pnl=-90.0, fees=0.0, commissions=0.0)],
                orders=[order(1001), order(2002, parent=1001)], missions=[m])
        assert r["state"] == DLB.OK
        assert r["loss_used"] == 90.0

    def test_our_own_tag_proves_ownership(self):
        m = Mission(order_id=None, custom_tag="EXPBOT-prod-abc")
        r = run(trades=[trade(5005, pnl=-50.0, fees=0.0, commissions=0.0)],
                orders=[order(5005, tag="EXPBOT-prod-abc")], missions=[m])
        assert r["state"] == DLB.OK

    def test_the_token_inside_a_tag_proves_ownership(self):
        m = Mission(order_id=None, token_id="prod-3066bead3250")
        r = run(trades=[trade(7007, pnl=-25.0, fees=0.0, commissions=0.0)],
                orders=[order(7007, tag="EXPBOT-prod-3066bead3250")], missions=[m])
        assert r["state"] == DLB.OK

    def test_D15_same_contract_is_never_ownership(self):
        """The four 15-lot manual fills on this account are the live proof."""
        r = run(trades=[trade(9999, pnl=-262.5, fees=5.40, size=15)],
                orders=[order(1001), order(9999)], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.CONTAMINATED
        assert r["entry_permitted"] is False
        assert r["unattributed_count"] == 1
        assert r["unattributed"][0]["order_id"] == 9999

    def test_D17_unknown_ownership_fails_closed(self):
        r = run(trades=[trade(4242, pnl=100.0, fees=0.0, commissions=0.0)],
                orders=[], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.CONTAMINATED

    def test_a_profitable_unattributed_trade_still_contaminates(self):
        """Contamination is about not knowing whose P&L it is, not about the
        sign of the number."""
        r = run(trades=[trade(9999, pnl=+900.0, fees=0.0, commissions=0.0)],
                orders=[order(9999)], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.CONTAMINATED

    def test_a_voided_trade_is_ignored(self):
        r = run(trades=[trade(9999, pnl=-500.0, voided=True)],
                orders=[], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.OK
        assert r["remaining_daily_room"] == BUDGET


# ── session window ────────────────────────────────────────────────────────────

class TestSessionWindow:
    def test_D21_the_window_starts_at_the_authorized_local_open(self):
        got = DLB.session_start_utc(session_date="20260831", window_start="09:00",
                                    tz_name="America/New_York")
        assert got.isoformat() == "2026-08-31T13:00:00+00:00"     # EDT

    def test_the_window_is_not_utc_midnight(self):
        """`recent_trades`' default reaches back to Sunday 20:00 ET on a Monday
        and would let a prior session's realized P&L leak into today's budget."""
        got = DLB.session_start_utc(session_date="20260831", window_start="09:00",
                                    tz_name="America/New_York")
        assert got.hour == 13 and got.minute == 0

    def test_D22_a_trade_before_the_session_start_is_excluded(self):
        r = run(trades=[trade(1001, pnl=-600.0, fees=0.0, created=BEFORE)],
                orders=[order(1001)], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.OK
        assert r["remaining_daily_room"] == BUDGET

    def test_a_prior_session_foreign_trade_does_not_contaminate(self):
        r = run(trades=[trade(9999, pnl=-100.0, created=BEFORE)],
                orders=[], missions=[Mission(order_id=1001)])
        assert r["state"] == DLB.OK

    def test_an_unusable_window_is_unknown_not_a_crash(self):
        assert DLB.session_start_utc(session_date="nope", window_start="09:00",
                                     tz_name="America/New_York") is None


# ── failure semantics ─────────────────────────────────────────────────────────

class TestFailClosed:
    def test_D9_unknown_pnl_closes_entry(self):
        r = DLB.compute(budget_usd=BUDGET, orders=None, trades=None,
                        missions=[Mission()], contract_id=CID,
                        session_start=START, max_risk_usd=MAXR)
        assert r["state"] == DLB.UNKNOWN
        assert r["entry_permitted"] is False
        assert r["reason"] == DLB.NO_VENUE

    def test_incomplete_discovery_closes_entry(self):
        r = run(trades=[], complete=False)
        assert r["state"] == DLB.UNKNOWN
        assert r["reason"] == DLB.DISCOVERY_INCOMPLETE

    def test_D18_an_unsigned_budget_closes_entry(self):
        r = run(trades=[], budget=None)
        assert r["state"] == DLB.UNKNOWN
        assert r["reason"] == DLB.NO_BUDGET

    def test_a_nonpositive_budget_closes_entry(self):
        for bad in (0, -725.0, "x"):
            assert run(trades=[], budget=bad)["entry_permitted"] is False

    def test_D24_a_venue_failure_never_raises(self):
        class Broken:
            def recent_trades(self, since=None):
                raise RuntimeError("venue down")
        r = DLB.resolve(session=Broken(), contract_id=CID, missions=[Mission()],
                        authorization=SA.SessionAuthorization(
                            session_id="S", account_fingerprint="a",
                            contract_id=CID, session_date="20260831",
                            decision_window="09:00-14:00 America/New_York",
                            daily_loss_budget_usd=BUDGET),
                        max_risk_usd=MAXR)
        assert r["state"] == DLB.UNKNOWN
        assert r["entry_permitted"] is False

    def test_every_refusal_still_reports_the_budget_terms(self):
        for r in (run(trades=[], complete=False), run(trades=[], budget=None)):
            assert r["max_risk_usd"] == MAXR
            assert r["allowed_planned_risk"] == 0.0


# ── the authorization contract ────────────────────────────────────────────────

class TestAuthorizationBinding:
    def _auth(self, **kw):
        # RESOLVED, NOT ASSUMED. `retrieval_enabled` is a SEPARATE binding with
        # its own refusal, and production `issue()` records the state the
        # runtime actually resolves rather than hard-coding one. A sibling test
        # that has called load_dotenv() leaves AI_RETRIEVAL_ENABLED=true set
        # process-wide, so a literal here would make these budget assertions
        # pass or fail on test ORDER instead of on their own subject. This
        # weakens nothing: verify() still enforces the retrieval binding, and
        # the budget refusals below are asserted individually.
        base = dict(session_id="PRAC-X", account_fingerprint="acct:x",
                    contract_id=CID, session_date="20260831",
                    retrieval_enabled=SA._issue_retrieval_state(),
                    decision_window="09:00-14:00 America/New_York")
        base.update(kw)
        a = SA.SessionAuthorization(**base)
        a.authorization_fingerprint = a.fingerprint()
        return a

    def test_D19_the_fingerprint_commits_to_the_budget(self):
        a = self._auth(daily_loss_budget_usd=725.00)
        b = self._auth(daily_loss_budget_usd=1000.00)
        assert a.fingerprint() != b.fingerprint()

    def test_D20_editing_the_budget_after_signing_fails(self):
        a = self._auth(daily_loss_budget_usd=725.00)
        a.daily_loss_budget_usd = 5000.00
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint="acct:x", contract_id=CID,
                     session_date="20260831")
        assert "AUTHORIZATION_CORRUPT" in str(exc.value)

    def test_D18_a_record_without_the_budget_cannot_verify(self):
        a = self._auth()
        assert a.daily_loss_budget_usd is None
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint="acct:x", contract_id=CID,
                     session_date="20260831")
        assert "NO_DAILY_LOSS_BUDGET" in str(exc.value)

    def test_the_refusal_names_schema_growth_not_tampering(self):
        """A legacy record is honest, not edited. Reporting it as CORRUPT would
        accuse it of something it did not do."""
        a = self._auth()
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint="acct:x", contract_id=CID,
                     session_date="20260831")
        assert "AUTHORIZATION_CORRUPT" not in str(exc.value)

    def test_the_sentinel_is_none_not_a_default_value(self):
        """`= 725.0` would silently grant every pre-existing authorization a
        term it never signed."""
        import dataclasses
        f = {x.name: x for x in dataclasses.fields(SA.SessionAuthorization)}
        assert f["daily_loss_budget_usd"].default is None

    def test_no_unrelated_constructor_inherits_a_budget(self):
        assert SA.SessionAuthorization(
            session_id="s", account_fingerprint="a", contract_id=CID,
            session_date="20260831",
            decision_window="w").daily_loss_budget_usd is None

    def test_a_signed_budget_verifies(self):
        a = self._auth(daily_loss_budget_usd=725.00)
        assert a.verify(account_fingerprint="acct:x", contract_id=CID,
                        session_date="20260831") is a

    def test_the_owner_law_is_the_issued_value(self):
        assert SA.DAILY_LOSS_BUDGET_USD == 725.00

    def test_the_budget_is_not_read_from_legacy_config(self):
        """STRUCTURAL, NOT TEXTUAL. The module's own comment NAMES the legacy
        sources it refuses to read, so grepping for those names flags the
        sentence that forbids them. Read the code instead."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "broker",
                                           "topstepx_session_authorization.py"),
                              encoding="utf-8").read())
        mods, calls = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
            elif isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.Call):
                f = n.func
                calls.add(getattr(f, "attr", None) or getattr(f, "id", None))
        assert not any("topstep_limits" in m for m in mods), sorted(mods)
        assert "getenv" not in calls
        assert "environ" not in calls


# ── sizing ────────────────────────────────────────────────────────────────────

class TestSizeDown:
    def _qty(self, ceiling, stop_points):
        from broker.topstepx_combine_risk import size_for_risk

        class C:
            id = CID
            tick_size = 0.25
            tick_value = 0.5
        return size_for_risk(stop_points=stop_points, contract=C(),
                             max_risk_usd=ceiling, max_contracts=15)

    def test_D27_a_reduced_ceiling_reduces_quantity_only(self):
        full = self._qty(350.0, 20.0)
        capped = self._qty(315.0, 20.0)
        assert capped["contracts"] < full["contracts"]
        assert capped["contracts"] > 0

    def test_D28_a_dollar_of_room_fits_no_contract(self):
        assert self._qty(1.0, 20.0)["contracts"] == 0

    def test_D11_the_fifteen_contract_ceiling_survives_a_full_budget(self):
        assert self._qty(350.0, 1.0)["contracts"] <= 15

    def test_D10_the_structural_stop_is_never_altered(self):
        """The ceiling changes SIZE. Moving the invalidation inward to fit a
        budget would be inventing a different trade and calling it the same one.
        `gross_stop_risk_per_contract` is the stop distance in dollars, so an
        identical value across two ceilings proves the geometry did not move."""
        a = self._qty(350.0, 20.0)
        b = self._qty(200.0, 20.0)
        assert a["gross_stop_risk_per_contract"] ==             b["gross_stop_risk_per_contract"] == 40.0
        assert a["contracts"] > b["contracts"] > 0

    def test_D25_all_three_build_runner_ceilings_receive_one_value(self):
        """The runner's own recheck exists so the final gate cannot fall back to
        a laxer default. A governor that reduced only the sizing call would be
        undone by it."""
        import ast
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_session.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "build_runner")
        # Every `max_risk_usd=` keyword inside build_runner must receive the ONE
        # governed name. The binding itself legitimately mentions the raw cap.
        supplied = [kw.value for n in ast.walk(fn) if isinstance(n, ast.Call)
                    for kw in n.keywords if kw.arg == "max_risk_usd"]
        assert supplied, "no max_risk_usd keyword found in build_runner"
        for v in supplied:
            assert isinstance(v, ast.Name) and v.id == "effective_max_risk",                 ast.dump(v)
        # ... and the runner's own recheck attribute, which is an assignment.
        assigned = [n.value.id for n in ast.walk(fn)
                    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name)
                    and any(getattr(t, "attr", None) == "max_risk_usd"
                            for t in n.targets)]
        assert assigned == ["effective_max_risk"], assigned


# ── the promise, and its limits ───────────────────────────────────────────────

class TestTheClaim:
    def test_D29_no_hard_loss_prevention_is_ever_claimed(self):
        r = run(trades=[trade(1001, pnl=-760.0, fees=0.0, commissions=0.0)])
        assert r["guarantees_max_realized_loss"] is False

    def test_the_module_says_what_it_cannot_do(self):
        """BEHAVIOURAL, NOT PROSE. Asserting a sentence breaks on a line wrap and
        proves nothing a consumer can read. Assert the FLAG every caller sees
        instead: no state, however healthy, may claim a hard loss guarantee."""
        for r in (run(trades=[]),
                  run(trades=[trade(1001, pnl=-100.0, fees=0.0, commissions=0.0)]),
                  run(trades=[trade(1001, pnl=-760.0, fees=0.0, commissions=0.0)]),
                  run(trades=[], budget=None),
                  run(trades=[], complete=False)):
            assert r["guarantees_max_realized_loss"] is False, r["state"]

    def test_D12_the_attempt_cap_is_a_separate_axis(self):
        """A winner never earns a third attempt; an exhausted budget never
        rewrites attempt history."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "broker",
                                           "daily_loss_budget.py"),
                              encoding="utf-8").read())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for banned in ("trades_used", "maximum_trades", "attempt_count",
                       "consume_attempt"):
            assert banned not in names, banned

    def test_D13_D14_the_governor_cannot_reach_management(self):
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "broker",
                                           "daily_loss_budget.py"),
                              encoding="utf-8").read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
            elif isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
        for banned in ("broker.break_even", "broker.break_even_actuator",
                       "broker.protection_state", "broker.topstepx_mission_state"):
            assert banned not in mods, banned

    def test_management_runs_before_the_entry_governor(self):
        """Ordering is the guarantee, not a promise: `manage_open_position()` is
        called at the top of the tick, the budget is resolved much later."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        assert src.index("self.last_management = self.manage_open_position()") < \
            src.index("budget = DLB.resolve(")

    def test_the_governor_resolves_before_an_attempt_is_spent(self):
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        assert src.index("budget = DLB.resolve(") < src.index("self.ps.build_runner(")

    def test_it_never_raises_on_malformed_input(self):
        for bad in (None, [], [None], [{"pnl": "x"}], [{"order_id": None}]):
            r = run(trades=bad, orders=[], missions=[Mission()])
            assert r["state"] in DLB.STATES


class TestPersistenceBoundary:
    """THE RECORD, NOT THE OBJECT.

    Every other test in this file builds a `SessionAuthorization` in memory. All
    58 of them passed while a correctly signed $725 record could not survive a
    write/read cycle: `load()` carries an explicit field allowlist, the new term
    was not in it, and the value was silently dropped. The launcher loads from
    disk, so a freshly minted authorization would have refused itself at startup
    with NO_DAILY_LOSS_BUDGET.

    These tests therefore use the REAL `issue()` / `load()` path on a real file.
    A constructor on both sides would reproduce the same blind spot.
    """

    ACCT = "acct:x"
    DATE = "20260901"

    def _issue(self, tmp_path, session_id="PERSIST-1"):
        path = os.path.join(str(tmp_path), "session_auth_%s.json" % session_id)
        return path, SA.issue(path=path, session_id=session_id,
                              account_fingerprint=self.ACCT, contract_id=CID,
                              session_date=self.DATE)

    def test_a_signed_budget_survives_write_and_read(self, tmp_path):
        path, issued = self._issue(tmp_path)
        assert issued.daily_loss_budget_usd == SA.DAILY_LOSS_BUDGET_USD
        assert json.load(open(path, encoding="utf-8"))[
            "daily_loss_budget_usd"] == SA.DAILY_LOSS_BUDGET_USD
        loaded = SA.SessionAuthorization.load(path)
        assert loaded.daily_loss_budget_usd == 725.00

    def test_the_loaded_record_keeps_the_written_signature(self, tmp_path):
        path, issued = self._issue(tmp_path)
        loaded = SA.SessionAuthorization.load(path)
        assert loaded.authorization_fingerprint == issued.authorization_fingerprint
        assert loaded.fingerprint() == loaded.authorization_fingerprint

    def test_the_loaded_record_verifies_under_the_launchers_law(self, tmp_path):
        """The end-to-end property the defect actually broke."""
        path, _ = self._issue(tmp_path)
        loaded = SA.SessionAuthorization.load(path)
        assert loaded.verify(account_fingerprint=self.ACCT, contract_id=CID,
                             session_date=self.DATE) is loaded

    def test_a_historical_record_loads_for_inspection_but_cannot_authorize(
            self, tmp_path):
        """SCHEMA GROWTH IS NOT TAMPERING. A record written before this term
        existed must remain readable and auditable, and must not authorize."""
        path, _ = self._issue(tmp_path, "LEGACY-1")
        d = json.load(open(path, encoding="utf-8"))
        del d["daily_loss_budget_usd"]                 # as a pre-unit record was
        json.dump(d, open(path, "w", encoding="utf-8"))
        loaded = SA.SessionAuthorization.load(path)
        assert loaded is not None                      # still inspectable
        assert loaded.daily_loss_budget_usd is None    # never defaulted to 725
        with pytest.raises(SA.AuthorizationRefused) as exc:
            loaded.verify(account_fingerprint=self.ACCT, contract_id=CID,
                          session_date=self.DATE)
        assert "NO_DAILY_LOSS_BUDGET" in str(exc.value)
        assert "CORRUPT" not in str(exc.value)

    def test_a_hand_widened_budget_on_disk_fails_verification(self, tmp_path):
        """The signature is what makes the number binding."""
        path, _ = self._issue(tmp_path, "TAMPER-1")
        d = json.load(open(path, encoding="utf-8"))
        d["daily_loss_budget_usd"] = 10000.00          # widened, not re-signed
        json.dump(d, open(path, "w", encoding="utf-8"))
        loaded = SA.SessionAuthorization.load(path)
        # NOT normalized away on load: the tampered value is carried through so
        # the mismatch is visible rather than quietly repaired.
        assert loaded.daily_loss_budget_usd == 10000.00
        with pytest.raises(SA.AuthorizationRefused) as exc:
            loaded.verify(account_fingerprint=self.ACCT, contract_id=CID,
                          session_date=self.DATE)
        assert "CORRUPT" in str(exc.value)

    def test_a_narrowed_budget_on_disk_also_fails(self, tmp_path):
        """Tampering DOWNWARD is still tampering. A record that no longer states
        what was signed is not authoritative just because it looks safer."""
        path, _ = self._issue(tmp_path, "TAMPER-2")
        d = json.load(open(path, encoding="utf-8"))
        d["daily_loss_budget_usd"] = 100.00
        json.dump(d, open(path, "w", encoding="utf-8"))
        with pytest.raises(SA.AuthorizationRefused, match="CORRUPT"):
            SA.SessionAuthorization.load(path).verify(
                account_fingerprint=self.ACCT, contract_id=CID,
                session_date=self.DATE)
