"""STEP 4B.12 §6 UNIT 6 — IDENTITY SURVIVES NORMALISATION.

`timeframe_builder` attaches `contract` to every bucket it emits.
`normalize_candle` rebuilds a whitelisted dict and does not carry it, so
`recent_candles` reached the toolbox with no contract at all:

    build_timeframes bucket      contract = 'CON.F.US.MNQ.U26'
    recent_candles               contract = 0 / 90, 0 / 60, 0 / 80, 0 / 32

Canonical FVG occurrence identity is `contract + timeframe + completion bucket`
(the theorem `market_events._fvgs_at` already publishes), so with the contract
absent EVERY plain-FVG occurrence on the execution path was
`identity_evaluable = False` -- measured 215/215 fvg_zones blocked.

Repaired at the additive seam CONTINUITY-2G already uses, NOT by widening the
canonical `normalize_candle` schema for every consumer in the tree.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_data.object_identity import MarketObjectIdentityError  # noqa: E402
from market_data.snapshot_builder import _source_contract  # noqa: E402

CONTRACT = "CON.F.US.MNQ.U26"


def raw(ts, contract=CONTRACT, **extra):
    r = {"timestamp": ts, "open": 100, "high": 101, "low": 99, "close": 100.5,
         "volume": 10, "complete": True, "members": 3, "expected_members": 3}
    if contract is not None:
        r["contract"] = contract
    r.update(extra)
    return r


class TestTheContractSurvives:

    def test_the_exact_bucket_contract_is_carried(self):
        series = [raw("2026-08-12T18:00:00+00:00")]
        assert _source_contract(series, {"timestamp": "2026-08-12T18:00:00+00:00"}) \
            == {"contract": CONTRACT}

    def test_each_candle_takes_its_OWN_bucket_contract(self):
        """PER CANDLE, not one value asserted over the series. A mixed series
        must not be laundered into a single confident claim."""
        series = [raw("2026-08-12T18:00:00+00:00", contract="CON.F.US.MNQ.U26"),
                  raw("2026-08-12T18:03:00+00:00", contract="CON.F.US.MNQ.Z26")]
        assert _source_contract(series, {"timestamp": "2026-08-12T18:00:00+00:00"}) \
            == {"contract": "CON.F.US.MNQ.U26"}
        assert _source_contract(series, {"timestamp": "2026-08-12T18:03:00+00:00"}) \
            == {"contract": "CON.F.US.MNQ.Z26"}


class TestItFailsClosed:

    def test_a_bucket_with_no_contract_yields_nothing(self):
        series = [raw("2026-08-12T18:00:00+00:00", contract=None)]
        assert _source_contract(series, {"timestamp": "2026-08-12T18:00:00+00:00"}) == {}

    def test_a_self_contradicting_row_yields_nothing(self):
        """`row_contract` refuses a row declaring two identity authorities. That
        refusal is preserved as ABSENCE, never swallowed into a guess."""
        series = [raw("2026-08-12T18:00:00+00:00", contract="CON.F.US.MNQ.U26",
                      contractId="CON.F.US.MNQ.Z26")]
        assert _source_contract(series, {"timestamp": "2026-08-12T18:00:00+00:00"}) == {}

    def test_an_unmatched_timestamp_yields_nothing(self):
        series = [raw("2026-08-12T18:00:00+00:00")]
        assert _source_contract(series, {"timestamp": "2026-08-12T19:99:00+00:00"}) == {}

    def test_no_configured_symbol_fallback_exists(self):
        """Identity must name the market object, never a SETTING. No alias, no
        environment variable, no hard-coded instrument."""
        import ast
        import inspect
        import textwrap
        from market_data import snapshot_builder as SB
        tree = ast.parse(textwrap.dedent(inspect.getsource(SB._source_contract)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        consts = {n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for forbidden in ("getenv", "environ", "symbol", "instrument",
                          "DEFAULT_CONTRACT", "MNQ"):
            assert forbidden not in (names | attrs), forbidden
        assert not any("MNQ" in c for c in consts), "no hard-coded instrument"


class TestTheRepairIsAdditive:

    def _snapshot(self):
        from datetime import datetime, timezone
        from data_feed.timeframe_builder import build_timeframes
        from market_data.canonical_history import load_normalized_last_wins_history
        from market_data.snapshot_builder import build_snapshot
        store = os.path.join(ROOT, "data", "market_data", "topstepx",
                             "CON_F_US_MNQ_U26.jsonl")
        if not os.path.exists(store):
            pytest.skip("venue tape not present")
        cut = datetime(2026, 8, 12, 19, 43, tzinfo=timezone.utc)
        rows = [b for b in load_normalized_last_wins_history(store)
                if datetime.fromisoformat(b["timestamp"]) <= cut][:6000]
        return build_snapshot(build_timeframes(rows), symbol="MNQ")

    def test_recent_candles_now_carry_the_contract(self):
        snap = self._snapshot()
        for tf in ("1m", "3m", "5m", "15m"):
            rc = (snap.get("timeframes", {}).get(tf) or {}).get("recent_candles") or []
            if not rc:
                continue
            assert all(c.get("contract") for c in rc), f"{tf} lost the contract"
            assert {c["contract"] for c in rc} == {CONTRACT}

    def test_price_fields_are_untouched(self):
        """ADDITIVE ONLY: every existing consumer reads exactly what it read
        before. A provenance repair may not become a behavioural rewrite."""
        snap = self._snapshot()
        for tf in ("1m", "3m", "5m", "15m"):
            rc = (snap.get("timeframes", {}).get(tf) or {}).get("recent_candles") or []
            for c in rc:
                for k in ("open", "high", "low", "close", "volume", "range",
                          "body_size", "upper_wick", "lower_wick", "direction",
                          "timestamp", "temporal_status"):
                    assert k in c, f"{tf}: {k} disappeared"

    def test_the_canonical_identity_can_now_be_minted(self):
        from toolbox.price_levels import fvg_occurrences
        snap = self._snapshot()
        minted = 0
        for tf, mins in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15)):
            rc = (snap.get("timeframes", {}).get(tf) or {}).get("recent_candles") or []
            for d in ("bullish", "bearish"):
                for o in fvg_occurrences(rc, d, mins):
                    assert o["occurrence_id"] is not None, \
                        "an authoritative production occurrence has no identity"
                    assert o["identity_evaluable"] is True
                    assert "None" not in o["occurrence_id"]
                    minted += 1
        assert minted, "fixture produced no occurrences to check"
