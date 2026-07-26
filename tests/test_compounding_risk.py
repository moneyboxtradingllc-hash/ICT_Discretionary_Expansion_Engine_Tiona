"""COMPOUNDING — risk scales with the account, never past the hard ceiling.

Sizing was a flat MAX_RISK_DOLLARS regardless of balance, so a growing account
kept risking the same dollars and never compounded.

Two invariants matter more than the growth itself:

  1. HARD_MAX_RISK_PCT is absolute. Whatever the config says, per-trade risk can
     never exceed that share of the balance.
  2. Unknown equity falls back to the flat budget, never to something larger. A
     bridge outage must not silently size up.

And one coherence property: the daily ceiling is checked PRE-trade against the
full proposed risk, so a ceiling below one trade's risk rejects every trade
forever. That must be reported as a configuration error, not emitted as an
endless stream of anonymous refusals.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader.deterministic import risk as R
from integrations.ninjatrader.deterministic import (
    MAX_RISK_DOLLARS, HARD_MAX_RISK_PCT, RISK_PCT_OF_EQUITY, MAX_CONTRACTS,
    POINT_VALUE,
)


class TestRiskCompounds:
    def test_budget_grows_with_equity(self):
        small, _ = R.risk_budget(25_000)
        large, _ = R.risk_budget(100_000)
        assert large > small

    def test_budget_is_the_configured_share(self):
        b, _ = R.risk_budget(50_000)
        assert b == pytest.approx(50_000 * RISK_PCT_OF_EQUITY / 100.0)

    def test_budget_shrinks_on_drawdown(self):
        """Compounding runs both ways — a smaller account risks less."""
        assert R.risk_budget(20_000)[0] < R.risk_budget(50_000)[0]

    def test_contracts_grow_with_equity(self):
        """On a wide stop the budget governs, so size tracks equity directly."""
        assert R.contracts_for_stop(25.0, 100_000) > R.contracts_for_stop(25.0, 25_000)

    def test_the_contract_ceiling_grows_too(self):
        """A fixed ceiling froze compounding at ~$75k; it must scale."""
        assert R.contract_ceiling(250_000)[0] > R.contract_ceiling(50_000)[0]

    def test_the_reason_states_the_arithmetic(self):
        _, why = R.risk_budget(50_000)
        assert "% of equity" in why and "50,000" in why


class TestTheHardCeilingIsAbsolute:
    def test_config_above_the_hard_cap_is_clamped(self, monkeypatch):
        monkeypatch.setattr(R, "RISK_PCT_OF_EQUITY", 10.0)
        b, why = R.risk_budget(100_000)
        assert b == pytest.approx(100_000 * HARD_MAX_RISK_PCT / 100.0)
        assert "capped" in why

    def test_risk_never_exceeds_the_hard_cap_at_any_equity(self, monkeypatch):
        monkeypatch.setattr(R, "RISK_PCT_OF_EQUITY", 25.0)
        for eq in (10_000, 50_000, 250_000, 1_000_000):
            assert R.risk_budget(eq)[0] <= eq * HARD_MAX_RISK_PCT / 100.0 + 1e-6

    def test_realised_risk_at_the_stop_stays_within_the_cap(self, monkeypatch):
        """The contract count must not round the account past the ceiling."""
        monkeypatch.setattr(R, "RISK_PCT_OF_EQUITY", HARD_MAX_RISK_PCT)
        for eq in (30_000, 60_000):
            for stop in (5.0, 9.0, 25.0):
                qty = R.contracts_for_stop(stop, eq)
                assert qty * stop * POINT_VALUE <= eq * HARD_MAX_RISK_PCT / 100.0 + 1e-6


class TestUnknownEquityFailsSafe:
    @pytest.mark.parametrize("bad", [None, 0, -1, "nonsense", float("nan")])
    def test_falls_back_to_the_flat_budget(self, bad):
        b, why = R.risk_budget(bad)
        assert b == MAX_RISK_DOLLARS
        assert "flat budget" in why

    def test_a_bridge_outage_never_sizes_up(self):
        """The failure mode that would matter: equity lost, size grows."""
        assert R.risk_budget(None)[0] <= R.risk_budget(50_000)[0]

    def test_contracts_fall_back_too(self):
        assert R.contracts_for_stop(9.0, None) == R.contracts_for_stop(9.0)


class TestDailyCeilingScalesWithIt:
    def test_ceiling_grows_with_equity(self):
        assert R.daily_loss_ceiling(100_000)[0] > R.daily_loss_ceiling(25_000)[0]

    def test_ceiling_exceeds_one_trade_at_default_config(self):
        """Otherwise the first trade of the day is always rejected."""
        for eq in (25_000, 50_000, 100_000):
            assert R.daily_loss_ceiling(eq)[0] > R.risk_budget(eq)[0]

    def test_a_trade_is_authorized_at_the_live_balance(self):
        d = R.assess_trade("short", 28540.0, 28552.25, 0.0, equity=50_369.60)
        assert d.approved is True
        assert d.quantity > 0


class TestIncoherentConfigIsReportedNotSilent:
    def test_budget_above_the_daily_ceiling_is_warned_not_auto_rejected(self, monkeypatch):
        """The setting is incoherent, but not necessarily untradeable: the
        contract ceiling often truncates actual risk far below the budget, and
        the real test is actual risk. Warn; let the arithmetic decide."""
        monkeypatch.setattr(R, "DAILY_LOSS_PCT_OF_EQUITY", 0.5)
        monkeypatch.setattr(R, "RISK_PCT_OF_EQUITY", 3.0)
        d = R.assess_trade("short", 28540.0, 28552.25, 0.0, equity=50_000)
        assert any("CONFIG:" in w and "DAILY_LOSS_PCT_OF_EQUITY" in w
                   for w in d.warnings)

    def test_actual_risk_over_the_ceiling_still_rejects(self, monkeypatch):
        """A wide stop that the ceiling does NOT truncate must be refused."""
        monkeypatch.setattr(R, "DAILY_LOSS_PCT_OF_EQUITY", 0.5)
        d = R.assess_trade("short", 28540.0, 28565.0, 0.0, equity=50_000)
        assert d.approved is False
        assert "daily-loss ceiling" in d.reason

    def test_the_budget_used_is_always_reported(self):
        d = R.assess_trade("short", 28540.0, 28552.25, 0.0, equity=50_000)
        assert any("risk budget" in w for w in d.warnings)


class TestCompoundingCanBeDisabled:
    def test_disabled_restores_the_flat_budget(self, monkeypatch):
        monkeypatch.setattr(R, "COMPOUNDING_ENABLED", False)
        b, why = R.risk_budget(500_000)
        assert b == MAX_RISK_DOLLARS
        assert "compounding off" in why


class TestExistingCallersAreUnchanged:
    def test_omitting_equity_preserves_legacy_sizing(self):
        assert R.contracts_for_stop(12.0) == int(MAX_RISK_DOLLARS // (12.0 * POINT_VALUE))

    def test_an_absolute_backstop_still_binds(self):
        from integrations.ninjatrader.deterministic import MAX_CONTRACTS_HARD
        assert R.contracts_for_stop(0.25, 10_000_000) == MAX_CONTRACTS_HARD

    def test_the_ceiling_never_drops_below_the_legacy_floor(self):
        from integrations.ninjatrader.deterministic import MAX_CONTRACTS_FLOOR
        for eq in (1_000, 10_000, 25_000, 50_000):
            assert R.contract_ceiling(eq)[0] >= MAX_CONTRACTS_FLOOR


class TestWhichLimitGovernedIsReported:
    """On tight stops the CEILING governs, not the risk percentage. Knowing which
    is the difference between risking 3% and believing you are."""

    def test_a_tight_stop_is_governed_by_the_contract_ceiling(self):
        s = R.size_for_stop(5.0, 50_000)
        assert s["governed_by"] == "contract_ceiling"
        assert s["wanted"] > s["quantity"]

    def test_a_wide_stop_is_governed_by_the_risk_budget(self):
        s = R.size_for_stop(25.0, 50_000)
        assert s["governed_by"] == "risk_budget"

    def test_actual_risk_is_reported_not_assumed(self):
        s = R.size_for_stop(9.0, 50_000)
        assert s["risk_at_stop"] == pytest.approx(s["quantity"] * 9.0 * POINT_VALUE)

    def test_the_ceiling_makes_tight_stops_risk_less_not_more(self):
        """A real consequence of capping: in the capped region, actual risk falls
        as the stop tightens, inverting risk-based sizing."""
        tight = R.size_for_stop(5.0, 50_000)["risk_at_stop"]
        wide = R.size_for_stop(25.0, 50_000)["risk_at_stop"]
        assert tight < wide

    def test_sizing_detail_names_both_constraints(self):
        d = R.size_for_stop(9.0, 50_000)["detail"]
        assert "budget" in d and "ceiling" in d
