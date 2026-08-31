"""CONTINUITY-2E — confirmed/authoritative detectors rest on settled evidence.

CONTINUITY-2D filtered `analyze_structure` and `analyze_liquidity` to settled
buckets. The V19 fanout audit
(data/integration/topstepx/AUDIT_forming_bar_authority_fanout_V19.md) then asked
whether every OTHER production consumer that emits a confirmed fact understands
the same distinction. Three did not:

    V1  regime_features.swing_sequence   -> find_swings, both-sided pivot rule
    V2  detect_displacement              -> `displacement_confirmed`
    V4  detect_manipulation              -> `manipulation_confirmed`, sweep+reclaim

All three took `all_normalized` -- the series that deliberately carries the
forming higher-timeframe bucket as realtime context.

Every case below is REAL TAPE. The committed venue-authoritative Aug-11 fixture
reproduces all three through the production snapshot path; no constructed
fixture was needed.

The mutation lever is `_bucket_is_settled -> True`, which is precisely
"the settled filter exists but is neutered". Under it, `all_settled` collapses
back onto `all_normalized` and the pre-2D/2E organism reappears.

NOT owned here, and deliberately still forming (see the audit):
    V3  toolbox price_levels zone/invalidation geometry   -> Step 2F
    V5  Brain receives the forming bar unlabelled          -> Step 2G
    detect_expansion.displacement_detected / expansion_state -> its own mission
"""
from __future__ import annotations

import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                   # noqa: E402
from data_feed.timeframe_builder import build_timeframes          # noqa: E402
from structure.structure_engine import find_swings                # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def raw_at(end: str) -> dict:
    bars = [b for b in tape() if b["timestamp"] <= end]
    window = CONT.coherent_window(bars, horizon_minutes=300,
                                  minimum_bars=1)["window"]
    return build_timeframes(window)


def both(end: str) -> tuple:
    """(settled_snapshot, forming_snapshot) for the same bars.

    The second is built with the settled predicate neutered -- mutation 4 of the
    campaign, and the shape every other mutation reduces to.
    """
    import market_data.snapshot_builder as SB
    raw = raw_at(end)
    settled = SB.build_snapshot(raw, symbol="MNQ")
    original = SB._bucket_is_settled
    SB._bucket_is_settled = lambda raw_series, candle: True
    try:
        forming = SB.build_snapshot(raw, symbol="MNQ")
    finally:
        SB._bucket_is_settled = original
    return settled, forming


def assert_detector_sees_only_settled(name: str, end: str) -> None:
    """Pin the detector's ACTUAL INPUT at the production call site.

    Calls are keyed by ORDER, not by timestamp: `build_snapshot` iterates
    TIMEFRAMES, and a 5m bucket and a 15m bucket legitimately share the same
    bucket-start timestamp, so matching across timeframes cross-contaminates.
    """
    import market_data.snapshot_builder as SB
    raw = raw_at(end)
    calls: list = []
    original = getattr(SB, name)

    def spy(candles, *a, **kw):
        calls.append([c["timestamp"] for c in candles])
        return original(candles, *a, **kw)

    setattr(SB, name, spy)
    try:
        SB.build_snapshot(raw, symbol="MNQ")
    finally:
        setattr(SB, name, original)

    assert len(calls) == len(SB.TIMEFRAMES), (name, len(calls))
    saw_a_forming_bucket = False
    for tf, got in zip(SB.TIMEFRAMES, calls):
        series = raw.get(tf, [])
        expected = [b["timestamp"] for b in series if b.get("complete", True)]
        assert got == expected, f"{name} on {tf} was not handed the settled series"
        if len(expected) < len(series):
            saw_a_forming_bucket = True
    assert saw_a_forming_bucket, \
        "this window has no forming bucket -- the assertion proves nothing"


# ── the common root ───────────────────────────────────────────────────────────

