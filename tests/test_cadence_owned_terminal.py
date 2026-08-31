"""STEP 4B.12 §9 — the expected terminal constituent belongs to the cadence.

`snapshot_builder` computed it as `bucket_start + N - 1` minutes. That is nominal
arithmetic asserting a schedule: it claims the venue was scheduled to print at
that minute, which only `venue_calendar` can answer.

The failure it invites is the mirror image of the defect this whole step exists
to remove. A bucket whose nominal last minute falls inside a scheduled closure
is COMPLETE, and the arithmetic would report its CLOSE unprovable -- a scheduled
closure masquerading as a missing observation.

MEASURED across the whole verified ordinary range (2026-08-01..2026-08-31), for
every ALIGNED bucket:

    tf    cadence==nominal   DIFFER   fully-closed   unknown
     1m             28785         0          15615       240
     3m              9595         0           5205        80
     5m              5757         0           3123        48
    15m              1919         0           1041        16

Zero differences -- because every CME boundary in scope (16:15, 16:30, 17:00,
18:00 ET) is a multiple of fifteen minutes and therefore never bisects an
aligned bucket. So the nominal answer was CORRECT in current scope; it was
simply not ENTITLED to be. The equivalence is proven here rather than assumed,
and the arithmetic is not promoted to universal authority.

(The `unknown` column is honest, not a defect: 00:00-03:59 UTC on 2026-08-01 is
2026-07-31 in Eastern, which lies outside the verified range.)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed.timeframe_builder import build_timeframes            # noqa: E402
from market_data.snapshot_builder import _previous_slot_close       # noqa: E402
from market_data.venue_calendar import (                            # noqa: E402
    CADENCE_OWNED, NOMINAL_UNDER_UNKNOWN_SCHEDULE, NO_EXPECTED_CONSTITUENT,
    expected_terminal_constituent)
from structure.liquidity_engine import PRIOR_AUTHORITATIVE          # noqa: E402


class TestTheCadenceCanDisagreeWithTheArithmetic:
    """Proven FIRST. An equivalence result means nothing if the two things being
    compared could never differ -- that would make the whole §9 table a
    tautology rather than a measurement."""

    def test_a_bucket_straddling_the_halt_ends_before_the_nominal_minute(self):
        # 16:15-16:30 ET is 20:15-20:30 UTC. A 15-minute span opening at 20:10Z
        # is scheduled to print only through 20:14Z.
        spec = expected_terminal_constituent("2026-08-12T20:10:00+00:00", 15)
        assert spec["basis"] == CADENCE_OWNED
        assert spec["terminal"] == "2026-08-12T20:14:00+00:00"
        nominal = "2026-08-12T20:24:00+00:00"
        assert spec["terminal"] != nominal, \
            "cadence and arithmetic cannot differ; the equivalence proof is vacuous"

    def test_a_fully_closed_span_expects_no_constituent_at_all(self):
        spec = expected_terminal_constituent("2026-08-12T20:15:00+00:00", 15)
        assert spec["basis"] == NO_EXPECTED_CONSTITUENT
        assert spec["terminal"] is None


class TestAlignedBucketsAgreeInCurrentScope:

    def test_no_aligned_bucket_in_the_verified_range_disagrees(self):
        """The §9 equivalence claim, re-measured. Sampled over one full verified
        week rather than the month to keep the suite quick; the month-wide run is
        recorded in this module's docstring."""
        start = datetime(2026, 8, 10, tzinfo=timezone.utc)
        end = datetime(2026, 8, 17, tzinfo=timezone.utc)
        for tf in (1, 3, 5, 15):
            owned = differing = 0
            probe = start
            while probe < end:
                if (probe.hour * 60 + probe.minute) % tf == 0:
                    spec = expected_terminal_constituent(probe.isoformat(), tf)
                    if spec["basis"] == CADENCE_OWNED:
                        owned += 1
                        nominal = (probe + timedelta(minutes=tf - 1)).isoformat()
                        differing += spec["terminal"] != nominal
                probe += timedelta(minutes=tf)
            assert owned > 0, f"{tf}m sample contained no cadence-owned bucket"
            assert differing == 0, \
                f"{tf}m: nominal arithmetic disagrees with the cadence in scope"


