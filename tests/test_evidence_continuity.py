"""STEP 2E — evidence continuity. Was there supposed to be a bar in between?

Per-bar S/F/I/U describes the observations that EXIST. Real swing provenance
showed that is not the whole story:

    swing_high:15m:2026-08-10T14:15:00+00:00:29900.0
    7 "confirming" observations spanning 70 HOURS
    gap 08-07 17:00 -> 08-10 13:30   4110 min, 77 missing buckets
    gap 08-10 13:30 -> 08-10 14:00     30 min,  1 missing bucket

(77, not the 273 a crude timestamp count gave: the Friday-close-to-Sunday-open
weekly closure is correctly excluded once the venue calendar answers instead of
a strategy session label.)

Every bar in it was `settled`. Ten of twenty-three 15m swings rest on
non-contiguous evidence.

Two orthogonal axes: what the bars are worth, and whether bars are missing
between them. Neither may erase the other.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from market_data.evidence_continuity import (                        # noqa: E402
    CONTIGUOUS, EXPECTED_MARKET_BREAK, VENUE_OPEN_OBSERVATION_ABSENT, MIXED,
    UNKNOWN_CADENCE, evaluate)


def stamps(*hhmm, day=12, month=8):
    return [f"2026-{month:02d}-{day:02d}T{h}:00+00:00" for h in hhmm]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheTwoAxesAreIndependent:

    def test_a_contiguous_series_is_contiguous(self):
        r = evaluate(stamps("19:00", "19:01", "19:02"), "1m")
        assert r["continuity_class"] == CONTIGUOUS
        assert r["gaps"] == []

    def test_all_settled_bars_can_still_be_non_contiguous(self):
        """The whole point of the step: temporal quality does not prove
        adjacency."""
        bars = [{"timestamp": s, "temporal_status": "settled"}
                for s in stamps("19:00", "19:01", "19:19")]
        assert evaluate(bars, "1m")["continuity_class"] != CONTIGUOUS

    def test_observation_count_and_elapsed_time_are_both_published(self):
        """Observation count may never masquerade as elapsed market time."""
        r = evaluate(stamps("19:00", "19:01", "19:19"), "1m")
        assert r["observation_count"] == 3
        assert r["elapsed_minutes"] == 19.0


# ══════════════════════════════════════════════════════════════════════════════
class TestGapsAreClassifiedNotGuessed:

    def test_a_mid_session_hole_is_VENUE_OPEN_ABSENCE(self):
        """Survived the first implementation. A fixed 30-minute probe stride ran
        ZERO probes on any gap shorter than 30 minutes, so a hole in the middle
        of the afternoon session was reported as an expected market break.

        Renamed from `..._is_MISSING_DATA`: the venue schedule proves trading
        COULD occur, not that the provider must emit a candle. ProjectX does not
        document the zero-trade case, so absence is reported as absence."""
        r = evaluate(stamps("19:00", "19:19"), "1m")       # 15:00-15:19 ET
        assert r["continuity_class"] == VENUE_OPEN_OBSERVATION_ABSENT
        assert "no observation" in r["gaps"][0]["rule"]
        assert "undocumented" in r["gaps"][0]["rule"]

    def test_the_gap_reports_how_many_buckets_are_missing(self):
        g = evaluate(stamps("19:00", "19:19"), "1m")["gaps"][0]
        assert g["missing_expected_buckets"] == 18
        assert g["gap_minutes"] == 19.0

    def test_every_gap_names_the_rule_that_classified_it(self):
        for series in (stamps("19:00", "19:19"), stamps("19:00", "23:30")):
            for g in evaluate(series, "1m")["gaps"]:
                assert g["rule"], "a classification without a stated rule is a guess"

    def test_the_weekly_closure_is_an_expected_break(self):
        """Saturday 08:00 ET -> Sunday 08:00 ET: entirely between the Friday
        17:00 ET close and the Sunday 18:00 ET open, so no bucket was ever
        expected. Rewritten from a `session_engine` weekend-probe assertion once
        the venue calendar replaced it."""
        r = evaluate(["2026-08-08T12:00:00+00:00", "2026-08-09T12:00:00+00:00"], "15m")
        assert r["continuity_class"] == EXPECTED_MARKET_BREAK
        assert r["gaps"][0]["missing_expected_buckets"] == 0
        assert "weekly_market_closed" in r["gaps"][0]["rule"]

    def test_unusable_timestamps_report_unknown_not_contiguous(self):
        assert evaluate(["not-a-time"], "1m")["continuity_class"] == UNKNOWN_CADENCE
        assert evaluate([], "1m")["continuity_class"] == UNKNOWN_CADENCE

    def test_simultaneous_conditions_are_preserved(self):
        """A genuinely mixed window: one gap is a scheduled venue halt, the other
        is real missing data. Both facts must survive.

        The first version paired two gaps that BOTH resolved to missing data once
        exact bucket counting replaced the session probe, so it no longer
        exercised MIXED at all -- it was passing for the wrong reason.
        """
        series = ["2026-08-12T20:59:00+00:00",   # 16:59 ET, last bar before halt
                  "2026-08-12T22:00:00+00:00",   # 18:00 ET, reopen — nothing skipped
                  "2026-08-12T22:20:00+00:00"]   # 18:20 ET, 19 buckets absent
        r = evaluate(series, "1m")
        assert r["continuity_class"] == MIXED
        assert set(r["continuity_issues"]) == {EXPECTED_MARKET_BREAK,
                                               VENUE_OPEN_OBSERVATION_ABSENT}


# ══════════════════════════════════════════════════════════════════════════════
class TestNoFabrication:

    def test_it_never_synthesises_bars(self):
        import inspect
        from market_data import evidence_continuity as EC
        body = inspect.getsource(EC)
        for banned in ("interpolat", "synthes", "backfill", "fill_missing"):
            assert banned not in body.lower().split('"""')[-1], banned

    def test_missing_is_reported_not_repaired(self):
        r = evaluate(stamps("19:00", "19:19"), "1m")
        assert r["observation_count"] == 2, "no bar was invented to close the gap"
        assert r["gaps"][0]["missing_expected_buckets"] > 0