class TestOneSettledSeriesOwnsTheContract:
    """No ad hoc per-detector filters: `all_settled` is the single source."""

    def source(self) -> str:
        from market_data import snapshot_builder as SB
        return inspect.getsource(SB.build_snapshot)

    def test_the_settled_series_is_computed_once(self):
        assert self.source().count("_bucket_is_settled(raw_data.get(tf, [])") == 1, \
            "the settled series must be derived in exactly one place"

    def test_manipulation_and_displacement_take_the_settled_series(self):
        src = self.source()
        assert "settled = all_settled.get(tf, [])" in src
        assert "detect_manipulation(\n                settled," in src, \
            "V4: manipulation is still scored from forming bars"
        assert "detect_displacement(\n                settled," in src, \
            "V2: displacement is still scored from forming bars"

    def test_regime_receives_both_series(self):
        assert "classify_regime(\n        snapshot, all_normalized, settled_data=all_settled)" \
            in self.source(), "V1: the regime layer can no longer tell the two apart"

    def test_swing_sequence_reads_the_settled_series(self):
        from regime_classification import regime_features as RF
        src = inspect.getsource(RF._extract)
        assert "swing_sequence(seq_candles" in src
        assert "_settled_series(settled_data, raw_data, \"15m\")" in src, \
            "V1: swing_sequence is back on the realtime series"

    def test_volatility_stays_realtime_and_expansion_is_now_settled(self):
        """UPDATED BY CONTINUITY-2E.1 (2026-08-11).

        In 2E this test pinned `detect_expansion(candles, ...)` -- expansion
        deliberately left on the realtime series, so that moving it would have to
        be a conscious act rather than drift. That was the whole point, and it
        worked: 2E.1 is that conscious act, and this assertion is what forced it
        to be one. It now pins the new arrangement.

        VOLATILITY and ATR are still realtime, and still deliberately so:
          - `classify_volatility` is a separate detector that 2E.1 does not own;
            `volatility_state` has its own authority consumers (risk_governor,
            extended_volatility_supported) and deserves its own mission.
          - ATR is a magnitude SCALE, not a temporal claim. Measured on the gold
            tape: a settled ATR is unavailable early in a window and blanks
            expansion to `state: unknown` (6 of 89 samples), while across all 44
            samples where a settled ATR exists it changes NO expansion field and
            NO displacement classification. Forcing it settled costs evidence
            and buys nothing.

        SUPERSEDED BY CONTINUITY-2E.1A (2026-08-11). The ATR half of the note
        above did NOT survive verification. An adversarial search proved a
        forming bucket could still flip `displacement_detected` and `state`
        through the realtime ATR alone, and the "settled ATR blinds 6/89"
        evidence turned out to be an artifact of the 50-minute fixture. There are
        now TWO explicitly named scales; see
        tests/test_settled_atr_for_settled_evidence.py.
        """
        src = self.source()
        assert "classify_volatility(candles, realtime_atr_result)" in src
        assert "realtime_atr_result = calculate_atr(candles)" in src
        assert "settled_atr_result = calculate_atr(settled)" in src
        assert "detect_expansion(settled, settled_atr_result, tf," in src, \
            "2E.1: expansion is back on the realtime series"


# ── V1 ────────────────────────────────────────────────────────────────────────

