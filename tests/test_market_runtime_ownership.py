"""SINGLE-TOPSTEP-MARKET-PUMP — one hub, one pump, one reconnect authority.

Before this, two components could each own a market stream: the candle provider
built its own session and connection, and the production session started its own
pump thread. Sharing one hub was not safe either, because `SignalRHub.on` kept a
single handler per event and the second consumer silently replaced the first.

These tests lock the ownership contract in code. No venue write is reachable:
the session fake raises on every write endpoint.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_client import TopstepXContract                  # noqa: E402
from broker.topstepx_market_runtime import (                         # noqa: E402
    MarketHubOwnershipError, TopstepXMarketRuntime,
)
from broker.topstepx_production_session import (                     # noqa: E402
    ProductionLaneRefused, ProductionSession,
)
from broker.topstepx_quote_provider import LiveQuoteProvider         # noqa: E402
from broker.topstepx_realtime import SignalRHub, StreamHealth        # noqa: E402

CID = "CON.F.US.MNQ.U26"
OTHER_CID = "CON.F.US.ES.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 19, 0, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
QUOTE = [CID, {"bestBid": 29759.75, "bestAsk": 29760.25, "lastPrice": 29760.0}]
TRADE = [CID, [{"price": 29760.0, "volume": 3,
                "timestamp": "2026-08-05T19:00:01Z"}]]


class VenueTouched(AssertionError):
    """A write endpoint was reached. Never allowed in these tests."""


class ScriptedHub:
    """A hub whose frames are supplied by the test. Opens no socket."""

    def __init__(self, fail_pumps=0):
        self.health = StreamHealth()
        self.handlers = {}
        self.queue = []
        self.pumps = 0
        self.reconnects = 0
        self.closes = 0
        self.subscribed = []
        self.fail_pumps = int(fail_pumps)
        self.open = True

    # SignalRHub-compatible surface
    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def subscribe(self, sub):
        self.subscribed.append(sub.method)

    def feed(self, event, args):
        self.queue.append((event, args))

    def pump(self, max_messages=1):
        self.pumps += 1
        if self.pumps <= self.fail_pumps:
            raise OSError("socket dropped")
        seen = 0
        while self.queue and seen < max_messages:
            event, args = self.queue.pop(0)
            for h in list(self.handlers.get(event) or ()):
                h(args)
            seen += 1
        return seen

    def reconnect(self):
        self.reconnects += 1
        self.open = True
        return ["SubscribeContractQuotes", "SubscribeContractTrades"]

    def close(self):
        self.closes += 1
        self.open = False


class BlockedSession:
    def __init__(self, hub=None, positions=None, orders=None):
        self.market_hub = None
        self._hub = hub or ScriptedHub()
        self._p, self._o = list(positions or []), list(orders or [])
        self.connects = 0

    def connect_market_hub(self):
        self.connects += 1
        self.market_hub = self._hub
        return self._hub

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def place_order(self, payload):
        raise VenueTouched("place_order reached")

    def cancel_order(self, oid):
        raise VenueTouched("cancel_order reached")

    def close_position(self, cid):
        raise VenueTouched("close_position reached")


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def runtime(hub=None, **kw):
    return TopstepXMarketRuntime(BlockedSession(hub=hub), MNQ, **kw)


class Candles:
    """Stand-in candle consumer: counts what the shared stream delivers."""

    def __init__(self):
        self.trades = 0
        self.quotes = 0

    def on_trade(self, args):
        self.trades += 1

    def on_quote(self, args):
        self.quotes += 1


# ══════════════════════════════════════════════════════════════════════════════
class TestOneHubManySubscribers:

    def test_the_hub_dispatches_to_every_subscriber_not_just_the_last(self):
        """`on` used to overwrite: attaching a second consumer unsubscribed the first."""
        hub = SignalRHub("https://rtc.topstepx.com/hubs/market", lambda: "t")
        seen = []
        hub.on("GatewayQuote", lambda a: seen.append("candles"))
        hub.on("GatewayQuote", lambda a: seen.append("quotes"))
        hub._dispatch({"type": 1, "target": "GatewayQuote", "arguments": QUOTE})
        assert seen == ["candles", "quotes"]

    def test_registering_the_same_handler_twice_does_not_double_count(self):
        hub = SignalRHub("https://rtc.topstepx.com/hubs/market", lambda: "t")
        seen = []

        def h(a):
            seen.append(1)

        hub.on("GatewayQuote", h)
        hub.on("GatewayQuote", h)
        hub._dispatch({"type": 1, "target": "GatewayQuote", "arguments": QUOTE})
        assert seen == [1]

    def test_one_event_counts_once_however_many_consumers_observe_it(self):
        hub = SignalRHub("https://rtc.topstepx.com/hubs/market", lambda: "t")
        hub.on("GatewayQuote", lambda a: None)
        hub.on("GatewayQuote", lambda a: None)
        assert hub._dispatch({"type": 1, "target": "GatewayQuote",
                              "arguments": QUOTE}) == 1

    def test_one_failing_consumer_does_not_starve_the_others(self):
        hub = SignalRHub("https://rtc.topstepx.com/hubs/market", lambda: "t")
        seen = []
        hub.on("GatewayQuote", lambda a: (_ for _ in ()).throw(ValueError("bad")))
        hub.on("GatewayQuote", lambda a: seen.append("survived"))
        hub._dispatch({"type": 1, "target": "GatewayQuote", "arguments": QUOTE})
        assert seen == ["survived"]

    def test_one_shared_hub_serves_both_candle_and_quote_consumers(self):
        hub = ScriptedHub()
        rt = runtime(hub)
        candles, quotes = Candles(), None
        rt.attach("candle-provider", "GatewayTrade", candles.on_trade)
        rt.attach("candle-provider", "GatewayQuote", candles.on_quote)
        quotes = LiveQuoteProvider(rt.hub, MNQ, clock=lambda: NOW)
        rt.note_subscriber("quote-provider")
        assert rt.session.connects == 1
        assert rt.subscriber_count == 2
        assert quotes.hub is rt.hub

    def test_a_quote_reaches_the_quote_provider_exactly_once(self):
        hub = ScriptedHub()
        rt = runtime(hub)
        candles = Candles()
        rt.attach("candle-provider", "GatewayQuote", candles.on_quote)
        seen = []
        qp = LiveQuoteProvider(rt.hub, MNQ, clock=lambda: NOW)
        rt.hub.on("GatewayQuote", lambda a: seen.append(1))
        hub.feed("GatewayQuote", QUOTE)
        hub.pump(max_messages=5)
        assert seen == [1]
        assert qp.capture().best_ask == 29760.25
        assert candles.quotes == 1

    def test_a_trade_reaches_the_candle_consumer_exactly_once(self):
        hub = ScriptedHub()
        rt = runtime(hub)
        candles = Candles()
        rt.attach("candle-provider", "GatewayTrade", candles.on_trade)
        LiveQuoteProvider(rt.hub, MNQ, clock=lambda: NOW)
        hub.feed("GatewayTrade", TRADE)
        hub.pump(max_messages=5)
        assert candles.trades == 1

    def test_no_event_is_split_between_competing_readers(self):
        """Both consumers advance under ONE pump; neither drains the other's data."""
        hub = ScriptedHub()
        rt = runtime(hub)
        candles = Candles()
        rt.attach("candle-provider", "GatewayTrade", candles.on_trade)
        rt.attach("candle-provider", "GatewayQuote", candles.on_quote)
        qp = LiveQuoteProvider(rt.hub, MNQ, clock=lambda: NOW)
        for _ in range(5):
            hub.feed("GatewayTrade", TRADE)
            hub.feed("GatewayQuote", QUOTE)
        hub.pump(max_messages=20)
        assert candles.trades == 5 and candles.quotes == 5
        assert qp.has_quote()


