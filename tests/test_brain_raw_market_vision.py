"""PHASE 4A — the windshield.

Measured on PROD-20260812-PM: Terra received exactly FIVE bars per timeframe on
all 81 scans. Five minutes of 1m. Twenty-five minutes of 5m. She was asked to
find a discretionary entry on the execution timeframes while looking through a
four-minute window.

The truncation lived in `snapshot_builder` (`normalized[-5:]`), so the CANONICAL
market state itself was amputated to the Brain's presentation policy and every
other consumer inherited the blindness before it got a say.

Now: the store retains, consumers present. Windows are role-based and neutral --
the last N canonical bars, nothing curated by mechanics.

No network. No model.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import (                                   # noqa: E402
    _BRAIN_PATH_BARS, _compact_path, build_brain_input)
from data_feed.timeframe_builder import build_timeframes             # noqa: E402
from market_data.snapshot_builder import (                           # noqa: E402
    CANONICAL_RETAINED_BARS, build_snapshot)

STORE = os.path.join(ROOT, "data", "market_data", "topstepx",
                     "CON_F_US_MNQ_U26.jsonl")


def _canonical_bars():
    if not os.path.exists(STORE):
        pytest.skip("canonical store not present in this checkout")
    return [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]


def _brain_at(hh, mm):
    bars = _canonical_bars()
    cut = datetime(2026, 8, 12, hh, mm, tzinfo=timezone.utc)
    kept = [b for b in bars if datetime.fromisoformat(b["timestamp"]) <= cut]
    if len(kept) < 200:
        pytest.skip("insufficient archived history for a span assertion")
    return build_brain_input(build_snapshot(build_timeframes(kept), symbol="MNQ"), {})


# ══════════════════════════════════════════════════════════════════════════════
class TestTheStoreIsNotTheView:

    def test_canonical_retention_is_role_based_not_five(self):
        assert CANONICAL_RETAINED_BARS == {"1m": 90, "3m": 60, "5m": 80, "15m": 32}

    def test_the_zone_detector_pins_its_OWN_window(self):
        """Widening the store must not move execution geometry. `price_levels`
        is fingerprint-bound; its 5-bar horizon is declared, not inherited."""
        from toolbox.price_levels import _ZONE_LOOKBACK_BARS
        assert _ZONE_LOOKBACK_BARS == 5

    def test_the_brain_window_is_declared_by_the_brain(self):
        assert _BRAIN_PATH_BARS == {"1m": 90, "3m": 60, "5m": 80, "15m": 32}


# ══════════════════════════════════════════════════════════════════════════════
class TestCompactPath:

    def _bar(self, ts, status="settled"):
        return {"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5,
                "close": 1.5, "volume": 10, "temporal_status": status}

    def test_a_row_is_ts_ohlcv_and_temporal_status(self):
        row = _compact_path([self._bar("2026-08-12T19:43:00+00:00")], 5)[0]
        assert row == ["08-12 19:43", 1.0, 2.0, 0.5, 1.5, 10, "S"]

    def test_the_timestamp_carries_the_DATE(self):
        """Survived the first implementation.

        A first cut emitted HH:MM only. Measured against the real canonical
        store, the 15m window reaches across a session boundary -- at the 15:43
        ET scan it spanned 2026-08-11 AND 2026-08-12. Yesterday's 14:15 bar was
        indistinguishable from today's, which is exactly 'absence masquerading
        as continuity' wearing a cheaper encoding.
        """
        rows = _compact_path([self._bar("2026-08-11T14:15:00+00:00"),
                              self._bar("2026-08-12T14:15:00+00:00")], 5)
        assert rows[0][0] == "08-11 14:15"
        assert rows[1][0] == "08-12 14:15"
        assert rows[0][0] != rows[1][0]

    @pytest.mark.parametrize("status,code", [("settled", "S"), ("forming", "F"),
                                             ("unknown", "U"), (None, "U")])
    def test_temporal_status_survives_compaction(self, status, code):
        assert _compact_path([self._bar("2026-08-12T19:43:00+00:00", status)], 5)[0][6] == code

    def test_a_forming_bar_is_included_and_labelled_never_dropped(self):
        rows = _compact_path([self._bar("2026-08-12T19:40:00+00:00", "settled"),
                              self._bar("2026-08-12T19:45:00+00:00", "forming")], 5)
        assert len(rows) == 2 and rows[-1][6] == "F"

    def test_derivable_fields_are_not_repeated(self):
        row = _compact_path([self._bar("2026-08-12T19:43:00+00:00")], 5)[0]
        assert len(row) == 7, "range/body_size/wicks/direction are reconstructible"

    def test_the_window_takes_the_NEWEST_bars(self):
        bars = [self._bar(f"2026-08-12T19:{m:02d}:00+00:00") for m in range(10, 40)]
        rows = _compact_path(bars, 5)
        assert len(rows) == 5 and rows[-1][0] == "08-12 19:39"


# ══════════════════════════════════════════════════════════════════════════════
class TestActualSpans:
    """§6 — prove the real spans, never fabricate history to meet a target."""

    def test_the_1543_scan_sees_the_afternoon(self):
        mk = _brain_at(19, 43)["market"]["candles"]
        assert len(mk["1m"]["path"]) == 90
        assert len(mk["5m"]["path"]) == 80
        assert mk["1m"]["path"][0][0].startswith("08-12")

    def test_the_5m_view_reaches_back_past_the_session_open(self):
        """The 5m chart is the narrative bridge between the 15m auction and the
        1m expression. At 15:43 it must not begin at 15:20."""
        mk = _brain_at(19, 43)["market"]["candles"]
        oldest = mk["5m"]["path"][0][0]              # "MM-DD HH:MM" UTC
        assert oldest <= "08-12 13:30", oldest       # 13:30Z = 09:30 ET open

    def test_every_row_is_date_qualified(self):
        mk = _brain_at(19, 43)["market"]["candles"]
        for tf in ("1m", "3m", "5m", "15m"):
            for row in mk[tf]["path"]:
                assert row[0][:2].isdigit() and row[0][2] == "-", row[0]

    def test_the_schema_and_legend_are_stated_once(self):
        market = _brain_at(19, 43)["market"]
        assert market["price_path_schema"] == ["ts", "o", "h", "l", "c", "v", "t"]
        assert "MM-DD" in market["price_path_legend"]
        for tf in ("1m", "3m", "5m", "15m"):
            assert "path_legend" not in market["candles"][tf]

    def test_the_compatibility_view_still_ships(self):
        mk = _brain_at(19, 43)["market"]["candles"]
        assert len(mk["1m"]["recent"]) == 5, "near-term detail retained for now"


# ══════════════════════════════════════════════════════════════════════════════
class TestFormingIsNotIncomplete:
    """PHASE 4B §7. `complete` is a MEMBERSHIP COUNT, not a temporal claim, so a
    historical bucket assembled across a hole in the canonical series was
    published as FORMING. Measured at the 15:43 scan: 7 of 32 15m bars,
    including 2026-08-11 15:00 built from FIVE of fifteen minutes. Terra was
    being told prior-day damaged history was live price action."""

    def _series(self):
        # three finished buckets, the middle one missing minutes, plus a live one
        return [
            {"timestamp": "2026-08-12T19:00:00+00:00", "complete": True,
             "members": 15, "expected_members": 15},
            {"timestamp": "2026-08-12T19:15:00+00:00", "complete": False,
             "members": 5, "expected_members": 15},
            {"timestamp": "2026-08-12T19:30:00+00:00", "complete": False,
             "members": 14, "expected_members": 15},
        ]

    def test_a_finished_but_partial_bucket_is_HISTORICAL_INCOMPLETE(self):
        from market_data.snapshot_builder import _temporal_status, HISTORICAL_INCOMPLETE
        s = self._series()
        assert _temporal_status(s, s[1], "15m")["temporal_status"] == HISTORICAL_INCOMPLETE

    def test_only_the_NEWEST_bucket_may_be_forming(self):
        from market_data.snapshot_builder import _temporal_status, FORMING
        s = self._series()
        assert _temporal_status(s, s[2], "15m")["temporal_status"] == FORMING
        assert _temporal_status(s, s[1], "15m")["temporal_status"] != FORMING

    def test_a_complete_bucket_is_still_settled(self):
        from market_data.snapshot_builder import _temporal_status, SETTLED
        s = self._series()
        assert _temporal_status(s, s[0], "15m")["temporal_status"] == SETTLED

    def test_DETECTOR_POLICY_IS_UNCHANGED(self):
        """The split refines what is PUBLISHED, never what counts as settled
        evidence. An incomplete historical bucket was excluded from settled
        detector inputs before and must be excluded now."""
        from market_data.snapshot_builder import _bucket_is_settled
        s = self._series()
        assert _bucket_is_settled(s, s[0]) is True      # complete
        assert _bucket_is_settled(s, s[1]) is False     # historical_incomplete
        assert _bucket_is_settled(s, s[2]) is False     # forming

    def test_unknown_still_counts_as_settled_for_detectors(self):
        """CONTINUITY-2D policy: inventing incompleteness would delete real
        structure. Unchanged."""
        from market_data.snapshot_builder import _bucket_is_settled
        s = [{"timestamp": "2026-08-12T19:00:00+00:00"}]     # no `complete` key
        assert _bucket_is_settled(s, s[0]) is True

    def test_the_compact_code_distinguishes_I_from_F(self):
        rows = _compact_path([
            {"timestamp": "2026-08-11T15:00:00+00:00", "open": 1, "high": 2,
             "low": 1, "close": 1, "volume": 1,
             "temporal_status": "historical_incomplete"},
            {"timestamp": "2026-08-12T19:30:00+00:00", "open": 1, "high": 2,
             "low": 1, "close": 1, "volume": 1, "temporal_status": "forming"}], 5)
        assert rows[0][6] == "I" and rows[1][6] == "F"

    def test_at_most_one_live_bucket_per_timeframe_on_the_real_tape(self):
        mk = _brain_at(19, 43)["market"]["candles"]
        for tf in ("1m", "3m", "5m", "15m"):
            forming = [r for r in mk[tf]["path"] if r[6] == "F"]
            assert len(forming) <= 1, (tf, len(forming))
            if forming:
                assert forming[0] is mk[tf]["path"][-1], tf

    def test_the_legend_explains_the_difference(self):
        legend = _brain_at(19, 43)["market"]["price_path_legend"]
        assert "forming now" in legend and "INCOMPLETE" in legend


class TestEyesightIsNeutral:
    """§8 — the trader's vision may not change because mechanics changed its mind."""

    def test_mechanical_opinion_cannot_alter_the_raw_window(self):
        bars = _canonical_bars()
        cut = datetime(2026, 8, 12, 19, 43, tzinfo=timezone.utc)
        kept = [b for b in bars if datetime.fromisoformat(b["timestamp"]) <= cut]
        if len(kept) < 200:
            pytest.skip("insufficient archived history")
        base = build_snapshot(build_timeframes(kept), symbol="MNQ")

        a, b = copy.deepcopy(base), copy.deepcopy(base)
        a["qualification"] = {"status": "elite"}
        a["playbook"] = {"selected_playbook": "trend_continuation", "direction": "bullish"}
        b["qualification"] = {"status": "no_trade"}
        b["playbook"] = {"selected_playbook": "no_playbook", "direction": "neutral"}

        ca = build_brain_input(a, {})["market"]["candles"]
        cb = build_brain_input(b, {})["market"]["candles"]
        for tf in ("1m", "3m", "5m", "15m"):
            assert ca[tf]["path"] == cb[tf]["path"], tf
