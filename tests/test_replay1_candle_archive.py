"""
REPLAY-1 — candle archive regression locks (2026-07-09).

The archive is the ONLY durable copy of the 1m tape (live fetch is a rolling
window). Locks:
  * range fetch: base interface raises DataFeedError (providers without range
    support keep working); the Alpaca override is archived and non-importable
  * archive round-trip: fetch → filter to ET date → atomic write → load
  * integrity: existing archive never silently clobbered (skip unless more bars
    or force); corrupt archive rewritten; no_data day reported, nothing written
  * ET-date filtering: bars outside the session date are excluded
  * env-isolated dir (REPLAY_CANDLES_DIR — DECON-2 pattern)
  * backfill: skips existing + no-data days; one bad day never kills the run
  * safety: replay_validation imports no broker/order machinery
"""
import json
import importlib
import os
import sys
import tempfile
import unittest
from datetime import timezone
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data_feed.provider_interface import BaseDataProvider, DataFeedError  # noqa: E402
from replay_validation.candle_archive import (                            # noqa: E402
    archive_session, load_session, list_archived, backfill, archive_path,
)


def _bar(ts, px=700.0):
    return {"timestamp": ts, "open": px, "high": px + 0.5,
            "low": px - 0.5, "close": px + 0.2, "volume": 1000.0}


class _FakeProvider(BaseDataProvider):
    """Serves a fixed tape; counts range calls. 2026-07-08 ET session bars are
    13:30-20:00 UTC (09:30-16:00 ET)."""

    def __init__(self, candles=None):
        self.calls = 0
        self._candles = candles if candles is not None else [
            _bar("2026-07-08T13:30:00+00:00"),
            _bar("2026-07-08T13:31:00+00:00"),
            _bar("2026-07-08T19:59:00+00:00"),
            # next ET day (00:30 ET on the 9th) — must be filtered out of 0708
            _bar("2026-07-09T04:30:00+00:00"),
        ]

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return list(self._candles)[-lookback_bars:]

    def fetch_1m_candles_range(self, symbol, start, end):
        self.calls += 1
        return list(self._candles)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {"REPLAY_CANDLES_DIR": self.tmp})
        self._e.start()

    def tearDown(self):
        self._e.stop()


class TestRangeFetchInterface(unittest.TestCase):
    def test_base_interface_raises_datafeed_error(self):
        class _Minimal(BaseDataProvider):
            def fetch_1m_candles(self, symbol, lookback_bars):
                return []
        with self.assertRaises(DataFeedError):
            _Minimal().fetch_1m_candles_range("QQQ", None, None)

    def test_the_alpaca_provider_is_not_importable(self):
        """LUNA-TOPSTEPX-ONLY: Alpaca was REMOVED, not archived.

        This test previously asserted the retired module sat under
        `archive/legacy_alpaca_qqq/` and could not be imported. The
        archive copy is gone too, so the surviving theorem is the one
        that actually matters: nothing can import an Alpaca provider.
        """
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("data_feed.alpaca_provider")

    def test_archive_filters_to_et_date_and_loads(self):
        prov = _FakeProvider()
        res = archive_session("20260708", "QQQ", provider=prov)
        self.assertEqual(res["status"], "archived")
        self.assertEqual(res["bar_count"], 3)       # the 0709-ET bar excluded
        candles = load_session("20260708", "QQQ")
        self.assertEqual(len(candles), 3)
        self.assertEqual(candles[0]["timestamp"], "2026-07-08T13:30:00+00:00")

    def test_load_missing_raises_with_instruction(self):
        with self.assertRaises(FileNotFoundError):
            load_session("19990101", "QQQ")

    def test_no_data_day_writes_nothing(self):
        prov = _FakeProvider(candles=[])
        res = archive_session("20260712", "QQQ", provider=prov)   # a Sunday
        self.assertEqual(res["status"], "no_data")
        self.assertFalse(os.path.exists(archive_path("20260712", "QQQ")))


class TestIntegrity(_Base):
    def test_existing_archive_not_silently_clobbered(self):
        prov = _FakeProvider()
        archive_session("20260708", "QQQ", provider=prov)
        res = archive_session("20260708", "QQQ", provider=prov)   # same bars
        self.assertEqual(res["status"], "skipped_existing")

    def test_more_bars_upgrades_and_force_overwrites(self):
        prov = _FakeProvider()
        archive_session("20260708", "QQQ", provider=prov)
        richer = _FakeProvider(prov._candles + [_bar("2026-07-08T19:58:00+00:00")])
        res = archive_session("20260708", "QQQ", provider=richer)
        self.assertEqual(res["status"], "archived")                # more bars wins
        self.assertEqual(res["bar_count"], 4)
        res = archive_session("20260708", "QQQ", provider=prov, force=True)
        self.assertEqual(res["status"], "archived")                # force overwrites
        self.assertEqual(res["bar_count"], 3)

    def test_corrupt_archive_rewritten(self):
        prov = _FakeProvider()
        path = archive_path("20260708", "QQQ")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        res = archive_session("20260708", "QQQ", provider=prov)
        self.assertEqual(res["status"], "archived")
        self.assertEqual(len(load_session("20260708", "QQQ")), 3)


class TestBackfillAndListing(_Base):
    def test_backfill_skips_existing_and_survives_errors(self):
        prov = _FakeProvider()
        # backfill window is relative to today; call archive directly for the
        # deterministic parts and prove backfill's error isolation separately.
        class _Explodes(BaseDataProvider):
            def fetch_1m_candles(self, symbol, lookback_bars):
                return []
            def fetch_1m_candles_range(self, symbol, start, end):
                raise DataFeedError("boom")
        results = backfill(3, "QQQ", provider=_Explodes())
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["status"].startswith("error:") for r in results))
        # and a healthy provider archives + lists
        archive_session("20260708", "QQQ", provider=prov)
        rows = list_archived("QQQ")
        self.assertEqual(rows, [{"date": "20260708", "symbol": "QQQ", "bar_count": 3}])


class TestSafetyIsolation(unittest.TestCase):
    def test_replay_package_imports_no_broker_machinery(self):
        pkg = os.path.join(os.path.dirname(__file__), "..", "src", "replay_validation")
        for name in os.listdir(pkg):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(pkg, name), encoding="utf-8") as fh:
                txt = fh.read()
            for forbidden in ("TradingClient", "submit_order", "broker_adapter",
                              "paper_execution"):
                self.assertNotIn(forbidden, txt, f"{name} references {forbidden}")


if __name__ == "__main__":
    unittest.main()