# ══════════════════════════════════════════════════════════════════════════════
class TestEventsCarryContinuity:

    def _events(self):
        import json
        from datetime import datetime, timezone
        store = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "market_data", "topstepx", "CON_F_US_MNQ_U26.jsonl")
        if not os.path.exists(store):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(store, encoding="utf-8") if l.strip()]
        cut = datetime(2026, 8, 12, 19, 43, tzinfo=timezone.utc)
        kept = [b for b in rows if datetime.fromisoformat(b["timestamp"]) <= cut]
        if len(kept) < 200:
            pytest.skip("insufficient archived history")
        from data_feed.timeframe_builder import build_timeframes
        from market_data.market_events import reconstruct_all
        tfs = build_timeframes(kept)
        # STEP 3F: aggregated bars lose the store's `contract` field
        # (`_aggregate` rebuilds a bar from OHLCV alone), so the caller supplies
        # it. That is the boundary where identity is minted, and it is meant to
        # be explicit there rather than defaulted underneath.
        events = reconstruct_all({k: tfs[k] for k in ("1m", "3m", "5m", "15m")},
                                 lookback_bars={"1m": 90, "3m": 60, "5m": 80, "15m": 32},
                                 contract="CON.F.US.MNQ.U26")
        assert events
        return events

    def test_every_event_publishes_its_source_continuity(self):
        for e in self._events():
            assert e["source_continuity_class"]
            assert "source_observation_count" in e
            assert "source_elapsed_minutes" in e

    def test_structural_events_expose_their_LEVEL_continuity(self):
        seen = 0
        for e in self._events():
            if e["event_type"] in ("BOS", "MSS"):
                seen += 1
                assert e["level_source_continuity_class"]
        assert seen

    def test_the_real_tape_contains_non_contiguous_structural_evidence(self):
        """Not a synthetic worry: measured, 3 of 23 structural events rest on a
        level whose confirming bars span hours with missing intervals."""
        bad = [e for e in self._events()
               if e["event_type"] in ("BOS", "MSS")
               and e["source_continuity_class"] != CONTIGUOUS]
        assert bad, "expected the archived tape to exercise this"
        for e in bad:
            assert e["source_elapsed_minutes"] > 60


