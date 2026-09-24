from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_candidate_freshness import (  # noqa: E402
    CandidateSnapshot, CandidateStale, LiquidityObjective, assess,
)

NOW = datetime(2026, 9, 24, 15, 30, tzinfo=timezone.utc)


def candidate():
    registered = (NOW - timedelta(minutes=10)).isoformat()
    return CandidateSnapshot(
        candidate_id="candidate-stale-level", snapshot_id="snap-current",
        direction="bullish", entry_price=29880.0, invalidation_price=29872.0,
        objective=LiquidityObjective("target@29910", "prior_session_high", 29910.0,
                                    NOW - timedelta(minutes=1)),
        contract_id="CON.F.US.MNQ.U26", account_fingerprint="account-fp",
        created_at=NOW - timedelta(minutes=1), narrative="bullish",
        extras={"structural_invalidation": {
            "structure_type": "protected_low",
            "authorized_catalog_row": {
                "type": "protected_low", "price": 29872.0, "timeframe": "5m",
                "registered_at": registered,
                "swing_id": "5m:swing_low:29872",
            }}})


def bars(*closes):
    stamps = [NOW - timedelta(minutes=20), NOW - timedelta(minutes=5), NOW - timedelta(minutes=2)]
    return {"5m": {"recent_candles": [
        {"timestamp": stamp.isoformat(), "close": close, "temporal_status": "settled"}
        for stamp, close in zip(stamps, closes)]}}


def common(**over):
    values = dict(
        current_price=29885.0, high_since=29890.0, low_since=29878.0,
        tick_size=0.25, snapshot_id="snap-current", contract_id="CON.F.US.MNQ.U26",
        account_fingerprint="account-fp", account_state_digest="", data_age_seconds=1,
        in_window=True, manual_activity=False, now=NOW,
    )
    values.update(over)
    return values


def test_candidate_created_after_registered_swing_was_broken_is_refused():
    # A pre-registration breach belongs to an earlier life; a later completed
    # 5m close below the registered low invalidates this selected stop.
    history = bars(29870.0, 29875.0, 29871.75)
    with pytest.raises(CandidateStale) as exc:
        assess(candidate(), **common(invalidation_timeframes=history))
    assert exc.value.reason == "invalidation_touched"


def test_history_since_registration_allows_unbroken_level():
    history = bars(29870.0, 29875.0, 29873.0)
    assert assess(candidate(), **common(invalidation_timeframes=history))["fresh"]


def test_missing_retained_history_refuses_instead_of_assuming_intact():
    too_recent = {"5m": {"recent_candles": [
        {"timestamp": (NOW - timedelta(minutes=2)).isoformat(),
         "close": 29880.0, "temporal_status": "settled"}]}}
    with pytest.raises(CandidateStale) as exc:
        assess(candidate(), **common(invalidation_timeframes=too_recent))
    assert exc.value.reason == "invalidation_history_unavailable"


@pytest.mark.parametrize("price", [29872.0, 29871.75])
def test_executable_price_at_or_through_structural_stop_is_refused(price):
    # Use an otherwise clean no-history candidate to isolate the final quote rule.
    c = candidate()
    c.extras = {}
    with pytest.raises(CandidateStale) as exc:
        assess(c, **common(current_executable_price=price))
    assert exc.value.reason == "current_price_beyond_invalidation"
