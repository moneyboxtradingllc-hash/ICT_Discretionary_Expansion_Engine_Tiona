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
    RISK_PCT_OF_EQUITY, HARD_MAX_RISK_PCT, DAILY_LOSS_PCT_OF_EQUITY,
    COMPOUNDING_ENABLED, MARGIN_PER_CONTRACT, MARGIN_USAGE_PCT,
    MAX_CONTRACTS_HARD,
)

LONG = "long"
SHORT = "short"


def normalize_tick(price: float, tick: float = TICK_SIZE) -> float:
    return round(round(float(price) / tick) * tick, 6)


def _equity(equity) -> Optional[float]:
    """Usable account equity, or None. Anything non-positive or unparseable is
    treated as unknown so sizing falls back to the fixed budget."""
    try:
        e = float(equity)
    except (TypeError, ValueError):
        return None
    return e if e > 0 else None


def risk_budget(equity=None) -> tuple:
    """Per-trade dollar risk. Returns (budget, reason).

    Compounds with the account: budget = equity x RISK_PCT_OF_EQUITY, so size
    grows as the balance grows and shrinks on drawdown. HARD_MAX_RISK_PCT caps
    the CONFIG — whatever the percentage is set to, per-trade risk can never
    exceed that share of the balance.

    Unknown equity falls back to the flat MAX_RISK_DOLLARS, never to something
    larger.
    """
    e = _equity(equity)
    if not COMPOUNDING_ENABLED:
        return MAX_RISK_DOLLARS, f"flat budget ${MAX_RISK_DOLLARS:.2f} (compounding off)"
    if e is None:
        return MAX_RISK_DOLLARS, (f"flat budget ${MAX_RISK_DOLLARS:.2f} "
                                  f"(equity unknown — fail-safe)")
    pct = min(RISK_PCT_OF_EQUITY, HARD_MAX_RISK_PCT)
    capped = pct < RISK_PCT_OF_EQUITY
    budget = round(e * pct / 100.0, 2)
    reason = (f"${budget:.2f} = {pct:.2f}% of equity ${e:,.2f}"
              + (f" (config {RISK_PCT_OF_EQUITY:.2f}% capped at "
                 f"{HARD_MAX_RISK_PCT:.2f}%)" if capped else ""))
    return budget, reason


def daily_loss_ceiling(equity=None) -> tuple:
    """Daily realized-loss ceiling. Returns (ceiling, reason).

    Must scale with the same equity the per-trade budget uses. The ceiling is
    checked PRE-trade against the full proposed risk, so a fixed ceiling below a
    compounded trade risk rejects every trade forever.
    """
    e = _equity(equity)
    if not COMPOUNDING_ENABLED or e is None:
        return DAILY_LOSS_CEILING, f"flat ceiling ${DAILY_LOSS_CEILING:.2f}"
    ceiling = round(e * DAILY_LOSS_PCT_OF_EQUITY / 100.0, 2)
    return ceiling, (f"${ceiling:.2f} = {DAILY_LOSS_PCT_OF_EQUITY:.2f}% of "
                     f"equity ${e:,.2f}")


