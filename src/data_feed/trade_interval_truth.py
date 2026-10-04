"""Durable extrema and coverage facts from the canonical raw trade stream.

This module records only exact timestamped trade extrema and the provenance
needed to say whether those extrema cover an uninterrupted live interval. It
does not retain raw trades and has no strategy or execution authority.
"""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone


SCHEMA = "trade_interval_truth.v1"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
CLOSED = "CLOSED"
_STATUSES = {COMPLETE, INCOMPLETE, CLOSED}


class TradeIntervalTruthError(ValueError):
    """An interval cannot be opened from the supplied authoritative facts."""


def _parse_aware(value, *, name: str) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            stamp = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            raise TradeIntervalTruthError(f"{name}_unparseable") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise TradeIntervalTruthError(f"{name}_timezone_required")
    return stamp.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _finite_price(value, *, name: str) -> float:
    if isinstance(value, bool):
        raise TradeIntervalTruthError(f"{name}_invalid")
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        raise TradeIntervalTruthError(f"{name}_invalid") from None
    if not math.isfinite(price):
        raise TradeIntervalTruthError(f"{name}_invalid")
    return price


class TradeIntervalTruth:
    """One-contract durable interval store fed by unique canonical GatewayTrade events."""

    def __init__(self, contract_id: str, path: str, *, clock=None) -> None:
        self.contract_id = str(contract_id or "").strip()
        if not self.contract_id:
            raise TradeIntervalTruthError("contract_id_required")
        self.path = os.path.abspath(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._intervals: dict[str, dict] = {}
        self._epochs: dict[str, dict] = {}
        # Receipt-time watermark is intentionally process-local. A restart
        # invalidates every active epoch, so it never needs to be reconstructed
        # from minute candles or persisted as market-history authority.
        self._epoch_last_received_at: dict[str, datetime] = {}
        self._current_epoch_id: str | None = None
        self._storage_healthy = True
        self._storage_error: str | None = None
        self._load()

    @property
    def storage_health(self) -> dict:
        with self._lock:
            return {"healthy": self._storage_healthy,
                    "error": self._storage_error,
                    "path": self.path}

    @property
    def current_epoch_id(self) -> str | None:
        with self._lock:
            return self._current_epoch_id

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                blob = json.load(fh)
            if not isinstance(blob, dict) or blob.get("schema") != SCHEMA:
                raise ValueError("schema_mismatch")
            if str(blob.get("contract_id") or "") != self.contract_id:
                raise ValueError("contract_mismatch")
            intervals = blob.get("intervals")
            epochs = blob.get("coverage_epochs", {})
            if not isinstance(intervals, dict) or not isinstance(epochs, dict):
                raise ValueError("state_shape_invalid")
            for epoch_id, epoch in epochs.items():
                if (not isinstance(epoch, dict)
                        or epoch.get("coverage_epoch_id") != epoch_id
                        or epoch.get("contract_id") != self.contract_id
                        or epoch.get("status") not in {"ACTIVE", INCOMPLETE}):
                    raise ValueError("coverage_epoch_invalid")
                _parse_aware(epoch.get("started_at"), name="epoch_started_at")
                if epoch.get("ended_at") is not None:
                    _parse_aware(epoch["ended_at"], name="epoch_ended_at")
            for interval_id, record in intervals.items():
                if (not isinstance(record, dict)
                        or record.get("interval_id") != interval_id
                        or record.get("contract_id") != self.contract_id
                        or record.get("coverage_status") not in _STATUSES
                        or record.get("coverage_epoch_id") not in epochs):
                    raise ValueError("interval_record_invalid")
                if (record.get("coverage_status") == COMPLETE
                        and epochs[record["coverage_epoch_id"]].get("status") != "ACTIVE"):
                    raise ValueError("complete_interval_epoch_not_active")
                if (record.get("coverage_status") == INCOMPLETE
                        and not str(record.get("incomplete_reason") or "").strip()):
                    raise ValueError("incomplete_interval_reason_missing")
                _parse_aware(record.get("anchor_at"), name="anchor_at")
                if record.get("requested_at") is not None:
                    _parse_aware(record["requested_at"], name="requested_at")
                _parse_aware(record.get("created_at"), name="created_at")
                _parse_aware(record.get("updated_at"), name="updated_at")
                _finite_price(record.get("anchor_reference_price"),
                              name="anchor_reference_price")
                if not str(record.get("anchor_reference_basis") or "").strip():
                    raise ValueError("anchor_reference_basis_missing")
                if isinstance(record.get("trade_count"), bool) or not isinstance(
                        record.get("trade_count"), int) or record["trade_count"] < 0:
                    raise ValueError("trade_count_invalid")
                for price_key, time_key in (("highest_trade_price", "highest_trade_at"),
                                            ("lowest_trade_price", "lowest_trade_at")):
                    price, stamp = record.get(price_key), record.get(time_key)
                    if (price is None) != (stamp is None):
                        raise ValueError(f"{price_key}_pair_invalid")
                    if price is not None:
                        _finite_price(price, name=price_key)
                        extreme_at = _parse_aware(stamp, name=time_key)
                        if extreme_at < _parse_aware(record["anchor_at"], name="anchor_at"):
                            raise ValueError(f"{time_key}_precedes_anchor")
                for key in ("first_observed_trade_at", "last_observed_trade_at",
                            "first_received_at", "last_received_at", "incomplete_at",
                            "closed_at"):
                    if record.get(key) is not None:
                        _parse_aware(record[key], name=key)
                if not isinstance(record.get("coverage_transitions"), list):
                    raise ValueError("coverage_transitions_invalid")
                for transition in record["coverage_transitions"]:
                    if not isinstance(transition, dict):
                        raise ValueError("coverage_transition_invalid")
                    _parse_aware(transition.get("at"), name="transition_at")
            self._intervals = {str(k): copy.deepcopy(v)
                               for k, v in intervals.items()}
            self._epochs = {str(k): copy.deepcopy(v)
                            for k, v in epochs.items() if isinstance(v, dict)}
        except Exception as exc:  # noqa: BLE001 — unreadable authority stays unavailable
            self._storage_healthy = False
            self._storage_error = f"state_unreadable:{type(exc).__name__}:{exc}"
            return

        # A process boundary breaks raw trade continuity. Candle backfill cannot
        # heal an exact-time trade interval, so every persisted live epoch and
        # COMPLETE interval is sealed as incomplete before a new epoch can open.
        now = self._now()
        changed = False
        for epoch in self._epochs.values():
            if epoch.get("status") == "ACTIVE":
                epoch.update(status=INCOMPLETE,
                             incomplete_reason="process_restart_without_exact_trade_backfill",
                             ended_at=_iso(now))
                changed = True
        for record in self._intervals.values():
            if record.get("coverage_status") == COMPLETE:
                self._mark_incomplete_locked(
                    record, "process_restart_without_exact_trade_backfill", now)
                changed = True
        if changed:
            self._persist_locked()

    def _now(self) -> datetime:
        return _parse_aware(self._clock(), name="clock")

    def _document(self) -> dict:
        return {"schema": SCHEMA,
                "contract_id": self.contract_id,
                "coverage_epochs": self._epochs,
                "intervals": self._intervals}

    def _persist_locked(self) -> bool:
        if not self._storage_healthy:
            return False
        parent = os.path.dirname(self.path) or "."
        tmp = None
        try:
            os.makedirs(parent, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".trade-interval-", dir=parent)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._document(), fh, sort_keys=True, separators=(",", ":"),
                          allow_nan=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            return True
        except Exception as exc:  # noqa: BLE001 — never claim durable truth on write failure
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            self._storage_healthy = False
            self._storage_error = f"state_write_failed:{type(exc).__name__}:{exc}"
            now = self._now()
            for record in self._intervals.values():
                if record.get("coverage_status") == COMPLETE:
                    self._mark_incomplete_locked(record, "persistence_write_failed", now)
            return False

    def _mark_incomplete_locked(self, record: dict, reason: str,
                                at: datetime) -> bool:
        if record.get("coverage_status") != COMPLETE:
            return False
        record.update(coverage_status=INCOMPLETE,
                      incomplete_reason=str(reason), incomplete_at=_iso(at),
                      updated_at=_iso(at))
        record.setdefault("coverage_transitions", []).append({
            "status": INCOMPLETE, "at": _iso(at), "reason": str(reason)})
        return True

    def begin_coverage_epoch(self, contract_id: str, epoch_id: str, at) -> dict:
        stamp = _parse_aware(at, name="epoch_at")
        contract = str(contract_id or "").strip()
        epoch = str(epoch_id or "").strip()
        if contract != self.contract_id or not epoch:
            raise TradeIntervalTruthError("coverage_epoch_identity_mismatch")
        with self._lock:
            if not self._storage_healthy:
                raise TradeIntervalTruthError("interval_storage_unavailable")
            if self._current_epoch_id == epoch:
                return copy.deepcopy(self._epochs[epoch])
            if epoch in self._epochs:
                raise TradeIntervalTruthError("coverage_epoch_id_reused")
            prior = self._current_epoch_id
            if prior is not None:
                self._break_epoch_locked("coverage_epoch_changed", stamp, prior)
            self._epochs[epoch] = {"coverage_epoch_id": epoch,
                                   "contract_id": contract,
                                   "started_at": _iso(stamp),
                                   "ended_at": None,
                                   "status": "ACTIVE",
                                   "incomplete_reason": None}
            self._current_epoch_id = epoch
            self._persist_locked()
            return copy.deepcopy(self._epochs[epoch])

    def _break_epoch_locked(self, reason: str, stamp: datetime,
                            epoch_id: str | None = None) -> bool:
        target = str(epoch_id or self._current_epoch_id or "")
        changed = False
        epoch = self._epochs.get(target) if target else None
        if epoch and epoch.get("status") == "ACTIVE":
            epoch.update(status=INCOMPLETE, ended_at=_iso(stamp),
                         incomplete_reason=str(reason))
            changed = True
        for record in self._intervals.values():
            if record.get("coverage_epoch_id") == target:
                changed = self._mark_incomplete_locked(record, reason, stamp) or changed
        if target and target == self._current_epoch_id:
            self._current_epoch_id = None
        return changed

    def mark_coverage_broken(self, reason: str, at=None,
                             *, epoch_id: str | None = None) -> None:
        stamp = _parse_aware(at if at is not None else self._now(), name="break_at")
        detail = str(reason or "coverage_unproven")
        with self._lock:
            changed = self._break_epoch_locked(detail, stamp, epoch_id)
            if changed:
                self._persist_locked()

    def open_interval(self, contract_id: str, requested_at,
                      anchor_reference_price, anchor_reference_basis: str) -> dict:
        """Open at registration time; ``requested_at`` is audit metadata only.

        An interval cannot be backdated because the tracker deliberately does
        not retain raw trades. The authoritative anchor is captured while the
        tracker lock is held, after all earlier observations have completed.
        """
        requested = (_parse_aware(requested_at, name="requested_at")
                     if requested_at is not None else None)
        reference = _finite_price(anchor_reference_price,
                                  name="anchor_reference_price")
        basis = str(anchor_reference_basis or "").strip()
        contract = str(contract_id or "").strip()
        if contract != self.contract_id:
            raise TradeIntervalTruthError("contract_mismatch")
        if not basis:
            raise TradeIntervalTruthError("anchor_reference_basis_required")
        with self._lock:
            if not self._storage_healthy:
                raise TradeIntervalTruthError("interval_storage_unavailable")
            # Capture the actual anchor only once registration owns the state
            # lock. A caller's older Brain/request timestamp is never coverage.
            now = self._now()
            if requested is not None and requested > now:
                raise TradeIntervalTruthError("requested_at_in_future")
            epoch_id = self._current_epoch_id
            epoch = self._epochs.get(epoch_id or "")
            if not epoch or epoch.get("status") != "ACTIVE":
                raise TradeIntervalTruthError("live_coverage_epoch_unavailable")
            if now < _parse_aware(epoch["started_at"], name="epoch_start"):
                raise TradeIntervalTruthError("anchor_precedes_coverage_epoch")
            last_received = self._epoch_last_received_at.get(epoch_id)
            if last_received is not None and now <= last_received:
                raise TradeIntervalTruthError("anchor_not_after_last_observed_event")
            interval_id = uuid.uuid4().hex
            record = {
                "interval_id": interval_id,
                "contract_id": self.contract_id,
                "anchor_at": _iso(now),
                "requested_at": _iso(requested) if requested is not None else None,
                "anchor_reference_price": reference,
                "anchor_reference_basis": basis,
                "coverage_epoch_id": epoch_id,
                "first_observed_trade_at": None,
                "last_observed_trade_at": None,
                "first_received_at": None,
                "last_received_at": None,
                "highest_trade_price": None,
                "highest_trade_at": None,
                "lowest_trade_price": None,
                "lowest_trade_at": None,
                "trade_count": 0,
                "coverage_status": COMPLETE,
                "incomplete_reason": None,
                "incomplete_at": None,
                "created_at": _iso(now),
                "updated_at": _iso(now),
                "coverage_transitions": [{"status": COMPLETE, "at": _iso(now),
                                           "reason": "opened_in_live_epoch"}],
            }
            self._intervals[interval_id] = record
            self._persist_locked()
            if not self._storage_healthy:
                raise TradeIntervalTruthError("interval_persistence_failed")
            return copy.deepcopy(record)

    @staticmethod
    def _contract_fields(row: dict):
        ids = [str(row.get(key)).strip() for key in ("contractId", "contract")
               if row.get(key) is not None and str(row.get(key)).strip()]
        if len(set(ids)) > 1:
            return None, "trade_contract_conflict"
        return (ids[0] if ids else None), None

    def observe_gateway_event(self, args, *, epoch_id: str,
                              received_at=None,
                              batch_identity_proven: bool = True) -> None:
        """Observe one unique GatewayTrade batch, preserving event-time semantics.

        Authenticated late trades from the same uninterrupted epoch are accepted
        for extrema even if their candle minute was already closed. Batch
        de-duplication is owned by MinuteCandleAggregator and this callback is
        invoked only for a batch it accepted as new.
        """
        received = _parse_aware(received_at if received_at is not None else self._now(),
                                name="received_at")
        with self._lock:
            if (not self._storage_healthy
                    or epoch_id != self._current_epoch_id):
                return
            if not batch_identity_proven:
                self._break_epoch_locked("trade_batch_identity_unproven", received,
                                         epoch_id)
                self._persist_locked()
                return
            if not isinstance(args, (list, tuple)) or len(args) < 2:
                self._break_epoch_locked("malformed_gateway_trade_event", received,
                                         epoch_id)
                self._persist_locked()
                return

            envelope = str(args[0]).strip() if args[0] is not None else ""
            if envelope and envelope != self.contract_id:
                # The event envelope affirmatively identifies another contract.
                return
            payload = args[1]
            rows = payload if isinstance(payload, list) else [payload]
            if not rows:
                return

            updates = []
            malformed_reason = None
            for row in rows:
                if not isinstance(row, dict):
                    malformed_reason = "malformed_trade_row"
                    break
                row_contract, contract_error = self._contract_fields(row)
                if contract_error:
                    malformed_reason = contract_error
                    break
                trade_contract = row_contract or envelope
                if not trade_contract:
                    malformed_reason = "trade_contract_unavailable"
                    break
                if trade_contract != self.contract_id:
                    if envelope == self.contract_id:
                        malformed_reason = "trade_contract_conflicts_with_event"
                        break
                    continue
                try:
                    event_at = _parse_aware(row.get("timestamp"),
                                            name="trade_timestamp")
                    price = _finite_price(row.get("price"), name="trade_price")
                except TradeIntervalTruthError as exc:
                    malformed_reason = str(exc)
                    break
                updates.append((event_at, price))

            if malformed_reason:
                self._break_epoch_locked(malformed_reason, received, epoch_id)
                self._persist_locked()
                return

            # A later interval anchor must be newer than every event already
            # consumed by this epoch, even when no interval was open yet.
            if updates:
                previous_received = self._epoch_last_received_at.get(epoch_id)
                if previous_received is None or received > previous_received:
                    self._epoch_last_received_at[epoch_id] = received

            changed = False
            for event_at, price in updates:
                event_iso = _iso(event_at)
                for record in self._intervals.values():
                    if (record.get("coverage_status") != COMPLETE
                            or record.get("coverage_epoch_id") != epoch_id
                            or event_at < _parse_aware(record["anchor_at"], name="anchor_at")):
                        continue
                    if record["first_observed_trade_at"] is None or event_at < _parse_aware(
                            record["first_observed_trade_at"], name="first_observed_trade_at"):
                        record["first_observed_trade_at"] = event_iso
                    if record["last_observed_trade_at"] is None or event_at > _parse_aware(
                            record["last_observed_trade_at"], name="last_observed_trade_at"):
                        record["last_observed_trade_at"] = event_iso
                    if record["first_received_at"] is None:
                        record["first_received_at"] = _iso(received)
                    record["last_received_at"] = _iso(received)
                    record["trade_count"] += 1
                    high = record["highest_trade_price"]
                    if high is None or price > high or (
                            price == high and event_at < _parse_aware(
                                record["highest_trade_at"], name="highest_trade_at")):
                        record["highest_trade_price"] = price
                        record["highest_trade_at"] = event_iso
                    low = record["lowest_trade_price"]
                    if low is None or price < low or (
                            price == low and event_at < _parse_aware(
                                record["lowest_trade_at"], name="lowest_trade_at")):
                        record["lowest_trade_price"] = price
                        record["lowest_trade_at"] = event_iso
                    record["updated_at"] = _iso(received)
                    changed = True
            if changed:
                self._persist_locked()

    def close_interval(self, interval_id: str, reason: str, at=None) -> dict:
        stamp = _parse_aware(at if at is not None else self._now(), name="closed_at")
        with self._lock:
            record = self._intervals.get(str(interval_id))
            if record is None:
                raise TradeIntervalTruthError("interval_not_found")
            if record.get("coverage_status") != CLOSED:
                record["coverage_status_at_close"] = record.get("coverage_status")
                record.update(coverage_status=CLOSED, closed_at=_iso(stamp),
                              close_reason=str(reason or "closed"),
                              updated_at=_iso(stamp))
                record.setdefault("coverage_transitions", []).append({
                    "status": CLOSED, "at": _iso(stamp),
                    "reason": str(reason or "closed")})
                self._persist_locked()
            return copy.deepcopy(record)

    def get_interval(self, interval_id: str) -> dict | None:
        with self._lock:
            record = self._intervals.get(str(interval_id))
            return copy.deepcopy(record) if record else None

    def active_intervals(self, contract_id: str | None = None) -> list:
        contract = str(contract_id or self.contract_id)
        if contract != self.contract_id:
            return []
        with self._lock:
            return [copy.deepcopy(record) for record in self._intervals.values()
                    if record.get("coverage_status") != CLOSED]
