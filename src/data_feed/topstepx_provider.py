"""TopstepX market-data provider — one-minute MNQ candles from the live hub.

The scan loop asks for 1m candles through `BaseDataProvider.fetch_1m_candles`;
`timeframe_builder` derives 3m/5m/15m from those. So the entire transport seam
is: Topstep trade events -> completed 1m candles -> that one method. Nothing
else in the organism changes.

WHY TRADES AND NOT `/api/History/retrieveBars`: that endpoint accepts the
connection and never returns a byte on this account (verified 2026-08-05 across
four independent clients). The realtime market hub, on the same JWT, streams
quotes and trades continuously. So candles are built from the stream. This is
not a preference — it is the only Topstep-native source currently answering.

SOURCE PURITY: this module imports no other venue. Every price originates in a
TopstepX `GatewayTrade` event for the exact pinned contract. A trade for any
other contract is discarded rather than adapted.

Observed live payloads (2026-08-05, MNQU6):

    GatewayTrade -> ["CON.F.US.MNQ.U26", [
        {"symbolId": "F.US.MNQ", "price": 29850.5,
         "timestamp": "2026-08-05T14:51:54.908+00:00", "type": 0,
         "volume": 1, "contractId": "CON.F.US.MNQ.U26"}, ...]]

    GatewayQuote -> ["CON.F.US.MNQ.U26", {"lastPrice": ..., "bestBid": ...,
         "bestAsk": ..., "timestamp": ...}]

Note the trade payload is a LIST of trades per event, not a single trade.

THIS MODULE HAS NO WRITE METHODS. It cannot place, cancel or close anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from data_feed import candle_continuity as CONT
from data_feed.provider_interface import BaseDataProvider, DataFeedError

SOURCE = "topstepx"
DEFAULT_CACHE_LIMIT = 5000          # ~3.5 days of RTH minutes; bounded on purpose
DEFAULT_STALE_SECONDS = 120.0
# A hub that has just connected has legitimately seen no events yet. Treating
# that as "stale" fails the startup data-feed check before the first quote can
# arrive (observed 2026-08-05: STARTUP DENIED at t+0). Staleness means the feed
# STOPPED, not that it has not started, so a bounded warm-up window separates
# the two. After the window with still no event, it is stale for real.
DEFAULT_WARMUP_GRACE_SECONDS = 45.0


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_ts(value) -> datetime:
    """Parse a ProjectX timestamp to an aware UTC datetime. Never naive."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise DataFeedError(f"unparseable timestamp {value!r}") from None
    if dt.tzinfo is None:
        raise DataFeedError(f"naive timestamp {value!r}; UTC offset required")
    return dt.astimezone(timezone.utc)


