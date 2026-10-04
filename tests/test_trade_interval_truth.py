from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from data_feed.trade_interval_truth import (  # noqa: E402
    COMPLETE, CLOSED, INCOMPLETE, TradeIntervalTruth, TradeIntervalTruthError,
)
from data_feed.provider_interface import DataFeedError  # noqa: E402
from data_feed.topstepx_provider import MinuteCandleAggregator, TopstepXDataProvider  # noqa: E402
from broker.topstepx_market_runtime import TopstepXMarketRuntime  # noqa: E402
from broker.topstepx_realtime import RealtimeError, SignalRHub  # noqa: E402

CID = "CON.F.US.MNQ.U26"
OTHER = "CON.F.US.MNQ.Z26"
BASE = datetime(2026, 10, 2, 14, 43, 40, tzinfo=timezone.utc)
ANCHOR = datetime(2026, 10, 2, 14, 43, 46, 912000, tzinfo=timezone.utc)


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def make_tracker(tmp_path, *, contract=CID, now=None, path=None):
    return TradeIntervalTruth(contract, str(path or (tmp_path / "intervals.json")),
                              clock=Clock(now or ANCHOR))


def row(price, at, contract=CID):
    return {"contractId": contract, "timestamp": at.isoformat(), "price": price,
            "volume": 1}


def opened(tracker, anchor=ANCHOR):
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    # A socket epoch is pending until a valid unique same-contract raw trade
    # proves GatewayTrade is delivering. This event also seeds the event-time
    # frontier captured by subsequent registration.
    observe(tracker, row(100, anchor), received=BASE + timedelta(seconds=1))
    return tracker._register_interval(CID, anchor, 100, "test_market_reference")


def observe(tracker, *rows, epoch="epoch-A", received=None, envelope=CID):
    tracker.observe_gateway_event(
        [envelope, list(rows)], epoch_id=epoch,
        received_at=received or BASE + timedelta(seconds=9))


def provider_with_live_trade(tmp_path, *, epoch_id="runtime-A", prove=True):
    now = datetime.now(timezone.utc)
    clock = Clock(now)
    tracker = TradeIntervalTruth(CID, str(tmp_path / f"{epoch_id}.json"), clock=clock)
    tracker.begin_coverage_epoch(CID, epoch_id, now)
    if prove:
        tracker.observe_gateway_event(
            [CID, [row(100, ANCHOR)]], epoch_id=epoch_id, received_at=now)
    provider = object.__new__(TopstepXDataProvider)
    provider._lock = threading.Lock()
    provider.trade_interval_truth = tracker
    provider.contract = SimpleNamespace(id=CID, tick_size=0.25)
    provider._trade_interval_epoch_id = epoch_id
    provider._trade_interval_runtime_epoch_id = epoch_id
    provider._stale_seconds = 120.0
    provider.runtime = SimpleNamespace(
        contract=SimpleNamespace(id=CID), hub=object(), is_running=True,
        _coverage_epoch_id=lambda: epoch_id, _clock=clock,
        last_trade_at=now if prove else None, last_quote_at=now if prove else None)
    return provider, clock


class QueueSocket:
    def __init__(self):
        self.frames = []

    def send(self, _data):
        return None

    def recv(self):
        if not self.frames:
            return '{"type":6}\x1e'
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    def close(self):
        return None


def realtime_provider_path(tmp_path):
    clock = Clock(datetime.now(timezone.utc))
    contract = SimpleNamespace(id=CID, tick_size=0.25)
    hub = SignalRHub("https://example.invalid/market", lambda: "test-token", clock=clock)
    hub._conn = QueueSocket()
    hub.health.connected = True
    runtime = TopstepXMarketRuntime(
        SimpleNamespace(connect_market_hub=lambda: hub), contract, clock=clock)
    provider = object.__new__(TopstepXDataProvider)
    provider._lock = threading.Lock()
    provider._stop = threading.Event()
    provider._stale_seconds = 120.0
    provider.contract = contract
    provider.runtime = runtime
    provider.trade_interval_truth = TradeIntervalTruth(
        CID, str(tmp_path / "realtime-intervals.json"), clock=clock)
    provider._trade_interval_epoch_id = None
    provider._trade_interval_runtime_epoch_id = None
    provider.aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    provider.wake_registry = None
    provider.store_dir = str(tmp_path)
    provider._persist = lambda _rows: None
    provider._trim = lambda: None
    provider.last_quote = {}
    runtime.add_coverage_listener(provider._on_coverage_event)
    runtime.connect()
    # The hub pump is driven synchronously below; expose a live owner state so
    # provider authority checks exercise the real runtime contract.
    runtime.pump_thread = SimpleNamespace(is_alive=lambda: True)
    runtime.attach("candle-provider", "GatewayTrade", provider._on_trade,
                   integrity_critical=True)
    return provider, runtime, hub, clock


