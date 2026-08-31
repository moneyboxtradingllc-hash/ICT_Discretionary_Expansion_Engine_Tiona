"""PRODUCTION-AUTHORIZATION-CLI — the durable record `--arm` requires.

The issuer writes a file and nothing else. These tests lock that it delegates to
the authoritative authorization module, refuses every out-of-doctrine term, and
never reaches an order endpoint.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker import topstepx_mission_state as MS                      # noqa: E402
from broker import topstepx_session_authorization as SA              # noqa: E402
from doctrine import instrument_identity as II                       # noqa: E402
from tools import topstepx_issue_session_authorization as ISS        # noqa: E402

CID = II.PRODUCTION_CONTRACT
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 20, 0, tzinfo=timezone.utc)
TOMORROW = "2026-08-06"


def issue(tmp_path, *, session_id="PROD-20260806", date_text=TOMORROW,
          fingerprint=FP, contract_id=CID, now=NOW):
    return ISS.issue_authorization(
        session_id=session_id, date_text=date_text, store_dir=str(tmp_path),
        account_fingerprint=fingerprint, contract_id=contract_id, now=now)


# ══════════════════════════════════════════════════════════════════════════════
class TestDelegatesToTheAuthority:

    def test_it_calls_the_authoritative_issuer(self):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(ISS.issue_authorization)))
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert "SA.issue" in calls

    def test_it_duplicates_no_fingerprint_logic(self):
        import inspect
        src = inspect.getsource(ISS)
        assert "hashlib" not in src and "sha256" not in src

    def test_it_cannot_place_an_order(self):
        import ast
        src = open(os.path.join("tools", "topstepx_issue_session_authorization.py"),
                   encoding="utf-8").read()
        calls = [getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)]
        for banned in ("place_order", "submit", "gated_submit", "cancel_order",
                       "close_position", "consume_attempt"):
            assert banned not in calls

    def test_it_uses_a_read_only_session(self):
        src = open(os.path.join("tools", "topstepx_issue_session_authorization.py"),
                   encoding="utf-8").read()
        assert "TopstepXReadOnlySession" in src
        assert "TopstepXLiveSession" not in src


class TestIssuedTerms:

    def test_a_valid_future_date_issues(self, tmp_path):
        r = issue(tmp_path)
        assert r["state"] == "ISSUED"
        assert os.path.exists(r["path"])

    def test_every_doctrine_term_is_bound(self, tmp_path):
        a = issue(tmp_path)["authorization"]
        assert a.maximum_trades == 2
        assert a.maximum_attempts_per_trade == 1
        assert a.maximum_risk_per_trade == 350.0
        assert a.maximum_contracts == 15
        assert a.preferred_stop_ceiling == 35.0
        assert a.absolute_stop_ceiling == 50.0
        assert a.compounding is False
        # PRE-NY-EXECUTION-WINDOW-1: canonical start 09:30 -> 09:00. The subject
        # of this test is unchanged -- every doctrine term must be BOUND into
        # the issued record -- only the bound value moved with the doctrine.
        assert a.decision_window == "09:00-14:00 America/New_York"
        assert a.contract_id == CID
        assert a.issued_at and a.authorization_fingerprint

    def test_the_written_record_verifies_under_the_launchers_law(self, tmp_path):
        a = issue(tmp_path)["authorization"]
        a.verify(account_fingerprint=FP, contract_id=CID, session_date="20260806")

    def test_altering_a_saved_term_invalidates_the_fingerprint(self, tmp_path):
        path = issue(tmp_path)["path"]
        d = json.load(open(path, encoding="utf-8"))
        d["maximum_risk_per_trade"] = 5000.0          # hand-widened on disk
        json.dump(d, open(path, "w", encoding="utf-8"))
        reloaded = SA.SessionAuthorization.load(path)
        with pytest.raises(SA.AuthorizationRefused, match="CORRUPT"):
            reloaded.verify(account_fingerprint=FP, contract_id=CID,
                            session_date="20260806")


class TestRefusals:

    def test_a_past_date_is_refused(self, tmp_path):
        with pytest.raises(ISS.IssuanceRefused, match="PAST_DATE"):
            issue(tmp_path, date_text="2026-08-04")

    def test_a_malformed_date_is_refused(self, tmp_path):
        for bad in ("20260806", "6/8/2026", "tomorrow", ""):
            with pytest.raises(ISS.IssuanceRefused, match="MALFORMED_DATE"):
                issue(tmp_path, date_text=bad)

    def test_a_missing_fingerprint_is_refused(self, tmp_path):
        with pytest.raises(ISS.IssuanceRefused, match="NO_FINGERPRINT"):
            issue(tmp_path, fingerprint="")

    def test_a_foreign_contract_is_refused(self, tmp_path):
        with pytest.raises(II.InstrumentIdentityError):
            issue(tmp_path, contract_id="CON.F.US.ES.U26")

    def test_a_stale_mnq_contract_is_refused(self, tmp_path):
        with pytest.raises(II.InstrumentIdentityError):
            issue(tmp_path, contract_id="CON.F.US.MNQ.Z26")

    @pytest.mark.parametrize("sym", ["QQQ", "SPY", "NQ", "ES", ""])
    def test_a_non_mnq_instrument_is_refused(self, sym):
        with pytest.raises(II.InstrumentIdentityError):
            II.assert_production_instrument(sym, where="authorization")

    def test_a_conflicting_authorization_cannot_overwrite(self, tmp_path):
        issue(tmp_path)
        with pytest.raises(ISS.IssuanceRefused, match="CONFLICTING_AUTHORIZATION"):
            issue(tmp_path, date_text="2026-08-07")     # same id, different date

    def test_an_authorization_with_consumed_attempts_cannot_be_replaced(self, tmp_path):
        r = issue(tmp_path)
        sid = "PROD-20260806"
        mission = MS.open_mission(
            path=os.path.join(str(tmp_path), f"trade_mission_{sid}_1.json"),
            mission_id=f"{sid}-T1", account_fingerprint=FP, contract_id=CID,
            authorization_fingerprint=r["authorization"].authorization_fingerprint,
            max_attempts=1)
        mission.consume_attempt(candidate_fingerprint="cand:x", token_id="tok-1")
        with pytest.raises(ISS.IssuanceRefused, match="ATTEMPTS_ALREADY_CONSUMED"):
            issue(tmp_path)


class TestDoctrineCeilings:
    """Terms above doctrine are refused at verification, however they got there."""

    def make(self, **over):
        kw = dict(session_id="S", account_fingerprint=FP, contract_id=CID,
                  session_date="20260806",
                  decision_window="09:30-14:00 America/New_York",
                  issued_at=NOW.isoformat())
        kw.update(over)
        a = SA.SessionAuthorization(**kw)
        a.authorization_fingerprint = a.fingerprint()
        return a

    def check(self, **over):
        with pytest.raises(SA.AuthorizationRefused):
            self.make(**over).verify(account_fingerprint=FP, contract_id=CID,
                                     session_date="20260806")

    def test_more_than_two_trades(self):
        self.check(maximum_trades=3)

    def test_more_than_one_attempt_per_trade(self):
        self.check(maximum_attempts_per_trade=2)

    def test_risk_above_250(self):
        self.check(maximum_risk_per_trade=500.0)

    def test_size_above_15(self):
        self.check(maximum_contracts=30)

    def test_preferred_stop_above_35(self):
        self.check(preferred_stop_ceiling=40.0)

    def test_absolute_stop_above_40(self):
        self.check(absolute_stop_ceiling=60.0)

    def test_compounding_enabled(self):
        self.check(compounding=True)

    def test_a_wider_window(self):
        self.check(decision_window="08:30-15:00 America/New_York")


class TestIdempotency:

    def test_reissuing_identical_unspent_is_idempotent(self, tmp_path):
        first = issue(tmp_path)
        again = issue(tmp_path, now=NOW + timedelta(minutes=30))
        assert again["state"] == "ALREADY_ISSUED_UNCHANGED"
        assert (again["authorization"].authorization_fingerprint
                == first["authorization"].authorization_fingerprint)

    def test_idempotent_reissue_does_not_drift_the_issued_at(self, tmp_path):
        first = issue(tmp_path)["authorization"].issued_at
        again = issue(tmp_path, now=NOW + timedelta(hours=2))["authorization"].issued_at
        assert first == again


class TestRedaction:

    def test_output_carries_no_secret_or_full_hash(self, tmp_path):
        r = issue(tmp_path)
        out = ISS.render(r, session_id="PROD-20260806", date_text=TOMORROW)
        full = r["authorization"].authorization_fingerprint
        assert full not in out                       # only a short suffix
        assert FP not in out                         # no raw fingerprint
        for var in ("TOPSTEPX_API_KEY", "TOPSTEPX_USERNAME", "TOPSTEPX_ACCOUNT_ID"):
            value = os.getenv(var)
            if value:
                assert value not in out
        assert "fingerprint verified" in out
        assert "ORDER PLACED                 : NO" in out

    def test_the_report_is_console_safe(self, tmp_path):
        out = ISS.render(issue(tmp_path), session_id="S", date_text=TOMORROW)
        out.encode("cp1252")


class TestLauncherAcceptance:

    def test_the_launcher_accepts_a_valid_fixture_authorization(self, tmp_path,
                                                                monkeypatch):
        from tools import topstepx_production_session as PS
        issue(tmp_path)
        monkeypatch.setattr(PS, "STORE_DIR", str(tmp_path))
        auth = PS.load_or_refuse_authorization(
            armed=True, session_id="PROD-20260806", fingerprint=FP,
            contract_id=CID, now=datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc))
        assert auth.session_id == "PROD-20260806"

    def test_the_launcher_refuses_a_missing_authorization(self, tmp_path, monkeypatch):
        from tools import topstepx_production_session as PS
        monkeypatch.setattr(PS, "STORE_DIR", str(tmp_path))
        with pytest.raises(SA.AuthorizationRefused, match="NO_SESSION_AUTHORIZATION"):
            PS.load_or_refuse_authorization(
                armed=True, session_id="ABSENT", fingerprint=FP, contract_id=CID,
                now=NOW)

    def test_the_launcher_refuses_an_expired_authorization(self, tmp_path, monkeypatch):
        from tools import topstepx_production_session as PS
        issue(tmp_path)
        monkeypatch.setattr(PS, "STORE_DIR", str(tmp_path))
        with pytest.raises(SA.AuthorizationRefused, match="EXPIRED"):
            PS.load_or_refuse_authorization(
                armed=True, session_id="PROD-20260806", fingerprint=FP,
                contract_id=CID,
                now=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc))


class TestTruthfulTelemetry:

    def test_it_does_not_claim_alpaca_runtime_is_removed(self):
        from tools import topstepx_production_session as PS
        out = PS.execution_path_telemetry(armed=False, mission_id="X", symbol="MNQ")
        assert "ALPACA RUNTIME               : REMOVED" not in out
        assert "ALPACA PRODUCTION PATH       : BLOCKED" in out
        assert "ALPACA DATA PROVIDER         : ARCHIVED" in out
        assert "QQQ PRODUCTION PATH          : BLOCKED" in out

    def test_the_legacy_subsystem_is_reported_as_it_actually_is(self):
        from tools import topstepx_production_session as PS
        state = PS.legacy_paper_subsystem_state()
        present = os.path.isdir(os.path.join("src", "paper_execution"))
        assert state == ("PRESENT - NOT PRODUCTION-REACHABLE" if present else "REMOVED")

    def test_a_reachable_retired_path_is_detectable(self):
        from tools import topstepx_production_session as PS
        import paper_execution.paper_broker  # noqa: F401  — deliberate probe
        assert any("paper_execution" in m for m in PS.retired_paths_reachable())

    def test_a_reachable_retired_path_REFUSES_the_production_lane(self):
        """DETECTION IS NOT REFUSAL.

        STEP 4B.12 §6 UNIT 6 relies on this to keep PAPER-FVG-1 non-blocking:
        `paper_execution.build_order` derives its stop from the family
        compatibility zone rather than the resolved FVG occurrence, and that is
        acceptable debt ONLY because the practice configuration cannot reach it.
        The sibling test above proves the launcher can SEE a loaded paper
        module; this one proves it actually declines to open the lane.
        """
        from tools import topstepx_production_session as PS
        import paper_execution.paper_broker  # noqa: F401  — deliberate probe
        session = type("S", (), {"account": None, "contract": None,
                                 "market_hub": None})()
        refusals = PS.check_startup(session, armed=False, mission_id="",
                                    provider="topstepx")
        assert any(r.startswith("RETIRED_PATH_REACHABLE") for r in refusals), \
            refusals


class TestAccountRole:
    """The venue environment is checked; the pin law does not check it."""

    def account(self, can_trade=True, simulated=True):
        return type("A", (), {"can_trade": can_trade, "simulated": simulated})()

    def test_a_tradeable_simulated_combine_passes(self):
        r = ISS.assert_account_role(self.account())
        assert r["can_trade"] is True and r["simulated"] is True

    def test_a_non_tradeable_account_is_refused(self):
        with pytest.raises(ISS.IssuanceRefused, match="ACCOUNT_CANNOT_TRADE"):
            ISS.assert_account_role(self.account(can_trade=False))

    def test_a_non_simulated_account_is_refused(self):
        with pytest.raises(ISS.IssuanceRefused, match="NON_SIMULATED_VENUE"):
            ISS.assert_account_role(self.account(simulated=False))
