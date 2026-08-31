"""The single owner of the TopstepX market socket.

    ONE MARKET HUB / ONE PUMP THREAD / ONE RECONNECT AUTHORITY / MANY SUBSCRIBERS

Before this module two components could each own a market stream: the candle
provider built its own session and connection, and the production session
started its own pump thread. Sharing one hub was not safe either — `SignalRHub.on`
kept a single handler per event, so the second consumer silently replaced the
first.

This component owns the transport and nothing else. It does not aggregate
candles, capture quotes, size trades or make decisions; consumers do that from
the events it dispatches. Ownership is enforced in code, not by convention: a
second owner is refused rather than quietly given a second reader.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

EVENT_QUOTE = "GatewayQuote"
EVENT_TRADE = "GatewayTrade"

STOPPED, RUNNING = "STOPPED", "RUNNING"


class MarketHubOwnershipError(RuntimeError):
    """Another component already owns this market stream."""
    code = "MARKET_HUB_ALREADY_OWNED"


class TopstepXMarketRuntime:
    """One connection, one pump thread, one reconnect authority."""

    def __init__(self, session, contract, *, clock=None, pump_batch: int = 25,
                 idle_wait: float = 2.0, empty_wait: float = 0.05,
                 stop_event=None) -> None:
        self.session = session
        self.contract = contract
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pump_batch = int(pump_batch)
        self._idle_wait = float(idle_wait)
        self._empty_wait = float(empty_wait)

        self.hub = None
        self.pump_owner_id: "str | None" = None
        self.pump_thread: "threading.Thread | None" = None
        self.connection_generation = 0
        self.subscribers: list = []
        self.last_message_at: "datetime | None" = None
        self.last_quote_at: "datetime | None" = None
        self.last_trade_at: "datetime | None" = None
        self.reconnects = 0
        # A consumer that owns this runtime may share its own stop signal, so
        # stopping the consumer genuinely stops the reader it started.
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._lock = threading.RLock()

    # ── ownership ─────────────────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self.pump_thread is not None and self.pump_thread.is_alive()

    @property
    def subscriber_count(self) -> int:
        return len(self.subscribers)

    @property
    def active_contracts(self) -> list:
        return [self.contract.id] if self.contract is not None else []

    def note_subscriber(self, name: str) -> None:
        """Record a consumer that registered its own handler on the hub.

        Telemetry must count what is actually attached. A consumer missing from
        this list reads as "not attached" in the ownership report even though it
        is receiving every event.
        """
        if name not in self.subscribers:
            self.subscribers.append(name)

    def attach(self, name: str, event: str, handler) -> None:
        """Register a consumer. Consumers observe; they never drain the socket."""
        if self.hub is None:
            self.connect()
        self.hub.on(event, handler)
        if name not in self.subscribers:
            self.subscribers.append(name)

    def connect(self):
        """Open the ONE market connection and register the subscription plan."""
        if self.hub is not None:
            return self.hub
        # The session registers the quote+trade subscription plan as it connects,
        # and `SignalRHub.subscribe` is keyed, so re-invoking it here would add
        # nothing. The plan is what `reconnect()` replays in order.
        hub = self.session.connect_market_hub()
        # Stamped by the runtime itself so freshness is transport truth, not a
        # figure any one consumer reports about itself.
        hub.on(EVENT_QUOTE, self._stamp_quote)
        hub.on(EVENT_TRADE, self._stamp_trade)
        self.hub = hub
        self.connection_generation = 1
        return hub

    def start(self, owner_id: str) -> "TopstepXMarketRuntime":
        """Start the single pump thread. Refuses a second owner."""
        with self._lock:
            if self.pump_owner_id is not None and self.pump_owner_id != owner_id:
                raise MarketHubOwnershipError(
                    f"{MarketHubOwnershipError.code}: '{self.pump_owner_id}' already "
                    f"pumps this market hub; '{owner_id}' must subscribe to the "
                    f"shared runtime instead of starting a second reader")
            if self.is_running:
                return self                      # same owner, idempotent
            self.connect()
            self.pump_owner_id = owner_id
            self._stop.clear()
            self.pump_thread = threading.Thread(
                target=self._pump_forever, name=f"topstepx-md[{owner_id}]", daemon=True)
            self.pump_thread.start()
            return self

    def stop(self, *, join_timeout: float = 5.0) -> None:
        """Signal the pump, join it, then close the hub exactly once."""
        self._stop.set()
        thread, self.pump_thread = self.pump_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
        if self.hub is not None:
            self.hub.close()                     # only the owner closes
            self.hub = None
        self.pump_owner_id = None

    # ── the one pump ──────────────────────────────────────────────────────────
    def _pump_forever(self) -> None:
        while not self._stop.is_set():
            hub = self.hub
            if hub is None:
                break
            try:
                if hub.pump(max_messages=self._pump_batch):
                    self.last_message_at = self._clock()
                else:
                    # `recv` normally blocks, so an empty cycle means the socket
                    # returned nothing without waiting. Spinning on that would
                    # burn a core and starve every other thread in the process.
                    self._stop.wait(self._empty_wait)
            except Exception:  # noqa: BLE001 — a dropped socket reconnects here, once
                self._reconnect()

    def _reconnect(self) -> None:
        """The ONLY reconnect authority. Subscribers never run their own."""
        try:
            self.hub.reconnect()                 # restores the plan in order
            self.connection_generation += 1
            self.reconnects += 1
            # Freshness is NOT restored here. A reconnected socket has delivered
            # nothing yet, so the stream stays stale until real data arrives.
        except Exception:  # noqa: BLE001
            self._stop.wait(self._idle_wait)

    # ── health ────────────────────────────────────────────────────────────────
    def _stamp_quote(self, args) -> None:
        self.last_quote_at = self.last_message_at = self._clock()

    def _stamp_trade(self, args) -> None:
        self.last_trade_at = self.last_message_at = self._clock()

    def _age(self, at) -> "float | None":
        return None if at is None else (self._clock() - at).total_seconds()

    def health(self) -> dict:
        return {"hub_connected": self.hub is not None,
                "pump_owner": self.pump_owner_id,
                "pump_thread_alive": self.is_running,
                "state": RUNNING if self.is_running else STOPPED,
                "connection_generation": self.connection_generation,
                "reconnects": self.reconnects,
                "last_message_age": self._age(self.last_message_at),
                "last_quote_age": self._age(self.last_quote_at),
                "last_trade_age": self._age(self.last_trade_at),
                "active_contracts": self.active_contracts,
                "subscriber_count": self.subscriber_count,
                "subscribers": list(self.subscribers)}

    def is_stale(self, max_age: float) -> bool:
        """No data yet is stale. A connected socket is not evidence of a feed."""
        age = self._age(self.last_message_at)
        return age is None or age > float(max_age)
