"""Is the PRAC lane eligible to ARM? Pure evaluation, no I/O.

PRAC-RELEASE-1 (2026-08-18).

Every gate below is a separate proposition with its own refusal string, because
"preflight failed" at 09:29 with the window open is not an answer anybody can
act on. Facts are gathered by `tools/prac_release_preflight.py` and handed here;
nothing in this module touches a venue, a clock or a disk, so the whole gate set
is testable without a market.

TWO MODES, deliberately.

    PREP    the night before. Everything that CAN be frozen ahead of time.
            A missing session authorization is EXPECTED, not a failure -- it is
            date-bound and belongs on the session morning.

    FINAL   the session morning. Adds today's authorization and live flatness.
            Only FINAL may report ARM_ELIGIBLE.

Neither mode arms anything. `arm_eligible` is a REPORT, and arming stays an
explicit separate operator action -- there is no code path here that flips it.

PRACTICE ONLY. The Combine is refused by identity, not by convention: the whole
machine gets proven on PRAC first, and there is no fall-through.
"""
from __future__ import annotations

import os

PREP = "PREP"
FINAL = "FINAL"


def _env_str(name: str):
    """Exactly what the environment says, or None. Never a fallback identity."""
    v = (os.environ.get(name) or "").strip()
    return v or None


def _env_int(name: str):
    v = _env_str(name)
    try:
        return int(v) if v is not None else None
    except ValueError:
        # A malformed id is NOT the same as an absent one, but both must fail
        # closed: returning None keeps the gate red rather than crashing here.
        return None


