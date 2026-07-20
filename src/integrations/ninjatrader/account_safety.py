"""Safety Constitution — account & instrument allowlists (fail closed).

This module is the innermost, dependency-free safety kernel. It is the last
line that makes the integration PHYSICALLY incapable of routing to a live
account under the foundation configuration, independent of NinjaTrader's own
Global Simulation Mode (which is a user-controlled GUI safeguard we do not
trust as the only control — defense in depth).

Rules:
  * Account allowlist = {"Sim101"} EXACTLY. Nothing else.
  * Normalization (whitespace/case) may only ever NARROW, never broaden, the
    allowlist. "sim101", " Sim101 " are accepted as Sim101; "Sim1010",
    "Sim101 Live", "Playback101" are rejected.
  * Blank / missing / ambiguous / unknown account -> DENY.
  * Instrument allowlist = the single resolved active MNQ expiry. NQ denied.
  * Quantity ceiling = 1 contract, whole positive integer only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from integrations.ninjatrader import MAX_CONTRACTS_FOUNDATION
from integrations.ninjatrader.instrument_spec import DENIED_ROOTS, CANONICAL_SYMBOL

# The ONLY account this integration may ever address in the foundation era.
ALLOWED_ACCOUNTS = frozenset({"Sim101"})


@dataclass
class SafetyDecision:
    allowed: bool
    reason: str
    normalized: Optional[str] = None

    def __bool__(self) -> bool:  # truthy == allowed
        return self.allowed


def _canonical_account(raw) -> Optional[str]:
    """Return the canonical account name if `raw` unambiguously names an
    allowlisted account, else None. Case/space-insensitive match against the
    allowlist ONLY — this can never invent a new allowed name."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    # Reject embedded whitespace ambiguity like "Sim101 Live" up front: only an
    # exact case-insensitive match to an allowlisted name is acceptable.
    for allowed in ALLOWED_ACCOUNTS:
        if stripped.lower() == allowed.lower():
            return allowed
    return None


def check_account(raw_account) -> SafetyDecision:
    """Fail-closed account gate. Only an exact (case/space-normalized) match to
    an allowlisted account passes."""
    canon = _canonical_account(raw_account)
    if canon is None:
        shown = "<blank>" if (raw_account is None or str(raw_account).strip() == "") \
            else repr(raw_account)
        return SafetyDecision(False, f"account {shown} is not allowlisted (allowed: "
                                     f"{sorted(ALLOWED_ACCOUNTS)})", None)
    return SafetyDecision(True, f"account {canon} allowlisted", canon)


def check_instrument(raw_instrument, resolved_expiry_name: Optional[str]) -> SafetyDecision:
    """Fail-closed instrument gate.

    `resolved_expiry_name` is the exact NinjaTrader instrument name of the active
    MNQ expiry (e.g. "MNQ 09-26"). Only that exact instrument passes. Any NQ
    root, blank, or mismatched instrument is denied.
    """
    if raw_instrument is None or not str(raw_instrument).strip():
        return SafetyDecision(False, "instrument is blank/missing", None)
    name = str(raw_instrument).strip()
    root = name.upper().split(" ")[0].strip()

    if root in DENIED_ROOTS:
        return SafetyDecision(False, f"instrument root {root!r} is explicitly DENIED", None)
    if root != CANONICAL_SYMBOL:
        return SafetyDecision(False,
                              f"instrument root {root!r} is not {CANONICAL_SYMBOL!r}", None)
    if not resolved_expiry_name or not str(resolved_expiry_name).strip():
        return SafetyDecision(False, "no resolved MNQ expiry — contract uncertainty denies", None)
    if name.upper() != str(resolved_expiry_name).strip().upper():
        return SafetyDecision(False,
                              f"instrument {name!r} != resolved active expiry "
                              f"{resolved_expiry_name!r}", None)
    return SafetyDecision(True, f"instrument {name} matches resolved active MNQ expiry", name)


def check_quantity(raw_qty) -> SafetyDecision:
    """Fail-closed quantity gate. Positive whole contract, at most the
    foundation ceiling. A zero-contract result must never be rounded up."""
    # Reject bools (bool is an int subclass) and non-numerics.
    if isinstance(raw_qty, bool) or raw_qty is None:
        return SafetyDecision(False, f"quantity {raw_qty!r} is not a whole contract count", None)
    try:
        as_float = float(raw_qty)
    except (TypeError, ValueError):
        return SafetyDecision(False, f"quantity {raw_qty!r} is not numeric", None)
    if as_float != int(as_float):
        return SafetyDecision(False, f"fractional quantity {raw_qty!r} not permitted", None)
    qty = int(as_float)
    if qty < 1:
        return SafetyDecision(False, f"quantity {qty} < 1 (zero/negative never rounds up)", None)
    if qty > MAX_CONTRACTS_FOUNDATION:
        return SafetyDecision(False,
                              f"quantity {qty} exceeds foundation ceiling "
                              f"{MAX_CONTRACTS_FOUNDATION}", None)
    return SafetyDecision(True, f"quantity {qty} within ceiling", str(qty))


@dataclass
class GateInputs:
    account: object = None
    instrument: object = None
    resolved_expiry_name: Optional[str] = None
    quantity: object = None
    connection_healthy: Optional[bool] = None
    account_state_known: Optional[bool] = None
    position_state_known: Optional[bool] = None
    contract_expiry_certain: Optional[bool] = None


def evaluate_fresh_entry(inp: GateInputs) -> SafetyDecision:
    """Conjunction of every fail-closed gate that governs a FRESH entry.

    Uncertainty on ANY of connection / account-state / position-state /
    contract-expiry denies fresh entries. (Managing an EXISTING position is a
    different path and is NOT gated here — see execution_adapter.)
    """
    acct = check_account(inp.account)
    if not acct:
        return acct
    instr = check_instrument(inp.instrument, inp.resolved_expiry_name)
    if not instr:
        return instr
    qty = check_quantity(inp.quantity)
    if not qty:
        return qty

    # Any None (unknown) or False (unhealthy) on the certainty flags denies.
    for flag_name, flag_val, ok_msg in (
        ("connection_healthy", inp.connection_healthy, "connection healthy"),
        ("account_state_known", inp.account_state_known, "account state known"),
        ("position_state_known", inp.position_state_known, "position state known"),
        ("contract_expiry_certain", inp.contract_expiry_certain, "expiry certain"),
    ):
        if flag_val is not True:
            return SafetyDecision(False, f"fresh-entry denied: {flag_name} is "
                                         f"{'unknown' if flag_val is None else flag_val}",
                                  None)

    return SafetyDecision(True, "all fresh-entry safety gates passed",
                          f"{acct.normalized}/{instr.normalized}/{qty.normalized}")