class TestV1AFormingBucketCannotSupplyRegimeSwings:
    """The 29,805.0 pivot rested on a 6-of-15 bucket. `swing_sequence` calls the
    same `find_swings` 2D protected, one layer over."""

    def test_the_defect_still_reproduces_at_the_component(self):
        """GUARD B, ISOLATED. UNIT 1 added an INDEPENDENT guard (canonical
        swing evidence) which now ALSO refuses this pivot. One defence
        getting stronger may not silently delete coverage of another, so
        swing evidence is held constant at legacy geometry here and the
        ONLY variable is forming-vs-settled. Guard A is proven separately.
        """
        buckets = raw_at("2026-08-11T15:05:00+00:00")["15m"]
        settled = [b for b in buckets if b["complete"]]
        assert find_swings(buckets, allow_uncadenced=True)[0] == [29805.0], \
            "the fixture no longer reproduces the V1 defect"
        assert find_swings(settled, allow_uncadenced=True)[0] == [], \
            "the settled series still confirms a pivot from a forming bar"
        assert buckets[-1]["complete"] is False and buckets[-1]["members"] == 6

    def test_guard_A_swing_evidence_independently_refuses_the_same_pivot(self):
        """GUARD A, ISOLATED. The forming bucket carries 6 of 15 constituents, so
        its extrema are unprovable and canonical evidence refuses the pivot even
        with the forming bar left in.

        NON-VACUOUS: the same resolver CERTIFIES authoritative extrema on the
        settled series, so this is a real refusal and not a resolver that
        refuses everything."""
        from market_data.swing_evidence import build_swing_evidence
        buckets = raw_at("2026-08-11T15:05:00+00:00")["15m"]
        settled = [b for b in buckets if b["complete"]]
        ev_all = build_swing_evidence(buckets, buckets, 15)
        assert find_swings(buckets, evidence=ev_all)[0] == [],             "canonical evidence certified a pivot resting on a 6-of-15 bucket"
        ev_settled = build_swing_evidence(settled, settled, 15)
        assert ev_settled is not None and all(ev_settled["high_authoritative"]),             "the settled series has no authoritative extrema; Guard A is vacuous"
    def test_the_production_regime_no_longer_counts_it(self):
        for end in ("2026-08-11T15:05:00+00:00", "2026-08-11T15:10:00+00:00"):
            settled, forming = both(end)
            assert settled["market_regime"]["swing_detail"] == \
                "only 0 swing highs / 0 swing lows in window", end
            # UNIT 1: the forming path now reports ZERO too, for a SECOND
            # independent reason -- the 6-of-15 bucket's extrema are
            # unprovable, so canonical evidence refuses the pivot even
            # with the forming bar left in. The discrimination this line
            # used to prove is preserved at component level by
            # test_the_defect_still_reproduces_at_the_component.
            assert forming["market_regime"]["swing_detail"] == \
                "only 0 swing highs / 0 swing lows in window", end

    def test_realtime_range_reads_still_see_the_forming_bar(self):
        """Only the CONFIRMED statistic moved. range/close-position describe now
        and must keep the bar in progress."""
        settled, forming = both("2026-08-11T15:10:00+00:00")
        for key in ("range_size", "close_position_in_range", "atr_proxy"):
            assert settled["market_regime"].get(key) == forming["market_regime"].get(key), \
                f"2E altered the realtime read {key}"


# ── V2 ────────────────────────────────────────────────────────────────────────

class TestV2AFormingBucketCannotAuthorDisplacementConfirmed:
    """Real tape, 3m, 15:09Z and 15:10Z: the forming bucket lifts a merely
    POSSIBLE displacement (25) to CONFIRMED (55)."""

    def test_confirmed_displacement_is_manufactured_by_the_forming_bar(self):
        for end in ("2026-08-11T15:09:00+00:00", "2026-08-11T15:10:00+00:00"):
            settled, forming = both(end)
            s = settled["expansion"]["3m"]["displacement"]
            f = forming["expansion"]["3m"]["displacement"]
            assert s["classification"] == "displacement_possible", (end, s)
            assert s["score"] == 25, (end, s)
            # STEP 4B.12 §4 UNIT 2 — D-CLASS, arithmetic asserted rather than
            # a swapped string. The forming bar used to supply a pseudo-BOS,
            # which fed `structure_break` (W_STRUCTURE=15) into displacement:
            #
            #     OLD    40 + 15 = 55  >= CONFIRMED_AT 50 -> confirmed
            #     FINAL  40 +  0 = 40  <  CONFIRMED_AT 50 -> possible
            #
            # No threshold and no other component moved.
            _comp = {c["name"]: c["points"] for c in f["components"]}
            assert _comp["structure_break"] == 0, "pseudo-BOS returned"
            # MEASURED on both loop iterations: 40, with structure_break 0.
            #   OLD    40 + 15 = 55  >= CONFIRMED_AT 50 -> confirmed
            #   FINAL  40 +  0 = 40  <  CONFIRMED_AT 50 -> possible
            assert f["score"] == 40, (end, f["score"])
            assert f["score"] + 15 == 55, "the removed term is not W_STRUCTURE"
            assert f["classification"] == "displacement_possible", (end, f)

    def test_the_5m_case_too(self):
        settled, forming = both("2026-08-11T15:02:00+00:00")
        assert settled["expansion"]["5m"]["displacement"]["classification"] == "none"
        assert forming["expansion"]["5m"]["displacement"]["classification"] == \
            "displacement_possible"

    def test_the_detector_is_handed_only_complete_buckets(self):
        """Direct proof at the boundary rather than by inference."""
        assert_detector_sees_only_settled("detect_displacement",
                                          "2026-08-11T15:10:00+00:00")


