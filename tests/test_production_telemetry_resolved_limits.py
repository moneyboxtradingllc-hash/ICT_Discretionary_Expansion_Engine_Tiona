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
    def render(authorization=None, governor=None, **env):
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from tools import topstepx_production_session as PS
        return PS.execution_path_telemetry(armed=False, mission_id="PROD-TEST",
                                           symbol="MNQ",
                                           authorization=authorization,
                                           governor=governor)
    return render


def _line(text: str, label: str) -> str:
    for row in text.splitlines():
        if row.strip().startswith(label):
            return row
    raise AssertionError(f"no {label!r} line in:\n{text}")


class TestOrdinaryLimits:
    """Doctrine values resolve from the authority, not from literals."""

    def test_doctrine_maximum_is_the_constant_not_a_literal(self, banner):
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        out = banner()
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in _line(
            out, "ALL-IN RISK (DOCTRINE MAX)")

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
        out = banner()
        assert "$250.00" not in out
        assert "40 points" not in out


class TestConfiguredIsLabelledConfiguration:
    """The module constant may be shown -- but never as a signed term."""

    def test_configured_is_named_configured_and_the_ceiling_names_itself(
            self, banner):
        from broker import topstepx_session_authorization as SA
        out = banner()
        configured = _line(out, "DAILY LOSS BUDGET (CONFIGURED)")
        assert f"${SA.DAILY_LOSS_BUDGET_USD:,.2f}" in configured
        assert "module default" in configured
        ceiling = _line(out, "CONFIGURATION-ONLY CEILING")
        assert "NOT the effective cap" in ceiling

    def test_the_module_constant_never_appears_as_signed(self, banner):
        """THE ORIGINAL DEFECT. `SA.DAILY_LOSS_BUDGET_USD` was printed under
        the label SIGNED, which is configuration wearing an authority it does
        not have."""
        assert "UNRESOLVED" in _line(banner(), "DAILY LOSS BUDGET (SIGNED)")


class TestSignedComesOnlyFromTheAuthorization:

    def test_signed_reports_the_authorization_not_the_module_default(
            self, banner):
        """A signed budget that DIFFERS from the module default."""
        from broker import topstepx_session_authorization as SA
        auth = type("A", (), {"daily_loss_budget_usd": 200.00})()
        row = _line(banner(authorization=auth), "DAILY LOSS BUDGET (SIGNED)")
        assert "$200.00" in row
        assert f"${SA.DAILY_LOSS_BUDGET_USD:,.2f}" not in row

    def test_an_authorization_missing_its_budget_is_unresolved(self, banner):
        """`verify` refuses an unsigned budget; the banner may not supply one."""
        auth = type("A", (), {"daily_loss_budget_usd": None})()
        row = _line(banner(authorization=auth), "DAILY LOSS BUDGET (SIGNED)")
        assert "UNRESOLVED" in row
        assert "signed no daily loss budget" in row

    def test_no_authorization_says_why_rather_than_defaulting(self, banner):
        row = _line(banner(), "DAILY LOSS BUDGET (SIGNED)")
        assert "UNRESOLVED" in row
        assert "scan loop" in row


class TestEffectiveComesOnlyFromTheGovernor:

    def test_without_a_governor_the_effective_cap_is_unresolved(self, banner):
        row = _line(banner(), "EFFECTIVE PER-TRADE CAP")
        assert "UNRESOLVED" in row
        assert "governor" in row

    def test_a_restart_with_prior_losses_reports_the_reduced_room(self, banner):
        """THE CASE THE FIRST CORRECTION GOT WRONG. min(doctrine, budget)
        assumed no realized loss. On a restart the room is already spent down,
        and the governor -- not arithmetic over a constant -- knows it."""
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        governor = {"state": "OK", "entry_permitted": True,
                    "allowed_planned_risk": 150.00,
                    "remaining_daily_room": 150.00}
        row = _line(banner(governor=governor), "EFFECTIVE PER-TRADE CAP")
        assert "$150.00" in row
        assert "GOVERNED BY REMAINING DAILY ROOM" in row
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in row

    def test_room_above_doctrine_reports_the_doctrine_maximum(self, banner):
        from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
        governor = {"state": "OK", "entry_permitted": True,
                    "allowed_planned_risk": PRODUCTION_MAX_RISK_USD,
                    "remaining_daily_room": 725.00}
        row = _line(banner(governor=governor), "EFFECTIVE PER-TRADE CAP")
        assert f"${PRODUCTION_MAX_RISK_USD:,.2f}" in row
        assert "doctrine maximum" in row
        assert "GOVERNED BY" not in row

    def test_a_governor_forbidding_entry_says_so(self, banner):
        """CONTAMINATED / UNKNOWN / EXHAUSTED forbid a new entry whatever the
        cap, so the state must travel with the number."""
        governor = {"state": "CONTAMINATED", "entry_permitted": False,
                    "reason": "unattributable_in_session_trade",
                    "allowed_planned_risk": 0.0,
                    "remaining_daily_room": 0.0}
        row = _line(banner(governor=governor), "EFFECTIVE PER-TRADE CAP")
        assert "CONTAMINATED" in row
        assert "NO NEW ENTRY PERMITTED" in row
        assert "unattributable_in_session_trade" in row


class TestDriftGuard:
    """Pinning today's values would not catch a re-hardcoded literal."""

    def test_the_banner_follows_the_constants(self, banner, monkeypatch):
        # PATCHED ON `topstepx_production_doctrine`, NOT on
        # `topstepx_combine_risk`: the doctrine module binds these VALUES at
        # import, so rebinding the source module would change nothing and the
        # guard would fail for a reason that says nothing about the banner.
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
