"""Phase 5 — MNQ contract resolution.

Resolves the EXACT active MNQ futures expiry from platform-provided instrument
candidates. It never fabricates an expiry and never falls back to a continuous
or full-size (NQ) symbol.

MNQ (like NQ) lists quarterly: March(H), June(M), September(U), December(Z),
expiring on the third Friday of the contract month. The "active" contract is
the front quarter that has not yet passed its roll boundary.

This module resolves from evidence the bridge supplies. When no candidates are
supplied it returns an UNRESOLVED result (fail closed) rather than guessing.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from integrations.ninjatrader.instrument_spec import (
    InstrumentSpec, CANONICAL_SYMBOL, DENIED_ROOTS,
    EXPECTED_TICK_SIZE, EXPECTED_POINT_VALUE, EXPECTED_TICK_VALUE,
)

QUARTERLY_MONTHS = {3: "H", 6: "M", 9: "U", 12: "Z"}
MONTH_BY_CODE = {v: k for k, v in QUARTERLY_MONTHS.items()}

# Default rollover danger window (calendar days before expiry) within which a
# fresh entry on the front month is discouraged. Advisory unless policy denies.
ROLLOVER_WARN_DAYS = 8


class ContractResolutionError(ValueError):
    pass


def _third_friday(year: int, month: int) -> _dt.date:
    d = _dt.date(year, month, 1)
    # weekday(): Mon=0 .. Fri=4
    first_friday_offset = (4 - d.weekday()) % 7
    first_friday = 1 + first_friday_offset
    return _dt.date(year, month, first_friday + 14)


@dataclass
class ContractCandidate:
    """One instrument the platform reports as available."""
    instrument_name: str          # e.g. "MNQ 09-26"
    expiry_month: Optional[int] = None    # 1..12
    expiry_year: Optional[int] = None     # 4-digit
    tick_size: Optional[float] = None
    point_value: Optional[float] = None

    def root(self) -> str:
        return str(self.instrument_name).upper().split(" ")[0].strip()


@dataclass
class ResolutionResult:
    resolved: bool
    reason: str
    spec: Optional[InstrumentSpec] = None
    rollover_state: str = "unknown"
    warnings: list = field(default_factory=list)
    rejected: list = field(default_factory=list)   # (name, why)

    def to_dict(self) -> dict:
        return {
            "resolved": self.resolved,
            "reason": self.reason,
            "rollover_state": self.rollover_state,
            "warnings": self.warnings,
            "rejected": [{"instrument": n, "why": w} for n, w in self.rejected],
            "spec": self.spec.to_dict() if self.spec else None,
        }


def _looks_continuous(name: str) -> bool:
    """A continuous/merged symbol has no explicit expiry (e.g. "MNQ", "MNQ ##-##",
    or a name ending in a continuous marker)."""
    n = str(name).strip().upper()
    if n == CANONICAL_SYMBOL:
        return True
    if "##" in n:
        return True
    if n.endswith(" CONTINUOUS") or n.endswith("~"):
        return True
    return False


def resolve_active_mnq(candidates: list,
                       as_of: Optional[_dt.date] = None,
                       rollover_warn_days: int = ROLLOVER_WARN_DAYS,
                       data_connection: str = "",
                       order_connection: str = "Sim101",
                       provenance: str = "bridge_instrument_list") -> ResolutionResult:
    """Pick the exact front-quarter MNQ expiry from `candidates`.

    Fails closed: empty candidates -> UNRESOLVED. Only MNQ quarterly contracts
    with an explicit future expiry are eligible. NQ and continuous symbols are
    recorded in `rejected` and never selected.
    """
    as_of = as_of or _dt.date.today()
    result = ResolutionResult(resolved=False, reason="no candidates supplied")

    if not candidates:
        return result

    eligible = []  # (expiry_date, candidate)
    for c in candidates:
        name = c.instrument_name
        root = c.root()
        if root in DENIED_ROOTS:
            result.rejected.append((name, f"denied full-size root {root!r} (NQ)"))
            continue
        if root != CANONICAL_SYMBOL:
            result.rejected.append((name, f"root {root!r} is not {CANONICAL_SYMBOL!r}"))
            continue
        if _looks_continuous(name):
            result.rejected.append((name, "continuous/merged symbol — not tradable as an expiry"))
            continue
        if not c.expiry_month or not c.expiry_year:
            result.rejected.append((name, "missing explicit expiry month/year"))
            continue
        if c.expiry_month not in QUARTERLY_MONTHS:
            result.rejected.append((name, f"non-quarterly month {c.expiry_month}"))
            continue
        expiry_date = _third_friday(c.expiry_year, c.expiry_month)
        if expiry_date < as_of:
            result.rejected.append((name, f"expired {expiry_date.isoformat()}"))
            continue
        eligible.append((expiry_date, c))

    if not eligible:
        result.reason = "no eligible non-expired MNQ quarterly candidate"
        return result

    eligible.sort(key=lambda t: t[0])
    expiry_date, chosen = eligible[0]
    days_to_expiry = (expiry_date - as_of).days

    if days_to_expiry <= rollover_warn_days:
        rollover_state = "rollover_window"
        result.warnings.append(
            f"{chosen.instrument_name} is {days_to_expiry}d from expiry "
            f"({expiry_date.isoformat()}) — within {rollover_warn_days}d rollover window")
        # If a later eligible quarter exists, surface it as the roll target.
        if len(eligible) > 1:
            result.warnings.append(
                f"roll target available: {eligible[1][1].instrument_name}")
    else:
        rollover_state = "active"

    tick = chosen.tick_size if chosen.tick_size is not None else EXPECTED_TICK_SIZE
    pv = chosen.point_value if chosen.point_value is not None else EXPECTED_POINT_VALUE
    tick_value = round(tick * pv, 10)

    spec = InstrumentSpec(
        provider_symbol=chosen.instrument_name,
        ninjatrader_name=chosen.instrument_name,
        expiry=f"{chosen.expiry_year:04d}-{chosen.expiry_month:02d}",
        tick_size=tick,
        point_value=pv,
        tick_value=tick_value,
        rollover_state=rollover_state,
        resolver_provenance=(f"{provenance}; front-quarter of "
                             f"{len(eligible)} eligible; expiry {expiry_date.isoformat()}; "
                             f"{days_to_expiry}d to expiry; as_of {as_of.isoformat()}"),
        data_connection=data_connection,
        order_connection=order_connection,
    )
    problems = spec.validate()
    if problems:
        result.reason = "resolved candidate failed spec validation: " + "; ".join(problems)
        result.rollover_state = rollover_state
        return result

    result.resolved = True
    result.reason = f"resolved active MNQ expiry {spec.ninjatrader_name}"
    result.spec = spec
    result.rollover_state = rollover_state
    return result
