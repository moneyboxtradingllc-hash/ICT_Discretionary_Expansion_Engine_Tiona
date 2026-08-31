"""CONTINUITY-2E.1A — the SCALE must match the temporal class of the EVIDENCE.

v22 moved the candle inputs of detect_expansion / detect_displacement /
detect_manipulation to settled evidence, but kept handing them an ATR computed
from the REALTIME series. Settled bodies were therefore judged against a
forming-derived threshold -- a category mismatch, not a rounding detail.

AUDIT_2E1A_verification_verdict.md proved it is reachable, not theoretical:

    atr       -> disp_threshold = max(atr * K_ATR, f_disp(tf))
                 -> _displacement_detected(SETTLED bodies, disp_threshold)
    atr_trend -> _score(...) {rising +5, stable 0, falling -8} -> expansion_score
                 -> state

Holding the settled history FIXED and varying only the forming bucket flipped
`displacement_detected` on 3m/5m/15m and `state` early<->mature -- in some cases
with the SAME number of forming minutes, so the forming bucket's price action
alone authored the field.

THE PROPERTY THIS FILE OWNS:

    identical settled history + ANY forming bucket
      => byte-identical settled expansion / displacement / manipulation evidence

The realtime lane is deliberately UNCHANGED and is asserted to still move, so a
future patch cannot quietly settle `classify_volatility` (its own open mission).
"""
from __future__ import annotations

import inspect
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                   # noqa: E402
from data_feed.timeframe_builder import build_timeframes          # noqa: E402
from market_data.candle_normalizer import normalize_candles       # noqa: E402
from market_data.session_engine import get_session_label          # noqa: E402
from volatility.atr_engine import MIN_CANDLES, calculate_atr      # noqa: E402
import market_data.snapshot_builder as SB                         # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")

#: Fields whose value can depend on ATR, directly or through `_state`.
ATR_DEPENDENT = ("state", "expansion_score", "displacement_detected")
#: The full published block -- asserted whole, so a future ATR-dependent field
#: cannot be added without this noticing.
EXPANSION_FIELDS = ATR_DEPENDENT + (
    "directional_efficiency", "body_dominance", "exhaustion_risk",
    "kappa", "magnitude_gated")


def bar(minute, o, h, l, c, v=1000):
    return {"timestamp": f"2026-08-11T{14 + minute // 60:02d}:{minute % 60:02d}:00+00:00",
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
            "close": round(c, 2), "volume": v}


def synthetic(rng, n_minutes, scale, start=0, px=29700.0):
    out = []
    for i in range(n_minutes):
        o = px
        c = px + rng.gauss(0, scale)
        h = max(o, c) + abs(rng.gauss(0, scale * 0.4))
        l = min(o, c) - abs(rng.gauss(0, scale * 0.4))
        out.append(bar(start + i, o, h, l, c))
        px = c
    return out, px


def snapshot(bars):
    return SB.build_snapshot(build_timeframes(bars), symbol="MNQ")


# ── the invariant, hunted adversarially ───────────────────────────────────────

