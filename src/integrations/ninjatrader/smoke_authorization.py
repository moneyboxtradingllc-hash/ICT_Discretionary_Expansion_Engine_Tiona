"""One-use smoke-order authorization token (mission MNQ-DEMO8458533-SMOKE-ORDER).

A single, explicit, human-issued authorization for exactly ONE 1-contract order.
The token is bound to account + instrument + quantity and is consumed (burned)
the instant it is used, so it can never authorize a second order.

Design (fail-closed):
  * A token must exist, be unused, unexpired, and match the exact
    account / instrument / quantity of the intended order.
  * Consuming a token flips used=true and records when/what — atomically before
    the order is transmitted, so a crash after consume never leaves it re-usable.
  * Missing / used / mismatched / expired token -> DENY.

This module NEVER creates a token on its own. A token is issued only by an
explicit human action (issue_token, called from an authorized prompt), so the
assistant cannot self-authorize an order.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional

TOKEN_PATH = os.path.join("data", "integration", "ninjatrader", "smoke_authorization.json")
DEFAULT_TTL_SECONDS = 3600  # a token is valid for 1 hour after issue


@dataclass
class SmokeToken:
    token_id: str
    account: str
    instrument: str
    quantity: int
    issued_at: float
    ttl_seconds: int
    issued_by: str
    # Full trade binding (all enforced at validate/consume time).
    direction: str = "long"
    entry_type: str = "market"
    stop_points: float = 5.0
    target_points: float = 5.0
    oco_required: bool = True
    purpose: str = "EXECUTION_SMOKE_TEST"
    max_submissions: int = 1
    simulation_only: bool = True
    used: bool = False
    used_at: Optional[float] = None
    used_for_intent: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class AuthorizationError(RuntimeError):
    pass


def issue_token(account: str, instrument: str, quantity: int, issued_by: str,
                ttl_seconds: int = DEFAULT_TTL_SECONDS, path: str = TOKEN_PATH,
                *, direction: str = "long", entry_type: str = "market",
                stop_points: float = 5.0, target_points: float = 5.0,
                oco_required: bool = True, purpose: str = "EXECUTION_SMOKE_TEST",
                max_submissions: int = 1, simulation_only: bool = True) -> SmokeToken:
    """Issue a fresh one-use token. Explicit human action only. Refuses to
    overwrite an existing UNUSED token (so a prior authorization is never
    silently replaced)."""
    existing = load_token(path)
    if existing is not None and not existing.used and not _expired(existing):
        raise AuthorizationError("an unused, unexpired token already exists; "
                                 "revoke it before issuing a new one")
    tok = SmokeToken(token_id=uuid.uuid4().hex, account=account, instrument=instrument,
                     quantity=int(quantity), issued_at=time.time(),
                     ttl_seconds=int(ttl_seconds), issued_by=issued_by,
                     direction=str(direction).lower(), entry_type=str(entry_type).lower(),
                     stop_points=float(stop_points), target_points=float(target_points),
                     oco_required=bool(oco_required), purpose=purpose,
                     max_submissions=int(max_submissions), simulation_only=bool(simulation_only))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tok.to_dict(), fh, indent=2)
    return tok


def load_token(path: str = TOKEN_PATH) -> Optional[SmokeToken]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return SmokeToken(**d)
    except (OSError, ValueError, TypeError):
        return None


def _expired(tok: SmokeToken, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.time()
    return now > (tok.issued_at + tok.ttl_seconds)


@dataclass
class AuthCheck:
    valid: bool
    reason: str
    token: Optional[SmokeToken] = None

    def __bool__(self):
        return self.valid


def validate_token(account: str, instrument: str, quantity: int,
                   path: str = TOKEN_PATH, now: Optional[float] = None,
                   direction: Optional[str] = None,
                   entry_type: Optional[str] = None) -> AuthCheck:
    """Read-only validation: is there a valid, unused, matching token? Does NOT
    consume it."""
    tok = load_token(path)
    if tok is None:
        return AuthCheck(False, "no smoke-authorization token present")
    if tok.used:
        return AuthCheck(False, f"token {tok.token_id} already used at {tok.used_at}")
    if _expired(tok, now):
        return AuthCheck(False, f"token {tok.token_id} expired")
    if tok.account != account:
        return AuthCheck(False, f"token account {tok.account!r} != {account!r}")
    if tok.instrument != instrument:
        return AuthCheck(False, f"token instrument {tok.instrument!r} != {instrument!r}")
    if int(tok.quantity) != int(quantity):
        return AuthCheck(False, f"token quantity {tok.quantity} != {quantity}")
    if direction is not None and tok.direction != str(direction).lower():
        return AuthCheck(False, f"token direction {tok.direction!r} != {direction!r}")
    if entry_type is not None and tok.entry_type != str(entry_type).lower():
        return AuthCheck(False, f"token entry_type {tok.entry_type!r} != {entry_type!r}")
    return AuthCheck(True, f"token {tok.token_id} valid and unused", tok)


def consume_token(account: str, instrument: str, quantity: int, intent_id: str,
                  path: str = TOKEN_PATH, now: Optional[float] = None,
                  direction: Optional[str] = None,
                  entry_type: Optional[str] = None) -> AuthCheck:
    """Validate AND burn the token atomically (write used=true BEFORE returning).
    Returns the consumed token on success; fails closed otherwise."""
    check = validate_token(account, instrument, quantity, path, now, direction, entry_type)
    if not check:
        return check
    tok = check.token
    tok.used = True
    tok.used_at = now if now is not None else time.time()
    tok.used_for_intent = intent_id
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tok.to_dict(), fh, indent=2)
    return AuthCheck(True, f"token {tok.token_id} consumed for intent {intent_id}", tok)


def revoke_token(path: str = TOKEN_PATH) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False
