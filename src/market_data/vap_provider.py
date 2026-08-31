"""VAP CAPTURE — the second GatewayTrade consumer. Records what is being thrown away.

LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 (2026-08-30).

WHAT WAS BEING LOST. Every trade arrives with price, size and a millisecond
timestamp. `MinuteCandleAggregator.ingest_trade` folds them into OHLCV and the
trade dict goes out of scope -- so `volume += volume` is the exact line where
price attribution dies. Nothing malicious, nothing broken: the candle layer was
never asked to remember where inside the bar the business happened.

THIS IS A RECORDER. It computes no POC, no value area, no delta, no acceptance,
no opinion. It has no route to the Brain, the snapshot, the execution gate or
any strategy surface, and it must not acquire one here.

WHY IT CANNOT DISTURB THE CANDLES. `SignalRHub.on` deliberately APPENDS
handlers -- it was written that way precisely so a second consumer could share
one socket without unsubscribing the first. So this attaches beside
`candle-provider` through `TopstepXMarketRuntime.attach`, keeps its own buckets,
its own batch ring and its own lock, and touches no aggregator state. The candle
provider is not modified by this unit at all.

THE HONEST CLAIM, AND ITS CEILING. There is no venue trade id and no sequence
number, and identical (timestamp, price, size) prints are LEGITIMATELY distinct
-- 2,584 trades on 2026-08-05 carried 1,093 such collisions, and treating them
as duplicates discarded 39% of real volume. So there is no per-trade
deduplication here, ever. Byte-identical batch redelivery is caught by the same
payload-hash guard the aggregator uses; a re-framed batch is not, and this
module does not pretend otherwise.

    steady state   strongest available
    reconnect      duplicate uncertainty remains
    restart        duplicate uncertainty remains (the ring is RAM)

OBSERVED-ZERO IS EARNED, NOT ASSUMED. A minute may be sealed as observed-zero
only when `venue_calendar` says the venue was expected to print, capture was
attached before the minute began, the connection generation never changed
across it, and a later trade proves capture was still live afterwards. Anything
weaker is UNPROVEN and writes nothing -- because an absent row means no
evidence, and that must never read as zero.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

from market_data import price_ticks as TICKS
from market_data import vap_store as STORE
from market_data import venue_calendar as VC

SCHEMA = "vap_capture.v1"

CONSUMER_NAME = "vap-capture"
TRADE_EVENT = "GatewayTrade"

#: Bounded ring of payload digests, mirroring the aggregator's own guard.
_BATCH_RING = 2000
_BATCH_TRIM = 1000


def _parse_ts(value):
    """Any venue timestamp -> aware UTC datetime, or None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def minute_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


