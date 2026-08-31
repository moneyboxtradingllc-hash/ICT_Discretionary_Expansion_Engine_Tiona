"""STEP 4B.12 §8 — one instant, one source-member identity.

`timeframe_builder` published `str(timestamp)` as source-member provenance and
every consumer compared those raw strings. So

    2026-08-12T18:14:00+00:00
    2026-08-12T14:14:00-04:00

-- the same minute of the same session, one written in UTC and one in Eastern --
were two different source-member identities. A terminal-constituent lookup
across that boundary reports the CLOSE unprovable for a bucket whose terminal
minute is present, and the previous-slot lookup reports NOT_OBSERVED for a slot
that was observed.

"Identity is answered by identity" is only true when the identity is canonical.
Absence must be real absence and not a spelling mismatch.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed.timeframe_builder import build_timeframes            # noqa: E402
from market_data.object_identity import canonical_instant           # noqa: E402
from market_data.snapshot_builder import (                          # noqa: E402
    _previous_slot_close, _terminal_constituent_observed)
from structure.liquidity_engine import (                            # noqa: E402
    PRIOR_AUTHORITATIVE, PRIOR_CLOSE_UNPROVEN, PRIOR_NO_OBSERVATION)


def minute(stamp, price=100.0):
    return {"timestamp": stamp, "open": price, "high": price + 1,
            "low": price - 1, "close": price, "volume": 10}


def utc_minutes(start_h, start_m, count):
    return [minute(f"2026-08-12T{start_h:02d}:{(start_m + k):02d}:00+00:00",
                   100.0 + k) for k in range(count)]


def eastern_minutes(start_h, start_m, count):
    """The same instants, written with a -04:00 offset."""
    return [minute(f"2026-08-12T{(start_h - 4):02d}:{(start_m + k):02d}:00-04:00",
                   100.0 + k) for k in range(count)]


class TestThePublishedProvenanceIsCanonical:

    def test_equivalent_offsets_produce_one_membership(self):
        utc = build_timeframes(utc_minutes(18, 0, 5))["5m"][0]
        eastern = build_timeframes(eastern_minutes(18, 0, 5))["5m"][0]
        assert utc["source_member_times"] == eastern["source_member_times"], \
            "the same five minutes produced two different source identities"

    def test_order_is_preserved(self):
        """This is a SEQUENCE: `close` is taken from bars[-1], so the terminal
        constituent is positional. Canonicalising must not sort or dedupe."""
        members = build_timeframes(utc_minutes(18, 0, 5))["5m"][0]["source_member_times"]
        assert list(members) == sorted(members)
        assert members[-1] == canonical_instant("2026-08-12T18:04:00+00:00")
        assert len(members) == 5

    def test_an_unparseable_stamp_never_reaches_provenance_at_all(self):
        """Measured, not assumed. The first version of this test asserted that
        an unparseable stamp survives into `source_member_times` in raw form --
        it cannot: `_floor_timestamp` raises while BUCKETING, long before
        provenance is published. The canonicaliser is therefore never the thing
        standing between junk and an identity here."""
        import pytest
        with pytest.raises(ValueError):
            build_timeframes(utc_minutes(18, 0, 4) + [minute("not-a-timestamp")])

    def test_a_naive_stamp_stays_visible_rather_than_becoming_canonical(self):
        """Naive stamps DO survive bucketing, and `canonical_instant` is called
        with strict=False so they keep their raw form. Naive-means-UTC is not a
        proven producer contract, so an ambiguous instant must not be dressed up
        as a canonical one -- it simply fails to match, which is honest."""
        bars = [minute(f"2026-08-12T18:0{k}:00") for k in range(5)]
        members = build_timeframes(bars)["5m"][0]["source_member_times"]
        assert "2026-08-12T18:04:00" in members
        assert not any(m.endswith("+00:00") for m in members)
        bucket = build_timeframes(bars)["5m"][0]
        assert _terminal_constituent_observed(
            bucket, "2026-08-12T18:04:00+00:00") is False, \
            "a naive stamp was silently accepted as a UTC instant"


class TestTerminalConstituentIdentityCrossesOffsets:

    def test_a_terminal_written_in_eastern_is_still_found(self):
        bucket = build_timeframes(utc_minutes(18, 0, 5))["5m"][0]
        assert _terminal_constituent_observed(
            bucket, "2026-08-12T14:04:00-04:00") is True, \
            "the terminal minute was present and reported unobserved"

    def test_it_still_refuses_when_the_terminal_is_genuinely_absent(self):
        """The repair must not turn into a rubber stamp: a canonical comparison
        that matched anything would be worse than the string one it replaced."""
        bars = utc_minutes(18, 0, 4)            # 18:00..18:03, terminal 18:04 absent
        bucket = build_timeframes(bars)["5m"][0]
        assert _terminal_constituent_observed(
            bucket, "2026-08-12T18:04:00+00:00") is False
        assert _terminal_constituent_observed(
            bucket, "2026-08-12T14:04:00-04:00") is False

    def test_provenance_absent_is_still_unprovable(self):
        assert _terminal_constituent_observed({}, "2026-08-12T18:04:00+00:00") is False


class TestThePreviousSlotLookupCrossesOffsets:
    """The bucket lookup carried the SAME defect one line earlier than the
    terminal lookup, and was easy to miss because both are single-line string
    comparisons that look obviously correct."""

    def series(self, bars):
        raw = build_timeframes(bars)["5m"]
        return raw, [b for b in raw if b.get("complete")]

    def test_an_observed_previous_slot_is_not_reported_missing(self):
        # 18:00-18:04, 18:05-18:09, 18:10-18:14 -- three complete 5m buckets,
        # written in EASTERN while `expected_buckets` answers in UTC.
        bars = eastern_minutes(18, 0, 15)
        raw, settled = self.series(bars)
        # drop the middle bucket from the SETTLED view only: the slot exists and
        # was observed, it is simply not the array neighbour.
        settled = [settled[0], settled[-1]]
        out = _previous_slot_close(settled, raw, 5)
        assert out["authority"] != PRIOR_NO_OBSERVATION, \
            "an observed previous slot was reported unobserved by spelling alone"
        assert out["authority"] == PRIOR_AUTHORITATIVE
        assert out["close"] is not None

    def test_a_genuinely_unobserved_slot_is_still_reported_missing(self):
        bars = utc_minutes(18, 0, 5) + utc_minutes(18, 10, 5)   # 18:05 slot absent
        raw, settled = self.series(bars)
        out = _previous_slot_close(settled, raw, 5)
        assert out["authority"] == PRIOR_NO_OBSERVATION

    def test_a_present_slot_with_an_absent_terminal_is_close_unproven(self):
        """Interior-missing and terminal-missing are indistinguishable by count
        and opposite in CLOSE authority -- the whole reason provenance exists."""
        bars = (utc_minutes(18, 0, 5)
                + utc_minutes(18, 5, 4)          # 18:09 terminal absent
                + utc_minutes(18, 10, 5))
        raw = build_timeframes(bars)["5m"]
        settled = [raw[0], raw[-1]]
        out = _previous_slot_close(settled, raw, 5)
        assert out["authority"] == PRIOR_CLOSE_UNPROVEN
        assert "close" not in out, "an unprovable close was published anyway"

    def test_an_interior_gap_still_leaves_the_close_authoritative(self):
        bars = (utc_minutes(18, 0, 5)
                + [minute("2026-08-12T18:05:00+00:00")]      # 18:06-18:08 absent
                + [minute("2026-08-12T18:09:00+00:00")]      # terminal PRESENT
                + utc_minutes(18, 10, 5))
        raw = build_timeframes(bars)["5m"]
        settled = [raw[0], raw[-1]]
        out = _previous_slot_close(settled, raw, 5)
        assert out["authority"] == PRIOR_AUTHORITATIVE, \
            "a degraded candle was treated as a degraded CLOSE field"
