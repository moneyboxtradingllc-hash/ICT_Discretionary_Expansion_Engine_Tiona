"""Production doctrine telemetry and startup guards.

Prints the resolved authoritative doctrine at every production startup, and
REFUSES to start when the active configuration contradicts it. The refusals
exist because this repository has already shipped each of them by accident:

  * a 10-point ceiling — `build_bracket` defaulted to the SMOKE value, so the
    resolved production ceiling was a smoke artifact until 2026-08-05
  * a 1-contract cap — likewise the smoke size, standing in for adaptive sizing
  * Topstep Position Brackets as protection authority — the venue's own bracket
    engine, which is not the bot's thesis

Printing the doctrine is not decoration: an operator who cannot see which
numbers are in force cannot tell a correct configuration from a smoke leftover.
"""
from __future__ import annotations

from broker.topstepx_combine_risk import (
    ABSOLUTE_MAX_STOP_POINTS, FIXED_COST_SOURCE,
    FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT, FIXED_ROUND_TRIP_FEES_PER_CONTRACT,
    MEASURED_FIXED_ROUND_TRIP_TOTAL, PREFERRED_MAX_STOP_POINTS,
    PRODUCTION_MAX_CONTRACTS, PRODUCTION_MAX_RISK_USD, SLIPPAGE_RESERVE_TICKS_PER_SIDE,
    SLIPPAGE_SOURCE,
)


class DoctrineConflict(RuntimeError):
    """Active configuration contradicts the authoritative doctrine."""


def resolve(slippage_ledger=None) -> dict:
    sample = (slippage_ledger.sample_status() if slippage_ledger is not None
              else {"reliable_observations": 0, "required_observations": 20,
                    "round_trips": 0, "required_round_trips": 10, "sufficient": False})
    return {
        "slippage_sample": sample,
        "production_max_risk_usd": PRODUCTION_MAX_RISK_USD,
        "preferred_max_stop_points": PREFERRED_MAX_STOP_POINTS,
        "absolute_max_stop_points": ABSOLUTE_MAX_STOP_POINTS,
        "extended_volatility_range": (PREFERRED_MAX_STOP_POINTS, ABSOLUTE_MAX_STOP_POINTS),
        "max_contracts": PRODUCTION_MAX_CONTRACTS,
        "stop_authority": "exact structural invalidation",
        "target_authority": "current Luna-selected liquidity objective",
        "bracket_authority": "bot-authored BracketGeometry",
        # DOCTRINE DECLARATION, not an account measurement. Named so nobody
        # reads it as evidence about the venue again -- see
        # `topstepx_protection_authority` for the account-state proposition.
        "topstep_position_brackets": "disabled",
        "topstep_position_brackets_source": "doctrine_declaration_not_measured",
        "account_protection_state_authority": "operator_attestation_required",
        "smoke_constants_active": False,
        "slippage_capture": "WIRED",
        "automatic_reserve_updates": "disabled",
        "fixed_costs": {"fees_round_trip": FIXED_ROUND_TRIP_FEES_PER_CONTRACT,
                        "commissions_round_trip": FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT,
                        "total_round_trip": MEASURED_FIXED_ROUND_TRIP_TOTAL,
                        "source": FIXED_COST_SOURCE},
        "slippage": {"reserve_ticks_per_side": SLIPPAGE_RESERVE_TICKS_PER_SIDE,
                     "measured": False, "source": SLIPPAGE_SOURCE},
    }


