"""Who owns the stop and the target? Attested, because it cannot be measured.

PROTECTION-AUTHORITY-1 (2026-08-18).

THE DEFECT THIS REPLACES. `topstepx_production_doctrine.resolve()` returned the
literal `"topstep_position_brackets": "disabled"` and `assert_no_conflict()`
compared that constant against itself. Both production callers invoke it with no
argument, so the guard COULD NOT FAIL -- a declaration wearing the costume of a
measurement. It was already false in practice: account 33333333 rejected
order-attached brackets with `errorCode=2 "Brackets cannot be used with Position
Brackets."`, proving the venue-side engine was ENABLED while startup passed.

WHY ATTESTATION AND NOT MEASUREMENT. `/api/Account/search` publishes exactly six
fields -- id, name, balance, canTrade, simulated, isVisible. There is no
account-settings endpoint anywhere in the client surface, and no hub event
carries bracket configuration. So the bot cannot see this. The honest response
is not to guess and not to keep asserting a constant; it is to require a HUMAN
to look at the venue UI and record what they saw, and to refuse when that record
is missing, stale, or about a different account.

WHY IT MATTERS, ON TWO SEPARATE AXES.

    AXIS A - MECHANISM.  Which venue bracket system the account is in.
        POSITION brackets are position-based and account-level: they would
        author protection for the same position our order already protects, so
        they must be OFF. ORDER-BASED Auto-OCO is the mechanism an attached
        `stopLossBracket`/`takeProfitBracket` rides on, so it must be ON.

    AXIS B - PRICE AUTHOR.  Who chooses the numbers. Always us. Production
        submits its own bracket derived from Terra's structural invalidation and
        the authorized objective, then re-anchors both legs to those absolute
        prices after the fill (EXEC-PRICE-ANCHOR-1).

CORRECTED 2026-08-19. v1 collapsed these axes and demanded Auto-OCO OFF too. The
only evidence for that was the venue refusal `errorCode=2 "Brackets cannot be
used with Position Brackets."` -- which names POSITION brackets and nothing else.
The widened requirement was recorded, the operator complied, and the first
attached-bracket canary under that configuration was rejected instantly (order
3420877831, status 5, 0 fills). A mechanism is not a thesis author.

    MEASURED  -> trust the venue
    ATTESTED  -> trust a named human, bounded to one account and one date
    NEITHER   -> refuse
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

#: v2 (2026-08-19). v1 required `account_auto_oco = confirmed_disabled`, which
#: conflated TWO DIFFERENT TopstepX bracket modes. The only evidence we ever had
#: was the venue's own refusal text -- errorCode=2 "Brackets cannot be used with
#: Position Brackets" -- which names POSITION BRACKETS and nothing else. We
#: widened that into "all account-side OCO must be off", the operator complied,
#: and the first attached-bracket canary under that configuration was instantly
#: rejected (order 3420877831, status 5, 0 fills).
#:
#: TopstepX distinguishes them: Position Risk/Profit Brackets are POSITION-based
#: and account-level; Auto-OCO brackets are ORDER-based and tied to the
#: individual entry. ProjectX `/api/Order/place` carries `stopLossBracket` and
#: `takeProfitBracket` in the request -- the order-based mechanism. So Auto-OCO
#: is the LINKAGE MECHANISM our own payload rides on; it is not a competing
#: thesis author. Position Brackets are the competing author, and they stay off.
#:
#: v1 attestations are refused rather than reinterpreted: they asserted a
#: materially different proposition about the venue.
SCHEMA = "protection_authority.v2"
LEGACY_SCHEMA_V1 = "protection_authority.v1"
STORE_FILENAME = "protection_authority_attestation.json"

#: AXIS B — who authors the PRICES. Always us.
BOT_ATTACHED_BRACKETS = "bot_attached_brackets"
CONFIRMED_DISABLED = "confirmed_disabled"
#: AXIS A — which venue bracket MECHANISM the account is in. Order-based
#: Auto-OCO is what an attached `stopLossBracket`/`takeProfitBracket` needs.
AUTO_OCO_ORDER_BASED = "auto_oco_order_based"

#: Refusal codes. Named so an operator at 09:29 reads a cause, not a boolean.
MISSING = "PROTECTION_ATTESTATION_MISSING"
CORRUPT = "PROTECTION_ATTESTATION_CORRUPT"
SCHEMA_MISMATCH = "PROTECTION_ATTESTATION_SCHEMA_MISMATCH"
EXPIRED = "PROTECTION_ATTESTATION_EXPIRED"
ACCOUNT_MISMATCH = "PROTECTION_ACCOUNT_MISMATCH"
FINGERPRINT_MISMATCH = "PROTECTION_FINGERPRINT_MISMATCH"
OWNER_CONFLICT = "PROTECTION_OWNER_CONFLICT"
POSITION_BRACKETS_ENABLED = "ACCOUNT_POSITION_BRACKETS_ENABLED"
BRACKET_MODE_WRONG = "ACCOUNT_BRACKET_MODE_NOT_ORDER_BASED"
NOT_OPERATOR_CONFIRMED = "PROTECTION_NOT_OPERATOR_CONFIRMED"


def store_path(store_dir: str) -> str:
    return os.path.join(store_dir, STORE_FILENAME)


def attestation_fingerprint(att: dict) -> str:
    """Stable identity of WHAT WAS ATTESTED, for binding into an authorization.

    Only the load-bearing claims are hashed. `confirmed_at_utc` is deliberately
    excluded so re-recording the same facts does not invalidate a session
    authorization, while changing any actual claim does.
    """
    payload = {k: (att or {}).get(k) for k in (
        "schema_version", "account_id", "account_fingerprint", "protection_owner",
        "account_position_brackets", "account_bracket_mode", "valid_for_session_date")}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "prot:" + hashlib.sha256(raw).hexdigest()[:16]


def build(*, account_id, account_fingerprint: str, session_date: str,
          confirmed_by: str, now=None) -> dict:
    """The record an operator creates AFTER looking at the venue UI.

    Never called by production and never called automatically: something has to
    have been seen by someone for this file to mean anything at all.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    att = {
        "schema_version": SCHEMA,
        "account_id": int(account_id),
        "account_fingerprint": str(account_fingerprint),
        "protection_owner": BOT_ATTACHED_BRACKETS,
        # AXIS A: mechanism. Position brackets off (they would compete for the
        # same position); order-based Auto-OCO on (our attached bracket rides it).
        "account_position_brackets": CONFIRMED_DISABLED,
        "account_bracket_mode": AUTO_OCO_ORDER_BASED,
        "confirmed_by": "operator",
        "confirmed_by_name": str(confirmed_by),
        "confirmed_at_utc": stamp,
        "valid_for_session_date": str(session_date),
        "source": "operator_visual_confirmation_of_venue_ui",
        "measurable_by_api": False,
    }
    att["attestation_fingerprint"] = attestation_fingerprint(att)
    return att