class TestUnknownScheduleStaysUnknown:
    """`is_expected` answers False for a SPECIAL_SCHEDULE_UNKNOWN date, so a
    two-valued implementation would declare every bucket outside the verified
    ranges to have no expected terminal and withhold the world.
    `_crosses_forbidden_boundary` already made exactly that mistake in the FVG
    work and killed every gap outside verified August."""

    def test_an_unverified_date_falls_back_to_nominal_and_says_so(self):
        spec = expected_terminal_constituent("2027-02-01T18:00:00+00:00", 5)
        assert spec["basis"] == NOMINAL_UNDER_UNKNOWN_SCHEDULE
        assert spec["terminal"] == "2027-02-01T18:04:00+00:00"

    def test_unknown_is_never_treated_as_closed(self):
        spec = expected_terminal_constituent("2027-02-01T18:00:00+00:00", 5)
        assert spec["basis"] != NO_EXPECTED_CONSTITUENT
        assert spec["terminal"] is not None, \
            "an unverified schedule was read as a scheduled closure"


class TestTheBasisTravelsWithTheVerdict:
    """PROVEN under a known schedule and PROVEN under nominal arithmetic are not
    the same strength of claim. A consumer that cannot tell them apart cannot
    audit this later."""

    def bars(self, day="2026-08-12"):
        out = []
        for k in range(15):
            h, m = 18, k
            out.append({"timestamp": f"{day}T{h:02d}:{m:02d}:00+00:00",
                        "open": 100.0 + k, "high": 101.0 + k, "low": 99.0 + k,
                        "close": 100.5 + k, "volume": 10})
        return out

    def slot(self, day):
        raw = build_timeframes(self.bars(day))["5m"]
        return _previous_slot_close([raw[0], raw[-1]], raw, 5)

    def test_a_verified_date_reports_cadence_ownership(self):
        out = self.slot("2026-08-12")
        assert out["authority"] == PRIOR_AUTHORITATIVE
        assert out["terminal_basis"] == CADENCE_OWNED

    def test_an_unverified_date_never_reaches_the_terminal_question(self):
        """§9 RESIDUE, discovered here and repaired at the authority boundary.

        This test was first written expecting NOMINAL_UNDER_UNKNOWN_SCHEDULE and
        MEASURED ADJACENT_SETTLED instead: `expected_buckets` calls
        `is_expected`, which is False for every minute of an unverified date, so
        the missing-slot detector could never fire and the array neighbour was
        ASSERTED to be the previous market slot without evidence. Silence from an
        authority with no jurisdiction had become proof of absence.

        The resolver now asks `cadence_authority_over` FIRST, so the unverified
        case is refused before the terminal question is ever reached -- which is
        why `terminal_basis` is still absent, for a completely different reason
        than when this test was written.
        """
        from structure.liquidity_engine import PRIOR_CADENCE_UNKNOWN
        out = self.slot("2027-02-01")
        assert out["authority"] == PRIOR_CADENCE_UNKNOWN
        assert "close" not in out, "a close was published without cadence authority"
        assert "terminal_basis" not in out, \
            "the terminal question was answered on a path that never asks it"

    def test_an_unprovable_close_also_carries_its_basis(self):
        bars = [b for b in self.bars() if b["timestamp"] != "2026-08-12T18:09:00+00:00"]
        raw = build_timeframes(bars)["5m"]
        out = _previous_slot_close([raw[0], raw[-1]], raw, 5)
        assert out["authority"] != PRIOR_AUTHORITATIVE
        assert out["terminal_basis"] == CADENCE_OWNED
