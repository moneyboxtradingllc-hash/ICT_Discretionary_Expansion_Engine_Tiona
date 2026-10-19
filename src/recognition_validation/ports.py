"""Availability-controlled offline ports and deny-by-default doubles.

`DecisionClock` is the historical market clock. It is NOT the clock used for
external authorization validity, request durations or budget leases: that is
real UTC (`real_utc_now`), so replaying an old date can never make an expired
authorization look valid.

Every write or network method on a double raises and is logged; no real
endpoint object is constructed anywhere in this module.
"""
from __future__ import annotations

import contextlib
import socket
import ast
from pathlib import Path
from functools import lru_cache
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from recognition_validation import contracts as C


def real_utc_now() -> datetime:
    """Real transport/authorization time. Never the historical decision clock."""
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _window_predicate():
    """Load the actual entrypoint functions without importing its dotenv/startup code."""
    path = Path(__file__).resolve().parents[2] / "tools/topstepx_production_session.py"
    names = {"_now_et", "effective_window", "production_window_open"}
    functions = [n for n in ast.parse(path.read_text(encoding="utf-8")).body
                 if isinstance(n, ast.FunctionDef) and n.name in names]
    C.require(len(functions) == len(names), "WINDOW_ADAPTER_UNAVAILABLE", "/production_window")
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["production_window_open"]


def production_window_open(moment):
    from broker import topstepx_session_authorization as SA
    return _window_predicate()(moment.astimezone(ZoneInfo(SA.PRODUCTION_WINDOW_TZ)))


class DecisionClock:
    """Deterministic historical market progression; never moves backwards."""

    def __init__(self, start: datetime):
        C.require(start.tzinfo is not None, "TIMEZONE_REQUIRED", "/clock")
        self._now = start.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def __call__(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        C.require(moment.tzinfo is not None, "TIMEZONE_REQUIRED", "/clock")
        moment = moment.astimezone(timezone.utc)
        C.require(moment >= self._now, "CLOCK_MOVED_BACKWARDS", "/clock", moment.isoformat())
        self._now = moment


class LocalCandlePort:
    """`fetch_1m_candles` over releases available by the decision clock only."""

    def __init__(self, stream, clock: DecisionClock, *, symbol: str = "MNQ"):
        self.stream, self.clock, self.symbol = stream, clock, symbol
        self.calls: list = []

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        C.require(symbol == self.symbol, "SYMBOL_MISMATCH", "/symbol", str(symbol))
        rows = self.stream.candles_at(self.clock.now(), lookback=lookback_bars)
        self.calls.append((self.clock.now().isoformat(), lookback_bars, len(rows)))
        return rows

    def stop(self):
        return None


@dataclass(frozen=True)
class MissingQuote:
    reason: str


class LocalQuotePort:
    """Archived or explicitly constructed quotes, available by t; never a candle close."""

    def __init__(self, quotes, clock: DecisionClock, *, contract_id: str, origin: str):
        C.require(origin in ("ARCHIVED", "CONSTRUCTED"), "QUOTE_ORIGIN_UNKNOWN", "/origin", origin)
        self.clock, self.contract_id, self.origin = clock, contract_id, origin
        self._quotes = sorted(quotes, key=lambda q: C.instant(q["captured_at_utc"]))

    def capture(self):
        from broker.topstepx_slippage import QuoteCapture
        now = self.clock.now()
        visible = [q for q in self._quotes if C.instant(q["captured_at_utc"]) <= now]
        if not visible:
            return MissingQuote("no_quote_available_by_decision_time")
        quote = visible[-1]
        if quote.get("contract_id") != self.contract_id:
            return MissingQuote("quote_contract_mismatch")
        captured = C.instant(quote["captured_at_utc"])
        return QuoteCapture(captured_at=captured, best_bid=float(quote["bid"]), best_ask=float(quote["ask"]),
                            last_trade=float(quote.get("last", quote["bid"])), contract_id=self.contract_id,
                            market_data_age_seconds=(now - captured).total_seconds())


class NetworkRefused(ConnectionError):
    """A network connection was attempted inside an offline run."""


@dataclass
class NetworkGuard:
    """Context manager: every socket connect raises and is recorded."""

    attempts: list = field(default_factory=list)

    @contextlib.contextmanager
    def deny(self):
        original_connect = socket.socket.connect
        original_create = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        guard = self

        def connect(sock, address, *args, **kwargs):
            guard.attempts.append(("connect", repr(address)))
            raise NetworkRefused(f"offline run refused connect to {address!r}")

        def create_connection(address, *args, **kwargs):
            guard.attempts.append(("create_connection", repr(address)))
            raise NetworkRefused(f"offline run refused connection to {address!r}")

        def getaddrinfo(host, *args, **kwargs):
            guard.attempts.append(("getaddrinfo", repr(host)))
            raise NetworkRefused(f"offline run refused name resolution for {host!r}")
        socket.socket.connect = connect
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        try:
            yield self
        finally:
            socket.socket.connect = original_connect
            socket.create_connection = original_create
            socket.getaddrinfo = original_getaddrinfo


class VenueWriteRefused(AssertionError):
    """A venue write was reached. Recorded, never performed."""


class Hub:
    def __init__(self):
        self.handlers: dict = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event, args):
        for handler in self.handlers.get(event, []):
            handler(args)


