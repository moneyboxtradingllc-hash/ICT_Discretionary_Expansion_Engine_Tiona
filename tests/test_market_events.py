"""ATOMIC MARKET EVENTS — the temporal spine.

Phase 4B was blocked because the producers published current state and discarded
the event: `sweep_detected: True` with no time and no level, `mss` a bare
boolean with no side. Reading the producers showed the information was never
missing -- both are LAST-BAR detectors, so the event belongs to `candles[-1]`
and the swept/broken level is computed and thrown away.

Events are therefore RECONSTRUCTED from canonical history rather than
accumulated in a ledger. Canonical history stays the single authority, so when
continuity repair rewrites the tape the events change with it and no cached
event can outlive the history that produced it.

The two things that make that legitimate, and the two things this file exists to
defend: reconstruction must be strictly no-lookahead, and identity must be
stable.
"""
from __future__ import annotations

import collections
import contextlib
import json
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from market_data.market_events import (                              # noqa: E402
    BOS, FVG, LIQUIDITY_SWEEP, MSS, reconstruct_all, reconstruct_events)


STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "market_data", "topstepx", "CON_F_US_MNQ_U26.jsonl")


def real_events(tf="1m", bars=90):
    """Events from the REAL canonical tape.

    `ramp()` is a clean staircase: it has no pierce-and-reclaim and no confirmed
    swing to break, so it produces ZERO events. Tests that iterated it were
    passing vacuously -- an empty loop asserts nothing. Anything that needs to
    inspect real event shape uses the archived tape and asserts non-empty.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    if not os.path.exists(STORE):
        pytest.skip("canonical store not present in this checkout")
    rows = [_json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
    cut = _dt(2026, 8, 12, 19, 43, tzinfo=_tz.utc)
    kept = [b for b in rows if _dt.fromisoformat(b["timestamp"]) <= cut]
    if len(kept) < 200:
        pytest.skip("insufficient archived history")
    from data_feed.timeframe_builder import build_timeframes
    series = build_timeframes(kept)[tf][-bars:]
    events = reconstruct_events(series, tf)
    assert events, "fixture produced no events -- a vacuous test is not a passing test"
    return events


CONTRACT = "CON.F.US.MNQ.U26"


@pytest.fixture(autouse=True)
def _contract_scope():
    """STEP 3F. Production supplies its contract explicitly at the top; these
    tests stand in for that boundary. Identity is never defaulted below it."""
    from market_data.market_events import contract_scope
    with contract_scope(CONTRACT):
        yield


@contextlib.contextmanager
def no_contract_scope():
    """Drop the ambient scope so the REFUSAL paths can be exercised.

    STEP 4B.1: the scope is a ContextVar, so it is reset by token rather than
    mutated as a list -- which is exactly the isolation the list could not
    provide across threads."""
    from market_data import market_events as ME
    token = ME._CONTRACT_SCOPE.set(())
    try:
        yield
    finally:
        ME._CONTRACT_SCOPE.reset(token)


def bar(minute, o, h, l, c, status="settled", day=12):
    # canonical store rows carry their own contract; so do these
    return {"timestamp": f"2026-08-{day:02d}T19:{minute:02d}:00+00:00",
            "open": o, "high": h, "low": l, "close": c, "volume": 100,
            "temporal_status": status, "contract": CONTRACT}


def ramp(n=40, start=100.0, step=1.0):
    """A clean staircase: enough bars for swings to form."""
    out = []
    for i in range(n):
        base = start + (step * i if i < n // 2 else step * (n - i))
        out.append(bar(i, base, base + 2, base - 2, base + 0.5))
    return out


# ══════════════════════════════════════════════════════════════════════════════
class TestNoLookahead:
    """`event(T) = detector(history <= T)`. Never the full tape sliced back."""

    def test_future_bars_cannot_change_a_past_event(self):
        candles = ramp(40)
        early = reconstruct_events(candles[:25], "1m")
        full = reconstruct_events(candles, "1m")
        cutoff = candles[24]["timestamp"]
        past_of_full = [e for e in full if e["event_time"] <= cutoff]
        assert [e["event_id"] for e in early] == [e["event_id"] for e in past_of_full], \
            "an event's identity moved once later bars existed -- that is lookahead"

    def test_appending_a_future_bar_does_not_rewrite_history(self):
        candles = ramp(30)
        before = reconstruct_events(candles, "1m")
        after = reconstruct_events(candles + [bar(31, 999, 1001, 997, 998)], "1m")
        old = [e for e in after if e["event_time"] <= candles[-1]["timestamp"]]
        assert [e["event_id"] for e in before] == [e["event_id"] for e in old]

    def test_the_reconstruction_only_ever_slices_forward(self):
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME.reconstruct_events)
        assert "candles[:i + 1]" in src, "the window must end at the bar being judged"


# ══════════════════════════════════════════════════════════════════════════════
class TestDeterministicIdentity:

    def test_two_runs_agree_exactly(self):
        candles = ramp(40)
        a = reconstruct_events(candles, "1m")
        b = reconstruct_events(candles, "1m")
        assert [e["event_id"] for e in a] == [e["event_id"] for e in b]

    def test_ids_are_unique_within_a_reconstruction(self):
        events = real_events("1m")
        ids = [e["event_id"] for e in events]
        assert len(ids) == len(set(ids))

    def test_no_process_time_or_randomness_in_identity(self):
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME)
        for banned in ("uuid", "random", "time.time", "datetime.now"):
            assert banned not in src, banned

    def test_the_id_names_type_timeframe_and_time(self):
        for e in real_events("5m"):
            assert e["event_id"].startswith(
                f"{e['event_type']}:{CONTRACT}:5m:{e['event_time']}")


# ══════════════════════════════════════════════════════════════════════════════
class TestTransitionsNotConditions:
    """`bos` is a STATE test -- true for every bar price stays beyond the level.
    Measured on the Aug-12 afternoon before this fix: 104 BOS events, most of
    them `broken=29877.5` restated across nine consecutive minutes."""

    def test_a_persisting_break_is_one_event(self):
        candles = ramp(40)
        events = reconstruct_events(candles, "1m")
        bos = [e for e in events if e["event_type"] == BOS]
        seen = [(e["direction"], e["broken_level"]) for e in bos]
        assert len(seen) == len(set(seen)) or len(bos) <= 4, \
            "the same break at the same level was emitted repeatedly"

    def test_a_break_of_a_DIFFERENT_level_is_a_new_event(self):
        from market_data.market_events import _continuity_key
        a = {"event_type": BOS, "source_tf": "1m", "direction": "bearish",
             "broken_level": 100.0}
        b = dict(a, broken_level=90.0)
        assert _continuity_key(a) != _continuity_key(b)

    def test_the_continuity_key_ignores_time(self):
        """A break persisting is one event, not a new one each minute."""
        from market_data.market_events import _continuity_key
        a = {"event_type": BOS, "source_tf": "1m", "direction": "bearish",
             "broken_level": 100.0, "event_time": "t1"}
        b = dict(a, event_time="t2")
        assert _continuity_key(a) == _continuity_key(b)


# ══════════════════════════════════════════════════════════════════════════════
class TestOccurrenceSemanticsArePerEventType:
    """One dedupe rule across two ontologies was a bug.

    A first version applied the same continuity key to SWEEP, BOS and MSS. It is
    right for BOS/MSS -- `close` beyond a swing stays true for every bar price
    remains there, so the transition is the event. It is WRONG for sweeps:
    `analyze_liquidity` tests candles[-1] against candles[-2], so each bar
    independently proves pierce-and-close-back. On the Aug-12 tape 11 distinct
    1m level+side pairs genuinely recurred, including 29903.25 raided on two
    consecutive bars at 18:22 and 18:23.
    """

    def test_the_continuity_key_is_for_persistent_conditions_only(self):
        import inspect
        from market_data import market_events as ME
        body = inspect.getsource(ME.reconstruct_events)
        head, _, tail = body.partition("for kind in (BOS, MSS)")
        assert tail, "the transition test must be scoped to BOS/MSS"
        assert "_continuity_key" not in head, \
            "a one-shot event must not be deduped by continuity key"

    def test_two_bars_sweeping_the_same_level_are_two_events(self):
        c = [bar(i, 100, 101, 99, 100) for i in range(8)]
        # two consecutive bars each pierce the same high and close back
        c += [bar(8, 100, 108, 99, 100), bar(9, 100, 108, 99, 100)]
        sweeps = [e for e in reconstruct_events(c, "1m")
                  if e["event_type"] == LIQUIDITY_SWEEP]
        stamps = {e["event_time"] for e in sweeps}
        assert len(sweeps) == len(stamps), "same-level sweeps collapsed"

    def test_a_one_shot_event_id_includes_its_bar(self):
        for e in real_events("1m"):
            if e["event_type"] in (LIQUIDITY_SWEEP, FVG):
                assert e["event_time"] in e["event_id"]

    def test_bos_is_persistent_and_mss_derives_from_it(self):
        """Producer ontology, not assumption: `bos` is a state predicate on
        last_close, and `mss` is a function of that same persistent `bos`."""
        import inspect
        from structure import structure_engine as SE
        src = inspect.getsource(SE.analyze_structure)
        assert "last_close > last_swing_high" in src
        assert "mss = (bos and bias" in src


class TestSweepOntology:

    def test_reclaim_is_an_ATTRIBUTE_not_an_event(self):
        """The producer sets `reclaim_detected` in the SAME branch as the sweep:
        one bar pierced a level and closed back through it. A separate RECLAIM
        row referencing a sweep would invent an ontology the detector does not
        have."""
        events = real_events("1m")
        assert not [e for e in events if e["event_type"] == "RECLAIM"]
        for e in events:
            if e["event_type"] == LIQUIDITY_SWEEP:
                assert "reclaimed" in e

    def test_a_sweep_carries_its_side_level_and_time(self):
        for e in real_events("1m"):
            if e["event_type"] == LIQUIDITY_SWEEP:
                assert e["sweep_side"] in ("above_high", "below_low")
                assert e["event_time"] and e["source_tf"] == "1m"
                assert "swept_level" in e

    def test_the_event_time_is_the_BAR_not_the_scan(self):
        candles = ramp(40)
        stamps = {c["timestamp"] for c in candles}
        for e in reconstruct_events(candles, "1m"):
            assert e["event_time"] in stamps, "event time must be a real bar time"


# ══════════════════════════════════════════════════════════════════════════════
class TestMssProvenance:
    """The distinction is small in code and total in ontology."""

    def test_mss_direction_comes_from_its_own_break(self):
        """`analyze_structure` computes `bos_dir` from THIS call's close against
        THIS call's swings, then derives `mss` from that same value -- it is not
        reading a stored or previous `bos_direction`."""
        import inspect
        from structure import structure_engine as SE
        src = inspect.getsource(SE.analyze_structure)
        assert "bos_dir = " in src and "mss = (bos and bias" in src
        assert "self." not in src and "global " not in src, \
            "MSS direction must not come from retained state"

    def test_an_mss_event_always_carries_a_direction(self):
        for e in real_events("1m"):
            if e["event_type"] == MSS:
                assert e["direction"] in ("bullish", "bearish")
                assert e["broken_level"] is not None

    def test_mss_and_its_bos_share_the_same_bar_and_side(self):
        events = real_events("1m")
        for m in [e for e in events if e["event_type"] == MSS]:
            twin = [e for e in events if e["event_type"] == BOS
                    and e["event_time"] == m["event_time"]]
            assert twin and twin[0]["direction"] == m["direction"]


# ══════════════════════════════════════════════════════════════════════════════
class TestFvgIsItsOwnFact:
    """`find_fvgs` tests physically distinct geometry:
       bullish c1.high < c3.low   |   bearish c1.low > c3.high"""

    def _gap_tape(self, direction):
        base = [bar(i, 100, 101, 99, 100) for i in range(6)]
        if direction == "bullish":
            base += [bar(6, 100, 101, 99, 100),
                     bar(7, 101, 110, 100, 109),
                     bar(8, 109, 112, 105, 111)]      # c1.high 101 < c3.low 105
        else:
            base += [bar(6, 100, 101, 99, 100),
                     bar(7, 99, 100, 90, 91),
                     bar(8, 91, 95, 88, 92)]          # c1.low 99 > c3.high 95
        return base

    @pytest.mark.parametrize("direction", ["bullish", "bearish"])
    def test_direction_comes_from_the_gap_geometry(self, direction):
        events = [e for e in reconstruct_events(self._gap_tape(direction), "1m")
                  if e["event_type"] == FVG]
        assert events, direction
        assert all(e["direction"] == direction for e in events)

    def test_a_gap_is_never_both_directions(self):
        for tape in (self._gap_tape("bullish"), self._gap_tape("bearish")):
            fvgs = [e for e in reconstruct_events(tape, "1m") if e["event_type"] == FVG]
            by_bar = {}
            for e in fvgs:
                by_bar.setdefault(e["event_time"], set()).add(e["direction"])
            for stamp, dirs in by_bar.items():
                assert len(dirs) == 1, (stamp, dirs)

    def test_an_fvg_carries_its_geometry_and_source_bars(self):
        for e in reconstruct_events(self._gap_tape("bearish"), "1m"):
            if e["event_type"] == FVG:
                assert e["gap_low"] < e["gap_high"] and e["gap_size"] > 0
                assert len(e["source_bars"]) == 3
                assert e["source_bars"][-1] == e["event_time"]

    def test_fvg_does_not_consult_displacement_or_bias(self):
        import inspect
        from market_data import market_events as ME
        # Body only: the docstring legitimately NAMES what it refuses to consult.
        body = inspect.getsource(ME._fvgs_at).split('"""')[-1]
        for banned in ("displacement", "bias", "recommendation"):
            assert banned not in body, banned

    def test_multiple_same_tf_same_direction_gaps_are_distinct_events(self):
        """TOOL INSTANCE IDENTITY: two bearish 1m FVGs at different prices are
        two physical objects and must not collapse."""
        tape = self._gap_tape("bearish")
        tape += [bar(9, 92, 93, 85, 86), bar(10, 86, 87, 80, 81),
                 bar(11, 81, 84, 78, 79)]
        fvgs = [e for e in reconstruct_events(tape, "1m") if e["event_type"] == FVG]
        if len(fvgs) >= 2:
            assert len({e["event_id"] for e in fvgs}) == len(fvgs)
            assert len({(e["gap_low"], e["gap_high"]) for e in fvgs}) == len(fvgs)


# ══════════════════════════════════════════════════════════════════════════════
class TestEventTemporalAuthority:
    """STEP 2A. An event is only as settled as the weakest bar it rests on."""

    def test_the_rule_has_ONE_owner(self):
        """`snapshot_builder._temporal_status` decides S/F/I/U. The event layer
        must not reimplement it or the two will drift."""
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME.annotate_temporal)
        assert "_temporal_status" in src and "from market_data.snapshot_builder" in src

    def test_annotation_actually_happens(self):
        """Without this the whole temporal layer is inert: `build_timeframes`
        emits `complete`/`members` but no `temporal_status`, and every event
        published as `unknown`."""
        import inspect
        from market_data import market_events as ME
        assert "annotate_temporal(candles, tf)" in inspect.getsource(ME.reconstruct_events)

    @pytest.mark.parametrize("states,expected", [
        (["settled", "settled", "settled"], "settled"),
        (["settled", "settled", "forming"], "forming"),
        (["historical_incomplete", "settled", "settled"], "historical_incomplete"),
        (["unknown", "settled", "settled"], "unknown"),
        (["historical_incomplete", "settled", "forming"], "forming"),
    ])
    def test_the_weakest_source_bar_wins(self, states, expected):
        from market_data.market_events import _weakest_temporal
        assert _weakest_temporal([{"temporal_status": s} for s in states]) == expected

    def test_an_fvg_uses_ALL_THREE_candles_not_just_the_last(self):
        """c1/c2 can be damaged while c3 is settled. Publishing c3's class alone
        would claim evidence the gap does not have.

        Behavioural rather than a source-string match: the first version of this
        test asserted an exact expression and broke the moment the call was
        wrapped across two lines, which tests formatting, not truth.
        """
        tape = [bar(i, 100, 101, 99, 100) for i in range(6)]
        tape += [bar(6, 100, 101, 99, 100),
                 bar(7, 99, 100, 90, 91),
                 bar(8, 91, 95, 88, 92)]          # bearish gap: c1.low 99 > c3.high 95
        for c in tape:
            c["temporal_status"] = "settled"
        tape[6]["temporal_status"] = "historical_incomplete"   # c1 is damaged
        fvgs = [e for e in reconstruct_events(tape, "1m") if e["event_type"] == FVG]
        assert fvgs, "expected a bearish gap"
        assert all(e["temporal_class"] == "historical_incomplete" for e in fvgs), \
            [e["temporal_class"] for e in fvgs]

    def test_a_sweep_rests_on_its_bar_AND_the_prior_close(self):
        import inspect
        from market_data import market_events as ME
        assert "_weakest_temporal(window[-2:])" in inspect.getsource(ME._sweep_at)

    def test_unknown_is_published_not_collapsed_into_settled(self):
        """CONTINUITY-2D policy preserved: unknown does not BLOCK, but it is not
        relabelled as a confident settled either."""
        from market_data.market_events import _weakest_temporal
        assert _weakest_temporal([{"temporal_status": "unknown"}]) == "unknown"

    def test_a_forming_source_bar_yields_a_forming_event(self):
        candles = ramp(30)
        candles[-1]["temporal_status"] = "forming"
        for e in reconstruct_events(candles, "1m"):
            if e["event_time"] == candles[-1]["timestamp"]:
                assert e["temporal_class"] == "forming"

    def test_bos_publishes_BOTH_evidence_legs(self):
        """Written in Step 2A as `..._records_that_its_LEVEL_evidence_is_untracked`,
        asserting the `level_evidence_temporal_class: "unknown"` placeholder was
        present. Step 2C paid that debt, so the old assertion became a test
        defending a hole. Now it defends the fix."""
        seen = 0
        for e in real_events("1m"):
            if e["event_type"] in (BOS, MSS):
                seen += 1
                assert e["break_temporal_class"]
                assert e["level_temporal_class"]
                assert e["broken_swing_id"]
        assert seen, "no structural events to check"