# ══════════════════════════════════════════════════════════════════════════════
class TestVenueCadenceAuthority:
    """STEP 2E.1. A session label is not an exchange calendar.

    `session_engine` labels ~04:00-20:00 ET for STRATEGY purposes. Using it to
    decide whether an MNQ bar should exist was wrong in BOTH directions, and both
    are pinned here. Schedule verified against CME Group: MNQ trades Sunday 18:00
    ET through Friday 17:00 ET with daily maintenance 17:00-18:00 ET.
    """

    def test_weekday_overnight_is_TRADING_not_closed(self):
        """22:00 ET on a weekday. `session_engine` says "closed"; MNQ trades."""
        from market_data.venue_calendar import TRADING_OPEN, classify
        assert classify("2026-08-12T02:00:00+00:00")["class"] == TRADING_OPEN

    def test_missing_overnight_bars_are_MISSING_not_excused(self):
        r = evaluate(["2026-08-12T02:00:00+00:00", "2026-08-12T02:19:00+00:00"], "1m")
        assert r["continuity_class"] == VENUE_OPEN_OBSERVATION_ABSENT
        assert r["gaps"][0]["missing_expected_buckets"] == 18

    def test_daily_maintenance_is_a_scheduled_halt(self):
        """17:00-18:00 ET. `session_engine` calls it after_hours; CME halts."""
        from market_data.venue_calendar import SCHEDULED_DAILY_MAINTENANCE, classify
        assert classify("2026-08-12T21:30:00+00:00")["class"] == SCHEDULED_DAILY_MAINTENANCE

    def test_maintenance_does_not_manufacture_missing_bars(self):
        r = evaluate(["2026-08-12T20:59:00+00:00", "2026-08-12T22:00:00+00:00"], "1m")
        assert r["continuity_class"] == EXPECTED_MARKET_BREAK
        assert r["gaps"][0]["missing_expected_buckets"] == 0

    def test_friday_close_and_sunday_reopen(self):
        from market_data.venue_calendar import (TRADING_OPEN, WEEKLY_MARKET_CLOSED,
                                                classify)
        assert classify("2026-08-07T20:59:00+00:00")["class"] == TRADING_OPEN
        assert classify("2026-08-07T21:30:00+00:00")["class"] == WEEKLY_MARKET_CLOSED
        assert classify("2026-08-09T21:00:00+00:00")["class"] == WEEKLY_MARKET_CLOSED
        assert classify("2026-08-09T23:00:00+00:00")["class"] == TRADING_OPEN

    def test_sunday_after_reopen_expects_bars(self):
        r = evaluate(["2026-08-09T22:00:00+00:00", "2026-08-09T22:20:00+00:00"], "1m")
        assert r["continuity_class"] == VENUE_OPEN_OBSERVATION_ABSENT

    def test_holidays_are_not_assumed_to_follow_ordinary_hours(self):
        from market_data.venue_calendar import SPECIAL_SCHEDULE_AUTHORITY_MISSING
        assert SPECIAL_SCHEDULE_AUTHORITY_MISSING is True

    def test_an_unsupported_instrument_reports_unknown(self):
        from market_data.venue_calendar import SPECIAL_SCHEDULE_UNKNOWN, classify
        assert classify("2026-08-12T19:00:00+00:00", "ES")["class"] == SPECIAL_SCHEDULE_UNKNOWN

    def test_bucket_alignment_matches_the_timeframe_builder(self):
        """A cadence checker expecting a bucket the builder could never emit is
        worse than no checker."""
        from market_data.venue_calendar import expected_buckets
        got = expected_buckets("2026-08-12T18:00:00+00:00",
                               "2026-08-12T19:00:00+00:00", 15)
        assert all(b.minute % 15 == 0 and b.second == 0 for b in got)

    def test_strategy_session_labels_are_untouched(self):
        """Jurisdictions stay separate: the venue calendar answers 'should a bar
        exist', never 'should the bot trade'."""
        from market_data.session_engine import get_session_label
        assert get_session_label("2026-08-12T13:45:00+00:00") == "ny_open"
        assert get_session_label("2026-08-12T02:00:00+00:00") == "closed"