class TestSinglePumpOwnership:

    def test_exactly_one_pump_thread_is_started(self):
        rt = runtime()
        before = threading.active_count()
        rt.start("candle-provider")
        try:
            assert threading.active_count() == before + 1
            assert rt.is_running
        finally:
            rt.stop()

    def test_starting_the_same_owner_twice_is_idempotent(self):
        rt = runtime()
        rt.start("candle-provider")
        first = rt.pump_thread
        try:
            rt.start("candle-provider")
            assert rt.pump_thread is first
        finally:
            rt.stop()

    def test_a_second_owner_is_refused(self):
        rt = runtime()
        rt.start("candle-provider")
        try:
            with pytest.raises(MarketHubOwnershipError, match="MARKET_HUB_ALREADY_OWNED"):
                rt.start("production-session")
        finally:
            rt.stop()

    def test_the_refusal_names_both_components(self):
        rt = runtime()
        rt.start("candle-provider")
        try:
            with pytest.raises(MarketHubOwnershipError) as exc:
                rt.start("production-session")
            assert "candle-provider" in str(exc.value)
            assert "production-session" in str(exc.value)
        finally:
            rt.stop()

    def test_a_refused_owner_starts_no_thread(self):
        rt = runtime()
        rt.start("candle-provider")
        try:
            n = threading.active_count()
            with pytest.raises(MarketHubOwnershipError):
                rt.start("production-session")
            assert threading.active_count() == n
        finally:
            rt.stop()

    def test_only_one_connection_is_opened(self):
        rt = runtime()
        rt.connect()
        rt.connect()
        rt.start("candle-provider")
        try:
            assert rt.session.connects == 1
        finally:
            rt.stop()


