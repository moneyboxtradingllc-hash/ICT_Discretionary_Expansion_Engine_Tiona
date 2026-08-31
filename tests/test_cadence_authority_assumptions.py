"""STEP 4B.12 — the assumptions the cadence repair rests on.

A comment is not a guard: these are exactly the facts that get changed months
later by someone with a good reason, silently resurrecting synthetic adjacency.

    A. ASSUMPTION A IS RETIRED (VENUE-CALENDAR-AUTHORITY-HORIZON-1, 2026-08-30).
       `cadence_authority_over` used to check only the ENDPOINTS of a span, which
       was sound only while the verified ordinary ranges were contiguous and
       convex. Extending ordinary authority to 2026-12-31 crosses the Labor Day,
       Thanksgiving, Christmas and New Year windows, so the ranges now contain
       DELIBERATE HOLES and convexity is gone. The old theorem was not weakened;
       the world it described stopped being true, and the source said in advance
       what to do when it did.

           OLD   known endpoints are enough, because authority has no holes
           NEW   inspect the interior

       What replaces it is stronger, not weaker: an unverified or special date
       BETWEEN two verified ones can no longer hide behind them.

    B. `allow_uncadenced=True` is a loaded gun, retained for one caller that is
       currently proven noncanonical. UNCHANGED.

If either surviving assumption stops holding, these tests must fail loudly
rather than let the engine keep believing them.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import market_data.venue_calendar as VC                             # noqa: E402


def _d(s):
    return date.fromisoformat(s)


class TestTheVerifiedRangesAreCutCorrectly:
    """The ranges are no longer required to be CONTIGUOUS -- holes are now the
    design. What they must still be is HONEST: every span must contain only
    genuinely ordinary dates, and every hole between spans must be occupied by
    the special window that caused it.

    These two survive from the old assumption class because their theorems are
    still true and now carry more weight: they are what proves the holes were
    cut around real holidays rather than drawn arbitrarily."""

    def test_no_special_schedule_date_hides_inside_a_verified_range(self):
        """A holiday inside an ordinary span would be claimed as ordinary by
        every consumer that trusts the range. `calendar_authority` checks
        SPECIAL_SCHEDULE_DATES first so the DATE still answers KNOWN_SPECIAL --
        but the span would be lying, and `expected_buckets` would be asked to
        count slots on a day whose hours are unknown."""
        for lo, hi in VC.VERIFIED_ORDINARY_RANGES:
            for day in VC.SPECIAL_SCHEDULE_DATES:
                assert not (lo <= day <= hi), (
                    f"{day} ({VC.SPECIAL_SCHEDULE_DATES[day]}) sits inside the "
                    f"verified range {lo}..{hi}. Endpoint checking now "
                    f"overclaims CADENCE_KNOWN across it; "
                    f"`cadence_authority_over` must become an interior scan.")

    def test_every_date_inside_a_verified_range_really_is_known_ordinary(self):
        """Measured rather than argued: walk the actual dates."""
        checked = 0
        for lo, hi in VC.VERIFIED_ORDINARY_RANGES:
            day = _d(lo)
            while day <= _d(hi):
                assert VC.calendar_authority(f"{day.isoformat()}T12:00:00-04:00") \
                    == "KNOWN_ORDINARY", f"{day} breaks convexity"
                checked += 1
                day += timedelta(days=1)
        assert checked > 0, "no verified range to check; this test is vacuous"

    def test_every_hole_between_ranges_is_occupied_by_a_special_window(self):
        """RETIRED THEOREM, REPLACED. This used to demand the ranges be
        CONTIGUOUS, because a gap was a place the endpoint shortcut could not
        see. The interior scan sees it now, so gaps are legal -- but only where a
        holiday actually put one. A hole over ordinary trading days would be
        authority silently thrown away."""
        spans = sorted((_d(lo), _d(hi)) for lo, hi in VC.VERIFIED_ORDINARY_RANGES)
        for (_, prev_hi), (next_lo, _) in zip(spans, spans[1:]):
            day = prev_hi + timedelta(days=1)
            while day < next_lo:
                assert day.isoformat() in VC.SPECIAL_SCHEDULE_DATES, (
                    f"{day} sits in a hole between verified ranges "
                    f"{prev_hi}..{next_lo} but is not a known special date. "
                    f"Either it is ordinary and the ranges should cover it, or "
                    f"it is special and SPECIAL_SCHEDULE_DATES should say so.")
                day += timedelta(days=1)


class TestTheInteriorScanIsLoadBearing:
    """A guard that would pass under a broken configuration guards nothing.

    The old version of this class proved the ENDPOINT shortcut really did
    overclaim, which justified the convexity guards. The shortcut is gone, so
    the proof obligation inverts: prove the interior scan really does CATCH what
    endpoints missed. Same purpose, opposite direction."""

    def test_an_unverified_interior_date_is_caught(self):
        original = VC.VERIFIED_ORDINARY_RANGES
        # August verified, October verified, September deliberately NOT --
        # the exact configuration the endpoint shortcut used to wave through.
        VC.VERIFIED_ORDINARY_RANGES = (("2026-08-01", "2026-08-31"),
                                       ("2026-10-01", "2026-10-31"))
        try:
            verdict = VC.cadence_authority_over("2026-08-20T12:00:00-04:00",
                                                "2026-10-05T12:00:00-04:00")
        finally:
            VC.VERIFIED_ORDINARY_RANGES = original
        assert verdict["authority"] == VC.CADENCE_UNKNOWN, (
            "endpoint checking has come back: a span whose ends are verified and "
            "whose middle is not must never answer CADENCE_KNOWN")
        assert verdict.get("unknown_date", "").startswith("2026-09")

    def test_a_special_interior_date_is_caught(self):
        """The live case, with the real configuration: Labor Day sits between
        two ordinary spans and the span across it must not be known."""
        verdict = VC.cadence_authority_over("2026-09-04T12:00:00-04:00",
                                            "2026-09-10T12:00:00-04:00")
        assert verdict["authority"] == VC.CADENCE_UNKNOWN
        assert verdict.get("unknown_date") in VC.SPECIAL_SCHEDULE_DATES

    def test_a_clean_span_is_still_known(self):
        """Non-vacuity: the scan must not simply refuse everything."""
        assert VC.cadence_authority_over(
            "2026-09-09T12:00:00-04:00",
            "2026-09-30T12:00:00-04:00")["authority"] == VC.CADENCE_KNOWN

    def test_the_real_configuration_is_restored(self):
        assert VC.VERIFIED_ORDINARY_RANGES == (
            ("2026-08-01", "2026-09-05"),
            ("2026-09-09", "2026-11-25"),
            ("2026-11-29", "2026-12-23"),
            ("2026-12-27", "2026-12-30"),
        )


class TestTheLegacyBridgeIsQuarantinedFromProduction:
    """ASSUMPTION B. `analyze_liquidity(..., allow_uncadenced=True)` reinstates
    exactly the synthetic adjacency the production path now refuses. It is
    tolerable only while its single caller is unreachable from production.

    Proven by import graph rather than by memory: today NO file under `src/`
    imports `market_events`. If one ever does, this fails instead of silently
    resurrecting the bridge.
    """

    def src_files(self):
        for root, _dirs, files in os.walk(SRC):
            if "__pycache__" in root:
                continue
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(root, name)

    def test_only_market_events_opts_into_the_bridge(self):
        """AST, not text search. The first version of this test grepped for
        `allow_uncadenced=True` and flagged `toolbox/price_levels.py`, which
        merely NAMES the flag inside the error message that teaches a caller how
        to request raw array geometry. A guard that cannot tell a call from a
        sentence about a call produces false alarms, and a false alarm on a
        safety test is how the test gets weakened later."""
        import ast
        callers = []
        for path in self.src_files():
            with open(path, encoding="utf-8") as fh:
                try:
                    tree = ast.parse(fh.read())
                except SyntaxError:                      # not our concern here
                    continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if (kw.arg == "allow_uncadenced"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True):
                        callers.append(
                            os.path.relpath(path, SRC).replace("\\", "/"))
        assert sorted(set(callers)) == ["market_data/market_events.py"], (
            f"unexpected uncadenced opt-in: {sorted(set(callers))}. Bridging to "
            f"the array neighbour must be requested out loud by a caller proven "
            f"noncanonical, never inherited.")

    def test_no_production_module_imports_market_events(self):
        importers = []
        for path in self.src_files():
            rel = os.path.relpath(path, SRC).replace("\\", "/")
            if rel == "market_data/market_events.py":
                continue
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            if re.search(r"^\s*(from\s+\S*market_events|import\s+\S*market_events)",
                         body, re.M):
                importers.append(rel)
        assert importers == [], (
            f"{importers} now import market_events, whose `_sweep_at` authors "
            f"sweeps from a bridged array-neighbour close. Either remove the "
            f"dependency or give that caller real cadence -- do not update this "
            f"test to accept it.")

    def test_the_bridge_still_changes_the_answer(self):
        """Non-vacuity: if `allow_uncadenced` stopped mattering, the quarantine
        above would be guarding nothing."""
        from structure.liquidity_engine import analyze_liquidity
        candles = [{"open": 80, "high": 85, "low": 79, "close": 84, "volume": 1},
                   {"open": 84, "high": 92, "low": 83, "close": 91, "volume": 1},
                   {"open": 91, "high": 100, "low": 90, "close": 99, "volume": 1},
                   {"open": 99, "high": 96, "low": 88, "close": 89, "volume": 1},
                   {"open": 89, "high": 92, "low": 86, "close": 87, "volume": 1},
                   {"open": 87, "high": 94, "low": 86, "close": 93, "volume": 1},
                   {"open": 93, "high": 95, "low": 92, "close": 94, "volume": 1},
                   {"open": 94, "high": 103, "low": 93, "close": 96, "volume": 1}]
        assert analyze_liquidity(candles)["sweep_detected"] is False
        assert analyze_liquidity(candles, allow_uncadenced=True)["sweep_detected"] is True
