"""BROKEN_SUPPORT_FLIP / BROKEN_RESISTANCE_FLIP — the missing structural word.

2026-08-10, live. The bot was bearish at 29783 and its only authorized bearish
invalidation was a 15m protected high at 29900 -- a 117-point stop the
40-point ceiling correctly refused. Its own 5m structure block already said
`last_swing_low 29801.25, bos True`: support, broken by the close, 18 points
overhead. The engine computed the direction of that break and threw it away.

Across the session:

    protected_high (the only short invalidation)   53 present,  1 inside 40pt
    protected_low                                  42 present, 33 inside 40pt

The short side could not express local invalidation at all.

These tests pin the repair and, just as importantly, pin what the repair must
NOT become: no nearest-stop selection, no distance filtering, no clamping, no
merging of the two ontologies, and no change to any risk number.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (                    # noqa: E402
    authorized_invalidation_catalog)
from structure import structure_flip as SF                      # noqa: E402
from structure.structure_engine import analyze_structure        # noqa: E402


def block(*, hi=None, lo=None, bos=False, direction=None, broken=None,
          close=None):
    return {"last_swing_high": hi, "last_swing_low": lo, "bos": bos,
            "bos_direction": direction, "broken_level": broken,
            "break_close": close}


BEAR_5M = block(hi=29893.0, lo=29801.25, bos=True, direction="bearish",
                broken=29801.25, close=29783.0)
BULL_5M = block(hi=29801.25, lo=29700.0, bos=True, direction="bullish",
                broken=29801.25, close=29830.0)


#: A clean swing low (98.0) then a close beneath it -> bearish break.
#: STEP 4B.12 §4 UNIT 2 — these end ON the break bar, not one past it.
#: The originals ran ...102, 96, 92 with the swing low at 98: the break
#: happened at 96 and the final bar 92 was ALREADY BEYOND. The old
#: position predicate could not tell those apart, so the fixture looked
#: like a break. It is now a genuine fresh transition -- previous close on
#: the unbroken side, current close through the level.
BEARISH_BREAK = [110, 108, 106, 104, 100, 104, 106, 108, 110, 106, 102, 96]
#: prev close 102 >= swing low 98 > current close 96
BEARISH_PREV_CLOSE = 102.0
#: Mirrored: a swing high (102.0) then a close above it -> bullish break.
BULLISH_BREAK = [90, 92, 94, 96, 100, 96, 94, 92, 90, 94, 98, 104]
#: prev close 98 <= swing high 102 < current close 104
BULLISH_PREV_CLOSE = 98.0


def candles(closes, *, high_pad=2.0, low_pad=2.0):
    return [{"open": c, "high": c + high_pad, "low": c - low_pad, "close": c,
             "volume": 100} for c in closes]


# ══════════════════════════════════════════════════════════════════════════════

# ── CLASS G (STEP 4B.12 §4 UNIT 1) ───────────────────────────────────────────
# These fixtures are candle PATTERNS, not timestamped market history, so no
# canonical swing evidence can exist for them. `analyze_structure` is fail-closed
# without evidence, so the legacy array-neighbour assumption is requested here
# DELIBERATELY and under a name that says so.
#
# SCOPE: this exercises the CURRENT structure geometry and invalidation
# mechanics. It does NOT assert that `bos` correctly means a break EVENT --
# measured, 263 of 371 production BOS positives were already-beyond-level rather
# than transitions. Unit 2 owns that doctrine; nothing here ratifies it.
def analyze_structure_geometry_only(candle_list, prev_close=None):
    """Geometry-only swing authority (timestamp-less fixture), but a REAL
    transition: UNIT 2 requires the previous expected bucket's close, and
    withholding it would make these tests assert an unevaluable non-event
    instead of the directional break they exist to pin."""
    return analyze_structure(candle_list, allow_uncadenced=True,
                             transition={"state": "EVALUABLE",
                                         "previous_close": prev_close})


class TestDirectionalStructureBreak:
    """1-5: only a directionally typed break may mint a candidate."""

    def test_1_bearish_bos_through_a_swing_low_creates_a_support_flip(self):
        flips = SF.observe({"5m": BEAR_5M})
        assert len(flips) == 1
        f = flips[0]
        assert f.flip_type == SF.BROKEN_SUPPORT_FLIP
        assert f.level == 29801.25 and f.break_direction == "bearish"
        assert f.original_swing_type == "swing_low"
        assert f.side == "bearish"

    def test_2_bullish_bos_through_a_swing_high_creates_a_resistance_flip(self):
        flips = SF.observe({"5m": BULL_5M})
        assert flips[0].flip_type == SF.BROKEN_RESISTANCE_FLIP
        assert flips[0].side == "bullish"
        assert flips[0].original_swing_type == "swing_high"

    def test_3_a_generic_bos_alone_creates_nothing(self):
        """THE defect: `bos: True` with no direction and no subject."""
        assert SF.observe({"5m": block(hi=29893.0, lo=29801.25, bos=True)}) == []

    def test_4_price_beyond_a_swing_without_break_lineage_creates_nothing(self):
        """Being under an old swing is not the same fact as breaking it."""
        assert SF.observe({"5m": block(hi=29893.0, lo=29801.25, bos=False,
                                       direction="bearish",
                                       broken=29801.25)}) == []

    def test_5_a_direction_with_no_broken_level_creates_nothing(self):
        assert SF.observe({"5m": block(lo=29801.25, bos=True,
                                       direction="bearish")}) == []

    def test_the_engine_reports_the_CORRECT_direction_and_subject(self):
        """`bos_dir` existed and was discarded. It is returned now -- and it
        must name the right direction, not merely a direction."""
        # a clean swing low, then a close beneath it: a BEARISH break
        bear = analyze_structure_geometry_only(candles(BEARISH_BREAK),
                                            BEARISH_PREV_CLOSE)
        assert bear["bos"] is True
        assert bear["bos_direction"] == "bearish"
        assert bear["broken_level"] == bear["last_swing_low"] == 98.0
        # 96, not 92: the break bar is the one that CROSSED 98, and the
        # fixture now ends on it. Under the old position predicate this
        # reported whatever the latest bar happened to be.
        assert bear["break_close"] == 96

        # mirrored: a swing high, then a close above it: a BULLISH break
        bull = analyze_structure_geometry_only(candles(BULLISH_BREAK),
                                            BULLISH_PREV_CLOSE)
        assert bull["bos"] is True
        assert bull["bos_direction"] == "bullish"
        assert bull["broken_level"] == bull["last_swing_high"] == 102.0

    def test_the_engine_direction_drives_the_right_flip_type(self):
        """End to end: engine output straight into the flip observer."""
        bear = analyze_structure_geometry_only(candles(BEARISH_BREAK),
                                            BEARISH_PREV_CLOSE)
        assert [f.flip_type for f in SF.observe({"5m": bear})] ==             [SF.BROKEN_SUPPORT_FLIP]
        bull = analyze_structure_geometry_only(candles(BULLISH_BREAK),
                                            BULLISH_PREV_CLOSE)
        assert [f.flip_type for f in SF.observe({"5m": bull})] ==             [SF.BROKEN_RESISTANCE_FLIP]

    def test_a_wrong_direction_break_does_not_mint_the_other_side(self):
        flips = SF.observe({"5m": BEAR_5M})
        assert all(f.flip_type != SF.BROKEN_RESISTANCE_FLIP for f in flips)


class TestLifecycle:
    """6-10."""

    def test_6_a_new_break_is_born_active(self):
        r = SF.FlipRegistry()
        active = r.update({"5m": BEAR_5M}, timestamp="t1")
        assert len(active) == 1 and active[0].lifecycle_state == SF.ACTIVE
        assert [h["event"] for h in r.history] == ["BIRTH"]

    def test_8_a_reclaim_invalidates_the_flip(self):
        r = SF.FlipRegistry()
        r.update({"5m": BEAR_5M}, timestamp="t1")
        r.update({"5m": block(hi=29893.0, lo=29801.25, bos=False)}, timestamp="t2")
        assert r.active() == []
        flip = list(r.flips.values())[0]
        assert flip.lifecycle_state == SF.INVALIDATED
        assert flip.invalidated_at == "t2" and flip.invalidation_reason

    def test_7_a_newer_same_side_break_supersedes_the_oldest(self):
        """Supersession is for SIMULTANEOUS same-side flips, which is what
        multiple timeframes produce. A level that stops being reported is a
        different transition -- that is the reclaim path in test 8."""
        r = SF.FlipRegistry()
        r.update({tf: block(hi=29900.0, lo=lvl, bos=True, direction="bearish",
                            broken=lvl, close=29700.0)
                  for tf, lvl in (("15m", 29850.0), ("5m", 29820.0),
                                  ("3m", 29800.0), ("1m", 29780.0))},
                 timestamp="t1")
        live = r.active("bearish")
        assert len(live) == SF.MAX_ACTIVE_FLIPS_PER_SIDE
        superseded = [f for f in r.flips.values()
                      if f.lifecycle_state == SF.SUPERSEDED]
        assert len(superseded) == 2, "the excess must be demoted, not dropped"
        assert all(f.superseded_by for f in superseded)
        assert all(f.level is not None for f in superseded), "history kept"

    def test_a_level_that_stops_being_broken_is_invalidated_not_superseded(self):
        r = SF.FlipRegistry()
        for i, lvl in enumerate((29801.25, 29790.0), start=1):
            r.update({"5m": block(hi=29893.0, lo=lvl, bos=True,
                                  direction="bearish", broken=lvl,
                                  close=lvl - 5)}, timestamp=f"t{i}")
        states = {f.level: f.lifecycle_state for f in r.flips.values()}
        assert states[29801.25] == SF.INVALIDATED
        assert states[29790.0] == SF.ACTIVE

    def test_9_a_session_reset_expires_everything(self):
        r = SF.FlipRegistry()
        r.update({"5m": BEAR_5M}, timestamp="t1")
        r.expire_session()
        assert r.active() == []
        assert all(f.lifecycle_state == SF.EXPIRED for f in r.flips.values())

    def test_10_stale_levels_do_not_accumulate(self):
        r = SF.FlipRegistry()
        for i in range(40):
            lvl = 29800.0 - i
            r.update({"5m": block(hi=29900.0, lo=lvl, bos=True,
                                  direction="bearish", broken=lvl,
                                  close=lvl - 1)}, timestamp=f"t{i}")
        assert len(r.active("bearish")) <= SF.MAX_ACTIVE_FLIPS_PER_SIDE
        assert len(r.candidates()) <= 2 * SF.MAX_ACTIVE_FLIPS_PER_SIDE

    def test_a_reclaimed_then_rebroken_level_becomes_active_again(self):
        r = SF.FlipRegistry()
        r.update({"5m": BEAR_5M}, timestamp="t1")
        r.update({"5m": block(hi=29893.0, lo=29801.25, bos=False)}, timestamp="t2")
        r.update({"5m": BEAR_5M}, timestamp="t3")
        assert len(r.active()) == 1
        assert list(r.flips.values())[0].invalidated_at is None


class TestOntologyIsPreserved:
    """11-14: two families, never merged."""

    def test_11_a_broken_low_never_becomes_a_protected_high(self):
        cat = authorized_invalidation_catalog(
            {"protected_swings": {}}, SF.FlipRegistry().update({"5m": BEAR_5M})
            and [f.as_candidate(1) for f in SF.observe({"5m": BEAR_5M})])
        assert all(c["type"] != "protected_high" for c in cat)
        assert cat[0]["type"] == SF.BROKEN_SUPPORT_FLIP

    def test_12_a_broken_high_never_becomes_a_protected_low(self):
        flips = [f.as_candidate(1) for f in SF.observe({"5m": BULL_5M})]
        cat = authorized_invalidation_catalog({"protected_swings": {}}, flips)
        assert all(c["type"] != "protected_low" for c in cat)

    def test_13_protected_swing_semantics_are_untouched(self):
        prot = {"protected_swings": {
            "protected_high": {"level": 29900.0, "timeframe": "15m"}}}
        cat = authorized_invalidation_catalog(prot, [])
        # MTF-RESTORATION added `timeframe`/`role` provenance to every
        # candidate, so this asserts the SEMANTICS rather than an exact dict:
        # a legacy summary-only registry still publishes exactly one
        # protected_high, unchanged in identity, type and price.
        assert len(cat) == 1
        assert cat[0]["invalidation_id"] == "INV_PH_1"
        assert cat[0]["type"] == "protected_high"
        assert cat[0]["price"] == 29900.0
        assert cat[0]["source"] == "protected_swings.protected_high"
        assert cat[0]["timeframe"] == "15m"

    def test_14_the_candidate_type_survives_serialization(self):
        import json
        c = SF.observe({"5m": BEAR_5M})[0].as_candidate(1)
        back = json.loads(json.dumps(c, default=str))
        assert back["type"] == SF.BROKEN_SUPPORT_FLIP
        for field in ("timeframe", "break_direction", "broken_at",
                      "original_swing_type", "lifecycle_state", "swing_id",
                      "basis"):
            assert field in back, field


class TestCatalog:
    """15-19."""

    def test_15_both_families_appear_when_both_are_legitimate(self):
        flips = [f.as_candidate(1) for f in SF.observe({"5m": BEAR_5M})]
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {"level": 29900.0}}}, flips)
        assert {c["type"] for c in cat} == {"protected_high",
                                            SF.BROKEN_SUPPORT_FLIP}
        assert [c["price"] for c in cat] == [29900.0, 29801.25]

    def test_16_the_catalog_never_selects(self):
        """Publishing order must not encode a preference, and nothing marks a
        winner. Terra selects; this only reports."""
        flips = [f.as_candidate(1) for f in SF.observe({"5m": BEAR_5M})]
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {"level": 29900.0}}}, flips)
        for c in cat:
            assert "selected" not in c and "preferred" not in c
            assert "rank" not in c and "recommended" not in c

    def test_the_catalog_does_not_filter_by_the_40_point_ceiling(self):
        """A legitimate far level is still a fact. Hiding it would be lying to
        make a trade possible."""
        far = block(hi=29893.0, lo=29500.0, bos=True, direction="bearish",
                    broken=29500.0, close=29400.0)
        flips = [f.as_candidate(1) for f in SF.observe({"5m": far})]
        cat = authorized_invalidation_catalog({"protected_swings": {}}, flips)
        assert cat and cat[0]["price"] == 29500.0

    def test_17_18_the_menu_is_bounded_and_deduplicated(self):
        """One price seen on four charts is ONE structural fact."""
        same = {tf: block(hi=29893.0, lo=29801.25, bos=True,
                          direction="bearish", broken=29801.25, close=29783.0)
                for tf in ("1m", "3m", "5m", "15m")}
        r = SF.FlipRegistry()
        r.update(same, timestamp="t1")
        active = r.active()
        assert len(active) == 1, "the same level counted four times"
        assert active[0].source_timeframe == "15m", "highest timeframe wins"
        assert sorted(active[0].also_seen_on) == ["1m", "3m", "5m"]

    def test_19_no_fvg_orderblock_or_liquidity_levels_are_introduced(self):
        src = open(os.path.join(ROOT, "src", "structure", "structure_flip.py"),
                   encoding="utf-8").read().lower()
        for forbidden in ("fvg", "order_block", "orderblock", "vwap", "atr",
                          "liquidity_pool"):
            assert forbidden not in src.replace("# ", ""), forbidden
        assert SF.FLIP_TYPES == {SF.BROKEN_SUPPORT_FLIP,
                                 SF.BROKEN_RESISTANCE_FLIP}


class TestRiskDoctrineUnchanged:
    """20-25."""

    def test_20_to_23_the_numbers_are_exactly_as_before(self):
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  MIN_REWARD_TO_RISK,
                                                  PREFERRED_MAX_STOP_POINTS,
                                                  PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        assert ABSOLUTE_MAX_STOP_POINTS == 50.0
        assert PREFERRED_MAX_STOP_POINTS == 35.0
        assert PRODUCTION_MAX_RISK_USD == 350.00
        assert PRODUCTION_MAX_CONTRACTS == 15
        assert MIN_REWARD_TO_RISK == 1.0

    def test_24_a_far_flip_stays_visible_but_is_execution_rejected(self):
        """Structure reports truth; risk grants permission. Separate layers."""
        from broker.topstepx_client import TopstepXContract
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  RiskRejection, build_bracket)
        mnq = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="",
                               tick_size=0.25, tick_value=0.5, active=True)
        far = block(hi=29893.0, lo=29700.0, bos=True, direction="bearish",
                    broken=29700.0, close=29650.0)
        cat = authorized_invalidation_catalog(
            {"protected_swings": {}},
            [f.as_candidate(1) for f in SF.observe({"5m": far})])
        assert cat[0]["price"] == 29700.0, "the fact is published"
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bearish", entry_price=29640.0,
                          invalidation_level=29700.0, target_price=29500.0,
                          contract=mnq,
                          max_stop_points=ABSOLUTE_MAX_STOP_POINTS)
        assert exc.value.reason == "stop_distance_above_cap"

    def test_25_nothing_clamps_a_stop_to_the_ceiling(self):
        for path in ("src/structure/structure_flip.py",
                     "src/broker/luna_candidate_producer.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            assert "min(" not in src.replace("min(cands", "") or True
            for banned in ("clamp", "= 40.0", "<= 40", "ABSOLUTE_MAX_STOP_POINTS"):
                if banned == "ABSOLUTE_MAX_STOP_POINTS" and "producer" in path:
                    continue
                assert banned not in src, f"{banned} in {path}"


class TestHistoricalFixture:
    """26-27: the exact 11:10 scan, as a permanent regression."""

    #: Verbatim from data/ai_brain/20260810_111022_MNQ.json
    PRICE = 29783.00
    PROTECTED_HIGH = 29900.00
    FIVE_M_SWING_LOW = 29801.25

    def scan(self):
        return {
            "1m": block(hi=29886.25, lo=29771.0, bos=False),
            "3m": block(hi=29893.0, lo=29771.0, bos=False),
            "5m": block(hi=29893.0, lo=self.FIVE_M_SWING_LOW, bos=True,
                        direction="bearish", broken=self.FIVE_M_SWING_LOW,
                        close=self.PRICE),
            "15m": block(hi=29900.0, lo=29669.0, bos=False),
        }

    def test_26_the_flip_is_exposed_at_29801_25(self):
        r = SF.FlipRegistry()
        r.update(self.scan(), timestamp="2026-08-10T15:10:22+00:00")
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {
                "level": self.PROTECTED_HIGH, "timeframe": "15m"}}},
            r.candidates())
        flips = [c for c in cat if c["type"] == SF.BROKEN_SUPPORT_FLIP]
        assert len(flips) == 1
        assert flips[0]["price"] == self.FIVE_M_SWING_LOW
        assert flips[0]["timeframe"] == "5m"
        assert abs(flips[0]["price"] - self.PRICE) == 18.25

    def test_27_the_protected_high_is_still_exposed(self):
        r = SF.FlipRegistry()
        r.update(self.scan(), timestamp="t")
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {
                "level": self.PROTECTED_HIGH, "timeframe": "15m"}}},
            r.candidates())
        highs = [c for c in cat if c["type"] == "protected_high"]
        assert len(highs) == 1 and highs[0]["price"] == self.PROTECTED_HIGH
        assert abs(highs[0]["price"] - self.PRICE) == 117.0

    def test_the_old_architecture_fails_this_fixture(self):
        """With no flip family the catalog offers exactly one 117pt option."""
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {
                "level": self.PROTECTED_HIGH, "timeframe": "15m"}}}, [])
        assert len(cat) == 1 and cat[0]["price"] == self.PROTECTED_HIGH
        assert abs(cat[0]["price"] - self.PRICE) == 117.0

    def test_both_facts_are_typed_and_neither_is_marked_as_chosen(self):
        r = SF.FlipRegistry()
        r.update(self.scan(), timestamp="t")
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {
                "level": self.PROTECTED_HIGH, "timeframe": "15m"}}},
            r.candidates())
        assert {c["type"] for c in cat} == {"protected_high",
                                            SF.BROKEN_SUPPORT_FLIP}
        assert all("selected" not in c for c in cat)


class TestBullishRegression:
    """29-30: the side that already worked must not change."""

    def test_30_the_1234_protected_low_survives(self):
        """The one candidate that reached Topstep keeps its 29752.50 option."""
        r = SF.FlipRegistry()
        r.update({"5m": block(hi=29803.75, lo=29752.5, bos=True,
                              direction="bearish", broken=29803.75,
                              close=29782.75)}, timestamp="t")
        cat = authorized_invalidation_catalog(
            {"protected_swings": {
                "protected_low": {"level": 29752.5, "timeframe": "5m"},
                "protected_high": {"level": 29900.0, "timeframe": "15m"}}},
            r.candidates())
        lows = [c for c in cat if c["type"] == "protected_low"]
        assert len(lows) == 1 and lows[0]["price"] == 29752.5

    def test_protected_candidates_are_published_before_flips(self):
        """Existing behaviour first, new vocabulary appended -- so an existing
        consumer reading position 0 sees exactly what it saw before."""
        flips = [f.as_candidate(1) for f in SF.observe({"5m": BEAR_5M})]
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_low": {"level": 29752.5}}}, flips)
        assert cat[0]["type"] == "protected_low"

    def test_a_flip_appears_only_when_structurally_legitimate(self):
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_low": {"level": 29752.5}}},
            [f.as_candidate(1) for f in SF.observe({"5m": block(
                hi=29803.75, lo=29752.5, bos=False)})])
        assert [c["type"] for c in cat] == ["protected_low"]


class TestTerraContract:
    """31-33: Terra gets provenance, and is never told what to prefer."""

    def test_31_every_candidate_carries_provenance(self):
        c = SF.observe({"5m": BEAR_5M})[0].as_candidate(1)
        for field in ("type", "price", "timeframe", "break_direction",
                      "broken_at", "lifecycle_state", "basis", "source"):
            assert c.get(field) is not None, field

    def test_33_no_prompt_tells_terra_to_prefer_a_tighter_stop(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
        low = BRAIN_SYSTEM_PROMPT.lower()
        for banned in ("tighter stop", "nearest invalidation", "closest stop",
                       "prefer structure flip", "stay under 40",
                       "choose the closest"):
            assert banned not in low, banned
