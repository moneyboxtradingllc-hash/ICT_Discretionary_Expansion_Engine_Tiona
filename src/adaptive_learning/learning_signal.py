"""
Adaptive Learning — Phase 1B: Learning Signal Generator (analysis-only).

Reads retrieved historical analogs (the output of ai_retrieval.retrieve_analogs)
and distills them into a structured, DETERMINISTIC LearningSignal: historical
win-rate / expectancy / risk over the matched analog set, plus warning tags and
evidence strings.

SCOPE GUARANTEES (Phase 1B):
  * ANALYSIS ONLY. No LLM. No mutation of retrieve_analogs(), Brain prompting,
    confidence, risk, or execution.
  * Default authority_level is "observe_only", which forces confidence_adjustment
    to 0 — this phase reads scars; it does not let the bot flinch yet.
  * Degrades gracefully on the trimmed analog view (which lacks mae/stop_distance/
    is_authoritative): such records are skipped from mae_risk only, and the
    authoritative filter applies only when the field is present.

Never raises from the public API.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

try:
    import pytz
    _NY = pytz.timezone("America/New_York")
except Exception:  # noqa: BLE001 — pytz is a project dep; degrade if absent
    _NY = None

from datetime import datetime

AUTHORITY_LEVELS = ("observe_only", "advisory", "bounded_modifier")
DEFAULT_SIMILARITY_THRESHOLD = 0.82


# ── Signal ────────────────────────────────────────────────────────────────────

@dataclass
class LearningSignal:
    sample_size: int = 0
    win_rate: float = 0.0
    avg_r: float = 0.0
    failure_rate: float = 0.0
    success_rate: float = 0.0
    mae_risk: "float | None" = None
    confidence_adjustment: int = 0
    risk_adjustment: int = 0                       # reserved (always 0 in 1B)
    playbook_bias: "str | None" = None
    warning_tags: list = field(default_factory=list)
    supporting_evidence: list = field(default_factory=list)
    conflicting_evidence: list = field(default_factory=list)
    authority_level: str = "observe_only"
    reason: str = ""


# ── field access helpers (tolerate trimmed view OR rich record) ───────────────

def _r_value(a: dict):
    v = a.get("realized_r")
    if v is None:
        v = a.get("r_multiple")
    return _to_float(v)


def _direction(a: dict):
    return _norm_dir(a.get("direction") or a.get("narrative_direction")
                     or a.get("delivery_direction"))


def _stop_distance(a: dict):
    """abs(entry - stop) in points, or an explicit stop_distance. None if absent."""
    sd = _to_float(a.get("stop_distance"))
    if sd is not None:
        return abs(sd)
    ep, sp = _to_float(a.get("entry_price")), _to_float(a.get("stop_price"))
    if ep is not None and sp is not None:
        return abs(ep - sp)
    return None


def _norm_dir(d):
    if not d:
        return None
    d = str(d).lower()
    for k in ("bullish", "bull", "long"):
        if d.startswith(k):
            return "bullish"
    for k in ("bearish", "bear", "short"):
        if d.startswith(k):
            return "bearish"
    if d in ("neutral", "none", "conflicted"):
        return None
    return None


def _compatible(cur, analog):
    """Directions compatible if either is unknown/neutral or they match."""
    if cur is None or analog is None:
        return True
    return cur == analog


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── NY lunch classification ───────────────────────────────────────────────────

def _in_ny_lunch(ts: str) -> bool:
    """True if `ts` falls in the 12:00–13:00 America/New_York lunch hour.

    UTC / offset-aware timestamps are converted to NY. A naive (tz-missing)
    timestamp is TREATED AS America/New_York local time (documented behavior).
    Window is [12:00, 13:00) NY.
    """
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return False
    try:
        if dt.tzinfo is None:
            local = _NY.localize(dt) if _NY else dt          # naive → treat as NY
        else:
            local = dt.astimezone(_NY) if _NY else dt        # convert to NY
        return local.hour == 12
    except Exception:  # noqa: BLE001
        return False


# ── confidence adjustment ─────────────────────────────────────────────────────

def calculate_confidence_adjustment(sample_size: int, win_rate: float,
                                    mean_r: float, authority_level: str) -> int:
    """Deterministic bounded confidence delta. Always clamped to [-5, +5].

    observe_only / thin sample / coin-flip win-rate / flat expectancy → 0.
    Positive edge → small positive; negative scar → harsher negative (floored)."""
    adj = 0
    if authority_level == "observe_only":
        adj = 0
    elif sample_size < 10:
        adj = 0
    elif 0.45 <= win_rate <= 0.55:
        adj = 0
    elif -0.2 <= mean_r <= 0.2:
        adj = 0
    elif win_rate >= 0.65 and mean_r >= 1.2:
        adj = min(int(2 + mean_r * 0.5), 5)
    elif win_rate <= 0.35 or mean_r < 0.0:
        # ADDENDUM #2 — scar penalties FLOOR (math.floor(-3.7) == -4), never
        # truncate toward zero (int(-3.7) == -3 would under-penalize).
        adj = max(math.floor(-3 + mean_r * 1.0), -5)
    else:
        adj = 0
    return max(-5, min(5, adj))


# ── public API ────────────────────────────────────────────────────────────────

def build_learning_signal(
    analogs,
    current_snapshot: dict = None,
    authority_level: str = "observe_only",
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> LearningSignal:
    """Convert retrieved analogs into a LearningSignal. Never raises."""
    try:
        if authority_level not in AUTHORITY_LEVELS:
            authority_level = "observe_only"
        return _build(analogs or [], current_snapshot or {},
                      authority_level, similarity_threshold)
    except Exception as exc:  # noqa: BLE001
        return LearningSignal(authority_level=authority_level,
                              warning_tags=["insufficient_sample_size"],
                              reason=f"signal_error:{type(exc).__name__}")


def _build(analogs, snapshot, authority_level, threshold) -> LearningSignal:
    cur_dir = _snapshot_direction(snapshot)
    cur_regime = (snapshot.get("market_regime", {}) or {}).get("regime_label")
    cur_regime = (cur_regime or "").lower() or None

    # ── filter ────────────────────────────────────────────────────────────────
    M = []
    for a in analogs:
        if not isinstance(a, dict):
            continue
        sim = _to_float(a.get("similarity"))
        if sim is None or sim < threshold:
            continue
        if _r_value(a) is None:                     # must have a realized result
            continue
        if "is_authoritative" in a and not a.get("is_authoritative"):
            continue                                 # authoritative if available
        if not _compatible(cur_dir, _direction(a)):
            continue
        M.append(a)

    n = len(M)
    if n == 0:
        return LearningSignal(
            authority_level=authority_level,
            warning_tags=["insufficient_sample_size"],
            reason="no qualifying analogs (after similarity/result/direction filter)",
        )

    rs = [_r_value(a) for a in M]
    wins = sum(1 for r in rs if r > 0)
    losses = sum(1 for r in rs if r < 0)
    win_rate = wins / n
    failure_rate = losses / n
    avg_r = sum(rs) / n

    # ── mae_risk (skip records missing mae or with zero/missing stop_distance) ─
    mae_ratios = []
    for a in M:
        mae = _to_float(a.get("mae"))
        sd = _stop_distance(a)
        if mae is None or sd is None or sd == 0:    # ADDENDUM #1 — guard div-by-0
            continue                                 # skip from mae_risk ONLY
        mae_ratios.append(abs(mae) / abs(sd))
    mae_risk = (sum(mae_ratios) / len(mae_ratios)) if mae_ratios else None

    confidence_adjustment = calculate_confidence_adjustment(
        n, win_rate, avg_r, authority_level)

    warning_tags = _warning_tags(M, rs, win_rate, avg_r, mae_risk, n, cur_regime)
    supporting, conflicting = _evidence(M)
    playbook_bias = _playbook_bias(M)

    reason = (f"n={n} win_rate={win_rate:.2f} avg_r={avg_r:.2f} "
              f"conf_adj={confidence_adjustment} authority={authority_level}")

    return LearningSignal(
        sample_size=n,
        win_rate=round(win_rate, 4),
        avg_r=round(avg_r, 4),
        failure_rate=round(failure_rate, 4),
        success_rate=round(win_rate, 4),
        mae_risk=(round(mae_risk, 4) if mae_risk is not None else None),
        confidence_adjustment=confidence_adjustment,
        risk_adjustment=0,
        playbook_bias=playbook_bias,
        warning_tags=warning_tags,
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        authority_level=authority_level,
        reason=reason,
    )


# ── components ────────────────────────────────────────────────────────────────

def _snapshot_direction(snapshot):
    na = snapshot.get("narrative_authority", {}) or {}
    sc = snapshot.get("shared_context", {}) or {}
    pb = snapshot.get("playbook", {}) or {}
    ql = snapshot.get("qualification", {}) or {}
    for cand in (na.get("narrative_direction"), sc.get("delivery_state"),
                 pb.get("direction"), ql.get("direction")):
        d = _norm_dir(cand)
        if d:
            return d
    return None


def _warning_tags(M, rs, win_rate, avg_r, mae_risk, n, cur_regime) -> list:
    tags = []
    failed = [a for a, r in zip(M, rs) if r < 0]
    if failed:
        lunch_fail = sum(1 for a in failed if _in_ny_lunch(a.get("timestamp")))
        if lunch_fail / len(failed) >= 0.70:
            tags.append("similar_setups_failed_during_lunch")
    if mae_risk is not None and mae_risk > 0.85:
        tags.append("prior_success_requires_stronger_delivery")
    if cur_regime:
        regime_set = [r for a, r in zip(M, rs)
                      if (a.get("regime") or "").lower() == cur_regime]
        if regime_set:
            regime_wr = sum(1 for r in regime_set if r > 0) / len(regime_set)
            if regime_wr < 0.30:
                tags.append("playbook_underperformed_in_current_regime")
    if 0.45 <= win_rate <= 0.55:
        tags.append("mixed_historical_outcomes")
    if n < 10:
        tags.append("insufficient_sample_size")
    if avg_r < 0:
        tags.append("negative_historical_expectancy")
    if win_rate >= 0.65 and avg_r >= 1.2:
        tags.append("positive_historical_expectancy")
    return tags


def _evidence(M, limit: int = 3):
    """Compact, deterministic favorable / unfavorable analog summaries."""
    enriched = [(_r_value(a), a) for a in M]
    winners = sorted([e for e in enriched if e[0] > 0], key=lambda e: -e[0])
    losers = sorted([e for e in enriched if e[0] < 0], key=lambda e: e[0])

    def _fmt(r, a):
        pb = (a.get("active_playbook") or a.get("playbook") or "n/a")
        rg = (a.get("regime") or "n/a")
        return f"{r:+.1f}R {pb}/{rg}"

    supporting = [_fmt(r, a) for r, a in winners[:limit]]
    conflicting = [_fmt(r, a) for r, a in losers[:limit]]
    return supporting, conflicting


def _playbook_bias(M):
    """Most frequent playbook among WINNING analogs (alphabetical tie-break)."""
    counts = {}
    for a in M:
        if (_r_value(a) or 0) > 0:
            pb = (a.get("active_playbook") or a.get("playbook") or "").lower()
            if pb:
                counts[pb] = counts.get(pb, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
