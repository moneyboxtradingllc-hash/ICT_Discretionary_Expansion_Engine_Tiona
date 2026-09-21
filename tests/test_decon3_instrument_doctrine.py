"""DECON-3 — TopstepX/MNQ only; Alpaca and QQQ permanently retired.

The evidence stores are partitioned by symbol, so partitioning is what keeps
equity statistics out of a futures decision. These tests lock the two things
that defeat it: a default that resolves to QQQ, and a record that never says
which instrument it came from.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from data_feed import DataFeedError, get_provider                    # noqa: E402
from doctrine.instrument_identity import (                           # noqa: E402
    PRODUCTION_CONTRACT, PRODUCTION_INSTRUMENT, InstrumentIdentityError,
    assert_production_contract, assert_production_instrument, filter_records,
    record_instrument, retrieval_eligible,
)

MNQ_REC = {"market_context": {"symbol": "MNQ"}}
QQQ_REC = {"market_context": {"symbol": "QQQ"}}
BARE_REC = {"market_context": {"regime": "range"}}


class TestProviderLaw:

    def test_alpaca_cannot_be_selected(self):
        with pytest.raises(DataFeedError, match="RETIRED"):
            get_provider("alpaca")

    def test_an_unknown_provider_refuses(self):
        with pytest.raises(DataFeedError):
            get_provider("mystery")

    def test_a_missing_provider_refuses(self, monkeypatch):
        monkeypatch.delenv("DATA_PROVIDER", raising=False)
        with pytest.raises(DataFeedError):
            get_provider()

    def test_topstepx_is_the_only_supported_provider(self):
        import inspect

        import data_feed
        src = inspect.getsource(data_feed.get_provider)
        assert "topstepx" in src
        assert "AlpacaProvider" not in src


class TestInstrumentLaw:

    def test_mnq_is_the_production_instrument(self):
        assert assert_production_instrument("MNQ") == PRODUCTION_INSTRUMENT
        assert assert_production_instrument(" mnq ") == "MNQ"

    def test_qqq_is_refused_and_never_converted(self):
        with pytest.raises(InstrumentIdentityError, match="RETIRED"):
            assert_production_instrument("QQQ")

    @pytest.mark.parametrize("sym", ["SPY", "IWM", "AAPL", "NQ", "ES"])
    def test_other_symbols_are_refused(self, sym):
        with pytest.raises(InstrumentIdentityError):
            assert_production_instrument(sym)

    def test_a_missing_symbol_refuses_rather_than_defaulting(self):
        for empty in (None, "", "   "):
            with pytest.raises(InstrumentIdentityError):
                assert_production_instrument(empty)

    def test_the_active_contract_must_match(self):
        assert assert_production_contract(PRODUCTION_CONTRACT) == PRODUCTION_CONTRACT
        for wrong in ("CON.F.US.ENQ.U26", "", None):
            with pytest.raises(InstrumentIdentityError):
                assert_production_contract(wrong)


class TestContractMonthAuthority:
    """CONTRACT-MONTH-AUTHORITY-1. TopstepX owns the month; we own the family.

    The September-to-December roll proved the two were conflated: the venue
    resolved the live contract and the repository refused to sign it because a
    constant still named the retired expiry.
    """

    def test_the_venue_resolved_active_month_is_accepted(self):
        """1. Whatever TopstepX resolves today is a legal identity to ask about."""
        assert (assert_production_contract("CON.F.US.MNQ.Z26")
                == "CON.F.US.MNQ.Z26")

    def test_a_prior_month_is_still_structurally_valid(self):
        """2. A retired month is well-formed. It is refused by the
        authorization's exact-contract binding, not by spelling."""
        assert (assert_production_contract("CON.F.US.MNQ.U26")
                == "CON.F.US.MNQ.U26")

    @pytest.mark.parametrize("foreign", [
        "CON.F.US.ES.Z26",      # a different future entirely
        "CON.F.US.MES.Z26",     # the micro S&P, one letter from ours
        "CON.F.US.ENQ.Z26",     # a near-miss root
        "CON.F.US.NQ.Z26",      # the full-size NQ, not the micro
        "QQQ",                  # the retired equity path
        "CON.F.US.MNQX.Z26",    # family prefix extended
    ])
    def test_foreign_families_are_refused(self, foreign):
        """3. The safety property this module exists for is unchanged."""
        with pytest.raises(InstrumentIdentityError):
            assert_production_contract(foreign)

    @pytest.mark.parametrize("malformed", [
        "CON.F.US.MNQ.",        # no month at all
        "CON.F.US.MNQ.Z",       # no year
        "CON.F.US.MNQ.Z2",      # one-digit year
        "CON.F.US.MNQ.Z266",    # three-digit year
        "CON.F.US.MNQ.A26",     # not a CME month code
        "CON.F.US.MNQ.Z26.X",   # trailing segment
        "con.f.us.mnq.z26",     # lower case is a different id
    ])
    def test_malformed_mnq_lookalikes_are_refused(self, malformed):
        """4. Well-formed is not the same as MNQ-shaped."""
        with pytest.raises(InstrumentIdentityError):
            assert_production_contract(malformed)

    def test_surrounding_whitespace_is_stripped_not_refused(self):
        assert (assert_production_contract("  CON.F.US.MNQ.Z26  ")
                == "CON.F.US.MNQ.Z26")

    def test_the_authorization_still_binds_one_exact_contract(self):
        """5. Family validity is permission to ASK, never to trade a different
        month. The signed authorization refuses a mismatch on any later run."""
        from datetime import datetime, timezone

        from ai_retrieval.retrieval import retrieval_enabled
        from broker import topstepx_session_authorization as SA

        fp = "acct:fc84f7a928d9"
        auth = SA.SessionAuthorization(
            session_id="PROD-20260921", account_fingerprint=fp,
            contract_id="CON.F.US.MNQ.Z26", session_date="20260921",
            decision_window="09:00-14:00 America/New_York",
            daily_loss_budget_usd=725.0,
            # Read from the runtime rather than pinned: this test is about the
            # contract binding, and an unrelated retrieval default must not be
            # what decides whether it passes.
            retrieval_enabled=retrieval_enabled(),
            issued_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc).isoformat())
        auth.authorization_fingerprint = auth.fingerprint()

        # The contract it signed verifies.
        auth.verify(account_fingerprint=fp, contract_id="CON.F.US.MNQ.Z26",
                    session_date="20260921")

        # A different month in the same family does NOT, even though that month
        # is structurally legal above.
        assert_production_contract("CON.F.US.MNQ.H27")
        with pytest.raises(SA.AuthorizationRefused, match="CONTRACT_MISMATCH"):
            auth.verify(account_fingerprint=fp, contract_id="CON.F.US.MNQ.H27",
                        session_date="20260921")