class TestAFormingBucketCannotAuthorSettledEvidence:
    """The 2E.1A counterexamples, promoted to a durable property test.

    Settled 1m history is held byte-identical; only the minutes belonging to the
    still-forming higher-timeframe bucket vary -- in COUNT and in CONTENT, at
    volatilities spanning far above and below the settled history's own, which is
    what moves ATR enough to cross `disp_threshold`.
    """

    def variants(self, seed, tf, bucket, trials):
        rng = random.Random(seed)
        n_settled = 120
        for _ in range(trials):
            settled_bars, px = synthetic(rng, n_settled, rng.uniform(1.0, 6.0))
            built = []
            for _ in range(2):
                forming, _ = synthetic(rng, rng.randint(1, bucket - 1),
                                       rng.uniform(0.5, 25.0), start=n_settled, px=px)
                built.append(settled_bars + forming)
            yield built[0], built[1]

    def test_expansion_block_is_invariant_to_the_forming_bucket(self):
        for tf, bucket in (("3m", 3), ("5m", 5), ("15m", 15)):
            checked = 0
            for a_bars, b_bars in self.variants(7, tf, bucket, 120):
                a = snapshot(a_bars)["expansion"][tf]
                b = snapshot(b_bars)["expansion"][tf]
                for key in EXPANSION_FIELDS:
                    assert a.get(key) == b.get(key), \
                        f"{tf}.{key}: forming bucket authored {a.get(key)!r} vs {b.get(key)!r}"
                checked += 1
            assert checked >= 100, (tf, checked)

    def test_displacement_and_manipulation_are_invariant_too(self):
        """Both take the settled ATR: `_magnitude` divides body by ATR,
        `_rapid_reversal` measures the reversal against it."""
        for tf, bucket in (("3m", 3), ("5m", 5), ("15m", 15)):
            checked = 0
            for a_bars, b_bars in self.variants(11, tf, bucket, 80):
                sa, sb = snapshot(a_bars), snapshot(b_bars)
                da = sa["expansion"][tf].get("displacement") or {}
                db = sb["expansion"][tf].get("displacement") or {}
                for key in ("classification", "score", "magnitude_atr",
                            "imbalance_count"):
                    assert da.get(key) == db.get(key), (tf, "displacement", key)
                ma = sa["liquidity"][tf].get("manipulation") or {}
                mb = sb["liquidity"][tf].get("manipulation") or {}
                for key in ("classification", "score"):
                    assert ma.get(key) == mb.get(key), (tf, "manipulation", key)
                rapid_a = [c for c in ma.get("components", [])
                           if c["name"] == "rapid_reversal"]
                rapid_b = [c for c in mb.get("components", [])
                           if c["name"] == "rapid_reversal"]
                assert [c["present"] for c in rapid_a] == \
                    [c["present"] for c in rapid_b], (tf, "rapid_reversal")
                checked += 1
            assert checked >= 60, (tf, checked)

    def test_the_realtime_lane_still_moves(self):
        """Not a nicety -- this is what stops a future patch from quietly
        settling `classify_volatility`, which is its own open mission and
        legitimately owns realtime semantics."""
        moved = 0
        for a_bars, b_bars in self.variants(3, "5m", 5, 60):
            a = snapshot(a_bars)["volatility"]["5m"]
            b = snapshot(b_bars)["volatility"]["5m"]
            if a != b:
                moved += 1
        assert moved > 0, \
            "realtime volatility no longer responds to the forming bar -- the " \
            "realtime lane was settled by accident"


# ── the wiring, at the production call site ──────────────────────────────────

