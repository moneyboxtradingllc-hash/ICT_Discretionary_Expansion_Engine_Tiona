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

MEM-DECAY-1 — scar forgiveness. The streak block is no longer permanent: each
blocked bucket is passed through the Memory Decay Engine (cooldown ->
probation -> reopen state machine). While SCARRED/COOLDOWN the block stands
untouched. Under PROBATION the hard block converts into the EXISTING defensive
actuators (confidence_penalty + risk_reduction -> mutation applies -10%
confidence and halves size) for a controlled test trade. A probation win
resets the table streak (bucket reopens); a probation loss re-locks with a
doubled cooldown. Decay can only soften — never boost, never approve.
"""
from __future__ import annotations

from adaptive_learning.performance_tables import DIMENSIONS, get_bucket
from adaptive_learning.memory_decay_engine import evaluate_bucket_decay

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
        "probation_active": False,
        "recommended_adjustments": [],
        "authority_level": AUTHORITY_LEVEL,
        "posture": POSTURE,
        "dimensions": {},
        "explanation": reason,
    }


def generate_adaptive_policy_report(candidate: dict,
                                    base_dir: "str | None" = None,
                                    today: "str | None" = None,
                                    decay_persist: bool = True) -> dict:
    """Build the DEFENSIVE_ONLY policy report for a candidate.

    candidate = {symbol, playbook, tool, session, regime, volatility}. Any dim may
    be missing/None (graded insufficient_data). Reads tables only; the Memory
    Decay Engine additionally advances per-bucket scar state (MEM-DECAY-1).
    `today` (YYYY-MM-DD) is a test seam; live callers use the wall clock.
    Never raises — returns a neutral report on any failure.
    """
    try:
        candidate = candidate or {}
        symbol = candidate.get("symbol") or "unknown"

        grades: dict = {}
        detail: dict = {}
        adjustments: list = []
        boost = penalty = risk_reduction = trade_block = False
        probation_active = False

        for dim in DIMENSIONS:
            key = candidate.get(dim)
            bucket = get_bucket(symbol, dim, key, base_dir)
            grade = _grade(bucket)
            grades[f"{dim}_grade"] = grade
            exp = float(bucket.get("expectancy", 0.0) or 0.0)
            trades = int(bucket.get("trades", 0) or 0)
            streak = int(bucket.get("loss_streak", 0) or 0)

            # ── MEM-DECAY-1: scar state (cooldown -> probation -> reopen) ──
            decay = evaluate_bucket_decay(symbol, dim, key, bucket,
                                          block_threshold=BLOCK_LOSS_STREAK,
                                          today=today, base_dir=base_dir,
                                          persist=decay_persist)
            # ── SUPPRESS-1: read-only suppression evidence (adaptive memory
            # feed). OBSERVATION ONLY — no policy flag reads these numbers;
            # repeated false suppressions become a FUTURE tuning signal.
            from adaptive_learning.suppression_cost_engine import get_suppression_stats
            suppression = get_suppression_stats(symbol, dim, key, base_dir)
            detail[dim] = {"key": key, "expectancy": exp, "trades": trades,
                           "loss_streak": streak, "grade": grade,
                           "decay": decay, "suppression": suppression}

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

            # ── streak block, filtered through decay (fires regardless of sample) ──
            if streak >= BLOCK_LOSS_STREAK:
                if decay.get("probation"):
                    # PROBATION: hard block softens into the existing defensive
                    # actuators — one reduced-size, reduced-confidence test trade.
                    probation_active = True
                    penalty = True
                    risk_reduction = True
                    adjustments.append(
                        f"{dim}({key}): PROBATION (lock #{decay.get('lock_count')}, "
                        f"cooldown served) -> reduced size + reduced confidence")
                else:
                    trade_block = True
                    adjustments.append(
                        f"{dim}({key}): loss_streak {streak} >= {BLOCK_LOSS_STREAK} "
                        f"-> trade_block [{decay.get('decay_status')} "
                        f"{decay.get('scar_age_sessions')}/{decay.get('cooldown_required')}]")

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
            "probation_active": probation_active,
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
