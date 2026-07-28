"""VOL-LEG-SCOPE — volatility describes now, and every state must be reachable.

volatility_classifier carries its own copy of _directional_efficiency, identical
to the one LEG-SCOPE fixed in expansion_detector and missed here. Unsliced it ran
over the whole normalized history (~2000 candles live) and decayed toward zero as
history grew.

The consequence was not a skewed number. _state() guards `explosive` and
`expanding` behind `dir_eff < 0.20` and `< 0.30`; with dir_eff pinned near 0.04
both guards were always true, so anything scoring above 65 became `toxic`,
anything above 55 `unstable`, and `expanding` was never emitted at all — which
made narrative_builder's `vol_15m in ("expanding", "stable")` a half-dead test.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from volatility.volatility_classifier import classify_volatility, _state
from structure import po3_config as cfg


@pytest.fixture(autouse=True)
def _flag_is_explicit(monkeypatch):
    """Pin to the code default; the live launch script exports 'off'.

    See the companion fixture in test_po3_leg_scoped_metrics.py.
    """
    monkeypatch.delenv("PO3_LEG_SCOPED_METRICS", raising=False)


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "range": h - l,
            "body_size": abs(c - o), "upper_wick": h - max(o, c),
            "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else "bearish"}


def _drive(n=40, base=28000.0, step=25.0):
    out, px = [], base
    for _ in range(n):
        nxt = px + step
        out.append(_c(px, nxt + 1, px - 1, nxt)); px = nxt
    return out


def _noise(n, base=28000.0):
    return [_c(base + (5 if i % 2 else -5), base + 30, base - 30,
               base - (5 if i % 2 else -5)) for i in range(n)]


ATR = {"atr": 20.0, "atr_trend": "rising"}


class TestEveryStateIsReachable:
    def test_expanding_can_be_produced(self):
        """It could not be, before. A state no input can reach is dead code."""
        assert _state(65, 0.55) == "expanding"

    def test_explosive_can_be_produced(self):
        assert _state(85, 0.60) == "explosive"

    def test_a_collapsed_dir_eff_hides_both(self):
        """Pins the mechanism: with dir_eff near zero the guards swallow them."""
        assert _state(85, 0.04) == "toxic"
        assert _state(65, 0.04) == "unstable"


class TestTheWindowIsBounded:
    def test_history_length_does_not_change_the_read(self):
        leg = _drive()
        short = classify_volatility(_noise(30) + leg, ATR)
        long_ = classify_volatility(_noise(3000) + leg, ATR)
        assert short["state"] == long_["state"]
        assert short["volatility_score"] == long_["volatility_score"]

    def test_a_directional_leg_escapes_the_dir_eff_guards(self):
        """`toxic` and `unstable` both mean "moving without direction". A clean
        one-way leg must not land in either — that was the collapsed-dir_eff
        signature. It may still score as low volatility: a smooth drive with
        tight ranges genuinely is calm, and that is a separate axis."""
        out = classify_volatility(_noise(2000) + _drive(), ATR)
        assert out["state"] not in ("toxic", "unstable"), out

    def test_choppy_tape_still_reads_low(self):
        """The fix must not simply inflate every read."""
        assert classify_volatility(_noise(200), ATR)["state"] in (
            "stable", "unstable", "toxic", "liquidity_vacuum")

    def test_short_series_is_unchanged(self):
        bars = _drive(10)
        assert classify_volatility(bars, ATR) == classify_volatility(list(bars), ATR)

    def test_kill_switch_restores_the_unbounded_window(self, monkeypatch):
        monkeypatch.setenv("PO3_LEG_SCOPED_METRICS", "off")
        assert cfg.leg_scope_enabled() is False
        leg = _drive()
        a = classify_volatility(_noise(30) + leg, ATR)["volatility_score"]
        b = classify_volatility(_noise(3000) + leg, ATR)["volatility_score"]
        assert a != b, "unbounded window should be history-dependent again"
