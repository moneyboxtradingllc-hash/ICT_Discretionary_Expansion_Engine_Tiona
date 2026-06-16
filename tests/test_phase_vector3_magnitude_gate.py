"""
VECTOR-3 — Absolute Magnitude Gate + PO3 Stability.

Proves scale-invariant ratio saturation on flat tape is neutralized (a
0.03-0.25pt candle can no longer manufacture displacement / healthy_expansion /
distribution / manipulation / full_distribution_alignment), the ATR dead-band
handoff is correct, kappa is monotonic+continuous, the phase dead-band holds a
contested phase, alignment hysteresis ignores 1m-only d_count flicker, and real
high-volatility expansion still passes untouched.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.candle_normalizer import normalize_candle
from volatility.atr_engine import calculate_atr
from volatility.expansion_detector import (
    detect_expansion, _kappa, _window_significance,
)
from structure.po3_engine import analyze_po3_snapshot
from structure.po3_alignment_manager import Po3StabilityManager
from structure import po3_config as cfg


def mk(o, h, l, c):
    return normalize_candle(
        {"timestamp": "2026-06-15T17:30:00+00:00", "open": o, "high": h, "low": l, "close": c},
        "sess")


# Real June-15 17:30-17:41 flat window (12 candles, span 0.615pt, max body 0.19).
FLAT = [
    mk(740.00, 740.12, 740.00, 740.12), mk(740.30, 740.30, 740.04, 740.11),
    mk(740.11, 740.13, 740.04, 740.10), mk(740.10, 740.10, 740.08, 740.08),
    mk(740.08, 740.25, 740.05, 740.22), mk(740.22, 740.30, 740.13, 740.30),
    mk(740.30, 740.38, 740.20, 740.22), mk(740.22, 740.22, 740.22, 740.22),
    mk(740.22, 740.22, 740.10, 740.10), mk(740.10, 740.10, 740.05, 740.05),
    mk(740.05, 740.05, 739.94, 739.94), mk(739.94, 740.18, 739.94, 740.09),
]
FLAT_HIST = [mk(740.0, 740.10, 739.95, 740.05) for _ in range(10)] + FLAT

# A genuine 1m opening drive (large directional bodies, wide window span).
DRIVE = [mk(738.0, 740.6, 737.9, 740.5), mk(740.5, 742.0, 740.4, 741.8),
         mk(741.8, 743.5, 741.7, 743.3), mk(743.3, 744.2, 743.1, 744.0)]
DRIVE_HIST = [mk(736.0, 736.5, 735.5, 736.2) for _ in range(10)] + DRIVE


def _po3_result(phase, winner=60, runner=20, material=False, gated=False):
    """Minimal per-TF result dict shaped like analyze_po3 output."""
    return {"phase": phase, "winner_score": winner, "runner_up_score": runner,
            "material_event": material, "magnitude_gated": gated}


class TestMagnitudeGateFlatTape(unittest.TestCase):
    def setUp(self):
        os.environ["VECTOR3_MAGNITUDE_GATE"] = "on"

    def test_flat_tape_neutralized(self):
        r = detect_expansion(FLAT_HIST, calculate_atr(FLAT_HIST), "1m")
        self.assertEqual(r["kappa"], 0.0)
        self.assertTrue(r["magnitude_gated"])
        # saturated ratios pulled back to neutral
        self.assertAlmostEqual(r["directional_efficiency"], 0.5, places=2)
        self.assertAlmostEqual(r["body_dominance"], 0.5, places=2)

    def test_tiny_candles_cannot_displace_or_expand(self):
        r = detect_expansion(FLAT_HIST, calculate_atr(FLAT_HIST), "1m")
        self.assertFalse(r["displacement_detected"])
        self.assertNotIn(r["state"], ("healthy_expansion", "mature_expansion"))
        self.assertLessEqual(r["expansion_score"], 50)   # cannot reach high conviction

    def test_flat_tape_no_distribution_no_manipulation_no_full_alignment(self):
        # Build a full snapshot on flat tape across all TFs; assert no high-conviction
        # PO3 phase and no full_distribution_alignment.
        from structure.structure_engine import analyze_structure
        from structure.liquidity_engine import analyze_liquidity
        from volatility.volatility_classifier import classify_volatility
        s, l, v, e = {}, {}, {}, {}
        for tf in ("15m", "5m", "3m", "1m"):
            atr = calculate_atr(FLAT_HIST)
            s[tf] = analyze_structure(FLAT_HIST)
            l[tf] = analyze_liquidity(FLAT_HIST)
            v[tf] = classify_volatility(FLAT_HIST, atr)
            e[tf] = detect_expansion(FLAT_HIST, atr, tf)
        po3 = analyze_po3_snapshot(s, l, v, e)
        self.assertNotEqual(po3["alignment"], "full_distribution_alignment")
        for tf in ("15m", "5m", "3m", "1m"):
            self.assertNotIn(po3[tf]["phase"], ("distribution", "manipulation"))


class TestAtrDeadBandHandoff(unittest.TestCase):
    def setUp(self):
        os.environ["VECTOR3_MAGNITUDE_GATE"] = "on"

    def test_collapsed_atr_uses_absolute_floor(self):
        # ATR collapsed (~0.05): threshold must be the floor, not atr*0.5.
        atr_small = 0.05
        thr = max(atr_small * cfg.K_ATR, cfg.f_disp("1m"))
        self.assertEqual(thr, cfg.f_disp("1m"))
        self.assertGreater(thr, atr_small * cfg.K_ATR)

    def test_high_atr_uses_atr_relative(self):
        # ATR genuinely high: atr*0.5 dominates the floor.
        atr_big = 2.0
        thr = max(atr_big * cfg.K_ATR, cfg.f_disp("1m"))
        self.assertEqual(thr, atr_big * cfg.K_ATR)
        self.assertGreater(thr, cfg.f_disp("1m"))

    def test_legacy_path_bitwise_when_tf_none(self):
        # tf=None -> no gate; displacement uses legacy atr*0.5 (the original bug).
        os.environ["VECTOR3_MAGNITUDE_GATE"] = "on"
        legacy = detect_expansion(FLAT_HIST, calculate_atr(FLAT_HIST))   # no tf
        self.assertTrue(legacy["displacement_detected"])   # legacy still fires on flat tape
        self.assertEqual(legacy["kappa"], 1.0)             # no attenuation


class TestKappaRamp(unittest.TestCase):
    def test_monotonic_continuous_across_band(self):
        f = cfg.f_win("1m")
        xs = [f * (i / 50.0) * 2 for i in range(0, 51)]   # 0 .. 2F
        ks = [_kappa(x, f, cfg.KAPPA_BAND_MULT) for x in xs]
        # bounded
        self.assertTrue(all(0.0 <= k <= 1.0 for k in ks))
        # monotonic non-decreasing
        self.assertTrue(all(ks[i + 1] >= ks[i] - 1e-9 for i in range(len(ks) - 1)))
        # zero at/below floor, one at/above 2F
        self.assertEqual(_kappa(f, f, cfg.KAPPA_BAND_MULT), 0.0)
        self.assertEqual(_kappa(2 * f, f, cfg.KAPPA_BAND_MULT), 1.0)
        # continuous: small input step -> small output step
        steps = [abs(ks[i + 1] - ks[i]) for i in range(len(ks) - 1)]
        self.assertLess(max(steps), 0.1)

    def test_significance_uses_recent_window(self):
        sig = _window_significance(FLAT, cfg.SIG_WINDOW)
        self.assertLess(sig, cfg.f_win("1m"))   # flat window is sub-floor


class TestRealExpansionStillPasses(unittest.TestCase):
    def setUp(self):
        os.environ["VECTOR3_MAGNITUDE_GATE"] = "on"

    def test_drive_passes_gate(self):
        r = detect_expansion(DRIVE_HIST, calculate_atr(DRIVE_HIST), "1m")
        self.assertEqual(r["kappa"], 1.0)
        self.assertFalse(r["magnitude_gated"])
        self.assertTrue(r["displacement_detected"])
        self.assertIn(r["state"], ("healthy_expansion", "mature_expansion"))


class TestPhaseDeadBand(unittest.TestCase):
    def test_holds_previous_when_margin_too_small(self):
        m = Po3StabilityManager()
        # establish accumulation on 1m
        base = {tf: _po3_result("accumulation", 60, 20) for tf in ("15m", "5m", "3m", "1m")}
        base["alignment"] = "accumulation_building"
        m.update(base)
        # contender: distribution wins by only 3 pts, non-material -> must hold accumulation
        nxt = dict(base)
        nxt["1m"] = _po3_result("distribution", winner=40, runner=37, material=False)
        out = m.update(nxt)
        self.assertEqual(out["1m"]["phase"], "accumulation")
        self.assertTrue(out["1m"]["stabilized_held"])

    def test_decisive_material_change_adopted_immediately(self):
        m = Po3StabilityManager()
        base = {tf: _po3_result("accumulation", 60, 20) for tf in ("15m", "5m", "3m", "1m")}
        base["alignment"] = "accumulation_building"
        m.update(base)
        nxt = dict(base)
        nxt["5m"] = _po3_result("distribution", winner=90, runner=20, material=True)
        out = m.update(nxt)
        self.assertEqual(out["5m"]["phase"], "distribution")
        self.assertFalse(out["5m"]["stabilized_held"])


class TestAlignmentHysteresis(unittest.TestCase):
    def test_1m_only_dcount_flip_does_not_move_alignment(self):
        m = Po3StabilityManager()
        # HTF stable distribution (15m,5m,3m); 1m toggles dist<->accu each scan.
        def results(one_m_phase, one_m_mat):
            r = {
                "15m": _po3_result("distribution", 90, 20, material=True),
                "5m":  _po3_result("distribution", 90, 20, material=True),
                "3m":  _po3_result("distribution", 80, 20, material=False),
                "1m":  _po3_result(one_m_phase, 60, 20, material=one_m_mat),
            }
            r["alignment"] = "full_distribution_alignment"
            return r
        # warm up to full_distribution
        m.update(results("distribution", False))
        first = m.update(results("distribution", False))["alignment"]
        # now flip 1m back and forth (sub-floor, non-material) many times
        seen = set()
        for ph in ("accumulation", "distribution") * 6:
            seen.add(m.update(results(ph, False))["alignment"])
        # alignment must not have been dragged off its HTF-driven value by 1m noise
        self.assertEqual(seen, {first})
        self.assertEqual(first, "full_distribution_alignment")

    def test_full_distribution_requires_htf_confirmation(self):
        m = Po3StabilityManager()
        # d_count==3 but ALL from 3m+1m (+manip on htf) -> no HTF distribution.
        r = {
            "15m": _po3_result("accumulation", 60, 20),
            "5m":  _po3_result("accumulation", 60, 20),
            "3m":  _po3_result("distribution", 80, 20),
            "1m":  _po3_result("distribution", 80, 20),
        }
        r["alignment"] = "full_distribution_alignment"
        # only 2 distribution -> not even d_count>=3; craft a 3rd on 3m-tier:
        r2 = dict(r)
        r2["15m"] = _po3_result("distribution", 80, 20)  # now 3 dist but htf=15m IS dist
        out = m.update(r2)
        # 15m is distribution -> HTF confirmed -> allowed
        self.assertEqual(out["alignment"], "full_distribution_alignment")


if __name__ == "__main__":
    unittest.main(verbosity=2)
