"""TOPSTEPX-SMOKE-AUTH — one-use operator authorization for the Combine smoke.

A passing preflight permits nothing. Submission additionally requires a fresh
token that the operator explicitly minted by typing an exact phrase naming the
purpose, the account role and the size — so authorization cannot be given by
accident, inherited from an earlier session, or replayed after a rejection.

The token is BOUND, not merely random. It carries the account fingerprint, the
contract id, the size cap, the risk cap and the process it was minted in, and
every one of those is re-checked at submit. A token minted for one MNQ on this
Combine cannot authorize a different contract, a larger size, a wider risk, a
different account, or a later process — even though it is a valid token.

The token is BURNED ATOMICALLY at the first submission ATTEMPT, before the
request leaves. Burning after a result would leave a window where a crash,
timeout or exception could be followed by a retry that spends the same
authorization twice; a duplicate live entry is precisely the failure this
mission cannot have. So an accepted order, a rejected order and an exception
all consume the token identically. Another submission needs another phrase.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from broker.topstepx_combine_risk import SMOKE_MAX_RISK_USD, SMOKE_MAX_STOP_POINTS

# FIRST-DAY SMOKE LAW (2026-08-05). The phrase names the ACTUAL cap in force.
# It previously said $250 — the future production ceiling — which would have let
# an operator authorize, in words, twelve times the risk this mission permits.
# The phrase is the operator's statement of intent, so it must be true.
AUTHORIZATION_PHRASE = (
    "AUTHORIZE TOPSTEPX COMBINE SMOKE — ONE MNQ — "
    "ONE QUALIFIED LUNA-AUTHORED TRADE — MAX PLANNED RISK $20"
)

# Retired wording. Explicitly rejected rather than silently unrecognized, so an
# operator pasting yesterday's phrase is told why instead of just "no match".
_RETIRED_PHRASES = (
    "AUTHORIZE TOPSTEPX COMBINE SMOKE — ONE MNQ — "
    "ONE QUALIFIED LUNA-AUTHORED TRADE — MAX RISK $250",
)

# The em dash is easy to lose to a keyboard or a copy-paste. Accept a hyphen
# variant of the SAME words — this is a typography tolerance, not a loosening
# of intent; every word, the size and the dollar figure must still be present.
_PHRASE_VARIANTS = (
    AUTHORIZATION_PHRASE,
    AUTHORIZATION_PHRASE.replace("—", "-"),
    AUTHORIZATION_PHRASE.replace("—", "--"),
)

DEFAULT_TTL_MINUTES = 30


class AuthorizationError(RuntimeError):
    """The phrase was wrong, or the token is missing, spent, expired or unbound."""


def _norm(text: str) -> str:
    """Collapse whitespace and case so formatting cannot defeat an exact match."""
    return " ".join((text or "").split()).strip().upper()


#: Token-id prefixes. They travel to the venue inside the customTag, so they
#: are the only place an order says which lane produced it.
SMOKE_TOKEN_PREFIX = "smoke-"
PRODUCTION_TOKEN_PREFIX = "prod-"


def phrase_is_valid(phrase: str) -> bool:
    return _norm(phrase) in {_norm(v) for v in _PHRASE_VARIANTS}


@dataclass
class SmokeAuthorization:
    """One authorization. Single-use, bound, expiring."""

    token_id: str
    account_fingerprint: str
    contract_id: str
    max_contracts: int
    max_risk_usd: float
    max_stop_points: float
    candidate_fingerprint: str
    snapshot_id: str
    direction: str
    stop_price: float
    target_price: float
    target_identity: str
    process_id: int
    issued_at: datetime
    expires_at: datetime
    spent_at: "datetime | None" = None
    spent_reason: str = ""
    _secret: str = field(default="", repr=False)

    # ── state ─────────────────────────────────────────────────────────────────
    @property
    def spent(self) -> bool:
        return self.spent_at is not None

    def is_expired(self, now: "datetime | None" = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def describe(self) -> dict:
        """Safe identifier for logs and evidence. Never contains the secret."""
        return {"token_id": self.token_id,
                "account_fingerprint": self.account_fingerprint,
                "contract_id": self.contract_id,
                "max_contracts": self.max_contracts,
                "max_risk_usd": self.max_risk_usd,
                "max_stop_points": self.max_stop_points,
                "candidate_fingerprint": self.candidate_fingerprint,
                "snapshot_id": self.snapshot_id,
                "direction": self.direction,
                "stop_price": self.stop_price,
                "target_price": self.target_price,
                "target_identity": self.target_identity,
                "issued_at": self.issued_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "spent": self.spent,
                "spent_at": self.spent_at.isoformat() if self.spent_at else None,
                "spent_reason": self.spent_reason}

    # ── use ───────────────────────────────────────────────────────────────────
    def validate_for(self, *, account_fingerprint: str, contract_id: str,
                     size: int, risk_usd: float, stop_points: float = None,
                     candidate_fingerprint: str = None, snapshot_id: str = None,
                     direction: str = None, stop_price: float = None,
                     target_price: float = None, target_identity: str = None,
                     now: "datetime | None" = None) -> None:
        """Every binding re-checked at submit time. Raises on any mismatch."""
        now = now or datetime.now(timezone.utc)
        if self.spent:
            raise AuthorizationError(
                f"authorization {self.token_id} was already spent at "
                f"{self.spent_at.isoformat()} ({self.spent_reason}). "
                f"A new operator phrase is required.")
        if self.is_expired(now):
            raise AuthorizationError(
                f"authorization {self.token_id} expired at {self.expires_at.isoformat()}")
        if os.getpid() != self.process_id:
            raise AuthorizationError(
                f"authorization {self.token_id} was minted in a different process")
        if account_fingerprint != self.account_fingerprint:
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to a different account")
        if contract_id != self.contract_id:
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to contract "
                f"{self.contract_id}, not {contract_id}")
        if int(size) > int(self.max_contracts):
            raise AuthorizationError(
                f"size {size} exceeds the authorized maximum of {self.max_contracts}")
        if float(risk_usd) > float(self.max_risk_usd):
            raise AuthorizationError(
                f"risk ${float(risk_usd):,.2f} exceeds the authorized maximum of "
                f"${float(self.max_risk_usd):,.2f}")
        if stop_points is not None and float(stop_points) > float(self.max_stop_points):
            raise AuthorizationError(
                f"stop distance {float(stop_points):g} points exceeds the authorized "
                f"maximum of {float(self.max_stop_points):g}")
        # The token authorizes ONE candidate, not "a trade". A different thesis
        # arriving on the same account and contract is a different decision.
        if (self.candidate_fingerprint and candidate_fingerprint is not None
                and candidate_fingerprint != self.candidate_fingerprint):
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to a different candidate")
        if (self.snapshot_id and snapshot_id is not None
                and snapshot_id != self.snapshot_id):
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to snapshot "
                f"{self.snapshot_id}, not {snapshot_id}")
        # THESIS BINDING. A token authorizes one thesis, not "a trade on MNQ".
        # Change the direction, the structural stop, the objective or its price
        # and it is a different decision that the operator never authorized.
        if self.direction and direction is not None and direction != self.direction:
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to a {self.direction} thesis")
        if (self.stop_price and stop_price is not None
                and abs(float(stop_price) - self.stop_price) > 1e-9):
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to stop "
                f"{self.stop_price}, not {stop_price}")
        if (self.target_price and target_price is not None
                and abs(float(target_price) - self.target_price) > 1e-9):
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to target "
                f"{self.target_price}, not {target_price}")
        if (self.target_identity and target_identity is not None
                and target_identity != self.target_identity):
            raise AuthorizationError(
                f"authorization {self.token_id} is bound to objective "
                f"{self.target_identity!r}, not {target_identity!r}")

    def burn(self, reason: str, now: "datetime | None" = None) -> dict:
        """Consume the token. Idempotent-safe: a second burn raises."""
        if self.spent:
            raise AuthorizationError(
                f"authorization {self.token_id} is already spent; refusing to reuse")
        self.spent_at = now or datetime.now(timezone.utc)
        self.spent_reason = reason
        self._secret = ""          # the secret cannot outlive its single use
        return {"token_id": self.token_id, "burned_at": self.spent_at.isoformat(),
                "reason": reason}


def issue(*, phrase: str, account_fingerprint: str, contract_id: str,
          max_contracts: int = 1, max_risk_usd: float = SMOKE_MAX_RISK_USD,
          max_stop_points: float = SMOKE_MAX_STOP_POINTS,
          candidate_fingerprint: str = "", snapshot_id: str = "",
          direction: str = "", stop_price: float = 0.0,
          target_price: float = 0.0, target_identity: str = "",
          ttl_minutes: int = DEFAULT_TTL_MINUTES,
          token_prefix: str = SMOKE_TOKEN_PREFIX,
          now: "datetime | None" = None) -> SmokeAuthorization:
    """Mint one authorization from the operator's exact phrase.

    `token_prefix` labels the token, and therefore the venue customTag, since
    `session_ledger.bot_tag` stamps `EXPBOT-<token_id>` onto every order. It
    defaults to smoke so nothing changes for the smoke tools; production passes
    `PRODUCTION_TOKEN_PREFIX`. PROD-20260810 placed a real 3-contract
    production order tagged `EXPBOT-smoke-40ac176b07b5`, which is a forensic
    trap on a venue where the tag is the only attribution evidence.

    Attribution is unaffected either way: `classify` strips `EXPBOT-` and
    matches the remainder against the session's known token ids, so it never
    reads the prefix. Nothing here participates in a fingerprint or a digest.
    """
    if not phrase_is_valid(phrase):
        norm = _norm(phrase)
        if norm in {_norm(p) for p in _RETIRED_PHRASES} or "MAX RISK $250" in norm:
            raise AuthorizationError(
                "that is the RETIRED $250 phrase. The first-day smoke authorizes "
                "a $20 maximum planned risk, and the phrase must say so.")
        raise AuthorizationError(
            "authorization phrase does not match. The exact phrase is required, "
            "naming the purpose, the size and the risk cap.")
    if not account_fingerprint:
        raise AuthorizationError("cannot authorize without a pinned account fingerprint")
    if not contract_id:
        raise AuthorizationError("cannot authorize without a resolved contract id")
    if int(max_contracts) < 1:
        raise AuthorizationError(f"max_contracts must be >= 1, got {max_contracts!r}")

    now = now or datetime.now(timezone.utc)
    return SmokeAuthorization(
        token_id=str(token_prefix) + secrets.token_hex(6),
        account_fingerprint=account_fingerprint,
        contract_id=contract_id,
        max_contracts=int(max_contracts),
        max_risk_usd=float(max_risk_usd),
        max_stop_points=float(max_stop_points),
        candidate_fingerprint=str(candidate_fingerprint),
        snapshot_id=str(snapshot_id),
        direction=str(direction),
        stop_price=float(stop_price or 0.0),
        target_price=float(target_price or 0.0),
        target_identity=str(target_identity),
        process_id=os.getpid(),
        issued_at=now,
        expires_at=now + timedelta(minutes=int(ttl_minutes)),
        _secret=secrets.token_hex(16),
    )


def authorize_submission(token: "SmokeAuthorization | None", *,
                         account_fingerprint: str, contract_id: str,
                         size: int, risk_usd: float, stop_points: float = None,
                         candidate_fingerprint: str = None, snapshot_id: str = None,
                         direction: str = None, stop_price: float = None,
                         target_price: float = None, target_identity: str = None,
                         now: "datetime | None" = None) -> dict:
    """The single gate a submission must pass. Validates, then BURNS.

    Burning here — before the caller sends anything — is deliberate. The caller
    gets a burned token back and one permission to try; whatever happens next,
    the authorization is gone.
    """
    if token is None:
        raise AuthorizationError(
            "no operator authorization present. A fresh exact phrase is required "
            "before any order can be submitted.")
    token.validate_for(account_fingerprint=account_fingerprint, contract_id=contract_id,
                       size=size, risk_usd=risk_usd, stop_points=stop_points,
                       candidate_fingerprint=candidate_fingerprint,
                       snapshot_id=snapshot_id, direction=direction,
                       stop_price=stop_price, target_price=target_price,
                       target_identity=target_identity, now=now)
    return token.burn("submission_attempted", now=now)
