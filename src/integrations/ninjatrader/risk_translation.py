"""Phase 13 — Risk translation: QQQ shares -> MNQ contracts.

The organism's risk governor and $500 ceiling remain the authority. This module
only translates a price-distance stop into a per-contract dollar risk for MNQ
and enforces the whole-contract, ceiling-bounded quantity rules.

    risk_per_contract = |entry - stop| * point_value + commission + slippage

Foundation rules:
  * maximum quantity = 1 contract; minimum = 1; no fractional contracts.
  * a zero-contract result is NEVER rounded up to 1.
  * if authorized risk cannot support even 1 contract, the trade is REJECTED.
  * commission/slippage are configurable; UNKNOWN commission is LABELLED, not
    silently assumed zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from integrations.ninjatrader import MAX_CONTRACTS_FOUNDATION
from integrations.ninjatrader.instrument_spec import InstrumentSpec


@dataclass
class CostModel:
    """Configurable, honestly-labelled cost assumptions. Sim101 fills must be
    MEASURED separately later; these are modeled placeholders."""
    commission_per_contract: Optional[float] = None   # None = UNKNOWN (labelled)
    slippage_ticks: float = 1.0                        # modeled entry+stop slippage in ticks
    source: str = "modeled_placeholder"

    def commission_known(self) -> bool:
        return self.commission_per_contract is not None

    def commission_value(self) -> float:
        return float(self.commission_per_contract) if self.commission_known() else 0.0


@dataclass
class RiskAssessment:
    approved: bool
    reason: str
    quantity: int
    risk_per_contract: float
    total_risk: float
    stop_ticks: float
    commission_known: bool
    warnings: list


def risk_per_contract(spec: InstrumentSpec, entry_price: float, stop_price: float,
                      cost: Optional[CostModel] = None) -> float:
    cost = cost or CostModel()
    distance = abs(float(entry_price) - float(stop_price))
    price_risk = distance * spec.point_value
    slippage_dollars = cost.slippage_ticks * spec.tick_value
    return price_risk + cost.commission_value() + slippage_dollars


def assess(spec: InstrumentSpec,
           entry_price: float,
           stop_price: float,
           authorized_risk: float,
           cost: Optional[CostModel] = None,
           requested_qty: int = 1) -> RiskAssessment:
    """Assess a single-contract MNQ entry against the authorized risk ceiling."""
    cost = cost or CostModel()
    warnings = []
    if not cost.commission_known():
        warnings.append("commission UNKNOWN — modeled as 0 but flagged; do not "
                        "treat as validated until Sim101 fills are measured")

    distance = abs(float(entry_price) - float(stop_price))
    if distance <= 0:
        return RiskAssessment(False, "entry and stop are equal — no defined risk distance",
                              0, 0.0, 0.0, 0.0, cost.commission_known(), warnings)

    stop_ticks = distance / spec.tick_size
    rpc = risk_per_contract(spec, entry_price, stop_price, cost)

    # Foundation: never size above 1, never below 1, never fractional.
    if requested_qty != 1:
        return RiskAssessment(False,
                              f"requested_qty {requested_qty} — foundation permits exactly 1",
                              0, rpc, 0.0, stop_ticks, cost.commission_known(), warnings)

    if rpc > float(authorized_risk):
        # 1 contract already exceeds the ceiling -> reject (never round to 0-and-up games).
        return RiskAssessment(
            False,
            f"1 MNQ contract risks ${rpc:.2f} > authorized ${float(authorized_risk):.2f} "
            f"— reject (do not round down to 0 then up to 1)",
            0, rpc, 0.0, stop_ticks, cost.commission_known(), warnings)

    qty = min(1, MAX_CONTRACTS_FOUNDATION)
    return RiskAssessment(True,
                          f"1 MNQ contract risks ${rpc:.2f} within authorized "
                          f"${float(authorized_risk):.2f}",
                          qty, rpc, rpc * qty, stop_ticks, cost.commission_known(), warnings)