def minute_floor(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


class MinuteCandleAggregator:
    """Trade events -> completed 1m OHLCV candles.

    A minute is emitted only once the clock has moved past it. The developing
    minute is never returned as a completed candle, because an engine that reads
    a forming bar as final evidence draws structure from a bar that has not
    happened yet.
    """

    def __init__(self, contract_id: str, tick_size: float = 0.0) -> None:
        self.contract_id = contract_id
        self.tick_size = float(tick_size or 0.0)
        self._open: "dict[datetime, dict]" = {}
        self._closed: "list[dict]" = []
        self._closed_minutes: set = set()
        self._seen_batches: list = []
        self.last_trade_at: "datetime | None" = None
        self.diagnostics = {"trades": 0, "duplicate_batches": 0, "late": 0,
                            "off_tick": 0, "foreign_contract": 0}

    # ── ingest ────────────────────────────────────────────────────────────────
    def ingest_trade(self, trade: dict) -> bool:
        """Fold one trade into its minute bucket. Returns True if it counted."""
        cid = trade.get("contractId") or trade.get("contract")
        if cid and cid != self.contract_id:
            self.diagnostics["foreign_contract"] += 1
            return False
        try:
            price = float(trade["price"])
            volume = float(trade.get("volume") or 0)
            ts = parse_ts(trade["timestamp"])
        except (KeyError, TypeError, ValueError, DataFeedError):
            return False

        # NO per-trade de-duplication. Identical (timestamp, price, size, side)
        # trades are NOT duplicates in futures — a swept order prints as many
        # same-price 1-lots in the same millisecond. Measured live on MNQU6
        # 2026-08-05: 2,584 trades carried 1,093 such collisions (one key
        # appeared 11 times), and treating them as duplicates discarded 39% of
        # real volume. Redelivery is guarded at the BATCH level in
        # `ingest_event`, which is where it actually occurs: over 421 consecutive
        # batches the hub repeated exactly zero.
        if self.tick_size > 0:
            steps = price / self.tick_size
            if abs(steps - round(steps)) > 1e-6:
                self.diagnostics["off_tick"] += 1

        bucket = minute_floor(ts)
        if bucket in self._closed_minutes:
            # Out-of-order arrival for a minute already published. Rewriting it
            # would change evidence an engine may already have consumed.
            self.diagnostics["late"] += 1
            return False

        c = self._open.get(bucket)
        if c is None:
            self._open[bucket] = {"timestamp": bucket.isoformat(), "open": price,
                                  "high": price, "low": price, "close": price,
                                  "volume": volume, "_first": ts, "_last": ts}
        else:
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["volume"] += volume
            if ts >= c["_last"]:
                c["close"] = price
                c["_last"] = ts
            if ts < c["_first"]:
                c["open"] = price          # a genuinely earlier trade re-opens it
                c["_first"] = ts
        self.diagnostics["trades"] += 1
        self.last_trade_at = max(self.last_trade_at or ts, ts)
        return True

    def ingest_event(self, args: list) -> int:
        """Handle one GatewayTrade payload: [contractId, [trade, ...]].

        Batch-level replay guard: a reconnect can redeliver a whole event, and
        re-folding it would double that batch's volume. The hash covers the
        entire payload, so two batches that merely contain similar trades stay
        distinct — only a byte-identical redelivery is dropped.
        """
        if not args or len(args) < 2:
            return 0
        try:
            digest = hashlib.sha1(
                json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        except Exception:  # noqa: BLE001 — an unhashable payload is still ingestible
            digest = None
        if digest is not None:
            if digest in self._seen_batches:
                self.diagnostics["duplicate_batches"] += 1
                return 0
            self._seen_batches.append(digest)
            if len(self._seen_batches) > 2000:
                del self._seen_batches[:1000]
        payload = args[1]
        rows = payload if isinstance(payload, list) else [payload]
        return sum(1 for r in rows if isinstance(r, dict) and self.ingest_trade(r))

    # ── close ─────────────────────────────────────────────────────────────────
    def roll(self, now: "datetime | None" = None) -> list:
        """Close every bucket strictly older than the current minute."""
        now = now or datetime.now(timezone.utc)
        boundary = minute_floor(now)
        newly = []
        for bucket in sorted(b for b in self._open if b < boundary):
            c = self._open.pop(bucket)
            c.pop("_first", None)
            c.pop("_last", None)
            self._closed.append(c)
            self._closed_minutes.add(bucket)
            newly.append(c)
        return newly

    def developing(self) -> "dict | None":
        """The forming minute, for diagnostics only. Never a completed candle."""
        if not self._open:
            return None
        bucket = max(self._open)
        c = dict(self._open[bucket])
        c.pop("_first", None)
        c.pop("_last", None)
        c["partial"] = True
        return c

    def closed_candles(self) -> list:
        return list(self._closed)


class TopstepXDataProvider(BaseDataProvider):
    """1m MNQ candles built from the TopstepX market hub. Read-only."""

    def __init__(self, *, contract_text: str = None, cache_limit: int = DEFAULT_CACHE_LIMIT,
                 stale_seconds: float = DEFAULT_STALE_SECONDS,
                 warmup_grace_seconds: float = DEFAULT_WARMUP_GRACE_SECONDS,
                 autostart: bool = True,
                 session=None, store_dir: str = None,
                 warmup_minutes: int = None) -> None:
        from broker.topstepx_readonly import TopstepXReadOnlySession

        username = (os.getenv("TOPSTEPX_USERNAME") or "").strip()
        api_key = (os.getenv("TOPSTEPX_API_KEY") or "").strip()
        if session is None and not (username and api_key):
            raise DataFeedError(
                "TopstepX data feed needs TOPSTEPX_USERNAME and TOPSTEPX_API_KEY. "
                "This provider never falls back to another venue.")

        self._session = session or TopstepXReadOnlySession(username, api_key)
        self._cache_limit = int(cache_limit)
        self._stale_seconds = float(stale_seconds)
        self._warmup_grace = float(warmup_grace_seconds)
        self._connected_at: "datetime | None" = None
        self._lock = threading.Lock()
        self.runtime = None            # the shared transport owner, set in start()
        self._owns_runtime = False
        self._stop = threading.Event()
        self.contract = None
        self.aggregator: "MinuteCandleAggregator | None" = None
        self.last_quote = {}
        # EVENT-WAKE-ACTIONABLE-STRUCTURE-1. Attached by the production owner
        # when it wants to be woken; None everywhere else, so every existing
        # caller -- replay, smoke, tools -- behaves byte-identically.
        self.wake_registry = None
        self.store_dir = store_dir or os.path.join(_repo_root(), "data", "market_data", "topstepx")
        # CANDLE-CONTINUITY. How far back warm-up reaches on start. Wide enough
        # that a normal patch-and-relaunch outage is fully recoverable; the
        # venue's own `bars()` caps the response, so asking generously is free.
        self.warmup_minutes = int(warmup_minutes or 240)
        self._last_backfill = None

        if autostart:
            self.start(contract_text or os.getenv("TOPSTEPX_CONTRACT") or "MNQ")

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self, contract_text: str = "MNQ", *, runtime=None) -> None:
        """Attach candle aggregation to a market runtime.

        When `runtime` is supplied this provider becomes a pure CONSUMER: it
        subscribes and never pumps, reconnects or closes the socket. Given no
        runtime it creates one and owns it, so standalone collection still works
        — but even then the pump lives in exactly one implementation.
        """
        from broker.topstepx_market_runtime import TopstepXMarketRuntime

        self._session.authenticate()
        self.contract = self._session.resolve_contract(contract_text)
        self.aggregator = MinuteCandleAggregator(self.contract.id, self.contract.tick_size)
        self._load_persisted()
        # CANDLE-CONTINUITY (2026-08-11). Before this call, a restart began with
        # only the minutes this process had personally witnessed, so downtime
        # became a permanent hole in history that nothing reported. Warm-up from
        # the venue's own closed bars runs BEFORE the first scan, which is also
        # why no stateful detector needs rebuilding here: none has run yet.
        self._backfill_history(minutes_back=self.warmup_minutes)

        self._owns_runtime = runtime is None
        self.runtime = runtime or TopstepXMarketRuntime(
            self._session, self.contract, stop_event=self._stop)
        self.runtime.attach("candle-provider", "GatewayTrade", self._on_trade)
        self.runtime.attach("candle-provider", "GatewayQuote", self._on_quote)
        self._connected_at = datetime.now(timezone.utc)
        if self._owns_runtime:
            self.runtime.start("candle-provider")

    @property
    def _thread(self):
        """The pump thread, wherever it actually lives."""
        return self.runtime.pump_thread if self.runtime is not None else None

    @_thread.setter
    def _thread(self, value):
        return None                 # ownership is the runtime's, not this class's

    def stop(self) -> None:
        self._stop.set()
        # Only the owner tears the transport down. A consumer that closed a
        # shared hub would silently blind every other subscriber.
        if self.runtime is not None and self._owns_runtime:
            self.runtime.stop()

    # ── handlers ──────────────────────────────────────────────────────────────
    def _on_trade(self, args) -> None:
        # Rolling happens here, on the dispatch that just delivered data. It used
        # to live in this provider's own pump loop; with the pump owned by the
        # shared runtime there is no such loop, and a minute that never rolled
        # would never be persisted or served.
        with self._lock:
            self.aggregator.ingest_event(args)
            newly = self.aggregator.roll()
            if newly:
                self._persist(newly)
                self._trim()
        # EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — SIGNAL ONLY, OUTSIDE THE LOCK.
        #
        # A completed bar MAY have created something worth watching. That is the
        # only thing this thread is permitted to conclude: it does not refresh,
        # does not detect, does not build a snapshot, does not run the toolbox,
        # and never calls the Brain. The production owner thread does all of it.
        if newly and self.wake_registry is not None:
            self.wake_registry.note_bar_closed()

    def _on_quote(self, args) -> None:
        if args and len(args) >= 2 and isinstance(args[1], dict):
            q = args[1]
            with self._lock:
                for k in ("lastPrice", "bestBid", "bestAsk", "timestamp"):
                    if q.get(k) is not None:
                        self.last_quote[k] = q[k]
                self.last_quote["received_at"] = datetime.now(timezone.utc).isoformat()
                bid, ask = self.last_quote.get("bestBid"), self.last_quote.get("bestAsk")
            # EVENT-WAKE — interaction DETECTION, never authorization. Evaluated
            # outside the provider lock against an immutable published snapshot;
            # this thread owns only its own OUTSIDE/INSIDE episode state and may
            # do nothing but set an event.
            if self.wake_registry is not None:
                try:
                    self.wake_registry.on_quote(bid=bid, ask=ask)
                except Exception:  # noqa: BLE001 — watching may never kill the feed
                    pass

    # ── persistence ───────────────────────────────────────────────────────────
    def _store_path(self) -> str:
        safe = (self.contract.id or "unknown").replace(".", "_")
        return os.path.join(self.store_dir, f"{safe}.jsonl")

    def _load_persisted(self) -> int:
        """Reload candles this bot previously built from Topstep events.

        Restarting must not throw away collected history — warm-up is the scarce
        resource here. Timestamps already present are skipped, so a restart can
        never duplicate a minute.
        """
        path = self._store_path()
        if not os.path.exists(path):
            return 0
        loaded = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    c = json.loads(line)
                    ts = parse_ts(c["timestamp"])
                except Exception:  # noqa: BLE001 — a bad line must not kill startup
                    continue
                bucket = minute_floor(ts)
                if bucket in self.aggregator._closed_minutes:
                    continue
                self.aggregator._closed.append(
                    {"timestamp": bucket.isoformat(), "open": float(c["open"]),
                     "high": float(c["high"]), "low": float(c["low"]),
                     "close": float(c["close"]), "volume": float(c.get("volume") or 0)})
                self.aggregator._closed_minutes.add(bucket)
                loaded += 1
        self.aggregator._closed.sort(key=lambda x: x["timestamp"])
        return loaded

    # ── canonical history ─────────────────────────────────────────────────────
    def _ingest_bars(self, bars: list) -> int:
        """Fold venue bars into the aggregator's closed record. Never duplicates.

        The aggregator's own minute set is the single identity authority, so a
        bar this process already built is never replaced by a REST copy of the
        same minute: two owners of one bar is the defect, not a merge conflict
        to arbitrate.
        """
        added = 0
        for bar in bars or []:
            stamp = parse_ts(bar.get("timestamp"))
            if stamp is None:
                continue
            bucket = minute_floor(stamp)
            if bucket in self.aggregator._closed_minutes:   # noqa: SLF001
                continue
            self.aggregator._closed.append({                # noqa: SLF001
                "timestamp": bucket.isoformat(),
                "open": float(bar["open"]), "high": float(bar["high"]),
                "low": float(bar["low"]), "close": float(bar["close"]),
                "volume": float(bar.get("volume") or 0)})
            self.aggregator._closed_minutes.add(bucket)     # noqa: SLF001
            added += 1
        if added:
            self.aggregator._closed.sort(key=lambda x: x["timestamp"])  # noqa: SLF001
        return added

    def _fetch_bars(self, minutes_back: int) -> list:
        """Closed 1m bars from the venue. `bars()` pins includePartialBar=False
        and sorts oldest-first, so the forming minute can never enter here."""
        fetch = getattr(self._session, "bars_1m", None)
        if fetch is None:
            raise DataFeedError("session exposes no historical bars endpoint")
        return fetch(minutes_back=int(minutes_back)) or []

    def _backfill_history(self, *, minutes_back: int = None) -> dict:
        """Warm up from venue history, then PROVE the result is continuous.

        Two gates, not one. A 200 response is not evidence that history healed;
        without the second verification we would only trade "we never noticed
        the gap" for "we assumed the repair worked", which is the same disease.

        Never raises. A venue that cannot be reached leaves the record exactly
        as it was and says so -- degraded, which is honest, rather than absent,
        which is a lie.
        """
        minutes = int(minutes_back or self.warmup_minutes)
        report = {"attempted": True, "added": 0, "error": None, "minutes_back": minutes,
                  "returned": 0, "oldest_returned": None, "newest_returned": None}
        try:
            with self._lock:
                fetched = self._fetch_bars(minutes)
                # WHAT THE VENUE ACTUALLY SAID, recorded separately from what was
                # ingested. `added` alone cannot distinguish "the venue returned
                # nothing" from "the store already held every minute offered" --
                # two very different facts, and startup authority needs both.
                stamps = sorted(s for s in (parse_ts(b.get("timestamp"))
                                            for b in fetched or []) if s is not None)
                report["returned"] = len(fetched or [])
                report["oldest_returned"] = stamps[0].isoformat() if stamps else None
                report["newest_returned"] = stamps[-1].isoformat() if stamps else None
                added = self._ingest_bars(fetched)
                if added:
                    self._persist(self.aggregator.closed_candles()[-added:])
                report["added"] = added
        except Exception as exc:  # noqa: BLE001 — warm-up may never kill startup
            report["error"] = f"{type(exc).__name__}: {exc}"
        # THE SECOND GATE.
        report.update(self.continuity_report())
        self._last_backfill = report
        return report

    def startup_history_report(self) -> dict:
        """The warm-up verdict, PUBLICLY readable.

        It was already recorded; nothing ever read it. A launcher that cannot see
        the warm-up result cannot tell a healthy start from a total history
        failure, which is precisely how zero bars passed for success.
        """
        return dict(self._last_backfill) if self._last_backfill else {}

    def canonical_candles(self) -> list:
        """The canonical closed record as-is.

        Deliberately NOT `fetch_1m_candles`: that one refuses on a stale or empty
        feed, which is right for a scan and wrong for a startup audit that has to
        be able to REPORT emptiness rather than raise on it.
        """
        with self._lock:
            return list(self.aggregator.closed_candles()) if self.aggregator else []

    @property
    def connected_at(self):
        """When this process attached to the stream. Used to prove that history
        did not begin at process boot."""
        return self._connected_at

    def continuity_report(self) -> dict:
        """What the canonical record actually looks like right now."""
        with self._lock:
            candles = list(self.aggregator.closed_candles())
        return CONT.summarize(candles, timeframe="1m")

    def repair_gaps(self, *, pad_minutes: int = 5) -> dict:
        """Runtime repair: refetch around every hole, then re-verify.

        Padded on both sides because a pivot needs candles either side of it to
        exist; refetching only the literal missing minutes would leave the
        swings at each seam decided by the neighbours the outage removed.

        `rebuild_required` is the honest part: inserting historical bars can
        change facts that stateful detectors already computed from the corrupted
        sequence. Repairing the array while a false swing still lives in a
        tracker would be a worse failure than the gap, because it would look
        fixed. The caller owns that rebuild; this only reports that it is owed.
        """
        before = self.continuity_report()
        if before.get("continuous"):
            return {"repaired": False, "reason": "already continuous", **before}
        window = CONT.repair_window(before.get("gaps") or [], pad_minutes=pad_minutes)
        minutes = self.warmup_minutes
        if window:
            span = (self._now() - window[0]).total_seconds() / 60.0
            minutes = max(int(span) + pad_minutes, pad_minutes)
        outcome = self._backfill_history(minutes_back=minutes)
        return {"repaired": bool(outcome.get("added")),
                "rebuild_required": bool(outcome.get("added")),
                "gaps_before": before.get("gap_count"),
                "gaps_after": outcome.get("gap_count"), **outcome}

    def _now(self):
        return datetime.now(timezone.utc)

    def _persist(self, candles: list) -> None:
        os.makedirs(self.store_dir, exist_ok=True)
        with open(self._store_path(), "a", encoding="utf-8") as fh:
            for c in candles:
                fh.write(json.dumps({**c, "source": SOURCE,
                                     "contract": self.contract.id}) + "\n")

    def _trim(self) -> None:
        if len(self.aggregator._closed) > self._cache_limit:
            drop = len(self.aggregator._closed) - self._cache_limit
            del self.aggregator._closed[:drop]

    # ── freshness ─────────────────────────────────────────────────────────────
    def feed_age_seconds(self, now: "datetime | None" = None) -> "float | None":
        hub = self._session.market_hub
        if hub is None:
            return None
        return hub.health.age_seconds(now)

    def is_warming_up(self, now: "datetime | None" = None) -> bool:
        """Connected, but no event has arrived yet and the grace window is open."""
        if self._connected_at is None or self.feed_age_seconds(now) is not None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - self._connected_at).total_seconds() <= self._warmup_grace

    def is_stale(self, now: "datetime | None" = None) -> bool:
        age = self.feed_age_seconds(now)
        if age is None:
            # No event yet: warming up is not stale; past the grace window it is.
            return not self.is_warming_up(now)
        return age > self._stale_seconds

    # ── BaseDataProvider ──────────────────────────────────────────────────────
    def fetch_1m_candles(self, symbol: str, lookback_bars: int = 300) -> list:
        """Completed Topstep 1m candles, oldest-first. Never the forming minute."""
        if self.aggregator is None:
            raise DataFeedError("TopstepX provider was never started")
        if self.is_stale():
            age = self.feed_age_seconds()
            raise DataFeedError(
                f"TOPSTEPX_BARS_STALE: market stream age "
                f"{'never' if age is None else f'{age:.0f}s'} exceeds "
                f"{self._stale_seconds:.0f}s. Refusing to serve stale candles; "
                f"no other venue is substituted.")
        with self._lock:
            self.aggregator.roll()
            candles = self.aggregator.closed_candles()
        if not candles:
            raise DataFeedError(
                "TOPSTEPX_BARS_EMPTY: no completed Topstep minute yet. The stream is "
                "live; candles accumulate one per minute. No substitute source exists.")
        out = [{k: c[k] for k in ("timestamp", "open", "high", "low", "close", "volume")}
               for c in candles]
        return out[-int(lookback_bars):] if lookback_bars else out

    def describe(self) -> dict:
        agg = self.aggregator
        return {"source": SOURCE,
                "provider": type(self).__name__,
                "contract_id": self.contract.id if self.contract else None,
                "contract_name": self.contract.name if self.contract else None,
                "tick_size": self.contract.tick_size if self.contract else None,
                "closed_candles": len(agg.closed_candles()) if agg else 0,
                "developing": agg.developing() if agg else None,
                "diagnostics": dict(agg.diagnostics) if agg else {},
                "feed_age_seconds": self.feed_age_seconds(),
                "stale": self.is_stale(),
                "last_quote": dict(self.last_quote)}