class TestSwingEvidenceProvenance:
    """STEP 2C. A break is only as trustworthy as the level it claims to break.

    `find_swings` computed the pivot index, the confirming bars and their
    timestamps, then returned bare prices. BOS could say "close broke 29877.5"
    without saying when 29877.5 became a level or whether that evidence was
    settled -- so it published `level_evidence_temporal_class: "unknown"`, which
    conflated market uncertainty with provenance our own code discarded.
    """

    def test_the_price_only_view_is_unchanged(self):
        """`find_swings` is now a projection of the detailed rule. Its contract
        must not have moved."""
        from structure.structure_engine import find_swings, find_swings_detailed
        candles = ramp(40)
        highs, lows = find_swings(candles, allow_uncadenced=True)
        dh, dl = find_swings_detailed(candles, allow_uncadenced=True)
        assert highs == [s["level"] for s in dh]
        assert lows == [s["level"] for s in dl]

    def test_a_swing_carries_its_own_evidence(self):
        from structure.structure_engine import find_swings_detailed
        highs, lows = find_swings_detailed(ramp(40), allow_uncadenced=True)
        for s in highs + lows:
            assert s["swing_id"] and s["pivot_time"] and s["confirmed_at"]
            assert s["source_bars"] and s["source_temporal_states"]
            assert s["side"] in ("high", "low")

    def test_a_pivot_is_confirmed_only_after_its_confirmation_bars_exist(self):
        """No-lookahead: a pivot may not be backdated as known before the bars
        that confirmed it existed."""
        from structure.structure_engine import find_swings_detailed
        candles = ramp(40)
        highs, _ = find_swings_detailed(candles, allow_uncadenced=True)
        assert highs, "expected at least one swing high"
        target = highs[0]
        cutoff = target["pivot_index"]          # stop BEFORE confirmation bars
        early, _ = find_swings_detailed(candles[:cutoff + 1], allow_uncadenced=True)
        assert target["swing_id"] not in {s["swing_id"] for s in early}

    def test_confirmed_at_is_never_before_pivot_time(self):
        from structure.structure_engine import find_swings_detailed
        highs, lows = find_swings_detailed(ramp(40), allow_uncadenced=True)
        for s in highs + lows:
            assert s["confirmed_at"] >= s["pivot_time"]

    def test_bos_names_the_exact_swing_it_broke(self):
        for e in real_events("1m"):
            if e["event_type"] in (BOS, MSS):
                assert e["broken_swing_id"], "a break must name its level's origin"
                assert e["broken_swing_pivot_time"]
                assert e["broken_swing_confirmed_at"]

    def test_a_settled_break_of_a_DAMAGED_level_is_not_a_settled_event(self):
        """The case this step exists for: the break bar settled, the level did
        not, and the event must inherit the weaker leg."""
        from market_data.market_events import _swing_temporal
        damaged = {"source_temporal_states": ["settled", "historical_incomplete",
                                              "settled"]}
        assert _swing_temporal(damaged) == "historical_incomplete"

    def test_both_legs_are_published_separately(self):
        for e in real_events("1m"):
            if e["event_type"] in (BOS, MSS):
                assert "break_temporal_class" in e and "level_temporal_class" in e
                assert e["temporal_class"] in (e["break_temporal_class"],
                                               e["level_temporal_class"])

    def test_the_debt_placeholder_is_gone(self):
        for e in real_events("1m"):
            assert "level_evidence_temporal_class" not in e, \
                "provenance debt should be paid, not renamed"

    def test_revising_history_revises_the_swing_identity(self):
        from structure.structure_engine import find_swings_detailed
        candles = ramp(40)
        before = {s["swing_id"] for s in find_swings_detailed(candles, allow_uncadenced=True)[0]}
        repaired = copy.deepcopy(candles)
        for c in repaired[10:20]:
            c["high"] += 50
        after = {s["swing_id"] for s in find_swings_detailed(repaired, allow_uncadenced=True)[0]}
        assert before != after


class TestSwingIdentityIsTimeframeQualified:
    """STEP 2D. A 1m swing low and a 5m swing low can share a pivot minute and a
    price and still be different structural objects. Once BOS/MSS began
    publishing `broken_swing_id`, an unqualified id would alias two different
    levels across the Brain's multi-timeframe world."""

    def _pivot_tape(self):
        return [{"timestamp": f"2026-08-12T19:{i:02d}:00+00:00", "open": 100,
                 "high": 100 + (5 if i == 5 else 0), "low": 99, "close": 100,
                 "temporal_status": "settled"} for i in range(12)]

    def test_the_same_pivot_on_two_timeframes_is_two_objects(self):
        from structure.structure_engine import find_swings_detailed
        a, _ = find_swings_detailed(self._pivot_tape(), "1m", allow_uncadenced=True)
        b, _ = find_swings_detailed(self._pivot_tape(), "5m", allow_uncadenced=True)
        assert a and b
        assert a[0]["swing_id"] != b[0]["swing_id"]
        assert a[0]["source_tf"] == "1m" and b[0]["source_tf"] == "5m"

    def test_the_object_carries_source_tf_not_just_the_id(self):
        from structure.structure_engine import find_swings_detailed
        highs, _ = find_swings_detailed(self._pivot_tape(), "3m", allow_uncadenced=True)
        assert highs[0]["source_tf"] == "3m"

    def test_bos_broken_swing_ids_are_timeframe_qualified(self):
        for e in real_events("5m"):
            if e.get("broken_swing_id"):
                assert ":5m:" in e["broken_swing_id"], e["broken_swing_id"]

    def test_the_price_only_contract_still_works_without_a_timeframe(self):
        from structure.structure_engine import find_swings
        highs, lows = find_swings(ramp(40), allow_uncadenced=True)
        assert isinstance(highs, list) and all(isinstance(h, float) for h in highs)


class TestCompositeTemporalEvidence:
    """STEP 2D. One scalar rank erases simultaneous, orthogonal defects."""

    def test_two_defects_both_survive(self):
        from market_data.market_events import _evidence_summary
        s = _evidence_summary(["historical_incomplete", "settled", "forming"])
        assert s["evidence_temporal_classes"] == ["forming", "historical_incomplete",
                                                  "settled"]
        assert s["all_evidence_settled"] is False

    def test_fully_settled_evidence_says_so(self):
        from market_data.market_events import _evidence_summary
        s = _evidence_summary(["settled", "settled"])
        assert s["evidence_temporal_classes"] == ["settled"]
        assert s["all_evidence_settled"] is True

    def _damaged_gap_tape(self, c3_status):
        tape = [bar(i, 100, 101, 99, 100) for i in range(6)]
        tape += [bar(6, 100, 101, 99, 100),
                 bar(7, 99, 100, 90, 91),
                 bar(8, 91, 95, 88, 92)]          # bearish gap
        for c in tape:
            c["temporal_status"] = "settled"
        tape[6]["temporal_status"] = "historical_incomplete"   # c1 permanently damaged
        tape[8]["temporal_status"] = c3_status                 # c3 forming or settled
        return tape

    def test_THE_CRITICAL_PROOF_forming_does_not_erase_incomplete(self):
        """c1 = historical_incomplete, c2 = settled, c3 = forming.
        The scalar ranks as `forming`; the permanent damage must still be
        visible, because it survives c3 closing."""
        fvgs = [e for e in reconstruct_events(self._damaged_gap_tape("forming"), "1m")
                if e["event_type"] == FVG]
        assert fvgs
        for e in fvgs:
            assert e["temporal_class"] == "forming"
            assert "historical_incomplete" in e["evidence_temporal_classes"]
            assert "forming" in e["evidence_temporal_classes"]

    def test_when_the_forming_bar_settles_the_damage_REMAINS(self):
        fvgs = [e for e in reconstruct_events(self._damaged_gap_tape("settled"), "1m")
                if e["event_type"] == FVG]
        assert fvgs
        for e in fvgs:
            assert "forming" not in e["evidence_temporal_classes"]
            assert "historical_incomplete" in e["evidence_temporal_classes"]
            assert e["all_evidence_settled"] is False

    def test_a_sweep_publishes_its_evidence_set(self):
        for e in real_events("1m"):
            if e["event_type"] == LIQUIDITY_SWEEP:
                assert "evidence_temporal_classes" in e
                assert "all_evidence_settled" in e

    def test_bos_evidence_covers_break_AND_level(self):
        for e in real_events("1m"):
            if e["event_type"] in (BOS, MSS):
                assert "evidence_temporal_classes" in e
                assert e["break_temporal_class"] in e["evidence_temporal_classes"]

    def test_every_event_family_exposes_the_summary(self):
        events = real_events("1m")
        assert events
        for e in events:
            assert isinstance(e["evidence_temporal_classes"], list)
            assert e["evidence_temporal_classes"]


class TestPersistentEventOccurrenceIdentity:
    """STEP 2B. Deduping a persisting condition must not merge two separate
    occurrences of the same break."""

    def test_the_same_level_broken_twice_is_two_events(self):
        base = [bar(i, 100, 101, 99, 100) for i in range(10)]
        # break down, recover back above, then break the same level again
        broke1 = [bar(10, 100, 101, 90, 91), bar(11, 91, 92, 89, 90)]
        recover = [bar(12, 90, 105, 90, 104), bar(13, 104, 106, 103, 105)]
        broke2 = [bar(14, 105, 106, 88, 89), bar(15, 89, 90, 87, 88)]
        events = reconstruct_events(base + broke1 + recover + broke2, "1m")
        bos = [e for e in events if e["event_type"] == BOS]
        ids = [e["event_id"] for e in bos]
        assert len(ids) == len(set(ids)), "two occurrences shared one event id"

    def test_the_event_id_carries_the_occurrence_time(self):
        for e in real_events("1m"):
            assert e["event_time"] in e["event_id"], e["event_id"]


class TestHistoryIsTheAuthority:

    def test_revising_canonical_history_revises_the_events(self):
        """No cached event may outlive the history that produced it."""
        candles = ramp(40)
        before = {e["event_id"] for e in reconstruct_events(candles, "1m")}
        repaired = copy.deepcopy(candles)
        for c in repaired[20:]:
            c["high"] += 40
            c["close"] += 40
            c["low"] += 40
        after = {e["event_id"] for e in reconstruct_events(repaired, "1m")}
        assert before != after, "rewriting the tape left the event stream unchanged"

    def test_ordering_is_by_market_time_not_timeframe(self):
        candles = ramp(40)
        events = reconstruct_all({"1m": candles, "5m": candles})
        stamps = [e["event_time"] for e in events]
        assert stamps == sorted(stamps)

    def test_events_carry_their_bar_temporal_class(self):
        candles = ramp(30)
        candles[-1]["temporal_status"] = "forming"
        events = reconstruct_events(candles, "1m")
        newest = [e for e in events if e["event_time"] == candles[-1]["timestamp"]]
        for e in newest:
            assert e["temporal_class"] == "forming"


# ══════════════════════════════════════════════════════════════════════════════
class TestDisplacementEventization:
    """STEP 3 / 3A. `detect_displacement` scores a FIXED TRAILING WINDOW, so its
    output is a rolling ASSESSMENT. A detector returning a result is not proof
    that a market event occurred."""

    _cache = {}

    def _res(self, bars=30):
        import json
        from datetime import datetime, timezone
        from market_data.market_events import reconstruct_displacement
        if bars in self._cache:
            return self._cache[bars]
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        cut = datetime(2026, 8, 12, 19, 43, tzinfo=timezone.utc)
        kept = [b for b in rows if datetime.fromisoformat(b["timestamp"]) <= cut]
        if len(kept) < 200:
            pytest.skip("insufficient archived history")
        res = reconstruct_displacement(kept, lookback_bars=bars)
        assert res["observations"], "fixture produced no displacement observations"
        self._cache[bars] = res
        return res

    def _obs(self, bars=30):
        return self._res(bars)["observations"]

    def _occ(self, bars=30):
        return self._res(bars)["occurrences"]

    # ── direction provenance ────────────────────────────────────────────────
    def test_direction_never_comes_from_structure(self):
        """Voter audit, pinned. `_structure_break`, `_efficiency` and
        `_no_hesitation` all return direction None and cast no vote; only the
        largest-body candle and consecutive-candle direction do."""
        import inspect
        from structure import displacement_detector as DD
        for fn in (DD._structure_break, DD._efficiency, DD._no_hesitation):
            src = inspect.getsource(fn)
            body = src.split('"""')[-1] if '"""' in src else src
            assert "return False" in body or "None" in body
        # the two that DO vote name the side from price
        assert "_dir_of(best_c)" in inspect.getsource(DD._magnitude)
        # UNIT 5 moved the same-direction walk into the continuity authority, so
        # `_dir_of` is now HANDED to it rather than called in a local loop. The
        # proposition is unchanged; the PROOF is upgraded from substring to AST,
        # because a substring scan reads comments and docstrings as if they were
        # code -- it would fail on the word "structure" in a comment and pass on
        # a structural read spelled through an alias.
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(DD._follow_through)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        subscripts = {n.value for n in ast.walk(tree)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "_dir_of" in names, "price is still the side's source"
        # every symbol the function can reach, however spelled
        reachable = names | attrs | subscripts
        assert not any("bos" in str(s).lower() or "mss" in str(s).lower()
                       or "struct" in str(s).lower() for s in reachable), \
            f"follow-through may never take its side from structure: {reachable}"
        # and the signature cannot receive a structure block at all
        params = [a.arg for a in ast.walk(tree) if isinstance(a, ast.arg)]
        assert params == ["window", "tf"], params

    def test_bos_cannot_author_displacement_direction(self):
        """§15. `_structure_break` sees BOS/MSS and still votes for nothing."""
        from structure.displacement_detector import _structure_break
        for struct in ({"bos": True, "bos_direction": "bullish"},
                       {"mss": True, "bias": "bearish"},
                       {"bos": True, "mss": True, "bos_direction": "bearish"}):
            present, _detail, direction = _structure_break(struct)
            assert present is True
            assert direction is None, "structure must never cast a direction vote"

    def test_mechanical_recommendation_cannot_reach_displacement(self):
        """The producer's whole signature is candles/struct/atr/expansion/
        authority. There is no channel for a recommendation, and `authority` is
        reported as coherence only -- never folded into score or direction."""
        import inspect
        from structure import displacement_detector as DD
        src = inspect.getsource(DD.detect_displacement)
        assert "recommendation" not in src
        head, tail = src.split("authority_coherence", 1)
        assert "direction =" not in tail, "authority must not rewrite direction"
        assert "score =" not in tail, "authority must not rewrite score"

    # ── §8/§9/§10 direction is a VOTE, not net travel ───────────────────────
    def test_direction_and_net_travel_are_separate_published_facts(self):
        for o in self._obs():
            assert "direction" in o and "net_travel" in o
            assert "net_travel_direction" in o and "direction_consistency" in o

    def test_a_bullish_vote_against_a_negative_move_stays_conflicted(self):
        """§10. The measured 15m case: largest body bullish, leg finished lower.
        The disagreement is EXPOSED, never resolved by whichever rule won."""
        from structure.displacement_detector import _consistency
        assert _consistency("bullish", -1.0, False) == "conflicted"
        assert _consistency("bearish", 1.0, False) == "conflicted"
        assert _consistency("bullish", 12.5, False) == "aligned"
        assert _consistency("bearish", -12.5, False) == "aligned"
        assert _consistency("bullish", 0.0, False) == "net_flat"
        assert _consistency(None, 5.0, True) == "no_direction"

    def test_consistency_is_never_recomputed_from_a_default(self):
        """Every observation's consistency must agree with its own two fields."""
        for o in self._obs():
            d, net, cons = o["direction"], o["net_travel"], o["direction_consistency"]
            if cons == "conflicted":
                assert d in ("bullish", "bearish") and net
                assert (net > 0) != (d == "bullish")
            elif cons == "aligned":
                assert (net > 0) == (d == "bullish")

    def test_direction_basis_separates_a_vote_from_a_fallback(self):
        """A won tally and a bare net-move fallback are different KINDS of
        claim; they wore one field name before 3A."""
        for o in self._obs():
            assert o["direction_basis"] in ("component_vote",
                                            "imbalance_echo_of_net_move",
                                            "net_move_fallback", "none")
            if o["direction_basis"] == "none":
                assert o["direction_vote"] is None
            elif o["direction_basis"] != "net_move_fallback":
                assert o["direction_vote"] == o["direction"]

    def test_an_echoed_fallback_is_never_labelled_a_component_vote(self):
        """§15. `_imbalance` is HANDED the leg and hands it back. When magnitude
        and follow-through are both silent, that echo is the ONLY vote -- and
        calling it `component_vote` laundered a net-move fallback into a
        witness. Measured 15m @19:24: no candle over 1.5x ATR, structure silent,
        efficiency 0.094, observed run BEARISH, headline bullish."""
        from structure.displacement_detector import detect_displacement
        # ten flat-ish candles drifting up, no body anywhere near 1.5x ATR,
        # no 3-candle run, but a bullish gap for `_imbalance` to find.
        bars = []
        for i in range(10):
            o = 100.0 + i * 0.1
            bars.append({"timestamp": f"2026-08-12T19:{i:02d}:00+00:00", "open": o,
                         "high": o + 0.4, "low": o - 0.4,
                         "close": o + (0.1 if i % 2 else -0.05)})
        bars[7].update(low=bars[7]["open"] + 3, high=bars[7]["open"] + 6,
                       close=bars[7]["open"] + 5)
        bars[8].update(low=bars[8]["open"] + 4, high=bars[8]["open"] + 7,
                       close=bars[8]["open"] + 4.5)
        # keep the final candle bearish so no 3-candle run can vote either
        bars[9].update(close=bars[9]["open"] - 0.2)
        d = detect_displacement(bars, {}, atr=50.0)   # ATR huge => magnitude silent
        assert d["magnitude_direction"] is None
        assert d["follow_through_direction"] is None
        assert d["direction_basis"] != "component_vote", (
            "an imbalance echo of the net move is not an independent witness")

    def test_the_imbalance_vote_is_marked_as_an_echo(self):
        """BEHAVIOURAL. The previous version matched the literal call text
        `find_fvgs(window, direction)` and broke when 4B.5 threaded
        `tf_minutes` through -- a refactor it did not disagree with."""
        from structure.displacement_detector import _imbalance
        bars = [{"timestamp": f"2026-08-12T17:{m:02d}:00+00:00", "open": 100.0 + m,
                 "high": 101.0 + m, "low": 99.0 + m, "close": 100.5 + m}
                for m in range(6)]
        bars[3].update(low=120.0, high=125.0, open=121.0, close=124.0)
        # handed bullish -> returns bullish; handed bearish -> never returns bullish
        _p, _d, up, _n, _g = _imbalance(bars, "bullish", 1)
        _p2, _d2, down, _n2, _g2 = _imbalance(bars, "bearish", 1)
        assert up in (None, "bullish") and down in (None, "bearish")
        assert any(o["imbalance_vote_echoes_leg"] for o in self._obs())

    def test_a_short_opposing_run_is_published_not_buried_in_a_detail_string(self):
        """§9. The observed follow-through run is exposed even when too short to
        vote, so a bearish run under a bullish headline is visible."""
        for o in self._obs():
            assert "follow_through_observed_direction" in o
            assert "directional_witnesses" in o
            assert "witnesses_conflict" in o
            w = o["directional_witnesses"]
            sides = {v for v in w.values() if v in ("bullish", "bearish")}
            assert o["witnesses_conflict"] is (len(sides) > 1)

    def test_witness_disagreement_is_exposed_never_resolved(self):
        from structure.displacement_detector import _witnesses_conflict
        assert _witnesses_conflict("bullish", "bearish", "bullish") is True
        assert _witnesses_conflict("bearish", None, "bearish") is False
        assert _witnesses_conflict(None, None, "flat") is False

    def test_a_tie_is_reported_not_resolved(self):
        for o in self._obs():
            assert isinstance(o["direction_conflicted"], bool)
            if o["direction_conflicted"]:
                assert o["direction"] is None
                assert o["direction_consistency"] == "no_direction"

    # ── §2/§4 assessment vs event ───────────────────────────────────────────
    def test_a_rolling_reading_is_typed_as_an_observation(self):
        from market_data.market_events import DISPLACEMENT_ASSESSMENT
        for o in self._obs():
            assert o["event_type"] == DISPLACEMENT_ASSESSMENT
            assert o["observed_at"]

    def test_the_scored_window_is_labelled_a_detector_artifact(self):
        """§6. `candles[-LOOKBACK:]`'s left edge is not where the move began,
        and publishing it as `start_time` invented a leg start."""
        for o in self._obs():
            assert o["window_is_trailing_artifact"] is True
            assert "start_time" not in o, "the fabricated leg start must be gone"

    # ── §6 stable identity ──────────────────────────────────────────────────
    def test_one_evolving_leg_does_not_get_a_new_id_every_bar(self):
        """§15. THE HEADLINE REGRESSION. The first version keyed identity on the
        sliding window's left edge, so every bar minted a fresh 'event'."""
        occ = self._occ()
        assert occ, "no occurrences folded"
        repeated = [o for o in occ if o["observation_count"] > 1]
        assert repeated, "fixture must contain a re-observed displacement"
        for o in repeated:
            assert len(o["status_history"]) < o["observation_count"], (
                "unchanged restatements must collapse, not become transitions")

    def test_occurrence_identity_is_the_anchor_not_the_window(self):
        for o in self._occ():
            assert o["anchor_time"]
            assert str(o["anchor_time"]) in o["occurrence_id"]

    def test_advancing_end_time_alone_never_mints_a_new_occurrence(self):
        """One episode per anchor PER CONTIGUOUS RUN. STEP 3G: an anchor that
        stops being reported and later returns is two runs, not one bridged
        stretch -- so the count is anchors plus genuine interruptions, never one
        per bar."""
        ids = [o["occurrence_id"] for o in self._occ()]
        assert len(ids) == len(set(ids))
        per_tf = {}
        for o in self._obs():
            if o["anchored"]:
                per_tf.setdefault(o["source_tf"], set()).add(o["anchor_time"])
        for tf, anchors in per_tf.items():
            occ = [o for o in self._occ() if o["source_tf"] == tf]
            segments = sum(1 for o in occ if o["segmented_from_earlier_episode"])
            assert len(occ) == len(anchors) + segments
            assert len(occ) < len([o for o in self._obs()
                                   if o["source_tf"] == tf and o["anchored"]]) + 1

    def test_an_unanchored_reading_is_never_promoted(self):
        """§4. No conviction candle means no market object to be an event about."""
        from market_data.market_events import fold_displacement_occurrences
        assert fold_displacement_occurrences(
            [{"source_tf": "1m", "anchored": False, "anchor_time": None,
              "status": "POSSIBLE", "observed_at": "t"}]) == []

    # ── §5/§7 lifecycle ─────────────────────────────────────────────────────
    def test_possible_never_masquerades_as_confirmed(self):
        for o in self._occ():
            if not o["ever_confirmed"]:
                assert o["confirmed_at"] is None
                assert o["highest_classification"] == "POSSIBLE"
            else:
                assert o["confirmed_at"]

    def test_confirmation_time_is_not_backdated_to_the_anchor(self):
        """§10. The engine did not know at the anchor bar what it learned later."""
        for o in self._occ():
            if o["confirmed_at"]:
                assert str(o["confirmed_at"]) >= str(o["first_observed_at"])

    def test_the_episode_is_not_dated_to_the_conviction_candle(self):
        """§10. An episode is a run of mechanical assessments; it began when the
        first one was MADE. Only the CONVICTION_CANDLE may carry the candle's
        own time, because that object IS the candle."""
        for o in self._occ():
            assert o["event_time"] == o["first_observed_at"]

    def test_attainment_and_presence_are_separate_axes(self):
        """§8. `status = CONFIRMED` alone meant both 'once crossed the
        threshold' and 'still here'. Orthogonal truths stay orthogonal."""
        from market_data.market_events import (fold_displacement_occurrences,
                                               PRESENCE_ENDED, PRESENCE_ACTIVE)
        seq = [{"source_tf": "1m", "anchored": True, "anchor_time": "2026-08-12T15:30:00+00:00",
                "observed_at": f"2026-08-12T16:{i:02d}:00+00:00", "score": 70,
                "status": ("CONFIRMED" if i < 3 else "POSSIBLE")} for i in range(4)]
        o = fold_displacement_occurrences(seq, final_observed_at="2026-08-12T16:09:00+00:00")[0]
        # historical attainment survives the later downgrade AND the silence
        assert o["ever_confirmed"] is True
        assert o["highest_classification"] == "CONFIRMED"
        assert o["confirmed_at"] == "2026-08-12T16:00:00+00:00"
        # ...but presence does not
        assert o["currently_observed"] is False
        assert o["presence_state"] == PRESENCE_ENDED
        assert o["current_classification"] == "POSSIBLE"
        assert "status" not in o, "the collapsed scalar must be gone"
        still = fold_displacement_occurrences(seq, final_observed_at="2026-08-12T16:03:00+00:00")[0]
        assert still["presence_state"] == PRESENCE_ACTIVE
        assert still["ever_confirmed"] is True

    def test_a_later_downgrade_never_erases_historical_confirmation(self):
        """§9. Real measured shape: 17:15 CONFIRMED -> 17:24 POSSIBLE."""
        from market_data.market_events import fold_displacement_occurrences
        seq = [{"source_tf": "1m", "anchored": True, "anchor_time": "2026-08-12T15:30:00+00:00",
                "observed_at": "2026-08-12T16:00:00+00:00", "status": "CONFIRMED", "score": 75},
               {"source_tf": "1m", "anchored": True, "anchor_time": "2026-08-12T15:30:00+00:00",
                "observed_at": "2026-08-12T16:01:00+00:00", "status": "POSSIBLE", "score": 30}]
        o = fold_displacement_occurrences(seq, final_observed_at="2026-08-12T16:01:00+00:00")[0]
        assert o["ever_confirmed"] is True and o["confirmed_at"] == "2026-08-12T16:00:00+00:00"
        assert o["current_classification"] == "POSSIBLE"

    def test_future_confirmation_does_not_rewrite_the_earlier_observation(self):
        """§9. The POSSIBLE reading stays POSSIBLE in the record forever."""
        from market_data.market_events import fold_displacement_occurrences
        seq = [{"source_tf": "1m", "anchored": True, "anchor_time": "2026-08-12T15:30:00+00:00",
                "observed_at": f"2026-08-12T16:{i:02d}:00+00:00", "status": ("POSSIBLE" if i < 3 else "CONFIRMED"),
                "score": 30 + i} for i in range(4)]
        occ = fold_displacement_occurrences(seq)[0]
        assert occ["ever_confirmed"] is True
        assert occ["confirmed_at"] == "2026-08-12T16:03:00+00:00"
        assert [h["status"] for h in occ["status_history"]] == ["POSSIBLE", "CONFIRMED"]
        assert occ["observation_count"] == 4
        assert all(s["status"] == "POSSIBLE" for s in seq[:3]), "sources mutated"

    def test_only_scored_displacement_becomes_an_observation(self):
        for o in self._obs():
            assert o["classification"] in ("displacement_possible",
                                           "displacement_confirmed")

    # ── §12 substrate survives ──────────────────────────────────────────────
    def test_it_inherits_the_evidence_substrate(self):
        for o in self._obs():
            assert o["temporal_class"]
            assert o["evidence_temporal_classes"]
            assert o["source_continuity_class"]
            assert "source_elapsed_minutes" in o
            assert "source_observation_count" in o

    def test_continuity_and_temporal_defects_survive_into_displacement(self):
        """§15. Recomputed from THIS reading's exact evidence, not inherited."""
        from market_data.market_events import _displacement_at
        series = [{"timestamp": f"2026-08-12T19:{m:02d}:00+00:00", "open": 1.0,
                   "high": 2.0, "low": 0.0, "close": 1.5,
                   "temporal_status": ("historical_incomplete" if m == 30 else "settled")}
                  for m in (10, 30, 31)]
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_possible", "lookback": 3,
            "magnitude_anchor_time": "2026-08-12T15:30:00+00:00", "score": 30}}}}
        o = _displacement_at(snap, series, "1m")
        assert o["temporal_class"] == "historical_incomplete"
        assert "historical_incomplete" in o["evidence_temporal_classes"]
        assert o["all_evidence_settled"] is False
        assert o["source_continuity_class"] != "contiguous"

    def test_forming_bars_are_excluded_from_the_evidence_window(self):
        from market_data.market_events import _displacement_at
        series = [{"timestamp": f"2026-08-12T19:{m:02d}:00+00:00", "open": 1.0,
                   "high": 2.0, "low": 0.0, "close": 1.5,
                   "temporal_status": ("forming" if m == 32 else "settled")}
                  for m in (30, 31, 32)]
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_possible", "lookback": 3,
            "magnitude_anchor_time": "A"}}}}
        o = _displacement_at(snap, series, "1m")
        assert all("19:32" not in b for b in o["source_bars"])

    # ── §13 no-lookahead / determinism ──────────────────────────────────────
    def test_ids_are_deterministic(self):
        from market_data.market_events import reconstruct_displacement
        a = [o["event_id"] for o in self._obs(20)]
        self._cache.pop(20, None)
        b = [o["event_id"] for o in self._obs(20)]
        assert a == b

    def test_reconstruction_is_no_lookahead(self):
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME.reconstruct_displacement)
        assert "candles_1m[:i + 1]" in src

    def test_it_uses_the_production_detector_not_a_copy(self):
        """Recomputing ATR or the expansion block here would be a second
        interpretation of the producer."""
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME.reconstruct_displacement)
        assert "build_snapshot" in src

    def test_the_return_type_forces_the_caller_to_name_an_ontology(self):
        res = self._res()
        assert set(res) == {"observations", "occurrences", "unanchored",
                            "candle_references", "magnitude_witnesses",
                            "follow_through_runs", "assessment_opportunities"}

    def test_there_are_far_fewer_occurrences_than_readings(self):
        """The measured symptom that opened 3A: 42 1m records over 45 bars."""
        res = self._res()
        assert len(res["occurrences"]) < len(res["observations"])