class VapCaptureProvider:
    """Minute x integer-tick observed volume, sealed on the minute boundary.

    Constructed with the contract it is keyed to. `attach(runtime)` registers it
    as a named consumer; nothing else in production may drive it.
    """

    def __init__(self, *, contract_id: str, tick_size: float, store_dir: str,
                 instrument: str = "MNQ", clock=None) -> None:
        self.contract_id = str(contract_id)
        self.tick_size = _num(tick_size)
        self.store_dir = store_dir
        self.instrument = instrument
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._runtime = None
        #: minute -> bucket. A bucket is only ever written by this class.
        self._open: dict = {}
        self._seen_batches: list = []
        self._sealed_minutes: set = set()
        self._last_generation = None
        #: The minute capture attached during. It can never be COMPLETE, and no
        #: later trade may promote it -- capture simply was not there for its start.
        self._attached_minute = None
        self._attached_at = None
        self.diagnostics = {"trades": 0, "duplicate_batches": 0, "off_grid": 0,
                            "foreign_contract": 0, "sealed": 0, "persist_failed": 0,
                            "observed_zero": 0, "unproven": 0, "interrupted": 0,
                            "partial_start": 0}

    # ── attachment ───────────────────────────────────────────────────────────

    def attach(self, runtime) -> "VapCaptureProvider":
        """Register beside the candle provider on the one shared runtime."""
        self._runtime = runtime
        self._attached_at = self._clock()
        self._attached_minute = minute_floor(self._attached_at)
        self._last_generation = getattr(runtime, "connection_generation", None)
        self._sealed_minutes = STORE.sealed_minutes(self.store_dir, self.contract_id)
        runtime.attach(CONSUMER_NAME, TRADE_EVENT, self.on_trade)
        return self

    @property
    def generation(self):
        return getattr(self._runtime, "connection_generation", None)

    # ── ingestion ────────────────────────────────────────────────────────────

    def on_trade(self, args) -> int:
        """One GatewayTrade payload. Never raises: capture may not kill the feed."""
        try:
            with self._lock:
                gen = self.generation
                self._note_generation(gen)
                folded = self._ingest_event(args, gen)
                self._seal_elapsed(gen)
                return folded
        except Exception:  # noqa: BLE001 — a recorder must never break the market feed
            return 0

    def _note_generation(self, gen) -> None:
        """A changed generation means the socket dropped. Every minute still
        open was being observed across that break and can never be COMPLETE."""
        if self._last_generation is None:
            self._last_generation = gen
            return
        if gen != self._last_generation:
            for bucket in self._open.values():
                bucket["interrupted"] = True
            self._last_generation = gen
            # Capture resumed mid-minute, exactly as at a cold attach: the
            # current minute's start was not observed on this generation.
            self._attached_minute = minute_floor(self._clock())

    def _ingest_event(self, args, gen) -> int:
        if not args or len(args) < 2:
            return 0
        # BATCH-LEVEL REPLAY GUARD ONLY. The hash covers the entire payload, so
        # two batches that merely contain similar trades stay distinct and only
        # a byte-identical redelivery is dropped. Nothing here deduplicates an
        # individual print.
        try:
            digest = hashlib.sha1(
                json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        except Exception:  # noqa: BLE001
            digest = None
        if digest is not None:
            if digest in self._seen_batches:
                self.diagnostics["duplicate_batches"] += 1
                return 0
            self._seen_batches.append(digest)
            if len(self._seen_batches) > _BATCH_RING:
                del self._seen_batches[:_BATCH_TRIM]
        payload = args[1]
        rows = payload if isinstance(payload, list) else [payload]
        return sum(1 for r in rows
                   if isinstance(r, dict) and self._ingest_trade(r, gen))

    def _ingest_trade(self, trade: dict, gen) -> bool:
        cid = trade.get("contractId") or trade.get("contract")
        if cid and str(cid) != self.contract_id:
            self.diagnostics["foreign_contract"] += 1
            return False
        ts = _parse_ts(trade.get("timestamp"))
        volume = _num(trade.get("volume"))
        if ts is None or volume is None:
            return False
        # OFF-GRID IS REFUSED, NOT RELOCATED. Rounding a price the venue cannot
        # quote into a neighbouring bucket would invent a trade there.
        index = TICKS.tick_index(trade.get("price"), self.tick_size)
        if index is None:
            self.diagnostics["off_grid"] += 1
            return False
        bucket = minute_floor(ts)
        if bucket.isoformat() in self._sealed_minutes:
            return False                      # already durably sealed; never rewritten
        b = self._open.get(bucket)
        if b is None:
            b = self._open[bucket] = {
                "levels": {}, "raw_type": {}, "unknown_type": 0.0,
                "trades": 0, "generation": gen, "interrupted": False}
        b["levels"][index] = b["levels"].get(index, 0.0) + volume
        # RAW TYPE, UNINTERPRETED. The code is preserved exactly as it arrived.
        # A missing or unusable code becomes `unknown`, never a default of 0 --
        # defaulting it would manufacture the very side evidence this unit
        # deliberately refuses to claim.
        raw = trade.get("type")
        if raw is None:
            b["unknown_type"] += volume
        else:
            key = str(raw)
            b["raw_type"][key] = b["raw_type"].get(key, 0.0) + volume
        b["trades"] += 1
        self.diagnostics["trades"] += 1
        return True

    # ── sealing ──────────────────────────────────────────────────────────────

    def _classify(self, minute: datetime, bucket) -> str:
        """The capture-continuity verdict for one elapsed minute."""
        if bucket is not None and bucket.get("interrupted"):
            return STORE.INTERRUPTED
        if self._attached_minute is not None and minute <= self._attached_minute:
            return STORE.PARTIAL_START
        if bucket is not None and bucket.get("generation") != self._last_generation:
            return STORE.INTERRUPTED
        # VENUE CADENCE IS THE SOLE SCHEDULE AUTHORITY. A minute the venue was
        # not scheduled to print, or whose schedule we cannot prove, can never
        # be COMPLETE -- and on an unknown-cadence date that is the answer even
        # when trades were seen, because the window's expectation is unproven.
        if not VC.is_expected(minute, self.instrument):
            return STORE.UNPROVEN
        return STORE.COMPLETE

    def _seal_elapsed(self, gen, *, now=None) -> list:
        """Seal every minute strictly older than the current one.

        Returns one verdict per elapsed minute, INCLUDING the ones that write
        nothing. A caller (and a test) can therefore see that an unproven empty
        minute was considered and refused, rather than inferring it from silence.
        """
        boundary = minute_floor(now or self._clock())
        verdicts = []
        for minute in sorted(m for m in self._open if m < boundary):
            bucket = self._open.pop(minute)
            verdicts.append(self._persist(minute, bucket, gen))

        # GAP MINUTES. A later trade proves capture was live after them, so an
        # expected minute with no trades, observed end to end on one unbroken
        # generation, is an OBSERVED-ZERO minute. Every gap minute is judged on
        # its OWN venue cadence -- a maintenance hour inside a gap does not
        # inherit the expectation of the trading minutes around it.
        for minute in self._gap_minutes(boundary):
            verdicts.append(self._persist(minute, None, gen))
        return verdicts

    def _gap_minutes(self, boundary: datetime) -> list:
        """Elapsed minutes with no bucket, between the last sealed one and now."""
        if not self._sealed_minutes:
            return []
        try:
            last = max(datetime.fromisoformat(m) for m in self._sealed_minutes)
        except Exception:  # noqa: BLE001
            return []
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        out, cursor = [], last + timedelta(minutes=1)
        # Bounded: a long outage must not produce an unbounded seal sweep. One
        # CME day of minutes is far more than a live gap can legitimately be.
        guard = 0
        while cursor < boundary and guard < 1500:
            guard += 1
            if cursor.isoformat() not in self._sealed_minutes and cursor not in self._open:
                out.append(cursor)
            cursor += timedelta(minutes=1)
        return out

    def _persist(self, minute: datetime, bucket, gen) -> dict:
        status = self._classify(minute, bucket)
        empty = bucket is None
        # AN EMPTY MINUTE IS ONLY EVER WRITTEN WHEN IT IS PROVABLY OBSERVED-ZERO.
        # Absent rows already mean "no evidence"; writing UNPROVEN placeholders
        # for every unexpected minute would fill the store with non-evidence.
        if empty and status != STORE.COMPLETE:
            self.diagnostics["unproven"] += 1
            return {"minute": minute.isoformat(), "status": status,
                    "persisted": False, "observed_zero_volume": False}
        record = STORE.build_record(
            contract_id=self.contract_id, minute=minute.isoformat(), status=status,
            tick_size=self.tick_size,
            levels={} if empty else bucket["levels"],
            raw_type_volume={} if empty else bucket["raw_type"],
            unknown_type_volume=0.0 if empty else bucket["unknown_type"],
            trades_observed=0 if empty else bucket["trades"],
            connection_generation=gen,
            observed_zero_volume=empty,
            sealed_at=self._clock().isoformat())
        ok = STORE.append(self.store_dir, record)
        if ok:
            self._sealed_minutes.add(minute.isoformat())
            self.diagnostics["sealed"] += 1
            if record["observed_zero_volume"]:
                self.diagnostics["observed_zero"] += 1
            if status == STORE.INTERRUPTED:
                self.diagnostics["interrupted"] += 1
            if status == STORE.PARTIAL_START:
                self.diagnostics["partial_start"] += 1
        else:
            # NOT DURABLE, NOT SEALED. The minute is not added to the sealed set
            # and the caller is told, so nothing downstream may treat an
            # unwritten minute as recorded history.
            self.diagnostics["persist_failed"] += 1
        return {"minute": minute.isoformat(), "status": status, "persisted": ok,
                "observed_zero_volume": record["observed_zero_volume"]}

    # ── observability ────────────────────────────────────────────────────────

    def describe(self) -> dict:
        with self._lock:
            return {"schema": SCHEMA, "consumer": CONSUMER_NAME,
                    "contract_id": self.contract_id, "tick_size": self.tick_size,
                    "attached_at": None if self._attached_at is None
                    else self._attached_at.isoformat(),
                    "connection_generation": self.generation,
                    "open_minutes": len(self._open),
                    "sealed_minutes": len(self._sealed_minutes),
                    "store": STORE.store_path(self.store_dir, self.contract_id),
                    "diagnostics": dict(self.diagnostics),
                    "claim": ("observed traded volume at price; no venue trade id "
                              "or sequence number exists, so exactly-once delivery "
                              "is not claimed across reconnect or restart")}