class TestEvidenceEligibility:

    def test_mnq_records_remain_eligible(self):
        assert retrieval_eligible(MNQ_REC)[0] is True

    def test_qqq_records_are_excluded(self):
        ok, why = retrieval_eligible(QQQ_REC)
        assert ok is False and "qqq" in why

    def test_records_without_identity_are_excluded_not_assumed(self):
        ok, why = retrieval_eligible(BARE_REC)
        assert ok is False and why == "missing_instrument_identity"

    def test_an_alpaca_venue_record_is_excluded(self):
        ok, why = retrieval_eligible({"instrument": "MNQ", "venue": "ALPACA"})
        assert ok is False and "alpaca" in why

    def test_records_marked_retired_historical_are_excluded(self):
        ok, why = retrieval_eligible({"instrument": "MNQ",
                                      "status": "RETIRED_HISTORICAL"})
        assert ok is False and why == "retired_historical_record"

    def test_an_explicitly_ineligible_record_is_excluded(self):
        ok, _ = retrieval_eligible({"instrument": "MNQ", "retrieval_eligible": False})
        assert ok is False

    def test_identity_is_found_in_market_context(self):
        """The schema nests symbol here; missing it would exclude everything."""
        assert record_instrument(MNQ_REC) == "MNQ"

    def test_filtering_keeps_mnq_and_drops_the_rest(self):
        keep, drop = filter_records([MNQ_REC, QQQ_REC, BARE_REC])
        assert len(keep) == 1 and len(drop) == 2


class TestRetrievalIsGuarded:

    def test_retrieval_excludes_qqq_before_similarity(self):
        """Identity is checked first: a QQQ session can look very similar."""
        import ast
        import inspect
        import textwrap

        from ai_retrieval import retrieval
        src = textwrap.dedent(inspect.getsource(retrieval.retrieve_analogs))
        tree = ast.parse(src)
        calls = [getattr(n.func, "id", "") for n in ast.walk(tree)
                 if isinstance(n, ast.Call)]
        assert calls.index("retrieval_eligible") < calls.index("cosine")


class TestNoQqqDefaultsRemain:

    @pytest.mark.parametrize("path", [
        "src/ai_brain/ecu.py",
        "src/ai_brain/thesis_lifecycle.py",
        "src/market_data/volume_witness.py",
    ])
    def test_no_executable_qqq_default_survives(self, path):
        """Checked on parsed code: comments may explain the old default."""
        import ast
        tree = ast.parse(open(path, encoding="utf-8").read())
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        offenders = [s for s in literals if s.strip().upper() == "QQQ"]
        assert not offenders, f"{path} still has an executable 'QQQ' literal"

    def test_the_production_launcher_has_no_qqq_default(self):
        import ast
        tree = ast.parse(open("tools/topstepx_production_session.py",
                              encoding="utf-8").read())
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        # A default would be the bare symbol. Telemetry lines that REPORT the
        # retirement ("QQQ RUNTIME : REMOVED") are the opposite of a default.
        assert not [s for s in literals if s.strip().upper() == "QQQ"]

    def test_the_production_launcher_imports_no_alpaca(self):
        import ast
        tree = ast.parse(open("tools/topstepx_production_session.py",
                              encoding="utf-8").read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
        assert not [m for m in mods if "alpaca" in m.lower()]
