"""
HTF-REPLAY — replay-parity locks (2026-07-30).

The wiring audit (docs/audits/HTF_WIRING_AUDIT_20260730.md) found that
replay_session never fed htf_context, so every Brain study measured an
HTF-blind Brain while the live QQQ lane carried HTF data — a live/replay
context mismatch. HTF-REPLAY repairs the test environment under strict
invariants. These tests lock them:

  * default OFF — the legacy HTF-blind walk is untouched: no htf kwarg reaches
    build_snapshot, no "htf" key on scan records, manifest labeled htf_memory_absent
  * opt-in ON — memory is reconstructed ONLY from archived sessions strictly
    BEFORE the replay date (no future data; the target session never seeds)
  * no future leakage INSIDE the day — at scan T the HTF state reflects only
    candles <= T (a late sweep must not appear in early-scan liquidity context)
  * isolation is structural — the live HTF store is neither read (preload=False
    ignores an existing store) nor written (persist=False leaves the dir alone)
  * determinism — two identical HTF-on runs produce identical scans
  * provability — every HTF-on scan carries the compact "htf" proof block and
    the manifest carries the arm label + seed dates
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.htf_memory_engine import HtfMemoryEngine        # noqa: E402
from replay_validation.replay_session import (                    # noqa: E402
    replay_session, _seed_htf_engine,
)
from replay_validation.candle_archive import archive_session      # noqa: E402
from data_feed.provider_interface import BaseDataProvider         # noqa: E402

from datetime import datetime, timedelta, timezone                # noqa: E402


class _MultiDayTape(BaseDataProvider):
    """Synthetic 1m tape over three ET sessions (all bars 13:30Z+ = 09:30 ET).

    0706: quiet day around 700 (high ~700.6)
    0707: prior session — day high EXACTLY 710.0, close 706.0
    0708: target — first 40 bars stay below 710; bars 40+ spike to 720
          (a LATE buy-side sweep early scans must not see)
    """

    _PLAN = {
        "20260706": [(700.0, 0.02, 0.3)] ,
        "20260707": [(705.0, 0.05, 0.3)],
        "20260708": [(706.0, 0.03, 0.3)],
    }

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return []

    def fetch_1m_candles_range(self, symbol, start, end):
        # start is ET midnight of the session date (04:00Z same calendar date)
        date = start.astimezone(timezone.utc).strftime("%Y%m%d")
        plan = self._PLAN.get(date)
        if not plan:
            return []
        base = (datetime.strptime(date, "%Y%m%d")
                .replace(hour=13, minute=30, tzinfo=timezone.utc))
        px, drift, wick = plan[0]
        out = []
        for i in range(60):
            px += drift if i % 3 else -drift / 2
            hi, lo = px + wick, px - wick
            if date == "20260707" and i == 30:
                hi = 710.0                    # the prior-day high level
            if date == "20260708" and i < 3:
                lo = 704.0                    # early sell-side sweep of the
                                              # prior low → only the 710 buy-side
                                              # draw remains untapped
            if date == "20260708" and i >= 40:
                hi = 720.0                    # LATE buy-side sweep — future
                px = 712.0                    # relative to the early test ticks
            ts = (base + timedelta(minutes=i)).isoformat()
            out.append({"timestamp": ts, "open": px, "high": hi,
                        "low": lo, "close": px + 0.05, "volume": 1000.0})
        if date == "20260707":
            out[-1]["close"] = 706.0          # deterministic prior close
        return out


def _early_ticks(n=3):
    base = datetime(2026, 7, 8, 13, 55, tzinfo=timezone.utc)   # bar ~25 of 0708
    return [base + timedelta(minutes=i) for i in range(n)]


class _ArchiveFixture(unittest.TestCase):
    """Three archived sessions in a sandboxed REPLAY_CANDLES_DIR + sandboxed
    HTF store dir carrying a sentinel the replay must never touch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.htf_dir = os.path.join(self.tmp, "htf_store")
        os.makedirs(self.htf_dir, exist_ok=True)
        # sentinel live store: 10 fake days — replay must not read or write it
        self.sentinel_path = os.path.join(self.htf_dir, "QQQ.json")
        fake_days = {f"2026-06-{d:02d}": {"open": 1, "high": 2, "low": 0,
                                          "close": 1, "first_ts": "x",
                                          "last_ts": "y"} for d in range(1, 11)}
        with open(self.sentinel_path, "w", encoding="utf-8") as fh:
            json.dump({"days": fake_days}, fh)
        with open(self.sentinel_path, "rb") as fh:
            self.sentinel_bytes = fh.read()

        self._e = patch.dict(os.environ, {
            "REPLAY_CANDLES_DIR": os.path.join(self.tmp, "candles"),
            "HTF_MEMORY_DIR": self.htf_dir,
            "AI_BRAIN_DIR": os.path.join(self.tmp, "no_records"),
        })
        self._e.start()
        for d in ("20260706", "20260707", "20260708"):
            archive_session(d, "QQQ", provider=_MultiDayTape())

    def tearDown(self):
        self._e.stop()

    def _run(self, htf, ticks=None, sandbox_name="sb"):
        return replay_session(
            "20260708", "QQQ", lookback=200, max_scans=3,
            ticks=ticks or _early_ticks(),
            sandbox=os.path.join(self.tmp, sandbox_name), htf=htf)