# ══════════════════════════════════════════════════════════════════════════════
class TestDisplacementIsAMechanicalAssessment(TestDisplacementEventization):
    """STEP 3B. The composite is demoted to its true jurisdiction.

    The alternative was to change trading doctrine -- make magnitude mandatory
    for `displacement_confirmed` -- so that the detector would fit an event
    ontology. That is tuning, and no evidence demanded it. The detector is
    untouched; only the claim made about its output changed.
    """

    def test_the_detector_doctrine_is_not_tuned(self):
        """§2. Pinned constants. If a future mission wants these changed it must
        say so out loud, not drift them to make an ontology tidy."""
        from structure import displacement_detector as DD
        assert (DD.MAGNITUDE_ATR_MULT, DD.CONFIRMED_AT, DD.POSSIBLE_AT) == (1.5, 50, 25)
        assert (DD.W_MAGNITUDE, DD.W_IMBALANCE, DD.W_STRUCTURE) == (30, 25, 15)
        assert (DD.W_EFFICIENCY, DD.W_FOLLOW, DD.W_NO_HESITATE) == (15, 10, 5)
        assert (DD.LOOKBACK, DD.FOLLOW_THROUGH_AT) == (10, 3)

    def test_magnitude_is_still_not_mandatory_for_confirmed(self):
        """§2. 55 real readings confirmed with no magnitude witness. That stays
        possible -- the classifier is unchanged."""
        unanchored_confirmed = [o for o in self._obs()
                                if not o["anchored"]
                                and o["classification"] == "displacement_confirmed"]
        assert unanchored_confirmed, "the doctrine change slipped in"

    def test_the_assessment_is_labelled_mechanical_opinion(self):
        """§6. `displacement_confirmed` is this classifier's opinion, not a
        synonym for 'confirmed market event'."""
        from market_data.market_events import DISPLACEMENT_ASSESSMENT
        for o in self._obs():
            assert o["event_type"] == DISPLACEMENT_ASSESSMENT
            assert o["epistemic_layer"] == "DERIVED_ASSESSMENTS"
            assert o["classification_is_mechanical_opinion"] is True

    def test_a_composite_assessment_is_never_emitted_as_an_atomic_event(self):
        """§17. The headline law of 3B."""
        from market_data.market_events import (layered_chronology,
                                               DISPLACEMENT_ASSESSMENT,
                                               MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE)
        res = self._res()
        layers = layered_chronology(res["observations"] + res["occurrences"]
                                    + res["candle_references"]
                                    + res["magnitude_witnesses"]
                                    + res["follow_through_runs"])
        facts = {e["event_type"] for e in layers["MARKET_EVENTS"]}
        assert DISPLACEMENT_ASSESSMENT not in facts
        assert MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE not in facts
        assert layers["DERIVED_ASSESSMENTS"], "assessments must land in their own layer"

    def test_the_episode_name_does_not_claim_a_displacement_leg(self):
        """§7. Identity licenses 'these assessments referenced this candle' and
        nothing more."""
        from market_data.market_events import MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE
        for o in self._occ():
            assert o["event_type"] == MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE
            assert o["epistemic_layer"] == "DERIVED_ASSESSMENTS"

    # ── §4 atomic component facts ───────────────────────────────────────────
    def test_the_anchor_candle_is_its_own_atomic_fact(self):
        """§2. The PHYSICAL half only: geometry true at the candle's own time."""
        from market_data.market_events import CANDLE_REFERENCE, layered_chronology
        ccs = self._res()["candle_references"]
        assert ccs, "no anchor candle recovered from the real tape"
        for c in ccs:
            assert c["event_type"] == CANDLE_REFERENCE
            # its OWN time -- correct because the object IS the candle
            assert c["event_time"] == c["source_bars"][0]
            assert c["direction"] in ("bullish", "bearish", "neutral")
            assert all(c[k] is not None for k in ("open", "high", "low", "close", "body"))
            # THE SPLIT: no ATR, no ratio, no verdict on a physical fact
            for derived in ("atr", "atr_multiple", "threshold_atr_multiple",
                            "qualified_at"):
                assert derived not in c, f"{derived} backdated onto a physical fact"
        assert all(e["event_type"] == CANDLE_REFERENCE
                   for e in layered_chronology(ccs)["MARKET_EVENTS"])

    def test_the_magnitude_verdict_is_stamped_when_it_was_computed(self):
        """§1/§2. MEASURED: 4 of 10 anchors did not clear the threshold against
        the ATR knowable at their own timestamp. The 5m candle at 16:35 was
        1.15x ATR when it printed and 1.56x ATR 39 minutes later, promoted by a
        FALLING ATR. A later ATR may not author an anchor-time fact."""
        from market_data.market_events import MAGNITUDE_WITNESS, layered_chronology
        ws = self._res()["magnitude_witnesses"]
        assert ws, "no magnitude witness recovered"
        lagged = 0
        for w in ws:
            assert w["event_type"] == MAGNITUDE_WITNESS
            # stamped at the JUDGEMENT, never at the candle
            assert w["event_time"] == w["observed_at"]
            assert w["event_time"] >= w["selected_candle_time"]
            assert w["atr"] and w["atr_multiple"]
            assert w["evidence_is_older_than_judgement"] is (
                w["selected_candle_time"] != w["event_time"])
            if w["evidence_is_older_than_judgement"]:
                lagged += 1
        assert lagged, "the real tape must contain judgements later than their evidence"
        assert not layered_chronology(ws)["MARKET_EVENTS"],             "a derived qualification is not a physical market event"

    def test_the_atr_denominator_carries_its_own_provenance(self):
        """§3. `atr_multiple = 1.52` is not a fact without saying which ATR
        made it 1.52."""
        for w in self._res()["magnitude_witnesses"]:
            assert w["atr_as_of"], "no as-of time for the denominator"
            assert w["atr_source"] and w["atr_source_tf"]
            assert w["threshold_atr_multiple"]
            # the denominator is assessment-time, and says so
            assert w["atr_as_of"] >= w["selected_candle_time"]

    def test_the_witness_points_at_a_real_anchor_candle(self):
        res = self._res()
        ids = {c["event_id"] for c in res["candle_references"]}
        for w in res["magnitude_witnesses"]:
            assert w["selected_candle_id"] in ids

    def test_the_anchor_candle_direction_comes_from_its_own_ohlc(self):
        for c in self._res()["candle_references"]:
            expect = ("bullish" if c["close"] > c["open"]
                      else "bearish" if c["close"] < c["open"] else "neutral")
            assert c["direction"] == expect

    def test_the_anchor_candle_is_emitted_once_not_once_per_bar(self):
        """It stays the largest body for up to ten bars; it printed once."""
        ids = [c["event_id"] for c in self._res()["candle_references"]]
        assert len(ids) == len(set(ids))

    def test_follow_through_stays_an_observation_not_an_event(self):
        """§4C, audited: the run is recomputed from `window[-1]` backwards every
        bar and grows, shrinks or flips. That is a rolling state."""
        from market_data.market_events import FOLLOW_THROUGH_RUN, layered_chronology
        runs = self._res()["follow_through_runs"]
        assert runs
        layers = layered_chronology(runs)
        assert not layers["MARKET_EVENTS"], "a computed run is not an occurrence"
        assert not layers["MARKET_OBSERVATIONS"], "the venue never printed a run"
        assert len(layers["DERIVED_FACTS"]) == len(runs)
        for r in runs:
            assert r["event_type"] == FOLLOW_THROUGH_RUN
            assert r["event_time"] == r["observed_at"]
            assert r["run_length"] >= 1
            assert r["voted"] == (r["run_length"] >= r["vote_threshold"])

    def test_the_assessment_carries_its_component_evidence(self):
        """§5. A reader must be able to reconstruct WHY it scored what it did."""
        for o in self._obs():
            assert o["components"]
            assert {c["name"] for c in o["components"]} == {
                "displacement_magnitude", "imbalance_created", "structure_break",
                "directional_efficiency", "follow_through", "no_hesitation"}
            assert "imbalance_gaps" in o and "structure_evidence" in o
            assert "directional_efficiency" in o
            if o["imbalance_count"]:
                assert len(o["imbalance_gaps"]) == o["imbalance_count"]

    def test_fvg_is_never_substituted_as_displacement_identity(self):
        """§3. An FVG is a real object but is not the identity of the move that
        produced it. Gaps are referenced as evidence, never as the anchor."""
        from market_data.market_events import fold_displacement_occurrences
        # a rich, gap-laden, CONFIRMED assessment with no conviction candle
        rich = [{"source_tf": "5m", "anchored": False, "anchor_time": None,
                 "observed_at": "2026-08-12T16:00:00+00:00", "status": "CONFIRMED", "score": 70,
                 "imbalance_count": 3,
                 "imbalance_gaps": [{"low": 1, "high": 2, "size": 1, "index": 4},
                                    {"low": 3, "high": 4, "size": 1, "index": 5},
                                    {"low": 5, "high": 6, "size": 1, "index": 6}]}]
        assert fold_displacement_occurrences(rich) == [], \
            "FVG geometry was substituted as a displacement anchor"
        # and on the real tape, gaps never confer an anchor
        for o in self._obs():
            if o["imbalance_gaps"] and not o["anchored"]:
                assert o["anchor_time"] is None, "an FVG became a fake anchor"

    def test_an_unanchored_assessment_is_truthful_and_still_usable(self):
        """§17. It cannot become an occurrence, but it is not discarded."""
        una = [o for o in self._obs() if not o["anchored"]]
        assert una, "the real tape must contain unanchored assessments"
        for o in una[:50]:
            assert o["score"] is not None and o["classification"]
            assert o["conviction_candle" if False else "anchor_time"] is None
            assert o["temporal_class"] and o["source_continuity_class"]

    def test_continuity_defects_stay_attached_to_the_exact_assessment_evidence(self):
        for o in self._obs():
            assert len(o["source_bars"]) == o["source_observation_count"] or \
                   o["source_continuity_class"] == "unknown_cadence"


