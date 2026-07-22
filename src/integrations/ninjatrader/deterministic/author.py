"""deterministic_sim_author — explicit-predicate trade authorship.

Evaluates the 20 required mechanical conditions. A trade is authorized ONLY when
every condition passes; ANY contradiction, unknown, or directional disagreement
is NO TRADE. Signals are never averaged through a score. This author never calls
the AI Brain / OpenAI and always labels its output mode+author.

`mechanical_facts` is produced upstream by running the organism's REAL mechanical
witnesses on an MNQ snapshot. Missing/unknown facts fail closed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from integrations.ninjatrader.deterministic import MODE, AUTHOR, QUANTITY
from integrations.ninjatrader.deterministic import risk as R

LONG, SHORT = "long", "short"
_REQUIRED_FACT_KEYS = (
    "setup_family", "direction", "qualification_direction", "playbook_direction",
    "decision_direction", "liquidity_evidence", "structural_evidence",
    "displacement_evidence", "trigger_confirmed", "protected_zone_permits",
    "commander_state", "fc0b_permits", "entry_invalidation", "opposing_direction",
    "final_gate_authorizes", "expected_entry",
)


@dataclass
class Check:
    n: int
    name: str
    passed: bool
    detail: str


@dataclass
class AuthorDecision:
    mode: str
    author: str
    authorized: bool
    checks: list = field(default_factory=list)
    direction: Optional[str] = None
    expected_entry: Optional[float] = None
    structural_stop: Optional[float] = None
    target_price: Optional[float] = None
    quantity: int = 0
    risk: Optional[dict] = None

    def blockers(self):
        return [f"{c.n}:{c.name}:{c.detail}" for c in self.checks if not c.passed]

    def to_dict(self):
        return {"mode": self.mode, "author": self.author, "authorized": self.authorized,
                "direction": self.direction, "expected_entry": self.expected_entry,
                "structural_stop": self.structural_stop, "target_price": self.target_price,
                "quantity": self.quantity, "risk": self.risk,
                "checks": [{"n": c.n, "name": c.name, "pass": c.passed, "detail": c.detail}
                           for c in self.checks]}


def _facts_complete(f: dict) -> Optional[str]:
    for k in _REQUIRED_FACT_KEYS:
        if k not in f:
            return f"missing mechanical fact {k!r}"
        if f[k] is None and k not in ("opposing_direction",):
            return f"unknown mechanical fact {k!r} (fail closed)"
    return None


def evaluate(mechanical_facts: Optional[dict], *, account_known: bool,
             position_known: bool, orders_known: bool, reconciliation_ok: bool,
             realized_daily_loss: float, can_enter: bool,
             can_enter_reason: str = "") -> AuthorDecision:
    d = AuthorDecision(MODE, AUTHOR, authorized=False)
    f = mechanical_facts or {}

    incomplete = _facts_complete(f)
    if incomplete:
        d.checks.append(Check(0, "mechanical_facts_present", False, incomplete))
        return d

    direction = str(f.get("direction", "")).lower()
    entry = f.get("expected_entry")
    invalidation = f.get("entry_invalidation")

    # Risk assessment (stop side/cap + target + 15-contract risk + daily ceiling).
    _valid_dir_prices = direction in (LONG, SHORT) and entry is not None and invalidation is not None
    _stop = (R.assess_structural_stop(direction, float(entry), float(invalidation))
             if _valid_dir_prices else None)
    risk = (R.assess_trade(direction, float(entry), float(invalidation), realized_daily_loss)
            if _valid_dir_prices else None)

    def _dir_agree(k):
        return str(f.get(k, "")).lower() == direction and direction in (LONG, SHORT)

    checks = [
        Check(1, "valid_setup_family", bool(f.get("setup_family")), str(f.get("setup_family"))),
        Check(2, "direction_explicit", direction in (LONG, SHORT), direction or "none"),
        Check(3, "qualification_agrees", _dir_agree("qualification_direction"),
              str(f.get("qualification_direction"))),
        Check(4, "playbook_agrees", _dir_agree("playbook_direction"), str(f.get("playbook_direction"))),
        Check(5, "decision_agrees", _dir_agree("decision_direction"), str(f.get("decision_direction"))),
        Check(6, "liquidity_evidence", f.get("liquidity_evidence") is True, str(f.get("liquidity_evidence"))),
        Check(7, "structural_evidence", f.get("structural_evidence") is True, str(f.get("structural_evidence"))),
        Check(8, "displacement_evidence", f.get("displacement_evidence") is True, str(f.get("displacement_evidence"))),
        Check(9, "trigger_confirmed", f.get("trigger_confirmed") is True, str(f.get("trigger_confirmed"))),
        Check(10, "protected_zone_permits", f.get("protected_zone_permits") is True, str(f.get("protected_zone_permits"))),
        Check(11, "commander_not_standdown",
              str(f.get("commander_state", "")).upper() != "STAND_DOWN", str(f.get("commander_state"))),
        Check(12, "fc0b_permits", f.get("fc0b_permits") is True, str(f.get("fc0b_permits"))),
        Check(13, "entry_invalidation_exists", invalidation is not None, str(invalidation)),
        Check(14, "invalidation_correct_side", bool(_stop and _stop.correct_side),
              _stop.reason if _stop else "no stop"),
        Check(15, f"stop_within_{R.MAX_STOP_POINTS:g}pts",
              bool(_stop and _stop.valid and _stop.stop_distance is not None
                   and _stop.stop_distance <= R.MAX_STOP_POINTS + 1e-9),
              (f"dist={_stop.stop_distance}" if _stop else "no stop")),
        Check(16, "target_valid_correct_side", bool(risk and risk.target_price is not None),
              (f"target={risk.target_price}" if risk else "no target")),
        Check(17, f"{QUANTITY}_contract_risk_fits", bool(risk and risk.approved) and can_enter,
              (risk.reason if risk else "no risk") + f" | session:{can_enter_reason}"),
        Check(18, "account_position_orders_known",
              bool(account_known and position_known and orders_known and reconciliation_ok),
              f"acct={account_known} pos={position_known} ord={orders_known} recon={reconciliation_ok}"),
        Check(19, "final_gate_authorizes", f.get("final_gate_authorizes") is True,
              str(f.get("final_gate_authorizes"))),
        Check(20, "no_opposing_direction",
              f.get("opposing_direction") in (None, "", direction),
              str(f.get("opposing_direction"))),
    ]
    d.checks = checks
    d.direction = direction if direction in (LONG, SHORT) else None
    d.expected_entry = entry
    if risk:
        d.structural_stop = risk.stop_price
        d.target_price = risk.target_price
        d.risk = {"gross_risk": risk.gross_risk, "gross_reward": risk.gross_reward,
                  "reward_to_risk": risk.reward_to_risk, "stop_distance": risk.stop_distance,
                  "approved": risk.approved, "reason": risk.reason}
    d.quantity = QUANTITY if all(c.passed for c in checks) else 0
    d.authorized = all(c.passed for c in checks)
    return d
