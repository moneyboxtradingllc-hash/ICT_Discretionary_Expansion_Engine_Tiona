"""OBJECTIVE-SCALE-PRESERVATION-1A — scale survives, behaviour does not change.

The defect this represents against: `brain_input` collapses the per-timeframe
liquidity hierarchy with `next()` over `("15m","5m","3m","1m")`, which returns
the HIGHEST TIMEFRAME that has a pool and calls it `nearest_buy_side`. On
2026-08-25 that handed Luna 29409.25 while her path ownership had reached only
1m, and never showed her the 1m pool ~24 points away.

This unit only makes the hierarchy derivable. It is wired to nothing, so the
last section proves the production surface is untouched.

No broker. No provider. No network.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from structure import liquidity_scale as LS                          # noqa: E402

BUY, SELL = LS.BUY_SIDE, LS.SELL_SIDE
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


def block(**by_tf):
    """A snapshot.liquidity block in its real shape."""
    out = {}
    for tf, (buy, sell) in by_tf.items():
        row = {}
        if buy is not None:
            row["nearest_buy_side_liquidity"] = buy
        if sell is not None:
            row["nearest_sell_side_liquidity"] = sell
        out[tf] = row
    return out


#: The real 2026-08-25 pools, read out of the archive.
AUG25 = block(**{"1m": (29249.25, 29209.25), "3m": (29345.0, 29145.5),
                 "5m": (29345.0, None), "15m": (29409.25, None)})


# ══ SCALE SURVIVES ══════════════════════════════════════════════════════════
class TestEveryScaleIsPreserved:

    def prices(self, side, src=AUG25):
        return [r["price"] for r in LS.canonical_pools(src, side=side)]

    def test_the_1m_pool_is_no_longer_discarded(self):
        assert 29249.25 in self.prices(BUY)

    def test_the_3m_and_5m_level_survives(self):
        assert 29345.0 in self.prices(BUY)

    def test_the_15m_pool_survives(self):
        assert 29409.25 in self.prices(BUY)

    def test_the_full_aug25_buy_hierarchy(self):
        assert self.prices(BUY) == [29249.25, 29345.0, 29409.25]

    def test_the_sell_side_hierarchy_is_equally_preserved(self):
        """The same defect exists on the sell side: legacy publishes the 3m
        pool while the 1m pool is nearer."""
        assert self.prices(SELL) == [29209.25, 29145.5]

    def test_a_missing_timeframe_is_omitted_not_nulled(self):
        rows = LS.canonical_pools(block(**{"1m": (100.0, None)}), side=BUY)
        assert len(rows) == 1 and rows[0]["supporting_timeframes"] == ["1m"]

    def test_an_absent_liquidity_block_is_empty(self):
        assert LS.canonical_pools({}, side=BUY) == []
        assert LS.canonical_pools(None, side=BUY) == []


# ══ ONE LEVEL, MANY WITNESSES ═══════════════════════════════════════════════
class TestSamePriceDeduplication:

    def test_3m_and_5m_at_one_price_become_one_destination(self):
        rows = [r for r in LS.canonical_pools(AUG25, side=BUY)
                if r["price"] == 29345.0]
        assert len(rows) == 1, "one level became two objectives"
        assert rows[0]["supporting_timeframes"] == ["3m", "5m"]

    def test_the_merge_keeps_both_witnesses(self):
        row = [r for r in LS.canonical_pools(AUG25, side=BUY)
               if r["price"] == 29345.0][0]
        assert row["shallowest_timeframe"] == "3m"
        assert row["deepest_timeframe"] == "5m"

    def test_distinct_prices_never_merge(self):
        src = block(**{"3m": (29345.0, None), "5m": (29350.0, None)})
        assert len(LS.canonical_pools(src, side=BUY)) == 2

    def test_one_tick_apart_is_two_levels(self):
        src = block(**{"3m": (29345.0, None), "5m": (29345.25, None)})
        rows = LS.canonical_pools(src, side=BUY, tick_size=0.25)
        assert len(rows) == 2, "adjacent ticks were merged"

    def test_float_noise_is_one_level(self):
        src = block(**{"3m": (29345.0, None), "5m": (29345.0 + 1e-9, None)})
        assert len(LS.canonical_pools(src, side=BUY)) == 1

    def test_all_four_timeframes_at_one_price_stay_one_level(self):
        src = block(**{tf: (29345.0, None) for tf in ("1m", "3m", "5m", "15m")})
        rows = LS.canonical_pools(src, side=BUY)
        assert len(rows) == 1
        assert rows[0]["supporting_timeframes"] == ["1m", "3m", "5m", "15m"]


# ══ PRICE IDENTITY IS DECLARED, NOT ASSUMED ═════════════════════════════════
class TestPriceIdentityAuthority:
    """`snapshot.liquidity` carries no tick geometry, so which comparison ran
    must be reported rather than guessed at by a reader."""

    def test_with_a_tick_it_says_half_tick(self):
        h = LS.hierarchy(AUG25, reference_price=29225.0, tick_size=0.25)
        assert h["price_identity"] == LS.TICK_IDENTITY and h["tick_size"] == 0.25

    def test_without_a_tick_it_says_rounding(self):
        h = LS.hierarchy(AUG25, reference_price=29225.0)
        assert h["price_identity"] == LS.DECIMAL_IDENTITY
        assert h["tick_size"] is None

    def test_half_tick_boundary(self):
        assert LS.same_level(29345.0, 29345.1, 0.25) is True     # <= 0.125
        assert LS.same_level(29345.0, 29345.25, 0.25) is False
        assert LS.same_level(None, 29345.0) is False


# ══ DIRECTION AND DISTANCE ══════════════════════════════════════════════════
class TestDirectionalSymmetry:

    def test_buy_side_distance_is_positive_above_price(self):
        rows = LS.canonical_pools(AUG25, side=BUY, reference_price=29225.0)
        assert all(r["distance"] > 0 for r in rows)

    def test_sell_side_distance_is_positive_below_price(self):
        rows = LS.canonical_pools(AUG25, side=SELL, reference_price=29225.0)
        assert all(r["distance"] > 0 for r in rows)

    def test_a_pool_price_has_traded_past_reads_negative(self):
        """Not an error — price trading past a level is a fact worth carrying."""
        rows = LS.canonical_pools(block(**{"1m": (29200.0, None)}), side=BUY,
                                  reference_price=29225.0)
        assert rows[0]["distance"] == -25.0

    def test_no_reference_price_leaves_distance_unknown(self):
        rows = LS.canonical_pools(AUG25, side=BUY)
        assert all(r["distance"] is None for r in rows)

    def test_the_mirror_is_structural_not_special_cased(self):
        mirrored = block(**{"1m": (None, 29249.25), "3m": (None, 29345.0),
                            "5m": (None, 29345.0), "15m": (None, 29409.25)})
        buy = LS.canonical_pools(AUG25, side=BUY)
        sell = LS.canonical_pools(mirrored, side=SELL)
        assert [r["price"] for r in buy] == [r["price"] for r in sell]
        assert [r["supporting_timeframes"] for r in buy] == \
            [r["supporting_timeframes"] for r in sell]


# ══ THE LEGACY FIELD IS UNTOUCHED ═══════════════════════════════════════════
class TestLegacyBehaviourUnchanged:

    def test_legacy_still_returns_the_HTF_pool_not_the_nearest(self):
        """Documenting the semantic defect without changing it."""
        assert LS.legacy_flattened(AUG25, BUY) == 29409.25
        nearest = min(LS.canonical_pools(AUG25, side=BUY,
                                         reference_price=29225.0),
                      key=lambda r: r["distance"])["price"]
        assert nearest == 29249.25
        assert LS.legacy_flattened(AUG25, BUY) != nearest

    def test_legacy_sell_side_matches_production(self):
        assert LS.legacy_flattened(AUG25, SELL) == 29145.5

    def test_brain_input_flattening_is_byte_identical_to_the_legacy_helper(self):
        """If these ever diverge, the comparison helper has become a second
        authority instead of a mirror."""
        _TFS = ("15m", "5m", "3m", "1m")
        for side, field in ((BUY, "nearest_buy_side_liquidity"),
                            (SELL, "nearest_sell_side_liquidity")):
            production = next(((AUG25.get(tf, {}) or {}).get(field)
                               for tf in _TFS
                               if (AUG25.get(tf, {}) or {}).get(field)), None)
            assert LS.legacy_flattened(AUG25, side) == production


# ══ BEHAVIOURAL INERTNESS ═══════════════════════════════════════════════════
class TestNothingConsumesThisYet:
    """1A must not change the decision surface. The strongest proof is that no
    production module imports it."""

    def test_no_production_module_imports_liquidity_scale(self):
        """STRUCTURAL: does production IMPORT the scale module?

        Same repair as the recovery kernel's. `rule_governance.
        epistemic_closure` registers `liquidity.scale_hierarchy` as a certified
        REPRESENTATION that is deliberately not Brain authority, which means it
        names this module without depending on it. The AST distinguishes the two.
        """
        from rule_governance.epistemic_closure import authority_ast as AST
        src_root = os.path.join(ROOT, "src")
        hits = AST.imports_module(
            src_root, "liquidity_scale",
            exclude_files=[os.path.join(src_root, "structure",
                                        "liquidity_scale.py")])
        assert hits == [], hits
    def test_the_module_mutates_nothing_it_is_given(self):
        src = json.loads(json.dumps(AUG25))
        before = json.dumps(src, sort_keys=True)
        LS.hierarchy(src, reference_price=29225.0, tick_size=0.25)
        assert json.dumps(src, sort_keys=True) == before

    def test_it_asserts_no_entitlement(self):
        h = LS.hierarchy(AUG25, reference_price=29225.0)
        blob = json.dumps(h).lower()
        for banned in ("primary", "target", "entitle", "preferred", "rank",
                       "recommended"):
            assert banned not in blob


# ══ ARCHIVE SPECIMENS ═══════════════════════════════════════════════════════
class TestAgainstRealArchive:

    def load(self, name):
        f = os.path.join(ARCHIVE, name)
        if not os.path.exists(f):
            pytest.skip(f"archived specimen absent: {name}")
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        return d["raw_snapshot"], d.get("input_payload") or {}

    def test_the_aug25_specimen_reproduces_from_the_archive(self):
        snap, ip = self.load("20260825_104919_MNQ.json")
        ref = (ip.get("market") or {}).get("current_price")
        h = LS.hierarchy(snap["liquidity"], reference_price=ref, tick_size=0.25)
        assert [r["price"] for r in h[BUY]] == [29249.25, 29345.0, 29409.25]
        assert [r["supporting_timeframes"] for r in h[BUY]] == \
            [["1m"], ["3m", "5m"], ["15m"]]

    def test_the_legacy_value_still_matches_what_luna_actually_received(self):
        snap, ip = self.load("20260825_104919_MNQ.json")
        published = (ip.get("liquidity") or {}).get("nearest_buy_side")
        assert LS.legacy_flattened(snap["liquidity"], BUY) == published

    def test_an_independent_session_also_yields_a_hierarchy(self):
        files = sorted(glob.glob(os.path.join(ARCHIVE, "20260824_*_MNQ.json")))
        if not files:
            pytest.skip("archive absent")
        seen = 0
        for f in files[:60]:
            try:
                with open(f, encoding="utf-8") as fh:
                    snap = json.load(fh)["raw_snapshot"]
            except Exception:  # noqa: BLE001
                continue
            h = LS.hierarchy(snap.get("liquidity") or {}, tick_size=0.25)
            if h[BUY] or h[SELL]:
                seen += 1
        assert seen > 0, "no hierarchy derivable on an independent session"

    def test_every_archived_scan_derives_without_raising(self):
        files = sorted(glob.glob(os.path.join(ARCHIVE, "20260825_*_MNQ.json")))
        if not files:
            pytest.skip("archive absent")
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    snap = json.load(fh)["raw_snapshot"]
            except Exception:  # noqa: BLE001
                continue
            h = LS.hierarchy(snap.get("liquidity") or {}, tick_size=0.25)
            assert h["schema"] == LS.SCHEMA
