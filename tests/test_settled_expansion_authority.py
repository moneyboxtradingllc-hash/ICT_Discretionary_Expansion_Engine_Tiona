"""CONTINUITY-2E.1 — expansion evidence rests on settled candles.

2E closed the three detectors that read candles directly, but left one seam:
`detect_displacement` took five of six components from settled bars while the
sixth, `directional_efficiency`, still arrived from `detect_expansion` running
on the realtime series. Five-sixths is not clean. `W_EFFICIENCY` is 15 of the
100 points that decide `displacement_confirmed` (threshold 50), and the same
scalar gates `po3_engine`'s `clean_disp` at `dir_eff >= 0.30`.

The audit (AUDIT_2E1_expansion_authority_settledness.md) then found something
stronger: of the ten fields `detect_expansion` publishes, NOT ONE is consumed as
a pure realtime witness. Every one feeds PO3 phase, tool scoring, risk posture, a
permission overlay, or Terra. The single consumer that legitimately wanted the
forming read was `brain_input.expansion_state` -- and CONTINUITY-2G now gives
Terra the forming bar itself, explicitly labelled. So `expansion_state` no longer
has to serve two masters, and one settled expansion object is sufficient.

WHAT 2E.1 DOES NOT OWN:
  volatility / ATR   a magnitude SCALE, not a temporal claim (measured below)
  V3 toolbox zones   Step 2F
  direction tie      2E.2, forensic only
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
from market_data.candle_normalizer import normalize_candles       # noqa: E402
from market_data.session_engine import get_session_label          # noqa: E402
from structure.displacement_detector import (                     # noqa: E402
    W_EFFICIENCY, CONFIRMED_AT, EFFICIENCY_AT, detect_displacement,
)
from market_data.swing_evidence import build_swing_evidence
from structure.structure_engine import analyze_structure          # noqa: E402
from volatility.atr_engine import calculate_atr                   # noqa: E402
from volatility.expansion_detector import detect_expansion        # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def raw_at(end: str) -> dict:
    bars = [b for b in tape() if b["timestamp"] <= end]
    return build_timeframes(CONT.coherent_window(bars, horizon_minutes=300,
                                                 minimum_bars=1)["window"])


def both(end: str) -> tuple:
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


def ends() -> list:
    return sorted({b["timestamp"] for b in tape()})[20:]


# ── the wiring ────────────────────────────────────────────────────────────────

class TestExpansionIsServedFromTheSettledSeries:

    def source(self) -> str:
        from market_data import snapshot_builder as SB
        return inspect.getsource(SB.build_snapshot)

    def test_detect_expansion_takes_settled(self):
        assert "detect_expansion(settled, settled_atr_result, tf," \
            in self.source()

    def test_volatility_stays_realtime_but_the_scale_split_in_two(self):
        """UPDATED BY CONTINUITY-2E.1A (2026-08-11).

        This asserted `classify_volatility(candles, atr_result)` and named ATR as
        "deliberately left realtime". The volatility half stands -- that lane is
        its own open mission. The ATR half did not: an adversarial search proved
        a forming bucket could still author `displacement_detected` and `state`
        through the realtime scale, so there are now two explicitly named ATRs.
        The invariant they enforce lives in
        tests/test_settled_atr_for_settled_evidence.py.
        """
        src = self.source()
        assert "realtime_atr_result = calculate_atr(candles)" in src
        assert "classify_volatility(candles, realtime_atr_result)" in src
        assert "settled_atr_result = calculate_atr(settled)" in src

    def test_the_detector_never_sees_a_forming_bucket(self):
        """Pinned at the production call site, keyed by CALL ORDER -- a 5m and a
        15m bucket share the same bucket-start timestamp, so matching across
        timeframes cross-contaminates."""
        import market_data.snapshot_builder as SB
        raw = raw_at("2026-08-11T15:10:00+00:00")
        calls, original = [], SB.detect_expansion

        def spy(candles, *a, **kw):
            calls.append([c["timestamp"] for c in candles])
            return original(candles, *a, **kw)

        SB.detect_expansion = spy
        try:
            SB.build_snapshot(raw, symbol="MNQ")
        finally:
            SB.detect_expansion = original

        assert len(calls) == len(SB.TIMEFRAMES)
        saw_forming = False
        for tf, got in zip(SB.TIMEFRAMES, calls):
            series = raw.get(tf, [])
            expected = [b["timestamp"] for b in series if b.get("complete", True)]
            assert got == expected, f"expansion on {tf} was not handed settled bars"
            if len(expected) < len(series):
                saw_forming = True
        assert saw_forming, "no forming bucket in this window -- proves nothing"


# ── the residue 2E left, measured ─────────────────────────────────────────────

class TestDirectionalEfficiencyNoLongerCarriesTheFormingBar:
    """The 15/100 scalar. `_directional_efficiency` reads `candles[-1]["close"]`
    -- the PROVISIONAL close -- directly."""

    def test_the_component_is_still_worth_crossing_the_threshold(self):
        """Documents WHY this mattered, so a later weights change is noticed."""
        assert W_EFFICIENCY == 15 and CONFIRMED_AT == 50 and EFFICIENCY_AT == 0.30

    def test_the_settled_snapshot_reports_a_settled_efficiency(self):
        """3m at 15:09Z: 0.257 came from the forming bar; the closed bars say
        0.064.

        CORRECTED (2E.1A): an earlier version of this docstring said 0.064 falls
        "below po3's 0.30 `clean_disp` gate, which the contaminated value
        cleared". **0.257 >= 0.30 is false** -- `clean_disp` was False on BOTH
        sides and never cleared. The 0.257 -> 0.064 move mattered through the
        ACCUMULATION `dir_eff < 0.25` term instead, alongside `state`
        mature->early and `compression_score` crossing 60. The measured
        mechanism is pinned in
        tests/test_settled_atr_for_settled_evidence.py::TestThe1509RecordIsCorrect
        and recorded in AUDIT_2E1A_verification_verdict.md.
        """
        settled, forming = both("2026-08-11T15:09:00+00:00")
        assert settled["expansion"]["3m"]["directional_efficiency"] == 0.064
        assert forming["expansion"]["3m"]["directional_efficiency"] == 0.257

    def test_displacement_scoring_is_now_fully_settled(self):
        """Every one of the six components, not five."""
        settled, forming = both("2026-08-11T15:09:00+00:00")
        s = settled["expansion"]["3m"]["displacement"]
        f = forming["expansion"]["3m"]["displacement"]
        assert (s["classification"], s["score"]) == ("displacement_possible", 25)
        # STEP 4B.12 §4 UNIT 2 — D-CLASS, measured on THIS file's fixture
        # (both loop iterations identical):
        #     structure_break 15 -> 0   (the forming bar's pseudo-BOS)
        #     unchanged: imbalance 25 · follow_through 10 · no_hesitation 5
        #     55 -> 40, CONFIRMED_AT 50 no longer crossed
        assert {c["name"]: c["points"] for c in f["components"]}["structure_break"] == 0
        assert (f["classification"], f["score"]) == ("displacement_possible", 40)
        eff = [c for c in s["components"] if c["name"] == "directional_efficiency"][0]
        assert eff["present"] is False and eff["points"] == 0
        assert "0.064" in eff["detail"]

    def test_po3_clean_disp_no_longer_inherits_a_forming_conviction(self):
        for end in ("2026-08-11T15:09:00+00:00", "2026-08-11T15:10:00+00:00"):
            settled, forming = both(end)
            assert settled["po3"]["3m"]["phase"] == "accumulation", end
            # D-CLASS. bos True->False leaves the structure state at 'neutral',
            # so PO3's *_continuation contribution (-15) and its
            # `if bos and (sweep or reclaim)` transition term (-30) both stop
            # firing. Manipulation is untouched and now wins the phase.
            #
            # NOTE: this test is NAMED for clean_disp/conviction, but both are
            # None on this fixture -- the proposition it actually asserts is the
            # PHASE. Not inventing a dependency the fixture does not exercise.
            assert forming["po3"]["3m"]["phase"] == "manipulation", end


# ── every published field, not just the one that was indicted ────────────────

class TestNoExpansionFieldIsAuthoredByAFormingBar:

    FIELDS = ("state", "expansion_score", "displacement_detected",
              "directional_efficiency", "body_dominance", "exhaustion_risk",
              "kappa", "magnitude_gated")

    def test_the_published_block_equals_a_settled_only_computation(self):
        """Recompute independently from settled bars and demand equality. This
        catches any field -- present or future -- that reaches the snapshot
        carrying the forming bucket."""
        checked = 0
        for end in ends():
            raw = raw_at(end)
            import market_data.snapshot_builder as SB
            snap = SB.build_snapshot(raw, symbol="MNQ")
            for tf in ("3m", "5m", "15m"):
                series = raw.get(tf, [])
                if all(b.get("complete", True) for b in series):
                    continue                       # no forming bucket to prove
                settled = normalize_candles([b for b in series if b["complete"]],
                                            get_session_label)
                if not settled:
                    continue
                # 2E.1A: the scale is now settled too. This recomputation used
                # `calculate_atr(<realtime series>)`, which encoded the very
                # mixed-provenance arrangement 2E.1A removed.
                # STEP 4B.12 §4 UNIT 1: the reference must mirror PRODUCTION's
                # inputs in every respect except the forming bar, which is the
                # single variable this test exists to isolate. Production now
                # builds structure from canonical swing evidence, so a reference
                # that recomputes `analyze_structure(settled)` bare is comparing
                # two different structure inputs and blaming the difference on
                # the forming bucket. Measured: 3m expansion_score 48 vs 45.
                _ev = build_swing_evidence(settled, series,
                                           {'3m': 3, '5m': 5, '15m': 15}[tf])
                expected = detect_expansion(
                    settled, calculate_atr(settled), tf,
                    analyze_structure(settled, _ev))
                got = snap["expansion"][tf]
                for key in self.FIELDS:
                    assert got.get(key) == expected.get(key), (end, tf, key)
                checked += 1
        assert checked > 50, f"only {checked} forming-bucket samples exercised"

    def test_the_state_label_itself_moves_when_the_forming_bar_is_readmitted(self):
        """A behavioural anchor, so the fix cannot be DEFEATED rather than
        deleted -- the source assertions above would survive `if False:`.

        Asserted per timeframe rather than on `market_regime.expansion_state`,
        and that is a deliberate, measured choice: `expansion_state` is the 15m
        state alone, and this 50-minute gold window holds only three 15m buckets,
        so the 15m label does NOT discriminate here (measured: 0 of 31 scans).
        The 3m and 5m labels each move on 7 of 31. Asserting on
        `expansion_state` would have been a test that passes for the wrong
        reason on a longer tape and fails for the wrong reason on this one.

        Measured on this fixture, settled vs forming:
            directional_efficiency  3m 20/31   5m 17/31
            body_dominance          3m 20/31   5m 17/31
            expansion_score         3m 19/31   5m 17/31
            exhaustion_risk         3m 11/31   5m 13/31
            state                   3m  7/31   5m  7/31
        """
        moved = {"3m": 0, "5m": 0}
        for end in ends():
            settled, forming = both(end)
            for tf in moved:
                if settled["expansion"][tf].get("state") != \
                        forming["expansion"][tf].get("state"):
                    moved[tf] += 1
        assert moved["3m"] >= 5 and moved["5m"] >= 5, \
            f"the fixture no longer discriminates the expansion state: {moved}"


# ── the measured reason ATR stays realtime ────────────────────────────────────

class TestAtrIsAScaleNotATemporalClaim:
    """2E.1 leaves ATR realtime ON EVIDENCE, not by omission."""

    def samples(self):
        for end in ends():
            raw = raw_at(end)
            for tf in ("3m", "5m", "15m"):
                series = raw.get(tf, [])
                settled_raw = [b for b in series if b.get("complete", True)]
                if not settled_raw or len(settled_raw) == len(series):
                    continue
                norm = normalize_candles(series, get_session_label)
                settled = normalize_candles(settled_raw, get_session_label)
                yield tf, norm, settled

    def test_a_settled_atr_would_sometimes_be_unavailable_and_blind_expansion(self):
        blinded = 0
        for tf, norm, settled in self.samples():
            if calculate_atr(settled).get("atr") is None:
                st = analyze_structure(settled)
                out = detect_expansion(settled, calculate_atr(settled), tf, st)
                assert out["state"] == "unknown" and out["magnitude_gated"] is True
                blinded += 1
        assert blinded > 0, \
            "no ATR-unavailable sample -- the stated reason is unevidenced here"

    def test_where_a_settled_atr_exists_it_changes_nothing(self):
        compared = 0
        for tf, norm, settled in self.samples():
            atr_st = calculate_atr(settled)
            if atr_st.get("atr") is None:
                continue
            st = analyze_structure(settled)
            e1 = detect_expansion(settled, calculate_atr(norm), tf, st)
            e2 = detect_expansion(settled, atr_st, tf, st)
            for key in TestNoExpansionFieldIsAuthoredByAFormingBar.FIELDS:
                assert e1.get(key) == e2.get(key), (tf, key)
            d1 = detect_displacement(settled, st, calculate_atr(norm).get("atr"), e1)
            d2 = detect_displacement(settled, st, atr_st.get("atr"), e2)
            assert d1["classification"] == d2["classification"], tf
            compared += 1
        assert compared > 20, f"only {compared} comparisons -- too thin to claim zero"


# ── what 2E.1 must not have changed ──────────────────────────────────────────

class TestNothingElseMoved:

    def test_terra_still_receives_the_forming_bar_labelled(self):
        """2G is what makes a settled `expansion_state` acceptable: the realtime
        view did not vanish, it moved to a channel that tells the truth."""
        from ai_brain.brain_input import build_brain_input
        import market_data.snapshot_builder as SB
        snap = SB.build_snapshot(raw_at("2026-08-11T15:05:00+00:00"), symbol="MNQ")
        block = build_brain_input(snap, {})["market"]["candles"]["15m"]
        assert block["last_candle_temporal_status"] == "forming"
        assert block["last_candle_members"] == 6
        assert block["last_candle_expected_members"] == 15

    def test_structure_and_liquidity_are_untouched(self):
        import market_data.snapshot_builder as SB
        snap = SB.build_snapshot(raw_at("2026-08-11T15:10:00+00:00"), symbol="MNQ")
        assert snap["structure"]["3m"].get("bos") is False
        assert snap["liquidity"]["3m"].get("nearest_sell_side_liquidity") == 29723.25

    def test_toolbox_zone_provenance_is_still_2f(self):
        """V3 is Step 2F. If 2E.1 quietly fixed it too, the missions have blurred
        and 2F would ship with no forensic replay of its own.

        BEHAVIOURAL, after the source version ESCAPED its own mutation: asserting
        `'tfs.get(tf, {}).get("recent_candles", [])' in source` passed happily
        when that exact substring was wrapped in a comprehension filtering out
        `temporal_status == "forming"`. The string survived; the behaviour did
        not. Spy on what the zone builder is actually handed instead.
        """
        from toolbox import price_levels as PL
        import market_data.snapshot_builder as SB

        snap = SB.build_snapshot(raw_at("2026-08-11T15:05:00+00:00"), symbol="MNQ")
        seen, original = [], PL._build_zone_for_family

        def spy(fam, direction, struct, liq, candles, tf, current):
            seen.append([c.get("temporal_status") for c in candles])
            return original(fam, direction, struct, liq, candles, tf, current)

        PL._build_zone_for_family = spy
        try:
            for tool in ("bullish_fvg", "bearish_fvg", "bullish_order_block"):
                PL.build_price_level(tool, snap)
        finally:
            PL._build_zone_for_family = original

        assert seen, "the zone builder was never reached -- assertion is vacuous"
        assert any("forming" in call for call in seen), \
            "the toolbox no longer receives the forming bar -- V3/2F was changed here"