class RefusingVenueSession:
    """Read-only synthetic venue: flat account, no orders; every write raises."""

    def __init__(self, *, account_id: int = 77):
        self.market_hub = Hub()
        self.account = type("SyntheticAccount", (), {"id": account_id})()
        self.writes: list = []

    def open_positions(self):
        return []

    def open_orders(self):
        return []

    def query_orders(self, *, statuses=None, contract_id=None):
        return []

    def recent_trades(self, since=None):
        return []

    def _refuse(self, name, payload):
        self.writes.append((name, payload))
        raise VenueWriteRefused(f"offline venue refused {name}")

    def place_order(self, payload):
        self._refuse("place_order", dict(payload))

    def cancel_order(self, order_id):
        self._refuse("cancel_order", order_id)

    def modify_order(self, order_id, **kwargs):
        self._refuse("modify_order", order_id)

    def close_position(self, contract_id):
        self._refuse("close_position", contract_id)


class OfflineRuntime:
    """The runtime surface ProductionLoop reads for health; no pump, no socket."""

    def __init__(self, hub, contract):
        self.hub, self.contract = hub, contract
        self.pump_owner_id = "production-startup"

    def health(self):
        return {"pump_owner": "production-startup", "pump_thread_alive": True,
                "active_contracts": [self.contract.id], "last_quote_age": 0.5,
                "connection_generation": 1, "subscriber_count": 2,
                "subscribers": ["candle-provider", "quote-provider"]}

    def note_subscriber(self, name):
        return None

    @property
    def is_running(self):
        return True


def synthetic_contract(contract_id: str):
    from broker.topstepx_client import TopstepXContract
    return TopstepXContract(id=contract_id, name="MNQ-OFFLINE", description="MNQ offline replay",
                            tick_size=0.25, tick_value=0.5, active=True)


def synthetic_authorization(store_dir, *, session_id: str, contract_id: str, session_date: str,
                            issued_at: str, account_fingerprint: str = "acct:offline-replay"):
    """A replay-local session authorization; never an operator authorization."""
    import os
    from broker import topstepx_session_authorization as SA
    auth = SA.SessionAuthorization(
        session_id=session_id, account_fingerprint=account_fingerprint, contract_id=contract_id,
        session_date=session_date, decision_window=SA.window_text(session_date), issued_at=issued_at,
        path=os.path.join(str(store_dir), f"session_auth_{session_id}.json"),
        daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD)
    auth.authorization_fingerprint = auth.fingerprint()
    return auth


def minute_after(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp).astimezone(timezone.utc) + timedelta(minutes=1)
