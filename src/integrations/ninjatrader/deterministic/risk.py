"""Deterministic risk engine — RISK-BASED sizing, structural stop, fixed target.

Pure math + fail-closed gates. No market opinions here; direction and the
structural invalidation price are supplied by the author from mechanical
structure. This module only validates and prices them.

Sizing is risk-based: contracts = floor(MAX_RISK_DOLLARS / (stop_pts x $2)),
capped at MAX_CONTRACTS. Tighter stop -> more size; wider stop -> less; a stop
beyond MAX_STOP_POINTS is NO TRADE (never widened to fit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from integrations.ninjatrader.deterministic import (
    TICK_SIZE, POINT_VALUE, TARGET_POINTS, MAX_STOP_POINTS, MAX_RISK_DOLLARS,
    MAX_CONTRACTS, DAILY_LOSS_CEILING, COMMISSION_PER_CONTRACT, SLIPPAGE_TICKS,
)

LONG = "long"
SHORT = "short"


def normalize_tick(price: float, tick: float = TICK_SIZE) -> float:
    return round(round(float(price) / tick) * tick, 6)


def contracts_for_stop(stop_points) -> int:
    """RISK-BASED size: the largest whole contract count whose worst-case loss
    (stop_points x $POINT_VALUE) stays within MAX_RISK_DOLLARS, capped at
    MAX_CONTRACTS. Returns 0 for a non-positive stop or a stop beyond the cap
    (-> no trade). Never rounds up; risk is never allowed to exceed the budget."""
    try:
        sp = float(stop_points)
    except (TypeError, ValueError):
        return 0
    if sp <= 0 or sp > MAX_STOP_POINTS + 1e-9:
        return 0
    raw = int(MAX_RISK_DOLLARS // (sp * POINT_VALUE))   # floor — never over budget
    return max(0, min(raw, MAX_CONTRACTS))


def check_quantity(qty) -> tuple:
    """Validate a RISK-SIZED quantity: a whole number in [1, MAX_CONTRACTS].
    Zero/negative/fractional/over-ceiling are rejected (never auto-adjusted)."""
    if isinstance(qty, bool) or qty is None:
        return False, f"quantity {qty!r} invalid"
    try:
        f = float(qty)
    except (TypeError, ValueError):
        return False, f"quantity {qty!r} not numeric"
    if f != int(f):
        return False, f"fractional quantity {qty!r} rejected"
    q = int(f)
    if q < 1:
        return False, f"quantity {q} < 1 (no trade)"
    if q > MAX_CONTRACTS:
        return False, f"quantity {q} > MAX_CONTRACTS {MAX_CONTRACTS}"
    return True, f"quantity {q} (1..{MAX_CONTRACTS})"


def target_price(direction: str, avg_fill: float) -> float:
    """Fixed 35-point target from the ACTUAL average fill, tick-normalized."""
    if direction == LONG:
        return normalize_tick(avg_fill + TARGET_POINTS)
    if direction == SHORT:
        return normalize_tick(avg_fill - TARGET_POINTS)
    raise ValueError(f"bad direction {direction!r}")


@dataclass
class StopAssessment:
    valid: bool
    reason: str
    stop_price: Optional[float] = None
    stop_distance: Optional[float] = None
    correct_side: bool = False


def assess_structural_stop(direction: str, reference_price: float,
                           structural_stop: float) -> StopAssessment:
    """Validate a STRUCTURE-derived stop: correct side + within the 25-pt cap.

    `reference_price` is the expected entry (pre-trade) or the actual average
    fill (post-fill re-check). The stop must invalidate the setup on the correct
    side and be <= 25.00 points away. Never widened, never moved closer here.
    """
    stop = normalize_tick(structural_stop)
    if direction == LONG:
        if not (stop < reference_price):
            return StopAssessment(False, "LONG stop must be BELOW entry", stop)
        dist = reference_price - stop
    elif direction == SHORT:
        if not (stop > reference_price):
            return StopAssessment(False, "SHORT stop must be ABOVE entry", stop)
        dist = stop - reference_price
    else:
        return StopAssessment(False, f"bad direction {direction!r}", stop)

    dist = round(dist, 6)
    if dist <= 0:
        return StopAssessment(False, "stop distance non-positive", stop, dist, False)
    # Hard cap: > 25.00 rejects. Exactly 25.00 passes.
    if dist > MAX_STOP_POINTS + 1e-9:
        return StopAssessment(False,
                              f"structural stop distance {dist} > {MAX_STOP_POINTS} cap — REJECT",
                              stop, dist, True)
    return StopAssessment(True, f"structural stop {dist} pts (<= {MAX_STOP_POINTS})",
                          stop, dist, True)


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    quantity: int = 0
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_distance: Optional[float] = None
    gross_risk: float = 0.0
    gross_reward: float = 0.0
    reward_to_risk: float = 0.0
    modeled_costs: float = 0.0
    commission_known: bool = False
    warnings: list = field(default_factory=list)


def _modeled_costs(qty: int) -> tuple:
    known = COMMISSION_PER_CONTRACT is not None
    commission = (float(COMMISSION_PER_CONTRACT) * qty) if known else 0.0
    slippage = SLIPPAGE_TICKS * TICK_SIZE * POINT_VALUE * qty
    return commission + slippage, known


def assess_trade(direction: str, reference_price: float, structural_stop: float,
                 realized_daily_loss: float) -> RiskDecision:
    """Full pre-authorization risk assessment with RISK-BASED sizing.

    Rejects if: stop wrong side, stop > 25pts (-> qty 0), sized quantity invalid,
    or realized_loss + full trade risk + modeled costs would breach the $1000
    ceiling. Quantity scales to the stop so per-trade risk stays near $500.
    """
    warnings = []
    stop = assess_structural_stop(direction, reference_price, structural_stop)
    if not stop.valid:
        return RiskDecision(False, stop.reason, stop_price=stop.stop_price,
                            stop_distance=stop.stop_distance)

    qty = contracts_for_stop(stop.stop_distance)
    ok_q, why_q = check_quantity(qty)
    if not ok_q:
        return RiskDecision(False, why_q, stop_price=stop.stop_price,
                            stop_distance=stop.stop_distance)

    dollars_per_point = POINT_VALUE * qty
    tgt = target_price(direction, reference_price)
    gross_risk = round(stop.stop_distance * dollars_per_point, 2)
    gross_reward = round(TARGET_POINTS * dollars_per_point, 2)
    rr = round(TARGET_POINTS / stop.stop_distance, 4)
    costs, known = _modeled_costs(qty)
    if not known:
        warnings.append("commission UNKNOWN — modeled 0 but flagged")

    # Daily-loss ceiling: realized loss + full proposed risk + modeled costs.
    projected = float(realized_daily_loss) + gross_risk + costs
    if projected > DAILY_LOSS_CEILING + 1e-9:
        return RiskDecision(False,
                            f"daily-loss ceiling: realized {realized_daily_loss} + risk "
                            f"{gross_risk} + costs {costs:.2f} = {projected:.2f} > "
                            f"{DAILY_LOSS_CEILING}",
                            quantity=qty, stop_price=stop.stop_price, target_price=tgt,
                            stop_distance=stop.stop_distance, gross_risk=gross_risk,
                            gross_reward=gross_reward, reward_to_risk=rr,
                            modeled_costs=costs, commission_known=known, warnings=warnings)

    return RiskDecision(True, f"risk approved for {qty} contracts",
                        quantity=qty, stop_price=stop.stop_price, target_price=tgt,
                        stop_distance=stop.stop_distance, gross_risk=gross_risk,
                        gross_reward=gross_reward, reward_to_risk=rr,
                        modeled_costs=costs, commission_known=known, warnings=warnings)
