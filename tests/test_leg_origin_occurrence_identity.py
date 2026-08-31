"""STEP 4B.12 §4 UNIT 4 — THE LEG BEGINS AT AN OCCURRENCE, NOT AT A PRICE.

`_leg_start_index` took the swing PRICE and scanned backwards for a candle whose
extreme equalled it. That matches EVERY candle that ever touched the level, and
the reversed scan took the most recent -- so a revisit could steal the leg origin
from the swing that made it.

Measured over 1000 lookups on the 2026-08-12 tape:

    exact identity                                     952
    wrong occurrence                                     48
      cause "a later candle revisited a level"       48/48
      changed a leg metric                              30
      numerically hidden by the [8,60] clamp            18

Measured decoy side across all 48: HIGH 36, LOW 12.
Measured form across all 48:
    a revisit outranking its OWN pivot                   40
    a revisit outranking the OTHER side's NEWER pivot      8

The second form is why price could never have been a safe identity mechanism:
the old search compared the two sides' most recent TOUCHES, not their two
authoritative OCCURRENCES, so a stale high revisit could outrank a genuinely
newer low pivot.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from structure import po3_config as cfg                      # noqa: E402
from structure.structure_engine import analyze_structure     # noqa: E402
from volatility import expansion_detector as EXP             # noqa: E402


def candle(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
            "volume": 10, "range": round(h - l, 2),
            "body_size": round(abs(c - o), 2),
            "direction": "bullish" if c > o else "bearish" if c < o else "neutral"}


def series(n, *, base=100.0):
    return [candle(f"2026-08-12T15:{i:02d}:00+00:00", base, base + 1,
                   base - 1, base + 0.5) for i in range(n)]


def old_price_search(candles, struct):
    """The REPLACED algorithm, kept here so every regression below can be shown
    to fail against it. A test that cannot fail against the defect proves
    nothing about the repair."""
    if not isinstance(struct, dict) or not candles:
        return None
    found = []
    for key, extreme in (("last_swing_high", "high"), ("last_swing_low", "low")):
        lvl = struct.get(key)
        if not isinstance(lvl, (int, float)):
            continue
        for i in range(len(candles) - 1, -1, -1):
            if abs(float(candles[i][extreme]) - float(lvl)) <= 1e-6:
                found.append(i)
                break
    return max(found) if found else None


# ── the two measured real collisions ─────────────────────────────────────────
class TestRealMeasuredCollisions:
    """Frozen from the production ledger, 2026-08-12."""

    def test_low_side_a_revisit_cannot_steal_the_origin(self):
        """The low-side class: 12 of the 48 measured collisions.

        Geometry constructed rather than lifted, because the two collisions I
        traced end to end (1m 15:53 and 3m 17:48) both turned out to be
        HIGH-side. Citing either of them here would have described this test
        with a tape that does not match it -- which is exactly the error the
        measured 36-high / 12-low split exists to prevent.
        """
        candles = series(12, base=29830.0)
        candles[4] = candle("2026-08-12T15:45:00+00:00",
                            29825.0, 29826.0, 29819.0, 29824.0)   # the pivot
        candles[10] = candle("2026-08-12T15:51:00+00:00",
                             29824.0, 29827.0, 29819.0, 29826.0)  # the revisit
        struct = {"last_swing_high": None, "last_swing_low": 29819.0,
                  "last_swing_high_pivot_index": None,
                  "last_swing_low_pivot_index": 4}

        assert EXP._leg_start_index(candles, struct) == 4
        # and the defect is real: the old algorithm chose the revisit
        assert old_price_search(candles, struct) == 10

    def test_high_side_is_symmetric(self):
        """3m 17:48, verified against the production pipeline.

        High 29920.00 was made at idx 523 (17:24) and touched again at idx 528
        (17:39); the touch outranked the pivot that made it. This is the
        DOMINANT form -- 40 of 48 collisions are a level losing to its own
        revisit, and 36 of 48 are high-side.
        """
        candles = series(12, base=29900.0)
        candles[3] = candle("2026-08-12T17:24:00+00:00",
                            29915.0, 29920.0, 29914.0, 29918.0)   # the pivot
        candles[8] = candle("2026-08-12T17:39:00+00:00",
                            29916.0, 29920.0, 29915.0, 29917.0)   # the revisit
        struct = {"last_swing_high": 29920.0, "last_swing_low": None,
                  "last_swing_high_pivot_index": 3,
                  "last_swing_low_pivot_index": None}

        assert EXP._leg_start_index(candles, struct) == 3
        assert old_price_search(candles, struct) == 8

    def test_the_origin_moves_the_leg_metrics(self):
        """A wrong origin resizes the leg, so the conviction ratios move with it.

        No real-tape figures are quoted here: the numbers this once cited came
        from a harness run that had not yet been bound to the production object
        graph, and the real measured deltas are frozen in the 15:55 regression
        below instead.
        """
        candles = series(20, base=29830.0)
        candles[8] = candle("2026-08-12T15:45:00+00:00",
                            29825.0, 29826.0, 29819.0, 29824.0)
        candles[14] = candle("2026-08-12T15:51:00+00:00",
                             29824.0, 29827.0, 29819.0, 29826.0)
        struct = {"last_swing_low": 29819.0, "last_swing_low_pivot_index": 8,
                  "last_swing_high": None, "last_swing_high_pivot_index": None}
        assert EXP._leg_start_index(candles, struct) == 8
        assert len(EXP._leg_slice(candles, struct)) != \
            len(candles[-(len(candles) - old_price_search(candles, struct)):])


# ── identity is correct even when the number does not move ───────────────────
class TestIdentityIsNotJustifiedByItsMetric:
    """18 of the 48 measured errors were absorbed by the [8, 60] clamp.

    Those are still identity errors. A repair certified only by metric equality
    would have declared them fine.
    """

    def test_identity_is_corrected_where_the_clamp_hides_the_delta(self):
        # both origins sit far enough back that LEG_MAX_CANDLES clamps them to
        # the same slice, so every leg metric is numerically identical
        n = cfg.LEG_MAX_CANDLES + 40
        candles = series(n, base=29800.0)
        pivot = 5
        revisit = 20
        candles[pivot] = candle("t-pivot", 29795.0, 29796.0, 29790.0, 29794.0)
        candles[revisit] = candle("t-revisit", 29794.0, 29797.0, 29790.0, 29796.0)
        struct = {"last_swing_low": 29790.0, "last_swing_low_pivot_index": pivot,
                  "last_swing_high": None, "last_swing_high_pivot_index": None}

        assert old_price_search(candles, struct) == revisit      # WRONG identity
        assert EXP._leg_start_index(candles, struct) == pivot     # RIGHT identity

        # ... and the metrics are identical either way, which is exactly why
        # identity needs its own assertion
        old_slice = candles[-(len(candles) - revisit):]
        old_slice = old_slice[-cfg.LEG_MAX_CANDLES:]
        assert len(EXP._leg_slice(candles, struct)) == len(old_slice)


# ── no price fallback, ever ──────────────────────────────────────────────────
class TestNoPriceFallback:

    def test_A_both_indices_valid_takes_the_later(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": 3,
            "last_swing_low_pivot_index": 7}) == 7

    def test_B_only_high_valid(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": 3,
            "last_swing_low_pivot_index": None}) == 3

    def test_C_only_low_valid(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": None,
            "last_swing_low_pivot_index": 6}) == 6

    def test_D_both_none_is_none(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": None,
            "last_swing_low_pivot_index": None}) is None

    def test_E_negative_index_is_invalid(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": -3,
            "last_swing_low_pivot_index": None}) is None

    def test_F_index_beyond_the_series_is_invalid(self):
        candles = series(10)
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": 10,
            "last_swing_low_pivot_index": None}) is None
        assert EXP._leg_start_index(candles, {
            "last_swing_high_pivot_index": 999,
            "last_swing_low_pivot_index": None}) is None

    def test_G_malformed_index_is_invalid(self):
        candles = series(10)
        for junk in ("4", 4.5, [4], {"i": 4}, True, False):
            assert EXP._leg_start_index(candles, {
                "last_swing_high_pivot_index": junk,
                "last_swing_low_pivot_index": None}) is None

    def test_H_a_same_price_candle_may_not_rescue_a_missing_index(self):
        """MANDATORY. Absent identity stays unknown; it is never guessed back."""
        candles = series(10, base=29800.0)
        candles[7] = candle("t", 29799.0, 29805.0, 29795.0, 29804.0)
        struct = {"last_swing_high": 29805.0, "last_swing_low": 29795.0,
                  "last_swing_high_pivot_index": None,
                  "last_swing_low_pivot_index": None}
        # the price is right there in the series...
        assert old_price_search(candles, struct) == 7
        # ...and the repaired resolver still refuses to use it
        assert EXP._leg_start_index(candles, struct) is None

    def test_the_bounded_fallback_window_still_owns_the_unknown_case(self):
        candles = series(80)
        struct = {"last_swing_high_pivot_index": None,
                  "last_swing_low_pivot_index": None}
        assert len(EXP._leg_slice(candles, struct)) == cfg.LEG_FALLBACK_CANDLES


# ── the producer contract ────────────────────────────────────────────────────
class TestProducerPublishesCoherentIdentity:

    def _tape(self):
        """A series with two clean pivots and a later revisit of each."""
        out = []
        pattern = [0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3]
        for i, step in enumerate(pattern):
            base = 100.0 + step
            out.append(candle(f"2026-08-12T15:{i:02d}:00+00:00",
                              base, base + 0.5, base - 0.5, base + 0.25))
        return out

    def test_price_and_index_come_from_the_same_occurrence(self):
        st = analyze_structure(self._tape(), allow_uncadenced=True)
        tape = self._tape()
        for level_key, index_key, extreme in (
                ("last_swing_high", "last_swing_high_pivot_index", "high"),
                ("last_swing_low", "last_swing_low_pivot_index", "low")):
            lvl, idx = st.get(level_key), st.get(index_key)
            if lvl is None:
                assert idx is None, f"{index_key} without {level_key}"
                continue
            assert isinstance(idx, int) and 0 <= idx < len(tape)
            # the published price must be THAT candle's extreme, not merely
            # some candle's extreme
            assert round(float(tape[idx][extreme]), 2) == lvl

    def test_every_return_branch_states_the_schema(self):
        for block in (analyze_structure([]),
                      analyze_structure(self._tape(), allow_uncadenced=True)):
            assert "last_swing_high_pivot_index" in block
            assert "last_swing_low_pivot_index" in block

    def test_the_insufficient_data_branch_states_none_not_absence(self):
        block = analyze_structure([])
        assert block["last_swing_high_pivot_index"] is None
        assert block["last_swing_low_pivot_index"] is None

    def test_an_absent_swing_carries_an_absent_index(self):
        block = analyze_structure(self._tape(), allow_uncadenced=True)
        if block["last_swing_high"] is None:
            assert block["last_swing_high_pivot_index"] is None
        if block["last_swing_low"] is None:
            assert block["last_swing_low_pivot_index"] is None


# ── real-tape certification ──────────────────────────────────────────────────
#: The last 80 settled 1m candles as of the 2026-08-12T15:55:00 scan, lifted
#: verbatim from the production store. This is one of the NINE measured
#: opportunities where the corrected leg origin changes the deterministic 1m
#: expansion state, and it reproduces on this tail exactly as it does on the
#: full 1453-candle series: 56 -> 46, mature_expansion -> early_expansion.
REAL_1M_TAIL = [
    ("14:36", 29883.0, 29906.25, 29878.5, 29898.75),
    ("14:37", 29898.5, 29918.5, 29898.25, 29912.75),
    ("14:38", 29913.25, 29928.75, 29908.75, 29912.5),
    ("14:39", 29913.0, 29923.0, 29906.75, 29921.0),
    ("14:40", 29921.0, 29924.75, 29911.25, 29921.75),
    ("14:41", 29921.5, 29928.0, 29916.75, 29920.5),
    ("14:42", 29920.25, 29923.0, 29894.5, 29905.75),
    ("14:43", 29906.0, 29918.25, 29898.75, 29916.5),
    ("14:44", 29916.25, 29925.0, 29911.0, 29924.75),
    ("14:45", 29924.5, 29930.25, 29915.5, 29925.5),
    ("14:46", 29924.5, 29931.75, 29917.25, 29919.0),
    ("14:47", 29919.25, 29924.0, 29890.25, 29897.75),
    ("14:48", 29898.0, 29905.75, 29890.25, 29900.25),
    ("14:49", 29900.25, 29905.25, 29895.25, 29904.0),
    ("14:50", 29904.0, 29904.75, 29870.75, 29876.0),
    ("14:51", 29876.0, 29878.0, 29863.0, 29874.5),
    ("14:52", 29874.25, 29887.75, 29865.0, 29886.75),
    ("14:53", 29886.75, 29892.75, 29869.0, 29889.5),
    ("14:54", 29889.5, 29896.0, 29855.75, 29861.5),
    ("14:55", 29862.0, 29866.25, 29848.5, 29854.25),
    ("14:56", 29854.25, 29876.25, 29853.5, 29862.5),
    ("14:57", 29862.5, 29879.25, 29861.5, 29871.75),
    ("14:58", 29871.5, 29878.75, 29866.0, 29867.5),
    ("14:59", 29867.5, 29876.5, 29861.5, 29867.25),
    ("15:00", 29867.5, 29874.75, 29853.25, 29870.75),
    ("15:01", 29870.75, 29878.75, 29864.0, 29878.0),
    ("15:02", 29878.0, 29878.75, 29855.75, 29866.75),
    ("15:03", 29867.25, 29869.25, 29841.25, 29843.5),
    ("15:04", 29843.25, 29852.25, 29838.75, 29851.25),
    ("15:05", 29851.5, 29856.0, 29841.25, 29854.0),
    ("15:06", 29853.5, 29879.25, 29845.75, 29876.5),
    ("15:07", 29876.25, 29877.75, 29864.75, 29875.25),
    ("15:08", 29875.25, 29876.5, 29861.75, 29869.25),
    ("15:09", 29869.0, 29877.25, 29866.0, 29870.5),
    ("15:10", 29871.5, 29873.25, 29848.5, 29851.25),
    ("15:11", 29851.25, 29863.75, 29849.0, 29863.75),
    ("15:12", 29863.75, 29886.5, 29859.25, 29886.5),
    ("15:13", 29886.5, 29890.5, 29878.25, 29884.75),
    ("15:14", 29884.75, 29891.25, 29877.0, 29879.5),
    ("15:15", 29880.25, 29887.5, 29872.75, 29874.5),
    ("15:16", 29875.5, 29885.25, 29872.0, 29874.0),
    ("15:17", 29874.25, 29883.25, 29866.25, 29882.5),
    ("15:18", 29882.0, 29882.75, 29868.75, 29869.0),
    ("15:19", 29869.5, 29874.25, 29862.25, 29870.75),
    ("15:20", 29871.25, 29878.0, 29863.75, 29865.75),
    ("15:21", 29866.25, 29875.25, 29861.25, 29874.25),
    ("15:22", 29874.0, 29874.75, 29848.75, 29852.75),
    ("15:23", 29852.75, 29856.75, 29845.0, 29856.25),
    ("15:24", 29856.25, 29858.25, 29847.75, 29849.25),
    ("15:25", 29849.5, 29854.75, 29843.5, 29848.5),
    ("15:26", 29848.5, 29857.5, 29845.5, 29854.25),
    ("15:27", 29854.5, 29858.5, 29846.25, 29853.0),
    ("15:28", 29853.0, 29861.5, 29845.5, 29858.75),
    ("15:29", 29858.5, 29874.5, 29852.75, 29874.5),
    ("15:30", 29866.5, 29868.0, 29864.75, 29865.5),
    ("15:31", 29864.75, 29868.0, 29849.5, 29851.75),
    ("15:32", 29852.0, 29857.5, 29831.75, 29843.5),
    ("15:33", 29843.5, 29846.5, 29822.75, 29825.5),
    ("15:34", 29825.5, 29837.0, 29818.75, 29833.0),
    ("15:35", 29832.0, 29845.75, 29830.75, 29840.5),
    ("15:36", 29840.0, 29858.25, 29833.25, 29853.25),
    ("15:37", 29854.0, 29854.75, 29845.5, 29846.75),
    ("15:38", 29847.5, 29850.75, 29842.75, 29847.0),
    ("15:39", 29847.0, 29850.5, 29830.0, 29833.0),
    ("15:40", 29832.75, 29834.25, 29819.25, 29820.0),
    ("15:41", 29820.0, 29832.25, 29818.75, 29832.0),
    ("15:42", 29832.25, 29842.5, 29831.0, 29837.25),
    ("15:43", 29837.5, 29843.0, 29834.5, 29838.25),
    ("15:44", 29837.25, 29839.75, 29825.5, 29828.5),
    ("15:45", 29828.5, 29832.5, 29819.0, 29826.75),
    ("15:46", 29826.75, 29837.0, 29822.25, 29834.5),
    ("15:47", 29834.25, 29846.75, 29828.25, 29846.5),
    ("15:48", 29845.75, 29847.5, 29832.0, 29836.75),
    ("15:49", 29836.0, 29847.25, 29833.25, 29847.0),
    ("15:50", 29847.5, 29848.5, 29834.25, 29835.0),
    ("15:51", 29835.25, 29843.0, 29834.75, 29840.0),
    ("15:52", 29840.25, 29849.25, 29839.5, 29847.75),
    ("15:53", 29848.0, 29854.0, 29846.75, 29850.25),
    ("15:54", 29850.25, 29851.5, 29837.0, 29837.5),
    ("15:55", 29837.5, 29843.5, 29830.75, 29830.75),
]

#: Measured on the real series, then shifted into this 80-candle window.
REAL_HIGH_PIVOT = 67          # 29843.00 made 15:43 -- the authoritative high
REAL_LOW_PIVOT = 69           # 29819.00 made 15:45 -- the authoritative low
REAL_OLD_ORIGIN = 75          # 15:51 -- merely TOUCHED 29843.00, never a pivot
REAL_HIGH_LEVEL = 29843.0
REAL_LOW_LEVEL = 29819.0


def _real_tail():
    out = []
    for hhmm, o, h, l, c in REAL_1M_TAIL:
        out.append({"timestamp": f"2026-08-12T{hhmm}:00+00:00", "open": o,
                    "high": h, "low": l, "close": c, "volume": 10,
                    "range": round(h - l, 2), "body_size": round(abs(c - o), 2),
                    "upper_wick": round(h - max(o, c), 2),
                    "lower_wick": round(min(o, c) - l, 2),
                    "direction": ("bullish" if c > o else
                                  "bearish" if c < o else "neutral")})
    return out


class TestRealTapeStateChange:
    """The behavioural consequence, on production data.

    Nine `expansion_state` values change across the 1000 measured opportunities,
    ALL on 1m -- eight of them mature_expansion -> early_expansion. The direction
    is the tell: the old code measured the leg from a REVISIT, a later and
    therefore shorter window, which made a young leg look further along than it
    was. This freezes one of those nine end to end.

    NOT "Terra-visible". Terra's `market.expansion_state` is sourced from 15m
    (`regime_features` -> exp_state_15) and the regime expansion flags read 5m
    and 15m; Unit 4 changed neither timeframe. Measured through the real
    serialized Brain payload, Terra's deterministic INPUT differs on 7 of 250
    scans -- via PO3/delivery and toolbox metadata, not via expansion_state --
    and the authorized tool-catalog SET never changes.
    """

    def _atr(self, candles):
        from volatility.atr_engine import calculate_atr
        return calculate_atr(candles)

    def test_the_decoy_is_a_real_touch_not_a_pivot(self):
        """The collision here is on the HIGH side.

        29843.00 was MADE at 15:43 (idx 67) and TOUCHED again at 15:51 (idx 75).
        The low 29819.00 at 15:45 (idx 69) was never revisited. The old search
        took the later of its two per-side matches -- high@75 beat low@69 -- so
        a high revisit stole the origin from a low pivot that came after it.
        """
        tape = _real_tail()
        assert tape[REAL_HIGH_PIVOT]["high"] == REAL_HIGH_LEVEL
        assert tape[REAL_OLD_ORIGIN]["high"] == REAL_HIGH_LEVEL     # the revisit
        assert tape[REAL_LOW_PIVOT]["low"] == REAL_LOW_LEVEL
        assert REAL_OLD_ORIGIN > REAL_LOW_PIVOT > REAL_HIGH_PIVOT
        assert tape[REAL_HIGH_PIVOT]["timestamp"].endswith("15:43:00+00:00")
        assert tape[REAL_LOW_PIVOT]["timestamp"].endswith("15:45:00+00:00")
        assert tape[REAL_OLD_ORIGIN]["timestamp"].endswith("15:51:00+00:00")
        # and 29819.00 occurs exactly once: the low side has no decoy at all
        assert [i for i, c in enumerate(tape)
                if abs(c["low"] - REAL_LOW_LEVEL) <= 1e-6] == [REAL_LOW_PIVOT]

    def test_the_corrected_origin_changes_the_terra_visible_state(self):
        from volatility.expansion_detector import detect_expansion
        tape = _real_tail()
        atr = self._atr(tape)
        # what the price search produced: the high revisit at 75
        wrong = {"last_swing_high": REAL_HIGH_LEVEL, "last_swing_low": REAL_LOW_LEVEL,
                 "last_swing_high_pivot_index": REAL_OLD_ORIGIN,
                 "last_swing_low_pivot_index": None}
        right = {"last_swing_high": REAL_HIGH_LEVEL, "last_swing_low": REAL_LOW_LEVEL,
                 "last_swing_high_pivot_index": REAL_HIGH_PIVOT,
                 "last_swing_low_pivot_index": REAL_LOW_PIVOT}
        a = detect_expansion(tape, atr, "1m", wrong)
        b = detect_expansion(tape, atr, "1m", right)
        assert a["state"] == "mature_expansion"
        assert b["state"] == "early_expansion"
        assert (a["expansion_score"], b["expansion_score"]) == (56, 46)

    def test_the_old_algorithm_would_have_chosen_the_touch(self):
        tape = _real_tail()
        struct = {"last_swing_high": REAL_HIGH_LEVEL, "last_swing_low": REAL_LOW_LEVEL}
        assert old_price_search(tape, struct) == REAL_OLD_ORIGIN

    def test_the_repaired_resolver_chooses_the_later_authoritative_pivot(self):
        tape = _real_tail()
        struct = {"last_swing_high_pivot_index": REAL_HIGH_PIVOT,
                  "last_swing_low_pivot_index": REAL_LOW_PIVOT}
        assert EXP._leg_start_index(tape, struct) == max(REAL_HIGH_PIVOT,
                                                         REAL_LOW_PIVOT)
        assert EXP._leg_start_index(tape, struct) != REAL_OLD_ORIGIN


# ── the producer swap did not move swing geometry ────────────────────────────
class TestPriceProjectionUnchanged:
    """Measured over 1000 production opportunities: the complete swing-price
    lists, `last_swing_high` and `last_swing_low` were IDENTICAL before and
    after the producer swapped `find_swings` for `find_swings_detailed`.

    Unit 4 attaches identity; it must never move geometry. This keeps the two
    APIs from drifting apart silently.
    """

    def _tape(self):
        prices = [50, 44, 38, 32, 26, 20, 26, 32, 38, 44, 50, 44, 38, 32, 26, 20]
        out = []
        for i, p in enumerate(prices):
            b = 28000.0 + p
            out.append(candle(f"2026-08-12T15:{i:02d}:00+00:00", b, b + 1, b - 1,
                              b + 0.5))
        return out

    def test_the_detailed_levels_project_to_the_price_only_lists(self):
        from structure.structure_engine import find_swings, find_swings_detailed
        tape = self._tape()
        h_old, l_old = find_swings(tape, allow_uncadenced=True)
        hd, ld = find_swings_detailed(tape, "1m", allow_uncadenced=True)
        assert [s["level"] for s in hd] == h_old
        assert [s["level"] for s in ld] == l_old

    def test_the_published_levels_come_from_the_projected_lists(self):
        from structure.structure_engine import analyze_structure, find_swings
        tape = self._tape()
        h, l = find_swings(tape, allow_uncadenced=True)
        st = analyze_structure(tape, allow_uncadenced=True)
        assert st["last_swing_high"] == (round(h[-1], 2) if h else None)
        assert st["last_swing_low"] == (round(l[-1], 2) if l else None)