class TestTheTwoScalesAreWiredToTheRightLanes:

    def source(self) -> str:
        return inspect.getsource(SB.build_snapshot)

    def test_both_scales_exist_and_are_named_for_their_class(self):
        src = self.source()
        assert "realtime_atr_result = calculate_atr(candles)" in src
        assert "settled_atr_result = calculate_atr(settled)" in src

    def test_realtime_atr_goes_only_to_volatility(self):
        src = self.source()
        assert "classify_volatility(candles, realtime_atr_result)" in src
        assert src.count("realtime_atr_result") == 2, \
            "realtime ATR reaches something other than the realtime lane"

    def test_settled_atr_reaches_all_three_settled_detectors(self):
        """CALL CONTRACT, not source text.

        This asserted literal source including newlines and indentation, so
        STEP 4B.12 §4 UNIT 1 broke it merely by threading `swing_evidence=` into
        `detect_manipulation` -- a change the test does not disagree with. A
        formatting-coupled assertion catches a reformat and misses a defeat.

        The INVARIANT is unchanged and still the subject: all three settled
        detectors are fed the SETTLED series and the SETTLED ATR scale, never
        the realtime ones. It is proven structurally instead of textually.
        """
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(self.source()))
        calls = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.setdefault(node.func.id, []).append(node)

        def names(node):
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

        for detector in ("detect_expansion", "detect_manipulation",
                         "detect_displacement"):
            found = calls.get(detector) or []
            assert found, f"{detector} is no longer called by build_snapshot"
            seen = names(found[0])
            assert "settled" in seen, f"{detector} is not fed the settled series"
            assert "settled_atr_result" in seen,                 f"{detector} is not fed the settled ATR scale"
            assert "realtime_atr_result" not in seen,                 f"{detector} reaches the realtime ATR scale"

        # UNIT 1, ADDITIVE -- this does not replace the settled-evidence
        # invariant above; manipulation must also receive canonical swing
        # evidence now that its pivots need proven market neighbourhoods.
        manip = calls["detect_manipulation"][0]
        assert any(kw.arg == "swing_evidence" for kw in manip.keywords),             "detect_manipulation no longer receives canonical swing evidence"

    def test_the_detectors_actually_receive_the_settled_scale(self):
        """Behavioural, keyed by call order -- a source string catches deletion,
        not defeat."""
        with open(FIXTURE, encoding="utf-8") as fh:
            tape = json.load(fh)["bars"]
        window = CONT.coherent_window(tape, horizon_minutes=300,
                                      minimum_bars=1)["window"]
        raw = build_timeframes(window)
        expected = {}
        for tf in SB.TIMEFRAMES:
            settled = normalize_candles([b for b in raw[tf] if b.get("complete", True)],
                                        get_session_label)
            expected[tf] = calculate_atr(settled).get("atr")

        seen, original = [], SB.detect_displacement

        def spy(candles, struct, atr, expansion, **kw):
            seen.append(atr)
            return original(candles, struct, atr, expansion, **kw)

        SB.detect_displacement = spy
        try:
            SB.build_snapshot(raw, symbol="MNQ")
        finally:
            SB.detect_displacement = original

        assert seen == [expected[tf] for tf in SB.TIMEFRAMES], \
            f"displacement was handed {seen}, settled ATRs are " \
            f"{[expected[tf] for tf in SB.TIMEFRAMES]}"


# ── fail-closed, never borrowed ──────────────────────────────────────────────

class TestAnUnavailableSettledScaleFailsClosed:
    """MEASURED against the real production range, and NARROWER than first
    stated. `topstepx_production_loop` accepts HISTORY_MINIMUM_BARS=60 up to
    HISTORY_HORIZON_MINUTES=300. The 15m availability, realtime vs settled:

        window   15m realtime      15m settled     2E.1A changes it?
         60min    4 / None          4 / None       no -- both blind already
         61min    5 / 11.12         4 / None       YES
         74min    5 / 18.60         4 / None       YES
         75min    5 / 18.60         5 / 18.60      no -- identical
        300min   20 / ok           20 / ok         no

    So the behaviour change is confined to a 61-74 minute coherent window, on the
    15m alone. And that band is precisely where the forming bucket is the FIFTH
    data point that makes a 14-period ATR computable at all -- the scale would be
    a fifth authored by an unfinished bar. Refusing it is the point.

    3m and 5m never enter this band at any production window length.
    """

    def window_of(self, minutes: int) -> dict:
        rng = random.Random(5)
        bars, _ = synthetic(rng, minutes, 3.0)
        return build_timeframes(CONT.coherent_window(
            bars, horizon_minutes=300, minimum_bars=60)["window"])

    def test_inside_the_band_the_settled_claim_refuses(self):
        for minutes in (61, 70, 74):
            raw = self.window_of(minutes)
            settled = normalize_candles([b for b in raw["15m"] if b["complete"]],
                                        get_session_label)
            realtime = normalize_candles(raw["15m"], get_session_label)
            assert len(settled) < MIN_CANDLES <= len(realtime), minutes
            assert calculate_atr(settled)["atr"] is None
            assert calculate_atr(realtime)["atr"] is not None, \
                "not actually inside the divergence band"
            exp = SB.build_snapshot(raw, symbol="MNQ")["expansion"]["15m"]
            assert exp["state"] == "unknown", minutes
            assert exp["magnitude_gated"] is True
            assert exp["displacement_detected"] is False

    def test_the_forming_bar_was_a_fifth_of_that_scale(self):
        """Why refusing is right rather than merely strict."""
        raw = self.window_of(70)
        realtime = normalize_candles(raw["15m"], get_session_label)
        assert len(realtime) == MIN_CANDLES
        assert raw["15m"][-1]["complete"] is False

    def test_below_the_band_nothing_changed(self):
        """At 60 minutes BOTH lanes are already blind -- 2E.1A did not cause it."""
        raw = self.window_of(60)
        realtime = normalize_candles(raw["15m"], get_session_label)
        assert calculate_atr(realtime)["atr"] is None
        assert SB.build_snapshot(raw, symbol="MNQ")["expansion"]["15m"]["state"] \
            == "unknown"

    def test_above_the_band_the_two_scales_agree(self):
        for minutes in (75, 90, 120):
            raw = self.window_of(minutes)
            settled = normalize_candles([b for b in raw["15m"] if b["complete"]],
                                        get_session_label)
            assert calculate_atr(settled)["atr"] is not None, minutes
            assert SB.build_snapshot(raw, symbol="MNQ")["expansion"]["15m"]["state"] \
                != "unknown", minutes

    def test_the_shorter_timeframes_never_enter_the_band(self):
        for minutes in (60, 61, 74, 75, 300):
            snap = SB.build_snapshot(self.window_of(minutes), symbol="MNQ")
            for tf in ("3m", "5m"):
                assert snap["expansion"][tf]["state"] != "unknown", (tf, minutes)


