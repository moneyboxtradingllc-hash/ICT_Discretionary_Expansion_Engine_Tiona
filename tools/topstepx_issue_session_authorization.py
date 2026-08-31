"""Issue the durable dated authorization that `--arm` requires.

`--arm` is a process argument: it does not survive a restart and carries no
account identity. This command writes the durable record the launcher reads —
after verifying, against the live venue, that the account it names is the pinned
account and the contract it names is the configured MNQ contract.

It never touches an order endpoint. The session it authorizes might; this
command only writes a file.

    python tools/topstepx_issue_session_authorization.py --session-id PROD-20260806 \
                                                         --date 2026-08-06

Doctrine values (2 trades, 1 attempt, $250, 15 MNQ, 35/40, window, compounding
off) are resolved from code. They are deliberately NOT operator-typed: a value
retyped at 6am is a value that can be mistyped, and the whole point of binding
them into the fingerprint is that they are not negotiable at the keyboard.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from broker import topstepx_mission_state as MS                      # noqa: E402
from broker import topstepx_session_authorization as SA              # noqa: E402
from broker.topstepx_redaction import assert_clean                   # noqa: E402
from doctrine import instrument_identity as II                       # noqa: E402

STORE_DIR = os.path.join("data", "integration", "topstepx")


class IssuanceRefused(RuntimeError):
    """The authorization will not be written."""


def parse_date(text: str) -> str:
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        raise IssuanceRefused(
            f"MALFORMED_DATE: {text!r} is not YYYY-MM-DD") from None


def assert_not_past(session_date: str, *, today: str) -> str:
    if session_date < today:
        raise IssuanceRefused(
            f"PAST_DATE: {session_date} has already passed (today {today}); "
            f"an authorization is never backdated")
    return session_date


def assert_account_role(account) -> dict:
    """The pinned account must be a tradeable Combine in the simulated venue.

    `pin_account` already refuses canTrade=false and isVisible=false. This adds
    the venue-environment check, which the pin does not make: authorizing a
    session against a non-simulated account is a different act entirely, and it
    must not be reachable by accident from the issuer.
    """
    can_trade = bool(getattr(account, "can_trade", False))
    simulated = bool(getattr(account, "simulated", False))
    if not can_trade:
        raise IssuanceRefused(
            "ACCOUNT_CANNOT_TRADE: the pinned account reports canTrade=false")
    if not simulated:
        raise IssuanceRefused(
            "NON_SIMULATED_VENUE: the pinned account is not in the simulated "
            "Combine environment; this issuer does not authorize live-funded "
            "sessions")
    return {"can_trade": can_trade, "simulated": simulated,
            "role": "Trading Combine (simulated venue environment)"}


def existing_state(path: str, session_id: str, store_dir: str) -> tuple:
    """(existing authorization or None, attempts already consumed)."""
    existing = SA.SessionAuthorization.load(path)
    spent = 0
    for i in (1, 2):
        m = MS.load(os.path.join(store_dir, f"trade_mission_{session_id}_{i}.json"))
        if m is not None and (m.attempt_count > 0 or m.state in MS.ATTEMPT_SPENT_STATES):
            spent += 1
    return existing, spent


def issue_authorization(*, session_id: str, date_text: str, store_dir: str,
                        account_fingerprint: str, contract_id: str,
                        now: datetime = None) -> dict:
    """Verify every term, then delegate to the authoritative issuer."""
    now = now or datetime.now(timezone.utc)
    session_date = assert_not_past(parse_date(date_text),
                                   today=now.strftime("%Y%m%d"))

    II.assert_production_contract(contract_id, where="authorization")
    if not str(account_fingerprint or "").strip():
        raise IssuanceRefused("NO_FINGERPRINT: the pinned account is unproven")

    path = os.path.join(store_dir, f"session_auth_{session_id}.json")
    existing, spent = existing_state(path, session_id, store_dir)

    if existing is not None:
        if spent:
            raise IssuanceRefused(
                f"ATTEMPTS_ALREADY_CONSUMED: {spent} entry attempt(s) were spent "
                f"under {session_id}; that allowance cannot be reissued")
        same = (existing.session_date == session_date
                and existing.account_fingerprint == account_fingerprint
                and existing.contract_id == contract_id
                and existing.authorization_fingerprint == existing.fingerprint())
        if not same:
            raise IssuanceRefused(
                f"CONFLICTING_AUTHORIZATION: {session_id} already exists with "
                f"different terms; delete it deliberately rather than overwriting")
        # Identical and unspent: idempotent, and the ORIGINAL record is kept so
        # its issued_at (and therefore its fingerprint) does not drift.
        return {"authorization": existing, "state": "ALREADY_ISSUED_UNCHANGED",
                "path": path}

    auth = SA.issue(path=path, session_id=session_id,
                    account_fingerprint=account_fingerprint,
                    contract_id=contract_id, session_date=session_date, now=now)
    # Prove the written record satisfies the same law the launcher will apply.
    auth.verify(account_fingerprint=account_fingerprint, contract_id=contract_id,
                session_date=session_date, now=now)
    return {"authorization": auth, "state": "ISSUED", "path": path}


def render(result: dict, *, session_id: str, date_text: str) -> str:
    a = result["authorization"]
    short = (a.authorization_fingerprint or "")[-6:]     # never the full hash
    return "\n".join([
        "=" * 70,
        f"PRODUCTION SESSION AUTHORIZATION : {result['state']}",
        "=" * 70,
        f"  SESSION                      : {session_id}",
        f"  DATE                         : {date_text}",
        "  ACCOUNT                      : fingerprint verified",
        f"  ACCOUNT ROLE                 : {result.get('role', {}).get('role', 'verified')}",
        f"  CAN TRADE                    : {result.get('role', {}).get('can_trade', '-')}",
        f"  INSTRUMENT                   : {II.PRODUCTION_INSTRUMENT}",
        f"  CONTRACT                     : {a.contract_id}",
        f"  WINDOW                       : {a.decision_window}",
        f"  MAXIMUM BOT TRADES           : {a.maximum_trades}",
        f"  MAXIMUM ATTEMPTS PER TRADE   : {a.maximum_attempts_per_trade}",
        f"  MAXIMUM ALL-IN RISK          : ${a.maximum_risk_per_trade:,.2f}",
        f"  MAXIMUM CONTRACTS            : {a.maximum_contracts}",
        f"  PREFERRED STOP RANGE         : 0-{a.preferred_stop_ceiling:g} points",
        f"  ABSOLUTE STOP CEILING        : {a.absolute_stop_ceiling:g} points",
        f"  COMPOUNDING                  : {'ON' if a.compounding else 'OFF'}",
        f"  AUTHORIZATION FINGERPRINT    : ...{short}",
        "  AUTHORIZATION STATE          : UNSPENT",
        "  ORDER PLACED                 : NO",
        "=" * 70,
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-id", required=True, help="e.g. PROD-20260806")
    ap.add_argument("--date", required=True, help="session date, YYYY-MM-DD")
    ap.add_argument("--symbol", default=II.PRODUCTION_INSTRUMENT)
    ap.add_argument("--store-dir", default=STORE_DIR)
    args = ap.parse_args(argv)

    try:
        II.assert_production_instrument(args.symbol, where="authorization")
    except II.InstrumentIdentityError as exc:
        print(f"AUTHORIZATION REFUSED: {exc}")
        return 2

    # READ-ONLY session: this command proves identity, it does not trade.
    from broker.topstepx_readonly import TopstepXReadOnlySession

    session = TopstepXReadOnlySession(os.getenv("TOPSTEPX_USERNAME"),
                                      os.getenv("TOPSTEPX_API_KEY"))
    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(args.symbol)

    try:
        role = assert_account_role(session.account)
    except IssuanceRefused as exc:
        print(f"AUTHORIZATION REFUSED: {exc}")
        return 2

    try:
        result = issue_authorization(
            session_id=args.session_id, date_text=args.date,
            store_dir=args.store_dir,
            account_fingerprint=os.environ["TOPSTEPX_ACCOUNT_FINGERPRINT"],
            contract_id=contract.id)
    except (IssuanceRefused, SA.AuthorizationRefused, II.InstrumentIdentityError) as exc:
        print(f"AUTHORIZATION REFUSED: {exc}")
        return 2

    result["role"] = role
    out = render(result, session_id=args.session_id, date_text=args.date)
    assert_clean(out)                       # no credential may reach the console
    print(out)
    print(f"\n  Next: python tools\\topstepx_production_session.py --arm "
          f"--mission-id {args.session_id} --until-close")
    print(f"  Write proof: {session.zero_write_proof().get('write_calls_made')} write calls made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
