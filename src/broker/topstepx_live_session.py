"""Write-capable TopstepX session for the authorized execution lane.

The sibling `TopstepXReadOnlySession` refuses every write at the transport. This
one does not, and that is the whole difference — so it is deliberately small,
holds no decision logic, and is only ever handed to an `ExecutionRunner` that
has an operator authorization behind it.

Every write it exposes maps to one verified official endpoint:

    place_order          POST /api/Order/place
    cancel_order         POST /api/Order/cancel
    modify_order         POST /api/Order/modify
    close_position       POST /api/Position/closeContract

`place_order` takes a body the caller already built and validated. It does not
construct or adjust the bracket: the geometry is built from the current price
moments before submission and must reach the venue byte-for-byte as checked.

Constructing this class does not arm anything. Submission still requires the
runner's full gate sequence and a burned one-use token.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from broker.topstepx_client import TopstepXAccount, TopstepXClient, TopstepXContract
from broker.topstepx_realtime import (
    MARKET_HUB_URL, USER_HUB_URL, SignalRHub, market_hub_subscriptions,
    user_hub_subscriptions,
)

WRITE_PATHS = ("/api/Order/place", "/api/Order/cancel", "/api/Order/modify",
               "/api/Position/closeContract")


class TopstepXLiveSession:
    """Authenticated, write-CAPABLE access to one pinned TopstepX account."""

    def __init__(self, username: str = None, api_key: str = None, *,
                 transport: Optional[Callable[..., dict]] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 connect_factory=None) -> None:
        username = (username or os.getenv("TOPSTEPX_USERNAME") or "").strip()
        api_key = (api_key or os.getenv("TOPSTEPX_API_KEY") or "").strip()
        self._client = TopstepXClient(username, api_key, transport=transport, clock=clock)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._connect_factory = connect_factory
        self.account: Optional[TopstepXAccount] = None
        self.contract: Optional[TopstepXContract] = None
        self.user_hub: Optional[SignalRHub] = None
        self.market_hub: Optional[SignalRHub] = None
        # Every write is recorded so the lifecycle artifact can state exactly
        # what was sent, and so "zero writes" is a measurement, not a promise.
        self.writes: list = []

    # ── identity ──────────────────────────────────────────────────────────────
    def authenticate(self) -> dict:
        self._client._authenticate()                      # noqa: SLF001
        return {"authenticated": bool(self._client._token)}   # noqa: SLF001

    def pin(self, *, account_id=None, account_name: str = "",
            expected_fingerprint: str = "") -> TopstepXAccount:
        self.account = self._client.pin_account(
            account_id=account_id, account_name=account_name,
            expected_fingerprint=expected_fingerprint)
        return self.account

    def resolve_contract(self, text: str = "MNQ") -> TopstepXContract:
        self.contract = self._client.resolve_contract(text)
        return self.contract

    def _require(self):
        if self.account is None or self.contract is None:
            raise RuntimeError("live session is not pinned to an account and contract")
        return self.account, self.contract

    # ── reads ─────────────────────────────────────────────────────────────────
    def open_positions(self) -> list:
        acct, _ = self._require()
        return self._client.open_positions(acct.id)

    def open_orders(self) -> list:
        acct, _ = self._require()
        return self._client.open_orders(acct.id)

    def order_by_id(self, order_id) -> "dict | None":
        """READ. Exact lifecycle of one known order -- the terminality oracle."""
        acct, _ = self._require()
        return self._client.order_by_id(acct.id, order_id)

    def query_orders(self, *, statuses=None, contract_id: str = None) -> list:
        """READ. Discovery across statuses, including the Suspended bracket
        children `open_orders()` omits by contract."""
        acct, _ = self._require()
        return self._client.query_orders(acct.id, statuses=statuses,
                                         contract_id=contract_id)

    def bars_1m(self, minutes_back: int = 180) -> list:
        """CLOSED 1m bars for the pinned contract, oldest-first.

        STARTUP-HISTORY-WIRING (2026-08-12, PROD-20260812). The production
        launcher hands THIS session to `TopstepXDataProvider`, whose warm-up does
        `getattr(session, "bars_1m", None)` and raises when it is absent. That
        exception is swallowed by design -- warm-up may never kill startup -- so
        the only path that actually trades began every session with ZERO history
        and then grew a chart out of its own uptime. Nineteen scans of
        NO_CANDLES, due to clear at 12:29 ET on sixty post-launch bars, at which
        point Terra would have reasoned on a chart born at 11:30.
        `repair_gaps()` failed the same way, so mid-session hole repair was inert
        too.

        The capability was never missing. `self._client.bars()` is the identical
        method `TopstepXReadOnlySession.bars_1m` already delegates to; only the
        write-capable session never said it could read history. Declared HERE, as
        a session-level capability, so the provider keeps depending on ONE
        explicit interface rather than reaching into `session._client` -- a
        provider that knew about private client internals would satisfy this
        defect by hiding it in a second place.
        """
        # Contract-scoped, NOT account-scoped -- history belongs to the
        # instrument, and `_require()` would additionally demand a pinned
        # account. The provider resolves a contract during `start()` but never
        # pins, so requiring an account here would reintroduce the same silent
        # warm-up failure through a different door.
        if self.contract is None:
            raise RuntimeError("no contract resolved; call resolve_contract() first")
        return self._client.bars(self.contract.id, minutes_back=minutes_back)

    def recent_trades(self, since: datetime = None) -> list:
        acct, _ = self._require()
        now = self._clock()
        start = since or now.replace(hour=0, minute=0, second=0, microsecond=0)
        out = self._client._post("/api/Trade/search", {                 # noqa: SLF001
            "accountId": acct.id,
            "startTimestamp": start.isoformat().replace("+00:00", "Z"),
            "endTimestamp": now.isoformat().replace("+00:00", "Z")})
        return out.get("trades") or []

    # ── writes ────────────────────────────────────────────────────────────────
    def place_order(self, payload: dict) -> dict:
        self._require()
        self.writes.append({"endpoint": "/api/Order/place",
                            "at": self._clock().isoformat()})
        return self._client.place_order_raw(payload)

    def cancel_order(self, order_id) -> dict:
        acct, _ = self._require()
        self.writes.append({"endpoint": "/api/Order/cancel",
                            "at": self._clock().isoformat(), "order_id": order_id})
        return self._client.cancel_order(acct.id, order_id)

    def modify_order(self, order_id, *, size=None, limit_price=None,
                     stop_price=None, trail_price=None) -> dict:
        """EXEC-PRICE-ANCHOR-1 (2026-08-18). Move a working protective leg.

        The venue's attached brackets are TICK OFFSETS applied to the actual
        fill, so after any slippage the working stop and target sit at prices
        the thesis never named. This is the write that puts them back on the
        authorized structural invalidation and the authorized objective.

        The caller owns the rule about WHICH price is legitimate -- this hop
        only carries it. `ExecutionRunner.reanchor_protection_to_structure`
        re-authorizes the trade against the actual fill first and flattens
        rather than modifying when the original thesis no longer clears the
        production caps.
        """
        acct, _ = self._require()
        self.writes.append({"endpoint": "/api/Order/modify",
                            "at": self._clock().isoformat(), "order_id": order_id,
                            "stop_price": stop_price, "limit_price": limit_price})
        return self._client.modify_order(acct.id, order_id, size=size,
                                         limit_price=limit_price,
                                         stop_price=stop_price, trail_price=trail_price)

    def close_position(self, contract_id: str) -> dict:
        acct, _ = self._require()
        self.writes.append({"endpoint": "/api/Position/closeContract",
                            "at": self._clock().isoformat()})
        return self._client.close_position(acct.id, contract_id)

    # ── realtime ──────────────────────────────────────────────────────────────
    def _token(self) -> str:
        return self._client._session_token()                # noqa: SLF001

    def connect_user_hub(self) -> SignalRHub:
        acct, _ = self._require()
        hub = SignalRHub(USER_HUB_URL, self._token,
                         connect_factory=self._connect_factory, clock=self._clock)
        hub.connect()
        for sub in user_hub_subscriptions(acct.id):
            hub.subscribe(sub)
        self.user_hub = hub
        return hub

    def connect_market_hub(self) -> SignalRHub:
        _, contract = self._require()
        hub = SignalRHub(MARKET_HUB_URL, self._token,
                         connect_factory=self._connect_factory, clock=self._clock)
        hub.connect()
        for sub in market_hub_subscriptions(contract.id):
            hub.subscribe(sub)
        self.market_hub = hub
        return hub

    def close(self) -> None:
        for hub in (self.user_hub, self.market_hub):
            if hub is not None:
                hub.close()

    # ── evidence ──────────────────────────────────────────────────────────────
    def write_proof(self) -> dict:
        return {"write_calls_made": len(self.writes), "writes": list(self.writes)}