def load(store_dir: str) -> dict | None:
    path = store_path(store_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"__corrupt__": True}


def verify(att: dict | None, *, account_id, account_fingerprint: str,
           session_date: str) -> list:
    """Reasons this attestation may NOT authorize protection. Empty is good.

    Every branch fails CLOSED. An attestation that is absent, unreadable, about
    another account, or about another day is not weaker evidence -- it is no
    evidence, and it is refused exactly like an explicit "brackets are enabled".
    """
    reasons: list = []
    if att is None:
        return [f"{MISSING}: no operator attestation that the bot owns protection"]
    if att.get("__corrupt__"):
        return [f"{CORRUPT}: the attestation file could not be parsed"]
    if att.get("schema_version") != SCHEMA:
        extra = ("  v1 required Auto-OCO DISABLED, which conflated position-based "
                 "and order-based brackets; it is superseded, not reinterpreted."
                 if att.get("schema_version") == LEGACY_SCHEMA_V1 else "")
        reasons.append(f"{SCHEMA_MISMATCH}: expected {SCHEMA}, "
                       f"found {att.get('schema_version')!r}.{extra}")
    try:
        same_account = int(att.get("account_id")) == int(account_id)
    except (TypeError, ValueError):
        same_account = False
    if not same_account:
        reasons.append(f"{ACCOUNT_MISMATCH}: attested for account "
                       f"{att.get('account_id')!r}, session is {account_id!r}")
    if str(att.get("account_fingerprint") or "") != str(account_fingerprint or ""):
        reasons.append(f"{FINGERPRINT_MISMATCH}: attested "
                       f"{att.get('account_fingerprint')!r}, session "
                       f"{account_fingerprint!r}")
    if str(att.get("valid_for_session_date") or "") != str(session_date or ""):
        reasons.append(f"{EXPIRED}: attested for {att.get('valid_for_session_date')!r}, "
                       f"session date is {session_date!r}. Venue settings can change "
                       f"overnight; yesterday's look is not today's evidence.")
    if att.get("protection_owner") != BOT_ATTACHED_BRACKETS:
        reasons.append(f"{OWNER_CONFLICT}: protection_owner is "
                       f"{att.get('protection_owner')!r}, doctrine requires "
                       f"{BOT_ATTACHED_BRACKETS}")
    if att.get("account_position_brackets") != CONFIRMED_DISABLED:
        reasons.append(f"{POSITION_BRACKETS_ENABLED}: account Position Brackets are "
                       f"{att.get('account_position_brackets')!r}; two protection "
                       f"authors may not race for one position")
    if att.get("account_bracket_mode") != AUTO_OCO_ORDER_BASED:
        reasons.append(f"{BRACKET_MODE_WRONG}: account bracket mode is "
                       f"{att.get('account_bracket_mode')!r}, attached "
                       f"stopLossBracket/takeProfitBracket require "
                       f"{AUTO_OCO_ORDER_BASED}")
    if att.get("confirmed_by") != "operator" or not att.get("confirmed_by_name"):
        reasons.append(f"{NOT_OPERATOR_CONFIRMED}: this record must name the human "
                       f"who looked at the venue UI")
    return reasons


def resolve(store_dir: str, *, account_id, account_fingerprint: str,
            session_date: str) -> dict:
    """Load + verify in one hop. `authorized` is the only truthy answer."""
    att = load(store_dir)
    reasons = verify(att, account_id=account_id,
                     account_fingerprint=account_fingerprint,
                     session_date=session_date)
    return {"authorized": not reasons, "reasons": reasons,
            "attestation": None if att is None or att.get("__corrupt__") else att,
            "attestation_fingerprint": (attestation_fingerprint(att)
                                        if att and not att.get("__corrupt__") else None),
            "measured_by_api": False,
            "source": "operator_attestation"}
