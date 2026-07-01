"""
Adaptive Learning — Phase 3B: Adaptive policy engine (READ, DEFENSIVE_ONLY).

Reads the symbol-native performance tables and turns them into a per-candidate
policy report: a grade per dimension plus DEFENSIVE_ONLY recommendation flags.

HARD DOCTRINE — DEFENSIVE_ONLY / recommendation-only (ADAPTIVE-3):

  Allowed to RECOMMEND : reduce confidence, reduce size, block a trade, caution.
  Forbidden            : create trades; override qualification / structure /
                         playbook / toolbox / risk governor / ECU thesis.

Nothing here mutates. `authority_level` is hard-locked to "observe_only" and the
posture is "DEFENSIVE_ONLY". Actuation (bounded mutation) is a LATER phase.

Policy rules (per dimension bucket, once it has >= MIN_SAMPLE trades):

  expectancy >= +0.25  -> confidence_boost      (suppressed if any defensive flag)
  expectancy <= -0.15  -> confidence_penalty
  expectancy <= -0.30  -> risk_reduction
  loss_streak >= 4     -> trade_block            (fires regardless of sample)
"""
from __future__ import annotations

from adaptive_learning.performance_tables import DIMENSIONS, get_bucket

BOOST_THRESHOLD    = 0.25
PENALTY_THRESHOLD  = -0.15
SEVERE_THRESHOLD   = -0.30
BLOCK_LOSS_STREAK  = 4
MIN_SAMPLE         = 3          # trades required before expectancy is graded

AUTHORITY_LEVEL = "observe_only"   # HARD-LOCK
POSTURE         = "DEFENSIVE_ONLY"  # HARD-LOCK


def _grade(bucket: dict) -> str:
    """Grade a bucket by expectancy, gated on sample size. Streak-driven blocking
    is handled separately (it can fire below MIN_SAMPLE at 4 losses)."""
    trades = int(bucket.get("trades", 0) or 0)
    exp = float(bucket.get("expectancy", 0.0) or 0.0)
    if trades < MIN_SAMPLE:
        return "insufficient_data"
    if exp <= SEVERE_THRESHOLD:
        return "severe"
    if exp <= PENALTY_THRESHOLD:
        return "weak"
    if exp >= BOOST_THRESHOLD:
        return "strong"
    return "neutral"


def neutral_policy_report(symbol: str = "unknown",
                          reason: str = "no performance history") -> dict:
    """Safe all-neutral report (no history / error). All flags False."""
    grades = {f"{d}_grade": "insufficient_data" for d in DIMENSIONS}
    return {
        "symbol": symbol,
        **grades,
        "confidence_boost_recommended": False,
        "confidence_penalty_recommended": False,
        "risk_reduction_recommended": False,
        "trade_block_recommended": False,
        "recommended_adjustments": [],
        "authority_level": AUTHORITY_LEVEL,
        "posture": POSTURE,
        "dimensions": {},
        "explanation": reason,
    }


def generate_adaptive_policy_report(candidate: dict,
                                    base_dir: "str | None" = None) -> dict:
    """Build the DEFENSIVE_ONLY policy report for a candidate.

    candidate = {symbol, playbook, tool, session, regime, volatility}. Any dim may
    be missing/None (graded insufficient_data). Reads tables only; never mutates.
    Never raises — returns a neutral report on any failure.
    """
    try:
        candidate = candidate or {}
        symbol = candidate.get("symbol") or "unknown"

        grades: dict = {}
        detail: dict = {}
        adjustments: list = []
        boost = penalty = risk_reduction = trade_block = False

        for dim in DIMENSIONS:
            key = candidate.get(dim)
            bucket = get_bucket(symbol, dim, key, base_dir)
            grade = _grade(bucket)
            grades[f"{dim}_grade"] = grade
            exp = float(bucket.get("expectancy", 0.0) or 0.0)
            trades = int(bucket.get("trades", 0) or 0)
            streak = int(bucket.get("loss_streak", 0) or 0)
            detail[dim] = {"key": key, "expectancy": exp, "trades": trades,
                           "loss_streak": streak, "grade": grade}

            # ── DEFENSIVE flags (require sample) ──
            if trades >= MIN_SAMPLE:
                if exp <= SEVERE_THRESHOLD:
                    risk_reduction = True
                    adjustments.append(
                        f"{dim}({key}): expectancy {exp:+.2f} <= {SEVERE_THRESHOLD} -> risk_reduction")
                if exp <= PENALTY_THRESHOLD:
                    penalty = True
                    adjustments.append(
                        f"{dim}({key}): expectancy {exp:+.2f} <= {PENALTY_THRESHOLD} -> confidence_penalty")
                elif exp >= BOOST_THRESHOLD:
                    adjustments.append(
                        f"{dim}({key}): expectancy {exp:+.2f} >= {BOOST_THRESHOLD} -> confidence_boost")
                    boost = True

            # ── streak block (fires regardless of sample) ──
            if streak >= BLOCK_LOSS_STREAK:
                trade_block = True
                adjustments.append(
                    f"{dim}({key}): loss_streak {streak} >= {BLOCK_LOSS_STREAK} -> trade_block")

        # DEFENSIVE precedence: any defensive signal suppresses a boost recommendation.
        if penalty or risk_reduction or trade_block:
            boost = False

        return {
            "symbol": symbol,
            **grades,
            "confidence_boost_recommended": boost,
            "confidence_penalty_recommended": penalty,
            "risk_reduction_recommended": risk_reduction,
            "trade_block_recommended": trade_block,
            "recommended_adjustments": adjustments,
            "authority_level": AUTHORITY_LEVEL,
            "posture": POSTURE,
            "dimensions": detail,
            "explanation": "adaptive performance policy (recommendation-only)",
        }
    except Exception as exc:  # noqa: BLE001
        return neutral_policy_report(
            (candidate or {}).get("symbol", "unknown"),
            reason=f"policy_error:{type(exc).__name__}")