class TestFvgAdjacencyWasNotAlreadySolved:
    """Retraction, pinned.

    An earlier report claimed `find_fvgs` already guaranteed adjacency because of
    `_bar_span_tolerance`. It does not: that guard needs at least three deltas to
    activate, so on a bare three-candle window it returns None and the
    timestamp-free rule accepts the gap.
    """

    def _tape(self):
        return [{"timestamp": "2026-08-12T14:00:00+00:00", "open": 100, "high": 101,
                 "low": 99, "close": 100},
                {"timestamp": "2026-08-12T14:01:00+00:00", "open": 99, "high": 100,
                 "low": 90, "close": 91},
                {"timestamp": "2026-08-12T14:03:00+00:00", "open": 91, "high": 95,
                 "low": 88, "close": 92}]      # 14:02 expected and absent

    def test_the_span_tolerance_does_not_even_activate(self):
        from toolbox.price_levels import _bar_span_tolerance
        assert _bar_span_tolerance(self._tape()) is None

    def test_find_fvgs_now_refuses_the_gapped_window(self):
        """THE POLICY DECISION THIS TEST DEFERRED IS NOW TAKEN (STEP 4B.5).

        It used to record, honestly, that a triple spanning a missing expected
        bucket was accepted as-is. The real cost surfaced later: on 2026-08-12 a
        single absent 1m bar left the 18:09 3m bucket incomplete, the
        displacement path filtered it out, and 18:06/18:12 became array
        neighbours -- producing an FVG the chronology path built from different
        candles. Filtering may remove evidentiary authority; it may not remove a
        market slot and make its neighbours consecutive.
        """
        from toolbox.price_levels import find_fvgs
        # the raw geometry primitive still sees it, explicitly requested
        assert find_fvgs(self._tape(), "bearish", allow_uncadenced=True), \
            "the raw primitive should still report the geometry"
        # the canonical path, given cadence authority, refuses it
        assert find_fvgs(self._tape(), "bearish", 1) == [], \
            "a triple spanning a missing expected bucket is not canonical"

    def test_continuity_reports_the_missing_bucket_exactly(self):
        r = evaluate(self._tape(), "1m")
        assert r["continuity_class"] == VENUE_OPEN_OBSERVATION_ABSENT
        assert r["gaps"][0]["missing_expected_buckets"] == 1


# ══════════════════════════════════════════════════════════════════════════════
class TestIntradayHaltIsModelled:
    """STEP 2E.2. CME lists a DAILY 16:15-16:30 ET equity-index trading halt for
    Micro E-mini futures, separate from the 17:00-18:00 session close. The first
    venue calendar omitted it and therefore expected bars during a period CME
    explicitly halts -- overstating absent observations."""

    @pytest.mark.parametrize("utc,expected", [
        ("2026-08-12T20:14:00+00:00", "trading_open"),                  # 16:14 ET
        ("2026-08-12T20:15:00+00:00", "scheduled_intraday_trading_halt"),
        ("2026-08-12T20:29:00+00:00", "scheduled_intraday_trading_halt"),
        ("2026-08-12T20:30:00+00:00", "trading_open"),                  # reopen
        ("2026-08-12T20:59:00+00:00", "trading_open"),
        ("2026-08-12T21:00:00+00:00", "scheduled_daily_maintenance"),
        ("2026-08-12T21:59:00+00:00", "scheduled_daily_maintenance"),
        ("2026-08-12T22:00:00+00:00", "trading_open"),                  # 18:00 reopen
    ])
    def test_exact_minute_boundaries(self, utc, expected):
        from market_data.venue_calendar import classify
        assert classify(utc)["class"] == expected

    def test_the_halt_expects_no_bars(self):
        r = evaluate(["2026-08-12T20:14:00+00:00", "2026-08-12T20:30:00+00:00"], "1m")
        assert r["continuity_class"] == EXPECTED_MARKET_BREAK
        assert r["gaps"][0]["missing_expected_buckets"] == 0

    def test_the_halt_is_distinguishable_from_the_session_close(self):
        """Not collapsed into one generic 'maintenance' label: the reason stays
        available."""
        from market_data.venue_calendar import classify
        assert classify("2026-08-12T20:20:00+00:00")["class"] != \
            classify("2026-08-12T21:30:00+00:00")["class"]

    def test_an_archive_that_never_reaches_the_halt_CANNOT_corroborate_it(self):
        """A zero count is evidence only when there was an opportunity to observe.

        THE ORIGINAL INVARIANT, now hermetic. It replaced an assertion that the
        store "contains no bars inside either halt" -- true, and meaningless,
        because the archive of the day ended at 16:07 ET and never reached
        16:15. That was reported as empirical corroboration. It is silence.

        It used to read the LIVE canonical store, whose end time was doing the
        work. The archive has since grown past 16:15, so the fixture inverted
        while the law it encodes did not change at all. The law is what is
        tested here; the mutable dependency is gone.
        """
        from market_data.evidence_continuity import NOT_TESTABLE, empirical_coverage
        short_day = [{"timestamp": f"2026-08-12T{h:02d}:{m:02d}:00+00:00"}
                     for h, m in ((13, 0), (15, 30), (20, 7))]      # 09:00-16:07 ET
        for window in (((16, 15), (16, 30)), ((17, 0), (18, 0))):
            cov = empirical_coverage(short_day, *window)
            assert cov["dates_with_bracketing_coverage"] == 0
            assert cov["observations_inside_window"] == 0
            assert cov["empirical_status"] == NOT_TESTABLE
            assert cov["trade_opportunity_authority"] is False

    def test_bracketing_silence_across_the_maintenance_break_IS_corroboration(self):
        """The other half of the same law, and the control for the test below."""
        from market_data.evidence_continuity import EMPIRICAL, empirical_coverage
        bars = [{"timestamp": "2026-08-17T20:59:00+00:00"},          # 16:59 ET
                {"timestamp": "2026-08-17T22:00:00+00:00"}]          # 18:00 ET
        cov = empirical_coverage(bars, (17, 0), (18, 0))
        assert cov["dates_with_bracketing_coverage"] == 1
        assert cov["observations_inside_window"] == 0
        assert cov["empirical_status"] == EMPIRICAL

    def test_bars_inside_a_scheduled_halt_are_PRESERVED_but_prove_nothing(self):
        """BAR-HALT-OBSERVATION-1. The measured 2026-08-17 contradiction, hermetic.

        Bars exist for every minute of a published CME halt. Both facts survive:
        the observations are counted (they are real evidence about the PROVIDER)
        and they are denied trade-opportunity authority (they are not evidence
        about the MARKET). Model B: preserve the observation, gate the credit.
        """
        from market_data.evidence_continuity import (
            CONFLICTED_WITH_SCHEDULE, empirical_coverage)
        bars = [{"timestamp": "2026-08-17T20:14:00+00:00"}]          # 16:14 ET
        bars += [{"timestamp": f"2026-08-17T20:{m}:00+00:00"} for m in range(15, 30)]
        bars += [{"timestamp": "2026-08-17T20:30:00+00:00"}]         # 16:30 ET
        cov = empirical_coverage(bars, (16, 15), (16, 30))
        assert cov["dates_with_bracketing_coverage"] == 1
        assert cov["observations_inside_window"] == 15       # PRESERVED, not erased
        assert cov["scheduled_break_dates"] == 1
        assert cov["empirical_status"] == CONFLICTED_WITH_SCHEDULE
        assert cov["trade_opportunity_authority"] is False   # the denied inference