def _env_map_int(name: str) -> dict:
    """Parse "id:reason,id:reason" (or bare ids) into {int: reason}."""
    out = {}
    for part in (_env_str(name) or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, reason = part.partition(":")
        try:
            out[int(key.strip())] = reason.strip() or "REFUSED_BY_CONFIGURATION"
        except ValueError:
            continue
    return out


def _env_map_str(name: str) -> dict:
    """Parse "acct:xxxx:reason,..." into {fingerprint: reason}.

    Fingerprints themselves contain a colon, so the reason is split from the
    RIGHT -- splitting from the left would silently truncate every key.
    """
    out = {}
    for part in (_env_str(name) or "").split(","):
        part = part.strip()
        if not part:
            continue
        head, sep, tail = part.rpartition(":")
        if sep and head.count(":") >= 1:
            out[head.strip()] = tail.strip() or "REFUSED_BY_CONFIGURATION"
        else:
            out[part] = "REFUSED_BY_CONFIGURATION"
    return out

#: THE ONE ACCOUNT THIS RELEASE PROFILE PERMITS -- SUPPLIED, NEVER BUILT IN.
#:
#: This used to be a hardcoded account number belonging to one operator. It is
#: now read from the environment so the profile carries no operator's brokerage
#: identity, and so a second operator cannot inherit someone else's account by
#: simply running the code.
#:
#: THERE IS NO DEFAULT, DELIBERATELY. `None` means "identity not stated", and
#: the gates below then FAIL CLOSED -- unset configuration must read as NOT
#: READY, never as permission. A default here would be an account this profile
#: would silently authorize.
PRAC_ACCOUNT_ID = _env_int("PRAC_ACCOUNT_ID")
PRAC_ACCOUNT_FINGERPRINT = _env_str("PRAC_ACCOUNT_FINGERPRINT")

#: Accounts this profile must refuse even when they authenticate, listed as
#: `id: reason` so a mistake names itself instead of failing with a generic
#: mismatch the operator has to decode.
#:
#: Also operator-supplied. A shipped denylist would publish the very account
#: numbers it exists to protect.
#: Format: "id:reason,id:reason"   (ids alone are also accepted)
FORBIDDEN_ACCOUNTS = _env_map_int("PRAC_FORBIDDEN_ACCOUNTS")
#: Format: "acct:xxxx:reason,acct:yyyy:reason"
FORBIDDEN_FINGERPRINTS = _env_map_str("PRAC_FORBIDDEN_FINGERPRINTS")

#: Frozen production risk doctrine. Restated here so preflight compares against
#: named numbers rather than against whatever the module happens to import.
#
# RISK-DOCTRINE-MIGRATION (operator, 2026-08-20): risk $250 -> $350 and the
# absolute ceiling 40.0 -> 50.0. These mirror `topstepx_combine_risk` and must
# move in the SAME commit as it -- a preflight that certifies numbers the engine
# no longer holds is worse than no preflight, because it reports PASS.
EXPECTED_MAX_RISK_USD = 350.0
EXPECTED_MAX_CONTRACTS = 15
EXPECTED_PREFERRED_STOP = 35.0
EXPECTED_ABSOLUTE_STOP = 50.0
EXPECTED_MIN_RR = 1.0


def expected_model() -> str:
    """The production model, from its OWNER -- never a literal here.

    This was hardcoded to `gpt-5.6-terra`, so the operator's 2026-08-19 ruling
    (Luna for the PRAC validation period, Terra reserved for the Combine phase)
    made a correctly-configured lane fail its own preflight. The gate's subject
    is "production runs the authorized model", not "production runs Terra".
    """
    from ai_brain.production_model import PRODUCTION_MODEL
    return PRODUCTION_MODEL


def _gate(name, ok, detail=""):
    return {"gate": name, "ok": bool(ok), "detail": detail}


def evaluate(facts: dict, *, mode: str = PREP) -> dict:
    """Facts in, gates out. `arm_eligible` is only ever True in FINAL mode."""
    f = facts or {}
    gates: list = []

    # ── A. source identity ────────────────────────────────────────────────────
    gates.append(_gate("source_tracked_clean", f.get("tracked_source_clean") is True,
                       f"dirty: {f.get('dirty_tracked_files') or []}"))
    gates.append(_gate("brain_fingerprint_known", bool(f.get("brain_fingerprint")),
                       f"fingerprint {f.get('brain_fingerprint')!r}"))

    # ── B/C. account: the PRAC one, and provably not the others ───────────────
    acct_id, acct_fp = f.get("account_id"), f.get("account_fingerprint")
    try:
        acct_id_int = int(acct_id)
    except (TypeError, ValueError):
        acct_id_int = None
    # FAIL CLOSED ON AN UNSTATED PIN. `None == None` would otherwise be True and
    # an unconfigured install would pass its own identity gate.
    gates.append(_gate("account_pin_configured",
                       PRAC_ACCOUNT_ID is not None
                       and PRAC_ACCOUNT_FINGERPRINT is not None,
                       "set PRAC_ACCOUNT_ID and PRAC_ACCOUNT_FINGERPRINT for "
                       "this install; there is no default account"))
    gates.append(_gate("account_is_prac",
                       PRAC_ACCOUNT_ID is not None and acct_id_int == PRAC_ACCOUNT_ID,
                       f"resolved account {acct_id!r}, expected {PRAC_ACCOUNT_ID}"))
    gates.append(_gate("account_fingerprint_is_prac",
                       PRAC_ACCOUNT_FINGERPRINT is not None
                       and acct_fp == PRAC_ACCOUNT_FINGERPRINT,
                       f"resolved {acct_fp!r}, expected {PRAC_ACCOUNT_FINGERPRINT}"))
    forbidden = FORBIDDEN_ACCOUNTS.get(acct_id_int) or FORBIDDEN_FINGERPRINTS.get(acct_fp)
    gates.append(_gate("not_a_forbidden_account", forbidden is None,
                       f"refused: {forbidden}" if forbidden else ""))
    gates.append(_gate("account_simulated", f.get("simulated") is True,
                       f"simulated={f.get('simulated')!r}"))
    gates.append(_gate("account_can_trade", f.get("can_trade") is True,
                       f"canTrade={f.get('can_trade')!r}"))
    gates.append(_gate("account_visible", f.get("is_visible") is True,
                       f"isVisible={f.get('is_visible')!r}"))

    # ── D. contract ───────────────────────────────────────────────────────────
    gates.append(_gate("contract_resolved", bool(f.get("contract_id")),
                       f"contract {f.get('contract_id')!r}"))

    # ── E. flat. Foreign orders are REPORTED, never silently absorbed ─────────
    gates.append(_gate("flat", int(f.get("open_positions") or 0) == 0,
                       f"{f.get('open_positions')} open position(s)"))
    gates.append(_gate("no_bot_working_orders", int(f.get("bot_working_orders") or 0) == 0,
                       f"{f.get('bot_working_orders')} bot working order(s)"))
    foreign = int(f.get("foreign_working_orders") or 0)
    gates.append(_gate("foreign_orders_reported", True,
                       f"{foreign} foreign working order(s) on this contract"
                       if foreign else "none"))

    # ── F. protection authority ───────────────────────────────────────────────
    prot = f.get("protection") or {}
    gates.append(_gate("protection_authority", prot.get("authorized") is True,
                       "; ".join(prot.get("reasons") or []) or "attested"))

    # ── G. execution doctrine ─────────────────────────────────────────────────
    doc = f.get("doctrine") or {}
    gates.append(_gate("max_risk_usd", float(doc.get("max_risk_usd") or 0) == EXPECTED_MAX_RISK_USD,
                       f"{doc.get('max_risk_usd')} (expected {EXPECTED_MAX_RISK_USD})"))
    gates.append(_gate("max_contracts", int(doc.get("max_contracts") or 0) == EXPECTED_MAX_CONTRACTS,
                       f"{doc.get('max_contracts')} (expected {EXPECTED_MAX_CONTRACTS})"))
    gates.append(_gate("preferred_stop_points",
                       float(doc.get("preferred_stop_points") or 0) == EXPECTED_PREFERRED_STOP,
                       f"{doc.get('preferred_stop_points')} (expected {EXPECTED_PREFERRED_STOP})"))
    gates.append(_gate("absolute_stop_ceiling",
                       float(doc.get("absolute_stop_points") or 0) == EXPECTED_ABSOLUTE_STOP,
                       f"{doc.get('absolute_stop_points')} (expected {EXPECTED_ABSOLUTE_STOP})"))
    gates.append(_gate("min_reward_to_risk",
                       float(doc.get("min_reward_to_risk") or 0) == EXPECTED_MIN_RR,
                       f"{doc.get('min_reward_to_risk')} (expected {EXPECTED_MIN_RR})"))
    # The bot owns protection: production must attach its own bracket, never
    # rely on the account engine. BRACKETLESS is a smoke-only diagnostic mode.
    gates.append(_gate("attached_brackets_not_bracketless",
                       f.get("production_bracketless") is False,
                       f"production_bracketless={f.get('production_bracketless')!r}"))

    # ── H. Brain. CONFIGURED, never called during preflight ───────────────────
    gates.append(_gate("brain_enabled", f.get("brain_enabled") is True,
                       f"AI_BRAIN_ENABLED resolves {f.get('brain_enabled')!r}"))
    want_model = expected_model()
    gates.append(_gate("model_is_the_production_tier", f.get("model") == want_model,
                       f"{f.get('model')!r} (expected {want_model})"))
    gates.append(_gate("no_provider_call_during_preflight",
                       int(f.get("provider_calls") or 0) == 0,
                       f"{f.get('provider_calls')} provider call(s)"))

    # ── I. session authorization: expected absent in PREP ─────────────────────
    has_auth = bool(f.get("session_authorization_valid"))
    if mode == FINAL:
        gates.append(_gate("session_authorization", has_auth,
                           f.get("session_authorization_detail")
                           or "no valid authorization for today"))
    else:
        gates.append(_gate("session_authorization_deferred", True,
                           "NOT ISSUED — correct tonight; it is date-bound"))

    failed = [g for g in gates if not g["ok"]]
    return {
        "mode": mode,
        "gates": gates,
        "failed": failed,
        "passed_count": len(gates) - len(failed),
        "total_count": len(gates),
        # Only FINAL may ever say yes, and saying yes is still only a REPORT.
        "arm_eligible": mode == FINAL and not failed,
        "prep_complete": mode == PREP and not failed,
        "arming_is_a_separate_operator_action": True,
    }