class TestEngineIsolation(_ArchiveFixture):
    def test_preload_false_ignores_existing_live_store(self):
        eager = HtfMemoryEngine("QQQ", persist=False)              # legacy: reads
        self.assertEqual(len(eager._state["days"]), 10)
        fresh = HtfMemoryEngine("QQQ", persist=False, preload=False)
        self.assertEqual(fresh._state["days"], {})

    def test_seeder_uses_only_prior_archived_sessions(self):
        engine, seed_dates = _seed_htf_engine("20260708", "QQQ")
        self.assertEqual(seed_dates, ["20260706", "20260707"])     # never 0708
        days = sorted(engine._state["days"])
        self.assertEqual(days, ["2026-07-06", "2026-07-07"])
        # sentinel store ignored (would have contributed 10 June days)
        self.assertNotIn("2026-06-01", engine._state["days"])
        # and never written
        with open(self.sentinel_path, "rb") as fh:
            self.assertEqual(fh.read(), self.sentinel_bytes)


class TestWalkerArms(_ArchiveFixture):
    def test_default_off_is_htf_blind_and_labeled(self):
        result = self._run(htf=False)
        self.assertFalse(result["manifest"]["htf_mode"])
        self.assertNotIn("htf_seed_dates", result["manifest"])
        self.assertIn("htf_memory_absent", result["manifest"]["caveats"])
        self.assertGreaterEqual(result["summary"]["scans"], 1)
        for scan in result["scans"]:
            self.assertNotIn("htf", scan)
        self.assertNotIn("htf", result["summary"])

    def test_htf_on_labeled_seeded_and_proven_per_scan(self):
        result = self._run(htf=True, sandbox_name="sb_on")
        m = result["manifest"]
        self.assertTrue(m["htf_mode"])
        self.assertEqual(m["htf_seed_dates"], ["20260706", "20260707"])
        self.assertIn("htf_memory_archive_seeded", m["caveats"])
        self.assertGreaterEqual(result["summary"]["scans"], 1)
        for scan in result["scans"]:
            proof = scan.get("htf")
            self.assertIsInstance(proof, dict)
            # 2 completed prior sessions + today forming = memory_age 2
            self.assertEqual(proof["memory_age"], 2)
            self.assertEqual(proof["latest_completed_day"], "2026-07-07")
        s = result["summary"]["htf"]
        self.assertEqual(s["scans_with_htf"], result["summary"]["scans"])
        self.assertEqual(s["memory_age_first"], 2)

    def test_no_future_leakage_late_sweep_invisible_to_early_scans(self):
        # ticks stop at bar ~27 of 0708; the 720.0 sweep happens at bar 40+.
        # If future candles leaked into HTF state, previous-day-high (710)
        # would read as swept and the buy_side draw would vanish.
        result = self._run(htf=True, sandbox_name="sb_leak")
        self.assertGreaterEqual(result["summary"]["scans"], 1)
        for scan in result["scans"]:
            draw = scan["htf"]["nearest_draw"]
            self.assertIsNotNone(draw)
            self.assertEqual(draw["side"], "buy_side")
            self.assertEqual(draw["level"], 710.0)

    def test_htf_on_run_is_deterministic(self):
        r1 = self._run(htf=True, sandbox_name="sb_d1")
        r2 = self._run(htf=True, sandbox_name="sb_d2")
        self.assertEqual(json.dumps(r1["scans"], sort_keys=True, default=str),
                         json.dumps(r2["scans"], sort_keys=True, default=str))

    def test_live_store_untouched_after_htf_run(self):
        self._run(htf=True, sandbox_name="sb_iso")
        with open(self.sentinel_path, "rb") as fh:
            self.assertEqual(fh.read(), self.sentinel_bytes)
        self.assertEqual(os.listdir(self.htf_dir), ["QQQ.json"])


if __name__ == "__main__":
    unittest.main()