class TestTradeOpportunityAuthority:
    """`a provider bar exists` -/-> `the market could have traded`."""

    def test_a_bar_in_the_halt_is_preserved_and_denied_authority(self):
        from market_data.evidence_continuity import (
            TRADE_AUTHORITY_DENIED_IN_SCHEDULED_BREAK, trade_opportunity_authority)
        out = trade_opportunity_authority("2026-08-17T20:20:00+00:00", bar_present=True)
        assert out["observation_preserved"] is True
        assert out["trade_opportunity_authority"] is False
        assert out["conflicts_with_schedule"] is True
        assert out["reason"] == TRADE_AUTHORITY_DENIED_IN_SCHEDULED_BREAK

    def test_a_bar_in_the_maintenance_break_is_denied_too(self):
        from market_data.evidence_continuity import trade_opportunity_authority
        out = trade_opportunity_authority("2026-08-17T21:30:00+00:00", bar_present=True)
        assert out["trade_opportunity_authority"] is False
        assert out["observation_preserved"] is True

    def test_an_ordinary_open_minute_with_an_observation_keeps_authority(self):
        from market_data.evidence_continuity import trade_opportunity_authority
        out = trade_opportunity_authority("2026-08-17T14:00:00+00:00", bar_present=True)
        assert out["trade_opportunity_authority"] is True
        assert out["calendar_class"] == "trading_open"

    def test_no_bar_confers_no_authority(self):
        from market_data.evidence_continuity import trade_opportunity_authority
        out = trade_opportunity_authority("2026-08-17T14:00:00+00:00", bar_present=False)
        assert out["trade_opportunity_authority"] is False
        assert out["observation_preserved"] is False

    def test_an_unknown_schedule_fails_closed(self):
        """Unknown is not permission."""
        from market_data import venue_calendar as VC
        from market_data.evidence_continuity import trade_opportunity_authority
        moment = next((f"{d}T14:00:00+00:00" for d in VC.SPECIAL_SCHEDULE_DATES), None)
        if moment is None:
            pytest.skip("no special-schedule date configured")
        out = trade_opportunity_authority(moment, bar_present=True)
        if out["calendar_class"] == VC.SPECIAL_SCHEDULE_UNKNOWN:
            assert out["trade_opportunity_authority"] is False
            assert out["observation_preserved"] is True

    def test_a_zero_count_with_coverage_IS_empirical(self):
        """The other direction, so the helper is not just always pessimistic."""
        from market_data.evidence_continuity import EMPIRICAL, empirical_coverage
        bars = [{"timestamp": "2026-08-12T18:00:00+00:00"},   # 14:00 ET
                {"timestamp": "2026-08-12T19:30:00+00:00"}]   # 15:30 ET
        cov = empirical_coverage(bars, (14, 30), (15, 0))     # bracketed window
        assert cov["dates_with_bracketing_coverage"] == 1
        assert cov["observations_inside_window"] == 0
        assert cov["empirical_status"] == EMPIRICAL