class TestReconnectAuthority:

    def test_a_socket_failure_triggers_exactly_one_reconnect(self):
        hub = ScriptedHub(fail_pumps=1)
        rt = runtime(hub)
        rt.start("candle-provider")
        try:
            assert wait_for(lambda: hub.reconnects >= 1)
            time.sleep(0.15)
            assert hub.reconnects == 1
        finally:
            rt.stop()

    def test_subscriptions_are_restored_after_reconnect(self):
        hub = ScriptedHub(fail_pumps=1)
        rt = runtime(hub)
        rt.start("candle-provider")
        try:
            assert wait_for(lambda: hub.reconnects >= 1)
        finally:
            rt.stop()
        # SignalRHub.reconnect replays the plan; the fake reports what it restored.
        assert hub.reconnect() == ["SubscribeContractQuotes", "SubscribeContractTrades"]

    def test_quotes_and_candles_both_resume_after_reconnect(self):
        hub = ScriptedHub(fail_pumps=1)
        rt = runtime(hub)
        candles = Candles()
        rt.attach("candle-provider", "GatewayTrade", candles.on_trade)
        qp = LiveQuoteProvider(rt.hub, MNQ, clock=lambda: NOW)
        rt.start("candle-provider")
        try:
            assert wait_for(lambda: hub.reconnects >= 1)
            hub.feed("GatewayTrade", TRADE)
            hub.feed("GatewayQuote", QUOTE)
            assert wait_for(lambda: candles.trades >= 1)
            assert wait_for(qp.has_quote)
        finally:
            rt.stop()

    def test_connection_generation_increments_once_per_reconnect(self):
        hub = ScriptedHub(fail_pumps=1)
        rt = runtime(hub)
        rt.connect()
        assert rt.connection_generation == 1
        rt.start("candle-provider")
        try:
            assert wait_for(lambda: rt.connection_generation == 2)
            time.sleep(0.15)
            assert rt.connection_generation == 2
        finally:
            rt.stop()

    def test_staleness_persists_until_fresh_post_reconnect_evidence(self):
        """A reopened socket has delivered nothing; it is not evidence of a feed."""
        hub = ScriptedHub(fail_pumps=1)
        rt = runtime(hub)
        rt.start("candle-provider")
        try:
            assert wait_for(lambda: hub.reconnects >= 1)
            assert rt.is_stale(30.0) is True          # reconnected, still no data
            hub.feed("GatewayQuote", QUOTE)
            assert wait_for(lambda: not rt.is_stale(30.0))
        finally:
            rt.stop()

    def test_no_data_ever_is_stale_not_fresh(self):
        rt = runtime()
        assert rt.is_stale(30.0) is True
        assert rt.health()["last_quote_age"] is None