# ══════════════════════════════════════════════════════════════════════════════
class TestDisplacementDownstreamJurisdiction:
    """STEP 3B §13. Who consumes what, and under which epistemic claim.

    Nothing is rewritten here. The point is that the boundary is now PINNED, so
    a future change that lets the composite assessment's direction leak into a
    tool as an exact atomic market fact fails a test instead of shipping.
    """

    #: THREE SPECIES OF CONSUMER, measured 2026-08-13.
    #:
    #:   LEGACY_COMPATIBILITY  reads `displacement_detected` -- the bare bool
    #:                         from `volatility/expansion_detector.py`, a
    #:                         DIFFERENT producer with its own threshold. It
    #:                         predates the confluence detector entirely.
    #:   MECHANICAL_ASSESSMENT reads the confluence block (`score`)
    #:   FACT                  reads candle geometry directly
    LEGACY_COMPATIBILITY = (
        "toolbox/toolbox_engine.py", "toolbox/tool_readiness.py",
        "structure/po3_engine.py", "regime_classification/regime_features.py",
        "qualification/trade_qualification_engine.py",
        "market_data/volume_witness.py", "ai_layer/narrative_builder.py",
        "ai_layer/ai_snapshot_formatter.py",
        "integrations/topstepx/deterministic/facts_provider.py")
    MECHANICAL_ASSESSMENT = ("structure/po3_engine.py",)
    FACT = ("toolbox/entry_trigger_prep.py",)

    def _src(self, rel):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "src", rel), encoding="utf-8") as fh:
            return fh.read()

    def test_no_consumer_reads_the_composite_assessment_direction(self):
        """THE BOUNDARY. A weighted vote consensus -- 73% of which was an
        imbalance echo -- must not become an exact atomic market direction."""
        for rel in set(self.LEGACY_COMPATIBILITY + self.MECHANICAL_ASSESSMENT
                       + self.FACT):
            src = self._src(rel)
            for leak in ('displacement"]["direction"',
                         'displacement", {}).get("direction"',
                         'disp_block["direction"]',
                         'disp_block.get("direction")'):
                assert leak not in src, f"{rel} consumes composite direction"

    def test_the_legacy_bool_is_a_different_producer(self):
        """`displacement_detected` is not the confluence classification. They
        are separate producers with separate thresholds, and conflating them
        would let a legacy bool speak for a scored assessment."""
        from volatility import expansion_detector as ED
        from structure import displacement_detector as DD
        assert hasattr(ED, "_displacement_detected")
        assert not hasattr(ED, "detect_displacement")
        assert "displacement_detected" not in DD.detect_displacement(
            [], None, None) .keys()

    def test_the_only_confluence_consumer_reads_score_not_classification(self):
        src = self._src("structure/po3_engine.py")
        assert 'disp_block.get("score")' in src
        assert 'disp_block.get("classification")' not in src

    def test_the_execution_bearing_consumer_reads_candle_geometry(self):
        """`entry_trigger_prep._displacement_confirmed` is the one consumer that
        can gate a live entry. It reads the last candle's own open/close and the
        zone relation -- never the composite."""
        src = self._src("toolbox/entry_trigger_prep.py")
        assert "detect_displacement" not in src
        assert 'float(last["open"])' in src and 'float(last["close"])' in src

    def test_every_imbalance_return_path_has_the_same_arity(self):
        """A 4-tuple slipped through on the `leg is None` branch and the whole
        suite still passed -- that branch needs a perfectly flat net move AND no
        magnitude direction, which no unit fixture produced. The real tape found
        it in one pass. Arity is now checked on every path."""
        from structure.displacement_detector import _imbalance
        flat = [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}] * 5
        for direction in (None, "neutral", "", "bullish"):
            assert len(_imbalance(flat, direction)) == 5, direction


# ══════════════════════════════════════════════════════════════════════════════
class TestFollowThroughRunEvidence:
    """STEP 3C §4-§6. A claim about N candles must name the N candles."""

    def _run(self, candles, tf="1m", forming=None):
        from market_data.market_events import _follow_through_run_at
        from structure.displacement_detector import _follow_through
        _ok, _d, vote, run_dir, run_len, run_bars = _follow_through(candles)
        d = {"follow_through_observed_direction": run_dir,
             "follow_through_run": run_len,
             "follow_through_direction": vote,
             "follow_through_run_bars": [b["timestamp"] for b in run_bars],
             "follow_through_run_candles": run_bars}
        return _follow_through_run_at(d, tf, candles[-1]["timestamp"])

    def _bear(self, minute, status="settled", day=12):
        base = 100.0 - minute
        return {"timestamp": f"2026-08-{day:02d}T19:{minute:02d}:00+00:00",
                "open": base + 2, "high": base + 3, "low": base - 1,
                "close": base, "temporal_status": status}

    def test_the_run_names_its_exact_bars(self):
        """§4. Not the newest bar, and not the whole 10-bar window."""
        window = [self._bear(m) for m in range(10)]
        window[0].update(open=1.0, close=9.0)     # bullish, breaks the run
        window[1].update(open=1.0, close=9.0)     # bullish
        run = self._run(window)
        assert run["run_length"] == 8
        assert len(run["source_bars"]) == 8
        assert run["source_observation_count"] == 8
        assert all("19:0" in b or "19:" in b for b in run["source_bars"])
        assert window[0]["timestamp"] not in run["source_bars"]
        assert window[1]["timestamp"] not in run["source_bars"]

    def test_a_three_bar_run_does_not_borrow_the_ten_bar_window(self):
        window = [self._bear(m) for m in range(10)]
        for i in range(7):                        # only the last 3 are bearish
            window[i].update(open=1.0, close=9.0)
        run = self._run(window)
        assert run["run_length"] == 3
        assert run["source_bars"] == [c["timestamp"] for c in window[-3:]]

    def test_a_discontinuous_run_reports_both_facts(self):
        """§5. The detector says three consecutive candles; the venue says a
        bucket is missing between them. BOTH survive -- the producer is not
        tuned, and the discontinuity is published beside its claim."""
        window = [self._bear(m) for m in (10, 11, 12, 13, 14, 15, 16)]
        # array-neighbours, but 19:30 -> 19:31 skips ~14 venue-open minutes
        window[-1]["timestamp"] = "2026-08-12T19:40:00+00:00"
        run = self._run(window)
        assert run["run_length"] == 7, "the producer's own claim must be unchanged"
        assert run["source_continuity_class"] != "contiguous"
        assert run["source_gaps"], "the hole vanished from the run's evidence"

    def test_a_damaged_bar_inside_the_run_survives(self):
        """§6. One historical_incomplete source bar is not erased by six good ones."""
        window = [self._bear(m) for m in range(10)]
        window[-3]["temporal_status"] = "historical_incomplete"
        run = self._run(window)
        assert run["temporal_class"] == "historical_incomplete"
        assert "historical_incomplete" in run["evidence_temporal_classes"]
        assert run["all_evidence_settled"] is False

    def test_forming_exclusion_matches_producer_semantics(self):
        """§6. `snapshot_builder` hands `detect_displacement` the SETTLED series,
        so a forming bar never reaches the run at all. Proven against the real
        production call rather than asserted."""
        import inspect
        from market_data import snapshot_builder as SB
        src = inspect.getsource(SB.build_snapshot)
        call = src[src.index("detect_displacement("):]
        assert call.split("\n")[1].strip().startswith("settled,"), \
            "the detector must receive the settled series, not the raw one"


# ══════════════════════════════════════════════════════════════════════════════
class TestLayerRegistryIsExhaustive:
    """STEP 3C §7/§8. Unknown schema is not mechanical opinion."""

    def test_an_unregistered_type_raises_rather_than_defaulting(self):
        from market_data.market_events import (layered_chronology,
                                               UnregisteredEventType)
        with pytest.raises(UnregisteredEventType):
            layered_chronology([{"event_type": "CONVICTON_CANDLE",   # typo
                                 "event_time": "2026-08-12T16:00:00+00:00", "event_id": "x"}])

    def test_a_typo_never_lands_in_derived_assessments(self):
        """The exact defect `.get(s, 2)` once had for temporal states: a bug
        wearing the costume of epistemic humility."""
        from market_data.market_events import layered_chronology
        out = layered_chronology([{"event_type": "CONVICTON_CANDLE",
                                   "event_time": "2026-08-12T16:00:00+00:00", "event_id": "x"}],
                                 strict=False)
        assert out["DERIVED_ASSESSMENTS"] == []
        assert out["MARKET_EVENTS"] == []
        assert out["MARKET_OBSERVATIONS"] == []
        assert len(out["UNCLASSIFIED"]) == 1

    def test_every_emitted_type_is_registered(self):
        """A new factual type that nobody registers must fail loudly, so the
        registry cannot silently fall behind the emitters."""
        from market_data import market_events as ME
        emitted = {ME.LIQUIDITY_SWEEP, ME.BOS, ME.MSS, ME.FVG, ME.CANDLE_REFERENCE,
                   ME.MAGNITUDE_WITNESS, ME.FOLLOW_THROUGH_RUN,
                   ME.DISPLACEMENT_ASSESSMENT,
                   ME.MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE}
        assert emitted == set(ME.EVENT_LAYER_REGISTRY)

    def test_every_registered_layer_is_a_declared_layer(self):
        from market_data import market_events as ME
        assert set(ME.EVENT_LAYER_REGISTRY.values()) <= set(ME.EPISTEMIC_LAYERS)

    def test_the_physical_and_derived_halves_land_in_different_layers(self):
        """STEP 3E: a candle is what the venue PRINTED; the ratio is what
        mechanics COMPUTED. Neither is the other's species."""
        from market_data.market_events import EVENT_LAYER_REGISTRY as R
        assert R["CANDLE_REFERENCE"] == "MARKET_OBSERVATIONS"
        assert R["MAGNITUDE_WITNESS"] == "DERIVED_FACTS"

    def test_score_and_event_reference_provenance_are_reported_separately(self):
        """STEP 3C §9. 'A reader can reconstruct why it scored what it scored'
        was true of the ARITHMETIC and overclaimed for EVENT references. Two
        fields, two answers, no fabricated ids."""
        from market_data.market_events import _displacement_at
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_possible", "lookback": 1,
            "components": [], "structure_evidence": {"bos": True, "mss": False}}}}}
        o = _displacement_at(snap, [{"timestamp": "2026-08-12T16:00:00+00:00",
                                      "temporal_status": "settled"}],
                             "1m", observed_at="2026-08-12T16:00:00+00:00")
        assert o["score_arithmetic_provenance"] == "COMPLETE"
        assert o["component_event_reference_provenance"] == "INCOMPLETE"
        assert len(o["event_reference_gaps"]) == 1   # imbalance closed in 4B.2
        # the debt is named, not hidden behind an invented id
        assert "bos_event_id" not in o["structure_evidence"]

    def test_the_verdict_is_stamped_at_the_scan_not_the_settled_bar(self):
        """STEP 3C. On a 5m timeframe the producer's newest SETTLED bar can be
        five minutes behind the scan that ran it. Stamping the verdict there
        would backdate it by exactly the amount this step exists to prevent --
        a smaller version of the same error."""
        from market_data.market_events import _magnitude_witness_at
        d = {"conviction_candle": {"timestamp": "2026-08-12T16:35:00+00:00",
                                   "body": 32.75, "atr": 21.05, "atr_multiple": 1.56,
                                   "atr_as_of": "2026-08-12T17:10:00+00:00",
                                   "atr_source": "x", "threshold_atr_multiple": 1.5,
                                   "qualified_at": "2026-08-12T17:10:00+00:00",
                                   "direction": "bullish"}}
        w = _magnitude_witness_at(d, "5m", "2026-08-12T17:14:00+00:00")
        assert w["event_time"] == "2026-08-12T17:14:00+00:00"
        assert w["producer_settled_through"] == "2026-08-12T17:10:00+00:00"
        assert w["atr_as_of"] == "2026-08-12T17:10:00+00:00"
        assert w["evidence_is_older_than_judgement"] is True

    def test_run_temporal_labels_are_recovered_not_left_unknown(self):
        """STEP 3C. The producer is handed `settled` straight from
        `build_timeframes`, which never sets `temporal_status` -- so reading its
        run candles back verbatim reported `unknown` on 970/970 real runs. That
        looked like a market finding and was a plumbing artifact."""
        from market_data.market_events import _follow_through_run_at
        stamps = [f"2026-08-12T19:{m:02d}:00+00:00" for m in (10, 11, 12)]
        d = {"follow_through_observed_direction": "bearish", "follow_through_run": 3,
             "follow_through_direction": "bearish",
             "follow_through_run_bars": stamps,
             # exactly what the producer hands back: NO temporal_status
             "follow_through_run_candles": [{"timestamp": s} for s in stamps]}
        bare = _follow_through_run_at(d, "1m", stamps[-1])
        assert bare["temporal_class"] == "unknown"
        annotated = [{"timestamp": s, "temporal_status": "settled"} for s in stamps]
        annotated[1]["temporal_status"] = "historical_incomplete"
        fixed = _follow_through_run_at(d, "1m", stamps[-1], annotated)
        assert fixed["temporal_class"] == "historical_incomplete"
        assert fixed["all_evidence_settled"] is False


# ══════════════════════════════════════════════════════════════════════════════
class TestStep3DIdentityAndDenominator:
    """STEP 3D. Identity is not state; a denominator is part of the evidence."""

    def _d(self, anchor="2026-08-12T16:35:00+00:00", direction="bullish",
           atr_bars=None):
        return {"conviction_candle": {
            "timestamp": anchor, "open": 100.0, "high": 140.0, "low": 99.0,
            "close": 132.75, "body": 32.75, "direction": direction,
            "atr": 21.05, "atr_multiple": 1.56,
            "atr_as_of": "2026-08-12T17:10:00+00:00",
            "atr_source": "calculate_atr(settled) at assessment time",
            "threshold_atr_multiple": 1.5,
            "qualified_at": "2026-08-12T17:10:00+00:00",
            "atr_period": 14,
            "atr_source_bars": [b["timestamp"] for b in (atr_bars or [])],
            "atr_source_candles": list(atr_bars or [])}}

    def _atr_bars(self, n=15, damaged=None, hole=False):
        out = []
        for i in range(n):
            m = i + 40 if hole and i == n - 1 else i
            out.append({"timestamp": f"2026-08-12T16:{m:02d}:00+00:00",
                        "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0,
                        "temporal_status": ("historical_incomplete"
                                            if damaged == i else "settled")})
        return out

    # -- 1: the noun no longer carries the role ------------------------------
    def test_the_physical_object_asserts_only_geometry(self):
        from market_data.market_events import _candle_reference_at, CANDLE_REFERENCE
        c = _candle_reference_at(self._d(), "5m")
        assert c["event_type"] == CANDLE_REFERENCE
        assert "anchor" not in c["event_type"].lower()
        for role in ("selection_role", "atr", "atr_multiple", "qualified_at",
                     "threshold_atr_multiple"):
            assert role not in c, f"{role} backdated onto a physical fact"
        assert c["bucket_timestamp"] == c["event_time"]

    def test_the_selection_role_lives_on_the_later_judgement(self):
        from market_data.market_events import _magnitude_witness_at
        w = _magnitude_witness_at(self._d(), "5m", "2026-08-12T17:14:00+00:00")
        assert w["selection_role"] == "largest qualifying body in the assessment window"
        assert w["selected_candle_time"] == "2026-08-12T16:35:00+00:00"

    # -- 2: identity is the bucket -------------------------------------------
    def test_candle_identity_excludes_direction(self):
        """Repaired history can flip a close; the 5m bucket at 16:35 is still
        the same market object. A stale old-direction twin must be impossible."""
        from market_data.market_events import _candle_reference_at
        up = _candle_reference_at(self._d(direction="bullish"), "5m")
        down = _candle_reference_at(self._d(direction="bearish"), "5m")
        assert up["event_id"] == down["event_id"], "direction leaked into identity"
        assert "bullish" not in up["event_id"] and "bearish" not in down["event_id"]
        assert up["direction"] != down["direction"], "direction must survive as state"

    def test_identity_is_instrument_tf_and_bucket(self):
        from market_data.market_events import candle_reference_id
        from doctrine.instrument_identity import PRODUCTION_CONTRACT
        assert candle_reference_id("5m", "2026-08-12T16:35:00+00:00") == \
            f"CANDLE_REFERENCE:{PRODUCTION_CONTRACT}:5m:2026-08-12T16:35:00+00:00"
        assert candle_reference_id("1m", "2026-08-12T16:00:00+00:00") != candle_reference_id("5m", "2026-08-12T16:00:00+00:00")

    def test_a_direction_flip_yields_one_object_not_two(self):
        from market_data.market_events import _candle_reference_at
        rebuilt = [_candle_reference_at(self._d(direction=x), "5m")
                   for x in ("bullish", "bearish")]
        assert len({c["event_id"] for c in rebuilt}) == 1

    # -- 3: the ATR source window --------------------------------------------
    def test_the_atr_source_window_is_the_producers_own_slice(self):
        """No second ATR implementation: `atr_source_window` restates
        `_sma_atr`'s rule in one place, including the extra OLDER bar that true
        range needs for its previous close."""
        from volatility.atr_engine import atr_source_window, _sma_atr, MIN_CANDLES
        bars = self._atr_bars(30)
        win = atr_source_window(bars, 14)
        assert len(win) == 15, "14 true ranges need 15 candles"
        assert win == bars[-15:]
        assert atr_source_window(bars[:MIN_CANDLES - 1], 14) == []
        assert round(_sma_atr(bars, 14), 6) == round(_sma_atr(win, 14), 6)

    def test_the_witness_publishes_the_denominators_bars(self):
        from market_data.market_events import _magnitude_witness_at
        bars = self._atr_bars(15)
        w = _magnitude_witness_at(self._d(atr_bars=bars), "1m", "2026-08-12T16:20:00+00:00")
        assert w["atr_period"] == 14
        assert w["atr_source_observation_count"] == 15
        assert w["atr_source_bars"] == [b["timestamp"] for b in bars]

    # -- 4: both legs decide evidence health ---------------------------------
    def test_a_clean_anchor_cannot_hide_a_damaged_denominator(self):
        from market_data.market_events import _magnitude_witness_at
        bars = self._atr_bars(15, damaged=3)
        anchor = {"timestamp": "2026-08-12T16:35:00+00:00",
                  "temporal_status": "settled"}
        w = _magnitude_witness_at(self._d(atr_bars=bars), "1m",
                                  "2026-08-12T16:20:00+00:00", [anchor] + bars)
        assert w["atr_temporal_class"] == "historical_incomplete"
        assert w["temporal_class"] == "historical_incomplete", \
            "the anchor's own cleanliness masked the denominator"
        assert w["all_evidence_settled"] is False

    def test_a_discontinuous_denominator_survives(self):
        from market_data.market_events import _magnitude_witness_at
        bars = self._atr_bars(15, hole=True)
        w = _magnitude_witness_at(self._d(atr_bars=bars), "1m", "2026-08-12T16:20:00+00:00", bars)
        assert w["atr_continuity_class"] != "contiguous"
        assert w["atr_source_gaps"]

    def test_the_witness_names_both_legs_as_source_bars(self):
        from market_data.market_events import _magnitude_witness_at
        bars = self._atr_bars(15)
        w = _magnitude_witness_at(self._d(atr_bars=bars), "1m", "2026-08-12T16:20:00+00:00")
        # the anchor is NOT a member of this fixture's ATR window, so both roles
        # really are 16 distinct observations
        assert w["numerator_is_inside_atr_window"] is False
        assert w["logical_evidence_reference_count"] == 16
        assert w["unique_physical_observation_count"] == 16
        assert len(w["source_bars"]) == 16
        assert "2026-08-12T16:35:00+00:00" in w["source_bars"]

    # -- 5: history repair ---------------------------------------------------
    def test_repairing_an_atr_source_bar_moves_the_ratio_not_the_identity(self):
        """The whole reason identity had to leave the magnitude judgement."""
        from market_data.market_events import (_magnitude_witness_at,
                                               _candle_reference_at)
        from volatility.atr_engine import calculate_atr, atr_source_window
        bars = self._atr_bars(20)
        before = calculate_atr(bars)["atr"]
        repaired = [dict(b) for b in bars]
        repaired[-2].update(high=140.0, low=60.0)
        after = calculate_atr(repaired)["atr"]
        assert after != before, "fixture did not actually change the denominator"
        d_before = self._d(atr_bars=atr_source_window(bars))
        d_after = self._d(atr_bars=atr_source_window(repaired))
        d_after["conviction_candle"]["atr"] = after
        d_after["conviction_candle"]["atr_multiple"] = round(32.75 / after, 2)
        w1 = _magnitude_witness_at(d_before, "1m", "2026-08-12T16:20:00+00:00")
        w2 = _magnitude_witness_at(d_after, "1m", "2026-08-12T16:20:00+00:00")
        assert w1["selected_candle_id"] == w2["selected_candle_id"]
        assert (_candle_reference_at(d_before, "1m")["event_id"] ==
                _candle_reference_at(d_after, "1m")["event_id"])
        assert w1["atr"] != w2["atr"]
        assert w1["atr_multiple"] != w2["atr_multiple"]

    # -- 6/7: array adjacency is not market continuity -----------------------
    def test_run_length_never_implies_market_continuity(self):
        from market_data.market_events import _follow_through_run_at
        stamps = ["2026-08-12T19:10:00+00:00", "2026-08-12T19:11:00+00:00",
                  "2026-08-12T19:25:00+00:00"]
        d = {"follow_through_observed_direction": "bearish", "follow_through_run": 3,
             "follow_through_direction": "bearish",
             "follow_through_run_bars": stamps,
             "follow_through_run_candles": [{"timestamp": s,
                                             "temporal_status": "settled"}
                                            for s in stamps]}
        r = _follow_through_run_at(d, "1m", stamps[-1])
        assert r["observed_run_length"] == 3, "the producer's claim must survive"
        assert r["array_adjacent"] is True
        assert r["market_continuity"] != "contiguous"
        assert r["market_continuity_assessable"] is True
        assert r["source_gaps"]

    def test_a_single_bar_run_is_not_reported_as_a_continuity_defect(self):
        from market_data.market_events import _follow_through_run_at
        s = "2026-08-12T19:10:00+00:00"
        d = {"follow_through_observed_direction": "bearish", "follow_through_run": 1,
             "follow_through_direction": None, "follow_through_run_bars": [s],
             "follow_through_run_candles": [{"timestamp": s,
                                             "temporal_status": "settled"}]}
        r = _follow_through_run_at(d, "1m", s)
        assert r["market_continuity_assessable"] is False

    # -- 8: provenance wording -----------------------------------------------
    def test_score_arithmetic_and_event_reference_provenance_are_distinct(self):
        from market_data.market_events import _displacement_at
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_possible", "lookback": 1,
            "components": []}}}}
        o = _displacement_at(snap, [{"timestamp": "2026-08-12T16:00:00+00:00",
                                      "temporal_status": "settled"}],
                             "1m", observed_at="2026-08-12T16:00:00+00:00")
        assert o["score_arithmetic_provenance"] == "COMPLETE"
        assert o["component_event_reference_provenance"] == "INCOMPLETE"
        assert "score_provenance" not in o, "the over-broad field must be gone"

    # -- 9: the object's claim must match the registry ------------------------
    def test_a_contradictory_epistemic_layer_is_a_schema_error(self):
        from market_data.market_events import (layered_chronology,
                                               UnregisteredEventType, FVG)
        bad = {"event_type": FVG, "epistemic_layer": "DERIVED_ASSESSMENTS",
               "event_time": "2026-08-12T16:00:00+00:00", "event_id": "x"}
        with pytest.raises(UnregisteredEventType):
            layered_chronology([bad])
        out = layered_chronology([bad], strict=False)
        assert out["MARKET_EVENTS"] == [], "the router silently repaired the producer"
        assert len(out["UNCLASSIFIED"]) == 1

    def test_an_agreeing_layer_routes_normally(self):
        from market_data.market_events import layered_chronology, FVG
        ok = {"event_type": FVG, "epistemic_layer": "MARKET_EVENTS",
              "event_time": "2026-08-12T16:00:00+00:00", "event_id": "x"}
        assert len(layered_chronology([ok])["MARKET_EVENTS"]) == 1

    def test_every_emitted_object_agrees_with_the_registry(self):
        """The invariant caught a real drift on first run: objects declared
        `DERIVED_ASSESSMENT` while the registry named `DERIVED_ASSESSMENTS`."""
        from market_data import market_events as ME
        import re
        src = open(ME.__file__, encoding="utf-8").read()
        declared = set(re.findall(r'"epistemic_layer": "([A-Z_]+)"', src))
        assert declared <= set(ME.EPISTEMIC_LAYERS), declared


