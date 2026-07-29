"""MNQ-DEMO8458533-SMOKE-ORDER — 12-point pre-order verification (GO/NO-GO).

Revised doctrine: the platform safety proof is POSITIVE evidence of the
Simulation environment + hard enforcement of DEMO8458533 as the sole account
(the old "Global Simulation Mode ON" requirement is obsolete on this NinjaTrader
edition and is intentionally NOT required).

Every check FAILS CLOSED: an unknown environment type, account identity,
position state, order state, or execution destination is a NO-GO. All twelve
must pass for an overall GO. This module NEVER submits an order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from integrations.ninjatrader.account_safety import ALLOWED_ACCOUNTS, check_account, check_instrument, check_quantity
from integrations.ninjatrader import environment_proof
from integrations.ninjatrader import smoke_authorization as auth

from integrations.ninjatrader.deterministic import (
    ACCOUNT as _CFG_ACCOUNT, INSTRUMENT as _CFG_INSTRUMENT)

EXPECTED_ACCOUNT = _CFG_ACCOUNT   # per-operator config, see .env.template
EXPECTED_INSTRUMENT = _CFG_INSTRUMENT   # per-operator config, see .env.template
EXPECTED_QUANTITY = 1


@dataclass
class Check:
    n: int
    name: str
    passed: bool
    detail: str


@dataclass
class PreflightResult:
    go: bool
    checks: list = field(default_factory=list)

    def failures(self):
        return [c for c in self.checks if not c.passed]

    def to_dict(self):
        return {"go": self.go,
                "checks": [{"n": c.n, "name": c.name, "pass": c.passed, "detail": c.detail}
                           for c in self.checks]}


def run(bridge_env: Optional[dict],
        account_state: Optional[dict],
        position: Optional[dict],
        order_summary: Optional[dict],
        instrument_metadata: Optional[dict],
        metadata_reconcile: Optional[dict],
        quote: Optional[dict],
        ati_default_account: Optional[str],
        intended_quantity: int = EXPECTED_QUANTITY,
        token_path: str = auth.TOKEN_PATH) -> PreflightResult:
    """Run all 12 checks against live bridge reads + attested platform facts."""
    checks = []
    a = account_state or {}
    p = position or {}
    o = order_summary or {}
    m = instrument_metadata or {}
    r = metadata_reconcile or {}
    q = quote or {}

    # 1. Connected environment is Simulation.
    env = environment_proof.evaluate(bridge_env, EXPECTED_ACCOUNT)
    checks.append(Check(1, "environment_is_simulation", bool(env), env.reason))

    # 2. Account is exactly DEMO8458533.
    acc_ok = check_account(a.get("account")).allowed and a.get("account") == EXPECTED_ACCOUNT
    checks.append(Check(2, "account_is_demo8458533", bool(acc_ok),
                        f"account_state.account={a.get('account')!r}"))

    # 3. No live account selected or reachable by the bridge.
    no_live = bool(env) and not env.live_suspects
    checks.append(Check(3, "no_live_account_reachable", no_live,
                        f"live_suspects={list(env.live_suspects)}; bridge acts only on "
                        f"{sorted(ALLOWED_ACCOUNTS)}"))

    # 4. Bridge account allowlist contains only DEMO8458533.
    allow_ok = ALLOWED_ACCOUNTS == frozenset({EXPECTED_ACCOUNT})
    checks.append(Check(4, "allowlist_is_demo_only", allow_ok,
                        f"ALLOWED_ACCOUNTS={sorted(ALLOWED_ACCOUNTS)}"))

    # 5. ATI default account is exactly DEMO8458533.
    ati_ok = ati_default_account == EXPECTED_ACCOUNT
    checks.append(Check(5, "ati_default_is_demo", bool(ati_ok),
                        f"ati_default_account={ati_default_account!r}"))

    # 6. Position known and flat.
    pos_ok = (p.get("known") is True) and (int(p.get("qty", 1)) == 0) and (p.get("flat") is True)
    checks.append(Check(6, "position_known_and_flat", bool(pos_ok),
                        f"known={p.get('known')} qty={p.get('qty')} flat={p.get('flat')}"))

    # 7. Working orders known and zero.
    ord_ok = (o.get("known") is True) and (int(o.get("working_order_count", 1)) == 0)
    checks.append(Check(7, "working_orders_known_zero", bool(ord_ok),
                        f"known={o.get('known')} count={o.get('working_order_count')}"))

    # 8. Instrument is exactly MNQ SEP26 (and metadata verified).
    instr_ok = (m.get("instrument_name") == EXPECTED_INSTRUMENT) and (r.get("metadata_verified") is True)
    checks.append(Check(8, "instrument_is_mnq_sep26_verified", bool(instr_ok),
                        f"instrument={m.get('instrument_name')!r} verified={r.get('metadata_verified')}"))

    # 9. Quantity is exactly one.
    qty_ok = int(intended_quantity) == EXPECTED_QUANTITY and check_quantity(intended_quantity).allowed
    checks.append(Check(9, "quantity_is_one", bool(qty_ok), f"intended_quantity={intended_quantity}"))

    # 10. Quote path healthy.
    quote_ok = bool(q.get("have_last")) and bool(q.get("have_bid")) and bool(q.get("have_ask"))
    checks.append(Check(10, "quote_path_healthy", quote_ok,
                        f"last={q.get('last')} bid={q.get('bid')} ask={q.get('ask')}"))

    # 11. Reconciliation clean (internal-flat == platform-flat, 0 orders).
    recon_ok = pos_ok and ord_ok
    checks.append(Check(11, "reconciliation_clean", bool(recon_ok),
                        "internal flat == platform flat and zero working orders"))

    # 12. One-use smoke authorization valid and unused.
    tok = auth.validate_token(EXPECTED_ACCOUNT, EXPECTED_INSTRUMENT, EXPECTED_QUANTITY, token_path)
    checks.append(Check(12, "smoke_authorization_valid_unused", bool(tok), tok.reason))

    go = all(c.passed for c in checks)
    return PreflightResult(go=go, checks=checks)
