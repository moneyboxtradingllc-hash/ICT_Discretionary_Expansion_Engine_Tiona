"""The startup banner must RESOLVE its risk limits, never restate them.

PROD-20260908 DISPLAY-ONLY CORRECTION.

Four lines of `execution_path_telemetry` were string literals:

    MAXIMUM ALL-IN RISK          : $250.00
    PREFERRED STOP RANGE         : 0-35 points
    ABSOLUTE STOP CEILING        : 40 points
    MAXIMUM CONTRACTS            : 15 MNQ

Two were WRONG. Doctrine is $350.00 and a 50-point ceiling, and had been since
the constants moved. The literals enforced nothing -- sizing reads
`topstepx_combine_risk.PRODUCTION_*` through `build_production_bracket` -- which
is precisely why nothing failed when they drifted, and why an operator reading
the banner was told one thing while the runner did another.

The other two were right BY COINCIDENCE. A test that only pins the current
values would keep passing if they were re-hardcoded, so the drift guard here
MUTATES the authoritative constants and requires the banner to follow. That is
the difference between "prints 35" and "reads the number 35 comes from".

Separately, the doctrine maximum is not always the operative cap.
`daily_loss_budget.compute` sets

    allowed_planned_risk = min(max_risk_usd, remaining_daily_room)

and `topstepx_production_loop` passes that into `build_production_bracket`. When
the signed budget is smaller than doctrine, the budget is what a trade is sized
against, and printing $350.00 as the effective cap would misreport it.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


@pytest.fixture
def banner(monkeypatch):
    """Render the banner, with the environment a startup would supply."""
    def render(**env):
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from tools import topstepx_production_session as PS
        return PS.execution_path_telemetry(armed=False, mission_id="PROD-TEST",
                                           symbol="MNQ")
    return render


def _line(text: str, label: str) -> str:
    for row in text.splitlines():
        if row.strip().startswith(label):
            return row
    raise AssertionError(f"no {label!r} line in:\n{text}")


class TestOrdinaryLimits:
    """The signed budget leaves room, so doctrine is the operative cap."""

    def test_doctrine_maximum_is_the_constant_not_a_literal(self, banner):
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        out = banner()
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in _line(
            out, "ALL-IN RISK (DOCTRINE MAX)")

    def test_effective_cap_is_doctrine_when_the_budget_allows_it(self, banner):
        from broker import topstepx_session_authorization as SA
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        assert SA.DAILY_LOSS_BUDGET_USD > PRODUCTION_MAX_RISK_USD, \
            "fixture assumption: the shipped budget exceeds the per-trade cap"
        row = _line(banner(), "EFFECTIVE PER-TRADE CAP")
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in row
        assert "doctrine maximum" in row
        assert "GOVERNED BY" not in row

    def test_stop_range_ceiling_and_contracts_resolve(self, banner):
        from broker.topstepx_combine_risk import (
            ABSOLUTE_MAX_STOP_POINTS, PREFERRED_MAX_STOP_POINTS,
            PRODUCTION_MAX_CONTRACTS)
        out = banner()
        assert f"0-{PREFERRED_MAX_STOP_POINTS:g} points" in _line(
            out, "PREFERRED STOP RANGE")
        assert f"{ABSOLUTE_MAX_STOP_POINTS:g} points" in _line(
            out, "ABSOLUTE STOP CEILING")
        assert f"{PRODUCTION_MAX_CONTRACTS} MNQ" in _line(
            out, "MAXIMUM CONTRACTS")

    def test_the_stale_literals_are_gone(self, banner):
        """The exact strings the operator was shown while doctrine said otherwise."""
        out = banner()
        assert "$250.00" not in out
        assert "40 points" not in out


class TestGovernorLowerThanDoctrine:
    """A budget below the per-trade cap IS the cap, and must say so."""

    def test_effective_cap_reports_the_budget_and_names_the_governor(
            self, banner, monkeypatch):
        from broker import topstepx_session_authorization as SA
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        monkeypatch.setattr(SA, "DAILY_LOSS_BUDGET_USD", 200.00)
        row = _line(banner(), "EFFECTIVE PER-TRADE CAP")
        assert "$200.00" in row
        assert "GOVERNED BY DAILY LOSS BUDGET" in row
        # The doctrine maximum is still disclosed, as context, never as effect.
        assert f"below the ${PRODUCTION_MAX_RISK_USD:,.2f} doctrine maximum" in row

    def test_the_doctrine_line_still_shows_doctrine(self, banner, monkeypatch):
        """Lowering the governor must not rewrite what doctrine says."""
        from broker import topstepx_session_authorization as SA
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        monkeypatch.setattr(SA, "DAILY_LOSS_BUDGET_USD", 200.00)
        out = banner()
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in _line(
            out, "ALL-IN RISK (DOCTRINE MAX)")
        assert "$200.00" in _line(out, "DAILY LOSS BUDGET (SIGNED)")

    def test_an_unsigned_budget_is_unresolved_never_defaulted(
            self, banner, monkeypatch):
        """`SessionAuthorization.verify` refuses an unsigned budget. The banner
        may not quietly supply the number the authorization never signed."""
        from broker import topstepx_session_authorization as SA
        monkeypatch.setattr(SA, "DAILY_LOSS_BUDGET_USD", None)
        out = banner()
        assert "UNRESOLVED" in _line(out, "EFFECTIVE PER-TRADE CAP")
        assert "UNSIGNED" in _line(out, "DAILY LOSS BUDGET (SIGNED)")


class TestDriftGuard:
    """Pinning today's values would not catch a re-hardcoded literal."""

    def test_the_banner_follows_the_constants(self, banner, monkeypatch):
        # PATCHED ON `topstepx_production_doctrine`, NOT on
        # `topstepx_combine_risk`. The doctrine module does `from ... import
        # PRODUCTION_MAX_RISK_USD`, which binds the VALUE at import time, so
        # rebinding the source module afterwards would change nothing and the
        # guard would fail for a reason that says nothing about the banner.
        # `resolve()` is the authority the banner reads; these are its names.
        from broker import topstepx_production_doctrine as DOCTRINE
        monkeypatch.setattr(DOCTRINE, "PRODUCTION_MAX_RISK_USD", 411.00)
        monkeypatch.setattr(DOCTRINE, "PREFERRED_MAX_STOP_POINTS", 22.0)
        monkeypatch.setattr(DOCTRINE, "ABSOLUTE_MAX_STOP_POINTS", 33.0)
        monkeypatch.setattr(DOCTRINE, "PRODUCTION_MAX_CONTRACTS", 7)
        out = banner()
        assert "$411.00" in _line(out, "ALL-IN RISK (DOCTRINE MAX)")
        assert "0-22 points" in _line(out, "PREFERRED STOP RANGE")
        assert "33 points" in _line(out, "ABSOLUTE STOP CEILING")
        assert "7 MNQ" in _line(out, "MAXIMUM CONTRACTS")

    def test_a_raised_doctrine_cap_lets_the_budget_govern(
            self, banner, monkeypatch):
        """Both halves of the min() are live, not just the budget half."""
        from broker import topstepx_production_doctrine as DOCTRINE
        from broker import topstepx_session_authorization as SA
        monkeypatch.setattr(DOCTRINE, "PRODUCTION_MAX_RISK_USD", 5000.00)
        monkeypatch.setattr(SA, "DAILY_LOSS_BUDGET_USD", 725.00)
        row = _line(banner(), "EFFECTIVE PER-TRADE CAP")
        assert "$725.00" in row
        assert "GOVERNED BY DAILY LOSS BUDGET" in row
