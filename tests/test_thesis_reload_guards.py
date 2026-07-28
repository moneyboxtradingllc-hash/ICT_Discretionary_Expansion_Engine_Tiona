"""A persisted thesis must not cross instruments or sleep through the calendar.

Both guards failed together on 2026-07-24. Building a snapshot for MNQ resurrected
a thesis created 2026-06-15 for QQQ:

  - snapshot_builder constructed ThesisLifecycleEngine() with no symbol, so the
    engine fell back to SCAN_SYMBOL/"QQQ". The reload guard compares the stored
    thesis's symbol against that same default, so it matched and admitted the
    thesis. The guard passed precisely because both sides were the same wrong
    default. (scan_loop and replay_session always passed the symbol; only the
    snapshot_builder fallback did not.)

  - age is counted in scans, not time. The thesis reloaded with age_scans=10,
    far under the 240 cap, after sitting on disk for 39 days.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.thesis_lifecycle import (
    STATUS_EXPIRED, ThesisLifecycleEngine, _minutes_since,
)


def _write_active(dirpath, *, symbol, last_updated, age_scans=10):
    payload = {"symbol": symbol,
               "active": {"thesis_id": "TH_test", "symbol": symbol,
                          "created_at": last_updated, "last_updated_at": last_updated,
                          "age_scans": age_scans, "status": "WEAKENING",
                          "direction": "neutral", "playbook_family": "accumulation"}}
    path = os.path.join(dirpath, "active_thesis.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, default=str)
    return path


@pytest.fixture
def brain_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
    monkeypatch.delenv("SCAN_SYMBOL", raising=False)
    return str(tmp_path)


def _fresh(minutes_ago=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class TestTheSymbolGuard:
    def test_another_instruments_thesis_is_not_resurrected(self, brain_dir):
        _write_active(brain_dir, symbol="QQQ", last_updated=_fresh())
        assert ThesisLifecycleEngine(symbol="MNQ SEP26")._active is None

    def test_the_same_instruments_thesis_is_resurrected(self, brain_dir):
        _write_active(brain_dir, symbol="MNQ SEP26", last_updated=_fresh())
        active = ThesisLifecycleEngine(symbol="MNQ SEP26")._active
        assert active is not None and active["thesis_id"] == "TH_test"


class TestTheClockGuard:
    def test_a_thesis_idle_for_weeks_does_not_return(self, brain_dir):
        """age_scans=10 is under the cap; only wall-clock catches this."""
        old = (datetime.now(timezone.utc) - timedelta(days=39)).isoformat()
        _write_active(brain_dir, symbol="MNQ SEP26", last_updated=old, age_scans=10)
        active = ThesisLifecycleEngine(symbol="MNQ SEP26")._active
        assert active["status"] == STATUS_EXPIRED
        assert "idle" in active["invalidated_reason"]

    def test_an_intraday_restart_still_recovers_its_thesis(self, brain_dir):
        _write_active(brain_dir, symbol="MNQ SEP26",
                      last_updated=_fresh(minutes_ago=90))
        active = ThesisLifecycleEngine(symbol="MNQ SEP26")._active
        assert active is not None and active["status"] != STATUS_EXPIRED

    def test_the_window_is_configurable(self, brain_dir, monkeypatch):
        monkeypatch.setenv("THESIS_MAX_RELOAD_AGE_MINUTES", "30")
        _write_active(brain_dir, symbol="MNQ SEP26",
                      last_updated=_fresh(minutes_ago=45))
        assert ThesisLifecycleEngine(symbol="MNQ SEP26")._active["status"] == STATUS_EXPIRED

    def test_zero_disables_the_check(self, brain_dir, monkeypatch):
        monkeypatch.setenv("THESIS_MAX_RELOAD_AGE_MINUTES", "0")
        old = (datetime.now(timezone.utc) - timedelta(days=39)).isoformat()
        _write_active(brain_dir, symbol="MNQ SEP26", last_updated=old)
        assert ThesisLifecycleEngine(symbol="MNQ SEP26")._active["status"] != STATUS_EXPIRED


class TestTheTimestampParser:
    def test_reads_the_ninjatrader_seven_digit_fraction(self):
        """datetime.fromisoformat rejects 7-digit fractional seconds outright."""
        assert _minutes_since("2026-07-24T13:52:00.0000000-04:00") is not None

    def test_unreadable_stamps_do_not_expire_a_thesis(self):
        assert _minutes_since("garbage") is None
        assert _minutes_since(None) is None

    def test_a_naive_stamp_is_still_measurable(self):
        naive = (datetime.now() - timedelta(minutes=10)).isoformat()
        assert 5 < _minutes_since(naive) < 20


class TestTheBuilderNamesTheInstrument:
    def test_snapshot_builder_passes_the_symbol_through(self, brain_dir, monkeypatch):
        """The fallback engine must not identify as QQQ on an MNQ session."""
        monkeypatch.setenv("BRAIN_ECU_MODE", "true")
        monkeypatch.setenv("THESIS_LIFECYCLE_MODE", "shadow")
        monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
        _write_active(brain_dir, symbol="QQQ", last_updated=_fresh())

        import market_data.snapshot_builder as sb
        seen = {}

        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine as Real

        class _Probe(Real):
            def __init__(self, persist=True, symbol=None):
                seen["symbol"] = symbol
                super().__init__(persist=persist, symbol=symbol)

        monkeypatch.setattr("ai_brain.thesis_lifecycle.ThesisLifecycleEngine", _Probe)
        from data_feed.timeframe_builder import build_timeframes
        candles = [{"timestamp": f"2026-07-24T13:{m:02d}:00-04:00", "open": 100.0,
                    "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10,
                    "instrument": "MNQ SEP26"} for m in range(0, 60)]
        sb.build_snapshot(build_timeframes(candles), symbol="MNQ SEP26")
        assert seen.get("symbol") == "MNQ SEP26"
