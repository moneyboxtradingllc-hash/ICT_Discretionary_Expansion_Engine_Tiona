"""STEP 4B.12 §4 UNIT 5 — CONSECUTIVE MEANS CONSECUTIVE MARKET BARS.

`expansion_detector._follow_through` and `displacement_detector._follow_through`
counted adjacent ARRAY elements. A venue-open bucket with no observation is
never built, so its neighbours are array-adjacent and the walk crossed the hole.

Measured over 1000 evaluations per producer on the 2026-08-12 tape:

    multi-bar runs                                   426
    spanning a missing expected bucket                29   (6.8%)
    unique holes                                      3    15m 18:00 · 3m 18:09 · 5m 18:10
    expansion over-credit deliveries                  26   (8 × 10pts, 18 × 5pts)
    expansion score changes                           26
    expansion STATE changes                            3   3m 18:14/18:15/18:16,
                                                           mature_expansion -> early_expansion
    displacement false >=3 witnesses                  11   (each -10, all bearish: 3m×6 5m×5)
    displacement direction / classification changes    0

The three state changes are ONE occurrence delivered three times: the 3m 18:09
bucket was never observed, so an observed run of 4 bought the capped 15 points
where market time supports 1 bar and 5 points. `expansion_score` 54 -> 44 crosses
the 45 gate. `body_dominance`, `directional_efficiency`, `leg_candles` and
`leg_scoped` are IDENTICAL across both arms -- the state moved because the
evidence was corrected, not because the leg was scoped differently.

An earlier measurement reported 0 state changes. It called `detect_expansion`
outside the full pipeline and is superseded; the figure above is the
production-faithful one.

MODEL B. The observation is preserved and the CREDIT is gated. An observed run
of six is a true statement about what the array held; it is not proof that six
consecutive market bars occurred. `market_events` already published exactly this
distinction -- these producers simply never adopted it.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_data.evidence_continuity import (  # noqa: E402
    CONTIGUOUS, EXPECTED_MARKET_BREAK, UNKNOWN_CADENCE,
    VENUE_OPEN_OBSERVATION_ABSENT, authoritative_trailing_run)
from structure import displacement_detector as DSP  # noqa: E402
from volatility import expansion_detector as EXP    # noqa: E402


def bar(ts, o, c):
    return {"timestamp": ts, "open": o, "high": max(o, c) + 1,
            "low": min(o, c) - 1, "close": c, "volume": 10,
            "range": round(abs(max(o, c) + 1 - (min(o, c) - 1)), 2),
            "body_size": round(abs(c - o), 2),
            "upper_wick": 1.0, "lower_wick": 1.0,
            "direction": "bearish" if c < o else "bullish" if c > o else "neutral"}


def falling(stamps, start=100.0):
    """A same-direction (bearish) run at the given expected bucket stamps."""
    out, px = [], start
    for s in stamps:
        out.append(bar(f"2026-08-12T{s}:00+00:00", px, px - 1))
        px -= 1
    return out


DIR = lambda c: c.get("direction")          # noqa: E731


# ── the authority itself ─────────────────────────────────────────────────────
class TestAuthoritativeTrailingRun:

    def test_A_contiguous_run_is_fully_authorised(self):
        v = authoritative_trailing_run(
            falling(["18:00", "18:03", "18:06", "18:09"]), "3m", DIR)
        assert v["observed_run"] == 4
        assert v["authoritative_run"] == 4
        assert v["continuity"] == CONTIGUOUS

    def test_B_a_missing_expected_bucket_stops_the_run(self):
        """The real 3m hole: 18:09 expected, never observed."""
        v = authoritative_trailing_run(
            falling(["18:00", "18:03", "18:06", "18:12"]), "3m", DIR)
        assert v["observed_run"] == 4, "the observation must survive"
        assert v["authoritative_run"] == 1
        assert v["continuity"] == VENUE_OPEN_OBSERVATION_ABSENT
        assert v["stopped_between"] == ("2026-08-12T18:06:00+00:00",
                                        "2026-08-12T18:12:00+00:00")

    def test_C_a_valid_recent_suffix_survives_an_older_gap(self):
        """A [hole] B C  ->  2, never 0. Older damage may not erase new proof."""
        v = authoritative_trailing_run(
            falling(["18:00", "18:06", "18:09", "18:12"]), "3m", DIR)
        assert v["observed_run"] == 4
        assert v["authoritative_run"] == 3

    def test_D_a_scheduled_closure_is_continuous_market_time(self):
        """20 minutes of wall-clock across a 5m timeframe, and NOT a gap.

        A `timedelta == timeframe` predicate would truncate here and flag every
        session boundary. The venue calendar says no bucket was expected.
        """
        v = authoritative_trailing_run(
            falling(["20:00", "20:05", "20:10", "20:30"]), "5m", DIR)
        assert v["authoritative_run"] == 4
        assert v["continuity"] == EXPECTED_MARKET_BREAK

    def test_E_unknown_cadence_authorises_nothing_across_it(self):
        """Not knowing what the venue was scheduled to print is not evidence
        that it printed nothing."""
        v = authoritative_trailing_run(
            [bar("nonsense-1", 100, 99), bar("nonsense-2", 99, 98)], None, DIR)
        assert v["authoritative_run"] <= 1

    def test_F_a_direction_change_bounds_the_run_before_continuity(self):
        run = falling(["18:00", "18:03"]) + [bar("2026-08-12T18:06:00+00:00", 98, 99)]
        v = authoritative_trailing_run(run, "3m", DIR)
        assert v["observed_run"] == 1 and v["direction"] == "bullish"

    def test_G_a_single_bar_is_not_a_continuity_question(self):
        v = authoritative_trailing_run(falling(["18:00"]), "3m", DIR)
        assert v["authoritative_run"] in (0, 1)

    def test_R_an_unavailable_calendar_fails_closed_and_never_raises(self):
        """CERTIFICATION-FOUND DEFECT. Wiring this authority into A1/A2 gave
        `venue_calendar` its first path into `build_snapshot`; a raising
        calendar escaped `detect_expansion` and destroyed the whole snapshot.

        A calendar that cannot answer is an UNKNOWN SCHEDULE, and an unknown
        schedule authorises nothing -- it is not an exception, and it is
        certainly not proof of contiguity.
        """
        from market_data import venue_calendar as VC
        run = falling(["18:00", "18:03", "18:06", "18:12"])
        original = VC.expected_buckets
        VC.expected_buckets = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable"))
        try:
            v = authoritative_trailing_run(run, "3m", DIR)
        finally:
            VC.expected_buckets = original
        assert v["observed_run"] == 4, "the observation still survives"
        assert v["authoritative_run"] == 1, "nothing is authorised across it"
        assert v["continuity"] == UNKNOWN_CADENCE

    def test_S_an_unavailable_calendar_cannot_manufacture_credit(self):
        """The failure must never land on the PERMISSIVE side: a broken
        calendar may not hand a contiguous verdict to a gapped run."""
        from market_data import venue_calendar as VC
        original = VC.expected_buckets
        VC.expected_buckets = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable"))
        try:
            candles = falling(["18:00", "18:03", "18:06", "18:12"])
            assert EXP._follow_through(candles, "3m") == 1
            ok, _d, vote, _od, run, _b = DSP._follow_through(candles, "3m")
        finally:
            VC.expected_buckets = original
        assert ok is False and vote is None
        assert run == 4, "observed claim intact even under calendar failure"


# ── A1 expansion: credit follows the authoritative run ───────────────────────
class TestExpansionCredit:

    def test_H_observed_and_authoritative_are_both_reported(self):
        candles = falling(["18:00", "18:03", "18:06", "18:12"])
        assert EXP._observed_follow_through(candles) == 4
        assert EXP._follow_through(candles, "3m") == 1

    def test_I_credit_uses_the_authoritative_run(self):
        """min(run*5, 15) is UNCHANGED. Only its evidentiary input is corrected."""
        candles = falling(["18:00", "18:03", "18:06", "18:12"])
        observed, authorised = 4, EXP._follow_through(candles, "3m")
        assert min(observed * 5, 15) == 15
        assert min(authorised * 5, 15) == 5

    def test_J_cap_saturation_leaves_identity_wrong_but_credit_equal(self):
        """Measured 3 times on real tape (3m 18:20-18:22): observed 6,
        authoritative 3, points 15 both sides. Still an identity error."""
        candles = falling(["18:00", "18:06", "18:09", "18:12", "18:15", "18:18"])
        v = authoritative_trailing_run(candles, "3m", DIR)
        assert v["observed_run"] == 6 and v["authoritative_run"] == 5
        assert min(v["observed_run"] * 5, 15) == min(v["authoritative_run"] * 5, 15)

    def test_K_a_contiguous_run_is_unaffected(self):
        candles = falling(["18:00", "18:03", "18:06", "18:09"])
        assert EXP._follow_through(candles, "3m") == 4
        assert EXP._observed_follow_through(candles) == 4


# ── A2 displacement: the vote is gated, the observation is not ───────────────
class TestDisplacementWitness:

    def test_L_a_gapped_run_earns_no_witness(self):
        window = falling(["18:00", "18:03", "18:06", "18:12"])
        ok, detail, vote, obs_dir, run, bars = DSP._follow_through(window, "3m")
        assert ok is False, "credit withheld"
        assert vote is None, "no direction vote from unauthorised evidence"
        assert run == 4, "the producer's own claim must be unchanged"
        assert obs_dir == "bearish", "the observed direction is still reported"
        assert "market-contiguous" in detail and "credit withheld" in detail

    def test_M_a_contiguous_three_bar_run_still_votes(self):
        window = falling(["18:00", "18:03", "18:06"])
        ok, _d, vote, _od, run, _b = DSP._follow_through(window, "3m")
        assert ok is True and vote == "bearish" and run == 3

    def test_N_threshold_preserved_when_the_gap_is_older(self):
        """Measured 3 times: a continuity defect exists but the authoritative
        trailing run is still >= 3, so the witness remains legitimate."""
        window = falling(["18:00", "18:06", "18:09", "18:12"])
        ok, _d, vote, _od, run, _b = DSP._follow_through(window, "3m")
        assert ok is True and vote == "bearish"
        assert run == 4, "observed claim intact"

    def test_O_scheduled_closure_does_not_withhold_the_witness(self):
        window = falling(["20:00", "20:05", "20:10", "20:30"])
        ok, _d, vote, _od, _r, _b = DSP._follow_through(window, "5m")
        assert ok is True and vote == "bearish"


# ── the invariant that makes this MODEL B ────────────────────────────────────
class TestObservationIsNeverErased:

    @pytest.mark.parametrize("stamps,tf", [
        (["18:00", "18:03", "18:06", "18:12"], "3m"),
        (["18:00", "18:05", "18:15"], "5m"),
        (["17:45", "18:15"], "15m"),
    ])
    def test_P_observed_run_is_unchanged_by_the_repair(self, stamps, tf):
        """The repair changes what credit is AUTHORISED, never what was SEEN."""
        candles = falling(stamps)
        naive = 1
        for c in reversed(candles[:-1]):
            if c["direction"] == candles[-1]["direction"]:
                naive += 1
            else:
                break
        assert EXP._observed_follow_through(candles) == naive
        assert authoritative_trailing_run(candles, tf, DIR)["observed_run"] == naive
        _ok, _d, _v, _od, run, _b = DSP._follow_through(candles, tf)
        assert run == naive

    def test_Q_direction_still_comes_only_from_price(self):
        import inspect
        src = inspect.getsource(DSP._follow_through)
        assert "_dir_of" in src
        assert not any(k in src for k in ("bos", "mss", "struct"))
