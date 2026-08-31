"""RISK-DOCTRINE-MIGRATION — 40 -> 50 points, $250 -> $350, $500 -> $725.

Operator ruling, 2026-08-20.

THE OCCASION, precisely. At 11:03 ET Luna held a bearish thesis whose structural
invalidation was the 29470.25 protected high. Measured from 29429.50 that is
40.75 points -- three ticks past the 40.0 ceiling -- so the setup died on
ELIGIBILITY rather than on judgement. NQ can genuinely require that much
structural room, and a ceiling that rejects a clean setup over three ticks is
too tight for the instrument.

THE OCCASION IS NOT THE JUSTIFICATION, and this unit does not pretend otherwise.
One scan later, at the 11:04 actionable scan, the protected-high stop was 31.00
points -- 29470.25 measured from 29439.25 -- already legal under the old 40.0
ceiling and already fundable under the old $250 cap, which sized it at 3 MNQ.
That trade was missed for reasons this migration does not touch. Nothing here
repairs the 2026-08-20 miss, and nothing here should be read as having done so.

A 29.50-point figure also appears in this day's record and is NOT this one: it
is 29470.25 measured from the 11:02 candle OPEN of 29440.75, the geometry
EXEC-PRICE-FRESHNESS-1 restored when it stopped pricing exposure off a settled
close. Different scan, different defect. The two must not be conflated.

WHAT 50 IS. A VETO CEILING, NOT A TARGET. The preferred bound is unchanged at
35.0, so the extended-volatility lane widens from 5 points to 15: setups that
must JUSTIFY their width with current evidence, never setups handed a wider
stop. The stop remains exactly the structural invalidation, and nothing may
widen one to consume budget.

WHAT $350 IS. A BUDGET CEILING. It buys CONTRACTS at a structural stop; it never
buys a wider one. A 31-point setup does not become a $350 risk -- integer sizing
still decides, and the engine bills all-in (point risk plus measured fixed cost
plus slippage reserve), so planned risk lands under the cap rather than on it.

WHAT $725 IS. Two trades at the $350 ceiling is $700; the remaining $25 is
headroom for commissions, fees and rounding, so the hard daily stop does not sit
exactly on the theoretical planned-risk sum.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_combine_risk as R                    # noqa: E402
from broker import topstepx_production_doctrine as D             # noqa: E402
from broker.topstepx_client import TopstepXContract              # noqa: E402
from operational_readiness import prac_release as PR             # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)

#: 2026-08-20, the 11:02 one-minute candle and the 5m protected high above it.
PROTECTED_HIGH = 29470.25
THE_11_03_STOP = 40.75          # 11:03:34 scan, price 29429.50 -- over by 3 ticks
THE_11_04_STOP = 31.00          # 11:04:53 scan, price 29439.25 -- ALREADY legal
#: NOT an 11:04 fact. The 11:02 candle OPEN, restored by EXEC-PRICE-FRESHNESS-1.
THE_11_02_OPEN_STOP = 29.50


class TestTheNumbersMoved:
    def test_the_absolute_ceiling_is_fifty(self):
        assert R.ABSOLUTE_MAX_STOP_POINTS == 50.0

    def test_the_risk_cap_is_three_fifty(self):
        assert R.PRODUCTION_MAX_RISK_USD == 350.00

    def test_the_daily_ceiling_is_seven_twenty_five(self):
        from adaptive_learning.capital_intelligence_engine import (
            DEFAULT_DAILY_LOSS_LIMIT_USD)
        assert DEFAULT_DAILY_LOSS_LIMIT_USD == 725.0

    def test_two_trades_at_the_cap_fit_under_the_daily_ceiling(self):
        from adaptive_learning.capital_intelligence_engine import (
            DEFAULT_DAILY_LOSS_LIMIT_USD)
        assert 2 * R.PRODUCTION_MAX_RISK_USD == 700.0
        assert DEFAULT_DAILY_LOSS_LIMIT_USD - 700.0 == 25.0


class TestTheNumbersThatDidNotMove:
    def test_the_preferred_stop_is_unchanged(self):
        assert R.PREFERRED_MAX_STOP_POINTS == 35.0

    def test_the_contract_cap_is_unchanged(self):
        assert R.PRODUCTION_MAX_CONTRACTS == 15

    def test_the_reward_floor_is_unchanged(self):
        assert R.MIN_REWARD_TO_RISK == 1.0

    def test_the_extended_lane_widened_rather_than_the_preferred_bound(self):
        assert R.ABSOLUTE_MAX_STOP_POINTS - R.PREFERRED_MAX_STOP_POINTS == 15.0


class TestTheCeilingBoundary:
    @pytest.mark.parametrize("pts,lane", [
        (10.00, R.NORMAL_STOP_RANGE),
        (35.00, R.NORMAL_STOP_RANGE),               # preferred, still normal
        (35.25, R.EXTENDED_VOLATILITY_STOP_RANGE),
        (40.00, R.EXTENDED_VOLATILITY_STOP_RANGE),
        (THE_11_03_STOP, R.EXTENDED_VOLATILITY_STOP_RANGE),   # 40.75
        (47.00, R.EXTENDED_VOLATILITY_STOP_RANGE),
        (49.75, R.EXTENDED_VOLATILITY_STOP_RANGE),
        (50.00, R.EXTENDED_VOLATILITY_STOP_RANGE),  # inclusive
        (50.25, R.STOP_DISTANCE_REJECTED),          # one tick past
        (60.00, R.STOP_DISTANCE_REJECTED),
    ])
    def test_classification(self, pts, lane):
        assert R.classify_stop_distance(pts) == lane

    #: The extended lane demands BOTH elevated volatility AND a named structural
    #: level. This is what makes 50 a veto ceiling rather than a target, and it
    #: is enforced by `extended_volatility_supported`, not by convention.
    EVIDENCE = {"volatility_state": "expansion",
                "structural_level_identity": "5m:protected_high:29470.25"}

    def test_the_forty_point_seven_five_setup_is_now_eligible(self):
        """The exact 2026-08-20 11:03 geometry, which the old ceiling refused."""
        entry = PROTECTED_HIGH - THE_11_03_STOP
        out = R.build_production_bracket(
            direction="bearish", entry_price=entry,
            invalidation_level=PROTECTED_HIGH, target_price=29240.25,
            contract=MNQ, evidence=self.EVIDENCE)
        assert out["geometry"].stop_points == pytest.approx(THE_11_03_STOP)
        assert out["sizing"]["contracts"] >= 1

    def test_the_wider_ceiling_is_unreachable_without_named_structure(self):
        """A busy market is not a licence to use the ceiling."""
        with pytest.raises(R.RiskRejection) as exc:
            R.build_production_bracket(
                direction="bearish", entry_price=PROTECTED_HIGH - THE_11_03_STOP,
                invalidation_level=PROTECTED_HIGH, target_price=29240.25,
                contract=MNQ, evidence={"volatility_state": "expansion"})
        assert exc.value.reason == "extended_volatility_unsupported"

    def test_the_wider_ceiling_is_unreachable_in_quiet_volatility(self):
        with pytest.raises(R.RiskRejection) as exc:
            R.build_production_bracket(
                direction="bearish", entry_price=PROTECTED_HIGH - THE_11_03_STOP,
                invalidation_level=PROTECTED_HIGH, target_price=29240.25,
                contract=MNQ,
                evidence={"volatility_state": "normal",
                          "structural_level_identity": "5m:protected_high:29470.25"})
        assert exc.value.reason == "extended_volatility_unsupported"

    def test_a_stop_inside_the_preferred_range_needs_no_such_evidence(self):
        out = R.build_production_bracket(
            direction="bearish", entry_price=PROTECTED_HIGH - 12.0,
            invalidation_level=PROTECTED_HIGH, target_price=29300.0,
            contract=MNQ, evidence={})
        assert out["sizing"]["contracts"] >= 1

    @pytest.mark.parametrize("pts", [50.25, 60.0])
    def test_past_the_ceiling_is_refused_not_resized(self, pts):
        with pytest.raises(R.RiskRejection):
            R.build_production_bracket(
                direction="bearish", entry_price=PROTECTED_HIGH - pts,
                invalidation_level=PROTECTED_HIGH, target_price=29000.0,
                contract=MNQ, evidence=self.EVIDENCE)


class TestSizingBuysContractsNotWiderStops:
    #: stop -> (contracts under $350, contracts under the retired $250)
    TABLE = {31.00: (5, 3), 35.00: (4, 3), THE_11_03_STOP: (4, 2),
             47.00: (3, 2), 49.75: (3, 2), 50.00: (3, 2)}

    @pytest.mark.parametrize("pts", sorted(TABLE))
    def test_integer_sizing_at_representative_stops(self, pts):
        now, before = self.TABLE[pts]
        assert R.size_for_risk(pts, MNQ)["contracts"] == now
        assert R.size_for_risk(pts, MNQ, max_risk_usd=250.0)["contracts"] == before

    @pytest.mark.parametrize("pts", sorted(TABLE))
    def test_planned_risk_never_exceeds_the_cap(self, pts):
        s = R.size_for_risk(pts, MNQ)
        assert s["all_in_planned_risk"] <= R.PRODUCTION_MAX_RISK_USD
        # and one more contract would break it -- the cap binds, nothing rounds up
        assert ((s["contracts"] + 1) * s["all_in_risk_per_contract"]
                > R.PRODUCTION_MAX_RISK_USD)

    def test_a_tight_stop_does_not_become_a_three_fifty_risk(self):
        """$350 is a ceiling, not an allocation."""
        s = R.size_for_risk(31.00, MNQ)
        assert s["all_in_planned_risk"] < R.PRODUCTION_MAX_RISK_USD

    def test_the_contract_cap_still_binds_above_the_dollar_cap(self):
        huge = R.size_for_risk(1.0, MNQ, max_risk_usd=1_000_000.0)
        assert huge["contracts"] <= R.PRODUCTION_MAX_CONTRACTS


class TestTheStopIsStillStructural:
    def test_the_stop_is_the_invalidation_not_the_ceiling(self):
        out = R.build_production_bracket(
            direction="bearish", entry_price=PROTECTED_HIGH - 12.0,
            invalidation_level=PROTECTED_HIGH, target_price=29300.0,
            contract=MNQ, evidence={"volatility_state": "normal"})
        assert out["geometry"].stop_points == pytest.approx(12.0)
        assert out["geometry"].stop_points < R.PREFERRED_MAX_STOP_POINTS

    def test_a_narrow_stop_does_not_inherit_the_new_ceiling(self):
        out = R.build_production_bracket(
            direction="bullish", entry_price=29500.0,
            invalidation_level=29490.0, target_price=29600.0,
            contract=MNQ, evidence={"volatility_state": "normal"})
        assert out["geometry"].stop_points == pytest.approx(10.0)


class TestEveryMirrorMoved:
    """A mirror that can disagree with its source is the model-identity defect
    in another costume. These are the copies that exist; they must agree."""

    def test_the_preflight_certifies_the_new_numbers(self):
        assert PR.EXPECTED_ABSOLUTE_STOP == R.ABSOLUTE_MAX_STOP_POINTS
        assert PR.EXPECTED_MAX_RISK_USD == R.PRODUCTION_MAX_RISK_USD
        assert PR.EXPECTED_PREFERRED_STOP == R.PREFERRED_MAX_STOP_POINTS
        assert PR.EXPECTED_MAX_CONTRACTS == R.PRODUCTION_MAX_CONTRACTS

    def test_the_startup_guard_admits_the_new_ceiling(self):
        """It compared against literal 40.0/250.0 and would have refused to
        start a correctly-migrated engine."""
        resolved = D.assert_no_conflict()
        assert resolved["absolute_max_stop_points"] == 50.0
        assert resolved["production_max_risk_usd"] == 350.00

    def test_the_startup_guard_reads_the_owner_not_a_literal(self):
        import ast
        import inspect
        src = ast.parse(inspect.getsource(D.assert_no_conflict).lstrip())
        literals = {n.value for n in ast.walk(src)
                    if isinstance(n, ast.Constant) and isinstance(n.value, float)}
        # 10.0 is the SMOKE sentinel and legitimately a literal; the doctrine
        # bounds must not be.
        assert not ({40.0, 50.0, 35.0, 250.0, 350.0} & literals), literals

    def test_the_authorization_cli_mirrors_the_doctrine(self):
        from broker import topstepx_session_authorization as SA
        src = inspect_source(SA)
        for stale in ("40.0", "250.0"):
            assert f"absolute_stop_ceiling: float = {stale}" not in src


class TestOutOfLaneCeilingsAreUntouched:
    """The TopstepX lane moved. Other engines did not."""

    def test_the_ninjatrader_deterministic_ceiling_is_untouched(self):
        from integrations.topstepx import deterministic as NT
        assert NT.DAILY_LOSS_CEILING == 1000.00

    def test_the_deploy_one_risk_profile_is_untouched(self):
        """`instance_config` serves BROKERS = (paper, tradestation) and is read
        only by `tools/create_instance.py` -- not the TopstepX lane."""
        from deployment.instance_config import RiskProfile
        assert RiskProfile().max_daily_loss == 500.0


def inspect_source(mod):
    import inspect
    return inspect.getsource(mod)


class TestTheRecordOfTheDayIsExact:
    """Two different stop distances belong to 2026-08-20 and mean opposite things.

    A draft of this unit recorded "at 11:04 the affordable stop was 29.50", which
    fused them. The number is real; the timestamp is not its own. Left standing
    it would have become the permanent account of the day, and the account is the
    only reason the doctrine moved -- so it is pinned here rather than trusted to
    prose.
    """

    #: The certified scan table, from `data/ai_brain/20260820_*_MNQ.json`.
    SCANS = {"11:03:34": 29429.50, "11:04:53": 29439.25}
    CANDLE_1102_OPEN = 29440.75

    def test_the_eleven_oh_four_stop_is_thirty_one_points(self):
        assert PROTECTED_HIGH - self.SCANS["11:04:53"] == THE_11_04_STOP == 31.00

    def test_the_eleven_oh_two_open_stop_is_twenty_nine_and_a_half(self):
        assert PROTECTED_HIGH - self.CANDLE_1102_OPEN == THE_11_02_OPEN_STOP == 29.50

    def test_they_are_not_the_same_number(self):
        assert THE_11_04_STOP != THE_11_02_OPEN_STOP

    def test_the_eleven_oh_three_stop_missed_the_old_ceiling_by_three_ticks(self):
        assert PROTECTED_HIGH - self.SCANS["11:03:34"] == THE_11_03_STOP == 40.75
        assert THE_11_03_STOP - 40.0 == pytest.approx(0.75)      # three MNQ ticks

    @pytest.mark.parametrize("stop", [THE_11_04_STOP, THE_11_02_OPEN_STOP])
    def test_neither_needed_this_migration(self, stop):
        """The graded miss was not a risk-doctrine problem, under either figure."""
        assert stop <= 40.0                                       # the OLD ceiling
        assert R.size_for_risk(stop, MNQ, max_risk_usd=250.0)["contracts"] >= 1

    def test_the_eleven_oh_four_setup_sized_three_contracts_under_the_old_cap(self):
        """All-in sizing, not raw point risk: 31 pts is $65.22/contract once
        measured fixed cost and slippage reserve are billed, so $250 bought
        THREE -- not the four that 31 x $2 x 4 = $248 suggests."""
        old = R.size_for_risk(THE_11_04_STOP, MNQ, max_risk_usd=250.0)
        assert old["contracts"] == 3
        assert old["all_in_risk_per_contract"] == pytest.approx(65.22, abs=0.01)
        assert 31.00 * 2.0 == 62.00 < old["all_in_risk_per_contract"]

    def test_only_the_eleven_oh_three_setup_required_the_new_ceiling(self):
        assert THE_11_03_STOP > 40.0                              # refused before
        assert THE_11_03_STOP <= R.ABSOLUTE_MAX_STOP_POINTS        # allowed now
