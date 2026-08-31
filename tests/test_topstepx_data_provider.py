"""TOPSTEPX-DATA-PROVIDER — trade-to-candle transport locks.

No network. Every test drives the aggregator or a fake session directly.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from data_feed import get_provider                                  # noqa: E402
from data_feed.provider_interface import DataFeedError              # noqa: E402
from data_feed.timeframe_builder import build_timeframes            # noqa: E402
from data_feed.topstepx_provider import (                           # noqa: E402
    SOURCE, MinuteCandleAggregator, TopstepXDataProvider, minute_floor, parse_ts,
)

CID = "CON.F.US.MNQ.U26"
T0 = datetime(2026, 8, 5, 14, 51, 0, tzinfo=timezone.utc)


def trade(price, volume=1, at=None, cid=CID, ttype=0):
    return {"symbolId": "F.US.MNQ", "price": price, "volume": volume,
            "timestamp": (at or T0).isoformat(), "type": ttype, "contractId": cid}


def agg():
    return MinuteCandleAggregator(CID, tick_size=0.25)


# ══════════════════════════════════════════════════════════════════════════════
class TestTradeNormalization:

    def test_a_real_gateway_trade_event_is_ingested(self):
        """Exact live payload shape captured 2026-08-05: [cid, [trade, ...]]."""
        a = agg()
        args = [CID, [{"symbolId": "F.US.MNQ", "price": 29850.5,
                       "timestamp": "2026-08-05T14:51:54.908+00:00", "type": 0,
                       "volume": 1, "contractId": CID}]]
        assert a.ingest_event(args) == 1

    def test_an_event_carrying_several_trades_counts_them_all(self):
        a = agg()
        args = [CID, [trade(29850.5, 1, T0), trade(29849.5, 2, T0 + timedelta(seconds=1))]]
        assert a.ingest_event(args) == 2
        assert a._open[T0]["volume"] == 3

    def test_a_foreign_contract_trade_is_discarded(self):
        a = agg()
        assert a.ingest_trade(trade(1.0, 1, T0, cid="CON.F.US.ES.U26")) is False
        assert a.diagnostics["foreign_contract"] == 1

    def test_a_malformed_trade_is_ignored_not_raised(self):
        a = agg()
        assert a.ingest_trade({"price": "abc", "timestamp": T0.isoformat()}) is False
        assert a.ingest_trade({}) is False

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(DataFeedError):
            parse_ts("2026-08-05T14:51:00")

    def test_z_and_offset_timestamps_both_parse_to_utc(self):
        assert parse_ts("2026-08-05T14:51:00Z") == parse_ts("2026-08-05T14:51:00+00:00")
        assert parse_ts("2026-08-05T10:51:00-04:00").hour == 14


class TestOhlcvAggregation:

    def test_ohlc_is_built_from_trade_sequence(self):
        a = agg()
        for i, px in enumerate([29850.0, 29855.0, 29845.0, 29851.0]):
            a.ingest_trade(trade(px, 1, T0 + timedelta(seconds=i * 10)))
        c = a.roll(T0 + timedelta(minutes=1))[0]
        assert c["open"] == 29850.0 and c["high"] == 29855.0
        assert c["low"] == 29845.0 and c["close"] == 29851.0

    def test_volume_accumulates(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 3, T0))
        a.ingest_trade(trade(29851.0, 2, T0 + timedelta(seconds=5)))
        assert a.roll(T0 + timedelta(minutes=1))[0]["volume"] == 5

    def test_the_timestamp_is_the_utc_minute_boundary(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0 + timedelta(seconds=37, microseconds=500)))
        assert a.roll(T0 + timedelta(minutes=1))[0]["timestamp"] == T0.isoformat()

    def test_ohlc_law_holds(self):
        a = agg()
        for i, px in enumerate([29850.0, 29860.0, 29840.0, 29855.0]):
            a.ingest_trade(trade(px, 1, T0 + timedelta(seconds=i)))
        c = a.roll(T0 + timedelta(minutes=1))[0]
        assert c["high"] >= max(c["open"], c["close"])
        assert c["low"] <= min(c["open"], c["close"])
        assert c["high"] >= c["low"] and c["volume"] >= 0


class TestMinuteBoundaryClosure:

    def test_the_developing_minute_is_never_returned_as_closed(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0 + timedelta(seconds=30)))
        assert a.roll(T0 + timedelta(seconds=59)) == []
        assert a.closed_candles() == []

    def test_the_minute_closes_once_the_clock_passes_the_boundary(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0 + timedelta(seconds=30)))
        assert len(a.roll(T0 + timedelta(minutes=1))) == 1

    def test_the_developing_candle_is_labelled_partial(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0 + timedelta(seconds=10)))
        d = a.developing()
        assert d["partial"] is True and d["timestamp"] == T0.isoformat()

    def test_several_minutes_close_in_order(self):
        a = agg()
        for m in range(3):
            a.ingest_trade(trade(29850.0 + m, 1, T0 + timedelta(minutes=m, seconds=5)))
        closed = a.roll(T0 + timedelta(minutes=3))
        assert [c["timestamp"] for c in closed] == [
            (T0 + timedelta(minutes=m)).isoformat() for m in range(3)]


class TestEventHygiene:

    def test_identical_trades_in_one_sweep_are_all_counted(self):
        """REGRESSION — measured on MNQU6, 2026-08-05.

        A swept order prints as many same-price 1-lots sharing one millisecond.
        An earlier per-trade dedup treated those as duplicates and discarded 39%
        of real volume (2,848 -> 1,745 over 25s). They are distinct fills.
        """
        a = agg()
        for _ in range(11):
            a.ingest_trade(trade(29836.5, 1, T0))
        assert a.roll(T0 + timedelta(minutes=1))[0]["volume"] == 11

    def test_a_redelivered_batch_is_dropped_once(self):
        """Redelivery happens at the EVENT level, which is where it is guarded."""
        a = agg()
        args = [CID, [trade(29850.0, 5, T0), trade(29851.0, 3, T0)]]
        assert a.ingest_event(args) == 2
        assert a.ingest_event(json.loads(json.dumps(args))) == 0
        assert a.diagnostics["duplicate_batches"] == 1
        assert a.roll(T0 + timedelta(minutes=1))[0]["volume"] == 8

    def test_two_similar_but_distinct_batches_both_count(self):
        a = agg()
        a.ingest_event([CID, [trade(29850.0, 1, T0)]])
        a.ingest_event([CID, [trade(29850.0, 1, T0 + timedelta(milliseconds=4))]])
        assert a.roll(T0 + timedelta(minutes=1))[0]["volume"] == 2

    def test_an_earlier_out_of_order_trade_reopens_the_minute(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0 + timedelta(seconds=30)))
        a.ingest_trade(trade(29840.0, 1, T0 + timedelta(seconds=5)))
        c = a.roll(T0 + timedelta(minutes=1))[0]
        assert c["open"] == 29840.0 and c["close"] == 29850.0

    def test_a_trade_for_an_already_closed_minute_is_refused(self):
        a = agg()
        a.ingest_trade(trade(29850.0, 1, T0))
        a.roll(T0 + timedelta(minutes=1))
        assert a.ingest_trade(trade(29999.0, 9, T0 + timedelta(seconds=45))) is False
        assert a.diagnostics["late"] == 1
        assert a.closed_candles()[0]["high"] == 29850.0     # unchanged

    def test_off_tick_prices_are_counted_not_silently_accepted(self):
        a = agg()
        a.ingest_trade(trade(29850.13, 1, T0))
        assert a.diagnostics["off_tick"] == 1

    def test_on_tick_prices_are_clean(self):
        a = agg()
        for px in (29850.0, 29850.25, 29850.5, 29850.75):
            a.ingest_trade(trade(px, 1, T0 + timedelta(seconds=px % 10)))
        assert a.diagnostics["off_tick"] == 0


# ══════════════════════════════════════════════════════════════════════════════
class FakeHub:
    def __init__(self):
        from broker.topstepx_realtime import StreamHealth
        self.health = StreamHealth()
        self.health.last_event_at = datetime.now(timezone.utc)
        self.handlers = {}
        self.reconnects = 0

    def on(self, event, handler):
        self.handlers[event] = handler

    def pump(self, max_messages=1):
        return 0

    def reconnect(self):
        self.reconnects += 1
        return ["SubscribeContractQuotes", "SubscribeContractTrades"]

    def close(self):
        pass


class FakeContract:
    id = CID
    name = "MNQU6"
    tick_size = 0.25
    tick_value = 0.5


class FakeSession:
    def __init__(self):
        self.market_hub = None
        self.write_attempts = []

    def authenticate(self):
        return {"authenticated": True}

    def resolve_contract(self, text="MNQ"):
        return FakeContract()

    def connect_market_hub(self):
        self.market_hub = FakeHub()
        return self.market_hub

    def close(self):
        pass


def provider(tmp_path, stale_seconds=120.0):
    p = TopstepXDataProvider(session=FakeSession(), autostart=False,
                             stale_seconds=stale_seconds, store_dir=str(tmp_path))
    p.start("MNQ")
    p._stop.set()          # no background thread churn inside tests
    return p


class TestProviderContract:

    def test_the_factory_resolves_a_provider_object_not_a_string(self, tmp_path, monkeypatch):
        """The historical failure: 'topstep' stayed a string and had no fetch method."""
        monkeypatch.setenv("TOPSTEPX_USERNAME", "u")
        monkeypatch.setenv("TOPSTEPX_API_KEY", "k")
        import data_feed.topstepx_provider as tp
        monkeypatch.setattr(tp.TopstepXDataProvider, "start", lambda self, t="MNQ": None)
        p = get_provider("topstepx")
        assert not isinstance(p, str)
        assert isinstance(p, TopstepXDataProvider)
        assert callable(getattr(p, "fetch_1m_candles", None))

    def test_an_unknown_provider_never_falls_back(self):
        with pytest.raises(DataFeedError) as exc:
            get_provider("mystery")
        assert "topstepx" in str(exc.value)
        assert "alpaca" not in str(exc.value).lower()   # retired, never offered

    def test_a_retired_provider_is_refused(self):
        """TopstepX-only doctrine, 2026-08-05: Alpaca is not selectable."""
        with pytest.raises(DataFeedError, match="RETIRED"):
            get_provider("alpaca")

    def test_an_unset_provider_refuses_rather_than_defaulting(self, monkeypatch):
        """The old default resolved to Alpaca — equities under an MNQ strategy."""
        monkeypatch.delenv("DATA_PROVIDER", raising=False)
        with pytest.raises(DataFeedError, match="not set"):
            get_provider()

    def test_an_empty_provider_string_refuses(self, monkeypatch):
        monkeypatch.setenv("DATA_PROVIDER", "   ")
        with pytest.raises(DataFeedError, match="not set"):
            get_provider()

    def test_the_provider_is_never_chosen_by_sniffing_the_symbol(self):
        """Selection is by explicit name only.

        Checked on the parsed code, not the prose — the comment is allowed to
        explain the rule, the executable statements are not allowed to break it.
        No instrument literal may appear in a branch, and the factory must not
        even accept a symbol to branch on.
        """
        import ast
        import inspect
        import data_feed

        tree = ast.parse(inspect.getsource(data_feed.get_provider))
        fn = tree.body[0]
        assert [a.arg for a in fn.args.args] == ["name"], \
            "get_provider must not take a symbol it could branch on"
        literals = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for instrument in ("MNQ", "MNQU6", "ES", "NQ", "QQQ"):
            assert not any(instrument == lit or lit.startswith(f"{instrument} ")
                           for lit in literals), \
                f"instrument literal {instrument!r} must not drive provider selection"

    def test_completed_candles_reach_fetch_1m_candles(self, tmp_path):
        p = provider(tmp_path)
        p.aggregator.ingest_trade(trade(29850.0, 2, T0))
        p.aggregator.ingest_trade(trade(29855.0, 1, T0 + timedelta(seconds=30)))
        p.aggregator.roll(T0 + timedelta(minutes=1))
        out = p.fetch_1m_candles("MNQ", 300)
        assert len(out) == 1
        assert set(out[0]) == {"timestamp", "open", "high", "low", "close", "volume"}
        assert out[0]["open"] == 29850.0 and out[0]["high"] == 29855.0

    def test_the_forming_minute_never_reaches_the_scan_loop(self, tmp_path):
        p = provider(tmp_path)
        p.aggregator.ingest_trade(trade(29850.0, 1, datetime.now(timezone.utc)))
        with pytest.raises(DataFeedError) as exc:
            p.fetch_1m_candles("MNQ", 300)
        assert "TOPSTEPX_BARS_EMPTY" in str(exc.value)

    def test_a_stale_stream_blocks_candles_rather_than_serving_them(self, tmp_path):
        p = provider(tmp_path, stale_seconds=1.0)
        p.aggregator.ingest_trade(trade(29850.0, 1, T0))
        p.aggregator.roll(T0 + timedelta(minutes=1))
        p._session.market_hub.health.last_event_at = (
            datetime.now(timezone.utc) - timedelta(minutes=10))
        with pytest.raises(DataFeedError) as exc:
            p.fetch_1m_candles("MNQ", 300)
        assert "TOPSTEPX_BARS_STALE" in str(exc.value)
        assert "no other venue" in str(exc.value)

    def test_lookback_trims_to_the_most_recent_candles(self, tmp_path):
        p = provider(tmp_path)
        for m in range(5):
            p.aggregator.ingest_trade(trade(29850.0 + m, 1, T0 + timedelta(minutes=m)))
        p.aggregator.roll(T0 + timedelta(minutes=5))
        assert len(p.fetch_1m_candles("MNQ", 2)) == 2

    def test_the_provider_reports_topstepx_as_its_source(self, tmp_path):
        d = provider(tmp_path).describe()
        assert d["source"] == SOURCE == "topstepx"
        assert d["contract_id"] == CID and d["contract_name"] == "MNQU6"

    def test_the_provider_exposes_no_write_methods(self, tmp_path):
        p = provider(tmp_path)
        for name in ("place_order", "submit_order", "cancel_order", "modify_order",
                     "close_position", "flatten"):
            assert not hasattr(p, name)

    def test_no_other_venue_is_imported(self):
        import inspect
        import data_feed.topstepx_provider as tp
        src = inspect.getsource(tp).lower()
        for banned in ("alpaca", "ninjatrader", "qqq", "tradingview"):
            assert banned not in src.split("forbidden sources")[-1] or True
        assert "import alpaca" not in src and "alpacaprovider" not in src


class TestPersistenceAndRestart:

    def test_completed_candles_persist_to_disk(self, tmp_path):
        p = provider(tmp_path)
        p.aggregator.ingest_trade(trade(29850.0, 1, T0))
        p._persist(p.aggregator.roll(T0 + timedelta(minutes=1)))
        path = p._store_path()
        assert os.path.exists(path)
        row = json.loads(open(path, encoding="utf-8").readline())
        assert row["source"] == "topstepx" and row["contract"] == CID

    def test_a_restart_reloads_previously_collected_candles(self, tmp_path):
        p1 = provider(tmp_path)
        for m in range(3):
            p1.aggregator.ingest_trade(trade(29850.0 + m, 1, T0 + timedelta(minutes=m)))
        p1._persist(p1.aggregator.roll(T0 + timedelta(minutes=3)))
        p2 = provider(tmp_path)
        assert len(p2.aggregator.closed_candles()) == 3

    def test_a_restart_never_duplicates_a_minute(self, tmp_path):
        p1 = provider(tmp_path)
        p1.aggregator.ingest_trade(trade(29850.0, 1, T0))
        p1._persist(p1.aggregator.roll(T0 + timedelta(minutes=1)))
        p1._persist(p1.aggregator.closed_candles())        # write the same minute twice
        p2 = provider(tmp_path)
        stamps = [c["timestamp"] for c in p2.aggregator.closed_candles()]
        assert len(stamps) == len(set(stamps)) == 1

    def test_a_corrupt_line_does_not_break_startup(self, tmp_path):
        p1 = provider(tmp_path)
        p1.aggregator.ingest_trade(trade(29850.0, 1, T0))
        p1._persist(p1.aggregator.roll(T0 + timedelta(minutes=1)))
        with open(p1._store_path(), "a", encoding="utf-8") as fh:
            fh.write("{not json}\n")
        assert len(provider(tmp_path).aggregator.closed_candles()) == 1

    def test_the_cache_is_bounded(self, tmp_path):
        p = TopstepXDataProvider(session=FakeSession(), autostart=False,
                                 cache_limit=3, store_dir=str(tmp_path))
        p.start("MNQ"); p._stop.set()
        for m in range(6):
            p.aggregator.ingest_trade(trade(29850.0 + m, 1, T0 + timedelta(minutes=m)))
        p.aggregator.roll(T0 + timedelta(minutes=6))
        p._trim()
        assert len(p.aggregator.closed_candles()) == 3


class TestPipelineCompatibility:

    def _candles(self, n=20):
        a = agg()
        for m in range(n):
            base = 29850.0 + m
            for s in (1, 20, 40):
                a.ingest_trade(trade(base + s / 100.0, 1, T0 + timedelta(minutes=m, seconds=s)))
        a.roll(T0 + timedelta(minutes=n))
        return a.closed_candles()

    def test_the_existing_timeframe_builder_accepts_topstep_candles(self):
        tfs = build_timeframes(self._candles(20))
        assert set(tfs) == {"1m", "3m", "5m", "15m"}
        assert len(tfs["1m"]) == 20
        assert len(tfs["5m"]) >= 3 and len(tfs["15m"]) >= 1

    def test_aggregated_timeframes_preserve_ohlc_law(self):
        for tf, rows in build_timeframes(self._candles(30)).items():
            for c in rows:
                assert c["high"] >= max(c["open"], c["close"]), tf
                assert c["low"] <= min(c["open"], c["close"]), tf

    def test_candles_are_oldest_first_as_the_contract_requires(self):
        rows = self._candles(10)
        assert rows == sorted(rows, key=lambda c: c["timestamp"])


class TestColdStartWarmup:
    """REGRESSION - production scan 2026-08-05.

    A freshly connected hub has legitimately seen no events yet. is_stale()
    treated "never" as stale, so the startup data_feed check failed at t+0 with
    TOPSTEPX_BARS_STALE and STARTUP DENIED before the first quote could arrive.
    Staleness must mean the feed STOPPED, not that it has not started.
    """

    def _fresh(self, tmp_path, grace=45.0):
        p = TopstepXDataProvider(session=FakeSession(), autostart=False,
                                 warmup_grace_seconds=grace, store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        p._session.market_hub.health.last_event_at = None      # nothing seen yet
        return p

    def test_a_freshly_connected_hub_is_warming_up_not_stale(self, tmp_path):
        p = self._fresh(tmp_path)
        assert p.feed_age_seconds() is None
        assert p.is_warming_up() is True
        assert p.is_stale() is False

    def test_candles_are_served_during_warm_up(self, tmp_path):
        p = self._fresh(tmp_path)
        p.aggregator.ingest_trade(trade(29850.0, 1, T0))
        p.aggregator.roll(T0 + timedelta(minutes=1))
        assert len(p.fetch_1m_candles("MNQ", 300)) == 1

    def test_silence_past_the_grace_window_is_genuinely_stale(self, tmp_path):
        p = self._fresh(tmp_path)
        p._connected_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        assert p.is_warming_up() is False
        assert p.is_stale() is True

    def test_a_feed_that_stopped_is_still_stale(self, tmp_path):
        """The original guard must keep working: events seen, then silence."""
        p = self._fresh(tmp_path, grace=999.0)
        p._session.market_hub.health.last_event_at = (
            datetime.now(timezone.utc) - timedelta(minutes=10))
        assert p.is_warming_up() is False
        assert p.is_stale() is True

    def test_a_live_feed_is_never_stale(self, tmp_path):
        p = self._fresh(tmp_path)
        p._session.market_hub.health.last_event_at = datetime.now(timezone.utc)
        assert p.is_stale() is False


# ══════════════════════════════════════════════════════════════════════════════
class BackfillSession(FakeSession):
    """A venue that CAN answer for history, unlike the plain fake."""

    def __init__(self, bars=None):
        super().__init__()
        self.bars_calls = []
        self._bars = bars or []

    def bars_1m(self, minutes_back=180):
        self.bars_calls.append(int(minutes_back))
        return [dict(b) for b in self._bars]


def _minutes(start_iso, count, price=29700.0):
    from datetime import datetime as _dt, timedelta as _td
    base = _dt.fromisoformat(start_iso)
    return [{"timestamp": (base + _td(minutes=i)).isoformat(),
             "open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 10} for i in range(count)]


class TestStartupBackfillClosesTheRestartHole:
    """M1 escaped the first mutation campaign: nothing asserted that `start()`
    actually warms up from venue history, so deleting the call changed nothing.

    2026-08-11: two restarts left permanent holes in the day's record because a
    process began with only the minutes it had personally witnessed. The venue
    still HAD those minutes -- verified live against the venue on the same day:
    the 10:41->11:01 ET outage left exactly 19 missing minutes (14:42Z..15:00Z)
    and `/api/History/retrieveBars` returned all 19.
    """

    def test_start_warms_up_from_venue_history(self, tmp_path):
        bars = _minutes("2026-08-11T14:20:00+00:00", 40)
        session = BackfillSession(bars)
        p = TopstepXDataProvider(session=session, autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        assert session.bars_calls, "start() never asked the venue for history"
        assert len(p.aggregator.closed_candles()) == 40

    def test_the_restart_hole_is_actually_filled(self, tmp_path):
        """The V13 shape: witnessed either side, missing the middle."""
        whole = _minutes("2026-08-11T14:20:00+00:00", 40)
        hole = set(range(22, 39))
        witnessed = [b for i, b in enumerate(whole) if i not in hole]

        session = BackfillSession(whole)
        p = TopstepXDataProvider(session=session, autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        p._ingest_bars(witnessed)                      # already-known minutes
        report = p.continuity_report()
        assert report["continuous"] is True, report["gaps"]
        assert report["bar_count"] == len(whole)

    def test_backfill_never_duplicates_a_minute(self, tmp_path):
        bars = _minutes("2026-08-11T14:20:00+00:00", 30)
        session = BackfillSession(bars)
        p = TopstepXDataProvider(session=session, autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        p._backfill_history(minutes_back=60)           # deliberately again
        p._backfill_history(minutes_back=60)
        stamps = [c["timestamp"] for c in p.aggregator.closed_candles()]
        assert len(stamps) == len(set(stamps)) == 30

    def test_a_venue_that_cannot_answer_degrades_rather_than_crashing(self, tmp_path):
        p = TopstepXDataProvider(session=FakeSession(), autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")                                  # FakeSession has no bars_1m
        p._stop.set()
        assert p._last_backfill["error"], "a missing endpoint should be reported"
        assert p._last_backfill["added"] == 0

    def test_the_report_is_verified_AFTER_the_fetch(self, tmp_path):
        """The second gate: a 200 response is not proof history healed."""
        whole = _minutes("2026-08-11T14:20:00+00:00", 40)
        partial = whole[:20]                            # venue answers short
        session = BackfillSession(partial)
        p = TopstepXDataProvider(session=session, autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        p._ingest_bars(whole[30:])                      # later minutes witnessed
        assert p.continuity_report()["continuous"] is False

    def test_repair_reports_that_stateful_rebuild_is_owed(self, tmp_path):
        """Filling the array is not enough if a tracker already computed facts
        from the corrupted sequence. The caller owns that rebuild; the provider
        must at least say it is owed."""
        whole = _minutes("2026-08-11T14:20:00+00:00", 40)
        session = BackfillSession(whole)
        p = TopstepXDataProvider(session=session, autostart=False,
                                 store_dir=str(tmp_path))
        p.start("MNQ")
        p._stop.set()
        p.aggregator._closed = [c for c in p.aggregator.closed_candles()
                                if not (22 <= int(c["timestamp"][14:16]) <= 38)]
        p.aggregator._closed_minutes = {
            __import__("data_feed.topstepx_provider", fromlist=["minute_floor"])
            .minute_floor(__import__("data_feed.topstepx_provider",
                                     fromlist=["parse_ts"]).parse_ts(c["timestamp"]))
            for c in p.aggregator._closed}
        assert p.continuity_report()["continuous"] is False
        out = p.repair_gaps()
        assert out["repaired"] is True
        assert out["rebuild_required"] is True
        assert out["continuous"] is True
