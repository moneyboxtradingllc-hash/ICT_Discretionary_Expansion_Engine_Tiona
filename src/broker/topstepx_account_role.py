"""TOPSTEPX-COMBINE-ROLE — venue environment vs operator-declared account role.

These are two different facts and conflating them produced a real misreport on
2026-08-04: the read-only preflight rendered `simulated=true` as
"SIMULATED (practice)", which told the operator his **Trading Combine** was a
Practice Account. It is not. A Trading Combine is simulated too — the flag
describes the ORDER-ROUTING ENVIRONMENT, not what the account is for.

The distinction matters because the two facts carry different consequences:

  VENUE ENVIRONMENT  (from the API, `TradingAccountModel.simulated`)
      Does an order reach a real exchange with real money behind it?
      Authoritative, venue-supplied, never operator-editable.

  ACCOUNT ROLE       (operator-declared, TOPSTEPX_ACCOUNT_ROLE)
      What is this account FOR? A Combine has evaluation rules, a trailing
      drawdown and consequences for a breach that a throwaway practice account
      does not. Reporting and policy need this; routing must never see it.

THE HARD RULE: role is REPORTING AND POLICY ONLY. It can never select, replace
or override the account pinned by id + fingerprint. `resolve_role()` takes no
account argument and returns no identifier for exactly that reason — there is
no code path through this module that could influence routing.
"""
from __future__ import annotations

import os

TRADING_COMBINE = "TRADING_COMBINE"
FUNDED = "FUNDED"
PRACTICE = "PRACTICE"
UNDECLARED = "UNDECLARED"

_KNOWN_ROLES = (TRADING_COMBINE, FUNDED, PRACTICE, UNDECLARED)

# Roles whose breach has consequences beyond the balance — an evaluation ends,
# a payout is lost. These get the loud treatment in reports.
_CONSEQUENTIAL = (TRADING_COMBINE, FUNDED)


def resolve_role(env: "dict | None" = None) -> str:
    """The operator's declared role for the pinned account.

    Takes no account and returns no identifier — by construction this cannot
    participate in account selection. An unrecognized value degrades to
    UNDECLARED rather than raising: a typo in a reporting label must never stop
    a preflight that is otherwise sound.
    """
    # `env is not None`, not `env or ...` — an EMPTY dict is falsy, so the truthy
    # form silently fell through to the real process environment and reported a
    # configured role for a caller that explicitly passed none.
    getenv = (env if env is not None else os.environ).get
    raw = (getenv("TOPSTEPX_ACCOUNT_ROLE") or "").strip().upper().replace("-", "_").replace(" ", "_")
    return raw if raw in _KNOWN_ROLES else (UNDECLARED if not raw else UNDECLARED)


def venue_environment(simulated: bool) -> str:
    """The venue's own answer, rendered without editorial."""
    return "SIMULATED" if simulated else "LIVE"


def describe(simulated: bool, env: "dict | None" = None) -> dict:
    """Two separate lines of evidence, never collapsed into one label."""
    role = resolve_role(env)
    return {
        "venue_environment": venue_environment(simulated),
        "operator_declared_account_role": role,
        "role_is_consequential": role in _CONSEQUENTIAL,
        "role_governs_routing": False,      # invariant, asserted by test
    }


def report_lines(simulated: bool, env: "dict | None" = None) -> list:
    """Human-facing lines for a preflight. Never renders 'SIMULATED PRACTICE'."""
    d = describe(simulated, env)
    lines = [f"Venue environment: {d['venue_environment']}",
             f"Operator-declared account role: {d['operator_declared_account_role']}"]
    if d["venue_environment"] == "LIVE":
        lines.append("*** LIVE ENVIRONMENT — REAL MONEY ***")
    elif d["role_is_consequential"]:
        # Simulated does not mean consequence-free. A Combine breach ends the
        # evaluation whether or not the dollars were real.
        lines.append("NOTE: simulated routing, but a Combine breach has real consequences.")
    return lines