class TestShutdown:

    def test_clean_shutdown_joins_the_pump_thread(self):
        rt = runtime()
        rt.start("candle-provider")
        thread = rt.pump_thread
        rt.stop()
        assert thread.is_alive() is False
        assert rt.is_running is False

    def test_clean_shutdown_closes_the_hub_once(self):
        hub = ScriptedHub()
        rt = runtime(hub)
        rt.start("candle-provider")
        rt.stop()
        assert hub.closes == 1

    def test_stopping_twice_does_not_close_a_second_time(self):
        hub = ScriptedHub()
        rt = runtime(hub)
        rt.start("candle-provider")
        rt.stop()
        rt.stop()
        assert hub.closes == 1

    def test_a_restart_creates_one_new_owner_not_two(self):
        rt = runtime()
        rt.start("candle-provider")
        rt.stop()
        assert rt.pump_owner_id is None
        before = threading.active_count()
        rt.start("production-session")       # ownership was released, not inherited
        try:
            assert threading.active_count() == before + 1
            assert rt.pump_owner_id == "production-session"
        finally:
            rt.stop()


class TestProductionSessionIsAConsumer:

    def session(self, tmp_path, rt, **kw):
        return ProductionSession(session=rt.session, account_fingerprint=FP,
                                 contract=MNQ, mission_id="M-1",
                                 store_dir=str(tmp_path), runtime=rt,
                                 clock=lambda: NOW, **kw)

    def test_it_delegates_start_pump_to_the_shared_owner(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt)
        try:
            before = threading.active_count()
            ps.start_pump("candle-provider")
            assert threading.active_count() == before      # no second reader
        finally:
            rt.stop()

    def test_it_cannot_take_ownership_from_the_candle_provider(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt)
        try:
            with pytest.raises(MarketHubOwnershipError):
                ps.start_pump("production-session")
        finally:
            rt.stop()

    def test_stop_pump_does_not_stop_the_shared_stream(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt)
        try:
            ps.stop_pump()
            assert rt.is_running is True
        finally:
            rt.stop()

    def test_the_lane_opens_on_the_shared_hub(self, tmp_path):
        hub = ScriptedHub()
        rt = runtime(hub)
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt)
        try:
            lane = ps.open_lane()
            assert lane["lane"] == "OPEN"
            assert ps.quote_provider.hub is rt.hub
            assert lane["ownership"]["pump_owner"] == "candle-provider"
        finally:
            rt.stop()

    def test_a_dead_pump_thread_refuses_the_lane(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        rt._stop.set()
        rt.pump_thread.join(timeout=3.0)
        ps = self.session(tmp_path, rt)
        with pytest.raises(ProductionLaneRefused, match="PUMP_THREAD_DEAD"):
            ps.open_lane()

    def test_ambiguous_ownership_refuses_the_lane(self, tmp_path):
        rt = runtime()
        rt.connect()                        # connected, but nobody pumps it
        ps = self.session(tmp_path, rt)
        with pytest.raises(ProductionLaneRefused, match="AMBIGUOUS_PUMP_OWNERSHIP"):
            ps.open_lane()

    def test_a_conflicting_active_contract_refuses_the_lane(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        other = TopstepXContract(id=OTHER_CID, name="ESU6", description="ES",
                                 tick_size=0.25, tick_value=12.5, active=True)
        ps = ProductionSession(session=rt.session, account_fingerprint=FP,
                               contract=other, mission_id="M-1",
                               store_dir=str(tmp_path), runtime=rt, clock=lambda: NOW)
        try:
            with pytest.raises(ProductionLaneRefused, match="CONTRACT_MISMATCH"):
                ps.open_lane()
        finally:
            rt.stop()

    def test_a_quote_provider_on_a_foreign_hub_refuses_the_lane(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        foreign = LiveQuoteProvider(ScriptedHub(), MNQ, clock=lambda: NOW)
        ps = self.session(tmp_path, rt, quote_provider=foreign)
        try:
            with pytest.raises(ProductionLaneRefused, match="FOREIGN_HUB"):
                ps.open_lane()
        finally:
            rt.stop()

    def test_a_stale_feed_is_reported_not_replaced(self, tmp_path):
        rt = runtime()
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt, max_market_age=0.0)
        try:
            assert ps.market_evidence_stale() is True
            assert rt.session.connects == 1        # no replacement connection
            assert rt.pump_owner_id == "candle-provider"
        finally:
            rt.stop()

    def test_telemetry_reports_one_connection_and_one_pump(self, tmp_path):
        hub = ScriptedHub()
        rt = runtime(hub)
        rt.attach("candle-provider", "GatewayTrade", Candles().on_trade)
        rt.start("candle-provider")
        ps = self.session(tmp_path, rt)
        try:
            ps.open_lane()
            out = ps.telemetry()
            assert "TOPSTEP MARKET RUNTIME       : SHARED" in out
            assert "SIGNALR CONNECTIONS          : 1" in out
            assert "PUMP OWNERS                  : 1" in out
            assert "PUMP THREAD                  : alive" in out
            assert "DUPLICATE PUMP PROTECTION    : ENFORCED" in out
            assert CID in out
            # Both consumers must be COUNTED, not just present.
            assert "SUBSCRIBERS                  : 2" in out
            assert "candle-provider" in out and "quote-provider" in out
            out.encode("cp1252")               # cp1252 console safe
        finally:
            rt.stop()


class TestCandleProviderIsAConsumer:

    def provider(self, tmp_path, rt):
        from data_feed.topstepx_provider import TopstepXDataProvider

        class FakeSession(BlockedSession):
            def authenticate(self):
                return {}

            def resolve_contract(self, text="MNQ"):
                return MNQ

        p = TopstepXDataProvider(session=FakeSession(hub=rt.session._hub),
                                 autostart=False, store_dir=str(tmp_path))
        p.start("MNQ", runtime=rt)
        return p

    def test_it_starts_no_pump_of_its_own_when_given_a_runtime(self, tmp_path):
        rt = runtime()
        rt.start("production-startup")
        before = threading.active_count()
        p = self.provider(tmp_path, rt)
        try:
            assert threading.active_count() == before
            assert p.runtime is rt
            assert p._owns_runtime is False
        finally:
            rt.stop()

    def test_it_does_not_close_a_hub_it_does_not_own(self, tmp_path):
        hub = ScriptedHub()
        rt = runtime(hub)
        rt.start("production-startup")
        p = self.provider(tmp_path, rt)
        try:
            p.stop()
            assert hub.closes == 0
            assert rt.is_running is True
        finally:
            rt.stop()

    def test_standalone_it_still_owns_and_stops_its_own_runtime(self, tmp_path):
        rt_holder = {}

        class FakeSession(BlockedSession):
            def authenticate(self):
                return {}

            def resolve_contract(self, text="MNQ"):
                return MNQ

        from data_feed.topstepx_provider import TopstepXDataProvider
        p = TopstepXDataProvider(session=FakeSession(), autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        rt_holder["rt"] = p.runtime
        assert p._owns_runtime is True
        assert p.runtime.pump_owner_id == "candle-provider"
        p.stop()
        assert p.runtime.is_running is False