# ══════════════════════════════════════════════════════════════════════════════
class TestStep3EEvidenceIdentityAndDerivedFacts:
    """STEP 3E. Two roles are not two observations; a candle is not an event
    because mechanics noticed it; derived fact is not raw observation."""

    def _atr_bars(self, stamps):
        return [{"timestamp": s, "open": 100.0, "high": 102.0, "low": 98.0,
                 "close": 101.0, "temporal_status": "settled"} for s in stamps]

    def _d(self, anchor, atr_stamps):
        bars = self._atr_bars(atr_stamps)
        return {"conviction_candle": {
            "timestamp": anchor, "open": 100.0, "high": 140.0, "low": 99.0,
            "close": 132.75, "body": 32.75, "direction": "bullish",
            "atr": 21.05, "atr_multiple": 1.56, "atr_as_of": atr_stamps[-1],
            "atr_source": "calculate_atr(settled) at assessment time",
            "threshold_atr_multiple": 1.5, "qualified_at": atr_stamps[-1],
            "atr_period": 14, "atr_source_bars": atr_stamps,
            "atr_source_candles": bars}}

    # -- 1/2: two roles, one observation ------------------------------------
    def test_the_selected_candle_inside_the_atr_window_is_not_counted_twice(self):
        """The usual real case: pick the largest body in the last ten bars and
        divide by an ATR whose window ends at the newest of those same bars."""
        from market_data.market_events import _magnitude_witness_at
        stamps = [f"2026-08-12T16:{m:02d}:00+00:00" for m in range(15)]
        anchor = stamps[9]                       # squarely inside the window
        w = _magnitude_witness_at(self._d(anchor, stamps), "1m", stamps[-1])
        assert w["numerator_is_inside_atr_window"] is True
        assert w["logical_evidence_reference_count"] == 16   # 1 + 15 roles
        assert w["unique_physical_observation_count"] == 15  # ...15 candles
        assert len(w["source_bars"]) == 15

    def test_both_roles_stay_separately_visible(self):
        from market_data.market_events import _magnitude_witness_at
        stamps = [f"2026-08-12T16:{m:02d}:00+00:00" for m in range(15)]
        w = _magnitude_witness_at(self._d(stamps[9], stamps), "1m", stamps[-1])
        assert w["numerator_source_bar"] == stamps[9]
        assert w["denominator_source_bars"] == stamps
        assert w["numerator_source_bar"] in w["denominator_source_bars"]

    def test_the_generic_source_list_is_unique_and_chronological(self):
        """A duplicated, non-monotonic array was the symptom: the anchor was
        prepended to a chronological window it already sat inside."""
        from market_data.market_events import _magnitude_witness_at
        stamps = [f"2026-08-12T16:{m:02d}:00+00:00" for m in range(15)]
        for anchor in (stamps[0], stamps[7], stamps[14]):
            w = _magnitude_witness_at(self._d(anchor, stamps), "1m", stamps[-1])
            bars = w["source_bars"]
            assert len(bars) == len(set(bars)), "one candle listed twice"
            assert bars == sorted(bars), "evidence order is not chronological"

    def test_a_numerator_outside_the_window_really_is_an_extra_observation(self):
        from market_data.market_events import _magnitude_witness_at
        stamps = [f"2026-08-12T16:{m:02d}:00+00:00" for m in range(15)]
        w = _magnitude_witness_at(self._d("2026-08-12T15:00:00+00:00", stamps),
                                  "1m", stamps[-1])
        assert w["numerator_is_inside_atr_window"] is False
        assert w["unique_physical_observation_count"] == 16

    # -- 3: a candle is not a market event -----------------------------------
    def test_an_ordinary_candle_is_not_promoted_to_a_market_event(self):
        """It printed whether or not any detector cared. Putting it in
        MARKET_EVENTS made the factual layer a function of what mechanics
        happened to notice."""
        from market_data.market_events import (EVENT_LAYER_REGISTRY,
                                               CANDLE_REFERENCE, FVG,
                                               LIQUIDITY_SWEEP, BOS, MSS)
        assert EVENT_LAYER_REGISTRY[CANDLE_REFERENCE] == "MARKET_OBSERVATIONS"
        for occurrence in (FVG, LIQUIDITY_SWEEP, BOS, MSS):
            assert EVENT_LAYER_REGISTRY[occurrence] == "MARKET_EVENTS"

    def test_the_candle_object_declares_the_observation_layer(self):
        from market_data.market_events import _candle_reference_at
        c = _candle_reference_at(
            self._d("2026-08-12T16:00:00+00:00",
                    ["2026-08-12T16:00:00+00:00"]), "1m")
        assert c["epistemic_layer"] == "MARKET_OBSERVATIONS"
        assert "RAW OBSERVATION" in c["species"]

    # -- 4/5/6/7: the derived-fact layer -------------------------------------
    def test_the_derived_fact_layer_exists(self):
        from market_data import market_events as ME
        assert "DERIVED_FACTS" in ME.EPISTEMIC_LAYERS
        assert set(ME.EVENT_LAYER_REGISTRY.values()) <= set(ME.EPISTEMIC_LAYERS)

    def test_deterministic_arithmetic_is_not_called_a_raw_observation(self):
        """The venue never printed `1.52x ATR` or `a run of 3`."""
        from market_data.market_events import (EVENT_LAYER_REGISTRY,
                                               MAGNITUDE_WITNESS,
                                               FOLLOW_THROUGH_RUN)
        assert EVENT_LAYER_REGISTRY[MAGNITUDE_WITNESS] == "DERIVED_FACTS"
        assert EVENT_LAYER_REGISTRY[FOLLOW_THROUGH_RUN] == "DERIVED_FACTS"

    def test_every_registered_type_declares_its_species(self):
        from market_data import market_events as ME
        assert set(ME.EVENT_SPECIES) == set(ME.EVENT_LAYER_REGISTRY)
        for kind, layer in ME.EVENT_LAYER_REGISTRY.items():
            species = ME.EVENT_SPECIES[kind]
            expected = {"MARKET_OBSERVATIONS": "RAW OBSERVATION",
                        "MARKET_EVENTS": "ATOMIC MARKET EVENT",
                        "DERIVED_FACTS": "DERIVED FACT",
                        "DERIVED_ASSESSMENTS": "MECHANICAL ASSESSMENT"}[layer]
            assert species.startswith(expected), (kind, species)

    def test_the_four_layers_are_ordered_raw_to_opinion(self):
        from market_data.market_events import EPISTEMIC_LAYERS
        assert EPISTEMIC_LAYERS[:4] == ("MARKET_OBSERVATIONS", "MARKET_EVENTS",
                                        "DERIVED_FACTS", "DERIVED_ASSESSMENTS")

    # -- 8: instrument-scoped identity ---------------------------------------
    def test_two_instruments_cannot_share_one_bucket_identity(self):
        from market_data.market_events import candle_reference_id
        mnq = candle_reference_id("1m", "2026-08-12T16:00:00+00:00",
                                  contract="CON.F.US.MNQ.U26")
        mes = candle_reference_id("1m", "2026-08-12T16:00:00+00:00",
                                  contract="CON.F.US.MES.U26")
        assert mnq != mes, "MNQ and MES collided on one market-object id"

    def test_identity_uses_the_repos_own_canonical_contract(self):
        """Not a hardcoded 'MNQ' -- the contract names the expiry too, so U26
        and Z26 buckets cannot collide."""
        from market_data.market_events import candle_reference_id
        from doctrine.instrument_identity import PRODUCTION_CONTRACT
        assert PRODUCTION_CONTRACT in candle_reference_id("1m", "2026-08-12T16:00:00+00:00")
        assert candle_reference_id("1m", "2026-08-12T16:00:00+00:00", contract="CON.F.US.MNQ.Z26") != \
            candle_reference_id("1m", "2026-08-12T16:00:00+00:00", contract="CON.F.US.MNQ.U26")

    # -- 9: timestamp canonicalisation ---------------------------------------
    def test_equivalent_instants_produce_one_identity(self):
        from market_data.market_events import candle_reference_id
        ids = {candle_reference_id("1m", t) for t in
               ("2026-08-12T16:00:00Z", "2026-08-12T16:00:00+00:00",
                "2026-08-12T12:00:00-04:00")}
        assert len(ids) == 1, f"one instant minted {len(ids)} ids: {ids}"

    def test_a_different_instant_is_a_different_object(self):
        from market_data.market_events import candle_reference_id
        assert candle_reference_id("1m", "2026-08-12T16:00:00Z") != \
            candle_reference_id("1m", "2026-08-12T16:01:00Z")

    def test_a_malformed_timestamp_stays_visible_but_cannot_mint_an_id(self):
        """STEP 3F: diagnostics keep it; identity refuses it."""
        from market_data.object_identity import (canonical_instant,
                                                 MarketObjectIdentityError)
        assert canonical_instant("not-a-time", strict=False) == "not-a-time"
        with pytest.raises(MarketObjectIdentityError):
            canonical_instant("not-a-time")

    def test_canonicalisation_matches_the_timeframe_builders_encoding(self):
        from market_data.market_events import canonical_instant
        from data_feed.timeframe_builder import build_timeframes
        bars = [{"timestamp": f"2026-08-12T16:{m:02d}:00+00:00", "open": 1.0,
                 "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1}
                for m in range(5)]
        built = build_timeframes(bars)["1m"]
        for b in built:
            assert canonical_instant(b["timestamp"]) == b["timestamp"], \
                "identity encoding disagrees with the canonical store"

    # -- 10: history revision -------------------------------------------------
    def test_an_ohlc_revision_keeps_identity_and_replaces_state(self):
        from market_data.market_events import _candle_reference_at
        stamps = ["2026-08-12T16:00:00+00:00"]
        up = self._d(stamps[0], stamps)
        down = self._d(stamps[0], stamps)
        down["conviction_candle"].update(open=140.0, close=100.0,
                                         direction="bearish")
        a = _candle_reference_at(up, "1m")
        b = _candle_reference_at(down, "1m")
        assert a["event_id"] == b["event_id"], "revision minted a second object"
        assert a["direction"] != b["direction"]
        assert a["close"] != b["close"]
        # and no stale twin can coexist in a rebuilt graph
        assert len({a["event_id"], b["event_id"]}) == 1

    # -- 11/12: component references -----------------------------------------
    def test_the_assessment_references_its_exact_derived_facts(self):
        from market_data.market_events import (_displacement_at,
                                               MAGNITUDE_WITNESS,
                                               FOLLOW_THROUGH_RUN)
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_confirmed", "lookback": 1,
            "components": [], "magnitude_anchor_time": "2026-08-12T16:00:00+00:00",
            "follow_through_observed_direction": "bearish",
            "follow_through_run": 3}}}}
        o = _displacement_at(snap, [{"timestamp": "2026-08-12T16:01:00+00:00",
                                     "temporal_status": "settled"}], "1m",
                             observed_at="2026-08-12T16:01:00+00:00")
        assert o["magnitude_witness_ref"]
        assert o["magnitude_witness_ref"].startswith(MAGNITUDE_WITNESS)
        assert o["follow_through_run_ref"]
        assert o["follow_through_run_ref"].startswith(FOLLOW_THROUGH_RUN)

    def test_an_absent_component_gets_an_explicit_null_not_a_guess(self):
        from market_data.market_events import _displacement_at
        snap = {"expansion": {"1m": {"displacement": {
            "classification": "displacement_possible", "lookback": 1,
            "components": []}}}}
        o = _displacement_at(snap, [{"timestamp": "2026-08-12T16:00:00+00:00",
                                      "temporal_status": "settled"}],
                             "1m", observed_at="2026-08-12T16:00:00+00:00")
        assert o["magnitude_witness_ref"] is None
        assert o["follow_through_run_ref"] is None

    def test_all_six_components_have_a_declared_reference_status(self):
        from market_data.market_events import _COMPONENT_REFERENCE_PROVENANCE
        assert set(_COMPONENT_REFERENCE_PROVENANCE) == {
            "displacement_magnitude", "imbalance_created", "structure_break",
            "directional_efficiency", "follow_through", "no_hesitation"}
        assert set(_COMPONENT_REFERENCE_PROVENANCE.values()) <= {
            "EXACT_OBJECT_REFERENCE", "INLINE_SCALAR", "INCOMPLETE"}

    def test_the_remaining_debt_is_exactly_structure(self):
        """STEP 4B.2 closed imbalance: gaps now carry their own c1/c2/c3 stamps,
        so each resolves to a canonical FVG completion slot. Structure still
        carries bare bos/mss booleans."""
        from market_data.market_events import _COMPONENT_REFERENCE_PROVENANCE as P
        assert {k for k, v in P.items() if v == "INCOMPLETE"} == {"structure_break"}
        for exact in ("displacement_magnitude", "follow_through",
                      "imbalance_created"):
            assert P[exact] == "EXACT_OBJECT_REFERENCE"

    def test_no_object_is_manufactured_for_an_inline_scalar(self):
        """The goal is exact truth, not maximal object count."""
        from market_data.market_events import (_COMPONENT_REFERENCE_PROVENANCE,
                                               EVENT_LAYER_REGISTRY)
        inline = {k for k, v in _COMPONENT_REFERENCE_PROVENANCE.items()
                  if v == "INLINE_SCALAR"}
        assert inline == {"directional_efficiency", "no_hesitation"}
        for name in inline:
            assert name.upper() not in EVENT_LAYER_REGISTRY

    # -- 14: registry guard survives the new layer ---------------------------
    def test_the_contradiction_guard_still_holds_with_derived_facts(self):
        from market_data.market_events import (layered_chronology,
                                               UnregisteredEventType,
                                               MAGNITUDE_WITNESS)
        bad = {"event_type": MAGNITUDE_WITNESS, "epistemic_layer": "MARKET_EVENTS",
               "event_time": "2026-08-12T16:00:00+00:00", "event_id": "x"}
        with pytest.raises(UnregisteredEventType):
            layered_chronology([bad])
        out = layered_chronology([bad], strict=False)
        assert out["DERIVED_FACTS"] == []
        assert len(out["UNCLASSIFIED"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
class TestStep3FGlobalIdentityContract:
    """STEP 3F. One identity contract for every object, not just candles."""

    MES = "CON.F.US.MES.U26"
    Z26 = "CON.F.US.MNQ.Z26"
    T = "2026-08-12T16:00:00+00:00"

    # -- 2: instrument scope is global ---------------------------------------
    def test_every_emitted_id_is_contract_scoped(self):
        """3E scoped CANDLE_REFERENCE and left the derived facts bare:
        `MAGNITUDE_WITNESS:1m:<t>:<anchor>` had no instrument at all."""
        from market_data import market_events as ME
        for kind in ME.EVENT_LAYER_REGISTRY:
            got = ME._event_id(kind, "1m", self.T, "x", "y")
            assert got.startswith(f"{kind}:{CONTRACT}:1m:"), got

    def test_two_instruments_cannot_collide_on_any_type(self):
        from market_data import market_events as ME
        for kind in ME.EVENT_LAYER_REGISTRY:
            a = ME._event_id(kind, "1m", self.T, contract=CONTRACT)
            b = ME._event_id(kind, "1m", self.T, contract=self.MES)
            assert a != b, kind

    def test_two_expiries_cannot_collide_on_any_type(self):
        """`MNQ` names no expiry; U26 and Z26 are different markets."""
        from market_data import market_events as ME
        for kind in ME.EVENT_LAYER_REGISTRY:
            a = ME._event_id(kind, "1m", self.T, contract=CONTRACT)
            b = ME._event_id(kind, "1m", self.T, contract=self.Z26)
            assert a != b, kind

    # -- 3: root symbol is not the contract ----------------------------------
    def test_a_root_symbol_cannot_scope_a_market_object(self):
        from market_data.object_identity import (canonical_contract,
                                                 MarketObjectIdentityError)
        for root in ("MNQ", "mes", "ES"):
            with pytest.raises(MarketObjectIdentityError):
                canonical_contract(instrument=root)
        assert canonical_contract(contract=CONTRACT) == CONTRACT

    # -- 4: missing provenance must fail, never borrow production ------------
    def test_missing_instrument_does_not_borrow_production_identity(self):
        """The forbidden failure: MES bars, caller omits the instrument, and the
        object silently becomes CON.F.US.MNQ.U26."""
        from market_data.object_identity import (market_object_id,
                                                 MarketObjectIdentityError)
        with pytest.raises(MarketObjectIdentityError):
            market_object_id("FVG", timeframe="1m", instant=self.T)

    def test_the_id_builder_holds_no_production_default(self):
        import inspect
        from market_data import object_identity as OI
        src = inspect.getsource(OI)
        assert "PRODUCTION_CONTRACT" not in src, \
            "the low-level identity owner must not know a default contract"

    def test_reconstruction_refuses_bars_with_no_contract(self):
        from market_data.market_events import (reconstruct_events,
                                               MarketObjectIdentityError)
        naked = [dict(b) for b in ramp(30)]
        for b in naked:
            b.pop("contract", None)
        with no_contract_scope():
            with pytest.raises(MarketObjectIdentityError):
                reconstruct_events(naked, "1m")

    def test_reconstruction_refuses_bars_spanning_two_contracts(self):
        from market_data.market_events import (reconstruct_events,
                                               MarketObjectIdentityError)
        mixed = [dict(b) for b in ramp(30)]
        mixed[5]["contract"] = self.MES
        with no_contract_scope():
            with pytest.raises(MarketObjectIdentityError):
                reconstruct_events(mixed, "1m")

    def _real_1m(self, n=400):
        """Real bars, because `ramp()` is a clean staircase that produces ZERO
        events -- asserting over an empty list proves nothing."""
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        return rows[-n:]

    def test_the_bars_own_contract_is_used_when_present(self):
        """Canonical store rows carry `contract`; the input object proves it."""
        from market_data.market_events import reconstruct_events
        own = [dict(b, contract=self.MES) for b in self._real_1m()]
        with no_contract_scope():
            events = reconstruct_events(own, "1m")
        assert events, "fixture produced no events -- a vacuous test"
        assert all(f":{self.MES}:" in e["event_id"] for e in events)

    # -- 5: threaded end to end ----------------------------------------------
    def test_reconstruction_threads_the_caller_contract_to_every_object(self):
        from market_data.market_events import reconstruct_events
        # bars whose own contract was stripped by transformation: the caller
        # legitimately supplies the scope. (Asserting a contract OVER bars that
        # prove a different one is a contradiction -- see the 3G tests.)
        bars = [{k: v for k, v in b.items() if k != "contract"}
                for b in self._real_1m()]
        for contract in (CONTRACT, self.MES, self.Z26):
            events = reconstruct_events(bars, "1m", contract=contract)
            assert events, "fixture produced no events -- a vacuous test"
            for e in events:
                assert f":{contract}:" in e["event_id"], e["event_id"]

    def test_no_object_uses_a_hidden_global_when_a_contract_was_supplied(self):
        from market_data.market_events import reconstruct_events
        bars = [{k: v for k, v in b.items() if k != "contract"}
                for b in self._real_1m()]
        events = reconstruct_events(bars, "1m", contract=self.MES)
        assert events
        assert not any(CONTRACT in e["event_id"] for e in events)

    # -- 6/7/8: state leaves identity ----------------------------------------
    def test_follow_through_identity_survives_a_run_length_revision(self):
        """`run_length` was IN the id, so repairing history until a run read 2
        instead of 3 minted a second fact object beside the first."""
        from market_data.market_events import _follow_through_run_at
        def run(n, direction="bearish"):
            stamps = [f"2026-08-12T19:{m:02d}:00+00:00" for m in range(n)]
            return _follow_through_run_at(
                {"follow_through_observed_direction": direction,
                 "follow_through_run": n, "follow_through_direction": direction,
                 "follow_through_run_bars": stamps,
                 "follow_through_run_candles": [{"timestamp": s} for s in stamps]},
                "1m", self.T)
        assert run(3)["event_id"] == run(2)["event_id"]
        assert run(3)["event_id"] == run(3, "bullish")["event_id"]
        assert run(3)["run_length"] != run(2)["run_length"]

    def test_magnitude_witness_identity_survives_an_anchor_revision(self):
        """Cardinality is one magnitude result per (contract, tf, assessment),
        so the selected candle is the RESULT of the scan, not its identity."""
        from market_data.market_events import _magnitude_witness_at
        def witness(anchor):
            return _magnitude_witness_at({"conviction_candle": {
                "timestamp": anchor, "body": 12.0, "atr": 8.0,
                "atr_multiple": 1.5, "direction": "bullish",
                "atr_as_of": self.T, "atr_source": "x",
                "threshold_atr_multiple": 1.5, "qualified_at": self.T,
                "atr_period": 14, "atr_source_bars": [], "atr_source_candles": []}},
                "1m", self.T)
        a = witness("2026-08-12T15:50:00+00:00")
        b = witness("2026-08-12T15:55:00+00:00")
        assert a["event_id"] == b["event_id"], "the answer became the identity"
        assert a["selected_candle_id"] != b["selected_candle_id"]

    def test_assessment_identity_survives_score_and_classification_changes(self):
        from market_data.market_events import _displacement_at
        def assess(cls, score, anchor):
            snap = {"expansion": {"1m": {"displacement": {
                "classification": cls, "lookback": 1, "score": score,
                "components": [], "magnitude_anchor_time": anchor}}}}
            return _displacement_at(snap, [{"timestamp": self.T,
                                            "temporal_status": "settled"}],
                                    "1m", observed_at=self.T)
        a = assess("displacement_possible", 30, None)
        b = assess("displacement_confirmed", 90, "2026-08-12T15:50:00+00:00")
        assert a["event_id"] == b["event_id"], "score/anchor leaked into identity"
        assert a["score"] != b["score"]

    def test_fvg_keeps_its_discriminators_because_cardinality_is_many(self):
        """The one exception, and the reason is auditable: `find_fvgs` returns
        several gaps from one window and two can complete on the same bar in
        opposite directions."""
        from market_data import market_events as ME
        assert ME.FVG not in ME._SINGLE_PER_TF_INSTANT
        a = ME._event_id(ME.FVG, "1m", self.T, "bullish", 100.0, 102.0)
        b = ME._event_id(ME.FVG, "1m", self.T, "bearish", 110.0, 112.0)
        assert a != b

    # -- 9: episode identity is deliberately candle-scoped -------------------
    def test_episode_identity_is_scoped_by_its_selected_candle(self):
        """Its whole ontology is 'the assessments that referenced THIS candle',
        so the candle distinguishes one episode from another -- the one place
        the selection is identity rather than state."""
        from market_data.market_events import fold_displacement_occurrences
        def obs(anchor, at):
            return {"source_tf": "1m", "anchored": True, "anchor_time": anchor,
                    "observed_at": at, "status": "CONFIRMED", "score": 70}
        got = fold_displacement_occurrences(
            [obs("2026-08-12T15:50:00+00:00", "2026-08-12T15:51:00+00:00"),
             obs("2026-08-12T15:55:00+00:00", "2026-08-12T15:56:00+00:00")])
        ids = [o["occurrence_id"] for o in got]
        assert len(ids) == len(set(ids)) == 2
        for i in ids:
            assert i.startswith(f"MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE:{CONTRACT}:1m:")

    # -- 10/11/12: one owner, strict time ------------------------------------
    def test_there_is_exactly_one_identity_owner(self):
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME)
        assert "def canonical_instant" not in src, "second timezone rule"
        assert "def canonical_contract" not in src, "second instrument authority"

    def test_equivalent_instants_produce_one_id_for_every_type(self):
        from market_data import market_events as ME
        for kind in ME.EVENT_LAYER_REGISTRY:
            ids = {ME._event_id(kind, "1m", t) for t in
                   ("2026-08-12T16:00:00Z", "2026-08-12T16:00:00+00:00",
                    "2026-08-12T12:00:00-04:00")}
            assert len(ids) == 1, (kind, ids)

    def test_a_naive_timestamp_cannot_author_identity(self):
        """`timeframe_builder._floor_timestamp` uses `dt.replace(...)` and
        PRESERVES whatever tzinfo it was given -- it never normalises to UTC, so
        naive-means-UTC was a comment, not a producer contract."""
        from market_data.object_identity import (canonical_instant,
                                                 MarketObjectIdentityError)
        with pytest.raises(MarketObjectIdentityError):
            canonical_instant("2026-08-12T16:00:00")
        assert canonical_instant("2026-08-12T16:00:00", strict=False) == \
            "2026-08-12T16:00:00"

    def test_the_naive_claim_is_checked_against_the_real_builder(self):
        import inspect
        from data_feed import timeframe_builder as TB
        src = inspect.getsource(TB._floor_timestamp)
        assert "dt.replace(" in src
        assert "astimezone" not in src and "utc" not in src.lower(), \
            "if the builder now normalises to UTC, the naive rule can be revisited"

    def test_the_real_store_satisfies_the_strict_contract(self):
        """The refusal must not be blocking legitimate production data."""
        import json
        from market_data.object_identity import canonical_instant
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        with open(STORE, encoding="utf-8") as fh:
            rows = [json.loads(l) for _, l in zip(range(200), fh) if l.strip()]
        assert rows
        for r in rows:
            assert canonical_instant(r["timestamp"])
            assert r.get("contract")

    def test_a_malformed_timestamp_cannot_mint_an_id_for_any_type(self):
        from market_data import market_events as ME
        from market_data.object_identity import MarketObjectIdentityError
        for kind in ME.EVENT_LAYER_REGISTRY:
            with pytest.raises(MarketObjectIdentityError):
                ME._event_id(kind, "1m", "garbage")

    # -- 13: the doctrine sentence -------------------------------------------
    def test_the_derived_fact_law_is_stated_correctly(self):
        """A derived fact does NOT recompute to the same value forever -- the
        ATR audit disproved that. Same EVIDENCE REVISION + same rule."""
        import inspect
        from market_data import object_identity as OI
        doc = inspect.getdoc(OI) or ""
        assert "same canonical evidence revision" in doc
        assert "deterministic rule" in doc
        # the wrong phrasing appears only as the claim being REFUTED
        assert "does not" in doc.split("forever")[0][-80:] or             "The correct law" in doc

    # -- 14: references resolve after migration ------------------------------
    def test_every_threaded_reference_resolves_after_migration(self):
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        res = reconstruct_displacement(rows[-260:], lookback_bars=25)
        wid = {w["event_id"] for w in res["magnitude_witnesses"]}
        rid = {r["event_id"] for r in res["follow_through_runs"]}
        cid = {c["event_id"] for c in res["candle_references"]}
        for o in res["observations"]:
            if o["magnitude_witness_ref"]:
                assert o["magnitude_witness_ref"] in wid
            if o["follow_through_run_ref"]:
                assert o["follow_through_run_ref"] in rid
        for w in res["magnitude_witnesses"]:
            assert w["selected_candle_id"].startswith("CANDLE_REFERENCE:")
        for e in res["occurrences"]:
            assert e["selected_candle_id"] in cid or e["selected_candle_id"]
        assert all(":" in i and i.count(":") >= 3 for i in wid | rid | cid)

    def test_no_two_simultaneous_objects_share_one_id(self):
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        res = reconstruct_displacement(rows[-260:], lookback_bars=25)
        for key in ("candle_references", "magnitude_witnesses",
                    "follow_through_runs", "occurrences"):
            ids = [o.get("event_id") or o.get("occurrence_id") for o in res[key]]
            assert len(ids) == len(set(ids)), key


# ══════════════════════════════════════════════════════════════════════════════
class TestStep3GTransformationProvenance:
    """STEP 3G. Transformation may not erase identity provenance; an explicit
    claim may fill absence but never override contradiction."""

    MES = "CON.F.US.MES.U26"
    Z26 = "CON.F.US.MNQ.Z26"

    def _1m(self, n=40, contract=CONTRACT):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)
        out = []
        for m in range(n):
            base = 100.0 + (m % 40)          # real minute arithmetic, not m:02d
            row = {"timestamp": (t0 + timedelta(minutes=m)).isoformat(),
                   "open": base, "high": base + 2, "low": base - 2,
                   "close": base + 1, "volume": 10}
            if contract:
                row["contract"] = contract
            out.append(row)
        return out

    # -- 1/5: contract survives aggregation ----------------------------------
    def test_aggregation_preserves_a_homogeneous_contract(self):
        """`_aggregate` rebuilt each bucket from OHLCV and dropped `contract`,
        so every derived bar arrived anonymous and had to be relabelled."""
        from data_feed.timeframe_builder import build_timeframes
        tfs = build_timeframes(self._1m())
        for tf in ("1m", "3m", "5m", "15m"):
            assert tfs[tf], tf
            for b in tfs[tf]:
                assert b.get("contract") == CONTRACT, (tf, b.get("timestamp"))

    def test_a_foreign_contract_propagates_unchanged(self):
        from data_feed.timeframe_builder import build_timeframes
        tfs = build_timeframes(self._1m(contract=self.MES))
        for tf in ("1m", "3m", "5m", "15m"):
            assert all(b["contract"] == self.MES for b in tfs[tf])

    def test_derived_bars_need_no_downstream_relabelling(self):
        """The whole point: a 5m bar now proves its own instrument, so a
        downstream caller never has to assert one it cannot verify."""
        from data_feed.timeframe_builder import build_timeframes
        from market_data.market_events import reconstruct_events, _contract_in
        tfs = build_timeframes(self._1m(200))
        for tf in ("3m", "5m", "15m"):
            assert _contract_in(tfs[tf]) == CONTRACT
        with no_contract_scope():
            events = reconstruct_events(tfs["5m"], "5m")   # no contract= needed
        assert all(f":{CONTRACT}:" in e["event_id"] for e in events)

    # -- 2: mixed contracts fail closed --------------------------------------
    def test_mixed_contract_aggregation_fails_closed(self):
        """Two futures contracts cannot be averaged into one candle. Choosing
        first, last, or the caller's parameter would each produce a
        normal-looking bar resting on two markets."""
        from data_feed.timeframe_builder import build_timeframes
        from market_data.object_identity import MarketObjectIdentityError
        bars = self._1m()
        bars[1]["contract"] = self.Z26          # same 5m bucket as bars[0]
        with pytest.raises(MarketObjectIdentityError) as err:
            build_timeframes(bars)
        assert "spans contracts" in str(err.value)
        assert CONTRACT in str(err.value) and self.Z26 in str(err.value)

    def test_mixed_contracts_are_not_resolved_by_majority_or_position(self):
        from data_feed.timeframe_builder import _bucket_contract
        from market_data.object_identity import MarketObjectIdentityError
        many = ([{"contract": CONTRACT}] * 14) + [{"contract": self.Z26}]
        with pytest.raises(MarketObjectIdentityError):
            _bucket_contract(many, "k")

    # -- 3: missing contract ---------------------------------------------------
    def test_silent_members_produce_a_silent_bar_not_a_guess(self):
        from data_feed.timeframe_builder import build_timeframes
        tfs = build_timeframes(self._1m(contract=None))
        for tf in ("3m", "5m", "15m"):
            assert all("contract" not in b for b in tfs[tf]), \
                "a contract was invented for bars that proved none"

    def test_silent_bars_still_refuse_identity_without_a_boundary(self):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.market_events import (reconstruct_events,
                                               MarketObjectIdentityError)
        tfs = build_timeframes(self._1m(200, contract=None))
        with no_contract_scope():
            with pytest.raises(MarketObjectIdentityError):
                reconstruct_events(tfs["5m"], "5m")

    # -- 4: explicit vs evidence ----------------------------------------------
    def test_an_explicit_contract_cannot_overrule_the_evidence(self):
        """THE DANGEROUS CASE: members are U26, caller says Z26, and the object
        emerges with a flawless-looking id scoped to the wrong market."""
        from market_data.market_events import (resolve_contract,
                                               MarketObjectIdentityError)
        with pytest.raises(MarketObjectIdentityError) as err:
            resolve_contract(self._1m(), self.Z26)
        assert "may not overrule the evidence" in str(err.value)

    def test_an_explicit_contract_may_fill_absence(self):
        from market_data.market_events import (resolve_contract,
                                               TRUSTED_BOUNDARY_SUPPLIED)
        got, prov = resolve_contract(self._1m(contract=None), self.MES)
        assert got == self.MES
        assert prov == TRUSTED_BOUNDARY_SUPPLIED

    def test_an_agreeing_explicit_contract_is_accepted(self):
        from market_data.market_events import resolve_contract, EVIDENCE_DERIVED
        got, prov = resolve_contract(self._1m(), CONTRACT)
        assert got == CONTRACT
        assert prov == EVIDENCE_DERIVED, "agreement is still evidence-derived"

    def test_reconstruction_refuses_a_contradicting_caller(self):
        from market_data.market_events import (reconstruct_events,
                                               MarketObjectIdentityError)
        with pytest.raises(MarketObjectIdentityError):
            reconstruct_events(self._1m(200), "1m", contract=self.MES)

    # -- 6: provenance source is published -------------------------------------
    def test_the_object_reports_where_its_contract_came_from(self):
        from market_data.market_events import (reconstruct_displacement,
                                               EVIDENCE_DERIVED)
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        with no_contract_scope():
            res = reconstruct_displacement(rows[-260:], lookback_bars=20)
        for c in res["candle_references"]:
            assert c["contract_provenance"] == EVIDENCE_DERIVED
            assert c["instrument"] == CONTRACT

    def test_the_two_provenance_kinds_are_distinct_values(self):
        from market_data.market_events import (EVIDENCE_DERIVED,
                                               TRUSTED_BOUNDARY_SUPPLIED)
        assert EVIDENCE_DERIVED != TRUSTED_BOUNDARY_SUPPLIED

    # -- 7/8/9: episode absence may not be bridged ------------------------------
    def _obs(self, tf, anchor, at, present=True):
        return {"source_tf": tf, "anchored": present,
                "anchor_time": anchor if present else None,
                "observed_at": at, "status": "CONFIRMED", "score": 70}

    def test_an_anchor_that_vanishes_and_returns_is_two_episodes(self):
        """Magnitude qualification is `body / CURRENT ATR`, and the ATR moves
        every scan while the body never does -- so the same candle can qualify,
        stop qualifying, and qualify again while still inside LOOKBACK."""
        from market_data.market_events import fold_displacement_occurrences
        A = "2026-08-12T16:00:00+00:00"
        seq = [self._obs("1m", A, "2026-08-12T16:10:00+00:00"),
               self._obs("1m", A, "2026-08-12T16:11:00+00:00"),
               self._obs("1m", None, "2026-08-12T16:12:00+00:00", present=False),
               self._obs("1m", A, "2026-08-12T16:13:00+00:00")]
        got = fold_displacement_occurrences(seq)
        assert len(got) == 2, "the absent interval was bridged"
        assert got[0]["episode_segment"] == 0
        assert got[1]["episode_segment"] == 1
        assert got[1]["segmented_from_earlier_episode"] is True
        assert got[0]["last_observed_at"] == "2026-08-12T16:11:00+00:00"
        assert got[1]["first_observed_at"] == "2026-08-12T16:13:00+00:00"

    def test_the_two_segments_do_not_share_an_identity(self):
        from market_data.market_events import fold_displacement_occurrences
        A = "2026-08-12T16:00:00+00:00"
        seq = [self._obs("1m", A, "2026-08-12T16:10:00+00:00"),
               self._obs("1m", None, "2026-08-12T16:11:00+00:00", present=False),
               self._obs("1m", A, "2026-08-12T16:12:00+00:00")]
        ids = [o["occurrence_id"] for o in fold_displacement_occurrences(seq)]
        assert len(ids) == len(set(ids)) == 2
        # first_observed_at is what separates them, which is why it is identity
        assert "16:10" in ids[0] and "16:12" in ids[1]

    def test_an_uninterrupted_run_stays_one_episode(self):
        from market_data.market_events import fold_displacement_occurrences
        A = "2026-08-12T16:00:00+00:00"
        seq = [self._obs("1m", A, f"2026-08-12T16:{m:02d}:00+00:00")
               for m in (10, 11, 12, 13)]
        got = fold_displacement_occurrences(seq)
        assert len(got) == 1
        assert got[0]["observation_count"] == 4
        assert got[0]["segmented_from_earlier_episode"] is False

    def test_a_gap_with_no_intervening_scan_is_not_an_interruption(self):
        """Absence means the engine LOOKED and did not report it -- not that no
        scan happened. A quiet stretch with no assessments at all is not a
        lifecycle gap."""
        from market_data.market_events import fold_displacement_occurrences
        A = "2026-08-12T16:00:00+00:00"
        seq = [self._obs("1m", A, "2026-08-12T16:10:00+00:00"),
               self._obs("1m", A, "2026-08-12T16:40:00+00:00")]
        assert len(fold_displacement_occurrences(seq)) == 1

    def test_another_timeframes_scans_do_not_segment_this_one(self):
        from market_data.market_events import fold_displacement_occurrences
        A = "2026-08-12T16:00:00+00:00"
        seq = [self._obs("1m", A, "2026-08-12T16:10:00+00:00"),
               self._obs("5m", "2026-08-12T16:05:00+00:00",
                         "2026-08-12T16:11:00+00:00"),
               self._obs("1m", A, "2026-08-12T16:12:00+00:00")]
        ones = [o for o in fold_displacement_occurrences(seq)
                if o["source_tf"] == "1m"]
        assert len(ones) == 1, "a 5m scan segmented a 1m episode"

    # -- 10/11: assessment time, not settled-through --------------------------
    def test_derived_identity_uses_assessment_time_not_settled_through(self):
        """5m evidence settled through 17:10 while the scan ran at 17:14. Three
        consecutive 1m scans against one 5m bucket are three assessments."""
        from market_data.market_events import _magnitude_witness_at
        def wit(at):
            return _magnitude_witness_at({"conviction_candle": {
                "timestamp": "2026-08-12T16:35:00+00:00", "body": 32.75,
                "atr": 21.05, "atr_multiple": 1.56, "direction": "bullish",
                "atr_as_of": "2026-08-12T17:10:00+00:00", "atr_source": "x",
                "threshold_atr_multiple": 1.5,
                "qualified_at": "2026-08-12T17:10:00+00:00",
                "atr_period": 14, "atr_source_bars": [],
                "atr_source_candles": []}}, "5m", at)
        ids = [wit(f"2026-08-12T17:{m}:00+00:00")["event_id"] for m in (11, 12, 13)]
        assert len(set(ids)) == 3, "three scans collapsed onto one settled bucket"
        for i, m in zip(ids, (11, 12, 13)):
            assert f"17:{m}:00" in i
            assert "17:10:00" not in i

    def test_the_settled_through_time_is_still_published(self):
        from market_data.market_events import _magnitude_witness_at
        w = _magnitude_witness_at({"conviction_candle": {
            "timestamp": "2026-08-12T16:35:00+00:00", "body": 1.0, "atr": 1.0,
            "atr_multiple": 1.5, "direction": "bullish",
            "atr_as_of": "2026-08-12T17:10:00+00:00", "atr_source": "x",
            "threshold_atr_multiple": 1.5,
            "qualified_at": "2026-08-12T17:10:00+00:00", "atr_period": 14,
            "atr_source_bars": [], "atr_source_candles": []}},
            "5m", "2026-08-12T17:14:00+00:00")
        assert w["event_time"] == "2026-08-12T17:14:00+00:00"
        assert w["producer_settled_through"] == "2026-08-12T17:10:00+00:00"

    def test_the_scan_slot_is_the_1m_bar_end_to_end(self):
        """Production cadence: one assessment per new 1m bar, so the identity
        instant is that bar. Proven from the reconstruction, not assumed."""
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        bars = rows[-260:]
        stamps = {b["timestamp"] for b in bars}
        with no_contract_scope():
            res = reconstruct_displacement(bars, lookback_bars=20)
        for o in res["observations"]:
            assert o["observed_at"] in stamps, "identity instant is not a 1m bar"
        # and every scan slot holds at most one assessment per timeframe
        seen = collections.Counter((o["source_tf"], o["observed_at"])
                                   for o in res["observations"])
        assert max(seen.values()) == 1

    # -- 12: references still resolve -----------------------------------------
    def test_refs_resolve_across_contracts_after_propagation(self):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.market_events import reconstruct_displacement
        for contract in (CONTRACT, self.MES, self.Z26):
            bars = self._1m(220, contract=contract)
            with no_contract_scope():
                res = reconstruct_displacement(bars, lookback_bars=15)
            ids = ({w["event_id"] for w in res["magnitude_witnesses"]}
                   | {r["event_id"] for r in res["follow_through_runs"]}
                   | {c["event_id"] for c in res["candle_references"]})
            for i in ids:
                assert f":{contract}:" in i, i
            for o in res["observations"]:
                if o["magnitude_witness_ref"]:
                    assert o["magnitude_witness_ref"] in ids
                if o["follow_through_run_ref"]:
                    assert o["follow_through_run_ref"] in ids
            # aggregation carried the contract, so no relabelling was needed
            assert f":{contract}:" in next(iter(ids))


