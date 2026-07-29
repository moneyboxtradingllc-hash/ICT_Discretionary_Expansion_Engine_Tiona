"""The trailing drawdown, wired into the sizing path.

Percent-of-equity reads the NOTIONAL balance, and on a prop account that number
is fiction. A 50K Combine is a $2,000 risk account. Unguarded, 3% of $50,000 buys
37 contracts at a 20-point stop — $1,480, or 74% of everything that exists, on a
single trade. Three consecutive losers would not just fail the evaluation, they
would end it.

These pin the guard on, the guard off, and the failure mode in between.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def sizing(monkeypatch, tmp_path):
    """Fresh module state per test; the guard reads env at call time."""
    monkeypatch.setenv("TOPSTEP_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.delenv("TOPSTEP_ACCOUNT_SIZE", raising=False)
    from integrations.ninjatrader.deterministic import risk
    return risk


def _risk_dollars(result, stop_points):
    return result["quantity"] * stop_points * 2.0      # MNQ $2/point


class TestGuardOff:
    def test_a_self_funded_account_is_completely_unaffected(self, sizing):
        """No TOPSTEP_ACCOUNT_SIZE means no trailing floor exists to model."""
        r = sizing.size_for_stop(20.0, equity=50_000.0)
        assert r["topstep_cap"] is None
        assert r["governed_by"] in ("risk_budget", "margin")
        assert r["quantity"] == 37

    def test_the_unguarded_size_is_the_danger_being_prevented(self, sizing):
        r = sizing.size_for_stop(20.0, equity=50_000.0)
        assert _risk_dollars(r, 20.0) == pytest.approx(1_480.0)
        # 74% of a 50K Combine's entire $2,000 buffer, on one trade.
        assert _risk_dollars(r, 20.0) / 2_000.0 > 0.7


class TestGuardOn:
    def test_size_collapses_to_the_operators_actual_practice(self, sizing, monkeypatch):
        """$250 on a 50K Combine is the stated rule; the guard reproduces it."""
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        r = sizing.size_for_stop(20.0, equity=50_000.0)
        assert r["governed_by"] == "topstep_mll"
        assert _risk_dollars(r, 20.0) <= 250.0

    @pytest.mark.parametrize("stop", [10.0, 15.0, 20.0, 25.0])
    def test_risk_stays_pinned_regardless_of_stop_width(self, sizing, monkeypatch, stop):
        """Risk-based sizing: a tighter stop buys more contracts, not more risk."""
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        r = sizing.size_for_stop(stop, equity=50_000.0)
        assert _risk_dollars(r, stop) <= 250.0

    def test_it_scales_to_a_larger_account_without_re_derivation(self, sizing, monkeypatch):
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "150K")
        r = sizing.size_for_stop(20.0, equity=150_000.0)
        assert _risk_dollars(r, 20.0) <= 562.50      # 12.5% of a $4,500 buffer

    def test_the_binding_limit_is_named_not_inferred(self, sizing, monkeypatch):
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        r = sizing.size_for_stop(20.0, equity=50_000.0)
        assert r["governed_by"] == "topstep_mll"
        assert "50K trailing MLL" in r["topstep_detail"]
        assert "floor" in r["topstep_detail"] and "room" in r["topstep_detail"]


class TestGuardShrinksWithTheBuffer:
    def test_a_drawn_down_account_sizes_smaller(self, sizing, monkeypatch):
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        healthy = sizing.size_for_stop(20.0, equity=50_000.0)["quantity"]
        drawn = sizing.size_for_stop(20.0, equity=48_800.0)["quantity"]
        assert 0 < drawn < healthy

    def test_a_breached_account_refuses_to_size(self, sizing, monkeypatch):
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        r = sizing.size_for_stop(20.0, equity=47_900.0)   # below the 48,000 floor
        assert r["quantity"] == 0


class TestItFailsClosed:
    def test_a_misconfigured_account_size_refuses_rather_than_disappears(
            self, sizing, monkeypatch):
        """A guard that vanishes when misconfigured is worse than no guard:
        the operator believes they are protected."""
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "250K")   # not a real size
        r = sizing.size_for_stop(20.0, equity=50_000.0)
        assert r["quantity"] == 0
        assert "TOPSTEP GUARD FAILED" in r["topstep_detail"]

    def test_unknown_equity_defers_to_the_existing_fallback(self, sizing, monkeypatch):
        monkeypatch.setenv("TOPSTEP_ACCOUNT_SIZE", "50K")
        r = sizing.size_for_stop(20.0, equity=None)
        assert r["topstep_cap"] is None
        assert "equity unknown" in r["topstep_detail"]
