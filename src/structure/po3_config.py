"""
VECTOR-3 — Absolute Magnitude Gate + PO3 Stability configuration.

Single source of truth for the scale-invariance fix. All physical floors are in
INSTRUMENT POINTS and baselined for QQQ / index-style instruments (price ~700).

Root problem these values solve: every conviction metric in the expansion /
PO3 path is a ratio or an ATR-relative comparison. On flat tape ATR collapses,
ratios saturate to 1.0, and a 0.03-0.25pt candle reads as institutional
displacement -> PO3 phase flips -> global alignment flickers on noise.

The fix injects ABSOLUTE point magnitude as a first-class gate:
  * displacement threshold has an absolute floor under the ATR term, and
  * a window-significance scalar (kappa) attenuates saturated ratios toward
    neutral when price simply did not physically move.

Kill switch: set env VECTOR3_MAGNITUDE_GATE=off to fall back to legacy
(bit-for-bit) behaviour. Default on.
"""
import os

# ── Master switch ─────────────────────────────────────────────────────────────

def gate_enabled() -> bool:
    """Magnitude gate active unless explicitly disabled. Default ON (welded)."""
    return os.getenv("VECTOR3_MAGNITUDE_GATE", "on").strip().lower() != "off"


# ── LEG-SCOPE — contextual conviction metrics ─────────────────────────────────
# Root problem these values solve: directional_efficiency, body_dominance and
# range_acceleration were computed over the ENTIRE normalized history handed to
# detect_expansion (~2000+ candles in the live lane). directional_efficiency is
# net travel / sum of all candle ranges, so its denominator grows without bound
# while the numerator cannot — it decays toward 0 regardless of price action.
# Measured live on MNQ 2026-07-24: 0.015 over 2000 1m candles vs 0.104 over 100.
#
# Downstream that pinned _compression_score high and dir_eff low on every scan,
# so PO3 scored accumulation +40 for free, denied distribution the +20 dir_eff
# bonus, and made `clean_disp` (dir_eff >= 0.30) unreachable — distribution could
# never clear PHASE_THRESHOLD. PO3 read "accumulation" on every timeframe of
# every scan. The metrics must answer "is THIS move repricing efficiently?", not
# "has the entire dataset been directional?".
#
# Fix: scope them to the current auction leg — the candles since the most recent
# structural pivot — with a floor (a 2-candle "leg" is noise) and a ceiling
# (beyond this it is no longer the CURRENT leg).
#
# Kill switch: PO3_LEG_SCOPED_METRICS=off restores the unbounded legacy window.

def leg_scope_enabled() -> bool:
    """Leg-scoped conviction metrics active unless disabled. Default ON."""
    return os.getenv("PO3_LEG_SCOPED_METRICS", "on").strip().lower() != "off"


LEG_MIN_CANDLES      = 8    # below this a "leg" is noise, not an auction leg
LEG_MAX_CANDLES      = 60   # beyond this it stops being the CURRENT leg
LEG_FALLBACK_CANDLES = 20   # when structure offers no usable pivot — never unbounded


# ── MANIPULATION — confluence lookback ────────────────────────────────────────
# analyze_liquidity inspects only candles[-1], so it answers "is a sweep
# completing on this bar". Manipulation is a PHASE and persists after the bar
# that created it; a raid three candles back still shaped the current auction.
# The confluence detectors scan this window instead of the closing bar.

MANIP_LOOKBACK = 10

# Swing context for the manipulation detectors. find_swings() over the full
# history returns pivots from days ago, which is the same unbounded-window defect
# LEG-SCOPE fixed in expansion: at the 2026-07-24 13:35 entry it compared a swing
# low of 28427 against 28254.25 from an unrelated leg and reported the wrong
# direction. Swings must be drawn from recent structure, not all of it.
MANIP_CONTEXT = 40


# ── ATR dead-band ─────────────────────────────────────────────────────────────
# displacement_threshold = max(atr * K_ATR, F_DISP[tf])
K_ATR = 0.50   # unchanged from legacy _displacement_detected

# ── Absolute point floors (QQQ baseline) ──────────────────────────────────────
# F_DISP — per-candle displacement floor. A single candle's body must clear this
#          (in points) before it can be called displacement, regardless of ATR.
# F_WIN  — window-significance floor. Recent physical travel (max of net
#          displacement and rolling range over SIG_WINDOW candles) must clear
#          this before saturated ratio metrics are trusted at full weight.
#
# Justification against the real June-15 17:30-17:41 flat window
# (12x 1m candles, span 0.615pt, max body 0.19pt):
#   F_DISP["1m"]=0.50 > 0.19  -> no flat candle can be displacement.
#   F_WIN["1m"] =1.10 > 0.615 -> kappa=0 across the whole window.
# A genuine 1m opening drive (body >=0.5pt, window span >2pt) clears both.
F_DISP = {
    "1m": 0.50,
    "3m": 0.90,
    "5m": 1.30,
    "15m": 2.50,
}

F_WIN = {
    "1m": 1.10,
    "3m": 1.70,
    "5m": 2.30,
    "15m": 4.00,
}

# Fallback floors when timeframe is unknown / not in the tables. Conservative
# (never blocks): zero floors == pure legacy ATR behaviour for that tf.
_F_DISP_DEFAULT = 0.0
_F_WIN_DEFAULT = 0.0

# Number of trailing candles over which window significance is measured. Sized to
# cover the documented ~11-12 minute flat window on 1m; scales naturally on HTFs.
SIG_WINDOW = 12

# Kappa band: significance ramps kappa 0->1 linearly across [F_WIN, 2*F_WIN].
# Width = F_WIN[tf] (one floor-width). Keeps the gate continuous (no cliff that
# would itself create flicker) while reaching full pass-through quickly.
KAPPA_BAND_MULT = 1.0


def f_disp(tf: str) -> float:
    return F_DISP.get(tf, _F_DISP_DEFAULT)


def f_win(tf: str) -> float:
    return F_WIN.get(tf, _F_WIN_DEFAULT)


# ── Phase dead-band ───────────────────────────────────────────────────────────
# A new winning phase replaces the held phase only if it clears threshold AND
# beats the runner-up by a margin; otherwise it must persist N scans (unless a
# material event grants immediate replacement).
PHASE_MARGIN_ABS = 12      # absolute score gap winner - runner_up
PHASE_MARGIN_REL = 0.15    # OR relative gap >= 0.15 * winner_score (whichever larger)
PHASE_PERSIST_N = 2        # consecutive scans a decisive-but-unconfirmed phase must hold

# ── Alignment hysteresis ──────────────────────────────────────────────────────
# Global alignment change requires N consecutive scans of the new candidate
# unless a material structural trigger is present on an HTF.
ALIGN_PERSIST_N = 2

# Higher timeframes whose phase change / material event can move global alignment
# immediately. A 1m/3m-only flip can never trigger an immediate alignment change.
HTF_TRIGGER_TFS = ("15m", "5m")