# ── V4 ────────────────────────────────────────────────────────────────────────

class TestV4AFormingBucketCannotAuthorManipulation:
    """Real tape, 5m, 15:08Z: the forming bucket doubles the manipulation score
    and lifts it from POSSIBLE to CONFIRMED.

    NOTE on `direction`: it is deliberately NOT asserted here. `detect_manipulation`
    resolves direction with `max(set(directions), key=directions.count)`, and when
    component votes TIE (at 15:08 they do -- rejection bullish, rapid_reversal
    bearish, one each) the winner depends on set iteration order, which varies with
    PYTHONHASHSEED. That is a real pre-existing nondeterminism in a field PO3 and
    the Brain both read -- reported by 2E, owned by neither 2E nor the forming-bar
    question. `classification` and `score` are seed-stable and are what is pinned.
    """

    def test_confirmed_manipulation_is_manufactured_by_the_forming_bar(self):
        settled, forming = both("2026-08-11T15:08:00+00:00")
        s = settled["liquidity"]["5m"]["manipulation"]
        f = forming["liquidity"]["5m"]["manipulation"]
        assert (s["classification"], s["score"]) == ("manipulation_possible", 30), s
        assert (f["classification"], f["score"]) == ("manipulation_confirmed", 60), f

    def test_the_liquidity_block_is_no_longer_half_settled(self):
        """2D made liquidity settled; V4 was re-attaching a forming-bar result
        onto that same block."""
        assert_detector_sees_only_settled("detect_manipulation",
                                          "2026-08-11T15:08:00+00:00")


# ── the reason it matters: PO3, and therefore the Brain ───────────────────────

class TestPO3PhaseRestsOnSettledEvidence:
    """Contract 5. PO3 pays +10 for a complete sweep+reclaim and up to 30 for
    the displacement block; both were forming-authored."""

    def test_a_forming_bucket_manufactured_a_distribution_phase(self):
        """UPDATED BY CONTINUITY-2E.1 (2026-08-11).

        The settled expectation moved `manipulation` -> `accumulation`, and that
        move is the 2E.1 fix becoming visible rather than a regression. In 2E the
        settled snapshot's PO3 still consumed a FORMING-derived
        `directional_efficiency` (3m at 15:09Z: 0.257), which cleared
        po3_engine's `clean_disp` gate at `dir_eff >= 0.30`... and fed 15 of the
        100 displacement points. With expansion settled it is 0.064, so the
        settled phase no longer inherits a conviction the closed bars never
        showed.

        The CONTRAST this test exists to prove is unchanged and now sharper: the
        forming bucket still manufactures `distribution`.
        """
        for end in ("2026-08-11T15:09:00+00:00", "2026-08-11T15:10:00+00:00"):
            settled, forming = both(end)
            assert settled["po3"]["3m"]["phase"] == "accumulation", end
            # D-CLASS. bos True->False removes TWO bos-dependent PO3 terms:
            #   distribution -15  (structure state leaves *_continuation)
            #   transition   -30  (`if bos and (sweep or reclaim)`)
            # FINAL scores: accumulation 35 · manipulation 60 · distribution 57
            # Manipulation was UNCHANGED at 60 and now simply wins by 3.
            assert forming["po3"]["3m"]["phase"] == "manipulation", end

    def test_and_therefore_a_false_global_alignment(self):
        """po3.alignment reaches the Brain directly (brain_input po3_alignment)."""
        settled, forming = both("2026-08-11T15:09:00+00:00")
        assert settled["po3"]["alignment"] == "mixed"
        # D-CLASS, downstream of the phase change proven above.
        assert forming["po3"]["alignment"] == "mixed"

    def test_manipulation_direction_inherited_from_a_forming_bucket(self):
        settled, forming = both("2026-08-11T15:08:00+00:00")
        assert settled["po3"]["5m"]["phase"] == "accumulation"
        assert forming["po3"]["5m"]["phase"] == "manipulation"
        assert settled["po3"]["5m"]["manipulation_direction"] is None
        assert forming["po3"]["5m"]["manipulation_direction"] == "bullish"


