"""Topstep's trailing drawdown, pinned against the way it actually behaves.

Every case here is a way an account gets closed while the bot believes it is
comfortably inside its limits. The two halves of the Maximum Loss Limit move on
different clocks, and modelling them as one number is the mistake:

  it RISES only on end-of-day balance
  it BREACHES in real time on net P&L, unrealized included

Figures: Topstep published Trading Combine limits (help.topstep.com, 2026-07-28).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from risk.topstep_limits import (
    ACCOUNT_SPECS, TopstepState, evaluate, load_state, max_contracts_within_mll,
    mll_threshold, save_state, spec_for,
)

MNQ_POINT = 2.0


@pytest.fixture
def spec():
    return spec_for("150K")


@pytest.fixture
def fresh(spec):
    return TopstepState(spec.label, spec.starting_balance, spec.starting_balance)


class TestTheThresholdMoves:
    def test_day_one_floor_is_starting_balance_minus_the_limit(self, spec, fresh):
        assert mll_threshold(spec, fresh.highest_eod_balance) == 145_500.0

    def test_it_rises_with_end_of_day_profit(self, spec, fresh):
        after = fresh.roll_day(152_000.0, "2026-07-28")
        assert mll_threshold(spec, after.highest_eod_balance) == 147_500.0

    def test_it_never_falls_back(self, spec, fresh):
        up = fresh.roll_day(152_000.0, "2026-07-28")
        down = up.roll_day(150_000.0, "2026-07-29")
        assert mll_threshold(spec, down.highest_eod_balance) == 147_500.0

    def test_it_locks_permanently_at_the_starting_balance(self, spec, fresh):
        rich = fresh.roll_day(200_000.0, "2026-07-28")
        assert mll_threshold(spec, rich.highest_eod_balance) == spec.starting_balance
        assert evaluate(spec, rich, balance=200_000.0).mll_locked is True

    def test_unrealized_profit_does_not_raise_it(self, spec, fresh):
        """The asymmetry that catches people: +$3,000 open buys no headroom."""
        v = evaluate(spec, fresh, balance=150_000.0, unrealized=3_000.0)
        assert v.mll_threshold == 145_500.0


class TestTheThresholdEnforces:
    def test_an_open_loser_can_breach_it_intraday(self, spec, fresh):
        """Realized P&L is flat; the position alone closes the account."""
        v = evaluate(spec, fresh, balance=150_000.0, unrealized=-4_600.0)
        assert v.mll_breached is True
        assert "MLL BREACHED" in v.reasons[0]

    def test_room_is_measured_on_net_equity(self, spec, fresh):
        v = evaluate(spec, fresh, balance=149_000.0, unrealized=-500.0)
        assert v.mll_room == pytest.approx(3_000.0)     # 148,500 - 145,500
        assert v.ok is True

    def test_giving_back_a_won_day_can_still_bust(self, spec, fresh):
        """Net profitable overall, account closed anyway — the real failure mode."""
        up = fresh.roll_day(154_000.0, "2026-07-28")    # threshold -> 149,500
        v = evaluate(spec, up, balance=149_400.0)
        assert v.mll_breached is True
        assert v.mll_room < 0
        assert 149_400.0 > spec.starting_balance - spec.max_loss_limit  # still 'up'


class TestTheDailyLimit:
    def test_room_is_measured_from_the_prior_close(self, spec):
        state = TopstepState(spec.label, 150_000.0, 150_000.0)
        assert evaluate(spec, state, balance=148_000.0).daily_room == pytest.approx(1_000.0)

    def test_it_trips_at_the_published_limit(self, spec):
        state = TopstepState(spec.label, 150_000.0, 150_000.0)
        v = evaluate(spec, state, balance=147_000.0)
        assert v.daily_breached is True
        assert v.ok is False

    def test_a_profitable_day_widens_the_daily_room(self, spec):
        state = TopstepState(spec.label, 150_000.0, 150_000.0)
        assert evaluate(spec, state, balance=151_000.0).daily_room == pytest.approx(4_000.0)


class TestPreTradeSizing:
    def test_size_is_capped_so_a_full_stop_cannot_bust(self, spec, fresh):
        """The question the bot never asked before placing an order."""
        n = max_contracts_within_mll(spec, fresh, balance=150_000.0,
                                     stop_points=20.0, point_value=MNQ_POINT)
        worst_case = n * 20.0 * MNQ_POINT
        room = evaluate(spec, fresh, balance=150_000.0).mll_room
        assert worst_case <= room * 0.25 + 1e-9

    def test_it_shrinks_as_the_buffer_shrinks(self, spec, fresh):
        wide = max_contracts_within_mll(spec, fresh, balance=150_000.0,
                                        stop_points=20.0, point_value=MNQ_POINT)
        thin = max_contracts_within_mll(spec, fresh, balance=146_000.0,
                                        stop_points=20.0, point_value=MNQ_POINT)
        assert thin < wide

    def test_it_refuses_rather_than_returning_one(self, spec, fresh):
        n = max_contracts_within_mll(spec, fresh, balance=145_600.0,
                                     stop_points=20.0, point_value=MNQ_POINT)
        assert n == 0

    def test_a_breached_account_sizes_to_zero(self, spec, fresh):
        assert max_contracts_within_mll(spec, fresh, balance=140_000.0,
                                        stop_points=20.0, point_value=MNQ_POINT) == 0

    def test_the_two_caps_bind_at_different_times(self, spec, fresh):
        """Percent-of-equity binds early; the MLL cap binds late. Use both.

        On a full buffer the MLL cap is the looser of the two — 0.35% of 150K is
        $525 (13 contracts at a 20pt stop) against an MLL allowance of $1,125 (28).
        That is not the MLL cap being useless: it is silent precisely while the
        account is healthy, and takes over once the buffer is spent. Sizing must
        be min(both), because each is blind where the other sees.
        """
        def pct_contracts(balance):
            return int((balance * 0.0035) // (20.0 * MNQ_POINT))

        # healthy account: percent-of-equity is the binding constraint
        healthy = max_contracts_within_mll(spec, fresh, balance=150_000.0,
                                           stop_points=20.0, point_value=MNQ_POINT)
        assert healthy > pct_contracts(150_000.0)

        # buffer nearly spent: the MLL cap takes over and is far stricter
        drawn = max_contracts_within_mll(spec, fresh, balance=146_200.0,
                                         stop_points=20.0, point_value=MNQ_POINT)
        assert drawn < pct_contracts(146_200.0)
        assert drawn > 0        # still tradeable, just small


class TestDurableState:
    def test_a_missing_file_starts_at_the_strictest_threshold(self, spec, tmp_path):
        state = load_state(spec, tmp_path / "none.json")
        assert state.highest_eod_balance == spec.starting_balance
        assert mll_threshold(spec, state.highest_eod_balance) == spec.mll_floor()

    def test_the_high_water_mark_survives_a_restart(self, spec, tmp_path):
        """If it resets, the threshold falls and the bot invents headroom."""
        p = tmp_path / "state.json"
        save_state(TopstepState(spec.label, 154_000.0, 152_000.0, "2026-07-28"), p)
        reloaded = load_state(spec, p)
        assert reloaded.highest_eod_balance == 154_000.0
        assert mll_threshold(spec, reloaded.highest_eod_balance) == 149_500.0

    def test_another_accounts_history_is_refused(self, spec, tmp_path):
        p = tmp_path / "state.json"
        save_state(TopstepState("50K", 52_000.0, 52_000.0), p)
        with pytest.raises(ValueError) as exc:
            load_state(spec, p)
        assert "Refusing to carry" in str(exc.value)


class TestSpecLookup:
    @pytest.mark.parametrize("given,expect", [
        ("150K", 150_000.0), ("150k", 150_000.0), ("$150,000", 150_000.0),
        ("150000", 150_000.0),
    ])
    def test_account_size_is_read_forgivingly(self, given, expect):
        assert spec_for(given).starting_balance == expect

    def test_an_unknown_size_is_refused_not_defaulted(self):
        with pytest.raises(KeyError):
            spec_for("250K")

    def test_published_limits_match_topstep(self):
        assert ACCOUNT_SPECS["150K"].max_loss_limit == 4_500.0
        assert ACCOUNT_SPECS["150K"].daily_loss_limit == 3_000.0
        assert ACCOUNT_SPECS["50K"].max_loss_limit == 2_000.0
        assert ACCOUNT_SPECS["100K"].max_loss_limit == 3_000.0
