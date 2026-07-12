"""
VOLUME-WITNESS (2026-07-10) — participation sense organ. WITNESS ONLY.

The mechanical review found volume flows through the whole data plane
(alpaca_provider IEX feed → timeframe_builder sum-aggregation →
candle_normalizer) and is then read by NOTHING. This organ turns the dead
field into deterministic, normalized, provenance-aware participation evidence
for the sovereign Brain.

Constitutional doctrine:
  VOLUME OBSERVES PARTICIPATION. THE AI BRAIN INTERPRETS ITS MEANING.
  - No directional verdict, no "volume agrees/disagrees", no trade opinion.
  - No authority path (qualification/gate/risk/sizing/stops/broker/decision/
    intent_score) may consume it — locked by test.
  - Gated VOLUME_WITNESS (default off): when off nothing is computed or
    attached; pipeline bit-for-bit unchanged.

Determinism: pure over the candles + event blocks it is handed, plus one
optional LOCAL baseline table (replay-built, see
replay_validation/volume_baseline.py). No wall-clock, no LLM, no network.

Venue doctrine: the Alpaca provider uses DataFeed.IEX — venue-limited volume,
NOT the consolidated tape. Relative metrics stay self-consistent (IEX vs its
own IEX baseline); absolute volume is labeled venue_limited_iex and must never
be read as total-market participation.

Bar-completeness doctrine: the provider's REST bars endpoint emits completed
bars only (the forming minute is not returned), so the last bar is treated as
the most recent COMPLETED bar; that basis is stated in data_quality and the
bar's own timestamp is exposed so staleness is always visible.

Event association reuses EXISTING sensors — no second detector:
  - sweep: liquidity_engine flags sweeps on the LAST candle (wick pierce +
    close back inside), so the sweep bar is the current bar by construction.
  - displacement: expansion_detector's convention (any of last 5 bars with
    body >= ATR-gated threshold); the leg is the existing tail
    same-direction-run convention (_follow_through analog).
"""
import json
import os

_TFS = ("15m", "5m", "3m", "1m")

CALCULATION_VERSION = "volume_witness_v1"

_BASELINE_BARS = 20   # trailing completed bars (excluding last) = baseline
_MIN_BASELINE = 10    # fewer usable baseline bars → insufficient_data
_RECENT_BARS = 5      # short window for the participation trend
_MIN_MINUTE_SAMPLE = 10   # same-minute percentile refuses below this n
_LEG_CAP = 10         # displacement leg bars examined (tail run cap)

# relative = last_volume / baseline_avg
_STATES = (            # (upper_bound_exclusive, label)
    (0.5, "dead"),
    (0.8, "quiet"),
    (1.5, "normal"),
    (2.5, "elevated"),
    (float("inf"), "climactic"),
)


def volume_witness_enabled() -> bool:
    return os.getenv("VOLUME_WITNESS", "off").lower().strip() in ("on", "true", "1")


# ── same-minute-of-day baseline table (replay-built, read-only) ───────────────

_baseline_cache: dict = {}


def baseline_table_path(symbol: str) -> str:
    root = os.getenv("PERFORMANCE_TABLES_DIR", os.path.join("data", "performance"))
    return os.path.join(root, symbol or "QQQ", "volume_minute_baseline.json")


def load_minute_baseline(symbol: str) -> "dict | None":
    """Replay-built per-minute-of-day volume distribution (ET HH:MM →
    sorted values). Local file only; cached; absent table → None (the
    percentile then reports unavailable — never fabricated)."""
    key = symbol or "QQQ"
    if key in _baseline_cache:
        return _baseline_cache[key]
    table = None
    try:
        path = baseline_table_path(key)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                table = json.load(fh)
    except Exception:  # noqa: BLE001
        table = None
    _baseline_cache[key] = table
    return table