class TestProviderContractIsNotAssumed:
    """STEP 2E.2. An open venue does not prove a candle must exist.

    ProjectX `retrieveBars` documents OHLCV, aggregation and `includePartialBar`
    but is SILENT on whether a zero-trade interval returns a zero-volume bar or
    is omitted. Until that is known, absence during open hours is reported as
    absence, never diagnosed as data loss.
    """

    def test_the_contract_is_recorded_as_undocumented(self):
        from market_data.evidence_continuity import PROVIDER_BAR_EMISSION_CONTRACT
        assert PROVIDER_BAR_EMISSION_CONTRACT == "undocumented"

    def test_the_class_name_does_not_claim_data_loss(self):
        assert "missing" not in VENUE_OPEN_OBSERVATION_ABSENT
        assert VENUE_OPEN_OBSERVATION_ABSENT == "venue_open_observation_absent"

    def test_the_rule_text_states_the_uncertainty(self):
        r = evaluate(stamps("19:00", "19:19"), "1m")
        assert "undocumented" in r["gaps"][0]["rule"]

    def test_two_absence_questions_stay_separable(self):
        """Venue question and observation question are different facts."""
        from market_data.venue_calendar import TRADING_OPEN, classify
        assert classify("2026-08-12T19:10:00+00:00")["class"] == TRADING_OPEN
        r = evaluate(stamps("19:00", "19:19"), "1m")
        assert r["continuity_class"] == VENUE_OPEN_OBSERVATION_ABSENT


class TestSpecialDateScope:
    """STEP 2E.3. Without a date authority the calendar cannot KNOW which dates
    are special, so Thanksgiving would run the ordinary Thursday rules. Authority
    is opt-in: ordinary only inside a range verified free of CME holidays."""

    def test_the_replay_scope_is_ordinary_schedule_authoritative(self):
        from market_data.venue_calendar import calendar_authority
        for day in ("2026-08-07", "2026-08-10", "2026-08-12"):
            assert calendar_authority(f"{day}T19:00:00+00:00") == "KNOWN_ORDINARY"

    def test_a_known_holiday_refuses_ordinary_hours(self):
        from market_data.venue_calendar import SPECIAL_SCHEDULE_UNKNOWN, classify
        assert classify("2026-07-03T19:00:00+00:00")["class"] == SPECIAL_SCHEDULE_UNKNOWN

    def test_thanksgiving_is_not_an_ordinary_thursday(self):
        from market_data.venue_calendar import SPECIAL_SCHEDULE_UNKNOWN, classify
        assert classify("2026-11-26T19:00:00+00:00")["class"] == SPECIAL_SCHEDULE_UNKNOWN

    def test_a_date_outside_verified_ranges_refuses_to_guess(self):
        from market_data.venue_calendar import calendar_authority
        assert calendar_authority("2027-02-01T19:00:00+00:00") == "OUTSIDE_AUTHORITY"

    def test_holiday_HOURS_are_not_invented(self):
        """Identifying the date is not the same as knowing its trading hours."""
        from market_data.venue_calendar import SPECIAL_SCHEDULE_AUTHORITY_MISSING
        assert SPECIAL_SCHEDULE_AUTHORITY_MISSING is True