def assert_no_conflict(d: dict = None) -> dict:
    """Refuse startup on any configuration that contradicts the doctrine."""
    d = d or resolve()
    absolute = float(d["absolute_max_stop_points"])
    preferred = float(d["preferred_max_stop_points"])
    risk = float(d["production_max_risk_usd"])

    if absolute <= 10.0:
        raise DoctrineConflict(
            f"absolute stop ceiling resolves to {absolute:g} points — that is the SMOKE "
            f"value, not production doctrine ({ABSOLUTE_MAX_STOP_POINTS:g})")
    if absolute < preferred:
        raise DoctrineConflict(
            f"absolute ceiling {absolute:g} is below the preferred range {preferred:g}")
    # RISK-DOCTRINE-MIGRATION (2026-08-20). These four bounds were LITERALS --
    # 40.0, 35.0, 250.0, 15 -- restating constants this module already imports.
    # The 2026-08-20 ceiling migration to 50.0 would therefore have been refused
    # at startup by a guard whose whole purpose is to detect configuration that
    # contradicts doctrine, while the doctrine itself had moved. A mirror that
    # can disagree with its source is the same defect as a duplicated model
    # identity, and it is fixed the same way: compare against the owner.
    if absolute > ABSOLUTE_MAX_STOP_POINTS:
        raise DoctrineConflict(
            f"absolute ceiling {absolute:g} exceeds the doctrinal maximum of "
            f"{ABSOLUTE_MAX_STOP_POINTS:g} points")
    if preferred != PREFERRED_MAX_STOP_POINTS:
        raise DoctrineConflict(
            f"preferred ceiling resolves to {preferred:g}, doctrine is "
            f"{PREFERRED_MAX_STOP_POINTS:g} points")
    if risk > PRODUCTION_MAX_RISK_USD:
        raise DoctrineConflict(
            f"risk cap {risk:g} exceeds the ${PRODUCTION_MAX_RISK_USD:g} doctrine")
    if int(d["max_contracts"]) > PRODUCTION_MAX_CONTRACTS:
        raise DoctrineConflict(
            f"contract cap {d['max_contracts']} exceeds {PRODUCTION_MAX_CONTRACTS} MNQ")
    # PROTECTION-AUTHORITY-1 (2026-08-18). This check used to compare
    # `resolve()`'s own hardcoded "disabled" against itself, and both production
    # callers invoke `assert_no_conflict()` with no argument -- so IT COULD NOT
    # FAIL. It was already false in practice: account 33333333 rejected
    # order-attached brackets with errorCode=2 "Brackets cannot be used with
    # Position Brackets", proving the venue engine was ENABLED while startup
    # passed happily.
    #
    # The value is a DECLARATION of doctrine (the bot owns protection), so the
    # guard still refuses a contradictory declaration. What it may no longer do
    # is imply the account was measured -- `/api/Account/search` publishes six
    # fields and none is a bracket setting. The account-state proposition now
    # belongs to `topstepx_protection_authority`, which requires a dated,
    # account-bound operator attestation and refuses when it is absent.
    if str(d["topstep_position_brackets"]).lower() != "disabled":
        raise DoctrineConflict(
            "Topstep Position Brackets are not a production protection authority")
    if d["smoke_constants_active"]:
        raise DoctrineConflict("smoke constants are active in a production path")
    return d


def render(d: dict = None) -> str:
    d = d or resolve()
    lo, hi = d["extended_volatility_range"]
    fx, sl = d["fixed_costs"], d["slippage"]
    sm = d.get("slippage_sample") or {"reliable_observations": 0,
                                      "required_observations": 20,
                                      "round_trips": 0, "required_round_trips": 10,
                                      "sufficient": False}
    return "\n".join([
        "=" * 70,
        "PRODUCTION DOCTRINE (resolved, authoritative)",
        "=" * 70,
        f"  PRODUCTION MAX RISK          : ${d['production_max_risk_usd']:,.2f} all-in",
        f"  PREFERRED MAX STRUCTURAL STOP: {d['preferred_max_stop_points']:.2f} points",
        f"  ABSOLUTE MAX STRUCTURAL STOP : {d['absolute_max_stop_points']:.2f} points",
        f"  EXTENDED VOLATILITY RANGE    : >{lo:.2f} through {hi:.2f} points",
        f"  MAX CONTRACTS                : {d['max_contracts']} MNQ",
        f"  STOP AUTHORITY               : {d['stop_authority']}",
        f"  TARGET AUTHORITY             : {d['target_authority']}",
        f"  BRACKET AUTHORITY            : {d['bracket_authority']}",
        f"  TOPSTEP POSITION BRACKETS    : {d['topstep_position_brackets']}",
        f"  SMOKE CONSTANTS              : {'active' if d['smoke_constants_active'] else 'not active'}",
        "  -- cost model --",
        f"  FIXED ROUND-TRIP / CONTRACT  : ${fx['total_round_trip']:.2f} "
        f"(fees ${fx['fees_round_trip']:.2f} + commissions ${fx['commissions_round_trip']:.2f})",
        f"    source                     : {fx['source']}",
        f"  ACTIVE SLIPPAGE RESERVE      : {sl['reserve_ticks_per_side']:g} tick(s) entry + "
        f"{sl['reserve_ticks_per_side']:g} tick(s) exit "
        f"= ${2 * sl['reserve_ticks_per_side'] * 0.5:.2f} per MNQ round trip",
        f"    measured                   : {sl['measured']}",
        f"    source                     : {sl['source']}",
        f"  SLIPPAGE CAPTURE             : {d.get('slippage_capture', 'NOT WIRED')}",
        f"  AUTOMATIC RESERVE UPDATES    : {d.get('automatic_reserve_updates', 'disabled')}",
        f"  SLIPPAGE SAMPLE              : "
        f"{sm['reliable_observations']}/{sm['required_observations']} reliable observations, "
        f"{sm['round_trips']}/{sm['required_round_trips']} round trips",
        f"    reserve revisitable        : {sm['sufficient']} "
        f"(review required regardless)",
        "=" * 70,
    ])


def print_startup_doctrine() -> dict:
    d = assert_no_conflict()
    print(render(d))
    return d