# ── the 15:09 record, corrected ──────────────────────────────────────────────

class TestThe1509RecordIsCorrect:
    """The 2E.1 closeout claimed the PO3 phase change came from `clean_disp`
    going true->false. `0.257 >= 0.30` is FALSE, so clean_disp was False on both
    sides and never cleared. This pins the ACTUAL mechanism from production
    values so the wrong story cannot be reinstated."""

    def expansion_pre_and_post(self):
        with open(FIXTURE, encoding="utf-8") as fh:
            tape = json.load(fh)["bars"]
        end = "2026-08-11T15:09:00+00:00"
        raw = build_timeframes(CONT.coherent_window(
            [b for b in tape if b["timestamp"] <= end],
            horizon_minutes=300, minimum_bars=1)["window"])
        post = SB.build_snapshot(raw, symbol="MNQ")
        # pre-2E.1: ONLY detect_expansion saw the realtime series+scale
        from volatility.expansion_detector import detect_expansion as real_de
        norm = {tf: normalize_candles(raw.get(tf, []), get_session_label)
                for tf in SB.TIMEFRAMES}
        SB.detect_expansion = lambda c, a, tf, s: real_de(
            norm.get(tf, c), calculate_atr(norm.get(tf, c)), tf, s)
        try:
            pre = SB.build_snapshot(raw, symbol="MNQ")
        finally:
            SB.detect_expansion = real_de
        return pre["expansion"]["3m"], post["expansion"]["3m"], pre, post

    def test_clean_disp_was_false_on_both_sides(self):
        pre, post, _, _ = self.expansion_pre_and_post()
        for label, e in (("pre", pre), ("post", post)):
            dir_eff = e["directional_efficiency"]
            clean_disp = e["displacement_detected"] and dir_eff >= 0.30
            assert clean_disp is False, \
                f"{label}: clean_disp True at dir_eff={dir_eff}"
        assert pre["directional_efficiency"] == 0.257
        assert post["directional_efficiency"] == 0.064

    def test_the_real_mechanism_was_three_other_accumulation_terms(self):
        from structure.po3_engine import _compression_score
        pre, post, _, _ = self.expansion_pre_and_post()
        # state: mature_expansion -> early_expansion  (+25 accumulation)
        assert pre["state"] == "mature_expansion"
        assert post["state"] == "early_expansion"
        # compression_score 54 -> 63, crossing the `> 60` term (+20)
        c_pre = _compression_score(pre["directional_efficiency"],
                                   pre["body_dominance"], pre["expansion_score"])
        c_post = _compression_score(post["directional_efficiency"],
                                    post["body_dominance"], post["expansion_score"])
        assert c_pre <= 60 < c_post, (c_pre, c_post)
        # directional_efficiency crossing the `< 0.25` term (+20)
        assert not (pre["directional_efficiency"] < 0.25)
        assert post["directional_efficiency"] < 0.25