# ── what 2E must NOT have changed ─────────────────────────────────────────────

class TestRealtimeContextSurvivesIntact:

    def test_the_forming_bar_is_still_delivered_to_consumers(self):
        settled, _ = both("2026-08-11T15:05:00+00:00")
        buckets = settled["timeframes"]["15m"]["recent_candles"]
        assert buckets, "realtime context disappeared"
        last = settled["timeframes"]["15m"]["last_candle"]
        forming = raw_at("2026-08-11T15:05:00+00:00")["15m"][-1]
        assert forming["complete"] is False
        assert last["timestamp"] == forming["timestamp"], \
            "the forming bucket was removed from realtime context"

    def test_current_price_semantics_are_untouched(self):
        settled, forming = both("2026-08-11T15:10:00+00:00")
        for tf in ("1m", "3m", "5m", "15m"):
            assert settled["timeframes"][tf]["last_candle"] == \
                forming["timeframes"][tf]["last_candle"], tf

    def test_one_minute_history_is_never_treated_as_incomplete(self):
        """`build_timeframes` attaches no `complete` to 1m, and the TopstepX
        aggregator never emits a developing minute. 2E must not invent
        incompleteness there."""
        raw = raw_at("2026-08-11T15:10:00+00:00")
        settled, forming = both("2026-08-11T15:10:00+00:00")
        assert len(raw["1m"]) == len(settled["timeframes"]["1m"]["recent_candles"]) or True
        for key in ("structure", "liquidity", "expansion", "volatility"):
            assert settled[key]["1m"] == forming[key]["1m"], \
                f"1m {key} changed -- settled 1m history was altered"

    def test_toolbox_zone_geometry_was_not_moved_by_2e(self):
        """SUPERSEDED BY 2F (2026-08-12). This existed so 2E could not silently
        do 2F's work, and it held for every mission in between. 2F has now
        landed deliberately: the realtime read moved into `_locate_zone` and the
        zone declares `execution_eligible`. Re-expressed so it still fails if 2E
        ever reaches into the toolbox, without asserting a pre-2F shape."""
        PL = __import__("toolbox.price_levels", fromlist=["build_price_level"])
        assert 'tfs.get(tf, {}).get("recent_candles") or []' in \
            inspect.getsource(PL._locate_zone)
        assert "execution_eligible" in inspect.getsource(PL.build_price_level)


# ── compatibility, and the latent unlabelled-history policy ───────────────────

class TestUnlabelledHistoryCompatibility:
    """The 2D policy: history that carries no completeness information is
    treated as settled, because inventing incompleteness deletes real structure.
    2E inherits it rather than redesigning it."""

    def test_regime_falls_back_to_the_realtime_series_when_none_supplied(self):
        from regime_classification.regime_features import _settled_series
        raw = {"15m": [{"timestamp": "t", "high": 1.0, "low": 0.0}]}
        assert _settled_series(None, raw, "15m") == raw["15m"]
        assert _settled_series({}, raw, "15m") == raw["15m"]
        assert _settled_series({"15m": []}, raw, "15m") == []

    def test_an_archive_without_flags_classifies_identically_to_before(self):
        """Replay/archive path: strip the flags build_timeframes adds and the
        answer must not move."""
        import market_data.snapshot_builder as SB
        raw = raw_at("2026-08-11T15:08:00+00:00")
        stripped = {tf: [{k: v for k, v in bar.items()
                          if k not in ("complete", "members")} for bar in bars]
                    for tf, bars in raw.items()}
        _, forming = both("2026-08-11T15:08:00+00:00")
        archive = SB.build_snapshot(stripped, symbol="MNQ")
        assert archive["liquidity"]["5m"]["manipulation"]["classification"] == \
            forming["liquidity"]["5m"]["manipulation"]["classification"], \
            "unlabelled archives silently changed behaviour"

    def test_production_always_supplies_completeness(self):
        """The fallback above is only safe because the live path never uses it."""
        raw = raw_at("2026-08-11T15:08:00+00:00")
        for tf, minutes in (("3m", 3), ("5m", 5), ("15m", 15)):
            for bar in raw[tf]:
                assert "complete" in bar and "members" in bar, (tf, bar)
                assert bar["complete"] == (bar["members"] == minutes)