def contract_ceiling(equity=None) -> tuple:
    """How many contracts the ACCOUNT CAN HOLD. Returns (ceiling, reason).

    Not a risk rule — risk is governed by the 3% budget alone. This is margin:
    a $50k account cannot carry 151 MNQ contracts whatever the risk math says,
    because the broker rejects it first. Applying it here makes a real constraint
    explicit instead of surfacing as a rejected order.
    """
    e = _equity(equity)
    if not COMPOUNDING_ENABLED or e is None:
        return MAX_CONTRACTS, f"legacy fixed ceiling {MAX_CONTRACTS} (equity unknown)"
    if MARGIN_PER_CONTRACT <= 0:
        return MAX_CONTRACTS_HARD, f"no margin configured — backstop {MAX_CONTRACTS_HARD}"
    usable = e * MARGIN_USAGE_PCT / 100.0
    affordable = int(usable // MARGIN_PER_CONTRACT)
    ceiling = max(0, min(affordable, MAX_CONTRACTS_HARD))
    return ceiling, (f"{ceiling} affordable = {MARGIN_USAGE_PCT:g}% of ${e:,.2f} "
                     f"(${usable:,.2f}) / ${MARGIN_PER_CONTRACT:,.2f} margin")


def size_for_stop(stop_points, equity=None) -> dict:
    """Contract count with the constraint that produced it named.

    Contracts follow from the risk budget: whatever 3% of equity buys at this
    stop. Margin can still bind on very tight stops, and when it does the trade
    risks LESS than the budget — so which limit governed is reported rather than
    assumed. "Risking 3%" and "believing you are" should never be confused.
    """
    try:
        sp = float(stop_points)
    except (TypeError, ValueError):
        return {"quantity": 0, "governed_by": "invalid_stop", "detail": "stop not numeric"}
    if sp <= 0 or sp > MAX_STOP_POINTS + 1e-9:
        return {"quantity": 0, "governed_by": "stop_cap",
                "detail": f"stop {sp} outside (0, {MAX_STOP_POINTS}]"}

    budget, budget_why = risk_budget(equity)
    ceiling, ceiling_why = contract_ceiling(equity)
    wanted = int(budget // (sp * POINT_VALUE))       # floor — never over budget
    qty = max(0, min(wanted, ceiling))
    governed = "margin" if wanted > ceiling else "risk_budget"
    return {"quantity": qty, "wanted": wanted, "ceiling": ceiling,
            "governed_by": governed,
            "detail": (f"budget {budget_why} wants {wanted} at {sp}pt; "
                       f"ceiling {ceiling_why} -> {qty} ({governed})"),
            "risk_at_stop": round(qty * sp * POINT_VALUE, 2)}


def contracts_for_stop(stop_points, equity=None) -> int:
    """RISK-BASED size: the largest whole contract count whose worst-case loss
    (stop_points x $POINT_VALUE) stays within the risk budget, capped at
    MAX_CONTRACTS. Returns 0 for a non-positive stop or a stop beyond the cap
    (-> no trade). Never rounds up; risk is never allowed to exceed the budget.

    `equity` compounds the budget; omitted, the flat MAX_RISK_DOLLARS applies.
    """
    try:
        sp = float(stop_points)
    except (TypeError, ValueError):
        return 0
    if sp <= 0 or sp > MAX_STOP_POINTS + 1e-9:
        return 0
    return size_for_stop(stop_points, equity)["quantity"]


def check_quantity(qty, equity=None) -> tuple:
    """Validate a RISK-SIZED quantity: a whole number in [1, ceiling].

    The ceiling is what the ACCOUNT CAN MARGIN at this equity, not a fixed 30 —
    a fixed number here would reject compounded sizes the risk rule legitimately
    produced. Omitting equity keeps the legacy fixed ceiling for existing callers.
    Zero/negative/fractional/over-ceiling are rejected, never auto-adjusted.
    """
    ceiling, ceiling_why = contract_ceiling(equity)
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
    if q > ceiling:
        return False, f"quantity {q} exceeds what the account can margin: {ceiling_why}"
    return True, f"quantity {q} (1..{ceiling})"


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
                 realized_daily_loss: float, equity=None) -> RiskDecision:
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

    budget, budget_why = risk_budget(equity)
    ceiling, ceiling_why = daily_loss_ceiling(equity)
    sizing = size_for_stop(stop.stop_distance, equity)
    warnings.append(f"risk budget {budget_why}")
    warnings.append(f"sizing {sizing['detail']}")

    # A budget above the daily ceiling is an incoherent SETTING, but not
    # necessarily an untradeable one: the contract ceiling often truncates actual
    # risk well below the budget, and the real test below uses actual risk. Warn
    # so the misconfiguration is visible; let the arithmetic decide.
    if budget > ceiling + 1e-9:
        warnings.append(
            f"CONFIG: per-trade budget ({budget_why}) exceeds the daily ceiling "
            f"({ceiling_why}) — only trades the contract ceiling truncates below "
            f"{ceiling:.2f} can be authorized. Raise DAILY_LOSS_PCT_OF_EQUITY.")

    qty = sizing["quantity"]
    ok_q, why_q = check_quantity(qty, equity)
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
    if projected > ceiling + 1e-9:
        return RiskDecision(False,
                            f"daily-loss ceiling: realized {realized_daily_loss} + risk "
                            f"{gross_risk} + costs {costs:.2f} = {projected:.2f} > "
                            f"{ceiling:.2f} ({ceiling_why})",
                            quantity=qty, stop_price=stop.stop_price, target_price=tgt,
                            stop_distance=stop.stop_distance, gross_risk=gross_risk,
                            gross_reward=gross_reward, reward_to_risk=rr,
                            modeled_costs=costs, commission_known=known, warnings=warnings)

    return RiskDecision(True, f"risk approved for {qty} contracts",
                        quantity=qty, stop_price=stop.stop_price, target_price=tgt,
                        stop_distance=stop.stop_distance, gross_risk=gross_risk,
                        gross_reward=gross_reward, reward_to_risk=rr,
                        modeled_costs=costs, commission_known=known, warnings=warnings)