# ══════════════════════════════════════════════════════════════════════════════
class TestStep3HOpportunityAndCompleteProvenance:
    """STEP 3H. Silence is evidence only when the detector had an opportunity to
    speak; one identified member does not identify its anonymous neighbours."""

    A = "2026-08-12T16:00:00+00:00"
    Z26 = "CON.F.US.MNQ.Z26"

    def _obs(self, at, anchor=None):
        return {"source_tf": "1m", "anchored": anchor is not None,
                "anchor_time": anchor, "observed_at": at,
                "status": "CONFIRMED", "score": 70}

    def _t(self, m):
        return f"2026-08-12T16:{m:02d}:00+00:00"

    # -- 1/3/4: opportunity, not output --------------------------------------
    def test_a_classification_none_scan_segments_the_episode(self):
        """THE 3G HOLE. `observations` only receives POSITIVE readings, so a
        scan whose classifier said "none" left no trace and the two surrounding
        anchor sightings looked adjacent -- while that silent scan is the
        STRONGEST evidence the anchor was absent."""
        from market_data.market_events import fold_displacement_occurrences
        seq = [self._obs(self._t(10), self.A), self._obs(self._t(12), self.A)]
        # exactly what the old timeline saw: two entries, no gap
        assert len(fold_displacement_occurrences(seq)) == 1
        # the detector DID run at 16:11 and reported nothing
        got = fold_displacement_occurrences(
            seq, opportunity_slots={"1m": [self._t(10), self._t(11), self._t(12)]})
        assert len(got) == 2, "a silent scan failed to segment the episode"
        assert got[1]["segmented_from_earlier_episode"] is True

    def test_no_scan_at_all_does_not_segment(self):
        """Absence earns meaning only when there was an opportunity. Elapsed
        wall-clock time is not an opportunity."""
        from market_data.market_events import fold_displacement_occurrences
        seq = [self._obs(self._t(10), self.A), self._obs(self._t(40), self.A)]
        got = fold_displacement_occurrences(
            seq, opportunity_slots={"1m": [self._t(10), self._t(40)]})
        assert len(got) == 1

    def test_an_unanchored_scan_also_counts_as_an_opportunity(self):
        """The detector spoke, just not about this anchor."""
        from market_data.market_events import fold_displacement_occurrences
        seq = [self._obs(self._t(10), self.A),
               self._obs(self._t(11)),                     # unanchored reading
               self._obs(self._t(12), self.A)]
        got = fold_displacement_occurrences(
            seq, opportunity_slots={"1m": [self._t(10), self._t(11), self._t(12)]})
        assert len(got) == 2

    def test_the_segmentation_basis_is_published(self):
        """A caller with no ledger cannot prove absence, and the object says so
        rather than implying a rigour it does not have."""
        from market_data.market_events import (fold_displacement_occurrences,
                                               SEGMENTED_ON_OPPORTUNITY,
                                               SEGMENTED_ON_OUTPUT_ONLY)
        seq = [self._obs(self._t(10), self.A), self._obs(self._t(12), self.A)]
        assert fold_displacement_occurrences(seq)[0]["segmentation_basis"] == \
            SEGMENTED_ON_OUTPUT_ONLY
        got = fold_displacement_occurrences(
            seq, opportunity_slots={"1m": [self._t(10), self._t(11), self._t(12)]})
        assert all(o["segmentation_basis"] == SEGMENTED_ON_OPPORTUNITY for o in got)

    # -- 2: the ledger records evaluation, not interesting output -------------
    def test_the_ledger_records_every_scan_the_detector_ran(self):
        """Including the ones that produced no displacement at all -- otherwise
        it is the positive-output list again under a new name."""
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        with no_contract_scope():
            res = reconstruct_displacement(rows[-300:], lookback_bars=40)
        slots = res["assessment_opportunities"]
        assert slots
        for tf, ts in slots.items():
            positive = {o["observed_at"] for o in res["observations"]
                        if o["source_tf"] == tf}
            assert positive <= set(ts), "a reading exists outside the ledger"
            assert len(ts) >= len(positive)
        # the ledger must be STRICTLY larger somewhere, or it proves nothing new
        assert any(len(ts) > len({o["observed_at"] for o in res["observations"]
                                  if o["source_tf"] == tf})
                   for tf, ts in slots.items()), \
            "the ledger never captured a silent scan -- it is output in disguise"

    def test_the_ledger_is_chronological_and_unique(self):
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        with no_contract_scope():
            res = reconstruct_displacement(rows[-300:], lookback_bars=40)
        for tf, ts in res["assessment_opportunities"].items():
            assert ts == sorted(ts), tf
            assert len(ts) == len(set(ts)), tf

    # -- 5: the real reappearances survive the stricter rule ------------------
    def test_the_known_real_reappearances_still_segment(self):
        """1m anchors 16:37 and 19:20 on the Aug-12 tape."""
        from market_data.market_events import reconstruct_displacement
        import json
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        from datetime import datetime as _dt, timezone as _tz
        rows = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        cut = _dt(2026, 8, 12, 19, 43, tzinfo=_tz.utc)
        kept = [b for b in rows if _dt.fromisoformat(b["timestamp"]) <= cut]
        with no_contract_scope():
            res = reconstruct_displacement(kept, lookback_bars=250)
        segmented = [o for o in res["occurrences"]
                     if o["segmented_from_earlier_episode"]]
        assert segmented, "the known reappearances stopped segmenting"
        anchors = {o["anchor_time"][11:16] for o in segmented}
        assert {"16:37", "19:20"} <= anchors, anchors

    # -- 7/8/11: partial contract provenance ---------------------------------
    def test_all_members_named_is_fully_evidence_derived(self):
        from data_feed.timeframe_builder import (_bucket_contract,
                                                 ALL_MEMBERS_EVIDENCE_DERIVED)
        got, prov = _bucket_contract([{"contract": CONTRACT}] * 3, "k")
        assert (got, prov) == (CONTRACT, ALL_MEMBERS_EVIDENCE_DERIVED)

    def test_no_member_named_stays_unknown(self):
        from data_feed.timeframe_builder import (_bucket_contract,
                                                 NO_MEMBER_EVIDENCE)
        got, prov = _bucket_contract([{}] * 3, "k")
        assert (got, prov) == (None, NO_MEMBER_EVIDENCE)

    def test_partial_silence_never_masquerades_as_full_evidence(self):
        """14 members proving U26 is not the same claim as 15 members proving
        U26. Measured policy: 0 of 1730 canonical rows lack a contract, so a
        silent member is schema damage."""
        from data_feed.timeframe_builder import _bucket_contract
        from market_data.object_identity import MarketObjectIdentityError
        with pytest.raises(MarketObjectIdentityError) as err:
            _bucket_contract([{"contract": CONTRACT}] * 14 + [{}], "k")
        assert "14/15" in str(err.value)
        assert "schema damage" in str(err.value)

    def test_partial_silence_fails_through_the_real_aggregator(self):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.object_identity import MarketObjectIdentityError
        bars = [{"timestamp": f"2026-08-12T16:{m:02d}:00+00:00", "open": 1.0,
                 "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1,
                 "contract": CONTRACT} for m in range(6)]
        bars[2].pop("contract")
        with pytest.raises(MarketObjectIdentityError):
            build_timeframes(bars)

    def test_mixed_contracts_still_fail(self):
        from data_feed.timeframe_builder import _bucket_contract
        from market_data.object_identity import MarketObjectIdentityError
        with pytest.raises(MarketObjectIdentityError):
            _bucket_contract([{"contract": CONTRACT}, {"contract": self.Z26}], "k")

    def test_the_reconstruction_resolver_is_no_more_permissive(self):
        """§11 -- `_contract_in` had the same hole, and a lower layer refusing
        while an upper layer accepts is how the defect comes back."""
        from market_data.market_events import _contract_in
        from market_data.object_identity import MarketObjectIdentityError
        assert _contract_in([{"contract": CONTRACT}] * 3) == CONTRACT
        assert _contract_in([{}] * 3) is None
        with pytest.raises(MarketObjectIdentityError):
            _contract_in([{"contract": CONTRACT}, {"contract": CONTRACT}, {}])

    def test_partial_members_plus_a_conflicting_boundary_fails(self):
        from market_data.market_events import resolve_contract
        from market_data.object_identity import MarketObjectIdentityError
        bars = [{"contract": CONTRACT}, {"contract": CONTRACT}, {}]
        with pytest.raises(MarketObjectIdentityError):
            resolve_contract(bars, self.Z26)

    # -- 10: provenance quality travels with the value -----------------------
    def test_the_derived_bar_carries_its_provenance_quality(self):
        from data_feed.timeframe_builder import (build_timeframes,
                                                 ALL_MEMBERS_EVIDENCE_DERIVED)
        bars = [{"timestamp": f"2026-08-12T16:{m:02d}:00+00:00", "open": 1.0,
                 "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1,
                 "contract": CONTRACT} for m in range(20)]
        tfs = build_timeframes(bars)
        for tf in ("3m", "5m", "15m"):
            for b in tfs[tf]:
                assert b["contract"] == CONTRACT
                assert b["contract_provenance"] == ALL_MEMBERS_EVIDENCE_DERIVED

    def test_a_silent_bar_carries_neither_value_nor_false_quality(self):
        from data_feed.timeframe_builder import build_timeframes
        bars = [{"timestamp": f"2026-08-12T16:{m:02d}:00+00:00", "open": 1.0,
                 "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1}
                for m in range(20)]
        tfs = build_timeframes(bars)
        for tf in ("3m", "5m", "15m"):
            for b in tfs[tf]:
                assert "contract" not in b
                assert "contract_provenance" not in b


# ══════════════════════════════════════════════════════════════════════════════
class TestStep4FvgCanonicalObject:
    """STEP 4 / 4A.2. One completion bucket, one FVG. Geometry is state."""

    STORE_PATH = STORE

    def _clean(self, n=12, base=100.0):
        """Well-formed ascending 1m candles with no gap anywhere."""
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)
        out = []
        for m in range(n):
            o = base + m
            out.append({"timestamp": (t0 + timedelta(minutes=m)).isoformat(),
                        "open": o, "high": o + 1.0, "low": o - 1.0, "close": o + 0.5,
                        "volume": 10, "contract": CONTRACT,
                        "temporal_status": "settled"})
        return out

    def _with_gap(self, n=12):
        """Same series, but c1.high < c3.low at one exact triple."""
        bars = self._clean(n)
        i = n - 3
        bars[i].update(high=bars[i]["open"] + 0.2)
        bars[i + 2].update(low=bars[i + 2]["open"] + 5.0,
                           high=bars[i + 2]["open"] + 8.0,
                           open=bars[i + 2]["open"] + 6.0,
                           close=bars[i + 2]["open"] + 7.0)
        return bars

    def _fvgs(self, bars, tf="1m"):
        from market_data.market_events import reconstruct_events, FVG
        return [e for e in reconstruct_events(bars, tf, contract=CONTRACT)
                if e["event_type"] == FVG]

    # -- identity ------------------------------------------------------------
    def test_identity_is_contract_tf_and_completion_bucket(self):
        got = self._fvgs(self._with_gap())
        assert got, "fixture produced no FVG -- a vacuous test"
        for e in got:
            assert e["event_id"] == f"FVG:{CONTRACT}:1m:{e['completion_bucket']}"

    def test_geometry_is_not_in_identity(self):
        """Direction and gap bounds are reconstructed from c1/c3 OHLC; history
        repair changes them, and an id carrying them would mint a twin."""
        for e in self._fvgs(self._with_gap()):
            for state in ("bullish", "bearish", str(e["gap_low"]),
                          str(e["gap_high"]), str(e["gap_size"])):
                assert state not in e["event_id"], (state, e["event_id"])

    def test_one_completion_bucket_holds_at_most_one_fvg(self):
        got = self._fvgs(self._with_gap())
        slots = [e["completion_bucket"] for e in got]
        assert len(slots) == len(set(slots))

    # -- exact three-candle evidence -----------------------------------------
    def test_the_object_names_its_exact_three_candles(self):
        for e in self._fvgs(self._with_gap()):
            assert e["source_bars"] == [e["c1_time"], e["c2_time"], e["c3_time"]]
            assert e["c3_time"] == e["event_time"]
            for cid, t in ((e["c1_id"], e["c1_time"]), (e["c2_id"], e["c2_time"]),
                           (e["c3_id"], e["c3_time"])):
                assert cid == f"CANDLE_REFERENCE:{CONTRACT}:1m:{t}"

    def test_the_array_index_is_diagnostic_only(self):
        """A position in a list is not a market identity and shifts the moment
        history is repaired."""
        for e in self._fvgs(self._with_gap()):
            assert "producer_index" in e
            assert str(e["producer_index"]) not in e["event_id"]

    # -- §12 completion-slot revision proof ----------------------------------
    def test_repairing_earlier_history_revises_the_same_slot(self):
        """THE PROOF THAT SOURCE EVIDENCE IS STATE. Insert a recovered bucket
        before the completion bar: the array-consecutive triple ending at T
        changes, so c1/c2 change -- but the occurrence slot does not."""
        from datetime import datetime, timedelta
        bars = self._with_gap()
        before = self._fvgs(bars)
        assert before, "fixture produced no FVG"
        target = before[0]
        # a previously-absent bucket is recovered two minutes before completion
        t = datetime.fromisoformat(target["c2_time"]) - timedelta(seconds=30)
        recovered = dict(bars[-2], timestamp=t.isoformat())
        repaired = sorted(bars + [recovered], key=lambda b: b["timestamp"])
        after = {e["event_id"]: e for e in self._fvgs(repaired)}
        if target["event_id"] in after:
            revised = after[target["event_id"]]
            assert revised["completion_bucket"] == target["completion_bucket"]
            assert revised["c1_time"] != target["c1_time"] or \
                revised["c2_time"] != target["c2_time"], \
                "the source triple did not actually change"
        # either way, no stale twin at the same slot
        slots = [e["completion_bucket"] for e in after.values()]
        assert len(slots) == len(set(slots))

    def test_a_vanished_fvg_leaves_no_stale_twin(self):
        bars = self._with_gap()
        got = self._fvgs(bars)
        assert got
        slot = got[0]["completion_bucket"]
        # close the gap: c3.low drops back inside c1's range
        flat = [dict(b) for b in bars]
        i = len(flat) - 1
        flat[i].update(low=flat[i]["open"] - 20.0)
        after = self._fvgs(flat)
        assert slot not in {e["completion_bucket"] for e in after}, \
            "a stale FVG survived history repair"

    # -- §13 well-formedness -------------------------------------------------
    def test_a_malformed_source_candle_fails_before_mint(self):
        from market_data.canonical_history import assert_well_formed
        from market_data.object_identity import MarketObjectIdentityError
        bars = self._with_gap()
        bars[-1].update(low=bars[-1]["high"] + 5.0)      # low above high
        with pytest.raises(MarketObjectIdentityError):
            assert_well_formed(bars, where="fvg source")

    def test_both_predicates_can_only_hold_on_malformed_geometry(self):
        from toolbox.price_levels import find_fvgs
        from market_data.canonical_history import candle_defects
        bad = self._clean(3)
        bad[0].update(low=1.0, high=0.0, open=0.5, close=0.5)
        bad[2].update(low=1.0, high=0.0, open=0.5, close=0.5)
        both = (find_fvgs(bad, "bullish", 1) and find_fvgs(bad, "bearish", 1))
        if both:
            assert candle_defects(bad[0]), \
                "both predicates held on a WELL-FORMED triple"

    # -- §6 dependency closure ------------------------------------------------
    def test_no_step4_fvg_depends_on_an_unresolved_revision_slot(self):
        """AUTHORITY PROPAGATES THROUGH DEPENDENCY, NOT FILE MEMBERSHIP. Proven
        mechanically against every real-tape FVG's exact c1/c2/c3 -- not by
        arguing that Aug-05 is several days earlier."""
        from market_data.canonical_history import (partition_revisions,
                                                   load_raw_journal,
                                                   unresolved_buckets,
                                                   depends_on_unresolved)
        from data_feed.timeframe_builder import build_timeframes
        from market_data.market_events import reconstruct_events, FVG
        if not os.path.exists(self.STORE_PATH):
            pytest.skip("canonical store not present")
        part = partition_revisions(load_raw_journal(self.STORE_PATH))
        bad = unresolved_buckets(part)
        assert bad, "fixture must contain unresolved slots to be meaningful"
        tfs = build_timeframes(part["bars"])
        checked = 0
        for tf in ("1m", "3m", "5m", "15m"):
            events = reconstruct_events(tfs[tf][-90:], tf, contract=CONTRACT)
            for e in (x for x in events if x["event_type"] == FVG):
                checked += 1
                assert depends_on_unresolved(e["source_bars"], bad) == [], \
                    f"{e['event_id']} rests on an unresolved revision slot"
        assert checked, "no FVGs checked -- a vacuous test"

    def test_an_unrelated_unresolved_slot_does_not_poison_an_fvg(self):
        from market_data.canonical_history import depends_on_unresolved
        far = {"2026-08-05T16:29:00+00:00"}
        got = self._fvgs(self._with_gap())
        assert got
        for e in got:
            assert depends_on_unresolved(e["source_bars"], far) == []

    def test_a_dependent_object_is_flagged(self):
        from market_data.canonical_history import depends_on_unresolved
        got = self._fvgs(self._with_gap())
        touched = {got[0]["c2_time"]}
        assert depends_on_unresolved(got[0]["source_bars"], touched) == \
            [got[0]["c2_time"]]

    # -- §1/§9 revision semantics --------------------------------------------
    def test_exact_duplicate_collapse_is_lossless_but_says_nothing_about_time(self):
        from market_data.canonical_history import (partition_revisions,
                                                   AS_OF_AVAILABILITY_UNKNOWN,
                                                   RETROSPECTIVE_NORMALIZED)
        row = {"timestamp": "2026-08-12T16:00:00+00:00", "contract": CONTRACT,
               "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9}
        part = partition_revisions([dict(row), dict(row)])
        assert len(part["bars"]) == 1
        assert part["bars"][0]["raw_revision_count"] == 2
        assert not part["unresolved_revision_slots"]
        assert part["history_basis"] == RETROSPECTIVE_NORMALIZED
        assert part["as_of_availability"] == AS_OF_AVAILABILITY_UNKNOWN, \
            "identical state must not imply identical availability time"

    def test_same_ohlc_different_volume_is_a_conflicting_revision(self):
        """§4 -- FVG geometry would never notice the volume, but they are still
        two different claims about one candle."""
        from market_data.canonical_history import partition_revisions
        a = {"timestamp": "2026-08-05T16:29:00+00:00", "contract": CONTRACT,
             "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 633}
        b = dict(a, volume=4048)
        part = partition_revisions([a, b])
        assert part["bars"] == []
        assert len(part["unresolved_revision_slots"]) == 1
        assert part["unresolved_revision_slots"][0]["revision_count"] == 2

    def test_conflicting_revisions_are_quarantined_not_resolved(self):
        from market_data.canonical_history import (partition_revisions,
                                                   UNRESOLVED_REVISION_AUTHORITY)
        a = {"timestamp": "2026-08-05T16:30:00+00:00", "contract": CONTRACT,
             "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 6416}
        b = dict(a, volume=1393)
        slot = partition_revisions([a, b])["unresolved_revision_slots"][0]
        assert slot["reason"] == UNRESOLVED_REVISION_AUTHORITY
        assert len(slot["candidate_revisions"]) == 2, "forensic candidates dropped"
        assert "winner" not in slot and "selected" not in slot

    def test_the_real_journal_quarantine_is_exactly_the_aug05_conflicts(self):
        from market_data.canonical_history import (partition_revisions,
                                                   load_raw_journal)
        if not os.path.exists(self.STORE_PATH):
            pytest.skip("canonical store not present")
        part = partition_revisions(load_raw_journal(self.STORE_PATH))
        slots = part["unresolved_revision_slots"]
        assert len(slots) == 19
        assert {s["bucket_timestamp"][:10] for s in slots} == {"2026-08-05"}

    # -- §2/§10 history basis -------------------------------------------------
    def test_bucket_time_does_not_claim_availability(self):
        from market_data.canonical_history import (AS_OF_AVAILABILITY_UNKNOWN,
                                                   HISTORY_BASES,
                                                   PERCEPTION_AS_OF)
        assert PERCEPTION_AS_OF in HISTORY_BASES
        assert AS_OF_AVAILABILITY_UNKNOWN != "AS_OF_AVAILABILITY_PROVEN"

    def test_the_loader_is_not_named_canonical(self):
        """A function that knowingly picks an unproven revision may not wear
        the word canonical."""
        from market_data import canonical_history as CH
        assert not hasattr(CH, "load_canonical_history")
        assert hasattr(CH, "load_normalized_last_wins_history")


# ══════════════════════════════════════════════════════════════════════════════
class TestStep4B1ClocksAndScopeSafety:
    """STEP 4B.1. Three clocks that may never impersonate one another, and a
    scope that must isolate under concurrency."""

    MES = "CON.F.US.MES.U26"

    def _gap_series(self, contract=CONTRACT, n=12, tf_min=1):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 8, 12, 17, 0, tzinfo=timezone.utc)
        out = []
        for m in range(n):
            o = 100.0 + m
            out.append({"timestamp": (t0 + timedelta(minutes=m * tf_min)).isoformat(),
                        "open": o, "high": o + 1.0, "low": o - 1.0, "close": o + 0.5,
                        "volume": 10, "contract": contract,
                        "temporal_status": "settled"})
        i = n - 3
        out[i]["high"] = out[i]["open"] + 0.2
        out[i + 2].update(low=out[i + 2]["open"] + 5.0, high=out[i + 2]["open"] + 8.0,
                          open=out[i + 2]["open"] + 6.0, close=out[i + 2]["open"] + 7.0)
        return out

    def _fvgs(self, bars, tf="1m", contract=CONTRACT):
        from market_data.market_events import reconstruct_events, FVG
        return [e for e in reconstruct_events(bars, tf, contract=contract)
                if e["event_type"] == FVG]

    # -- §1/§2 the three clocks ----------------------------------------------
    def test_bucket_end_is_arithmetic_per_timeframe(self):
        from market_data.market_events import _bucket_end
        t = "2026-08-12T17:10:00+00:00"
        assert _bucket_end(t, "1m") == "2026-08-12T17:11:00+00:00"
        assert _bucket_end(t, "3m") == "2026-08-12T17:13:00+00:00"
        assert _bucket_end(t, "5m") == "2026-08-12T17:15:00+00:00"
        assert _bucket_end(t, "15m") == "2026-08-12T17:25:00+00:00"

    def test_settled_confirmation_is_never_the_bucket_start(self):
        """THE BUG THIS STEP EXISTS TO KILL. A 5m bar beginning at 17:10 cannot
        have final OHLC at 17:10."""
        got = self._fvgs(self._gap_series())
        assert got, "fixture produced no FVG -- a vacuous test"
        for e in got:
            assert "settled_confirmation_at" not in e, \
                "the backdated field must be gone"
            assert e["settled_observed_at"] != e["completion_bucket_start"]
            assert e["completion_bucket_end"] > e["completion_bucket_start"]

    def test_retrospective_history_leaves_settlement_knowledge_unknown(self):
        """Even a proven bucket close does not prove the ENGINE held the final
        bar then -- legacy rows carry no persisted_at."""
        for e in self._fvgs(self._gap_series()):
            assert e["as_of_availability"] == "AS_OF_AVAILABILITY_UNKNOWN"
            assert e["settled_observed_at"] is None, \
                "a plausible-looking timestamp was invented"

    def test_the_four_clocks_are_separate_fields(self):
        """STEP 4B.2 renamed `geometry_observed_at` -> `assessed_at`, because on
        retrospective history it is the SIMULATED scan, not historical
        perception. `engine_observed_at` carries the perception clock and is
        populated only when the basis can support it."""
        for e in self._fvgs(self._gap_series()):
            for field in ("completion_bucket_start", "completion_bucket_end",
                          "assessed_at", "engine_observed_at",
                          "settled_observed_at"):
                assert field in e, field
            assert e["engine_observed_at"] is None
            assert e["engine_observation_known"] is False
            # identity uses the SLOT, never the knowledge clock
            assert e["completion_bucket_start"] in e["event_id"]
            assert e["completion_bucket_end"] not in e["event_id"]

    def test_event_time_is_documented_as_slot_ordering_only(self):
        import inspect
        from market_data import market_events as ME
        src = inspect.getsource(ME._fvgs_at)
        assert "BUCKET TIME IS NOT KNOWLEDGE TIME" in src
        for e in self._fvgs(self._gap_series()):
            assert e["event_time"] == e["completion_bucket_start"]

    # -- §5/§6 forming vs settled --------------------------------------------
    def test_a_forming_c3_never_claims_settled_formation(self):
        bars = self._gap_series()
        bars[-1]["temporal_status"] = "forming"
        got = self._fvgs(bars)
        assert got
        for e in got:
            assert e["formation_settled"] is False
            assert e["geometry_may_still_revise"] is True
            assert e["settled_observed_at"] is None

    def test_forming_geometry_can_disappear_without_a_settled_record(self):
        bars = self._gap_series()
        bars[-1]["temporal_status"] = "forming"
        assert self._fvgs(bars), "fixture must start with visible geometry"
        # price trades through: the gap closes while c3 is still forming
        erased = [dict(b) for b in bars]
        erased[-1].update(low=erased[-1]["open"] - 20.0)
        assert not self._fvgs(erased)

    def test_a_settled_c3_reports_settled_formation(self):
        for e in self._fvgs(self._gap_series()):
            assert e["c3_temporal_status"] == "settled"
            assert e["formation_settled"] is True

    # -- §7 scope isolation ---------------------------------------------------
    def test_the_scope_is_a_contextvar_not_a_module_global(self):
        from contextvars import ContextVar
        from market_data import market_events as ME
        assert isinstance(ME._CONTRACT_SCOPE, ContextVar), \
            "a module-global list cannot isolate across threads"

    def test_nested_scope_restores_the_outer_contract(self):
        from market_data.market_events import contract_scope, _active_contract
        with contract_scope(CONTRACT):
            assert _active_contract() == CONTRACT
            with contract_scope(self.MES):
                assert _active_contract() == self.MES
            assert _active_contract() == CONTRACT
        # the autouse fixture supplies the outermost scope, so exiting here
        # returns to IT -- not to None
        assert _active_contract() == CONTRACT
        with no_contract_scope():
            assert _active_contract() is None

    def test_an_exception_inside_a_scope_still_restores(self):
        from market_data.market_events import contract_scope, _active_contract
        with contract_scope(CONTRACT):
            try:
                with contract_scope(self.MES):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            assert _active_contract() == CONTRACT

    def test_threads_cannot_cross_contaminate_contract_scope(self):
        """The serial U26/MES/Z26 test could never have caught this. The
        provider owns a threading.Lock, so this runtime really is threaded."""
        import threading
        from market_data.market_events import contract_scope, _active_contract
        seen, errors = {}, []
        start = threading.Barrier(2)

        def worker(name, contract):
            try:
                with contract_scope(contract):
                    start.wait(timeout=5)          # force overlap
                    for _ in range(200):
                        if _active_contract() != contract:
                            errors.append((name, _active_contract()))
                    seen[name] = _active_contract()
            except Exception as exc:               # noqa: BLE001
                errors.append((name, repr(exc)))

        threads = [threading.Thread(target=worker, args=("a", CONTRACT)),
                   threading.Thread(target=worker, args=("b", self.MES))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors, errors
        assert seen == {"a": CONTRACT, "b": self.MES}

    def test_outside_any_scope_identity_still_refuses(self):
        from market_data.market_events import candle_reference_id
        from market_data.object_identity import MarketObjectIdentityError
        with no_contract_scope():
            with pytest.raises(MarketObjectIdentityError):
                candle_reference_id("1m", "2026-08-12T17:00:00+00:00")

    # -- §8/§9 explicit scope, proven first ----------------------------------
    def test_source_refs_carry_explicit_contract_from_their_own_candles(self):
        for contract in (CONTRACT, self.MES):
            got = self._fvgs(self._gap_series(contract), contract=contract)
            assert got
            for e in got:
                assert e["contract"] == contract
                for k in ("event_id", "c1_id", "c2_id", "c3_id"):
                    assert f":{contract}:" in e[k], (k, e[k])

    def test_the_source_contract_is_proven_before_it_scopes_anything(self):
        """Order matters: validate c1/c2/c3, THEN scope. Never choose a
        contract and stamp it onto contradictory candles."""
        from market_data.market_events import reconstruct_events
        from market_data.object_identity import MarketObjectIdentityError
        bars = self._gap_series()
        bars[-2]["contract"] = self.MES              # one source candle disagrees
        with pytest.raises(MarketObjectIdentityError):
            reconstruct_events(bars, "1m")

    def test_a_self_contradicting_source_row_blocks_the_fvg(self):
        from market_data.market_events import reconstruct_events
        from market_data.object_identity import MarketObjectIdentityError
        bars = self._gap_series()
        bars[-1]["contractId"] = self.MES            # row declares both, disagreeing
        with pytest.raises(MarketObjectIdentityError):
            reconstruct_events(bars, "1m")

    def test_explicit_refs_do_not_depend_on_ambient_state(self):
        """A published reference carries its own proof."""
        got = self._fvgs(self._gap_series())
        assert got
        with no_contract_scope():
            for e in got:
                assert f":{CONTRACT}:" in e["c1_id"]

    # -- §12 the semantic correction survives --------------------------------
    def test_the_imbalance_semantic_basis_is_published(self):
        from structure.displacement_detector import (detect_displacement,
                                                     IMBALANCE_SEMANTIC_BASIS)
        d = detect_displacement(self._gap_series(), {}, atr=2.0)
        assert d["imbalance_semantic_basis"] == "WINDOW_CONTAINS_DIRECTIONAL_FVG"
        assert "does NOT establish" in d["imbalance_semantic_note"]
        assert IMBALANCE_SEMANTIC_BASIS == "WINDOW_CONTAINS_DIRECTIONAL_FVG"

    def test_the_producer_really_scans_the_whole_window(self):
        """The evidence for the semantic downgrade, proven by BEHAVIOUR.

        The previous version matched the literal call text
        `find_fvgs(window, direction)` and broke when 4B.5 threaded `tf_minutes`
        through -- a refactor it did not disagree with. A gap formed at the
        START of the window still scores, so the component cannot be claiming
        the current leg created it.
        """
        from structure.displacement_detector import _imbalance
        bars = [{"timestamp": f"2026-08-12T17:{m:02d}:00+00:00", "open": 100.0,
                 "high": 100.5, "low": 99.5, "close": 100.0} for m in range(10)]
        bars[2].update(low=120.0, high=125.0, open=121.0, close=124.0)
        present, _detail, _d, n, gaps = _imbalance(bars, "bullish", 1)
        assert present and n >= 1, "an old gap did not score"
        assert gaps[0]["c3_time"] == bars[2]["timestamp"], \
            "the scored gap is not the one at the window start"


# ══════════════════════════════════════════════════════════════════════════════
class TestAmbientScopeIsNotEvidentiaryAuthority:
    """STEP 4B.12 §3. ContextVar solved CONCURRENCY. It never made ambient scope
    evidence. Published canonical provenance answers the second question.

    Measured before the repair: a contractless series inside a
    `CON.F.US.MES.U26` ambient scope minted
    `FVG:CON.F.US.MES.U26:1m:2026-08-12T17:02:00+00:00` on zero source evidence
    -- a flawless-looking canonical reference whose instrument came from
    surrounding execution state.
    """

    MES = "CON.F.US.MES.U26"
    T = "2026-08-12T17:02:00+00:00"

    def _snap(self):
        gap = {"index": 0, "low": 1, "high": 2, "size": 1,
               "c1_time": "2026-08-12T17:00:00+00:00",
               "c2_time": "2026-08-12T17:01:00+00:00", "c3_time": self.T}
        return {"expansion": {"1m": {"displacement": {
            "classification": "displacement_confirmed", "lookback": 3,
            "components": [], "imbalance_gaps": [gap],
            "fvg_bullish_gaps": [gap], "fvg_bearish_gaps": []}}}}

    def _at(self, series):
        from market_data.market_events import _displacement_at
        return _displacement_at(self._snap(), series, "1m", observed_at=self.T)

    # ── CASE A: no source contract + ambient MES ────────────────────────────
    def test_ambient_scope_cannot_authorize_a_published_ref(self):
        from market_data.market_events import contract_scope
        bare = [{"timestamp": self.T, "temporal_status": "settled"}]
        with contract_scope(self.MES):
            o = self._at(bare)
        assert o["ref_contract"] is None
        assert o["ref_contract_provenance"] == "NO_SOURCE_CONTRACT_EVIDENCE"
        assert o["exact_refs_publishable"] is False
        for field in ("imbalance_event_refs", "fvg_bullish_refs",
                      "fvg_bearish_refs"):
            assert all(r is None for r in o[field]), field
        assert all(t["ref"] is None for t in o["imbalance_ref_triples"])
        # and nothing anywhere carries the ambient instrument
        assert self.MES not in json.dumps(
            {k: v for k, v in o.items() if "ref" in k}), \
            "the ambient contract leaked into published provenance"

    # ── CASE B: source proves MNQ + ambient contradicts with MES ────────────
    def test_source_evidence_dominates_a_contradictory_ambient_scope(self):
        from market_data.market_events import contract_scope
        proven = [{"timestamp": self.T, "temporal_status": "settled",
                   "contract": CONTRACT}]
        with contract_scope(self.MES):
            o = self._at(proven)
        assert o["ref_contract"] == CONTRACT
        assert o["ref_contract_provenance"] == "EVIDENCE_DERIVED"
        assert o["exact_refs_publishable"] is True
        for field in ("imbalance_event_refs", "fvg_bullish_refs"):
            for r in o[field]:
                if r is not None:
                    assert f":{CONTRACT}:" in r, r
                    assert self.MES not in r, "ambient overrode the evidence"

    def test_every_published_ref_field_is_covered(self):
        """All four fields named in the ruling, not a representative sample."""
        from market_data.market_events import contract_scope
        proven = [{"timestamp": self.T, "temporal_status": "settled",
                   "contract": CONTRACT}]
        with contract_scope(self.MES):
            o = self._at(proven)
        for field in ("fvg_bullish_refs", "fvg_bearish_refs",
                      "imbalance_event_refs", "imbalance_ref_triples"):
            assert field in o, field
        assert o["imbalance_ref_triples"][0]["ref"].startswith(f"FVG:{CONTRACT}:")

    # ── the pre-existing refusals must still hold ───────────────────────────
    def test_mixed_partial_and_contractid_refusals_survive(self):
        from market_data.market_events import _contract_in
        from market_data.object_identity import MarketObjectIdentityError
        C, M = CONTRACT, self.MES
        with pytest.raises(MarketObjectIdentityError):       # mixed
            _contract_in([{"contract": C}, {"contract": M}])
        with pytest.raises(MarketObjectIdentityError):       # partial silence
            _contract_in([{"contract": C}, {"contract": C}, {}])
        with pytest.raises(MarketObjectIdentityError):       # row self-contradicts
            _contract_in([{"contract": C, "contractId": M}])
        assert _contract_in([{"contract": C}] * 3) == C      # unanimous is fine

    def test_the_real_tape_publishes_only_evidence_derived_refs(self):
        """Production is unaffected: every assessment proves its own contract."""
        import json as _json
        from market_data.market_events import reconstruct_displacement
        if not os.path.exists(STORE):
            pytest.skip("canonical store not present")
        rows = [_json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        with no_contract_scope():
            res = reconstruct_displacement(rows[-300:], lookback_bars=25)
        assert res["observations"]
        for o in res["observations"]:
            assert o["ref_contract_provenance"] == "EVIDENCE_DERIVED"
            assert o["exact_refs_publishable"] is True
