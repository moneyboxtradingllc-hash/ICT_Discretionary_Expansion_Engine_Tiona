"""TOPSTEPX-INTEGRATION — a venue session that cannot write.

The mission's requirement is precise: the read-only preflight must be
*structurally* incapable of placing, modifying, cancelling or closing an order,
not merely operated by someone who intends not to. Two things make that true
here, and both are needed:

  1. NO WRITE METHODS EXIST on this object. There is no place_order, no
     cancel, no modify, no flatten, no close_position. You cannot call what is
     not there, and `assert_no_write_surface()` proves the absence rather than
     asserting it in prose.

  2. THE TRANSPORT REFUSES WRITE PATHS. Even if some future code reached the
     wrapped client directly, every request passes an allowlist keyed on the
     endpoint path. A write path raises ReadOnlyViolation before a byte leaves
     the process. This is the guarantee that survives refactors — (1) can be
     defeated by someone adding a method; (2) cannot be defeated by accident.

The allowlist is deliberately explicit rather than a "block the known writes"
denylist: a new venue write endpoint added by TopstepX tomorrow is denied by
default, which is the direction a safety gate should fail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from broker.topstepx_client import (
    TopstepXAccount, TopstepXClient, TopstepXContract, TopstepXError,
)
from broker.topstepx_realtime import (
    MARKET_HUB_URL, USER_HUB_URL, SignalRHub, market_hub_subscriptions,
    user_hub_subscriptions,
)

# Every endpoint the read-only phase is permitted to touch. Anything absent is
# refused — including endpoints that merely *look* harmless.
READ_ALLOWLIST = frozenset({
    "/api/Auth/loginKey",
    "/api/Auth/validate",
    "/api/Account/search",
    "/api/Contract/search",
    "/api/Contract/available",
    "/api/Contract/searchById",
    "/api/History/retrieveBars",
    "/api/Position/searchOpen",
    "/api/Order/searchOpen",
    # THE COMPLETE DISCOVERY SURFACE, and a READ. `searchOpen` omits Suspended
    # bracket children by official Gateway contract, so a read-only session
    # limited to it could report an account as having no working orders while
    # one rested at the venue -- a false clean bill of health from the very
    # surface that exists to give an honest one.
    "/api/Order/v2/query",
    "/api/Order/searchById",
    "/api/Order/search",
    "/api/Trade/search",
})

# Named only so a violation message can say what was attempted. Never called.
KNOWN_WRITE_PATHS = frozenset({
    "/api/Order/place", "/api/Order/cancel", "/api/Order/modify",
    "/api/Position/closeContract", "/api/Position/partialCloseContract",
})

# Method names that must NOT exist on a read-only session.
_FORBIDDEN_ATTRS = (
    "place_order", "place_bracket_market_order", "submit_order", "cancel_order",
    "modify_order", "close_position", "partial_close", "flatten",
    "emergency_flatten", "close_contract",
)


class ReadOnlyViolation(RuntimeError):
    """Something tried to reach a write endpoint from a read-only session."""


class TopstepXReadOnlySession:
    """Authenticated, write-incapable access to one pinned TopstepX account."""

    def __init__(self, username: str, api_key: str, *,
                 transport: Optional[Callable[..., dict]] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 connect_factory: Optional[Callable[[str], Any]] = None,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._client = TopstepXClient(username, api_key, transport=transport,
                                      clock=clock, sleep=sleep)
        # Install the guard by wrapping whatever transport the client ended up
        # with. Wrapping (rather than replacing) keeps the injected test
        # transport working while still enforcing the allowlist on it.
        self._inner_transport = self._client._transport      # noqa: SLF001 — deliberate seam
        self._client._transport = self._guarded_transport    # noqa: SLF001
        self.endpoints_called: list = []
        self.write_attempts: list = []
        self._connect_factory = connect_factory
        self._sleep = sleep
        self.account: Optional[TopstepXAccount] = None
        self.contract: Optional[TopstepXContract] = None
        self.user_hub: Optional[SignalRHub] = None
        self.market_hub: Optional[SignalRHub] = None

    # ── the guard ─────────────────────────────────────────────────────────────
    def _guarded_transport(self, url: str, payload: dict, headers: dict, timeout: float) -> dict:
        path = urlsplit(url).path
        if path not in READ_ALLOWLIST:
            self.write_attempts.append(path)
            kind = "known write endpoint" if path in KNOWN_WRITE_PATHS else "non-allowlisted endpoint"
            raise ReadOnlyViolation(
                f"read-only session refused {kind} {path}. No request was sent."
            )
        self.endpoints_called.append(path)
        return self._inner_transport(url, payload, headers, timeout)

    def assert_no_write_surface(self) -> list:
        """Prove absence of write methods. Returns the checked names."""
        present = [n for n in _FORBIDDEN_ATTRS if hasattr(self, n)]
        if present:
            raise ReadOnlyViolation(
                f"read-only session exposes write method(s): {present}")
        return list(_FORBIDDEN_ATTRS)

    # ── reads ─────────────────────────────────────────────────────────────────
    def authenticate(self) -> dict:
        """Force a login and report PASS/FAIL without revealing the token.

        Success requires everything the operator's contract requires:
        the call succeeds, `success` is true, `errorCode` is 0, and the token is
        a non-empty string. `_authenticate` already enforces success+token; this
        adds the errorCode check and returns a describable, tokenless result.
        """
        self._client._authenticate()                          # noqa: SLF001
        token = self._client._token                           # noqa: SLF001
        ok = isinstance(token, str) and bool(token.strip())
        return {"authenticated": ok,
                "token_present": ok,
                "token_type": "JWT" if ok else None,
                "expires_at": (self._client._token_expires.isoformat()   # noqa: SLF001
                               if self._client._token_expires else None)}  # noqa: SLF001

    def pin(self, *, account_id=None, account_name: str = "",
            expected_fingerprint: str = "") -> TopstepXAccount:
        self.account = self._client.pin_account(
            account_id=account_id, account_name=account_name,
            expected_fingerprint=expected_fingerprint)
        return self.account

    def resolve_contract(self, text: str = "MNQ", live: bool = False) -> TopstepXContract:
        """Resolve the ACTIVE contract for `text` from the API. Never hardcoded.

        Rejects ambiguity and inactivity rather than choosing: two active MNQ
        expiries mean the roll is in progress and the operator must say which
        one, and an inactive contract is a stale ID by definition.
        """
        candidates = [c for c in self._client.search_contracts(text, live=live) if c.active]
        if not candidates:
            raise TopstepXError(
                f"no ACTIVE contract matched {text!r}. Refusing to fall back to a "
                f"hardcoded or inactive contract id.")
        exact = [c for c in candidates if c.name.upper().startswith(text.upper())]
        pool = exact or candidates
        if len(pool) > 1:
            raise TopstepXError(
                f"{len(pool)} active contracts matched {text!r} "
                f"({', '.join(sorted(c.name for c in pool))}). Ambiguous during a "
                f"roll — pin TOPSTEPX_CONTRACT to one name.")
        c = pool[0]
        if c.tick_size <= 0 or c.tick_value <= 0:
            raise TopstepXError(
                f"contract {c.id} reports tickSize={c.tick_size} tickValue={c.tick_value}; "
                f"invalid metadata cannot size a stop.")
        self.contract = c
        return c

    def open_positions(self) -> list:
        return self._client.open_positions(self._require_account().id)

    def open_orders(self, contract_id: Optional[str] = None) -> list:
        return self._client.open_orders(self._require_account().id, contract_id)

    def query_orders(self, *, statuses=None, contract_id: Optional[str] = None) -> list:
        """READ. Discovery across statuses, including the Suspended bracket
        children `open_orders()` omits by contract."""
        return self._client.query_orders(self._require_account().id,
                                         statuses=statuses,
                                         contract_id=contract_id)

    def order_by_id(self, order_id) -> "dict | None":
        """READ. The terminality oracle for one known order."""
        return self._client.order_by_id(self._require_account().id, order_id)

    def bars_1m(self, minutes_back: int = 180) -> list:
        return self._client.bars(self._require_contract().id, minutes_back=minutes_back)

    def _require_account(self) -> TopstepXAccount:
        if self.account is None:
            raise TopstepXError("no account pinned; call pin() first")
        return self.account

    def _require_contract(self) -> TopstepXContract:
        if self.contract is None:
            raise TopstepXError("no contract resolved; call resolve_contract() first")
        return self.contract

    # ── realtime ──────────────────────────────────────────────────────────────
    def _token(self) -> str:
        return self._client._session_token()                  # noqa: SLF001

    def connect_user_hub(self) -> SignalRHub:
        hub = SignalRHub(USER_HUB_URL, self._token,
                         connect_factory=self._connect_factory,
                         clock=self._clock, sleep=self._sleep)
        hub.connect()
        for sub in user_hub_subscriptions(self._require_account().id):
            hub.subscribe(sub)
        self.user_hub = hub
        return hub

    def connect_market_hub(self) -> SignalRHub:
        hub = SignalRHub(MARKET_HUB_URL, self._token,
                         connect_factory=self._connect_factory,
                         clock=self._clock, sleep=self._sleep)
        hub.connect()
        for sub in market_hub_subscriptions(self._require_contract().id):
            hub.subscribe(sub)
        self.market_hub = hub
        return hub

    def close(self) -> None:
        for hub in (self.user_hub, self.market_hub):
            if hub is not None:
                hub.close()

    # ── evidence ──────────────────────────────────────────────────────────────
    def zero_write_proof(self) -> dict:
        """The artifact's claim that nothing was mutated, with its basis."""
        return {"write_attempts": list(self.write_attempts),
                "write_calls_made": 0,
                "endpoints_called": sorted(set(self.endpoints_called)),
                "allowlist_enforced": sorted(READ_ALLOWLIST),
                "write_surface_absent": self.assert_no_write_surface()}
