"""Zone SOURCE-TIMEFRAME policy (2026-07-23).

The stop anchors to the zone-defining candle's wick, so stop width scales with
the source candle's timeframe. 1m zones produce stops far below MNQ's
survivability floor (~2pt median vs a 15pt minimum) — they can never size, and
the ones that squeak through are tighter than the instrument's noise. 1m is
dropped as a zone source; per-family ORDERING is untouched (only the allowed
SET is constrained), so this cannot silently change which setups are detected.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.price_levels import (                                   # noqa: E402
    _DEFAULT_SOURCE_TFS, _FAMILY_TF_PRIORITY, _allowed_source_tfs,
    _symbol_root, build_price_level,
)


class TestDefaultPolicy(unittest.TestCase):
    def test_default_drops_1m_only(self):
        self.assertEqual(_DEFAULT_SOURCE_TFS, ("15m", "5m", "3m"))
        self.assertNotIn("1m", _DEFAULT_SOURCE_TFS)

    def test_default_used_when_no_env_no_symbol(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_allowed_source_tfs(""), _DEFAULT_SOURCE_TFS)
            self.assertEqual(_allowed_source_tfs("MNQ SEP26"), _DEFAULT_SOURCE_TFS)

    def test_family_ordering_untouched(self):
        # ordering encodes tool semantics — the policy constrains the SET only
        self.assertEqual(_FAMILY_TF_PRIORITY["ifvg"], ["3m", "1m", "5m", "15m"])
        self.assertEqual(_FAMILY_TF_PRIORITY["opening_fvg"], ["1m", "3m", "5m", "15m"])


class TestSymbolRoot(unittest.TestCase):
    def test_roots(self):
        self.assertEqual(_symbol_root("MNQ SEP26"), "MNQ")
        self.assertEqual(_symbol_root("mnqu6"), "MNQ")
        self.assertEqual(_symbol_root(""), "")
        self.assertEqual(_symbol_root(None), "")


class TestEnvOverrides(unittest.TestCase):
    def test_global_env_rollback_restores_1m(self):
        with mock.patch.dict(os.environ, {"ZONE_SOURCE_TFS": "15m,5m,3m,1m"}, clear=True):
            self.assertIn("1m", _allowed_source_tfs("MNQ SEP26"))

    def test_per_symbol_env_wins_and_isolates(self):
        with mock.patch.dict(os.environ, {"ZONE_SOURCE_TFS_MNQ": "15m"}, clear=True):
            self.assertEqual(_allowed_source_tfs("MNQ SEP26"), ("15m",))
            # a different symbol is unaffected
            self.assertEqual(_allowed_source_tfs("MES SEP26"), _DEFAULT_SOURCE_TFS)

    def test_malformed_env_cannot_blank_the_toolbox(self):
        for bad in ("", "   ", "garbage,nonsense", ",,,"):
            with mock.patch.dict(os.environ, {"ZONE_SOURCE_TFS": bad}, clear=True):
                self.assertEqual(_allowed_source_tfs("MNQ SEP26"), _DEFAULT_SOURCE_TFS, bad)

    def test_per_symbol_env_takes_precedence_over_global(self):
        with mock.patch.dict(os.environ,
                             {"ZONE_SOURCE_TFS": "15m,5m,3m,1m",
                              "ZONE_SOURCE_TFS_MNQ": "15m,5m"}, clear=True):
            self.assertEqual(_allowed_source_tfs("MNQ SEP26"), ("15m", "5m"))


def _candles(n=30, base=29000.0):
    out = []
    for i in range(n):
        o = base + i
        out.append({"open": o, "high": o + 3, "low": o - 3, "close": o + 1,
                    "timestamp": f"2026-07-23T10:{i:02d}:00-04:00", "volume": 100})
    return out


class TestOneMinuteSourceIsDropped(unittest.TestCase):
    def _snap(self, tf_with_candles):
        return {
            "symbol": "MNQ SEP26",
            "session": "ny_open",
            "timeframes": {tf: {"recent_candles": _candles()} for tf in tf_with_candles},
            "structure": {}, "liquidity": {},
        }

    def test_1m_only_snapshot_yields_no_zone(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = build_price_level("bullish_fvg", self._snap(["1m"]))
            self.assertEqual(out.get("level_type"), "no_zone")

    def test_1m_only_still_works_when_env_rolls_back(self):
        # proves the guard (not missing data) is what produced no_zone above
        with mock.patch.dict(os.environ, {"ZONE_SOURCE_TFS": "15m,5m,3m,1m"}, clear=True):
            out = build_price_level("bullish_fvg", self._snap(["1m"]))
            self.assertIsNotNone(out.get("level_type"))


if __name__ == "__main__":
    unittest.main()
