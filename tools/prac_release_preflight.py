"""Is the PRAC lane eligible to ARM? Read-only, DISARMED, places nothing.

    python tools/prac_release_preflight.py                 # PREP  (tonight)
    python tools/prac_release_preflight.py --final         # FINAL (session morning)
    python tools/prac_release_preflight.py --offline       # no venue contact

PRAC-RELEASE-1. Gathers facts and hands them to
`operational_readiness.prac_release.evaluate`, which owns every gate. This file
deliberately decides nothing: a preflight whose verdict logic is tangled into
its I/O cannot be tested without a market.

It runs on `TopstepXReadOnlySession` -- no write methods exist and the transport
refuses every write path -- so it cannot place, modify, cancel or close
anything. It never calls Terra: the model is RESOLVED, not invoked.

It never arms. `ARM_ELIGIBLE` is a report; arming stays an explicit, separate
operator action.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

from broker import topstepx_protection_authority as PA           # noqa: E402
from operational_readiness import prac_release as PR             # noqa: E402

ET = ZoneInfo("America/New_York")
STORE_DIR = os.path.join("data", "integration", "topstepx")


def _tracked_clean() -> tuple:
    """Only TRACKED SOURCE counts. Runtime evidence is not dirt to be laundered."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--",
                              "src", "tests", "tools"],
                             capture_output=True, text=True, timeout=60)
        dirty = [l[3:] for l in out.stdout.splitlines() if l.strip()]
        return (not dirty), dirty
    except Exception as exc:  # noqa: BLE001
        return False, [f"git unavailable: {type(exc).__name__}"]


def gather(*, offline: bool, session_date: str) -> dict:
    from ai_brain.narrative_brain import enabled as brain_enabled
    from ai_brain.production_model import brain_contract_fingerprint, resolve_model
    from broker import topstepx_combine_risk as RISK

    clean, dirty = _tracked_clean()
    facts = {
        "tracked_source_clean": clean, "dirty_tracked_files": dirty,
        "brain_fingerprint": brain_contract_fingerprint(),
        "brain_enabled": brain_enabled(),
        "provider_calls": 0,               # nothing here calls Terra
        "production_bracketless": False,   # production always attaches its own
        "doctrine": {
            "max_risk_usd": RISK.PRODUCTION_MAX_RISK_USD,
            "max_contracts": RISK.PRODUCTION_MAX_CONTRACTS,
            "preferred_stop_points": RISK.PREFERRED_MAX_STOP_POINTS,
            "absolute_stop_points": RISK.ABSOLUTE_MAX_STOP_POINTS,
            "min_reward_to_risk": RISK.MIN_REWARD_TO_RISK,
        },
        "account_id": os.getenv("TOPSTEPX_ACCOUNT_ID"),
        "account_fingerprint": os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT"),
    }
    try:
        facts["model"] = resolve_model(armed=True)
    except Exception as exc:  # noqa: BLE001 — report, never crash the preflight
        facts["model"] = f"UNRESOLVED: {type(exc).__name__}"

    facts["protection"] = PA.resolve(
        STORE_DIR, account_id=facts["account_id"],
        account_fingerprint=facts["account_fingerprint"], session_date=session_date)

    # SESSION AUTHORIZATION. FINAL asks whether a valid, date-bound record exists
    # for TODAY; PREP does not. This was missing entirely, so FINAL could never
    # pass even with a freshly issued and independently verified authorization --
    # the gate had no fact to read. Verification is delegated to the canonical
    # owner (`SessionAuthorization.verify`), never re-implemented here.
    #
    # The stored date is the compact YYYYMMDD `parse_date()` produces, and
    # `verify()` compares raw strings, so the ISO session date is normalised the
    # way the issuer does -- the exact mismatch that once made a valid
    # authorization read as AUTHORIZATION_EXPIRED.
    from broker import topstepx_session_authorization as SA
    compact = session_date.replace("-", "")
    found, detail = None, "no authorization record for this session date"
    for path in sorted(glob.glob(os.path.join(STORE_DIR, "session_auth_*.json"))):
        record = SA.SessionAuthorization.load(path)
        if record is None or str(record.session_date) != compact:
            continue
        try:
            record.verify(account_fingerprint=facts["account_fingerprint"] or "",
                          contract_id=facts.get("contract_id")
                          or os.getenv("TOPSTEPX_CONTRACT_ID", "CON.F.US.MNQ.U26"),
                          session_date=compact)
            found = record
            detail = (f"{record.session_id} · auth ...{str(record.authorization_fingerprint)[-6:]} "
                      f"· brain ...{str(record.brain_contract_fingerprint)[-6:]} · UNSPENT"
                      if not getattr(record, "spent", False) else record.session_id)
            break
        except SA.AuthorizationRefused as exc:
            detail = f"{os.path.basename(path)}: {exc}"
    facts["session_authorization_valid"] = found is not None
    facts["session_authorization_detail"] = detail
    facts["session_authorization_id"] = getattr(found, "session_id", None)
    facts["session_authorization_fingerprint"] = getattr(
        found, "authorization_fingerprint", None)

    if offline:
        facts["offline"] = True
        return facts

    from broker.topstepx_readonly import TopstepXReadOnlySession
    session = TopstepXReadOnlySession(os.getenv("TOPSTEPX_USERNAME", ""),
                                      os.getenv("TOPSTEPX_API_KEY", ""))
    session.assert_no_write_surface()          # raises if a write method exists
    session.authenticate()
    account = session.pin(account_id=int(facts["account_id"] or 0),
                          expected_fingerprint=facts["account_fingerprint"] or "")
    contract = session.resolve_contract(os.getenv("TOPSTEPX_CONTRACT", "MNQ"))
    orders = session.open_orders()
    mine = [o for o in orders
            if str(o.get("contract_id") or "") == str(contract.id)]
    facts.update({
        "account_id": account.id, "simulated": account.simulated,
        "can_trade": account.can_trade, "is_visible": account.is_visible,
        "balance": account.balance, "contract_id": contract.id,
        "open_positions": len(session.open_positions()),
        # Nothing is "ours" without a live mission, so a working order on our
        # contract is reported as FOREIGN rather than quietly claimed.
        "bot_working_orders": 0, "foreign_working_orders": len(mine),
        "offline": False,
    })
    session.close()
    return facts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true",
                   help="session-morning mode; requires today's authorization")
    ap.add_argument("--offline", action="store_true", help="no venue contact")
    ap.add_argument("--session-date", default="")
    args = ap.parse_args(argv)

    mode = PR.FINAL if args.final else PR.PREP
    session_date = args.session_date or datetime.now(ET).strftime("%Y-%m-%d")
    facts = gather(offline=args.offline, session_date=session_date)
    report = PR.evaluate(facts, mode=mode)

    print(f"\n  PRAC RELEASE PREFLIGHT — {mode}   session date {session_date} ET")
    print(f"  {'-' * 68}")
    for g in report["gates"]:
        print(f"  {'PASS' if g['ok'] else 'FAIL'}  {g['gate']:<38} {g['detail']}")
    print(f"  {'-' * 68}")
    print(f"  GATES                         : {report['passed_count']}/{report['total_count']}")
    print(f"  ARM ELIGIBLE                  : {report['arm_eligible']}")
    if mode == PR.PREP:
        print(f"  PREP COMPLETE                 : {report['prep_complete']}")
    print("  ARMING                        : a separate explicit operator action")
    return 0 if not report["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
