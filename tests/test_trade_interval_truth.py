from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from data_feed.trade_interval_truth import (  # noqa: E402
    COMPLETE, CLOSED, INCOMPLETE, TradeIntervalTruth, TradeIntervalTruthError,
)
from data_feed.topstepx_provider import MinuteCandleAggregator, TopstepXDataProvider  # noqa: E402

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
                              clock=Clock(now or BASE + timedelta(minutes=1)))


def row(price, at, contract=CID):
    return {"contractId": contract, "timestamp": at.isoformat(), "price": price,
            "volume": 1}


def opened(tracker, anchor=ANCHOR):
    tracker.begin_coverage_epoch(CID, "epoch-A", BASE)
    return tracker.open_interval(CID, anchor, 100, "test_market_reference")


def observe(tracker, *rows, epoch="epoch-A", received=None, envelope=CID):
    tracker.observe_gateway_event(
        [envelope, list(rows)], epoch_id=epoch,
        received_at=received or BASE + timedelta(minutes=1))


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
    assert actual["coverage_status"] == COMPLETE


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


def test_reconnect_breaks_old_interval_and_new_epoch_can_open_new_one(tmp_path):
    tracker = make_tracker(tmp_path)
    old = opened(tracker)
    observe(tracker, row(102, ANCHOR + timedelta(seconds=1)))
    tracker.mark_coverage_broken("runtime_reconnect", BASE + timedelta(seconds=20),
                                 epoch_id="epoch-A")
    assert tracker.get_interval(old["interval_id"])["coverage_status"] == INCOMPLETE
    tracker.begin_coverage_epoch(CID, "epoch-B", BASE + timedelta(seconds=21))
    observe(tracker, row(120, ANCHOR + timedelta(seconds=3)), epoch="epoch-B")
    assert tracker.get_interval(old["interval_id"])["highest_trade_price"] == 102
    new = tracker.open_interval(CID, BASE + timedelta(seconds=22), 100, "fresh_epoch")
    assert new["coverage_status"] == COMPLETE


def test_process_restart_marks_active_interval_incomplete_without_backfill(tmp_path):
    path = tmp_path / "durable.json"
    first = make_tracker(tmp_path, path=path)
    record = opened(first)
    observe(first, row(105, ANCHOR + timedelta(seconds=1)))
    restarted = make_tracker(tmp_path, path=path,
                             now=BASE + timedelta(minutes=2))
    loaded = restarted.get_interval(record["interval_id"])
    assert loaded["coverage_status"] == INCOMPLETE
    assert loaded["incomplete_reason"] == "process_restart_without_exact_trade_backfill"
    assert loaded["highest_trade_price"] == 105
    assert restarted.current_epoch_id is None
    with pytest.raises(TradeIntervalTruthError, match="live_coverage_epoch_unavailable"):
        restarted.open_interval(CID, BASE + timedelta(minutes=1), 100, "no_epoch")


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
        reloaded.open_interval(CID, BASE + timedelta(minutes=1), 100, "corrupt")


def test_foreign_contract_does_not_update_extrema_and_cannot_open(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    observe(tracker, row(999, ANCHOR + timedelta(seconds=1), OTHER), envelope=OTHER)
    assert tracker.get_interval(record["interval_id"])["highest_trade_price"] is None
    with pytest.raises(TradeIntervalTruthError, match="contract_mismatch"):
        tracker.open_interval(OTHER, ANCHOR, 100, "wrong_contract")
    tracker.begin_coverage_epoch(CID, "epoch-B", BASE + timedelta(seconds=10))
    assert tracker.get_interval(record["interval_id"])["coverage_status"] == INCOMPLETE
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
    assert current["coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"].startswith("trade_timestamp_")
    assert current["highest_trade_price"] is None


def test_malformed_batch_is_atomic_and_does_not_apply_earlier_rows(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    observe(tracker, row(105, ANCHOR + timedelta(seconds=1)),
            {"contractId": CID, "timestamp": "bad", "price": 120})
    current = tracker.get_interval(record["interval_id"])
    assert current["coverage_status"] == INCOMPLETE
    assert current["highest_trade_price"] is None


def test_unhashable_gateway_event_marks_coverage_incomplete(tmp_path):
    tracker = make_tracker(tmp_path)
    record = opened(tracker)
    tracker.observe_gateway_event(
        [CID, [row(110, ANCHOR + timedelta(seconds=1))]], epoch_id="epoch-A",
        received_at=BASE + timedelta(minutes=1), batch_identity_proven=False)
    current = tracker.get_interval(record["interval_id"])
    assert current["coverage_status"] == INCOMPLETE
    assert current["incomplete_reason"] == "trade_batch_identity_unproven"
    assert current["highest_trade_price"] is None


@pytest.mark.parametrize("bad_price", [None, "not-a-price", float("nan"), float("inf")])
def test_unpriceable_trade_breaks_coverage_without_extrema(tmp_path, bad_price):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    observe(tracker, {"contractId": CID, "timestamp": ANCHOR.isoformat(),
                      "price": bad_price})
    current = tracker.get_interval(interval["interval_id"])
    assert current["coverage_status"] == INCOMPLETE
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
    assert raw["schema"] == "trade_interval_truth.v1"


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


def test_close_is_terminal_and_contract_scoped(tmp_path):
    tracker = make_tracker(tmp_path)
    interval = opened(tracker)
    closed = tracker.close_interval(interval["interval_id"], "anchor_superseded")
    assert closed["coverage_status"] == CLOSED
    assert closed["coverage_status_at_close"] == COMPLETE
    assert tracker.active_intervals(CID) == []
    assert tracker.active_intervals(OTHER) == []


def test_interval_truth_has_no_strategy_or_execution_consumer():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src"
    allowed = {
        (source_root / "data_feed" / "trade_interval_truth.py").resolve(),
        (source_root / "data_feed" / "topstepx_provider.py").resolve(),
    }
    references = set()
    for source in source_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if any(token in text for token in
               ("TradeIntervalTruth", "trade_interval_truth", "open_trade_interval")):
            references.add(source.resolve())
    assert references == allowed