def dispatch_gateway_trade(hub, at, price=100):
    return hub._dispatch({
        "type": 1, "target": "GatewayTrade",
        "arguments": [CID, [row(price, at)]],
    })


def test_exact_timestamp_anchor_excludes_pre_anchor_trade(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    observe(tracker,
            row(100, ANCHOR - timedelta(milliseconds=112)),
            row(101, ANCHOR),
            row(105, ANCHOR + timedelta(milliseconds=188)),
            row(99, ANCHOR + timedelta(seconds=1, milliseconds=88)))
    actual = tracker.get_interval(record["interval_id"])
    assert actual["highest_trade_price"] == 105
    assert actual["lowest_trade_price"] == 99
    assert actual["first_observed_trade_at"] == ANCHOR.isoformat()
    assert actual["trade_count"] == 3
    assert actual["last_recorded_coverage_status"] == COMPLETE


def test_past_request_time_is_metadata_not_a_retroactive_coverage_anchor(tmp_path):
    clock = Clock(ANCHOR)
    tracker = TradeIntervalTruth(CID, str(tmp_path / "intervals.json"), clock=clock)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    observe(tracker, row(120, ANCHOR - timedelta(seconds=1)),
            received=ANCHOR - timedelta(milliseconds=500))

    # The requested/Brain time is deliberately historical. Registration binds
    # to the already-observed venue event frontier, not local wall time.
    interval = tracker._register_interval(CID, BASE, 100, "test_market_reference")
    assert interval["requested_at"] == BASE.isoformat()
    assert interval["anchor_at"] == (ANCHOR - timedelta(seconds=1)).isoformat()
    assert interval["registered_at"] == ANCHOR.isoformat()
    assert interval["coverage_status"] == COMPLETE
    assert interval["highest_trade_price"] is None

    observe(tracker, row(105, ANCHOR + timedelta(milliseconds=1)),
            received=ANCHOR + timedelta(seconds=1))
    current = tracker.get_interval(interval["interval_id"])
    assert current["highest_trade_price"] == 105
    assert current["trade_count"] == 1


def test_registration_uses_market_frontier_when_venue_clock_is_ahead(tmp_path):
    # The just-consumed print's venue clock is later than the local registration
    # clock. Its actual event time, not datetime.now(), defines the anchor.
    local_clock = Clock(ANCHOR)
    tracker = TradeIntervalTruth(CID, str(tmp_path / "intervals.json"),
                                 clock=local_clock)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    frontier = ANCHOR + timedelta(milliseconds=138)
    observe(tracker, row(105, frontier), received=ANCHOR - timedelta(milliseconds=12))
    interval = tracker._register_interval(CID, BASE, 100, "test_market_reference")
    assert interval["anchor_at"] == frontier.isoformat()
    assert interval["registered_at"] == ANCHOR.isoformat()
    observe(tracker, row(999, frontier - timedelta(milliseconds=1)),
            received=ANCHOR + timedelta(milliseconds=1))
    assert tracker.get_interval(interval["interval_id"])["highest_trade_price"] is None


def test_registration_does_not_let_local_clock_move_market_frontier(tmp_path):
    # The local process clock may be ahead of venue event time. A genuinely
    # later-dispatched event after the frontier still belongs to the interval.
    local_clock = Clock(ANCHOR + timedelta(seconds=10))
    tracker = TradeIntervalTruth(CID, str(tmp_path / "intervals.json"),
                                 clock=local_clock)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    frontier = ANCHOR
    observe(tracker, row(100, frontier), received=ANCHOR + timedelta(seconds=1))
    interval = tracker._register_interval(CID, BASE, 100, "test_market_reference")
    assert interval["anchor_at"] == frontier.isoformat()
    assert interval["registered_at"] == (ANCHOR + timedelta(seconds=10)).isoformat()
    observe(tracker, row(105, frontier + timedelta(milliseconds=1)),
            received=ANCHOR + timedelta(seconds=11))
    assert tracker.get_interval(interval["interval_id"])["highest_trade_price"] == 105


def test_connected_epoch_without_a_valid_trade_cannot_open_interval(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    with pytest.raises(TradeIntervalTruthError, match="live_coverage_epoch_unavailable"):
        tracker._register_interval(CID, BASE, 100, "pending")
    assert tracker._provider_current_coverage_evidence("epoch-A") is None


def test_provider_refuses_connected_but_not_yet_proven_trade_generation(tmp_path):
    provider, _clock = provider_with_live_trade(tmp_path, prove=False)
    with pytest.raises(DataFeedError, match="COVERAGE_UNPROVEN"):
        provider.open_trade_interval(BASE, 100, "pending_generation")


def test_reconnect_epoch_stays_pending_until_first_valid_trade(tmp_path):
    provider, clock = provider_with_live_trade(tmp_path)
    old = provider.open_trade_interval(BASE, 100, "epoch_A")
    tracker = provider.trade_interval_truth
    tracker.mark_coverage_broken("runtime_reconnect", clock.at,
                                 epoch_id="runtime-A")
    tracker.begin_coverage_epoch(CID, "runtime-B", clock.at)
    provider._trade_interval_epoch_id = "runtime-B"
    provider._trade_interval_runtime_epoch_id = "runtime-B"
    provider.runtime._coverage_epoch_id = lambda: "runtime-B"
    provider.runtime.last_trade_at = None
    with pytest.raises(DataFeedError, match="COVERAGE_UNPROVEN"):
        provider.open_trade_interval(BASE, 100, "before_first_B_trade")
    tracker.observe_gateway_event(
        [CID, [row(101, ANCHOR + timedelta(seconds=1))]],
        epoch_id="runtime-B", received_at=clock.at)
    provider.runtime.last_trade_at = clock.at
    new = provider.open_trade_interval(BASE, 100, "after_first_B_trade")
    assert tracker.get_interval(old["interval_id"])["last_recorded_coverage_status"] == INCOMPLETE
    assert new["coverage_status"] == COMPLETE


def test_authority_read_requires_fresh_raw_trade_not_live_quotes(tmp_path):
    provider, clock = provider_with_live_trade(tmp_path)
    interval = provider.open_trade_interval(BASE, 100, "fresh_trade")
    stale = datetime.now(timezone.utc) - timedelta(seconds=121)
    provider.trade_interval_truth._epochs[provider._trade_interval_epoch_id][
        "last_valid_trade_received_at"] = stale.isoformat()
    provider.runtime.last_trade_at = stale
    audit = provider.trade_interval_truth.get_interval(interval["interval_id"])
    assert audit["authority_scope"] == "AUDIT_ONLY"
    assert audit["last_recorded_coverage_status"] == COMPLETE
    assert "coverage_status" not in audit
    assert all(item["authority_scope"] == "AUDIT_ONLY"
               for item in provider.trade_interval_truth.active_intervals())
    with pytest.raises(DataFeedError, match="STREAM_STALE"):
        provider.read_authoritative_trade_interval(interval["interval_id"])
    current = provider.trade_interval_truth.get_interval(interval["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"] == "raw_trade_stream_stale"


def test_unique_trade_freshness_is_required_even_if_runtime_sees_replays(tmp_path):
    provider, clock = provider_with_live_trade(tmp_path)
    interval = provider.open_trade_interval(BASE, 100, "fresh_trade")
    stale = datetime.now(timezone.utc) - timedelta(seconds=121)
    provider.trade_interval_truth._epochs[provider._trade_interval_epoch_id][
        "last_valid_trade_received_at"] = stale.isoformat()
    # A raw transport message refreshed the runtime receipt clock, but no new
    # unique validated same-contract trade refreshed interval coverage.
    provider.runtime.last_trade_at = datetime.now(timezone.utc)
    provider.runtime.last_quote_at = provider.runtime.last_trade_at
    with pytest.raises(DataFeedError, match="STREAM_STALE"):
        provider.read_authoritative_trade_interval(interval["interval_id"])
    assert provider.trade_interval_truth.get_interval(
        interval["interval_id"])["last_recorded_coverage_status"] == INCOMPLETE


def test_authority_read_returns_only_current_complete_fresh_interval(tmp_path):
    provider, clock = provider_with_live_trade(tmp_path)
    interval = provider.open_trade_interval(BASE, 100, "fresh_trade")
    current = provider.read_authoritative_trade_interval(interval["interval_id"])
    assert current["coverage_status"] == COMPLETE
    assert current["authority_scope"] == "CURRENT_PROVIDER_VALIDATED"


@pytest.mark.parametrize("failure", [
    "receive", "receive_ended", "malformed_frame", "handler",
])
def test_realtime_integrity_failures_break_interval_and_later_trade_cannot_heal(
        tmp_path, failure):
    provider, runtime, hub, clock = realtime_provider_path(tmp_path)
    assert dispatch_gateway_trade(hub, clock.at, 100) == 1
    interval = provider.open_trade_interval(clock.at, 100, "realtime_probe")

    if failure == "receive":
        hub._conn.frames.append(OSError("read failed"))
        with pytest.raises(RealtimeError, match="receive failed"):
            hub.pump(max_messages=1)
    elif failure == "receive_ended":
        hub._conn.frames.append(None)
        with pytest.raises(RealtimeError, match="receive ended"):
            hub.pump(max_messages=1)
    elif failure == "malformed_frame":
        hub._conn.frames.append("not-json\x1e")
        with pytest.raises(RealtimeError, match="integrity unproven"):
            hub.pump(max_messages=1)
    else:
        provider.aggregator.ingest_event = lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("provider callback failed"))
        hub._conn.frames.append(
            '{"type":1,"target":"GatewayTrade","arguments":['
            f'"{CID}",[{{"contractId":"{CID}","timestamp":"{(clock.at + timedelta(seconds=1)).isoformat()}","price":111}}]]}}\x1e')
        with pytest.raises(RealtimeError, match="integrity unproven"):
            hub.pump(max_messages=1)

    audit = provider.trade_interval_truth.get_interval(interval["interval_id"])
    assert audit["last_recorded_coverage_status"] == INCOMPLETE
    assert runtime.trade_transport_integrity_healthy is False

    # A later syntactically valid trade on the compromised generation cannot
    # restore the old interval or re-enable reads.
    hub._dispatch({
        "type": 1, "target": "GatewayTrade",
        "arguments": [CID, [row(120, clock.at + timedelta(seconds=2))]],
    })
    assert provider.trade_interval_truth.get_interval(
        interval["interval_id"])["last_recorded_coverage_status"] == INCOMPLETE
    with pytest.raises(DataFeedError):
        provider.read_authoritative_trade_interval(interval["interval_id"])


def test_irrelevant_gatewaytrade_consumer_failure_does_not_break_canonical_coverage(tmp_path):
    provider, runtime, hub, clock = realtime_provider_path(tmp_path)
    assert dispatch_gateway_trade(hub, clock.at, 100) == 1
    interval = provider.open_trade_interval(clock.at, 100, "diagnostic_probe")
    hub.on("GatewayTrade", lambda _args: (_ for _ in ()).throw(ValueError("diagnostic")))
    assert dispatch_gateway_trade(hub, clock.at + timedelta(seconds=1), 105) == 1
    assert runtime.trade_transport_integrity_healthy is True
    assert provider.read_authoritative_trade_interval(interval["interval_id"])[
        "highest_trade_price"] == 105


def test_late_event_older_than_captured_frontier_cannot_make_post_anchor_extreme(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    frontier = ANCHOR + timedelta(seconds=5)
    observe(tracker, row(100, frontier), received=BASE + timedelta(seconds=8))
    interval = tracker._register_interval(CID, BASE, 100, "event_frontier")
    observe(tracker, row(999, frontier - timedelta(milliseconds=1)),
            received=BASE + timedelta(seconds=9))
    current = tracker.get_interval(interval["interval_id"])
    assert current["highest_trade_price"] is None
    observe(tracker, row(105, frontier + timedelta(milliseconds=1)),
            received=BASE + timedelta(seconds=10))
    assert tracker.get_interval(interval["interval_id"])["highest_trade_price"] == 105


def test_finite_zero_price_is_preserved_as_market_fact(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    observe(tracker, row(0, ANCHOR))
    assert tracker.get_interval(interval["interval_id"])["lowest_trade_price"] == 0


@pytest.mark.parametrize("post_prices,expected_high,expected_low", [
    ([100, 102, 99], 102, 99),
    ([100, 101, 98], 101, 98),
])
def test_same_minute_pre_anchor_ohlc_extreme_is_excluded_from_interval(
        tmp_path, post_prices, expected_high, expected_low):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    before = ANCHOR - timedelta(milliseconds=1)
    after = [ANCHOR + timedelta(milliseconds=i) for i in (1, 2, 3)]
    aggregator.ingest_event([CID, [row(110, before), row(90, before + timedelta(milliseconds=1))]])
    for price, at in zip(post_prices, after):
        aggregator.ingest_event([CID, [row(price, at)]], on_unique_event=lambda args,
                                batch_identity_proven: tracker.observe_gateway_event(
                                    args, epoch_id="epoch-A", received_at=BASE + timedelta(minutes=1),
                                    batch_identity_proven=batch_identity_proven))
    actual = tracker.get_interval(record["interval_id"])
    candle = aggregator.developing()
    assert candle["high"] == 110 and candle["low"] == 90
    assert actual["highest_trade_price"] == expected_high
    assert actual["lowest_trade_price"] == expected_low


def test_authenticated_late_event_updates_interval_but_not_closed_candle(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    provider = object.__new__(TopstepXDataProvider)
    provider._lock = threading.Lock()
    provider.aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    provider.trade_interval_truth = tracker
    provider._trade_interval_epoch_id = "epoch-A"
    provider._trade_interval_runtime_epoch_id = "epoch-A"
    provider.runtime = SimpleNamespace(
        contract=SimpleNamespace(id=CID), hub=object(), is_running=True,
        _coverage_epoch_id=lambda: "epoch-A")
    provider.contract = SimpleNamespace(id=CID, tick_size=0.25)
    provider._stop = threading.Event()
    provider.wake_registry = None
    provider._persist = lambda _rows: None
    provider._trim = lambda: None
    first = [CID, [row(101, ANCHOR + timedelta(seconds=10))]]
    provider._on_trade(first)
    closed_before = provider.aggregator.closed_candles()[0]["high"]
    late = [CID, [row(106, ANCHOR + timedelta(seconds=5))]]
    provider._on_trade(late)
    current = tracker.get_interval(interval["interval_id"])
    assert provider.aggregator.diagnostics["late"] == 1
    assert provider.aggregator.closed_candles()[0]["high"] == closed_before
    assert current["highest_trade_price"] == 106
    assert current["highest_trade_at"] == (ANCHOR + timedelta(seconds=5)).isoformat()


def test_provider_serializes_interval_registration_with_raw_trade_dispatch(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.begin_coverage_epoch(CID, "runtime-A", BASE)
    registered = threading.Event()
    allow_open_return = threading.Event()
    event_waiting_for_lock = threading.Event()
    lock = threading.Lock()

    class OrderedProviderLock:
        def __enter__(self):
            if threading.current_thread().name == "trade-dispatch":
                event_waiting_for_lock.set()
            lock.acquire()
            return self

        def __exit__(self, *_exc):
            lock.release()

    original_open = tracker._register_interval

    def pause_after_registration(*args, **kwargs):
        record = original_open(*args, **kwargs)
        registered.set()
        if not allow_open_return.wait(2):
            raise AssertionError("test did not release interval registration")
        return record

    tracker._register_interval = pause_after_registration
    provider = object.__new__(TopstepXDataProvider)
    provider._lock = OrderedProviderLock()
    provider.trade_interval_truth = tracker
    provider.contract = SimpleNamespace(id=CID, tick_size=0.25)
    runtime_clock = Clock(datetime.now(timezone.utc))
    provider.runtime = SimpleNamespace(
        contract=SimpleNamespace(id=CID), hub=object(), is_running=True,
        _coverage_epoch_id=lambda: "runtime-A", _clock=runtime_clock,
        last_trade_at=runtime_clock.at)
    provider._stale_seconds = 120
    provider._trade_interval_epoch_id = "runtime-A"
    provider._trade_interval_runtime_epoch_id = "runtime-A"
    provider._stop = threading.Event()
    provider.aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    provider.wake_registry = None
    provider._persist = lambda _rows: None
    provider._trim = lambda: None
    provider._on_trade([CID, [row(100, ANCHOR)]])
    errors = []
    returned = []

    def open_interval():
        try:
            returned.append(provider.open_trade_interval(
                BASE, 100, "mechanics_registration_reference"))
        except Exception as exc:  # noqa: BLE001 — surface thread errors below
            errors.append(exc)

    opener = threading.Thread(target=open_interval, name="interval-open")
    opener.start()
    assert registered.wait(2)
    dispatcher = threading.Thread(
        target=lambda: provider._on_trade(
            [CID, [row(105, ANCHOR + timedelta(milliseconds=1))]]),
        name="trade-dispatch")
    dispatcher.start()
    try:
        assert event_waiting_for_lock.wait(2)
    finally:
        allow_open_return.set()
    opener.join(2)
    dispatcher.join(2)

    assert not opener.is_alive() and not dispatcher.is_alive()
    assert errors == []
    assert len(returned) == 1
    record = tracker.get_interval(returned[0]["interval_id"])
    assert record["anchor_at"] == ANCHOR.isoformat()
    assert record["highest_trade_price"] == 105
    assert record["trade_count"] == 1


def test_trade_event_detects_runtime_epoch_mismatch_before_interval_update(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    provider = object.__new__(TopstepXDataProvider)
    provider._lock = threading.Lock()
    provider.aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    provider.trade_interval_truth = tracker
    provider._trade_interval_epoch_id = "epoch-A"
    provider._trade_interval_runtime_epoch_id = "runtime-A"
    provider.runtime = SimpleNamespace(
        contract=SimpleNamespace(id=CID), hub=object(), is_running=True,
        _coverage_epoch_id=lambda: "runtime-B")
    provider.contract = SimpleNamespace(id=CID, tick_size=0.25)
    provider._stop = threading.Event()
    provider.wake_registry = None
    provider._persist = lambda _rows: None
    provider._trim = lambda: None

    provider._on_trade([CID, [row(120, ANCHOR + timedelta(seconds=1))]])

    current = tracker.get_interval(interval["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"] == "runtime_epoch_mismatch"
    assert current["highest_trade_price"] is None
    # Interval truth fails closed while the ordinary candle observer still
    # receives the event through its existing ingestion path.
    assert provider.aggregator.closed_candles()[-1]["high"] == 120


def test_reconnect_breaks_old_interval_and_new_epoch_can_open_new_one(tmp_path):
    tracker = make_tracker(tmp_path)
    old = opened(tracker)
    observe(tracker, row(102, ANCHOR + timedelta(seconds=1)))
    tracker.mark_coverage_broken("runtime_reconnect", BASE + timedelta(seconds=20),
                                 epoch_id="epoch-A")
    assert tracker.get_interval(old["interval_id"])["last_recorded_coverage_status"] == INCOMPLETE
    tracker.begin_coverage_epoch(CID, "epoch-B", BASE + timedelta(seconds=21))
    observe(tracker, row(120, ANCHOR + timedelta(seconds=3)), epoch="epoch-B")
    assert tracker.get_interval(old["interval_id"])["highest_trade_price"] == 102
    tracker._clock.at = BASE + timedelta(seconds=23)
    new = tracker._register_interval(CID, BASE + timedelta(seconds=22), 100, "fresh_epoch")
    assert new["coverage_status"] == COMPLETE


def test_process_restart_marks_active_interval_incomplete_without_backfill(tmp_path):
    path = tmp_path / "durable.json"
    first = make_tracker(tmp_path, path=path)
    record = opened(first)
    observe(first, row(105, ANCHOR + timedelta(seconds=1)))
    restarted = make_tracker(tmp_path, path=path,
                             now=BASE + timedelta(minutes=2))
    loaded = restarted.get_interval(record["interval_id"])
    assert loaded["last_recorded_coverage_status"] == INCOMPLETE
    assert loaded["incomplete_reason"] == "process_restart_without_exact_trade_backfill"
    assert loaded["highest_trade_price"] == 105
    assert restarted.current_epoch_id is None
    with pytest.raises(TradeIntervalTruthError, match="live_coverage_epoch_unavailable"):
        restarted._register_interval(CID, BASE + timedelta(minutes=1), 100, "no_epoch")


def test_legacy_v1_records_are_preserved_but_never_keep_complete_authority(tmp_path):
    path = tmp_path / "legacy.json"
    tracker = make_tracker(tmp_path, path=path)
    interval = opened(tracker)
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["schema"] = "trade_interval_truth.v1"
    epoch = blob["coverage_epochs"]["epoch-A"]
    for key in ("trade_coverage_status", "event_time_frontier",
                "frontier_observation_sequence", "last_observation_sequence",
                "last_valid_trade_received_at", "first_valid_trade_received_at"):
        epoch.pop(key, None)
    record = blob["intervals"][interval["interval_id"]]
    record.pop("anchor_observation_sequence", None)
    record.pop("registered_at", None)
    path.write_text(json.dumps(blob), encoding="utf-8")

    migrated = make_tracker(tmp_path, path=path, now=ANCHOR + timedelta(minutes=1))
    preserved = migrated.get_interval(interval["interval_id"])
    assert migrated.storage_health["healthy"] is True, migrated.storage_health
    assert preserved["last_recorded_coverage_status"] == INCOMPLETE
    assert preserved["incomplete_reason"] == "legacy_event_frontier_unavailable"
    assert preserved["anchor_observation_sequence"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "trade_interval_truth.v2"


def test_corrupt_persisted_extrema_are_unavailable_not_authoritative(tmp_path):
    path = tmp_path / "durable.json"
    tracker = make_tracker(tmp_path, path=path)
    interval = opened(tracker)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["intervals"][interval["interval_id"]]["highest_trade_price"] = float("nan")
    path.write_text(json.dumps(stored), encoding="utf-8")
    reloaded = make_tracker(tmp_path, path=path, now=BASE + timedelta(minutes=2))
    assert reloaded.storage_health["healthy"] is False
    assert reloaded.get_interval(interval["interval_id"]) is None
    with pytest.raises(TradeIntervalTruthError, match="interval_storage_unavailable"):
        reloaded._register_interval(CID, BASE + timedelta(minutes=1), 100, "corrupt")


def test_foreign_contract_does_not_update_extrema_and_cannot_open(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    observe(tracker, row(999, ANCHOR + timedelta(seconds=1), OTHER), envelope=OTHER)
    assert tracker.get_interval(record["interval_id"])["highest_trade_price"] is None
    with pytest.raises(TradeIntervalTruthError, match="contract_mismatch"):
        tracker._register_interval(OTHER, ANCHOR, 100, "wrong_contract")
    tracker.begin_coverage_epoch(CID, "epoch-B", BASE + timedelta(seconds=10))
    assert tracker.get_interval(record["interval_id"])["last_recorded_coverage_status"] == INCOMPLETE
    assert tracker.get_interval(record["interval_id"])["incomplete_reason"] == "coverage_epoch_changed"


def test_persisted_state_for_another_contract_is_not_inherited(tmp_path):
    path = tmp_path / "same_path.json"
    tracker = make_tracker(tmp_path, path=path)
    opened(tracker)
    other_contract = make_tracker(tmp_path, contract=OTHER, path=path)
    assert other_contract.storage_health["healthy"] is False
    with pytest.raises(TradeIntervalTruthError, match="interval_storage_unavailable"):
        other_contract.begin_coverage_epoch(OTHER, "other-epoch", BASE)


@pytest.mark.parametrize("bad_timestamp", [None, "not-a-time", "2026-10-02T14:43:47"])
def test_malformed_or_naive_trade_timestamp_breaks_coverage_without_extrema(
        tmp_path, bad_timestamp):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    bad = {"contractId": CID, "timestamp": bad_timestamp, "price": 111}
    observe(tracker, bad)
    current = tracker.get_interval(record["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"].startswith("trade_timestamp_")
    assert current["highest_trade_price"] is None


def test_malformed_batch_is_atomic_and_does_not_apply_earlier_rows(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    observe(tracker, row(105, ANCHOR + timedelta(seconds=1)),
            {"contractId": CID, "timestamp": "bad", "price": 120})
    current = tracker.get_interval(record["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["highest_trade_price"] is None


def test_unhashable_gateway_event_marks_coverage_incomplete(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    tracker.observe_gateway_event(
        [CID, [row(110, ANCHOR + timedelta(seconds=1))]], epoch_id="epoch-A",
        received_at=BASE + timedelta(minutes=1), batch_identity_proven=False)
    current = tracker.get_interval(record["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"] == "trade_batch_identity_unproven"
    assert current["highest_trade_price"] is None


@pytest.mark.parametrize("bad_price", [None, "not-a-price", float("nan"), float("inf")])
def test_unpriceable_trade_breaks_coverage_without_extrema(tmp_path, bad_price):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    observe(tracker, {"contractId": CID, "timestamp": ANCHOR.isoformat(),
                      "price": bad_price})
    current = tracker.get_interval(interval["interval_id"])
    assert current["last_recorded_coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"] == "trade_price_invalid"
    assert current["highest_trade_price"] is None


def test_interval_state_persists_extrema_but_not_raw_trade_list(tmp_path):
    path = tmp_path / "durable.json"
    tracker = make_tracker(tmp_path, path=path)
    interval = opened(tracker)
    observe(tracker, row(105, ANCHOR + timedelta(seconds=1)))
    raw = json.loads(path.read_text(encoding="utf-8"))
    record = raw["intervals"][interval["interval_id"]]
    assert record["highest_trade_price"] == 105
    assert "trades" not in record and "raw_events" not in record
    assert raw["schema"] == "trade_interval_truth.v2"


def test_interval_observer_error_does_not_change_candle_ingestion():
    aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    at = datetime(2026, 10, 2, 14, 43, 50, tzinfo=timezone.utc)
    count = aggregator.ingest_event(
        [CID, [row(101, at)]],
        on_unique_event=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("observer")))
    assert count == 1
    assert aggregator.developing()["high"] == 101
    assert aggregator.developing()["low"] == 101


def test_batch_replay_guard_prevents_interval_double_count(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    args = [CID, [row(105, ANCHOR + timedelta(seconds=1))]]

    def observe_unique(event, *, batch_identity_proven):
        tracker.observe_gateway_event(event, epoch_id="epoch-A",
                                      received_at=BASE + timedelta(minutes=1),
                                      batch_identity_proven=batch_identity_proven)

    assert aggregator.ingest_event(args, on_unique_event=observe_unique) == 1
    assert aggregator.ingest_event(args, on_unique_event=observe_unique) == 0
    current = tracker.get_interval(interval["interval_id"])
    assert current["trade_count"] == 1


def test_interval_epoch_dedup_survives_more_than_legacy_replay_window(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    # The raw digest set is in-memory epoch evidence; skip repeated fsync in this
    # stress test while retaining the production event/aggregator/tracker path.
    tracker._persist_locked = lambda: True
    aggregator = MinuteCandleAggregator(CID, tick_size=0.25)
    first = [CID, [row(105, ANCHOR)]]

    def ingest(args):
        return aggregator.ingest_event(
            args,
            on_unique_event=lambda event, batch_identity_proven:
                tracker.observe_gateway_event(
                    event, epoch_id="epoch-A", received_at=BASE + timedelta(seconds=1),
                    batch_identity_proven=batch_identity_proven))

    assert ingest(first) == 1
    for index in range(2105):
        # Every later batch is a distinct authenticated late event. Keeping its
        # venue time behind the frontier stresses the replay-cache boundary.
        assert ingest([CID, [row(100 + index * 0.25,
                                 ANCHOR - timedelta(milliseconds=1))]]) == 1

    interval = tracker._register_interval(CID, BASE, 100, "dedup_frontier")
    epoch_before = tracker._epochs["epoch-A"].copy()
    assert interval["anchor_observation_sequence"] == epoch_before[
        "frontier_observation_sequence"]
    assert interval["trade_count"] == 0

    # The candle aggregator has evicted this digest by now. Interval authority
    # still recognizes it over the full coverage epoch before assigning sequence.
    assert ingest(first) == 1
    current = tracker.get_interval(interval["interval_id"])
    epoch_after = tracker._epochs["epoch-A"]
    assert current["last_recorded_coverage_status"] == COMPLETE
    assert current["trade_count"] == 0
    assert current["highest_trade_price"] is None
    assert epoch_after["event_time_frontier"] == epoch_before["event_time_frontier"]
    assert epoch_after["frontier_observation_sequence"] == epoch_before[
        "frontier_observation_sequence"]
    assert epoch_after["last_observation_sequence"] == epoch_before[
        "last_observation_sequence"]


def test_close_is_terminal_and_contract_scoped(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    closed = tracker.close_interval(interval["interval_id"], "anchor_superseded")
    assert closed["last_recorded_coverage_status"] == CLOSED
    assert closed["coverage_status_at_close"] == COMPLETE
    assert tracker.active_intervals(CID) == []
    assert tracker.active_intervals(OTHER) == []


def test_interval_truth_has_no_strategy_or_execution_consumer():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src"
    allowed = {(source_root / "data_feed" / "topstepx_provider.py").resolve()}
    references = set()
    for source in source_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if ("from data_feed.trade_interval_truth import" in text
                or "TradeIntervalTruth(" in text
                or "read_authoritative_trade_interval(" in text):
            references.add(source.resolve())
    assert references == allowed


def test_provider_is_the_only_current_authority_api_consumer():
    root = Path(__file__).resolve().parents[1] / "src"
    tracker_path = (root / "data_feed" / "trade_interval_truth.py").resolve()
    provider_path = (root / "data_feed" / "topstepx_provider.py").resolve()
    for name in ("authoritative_interval", "coverage_evidence", "open_interval"):
        assert not hasattr(TradeIntervalTruth, name)
    private_api_consumers = set()
    for source in root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if any(token in text for token in (
                "_provider_current_interval_record(",
                "_provider_current_coverage_evidence(",
                "_register_interval(")):
            private_api_consumers.add(source.resolve())
    assert private_api_consumers == {tracker_path, provider_path}