def _minute_et(ts) -> "str | None":
    """ET HH:MM from a candle timestamp (bar-stamped time, never wall clock)."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return None


def same_minute_percentile(volume: float, ts, table: "dict | None") -> dict:
    """Percentile of `volume` among prior sessions' SAME ET minute (corrects
    the intraday U-shape). Refuses below _MIN_MINUTE_SAMPLE — no fabrication."""
    out = {"same_minute_percentile": None, "same_minute_sample_n": 0}
    if not table:
        return out
    minute = _minute_et(ts)
    values = ((table.get("minutes") or {}).get(minute) or []) if minute else []
    out["same_minute_sample_n"] = len(values)
    if len(values) < _MIN_MINUTE_SAMPLE:
        return out
    below = sum(1 for v in values if v <= volume)
    out["same_minute_percentile"] = round(100.0 * below / len(values))
    return out


# ── core per-TF relative volume ───────────────────────────────────────────────

def _classify(relative: float) -> str:
    for bound, label in _STATES:
        if relative < bound:
            return label
    return "climactic"


def _tf_witness(candles: list) -> dict:
    vols = [float(c.get("volume") or 0) for c in (candles or [])]
    if len(vols) < _MIN_BASELINE + 2:
        return {"state": "insufficient_data", "bars_seen": len(vols)}

    last = vols[-1]
    baseline_window = vols[-(_BASELINE_BARS + 1):-1]
    usable = [v for v in baseline_window if v > 0]
    if len(usable) < _MIN_BASELINE:
        return {"state": "insufficient_data", "bars_seen": len(vols),
                "nonzero_baseline_bars": len(usable)}

    baseline = sum(usable) / len(usable)
    relative = last / baseline
    recent = vols[-_RECENT_BARS:]
    recent_avg = sum(recent) / len(recent)
    trend_ratio = recent_avg / baseline
    if trend_ratio > 1.2:
        trend = "rising"
    elif trend_ratio < 0.8:
        trend = "falling"
    else:
        trend = "flat"

    # rolling z-score over the baseline window (completed bars only);
    # zero variance is reported honestly as unavailable, never as 0
    mean = sum(baseline_window) / len(baseline_window)
    var = sum((v - mean) ** 2 for v in baseline_window) / len(baseline_window)
    zscore = round((last - mean) / var ** 0.5, 2) if var > 0 else None

    return {
        "last_volume": round(last, 1),
        "baseline_avg": round(baseline, 1),
        "baseline_bars": len(usable),
        "relative": round(relative, 2),
        "zscore": zscore,
        "state": _classify(relative),
        "recent_avg": round(recent_avg, 1),
        "trend_ratio": round(trend_ratio, 2),
        "trend": trend,
    }


# ── data quality ──────────────────────────────────────────────────────────────

def _missing_bars(candles: list) -> int:
    """Gaps > 60s between consecutive 1m bar timestamps inside the baseline
    window (IEX prints no bar on zero-trade minutes — absence is data, but it
    must be visible)."""
    try:
        from datetime import datetime, timezone
        window = (candles or [])[-(_BASELINE_BARS + 1):]
        ts = []
        for c in window:
            t = datetime.fromisoformat(str(c.get("timestamp")).replace("Z", "+00:00"))
            ts.append(t.replace(tzinfo=t.tzinfo or timezone.utc))
        return sum(1 for a, b in zip(ts, ts[1:])
                   if (b - a).total_seconds() > 90)
    except Exception:  # noqa: BLE001
        return 0


def _data_quality(one_m: list, core_1m: dict, baseline_table) -> dict:
    if core_1m.get("state") == "insufficient_data":
        status = "insufficient_history"
    elif _missing_bars(one_m) > 3 or core_1m.get("zscore") is None:
        status = "degraded"
    else:
        status = "healthy"
    sessions = int((baseline_table or {}).get("sessions") or 0)
    last_ts = (one_m[-1].get("timestamp") if one_m else None)
    return {
        "status": status,
        "feed_source": "alpaca",
        "venue_scope": "venue_limited_iex",
        "venue_note": ("IEX venue volume only — NOT the consolidated tape. "
                       "Relative metrics compare IEX to its own IEX baseline; "
                       "absolute volume understates total-market activity."),
        "bar_timestamp": last_ts,
        "bar_complete": True,
        "bar_complete_basis": ("provider REST bars endpoint emits completed "
                               "bars only; the forming minute is not returned"),
        "missing_bar_count": _missing_bars(one_m),
        "baseline_sessions": sessions,
        "warmup_sufficient": core_1m.get("state") != "insufficient_data",
    }


# ── event association (existing sensors only — no re-detection) ──────────────

def _sweep_context(all_normalized: dict, liquidity: dict, by_tf: dict,
                   baseline_table) -> dict:
    """Volume on the ALREADY-identified sweep. liquidity_engine flags sweeps
    on the last candle, so the sweep bar is the current bar by construction."""
    for tf in _TFS:
        liq = (liquidity or {}).get(tf) or {}
        if not liq.get("sweep_detected"):
            continue
        candles = (all_normalized or {}).get(tf) or []
        core = by_tf.get(tf) or {}
        if core.get("state") == "insufficient_data" or not candles:
            return {"event_present": True, "tf": tf,
                    "relative_volume": None, "volume_peak_timing": "unavailable"}
        vols = [float(c.get("volume") or 0) for c in candles]
        approach = vols[-4:-1]
        peak_timing = ("before" if approach and max(approach) > vols[-1]
                       else "during")
        pct = same_minute_percentile(vols[-1], candles[-1].get("timestamp"),
                                     baseline_table) if tf == "1m" else \
            {"same_minute_percentile": None, "same_minute_sample_n": 0}
        return {
            "event_present": True,
            "tf": tf,
            "sweep_direction": liq.get("sweep_direction"),
            "relative_volume": core.get("relative"),
            "volume_peak_timing": peak_timing,
            **pct,
        }
    return {"event_present": False}


def _displacement_context(all_normalized: dict, expansion: dict,
                          by_tf: dict) -> dict:
    """Participation across the EXISTING displacement leg convention: the tail
    same-direction run (expansion_detector's follow-through analog), only when
    the existing sensor already flagged displacement. No second detector."""
    for tf in _TFS:
        exp = (expansion or {}).get(tf) or {}
        if not exp.get("displacement_detected"):
            continue
        candles = (all_normalized or {}).get(tf) or []
        core = by_tf.get(tf) or {}
        if core.get("state") == "insufficient_data" or len(candles) < 2:
            return {"event_present": True, "tf": tf, "leg_bar_count": 0,
                    "note": "insufficient volume history for leg metrics"}
        last_dir = candles[-1].get("direction")
        leg = []
        for c in reversed(candles[-_LEG_CAP:]):
            if last_dir not in ("bullish", "bearish") or c.get("direction") != last_dir:
                break
            leg.append(c)
        leg.reverse()
        if not leg:
            leg = [candles[-1]]
        vols = [float(c.get("volume") or 0) for c in leg]
        baseline = core.get("baseline_avg") or 0
        total = sum(vols)
        half = max(1, len(vols) // 2)
        expanding = (len(vols) >= 2
                     and sum(vols[-half:]) / half > sum(vols[:half]) / half)
        progress = abs(float(leg[-1].get("close") or 0) - float(leg[0].get("open") or 0))
        return {
            "event_present": True,
            "tf": tf,
            "leg_bar_count": len(leg),
            "total_volume": round(total, 1),
            "average_relative_volume": (round((total / len(vols)) / baseline, 2)
                                        if baseline > 0 else None),
            "volume_expanding_across_leg": bool(expanding),
            "price_progress_per_volume": (round(progress / total, 8)
                                          if total > 0 else None),
        }
    return {"event_present": False}


# ── participation summary ─────────────────────────────────────────────────────

_PARTICIPATION_MAP = {"dead": "subdued", "quiet": "subdued", "normal": "normal",
                      "elevated": "elevated", "climactic": "elevated"}


def _efficiency(candles: list, core_1m: dict) -> str:
    """Descriptive price-progress vs participation over the last 5 bars.
    NEVER interpreted directionally here — the Brain owns meaning."""
    if core_1m.get("state") == "insufficient_data" or len(candles or []) < _RECENT_BARS:
        return "unavailable"
    recent = candles[-_RECENT_BARS:]
    net = abs(float(recent[-1].get("close") or 0) - float(recent[0].get("open") or 0))
    total_range = sum(abs(float(c.get("high") or 0) - float(c.get("low") or 0))
                      for c in recent)
    progress = (net / total_range) if total_range > 0 else 0.0
    rel = core_1m.get("trend_ratio") or 0
    high_vol, low_vol = rel >= 1.5, rel < 0.8
    if high_vol and progress >= 0.5:
        return "high_volume_large_progress"
    if high_vol and progress < 0.25:
        return "high_volume_low_progress"
    if low_vol and progress >= 0.5:
        return "low_volume_large_progress"
    return "ordinary"


# ── public builder ────────────────────────────────────────────────────────────

def build_volume_witness(all_normalized: dict, liquidity: dict = None,
                         expansion: dict = None, symbol: str = None) -> dict:
    """Full participation witness for snapshot['volume_witness'].
    Non-directional by construction; deterministic over its inputs + the local
    baseline table; never raises."""
    try:
        by_tf = {tf: _tf_witness((all_normalized or {}).get(tf) or [])
                 for tf in _TFS}
        one_m = (all_normalized or {}).get("1m") or []
        core_1m = by_tf.get("1m") or {}
        baseline_table = load_minute_baseline(symbol or "QQQ")

        current_bar = {}
        if core_1m.get("state") not in (None, "insufficient_data"):
            current_bar = {
                "volume": core_1m["last_volume"],
                "relative_volume_20": core_1m["relative"],
                "rolling_volume_zscore": core_1m["zscore"],
                **same_minute_percentile(core_1m["last_volume"],
                                         one_m[-1].get("timestamp") if one_m else None,
                                         baseline_table),
            }

        participation_state = _PARTICIPATION_MAP.get(core_1m.get("state"),
                                                     "unavailable")
        return {
            "source": "mechanical_volume_witness",
            "authored_by": "mechanical_sensor",
            "authority_class": "witness",
            "authority": "witness_only",
            "decision_authority": False,
            "non_directional": True,
            "calculation_version": CALCULATION_VERSION,
            "data_quality": _data_quality(one_m, core_1m, baseline_table),
            "current_bar": current_bar,
            "by_tf": by_tf,
            "sweep_context": _sweep_context(all_normalized, liquidity, by_tf,
                                            baseline_table),
            "displacement_context": _displacement_context(all_normalized,
                                                          expansion, by_tf),
            "participation": {
                "state": participation_state,
                "price_volume_efficiency": _efficiency(one_m, core_1m),
                "volume_trend": core_1m.get("trend", "unavailable"),
            },
            "note": ("relative participation vs own trailing baseline — "
                     "magnitude of activity only, never a direction"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"source": "mechanical_volume_witness",
                "authority_class": "witness", "authority": "witness_only",
                "decision_authority": False, "non_directional": True,
                "calculation_version": CALCULATION_VERSION,
                "by_tf": {}, "error": f"volume_witness error: {exc}"}
