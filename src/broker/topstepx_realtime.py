"""TOPSTEPX-INTEGRATION — native SignalR clients for the ProjectX realtime hubs.

Official surface (ProjectX Gateway API — Realtime Updates, verified 2026-08-04):

  User hub    https://rtc.topstepx.com/hubs/user?access_token=<JWT>
    SubscribeAccounts()            -> GatewayUserAccount
    SubscribeOrders(accountId)     -> GatewayUserOrder
    SubscribePositions(accountId)  -> GatewayUserPosition
    SubscribeTrades(accountId)     -> GatewayUserTrade

  Market hub  https://rtc.topstepx.com/hubs/market?access_token=<JWT>
    SubscribeContractQuotes(contractId) -> GatewayQuote(contractId, data)
    SubscribeContractTrades(contractId) -> GatewayTrade(contractId, data)

Why this is written by hand rather than pulled from a SignalR package: the
repository has `websockets` and no SignalR client, and the mission forbids a
runtime dependency on another bot's implementation. The SignalR JSON protocol
that these hubs need is small — a negotiate POST, a handshake frame, then
record-separated JSON messages — so implementing it natively costs less than
carrying a dependency, and it keeps every framing decision inspectable.

SUBSCRIPTION DETERMINISM is the property this module exists to guarantee. A
reconnect that silently drops a subscription produces the worst failure this
venue can hand us: a live-looking connection that has stopped delivering fills.
So subscriptions are held as an ordered, de-duplicated plan and REPLAYED in the
same order on every (re)connect — never re-derived from ambient state.

This module performs NO write operations. It subscribes and it reads. There is
no order/position mutation path here, by construction.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlencode

# SignalR frames are terminated by the ASCII record separator, not by newline.
_RS = "\x1e"

USER_HUB_URL = "https://rtc.topstepx.com/hubs/user"
MARKET_HUB_URL = "https://rtc.topstepx.com/hubs/market"


class RealtimeError(RuntimeError):
    """The hub could not be connected, or refused a subscription."""


@dataclass(frozen=True)
class Subscription:
    """One hub method invocation and the event it causes to start flowing."""
    method: str                 # e.g. "SubscribeOrders"
    args: tuple                 # e.g. (accountId,)
    event: str                  # e.g. "GatewayUserOrder"

    def key(self) -> tuple:
        return (self.method, self.args)


@dataclass
class StreamHealth:
    """What the preflight needs to say about a hub without guessing.

    `last_event_at` is the freshness signal. A connected socket with no events
    is not proof of a working feed — outside RTH it is even expected — so
    freshness is REPORTED and judged by the caller against its own window,
    never silently treated as success.
    """
    connected: bool = False
    handshake_ok: bool = False
    subscriptions: list = field(default_factory=list)
    events_seen: dict = field(default_factory=dict)
    last_event_at: Optional[datetime] = None
    reconnects: int = 0
    resubscribed_in_order: bool = False
    errors: list = field(default_factory=list)

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.last_event_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - self.last_event_at).total_seconds()

    def is_stale(self, max_age: float, now: Optional[datetime] = None) -> bool:
        """No event ever, or the newest one is older than `max_age`."""
        age = self.age_seconds(now)
        return age is None or age > max_age


class SignalRHub:
    """Minimal SignalR JSON-protocol client for one ProjectX hub.

    `connect_factory` is the seam that makes the whole class testable without a
    network: it is called as connect_factory(url) and must return an object with
    send(str), recv() -> str and close(). The default builds a real WebSocket.
    """

    def __init__(self, hub_url: str, token_provider: Callable[[], str], *,
                 connect_factory: Optional[Callable[[str], Any]] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 max_reconnects: int = 5,
                 backoff_base: float = 1.0, backoff_max: float = 30.0,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self.hub_url = hub_url
        self._token_provider = token_provider
        self._connect_factory = connect_factory or _default_ws_connect
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_reconnects = int(max_reconnects)
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self._sleep = sleep or time.sleep

        self._conn: Any = None
        self._invocation_id = 0
        # Ordered plan + membership set: order gives deterministic replay, the
        # set makes a duplicate subscribe a no-op instead of a second stream.
        self._plan: list = []
        self._plan_keys: set = set()
        self.health = StreamHealth()
        self._handlers: dict = {}

    # ── connection ────────────────────────────────────────────────────────────
    def _url_with_token(self) -> str:
        """Socket URL: documented hub address, WebSocket scheme, token attached.

        The official docs give the hub as an https:// address and configure the
        SignalR client with `skipNegotiation: true` +
        `transport: HttpTransportType.WebSockets`. That client rewrites the
        scheme to wss:// internally before opening the socket — a detail the
        docs never state because the JS library hides it.

        A raw WebSocket library does not hide it: handing `websockets` an
        https:// URL raises InvalidURI, which is exactly how the live preflight
        failed on 2026-08-04 after the entire REST path had already passed. The
        documented constant stays https:// (it is what the docs say, and it is
        what evidence should report); only the socket call is rewritten.

        skipNegotiation means there is deliberately NO /negotiate round trip.
        """
        return f"{_ws_scheme(self.hub_url)}?{urlencode({'access_token': self._token_provider()})}"

    def connect(self) -> None:
        """Open the socket and complete the SignalR handshake.

        The token rides the query string because that is what the hubs accept;
        it is therefore never logged — `describe()` and every error path below
        report the hub path only.
        """
        try:
            self._conn = self._connect_factory(self._url_with_token())
        except Exception as exc:  # noqa: BLE001 — surface as one venue error type
            self.health.connected = False
            self.health.errors.append(f"connect_failed:{type(exc).__name__}")
            raise RealtimeError(f"cannot open {self.hub_url}: {type(exc).__name__}") from exc
        self.health.connected = True
        self._handshake()

    def _handshake(self) -> None:
        self._send_raw({"protocol": "json", "version": 1})
        raw = self._conn.recv()
        # An empty object is the documented success handshake; anything with an
        # `error` key is a refusal we must not paper over.
        for msg in _split_frames(raw):
            if msg.get("error"):
                self.health.handshake_ok = False
                raise RealtimeError(f"handshake refused by {self.hub_url}: {msg['error']}")
        self.health.handshake_ok = True

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — closing must never raise upward
                pass
        self._conn = None
        self.health.connected = False

    # ── subscriptions ─────────────────────────────────────────────────────────
    def subscribe(self, sub: Subscription) -> None:
        """Register a subscription in the plan and invoke it once.

        Re-subscribing the same method+args is deliberately a no-op: duplicate
        subscriptions produce duplicate events, and duplicated fill events are
        how a position gets double-counted.
        """
        if sub.key() in self._plan_keys:
            return
        self._plan.append(sub)
        self._plan_keys.add(sub.key())
        self._invoke(sub)

    def _invoke(self, sub: Subscription) -> None:
        self._invocation_id += 1
        self._send_raw({"type": 1, "invocationId": str(self._invocation_id),
                        "target": sub.method, "arguments": list(sub.args)})
        if sub.event not in self.health.subscriptions:
            self.health.subscriptions.append(sub.event)

    def on(self, event: str, handler: Callable[[list], None]) -> None:
        """Add a handler for `event`. Many consumers may share one event.

        This deliberately APPENDS. A single-slot mapping silently replaced the
        previous handler, so attaching the quote provider to a hub the candle
        provider was already using would have unsubscribed the candle provider
        without any error — the exact failure that makes one shared stream
        unsafe. Registering the identical handler twice is still a no-op, so a
        repeated attach cannot double-count an event.
        """
        handlers = self._handlers.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    def replay_subscriptions(self) -> list:
        """Re-invoke every planned subscription, in the original order.

        Returns the order actually replayed so a caller (and the preflight
        evidence) can assert determinism rather than trust it.
        """
        replayed = []
        for sub in self._plan:
            self._invoke(sub)
            replayed.append(sub.method)
        return replayed

    def reconnect(self) -> list:
        """Reopen the socket and deterministically restore the subscription plan."""
        planned = [s.method for s in self._plan]
        self.close()
        delay = self.backoff_base
        last: Optional[Exception] = None
        for attempt in range(self.max_reconnects):
            try:
                self.connect()
                replayed = self.replay_subscriptions()
                self.health.reconnects += 1
                self.health.resubscribed_in_order = (replayed == planned)
                if not self.health.resubscribed_in_order:
                    raise RealtimeError(
                        f"resubscription order diverged: planned {planned}, replayed {replayed}")
                return replayed
            except RealtimeError as exc:
                last = exc
                if attempt < self.max_reconnects - 1:
                    self._sleep(delay)
                    delay = min(delay * 2, self.backoff_max)
        raise RealtimeError(f"reconnect to {self.hub_url} failed after "
                            f"{self.max_reconnects} attempts: {last}")

    # ── receive ───────────────────────────────────────────────────────────────
    def pump(self, max_messages: int = 1) -> int:
        """Read up to `max_messages` frames and dispatch them. Returns count.

        A malformed frame is counted and skipped rather than raised: one bad
        message from the venue must not tear down a healthy subscription, and
        the error is preserved on `health.errors` where evidence can see it.
        """
        seen = 0
        for _ in range(max_messages):
            try:
                raw = self._conn.recv()
            except Exception as exc:  # noqa: BLE001
                self.health.errors.append(f"recv_failed:{type(exc).__name__}")
                break
            if raw is None:
                break
            for msg in _split_frames(raw):
                seen += self._dispatch(msg)
        return seen

    def _dispatch(self, msg: dict) -> int:
        mtype = msg.get("type")
        if mtype == 6:          # ping/keepalive — traffic, not an event
            return 0
        if mtype != 1:          # completions, close frames, protocol chatter
            if msg.get("error"):
                self.health.errors.append(f"hub_error:{msg['error']}")
            return 0
        target = msg.get("target") or ""
        args = msg.get("arguments") or []
        self.health.events_seen[target] = self.health.events_seen.get(target, 0) + 1
        self.health.last_event_at = self._clock()
        for handler in list(self._handlers.get(target) or ()):
            try:
                handler(args)
            except Exception as exc:  # noqa: BLE001 — a handler bug is not a feed failure
                self.health.errors.append(f"handler_error:{target}:{type(exc).__name__}")
        # ONE event counts once however many consumers observed it. Counting per
        # handler would inflate the feed's own evidence of activity.
        return 1

    def _send_raw(self, obj: dict) -> None:
        if self._conn is None:
            raise RealtimeError(f"{self.hub_url} is not connected")
        self._conn.send(json.dumps(obj) + _RS)

    def describe(self) -> dict:
        """Health snapshot. Contains no token and no account name by construction."""
        return {"hub": self.hub_url,
                "connected": self.health.connected,
                "handshake_ok": self.health.handshake_ok,
                "subscriptions": list(self.health.subscriptions),
                "events_seen": dict(self.health.events_seen),
                "last_event_at": (self.health.last_event_at.isoformat()
                                  if self.health.last_event_at else None),
                "reconnects": self.health.reconnects,
                "resubscribed_in_order": self.health.resubscribed_in_order,
                "errors": list(self.health.errors)}


def _ws_scheme(url: str) -> str:
    """https -> wss, http -> ws. Any other scheme is passed through untouched."""
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    return url


def _split_frames(raw: str) -> list:
    """Split a SignalR payload into JSON objects on the record separator.

    One WebSocket read can carry several frames; a frame that will not parse is
    skipped rather than killing the read loop.
    """
    out = []
    for chunk in (raw or "").split(_RS):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return out


def _default_ws_connect(url: str):
    """Real WebSocket transport. Imported lazily so tests never need the package."""
    try:
        from websockets.sync.client import connect as ws_connect
    except Exception as exc:  # noqa: BLE001
        raise RealtimeError(
            "the `websockets` package is required for TopstepX realtime hubs"
        ) from exc
    return ws_connect(url, open_timeout=15, close_timeout=5)


# ── hub builders ──────────────────────────────────────────────────────────────
def user_hub_subscriptions(account_id: int) -> list:
    """The four documented user-hub subscriptions, in a fixed order.

    Order is part of the contract here: reconnect replays this exact sequence,
    and the preflight asserts the replay matches.
    """
    return [
        Subscription("SubscribeAccounts", (), "GatewayUserAccount"),
        Subscription("SubscribeOrders", (int(account_id),), "GatewayUserOrder"),
        Subscription("SubscribePositions", (int(account_id),), "GatewayUserPosition"),
        Subscription("SubscribeTrades", (int(account_id),), "GatewayUserTrade"),
    ]


def market_hub_subscriptions(contract_id: str) -> list:
    """Quote and trade streams for one contract, in a fixed order."""
    return [
        Subscription("SubscribeContractQuotes", (str(contract_id),), "GatewayQuote"),
        Subscription("SubscribeContractTrades", (str(contract_id),), "GatewayTrade"),
    ]
