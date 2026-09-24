from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from narrative_authority.protected_swings import ProtectedSwingTracker  # noqa: E402


def _record(tf, side, level=100.0, registered_at="2026-09-24T14:00:00+00:00"):
    return {"level": level, "timeframe": tf, "role": "test",
            "registered_at": registered_at,
            "swing_id": f"{tf}:swing_{side}:{level:g}", "basis": "test"}


def _snapshot(**tf_candles):
    return {"liquidity": {}, "structure": {}, "timestamp": "2026-09-24T15:00:00+00:00",
            "timeframes": {tf: {"recent_candles": candles}
                           for tf, candles in tf_candles.items()}}


@pytest.mark.parametrize(("side", "close", "mapping", "slot", "crossed"), [
    ("high", 100.25, "highs", "protected_highs", True),
    ("low", 99.75, "lows", "protected_lows", True),
])
def test_one_tick_completed_own_timeframe_close_invalidates(side, close, mapping, slot,
                                                           crossed, monkeypatch):
    monkeypatch.setenv("NARRATIVE_PROTECTED_BUFFER_PCT", "90")
    tracker = ProtectedSwingTracker()
    getattr(tracker, slot)["5m"] = _record("5m", side)
    state = tracker.update(_snapshot(**{"5m": [{"timestamp": "2026-09-24T14:55:00+00:00",
                                                   "close": close,
                                                   "temporal_status": "settled"}]}))
    assert "5m" not in getattr(tracker, slot)
    assert state["by_timeframe"][mapping] == {}


@pytest.mark.parametrize(("side", "mapping", "slot"), [
    ("high", "highs", "protected_highs"),
    ("low", "lows", "protected_lows"),
])
def test_wick_beyond_without_own_timeframe_close_does_not_invalidate(side, mapping, slot):
    tracker = ProtectedSwingTracker()
    getattr(tracker, slot)["5m"] = _record("5m", side)
    # The 1m close/wick crosses; only a completed 5m close can invalidate this life.
    state = tracker.update(_snapshot(**{
        "1m": [{"timestamp": "2026-09-24T14:59:00+00:00", "high": 101.0,
                "low": 99.0, "close": 101.0 if side == "high" else 99.0,
                "temporal_status": "settled"}],
        "5m": [{"timestamp": "2026-09-24T14:55:00+00:00", "high": 101.0,
                "low": 99.0, "close": 100.0, "temporal_status": "settled"}],
    }))
    assert "5m" in getattr(tracker, slot)
    assert "5m" in state["by_timeframe"][mapping]


@pytest.mark.parametrize("tf", ["1m", "3m", "5m", "15m"])
def test_each_registered_timeframe_uses_its_own_completed_close(tf):
    tracker = ProtectedSwingTracker()
    tracker.protected_highs[tf] = _record(tf, "high")
    candles = {other: [{"timestamp": "2026-09-24T14:55:00+00:00",
                       "close": 100.25, "temporal_status": "settled"}]
               for other in ("1m", "3m", "5m", "15m")}
    candles[tf] = [{"timestamp": "2026-09-24T14:55:00+00:00",
                    "close": 100.0, "temporal_status": "settled"}]
    tracker.update(_snapshot(**candles))
    assert tf in tracker.protected_highs

    candles[tf] = [{"timestamp": "2026-09-24T14:55:00+00:00",
                    "close": 100.25, "temporal_status": "settled"}]
    tracker.update(_snapshot(**candles))
    assert tf not in tracker.protected_highs
