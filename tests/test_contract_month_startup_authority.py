"""CONTRACT-MONTH-AUTHORITY-1 — the LIVE LAUNCHER must accept the venue's month.

The PRAC preflight went 24/24 while `tools/topstepx_production_session.py` still
compared the venue-resolved contract against one pinned expiry:

    if contract and contract != II.PRODUCTION_CONTRACT:   # U26

After the September expiry TopstepX resolves Z26, so the real production
entrypoint refused to start on the contract it had just correctly resolved --
and the banner printed U26 as ACTIVE CONTRACT while it did so. The preflight
never exercised either path, which is precisely why a green preflight was not
evidence that the launcher could start.

These tests exercise the launcher directly. The safety property is unchanged and
is asserted here as such: foreign families and malformed ids are still refused
at startup. What moved is WHO owns the month -- TopstepX resolves it, the
session authorization signs that exact id, and `verify` refuses any mismatch.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

VENUE_RESOLVED = "CON.F.US.MNQ.Z26"       # what TopstepX resolves today
RETIRED_MONTH = "CON.F.US.MNQ.U26"        # what the constant used to pin


def _session(contract_id):
    """The startup surface `check_startup` actually reads."""
    return type("S", (), {
        "account": type("A", (), {"id": 1})(),
        "contract": type("C", (), {"id": contract_id})(),
        "market_hub": object()})()


def _foreign_contract_refusals(contract_id, monkeypatch):
    from tools import topstepx_production_session as PS
    monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
    out = PS.check_startup(_session(contract_id), armed=False, mission_id="",
                           provider="topstepx")
    return [r for r in out if r.startswith("FOREIGN_CONTRACT")]


class TestTheLauncherAcceptsTheVenueResolvedMonth:

    def test_the_active_venue_month_does_not_refuse_startup(self, monkeypatch):
        """THE DEFECT. Z26 is what TopstepX resolves; it must start."""
        assert _foreign_contract_refusals(VENUE_RESOLVED, monkeypatch) == []

    def test_the_previously_pinned_month_also_does_not_refuse(self, monkeypatch):
        """A retired month is well-formed. It is refused by the authorization's
        exact-contract binding, never by the startup family guard."""
        assert _foreign_contract_refusals(RETIRED_MONTH, monkeypatch) == []

    @pytest.mark.parametrize("month", ["H27", "M27", "U27", "Z27"])
    def test_future_quarterlies_will_not_need_another_repair(self, month,
                                                             monkeypatch):
        """The point of the change: December's roll must not be an outage."""
        assert _foreign_contract_refusals(f"CON.F.US.MNQ.{month}",
                                          monkeypatch) == []


class TestTheSafetyPropertyIsUnchanged:
    """This guard exists to keep foreign instruments out of a live session.
    Widening the MONTH must not widen the FAMILY."""

    @pytest.mark.parametrize("foreign", [
        "CON.F.US.ES.Z26",      # a different future entirely
        "CON.F.US.MES.Z26",     # the micro S&P, one letter from ours
        "CON.F.US.NQ.Z26",      # the full-size NQ, not the micro
        "CON.F.US.ENQ.Z26",     # a near-miss root
        "QQQ",                  # the retired equity path
        "CON.F.US.MNQX.Z26",    # family prefix extended
    ])
    def test_a_foreign_family_still_refuses_startup(self, foreign, monkeypatch):
        assert _foreign_contract_refusals(foreign, monkeypatch), (
            f"{foreign} started a production session")

    @pytest.mark.parametrize("malformed", [
        "CON.F.US.MNQ.",        # no month at all
        "CON.F.US.MNQ.Z",       # no year
        "CON.F.US.MNQ.Z2",      # one-digit year
        "CON.F.US.MNQ.A26",     # not a CME month code
        "CON.F.US.MNQ.Z26.X",   # trailing segment
        "con.f.us.mnq.z26",     # lower case is a different id
    ])
    def test_a_malformed_id_still_refuses_startup(self, malformed, monkeypatch):
        assert _foreign_contract_refusals(malformed, monkeypatch), (
            f"{malformed} started a production session")

    def test_the_refusal_still_names_what_it_refused(self, monkeypatch):
        refusals = _foreign_contract_refusals("CON.F.US.ES.Z26", monkeypatch)
        assert "CON.F.US.ES.Z26" in refusals[0]


class TestStartupTelemetryReportsTheResolvedContract:

    def test_it_reports_the_venue_resolved_id(self):
        from tools import topstepx_production_session as PS
        out = PS.execution_path_telemetry(armed=False, mission_id="M",
                                          symbol="MNQ",
                                          contract_id=VENUE_RESOLVED)
        line = [l for l in out.splitlines() if "ACTIVE CONTRACT" in l][0]
        assert VENUE_RESOLVED in line
        assert RETIRED_MONTH not in line, "the banner still names the constant"

    def test_absent_a_resolved_contract_it_says_so_rather_than_guessing(self):
        """The codebase's own rule: report UNRESOLVED, never substitute a
        configured default. A banner that names a month it cannot observe is
        how a session gets assumed to be on an instrument it is not."""
        from tools import topstepx_production_session as PS
        out = PS.execution_path_telemetry(armed=False, mission_id="M",
                                          symbol="MNQ")
        line = [l for l in out.splitlines() if "ACTIVE CONTRACT" in l][0]
        assert "UNRESOLVED" in line
        assert RETIRED_MONTH not in line


class TestTheExactMonthIsStillBoundDownstream:
    """Startup validity is permission to ASK. The authorization is what pins
    one exact contract for one session date."""

    def _auth(self, contract_id):
        from datetime import datetime, timezone

        from ai_retrieval.retrieval import retrieval_enabled
        from broker import topstepx_session_authorization as SA
        auth = SA.SessionAuthorization(
            session_id="PROD-20260921", account_fingerprint="acct:fc84f7a928d9",
            contract_id=contract_id, session_date="20260921",
            decision_window="09:00-14:00 America/New_York",
            daily_loss_budget_usd=725.0,
            retrieval_enabled=retrieval_enabled(),
            issued_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc).isoformat())
        auth.authorization_fingerprint = auth.fingerprint()
        return auth

    def test_an_authorization_signed_for_the_resolved_month_verifies(self):
        self._auth(VENUE_RESOLVED).verify(
            account_fingerprint="acct:fc84f7a928d9",
            contract_id=VENUE_RESOLVED, session_date="20260921")

    def test_it_refuses_a_different_month_in_the_same_family(self):
        """Startup would now admit H27. The authorization still will not."""
        from broker import topstepx_session_authorization as SA
        with pytest.raises(SA.AuthorizationRefused, match="CONTRACT_MISMATCH"):
            self._auth(VENUE_RESOLVED).verify(
                account_fingerprint="acct:fc84f7a928d9",
                contract_id="CON.F.US.MNQ.H27", session_date="20260921")

    def test_it_refuses_the_retired_month(self):
        from broker import topstepx_session_authorization as SA
        with pytest.raises(SA.AuthorizationRefused, match="CONTRACT_MISMATCH"):
            self._auth(VENUE_RESOLVED).verify(
                account_fingerprint="acct:fc84f7a928d9",
                contract_id=RETIRED_MONTH, session_date="20260921")
