"""STEP 4B.12 §4 UNIT 1 — a pivot's neighbours are MARKET neighbours.

`find_swings` confirmed pivots against ARRAY neighbours of the settled survivors,
so a bucket dropped for incompleteness made its survivors adjacent:

    good bucket -> [incomplete bucket dropped] -> good bucket
    became `good, good`, and the pivot rule called them neighbours.

Measured on the real tape, unique production pivots whose neighbourhood omitted a
required canonical slot: 1m 17/313, 3m 12/102, 5m 13/55, 15m 11/19. Two published
levels stood on it -- 5m last_swing_low 29889.75 and 15m last_swing_high
29928.75 -- both descending from ONE absent source minute at 18:11. Neither was
proven FALSE. They were pivots the engine had no right to certify.

Every negative control here proves the pivot WOULD have been certified absent the
specific defect injected. False-stayed-False is not evidence.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from data_feed.timeframe_builder import build_timeframes            # noqa: E402
from market_data.snapshot_builder import _bucket_is_settled         # noqa: E402
from market_data.swing_evidence import (                            # noqa: E402
    ADJ_CADENCE_UNKNOWN, ADJ_NEIGHBOUR_OMITTED, ADJ_PROVEN,
    build_swing_evidence, project_swing_evidence)
from structure.structure_engine import (                            # noqa: E402
    SWING_CADENCE_UNKNOWN, SWING_EVALUABLE, SWING_EXTREMA_UNPROVEN,
    SWING_NEIGHBOUR_OMITTED, find_swings_detailed)

VERIFIED_DAY = "2026-08-12"      # inside VERIFIED_ORDINARY_RANGES
#: A DECLARED HOLIDAY, NOT A DATE BEYOND THE HORIZON. This was 2026-09-15,
#: chosen because it lay outside VERIFIED_ORDINARY_RANGES -- which made the
#: specimen a hostage to the horizon, and VENUE-CALENDAR-AUTHORITY-HORIZON-1
#: duly broke it by extending ordinary authority to year-end. The theorem
#: below is about UNKNOWN CADENCE, not about an unverified date, so the
#: specimen is now a date whose cadence is unknown BY DESIGN: Labor Day is
#: KNOWN_SPECIAL and its exact product hours are deliberately not encoded, so
#: it stays CADENCE_UNKNOWN however far ordinary authority is later extended.
UNKNOWN_DAY = "2026-09-07"       # KNOWN_SPECIAL; exact cadence unproven
TF = 5

#: Bucket highs chosen so index 8 is an unambiguous fractal high with three
#: strictly lower buckets on each side, and index 8's low is NOT a pivot low.
HIGHS = [100, 101, 102, 103, 104, 105, 106, 107, 120,
         108, 109, 110, 111, 112, 113, 114]


def minute(day, offset, high, low=None):
    t = datetime.fromisoformat(f"{day}T18:00:00+00:00") + timedelta(minutes=offset)
    lo = high - 5 if low is None else low
    return {"timestamp": t.isoformat(), "open": high - 2, "high": high,
            "low": lo, "close": high - 1, "volume": 10}


def tape(day=VERIFIED_DAY, highs=None, drop_buckets=(), drop_minutes=(),
         duplicate=None):
    """1m bars whose 5m buckets take the given highs.

    `drop_buckets`   remove every constituent -> the aggregate never exists
    `drop_minutes`   remove one constituent  -> the aggregate is incomplete
    `duplicate`      (bucket, minute) repeat one constituent so the bucket keeps
                     a FULL count while an expected identity is absent
    """
    highs = highs or HIGHS
    bars = []
    for b, h in enumerate(highs):
        if b in drop_buckets:
            continue
        for m in range(TF):
            off = b * TF + m
            if (b, m) in drop_minutes:
                continue
            bars.append(minute(day, off, h))
        if duplicate and duplicate[0] == b:
            bars.append(minute(day, b * TF + duplicate[1], h))
    return bars


def resolve(bars, day=VERIFIED_DAY):
    raw = build_timeframes(bars)["5m"]
    settled = [c for c in raw if _bucket_is_settled(raw, c)]
    return settled, raw, build_swing_evidence(settled, raw, TF)


def pivot_times(swings):
    return {(s["side"], s["pivot_time"]) for s in swings}


TARGET = ("high", f"{VERIFIED_DAY}T18:40:00+00:00")     # bucket 8 = 18:40


class TestA_CleanCanonicalPivotPositive:

    def test_a_complete_authoritative_neighbourhood_certifies_the_pivot(self):
        settled, _raw, ev = resolve(tape())
        assert all(v == ADJ_PROVEN for v in ev["adjacency"])
        assert all(ev["high_authoritative"])
        highs, _lows = find_swings_detailed(settled, "5m", evidence=ev)
        assert TARGET in pivot_times(highs), \
            "the canonical pivot was not certified; every control below is vacuous"


class TestB_CleanCanonicalPivotNegative:

    def test_a_complete_neighbourhood_that_simply_is_not_a_pivot(self):
        """The negative comes from GEOMETRY, never from omitted evidence."""
        ramp = list(range(100, 116))
        settled, _raw, ev = resolve(tape(highs=ramp))
        assert all(v == ADJ_PROVEN for v in ev["adjacency"])
        assert all(ev["high_authoritative"]), "evidence must be complete here"
        highs, _lows = find_swings_detailed(settled, "5m", evidence=ev)
        assert not highs, "a monotonic ramp produced a swing high"


class TestC_RequiredNeighbourAbsent:

    def test_legacy_certifies_it_and_final_refuses(self):
        bars = tape(drop_buckets=(6,))
        settled, _raw, ev = resolve(bars)
        legacy, _ = find_swings_detailed(settled, "5m", allow_uncadenced=True)
        assert TARGET in pivot_times(legacy), \
            "legacy no longer certifies it; this control proves nothing"
        final, _ = find_swings_detailed(settled, "5m", evidence=ev)
        assert TARGET not in pivot_times(final)

    def test_the_cause_is_named(self):
        settled, _raw, ev = resolve(tape(drop_buckets=(6,)))
        assert ADJ_NEIGHBOUR_OMITTED in ev["adjacency"]
        from structure.structure_engine import _neighbourhood_verdict
        idx = next(i for i, c in enumerate(settled)
                   if c["timestamp"] == TARGET[1])
        assert _neighbourhood_verdict(ev, idx - 3, idx + 3, "high") == \
            SWING_NEIGHBOUR_OMITTED


class TestDE_ExtremaUnproven:
    """A bucket with a FULL member count but a missing expected identity stays
    in the settled series -- so this is the one path on which the extrema lane,
    rather than the adjacency lane, decides. It is the same mechanism as K/L."""

    def series(self):
        # bucket 7 keeps 5 members: 18:35,18:36,18:37,18:39 + a repeat of 18:36
        return tape(drop_minutes={(7, 3)}, duplicate=(7, 1))

    def test_D_high_authority_fails_while_the_aggregate_exists(self):
        settled, raw, ev = resolve(self.series())
        present = [c for c in raw if c["timestamp"].endswith("18:35:00+00:00")]
        assert present, "the aggregate must still exist for this to test extrema"
        assert present[0].get("complete") is True, \
            "the bucket must survive the settled filter, else this is case C"
        idx = next(i for i, c in enumerate(settled)
                   if c["timestamp"].endswith("18:35:00+00:00"))
        assert ev["high_authoritative"][idx] is False
        assert ev["adjacency"][idx] == ADJ_PROVEN, \
            "adjacency must be intact so the EXTREMA lane is what decides"

    def test_E_low_authority_fails_on_the_same_object(self):
        settled, _raw, ev = resolve(self.series())
        idx = next(i for i, c in enumerate(settled)
                   if c["timestamp"].endswith("18:35:00+00:00"))
        assert ev["low_authoritative"][idx] is False

    def test_the_pivot_that_depends_on_it_is_extrema_unproven(self):
        settled, _raw, ev = resolve(self.series())
        from structure.structure_engine import _neighbourhood_verdict
        idx = next(i for i, c in enumerate(settled)
                   if c["timestamp"] == TARGET[1])
        assert _neighbourhood_verdict(ev, idx - 3, idx + 3, "high") == \
            SWING_EXTREMA_UNPROVEN
        final, _ = find_swings_detailed(settled, "5m", evidence=ev)
        assert TARGET not in pivot_times(final)


class TestF_ScheduledClosureIsNotMissingEvidence:

    def test_a_venue_closure_does_not_manufacture_an_omission(self):
        """16:15-16:30 ET is 20:15-20:30 UTC. Buckets either side of it are
        canonical market neighbours despite the wall-clock gap."""
        bars = []
        for b, h in enumerate(HIGHS):
            base = datetime.fromisoformat(f"{VERIFIED_DAY}T20:00:00+00:00")
            start = base + timedelta(minutes=b * TF)
            if 20 * 60 + 15 <= start.hour * 60 + start.minute < 20 * 60 + 30:
                continue                       # the venue was closed
            for m in range(TF):
                t = start + timedelta(minutes=m)
                bars.append({"timestamp": t.isoformat(), "open": h - 2,
                             "high": h, "low": h - 5, "close": h - 1,
                             "volume": 10})
        settled, _raw, ev = resolve(bars)
        assert ADJ_NEIGHBOUR_OMITTED not in ev["adjacency"], \
            "a scheduled closure was reported as a missing market neighbour"


class TestG_UnknownCadenceIsNotEvaluable:
    """NON-VACUOUS by construction: the identical geometry is run twice and the
    known-cadence side must certify the pivot."""

    def test_the_known_side_certifies_the_pivot(self):
        settled, _raw, ev = resolve(tape(day=VERIFIED_DAY))
        highs, _ = find_swings_detailed(settled, "5m", evidence=ev)
        assert TARGET in pivot_times(highs)

    def test_the_same_geometry_is_withheld_when_cadence_is_unknown(self):
        settled, _raw, ev = resolve(tape(day=UNKNOWN_DAY), day=UNKNOWN_DAY)
        assert all(v == ADJ_CADENCE_UNKNOWN for v in ev["adjacency"])
        highs, _ = find_swings_detailed(settled, "5m", evidence=ev)
        assert not highs, "unknown cadence certified a pivot"

    def test_the_cause_is_cadence_not_omission(self):
        """Without authority we cannot even say WHICH neighbours were required,
        so claiming an omission would assert knowledge we do not have."""
        settled, _raw, ev = resolve(tape(day=UNKNOWN_DAY), day=UNKNOWN_DAY)
        from structure.structure_engine import _neighbourhood_verdict
        assert _neighbourhood_verdict(ev, 5, 11, "high") == SWING_CADENCE_UNKNOWN


class TestH_FilteringMayNotManufactureAdjacency:

    def test_A_and_C_do_not_become_neighbours_when_B_is_dropped(self):
        settled, _raw, ev = resolve(tape(drop_buckets=(6,)))
        stamps = [c["timestamp"][11:19] for c in settled]
        assert "18:30:00" not in stamps, "bucket B survived; nothing was filtered"
        i = stamps.index("18:25:00")
        assert stamps[i + 1] == "18:35:00", "A and C are array-adjacent"
        assert ev["adjacency"][i] == ADJ_NEIGHBOUR_OMITTED, \
            "filtering made two non-neighbouring market buckets adjacent"


class TestI_UnrelatedCloseDegradationDoesNotInvalidateExtrema:

    def test_a_pivot_survives_when_only_close_authority_is_degraded(self):
        """Proposition-scoped field authority: swing-high consumes HIGH,
        swing-low consumes LOW, and neither consumes CLOSE. This is the exact
        inverse of the liquidity raid family, which needs CLOSE and not extrema.
        """
        settled, _raw, ev = resolve(tape())
        assert "close_authoritative" not in ev, \
            "the swing evidence must not even model CLOSE authority"
        highs, _ = find_swings_detailed(settled, "5m", evidence=ev)
        assert TARGET in pivot_times(highs)


class TestJ_DuplicatePriceGeometryPreservesOccurrenceIdentity:

    def test_two_occurrences_at_one_price_stay_distinct(self):
        highs = list(HIGHS)
        highs[12] = 120                       # same price as the bucket-8 pivot
        settled, _raw, ev = resolve(tape(highs=highs))
        certified, _ = find_swings_detailed(settled, "5m", evidence=ev)
        times = {s["pivot_time"] for s in certified if s["level"] == 120}
        assert TARGET[1] in times, "the intended occurrence lost its identity"
        for s in certified:
            assert s["pivot_time"], "a swing carries no occurrence identity"
            assert s["swing_id"].count(":") >= 3, \
                "swing_id must qualify tf + instant, not price alone"


class TestKL_CountIsNotConstituentIdentity:

    def test_K_full_count_with_a_replaced_member_does_not_authorise(self):
        settled, raw, ev = resolve(tape(drop_minutes={(7, 3)},
                                        duplicate=(7, 1)))
        bucket = next(c for c in raw if c["timestamp"].endswith("18:35:00+00:00"))
        assert len(bucket["source_member_times"]) == bucket["expected_members"], \
            "the count must MATCH, else this is not the count-vs-identity case"
        idx = next(i for i, c in enumerate(settled)
                   if c["timestamp"].endswith("18:35:00+00:00"))
        assert ev["high_authoritative"][idx] is False, \
            "cardinality authorised extrema; count is not identity"

    def test_L_a_duplicate_cannot_stand_in_for_a_missing_member(self):
        _settled, raw, _ev = resolve(tape(drop_minutes={(7, 3)},
                                          duplicate=(7, 1)))
        bucket = next(c for c in raw if c["timestamp"].endswith("18:35:00+00:00"))
        members = list(bucket["source_member_times"])
        assert len(members) != len(set(members)), "no duplicate was injected"
        assert not any(m.endswith("18:38:00+00:00") for m in members), \
            "the expected member is present; nothing is being masked"


class TestM_ForeignMemberCannotAuthoriseAnAggregate:

    def test_the_producer_structurally_prevents_a_foreign_member(self):
        """Pinned on the PRODUCER rather than by faking an unsupported state:
        `_floor_timestamp` sends every bar to the bucket its own timestamp
        floors into, so a member of another bucket cannot appear here."""
        _settled, raw, _ev = resolve(tape())
        for c in raw:
            t0 = datetime.fromisoformat(c["timestamp"])
            span = {(t0 + timedelta(minutes=k)).isoformat() for k in range(TF)}
            for m in c["source_member_times"]:
                assert m in span, f"foreign member {m} in bucket {c['timestamp']}"


class TestN_ExactExpectedSetAuthorisesExtrema:

    def test_every_expected_constituent_present_authorises(self):
        _settled, raw, ev = resolve(tape())
        assert all(ev["high_authoritative"]) and all(ev["low_authoritative"])
        for c in raw:
            assert len(set(c["source_member_times"])) == TF
        # NOTE: no unscheduled-extra-print control. Measured reachability on
        # 1,038 production aggregates was ZERO, and inventing a supported state
        # we have no evidence can exist is exactly what this project forbids.


class TestProductionThreading:
    """No production consumer may inherit legacy array adjacency."""

    def src_files(self):
        for root, _d, files in os.walk(SRC):
            if "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)

    def test_only_the_noncanonical_module_opts_into_uncadenced_swings(self):
        callers = []
        for path in self.src_files():
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (kw.arg == "allow_uncadenced"
                                and isinstance(kw.value, ast.Constant)
                                and kw.value.value is True):
                            callers.append(
                                os.path.relpath(path, SRC).replace("\\", "/"))
        assert sorted(set(callers)) == ["market_data/market_events.py"], \
            f"a production caller reverted to legacy adjacency: {sorted(set(callers))}"

    def test_the_three_consumers_accept_canonical_evidence(self):
        import inspect
        from regime_classification.structure_hierarchy import swing_sequence
        from structure.liquidity_engine import analyze_liquidity
        from structure.manipulation_detector import detect_manipulation
        for fn in (analyze_liquidity, detect_manipulation, swing_sequence):
            assert "swing_evidence" in inspect.signature(fn).parameters, \
                f"{fn.__name__} cannot receive canonical swing evidence"


class TestProjectionPreservesTheConsumerHorizon:
    """TRUTHFUL AUTHORITY MAY NOT BROADEN A CONSUMER'S MARKET HORIZON."""

    def test_a_bounded_window_gets_exactly_its_own_positions(self):
        settled, _raw, ev = resolve(tape())
        child = settled[-6:]
        proj = project_swing_evidence(ev, child)
        assert len(proj["high_authoritative"]) == len(child)
        assert len(proj["low_authoritative"]) == len(child)
        assert len(proj["adjacency"]) == len(child) - 1
        assert proj["bucket_times"] == [c["timestamp"] for c in child]

    def test_an_edge_from_outside_the_window_is_never_imported(self):
        settled, _raw, ev = resolve(tape(drop_buckets=(2,)))
        assert ADJ_NEIGHBOUR_OMITTED in ev["adjacency"], "no omission to leak"
        child = settled[-5:]
        proj = project_swing_evidence(ev, child)
        assert ADJ_NEIGHBOUR_OMITTED not in proj["adjacency"], \
            "an adjacency defect outside the consumer window leaked into it"

    def test_identity_mismatch_fails_closed(self):
        settled, _raw, ev = resolve(tape())
        alien = [dict(settled[0], timestamp="2026-01-01T00:00:00+00:00")]
        assert project_swing_evidence(ev, alien) is None, \
            "projection aligned by position instead of identity"

    def test_a_skipped_position_inside_the_window_is_an_omission(self):
        settled, _raw, ev = resolve(tape())
        child = [settled[3], settled[5], settled[6]]     # 4 deliberately skipped
        proj = project_swing_evidence(ev, child)
        assert proj["adjacency"][0] == ADJ_NEIGHBOUR_OMITTED
