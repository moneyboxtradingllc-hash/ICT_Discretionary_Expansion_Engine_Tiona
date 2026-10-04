"""Durable extrema and coverage facts from the canonical raw trade stream.

This module records only exact timestamped trade extrema and the provenance
needed to say whether those extrema cover an uninterrupted live interval. It
does not retain raw trades and has no strategy or execution authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone


SCHEMA = "trade_interval_truth.v2"
_LEGACY_SCHEMA = "trade_interval_truth.v1"
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
        # Digests are deliberately retained for the complete live epoch. A
        # bounded eviction window cannot distinguish a late replay from a new
        # equal-timestamp event around an interval frontier.
        self._seen_batch_digests: dict[str, set[str]] = {}
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

    @staticmethod
    def _audit_interval_view(record: dict) -> dict:
        view = copy.deepcopy(record)
        view["authority_scope"] = "AUDIT_ONLY"
        view["last_recorded_coverage_status"] = view.pop("coverage_status", None)
        return view

    @staticmethod
    def _audit_epoch_view(epoch: dict) -> dict:
        view = copy.deepcopy(epoch)
        view["authority_scope"] = "AUDIT_ONLY"
        view["last_recorded_epoch_status"] = view.pop("status", None)
        view["last_recorded_trade_coverage_status"] = view.pop(
            "trade_coverage_status", None)
        return view

    def audit_coverage_epoch(self, epoch_id: str | None = None) -> dict | None:
        """Return stored epoch history explicitly scoped as audit data."""
        with self._lock:
            target = str(epoch_id or self._current_epoch_id or "")
            epoch = self._epochs.get(target)
            return self._audit_epoch_view(epoch) if epoch else None

    def _provider_current_coverage_evidence(self, epoch_id: str) -> dict | None:
        """Internal evidence accessor; provider must validate runtime and freshness."""
        with self._lock:
            epoch = self._epochs.get(str(epoch_id))
            if (not self._storage_healthy or str(epoch_id) != self._current_epoch_id
                    or not epoch or epoch.get("status") != "ACTIVE"
                    or epoch.get("trade_coverage_status") != "PROVEN"):
                return None
            return copy.deepcopy(epoch)

    def _provider_current_interval_record(self, interval_id: str, *, epoch_id: str) -> dict | None:
        """Private stored row for the provider after its live checks succeed."""
        with self._lock:
            if not self._storage_healthy or str(epoch_id) != self._current_epoch_id:
                return None
            epoch = self._epochs.get(str(epoch_id))
            record = self._intervals.get(str(interval_id))
            if (not epoch or epoch.get("status") != "ACTIVE"
                    or epoch.get("trade_coverage_status") != "PROVEN"
                    or not record or record.get("coverage_status") != COMPLETE
                    or record.get("coverage_epoch_id") != str(epoch_id)):
                return None
            return copy.deepcopy(record)

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                blob = json.load(fh)
            if (not isinstance(blob, dict)
                    or blob.get("schema") not in {SCHEMA, _LEGACY_SCHEMA}):
                raise ValueError("schema_mismatch")
            legacy = blob.get("schema") == _LEGACY_SCHEMA
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
                        or epoch.get("status") not in {"PENDING", "ACTIVE", INCOMPLETE}):
                    raise ValueError("coverage_epoch_invalid")
                if not legacy:
                    if epoch.get("trade_coverage_status") not in {"PENDING", "PROVEN", INCOMPLETE}:
                        raise ValueError("trade_coverage_status_invalid")
                    if (epoch.get("status") == "ACTIVE"
                            and epoch.get("trade_coverage_status") != "PROVEN"):
                        raise ValueError("active_epoch_without_proven_trade_coverage")
                    if (epoch.get("status") == "PENDING"
                            and epoch.get("trade_coverage_status") != "PENDING"):
                        raise ValueError("pending_epoch_trade_status_mismatch")
                    for key in ("frontier_observation_sequence", "last_observation_sequence"):
                        value = epoch.get(key)
                        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                            raise ValueError(f"{key}_invalid")
                    if epoch.get("event_time_frontier") is not None:
                        _parse_aware(epoch["event_time_frontier"], name="event_time_frontier")
                    if (epoch.get("status") == "ACTIVE"
                            and (epoch.get("event_time_frontier") is None
                                 or epoch.get("frontier_observation_sequence", 0) < 1
                                 or epoch.get("last_observation_sequence", 0)
                                 < epoch.get("frontier_observation_sequence", 0))):
                        raise ValueError("active_epoch_frontier_invalid")
                    if (epoch.get("status") == "PENDING"
                            and (epoch.get("event_time_frontier") is not None
                                 or epoch.get("last_observation_sequence", 0) != 0)):
                        raise ValueError("pending_epoch_has_trade_frontier")
                    if epoch.get("last_valid_trade_received_at") is not None:
                        _parse_aware(epoch["last_valid_trade_received_at"],
                                     name="last_valid_trade_received_at")
                    if epoch.get("first_valid_trade_received_at") is not None:
                        _parse_aware(epoch["first_valid_trade_received_at"],
                                     name="first_valid_trade_received_at")
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
                        and (epochs[record["coverage_epoch_id"]].get("status") != "ACTIVE"
                             or (not legacy and epochs[record["coverage_epoch_id"]].get(
                                 "trade_coverage_status") != "PROVEN"))):
                    raise ValueError("complete_interval_epoch_not_active")
                if (record.get("coverage_status") == INCOMPLETE
                        and not str(record.get("incomplete_reason") or "").strip()):
                    raise ValueError("incomplete_interval_reason_missing")
                _parse_aware(record.get("anchor_at"), name="anchor_at")
                if not legacy and (isinstance(record.get("anchor_observation_sequence"), bool)
                                   or not isinstance(record.get("anchor_observation_sequence"), int)
                                   or record["anchor_observation_sequence"] < 0):
                    raise ValueError("anchor_observation_sequence_invalid")
                if record.get("requested_at") is not None:
                    _parse_aware(record["requested_at"], name="requested_at")
                if record.get("registered_at") is not None:
                    _parse_aware(record["registered_at"], name="registered_at")
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
        if legacy:
            # v1 anchors mixed local registration time with venue event time.
            # Preserve those records for audit, but never carry their COMPLETE
            # claim into the event-frontier contract.
            for epoch in self._epochs.values():
                epoch.update(status=INCOMPLETE, trade_coverage_status=INCOMPLETE,
                             incomplete_reason="legacy_event_frontier_unavailable",
                             ended_at=epoch.get("ended_at") or _iso(now),
                             event_time_frontier=None,
                             frontier_observation_sequence=0,
                             last_observation_sequence=0,
                             last_valid_trade_received_at=None)
                changed = True
            for record in self._intervals.values():
                record.setdefault("anchor_observation_sequence", 0)
                record.setdefault("registered_at", record.get("created_at") or _iso(now))
                if record.get("coverage_status") == COMPLETE:
                    self._mark_incomplete_locked(
                        record, "legacy_event_frontier_unavailable", now)
                    changed = True
        for epoch in self._epochs.values():
            if epoch.get("status") in {"PENDING", "ACTIVE"}:
                epoch.update(status=INCOMPLETE,
                             trade_coverage_status=INCOMPLETE,
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
        # Raw event identities are intentionally process local. _load has
        # already invalidated every old epoch, so a restart never inherits a
        # dedup/frontier claim as live continuity.
        self._seen_batch_digests.clear()

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
                return self._audit_epoch_view(self._epochs[epoch])
            if epoch in self._epochs:
                raise TradeIntervalTruthError("coverage_epoch_id_reused")
            prior = self._current_epoch_id
            if prior is not None:
                self._break_epoch_locked("coverage_epoch_changed", stamp, prior)
            self._epochs[epoch] = {"coverage_epoch_id": epoch,
                                   "contract_id": contract,
                                   "started_at": _iso(stamp),
                                   "ended_at": None,
                                   "status": "PENDING",
                                   "trade_coverage_status": "PENDING",
                                   "incomplete_reason": None,
                                   "event_time_frontier": None,
                                   "frontier_observation_sequence": 0,
                                   "last_observation_sequence": 0,
                                   "last_valid_trade_received_at": None}
            self._current_epoch_id = epoch
            self._seen_batch_digests[epoch] = set()
            self._persist_locked()
            return self._audit_epoch_view(self._epochs[epoch])

    def _break_epoch_locked(self, reason: str, stamp: datetime,
                            epoch_id: str | None = None) -> bool:
        target = str(epoch_id or self._current_epoch_id or "")
        changed = False
        epoch = self._epochs.get(target) if target else None
        if epoch and epoch.get("status") in {"PENDING", "ACTIVE"}:
            epoch.update(status=INCOMPLETE, trade_coverage_status=INCOMPLETE,
                         ended_at=_iso(stamp),
                         incomplete_reason=str(reason))
            changed = True
        for record in self._intervals.values():
            if record.get("coverage_epoch_id") == target:
                changed = self._mark_incomplete_locked(record, reason, stamp) or changed
        if target and target == self._current_epoch_id:
            self._current_epoch_id = None
        self._seen_batch_digests.pop(target, None)
        return changed

    def mark_coverage_broken(self, reason: str, at=None,
                             *, epoch_id: str | None = None) -> None:
        stamp = _parse_aware(at if at is not None else self._now(), name="break_at")
        detail = str(reason or "coverage_unproven")
        with self._lock:
            changed = self._break_epoch_locked(detail, stamp, epoch_id)
            if changed:
                self._persist_locked()

    def _register_interval(self, contract_id: str, requested_at,
                           anchor_reference_price, anchor_reference_basis: str) -> dict:
        """Open against the observed market-event frontier.

        Request and registration timestamps are local lineage only. The
        authoritative anchor is the latest proven venue event-time frontier
        plus its provider observation sequence, captured while both provider
        dispatch and tracker state are serialized.
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
            # Local time is descriptive only; do not compare it with venue
            # event timestamps or let it define event membership.
            now = self._now()
            epoch_id = self._current_epoch_id
            epoch = self._epochs.get(epoch_id or "")
            if (not epoch or epoch.get("status") != "ACTIVE"
                    or epoch.get("trade_coverage_status") != "PROVEN"):
                raise TradeIntervalTruthError("live_coverage_epoch_unavailable")
            frontier = epoch.get("event_time_frontier")
            frontier_sequence = epoch.get("frontier_observation_sequence")
            if (frontier is None or isinstance(frontier_sequence, bool)
                    or not isinstance(frontier_sequence, int)):
                raise TradeIntervalTruthError("event_time_frontier_unavailable")
            anchor_at = _parse_aware(frontier, name="event_time_frontier")
            interval_id = uuid.uuid4().hex
            record = {
                "interval_id": interval_id,
                "contract_id": self.contract_id,
                "anchor_at": _iso(anchor_at),
                "anchor_observation_sequence": frontier_sequence,
                "requested_at": _iso(requested) if requested is not None else None,
                "registered_at": _iso(now),
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
                                           "reason": "opened_at_proven_event_frontier"}],
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

        Batch de-duplication is owned by MinuteCandleAggregator and this
        callback is invoked only for a batch it accepted as new. Event membership
        uses the composite (venue event timestamp, provider observation sequence)
        boundary. A later-delivered print strictly older than the anchor frontier
        is pre-anchor and excluded; equal-timestamp prints are ordered by their
        explicit dispatch sequence. No local receipt clock participates.
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

            try:
                batch_digest = hashlib.sha256(
                    json.dumps(args, sort_keys=True, default=str,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
            except Exception:  # noqa: BLE001 — identity uncertainty breaks coverage
                self._break_epoch_locked("trade_batch_identity_unproven", received,
                                         epoch_id)
                self._persist_locked()
                return
            seen = self._seen_batch_digests.setdefault(epoch_id, set())
            if batch_digest in seen:
                # Replay classification precedes every authority-bearing update.
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

            # Retain identity for the whole uninterrupted epoch. If the process
            # restarts, _load invalidates that epoch and starts with an empty set.
            seen.add(batch_digest)

            changed = False
            epoch = self._epochs[epoch_id]
            if updates:
                if epoch.get("trade_coverage_status") == "PENDING":
                    epoch.update(status="ACTIVE", trade_coverage_status="PROVEN",
                                 first_valid_trade_received_at=_iso(received))
                epoch["last_valid_trade_received_at"] = _iso(received)
                changed = True
            for event_at, price in updates:
                sequence = int(epoch.get("last_observation_sequence") or 0) + 1
                epoch["last_observation_sequence"] = sequence
                previous_frontier = epoch.get("event_time_frontier")
                previous_frontier_at = (_parse_aware(previous_frontier,
                                                      name="event_time_frontier")
                                        if previous_frontier else None)
                if previous_frontier_at is None or event_at >= previous_frontier_at:
                    epoch["event_time_frontier"] = _iso(event_at)
                    epoch["frontier_observation_sequence"] = sequence
                event_iso = _iso(event_at)
                for record in self._intervals.values():
                    if (record.get("coverage_status") != COMPLETE
                            or record.get("coverage_epoch_id") != epoch_id
                            or (event_at, sequence) <= (
                                _parse_aware(record["anchor_at"], name="anchor_at"),
                                int(record.get("anchor_observation_sequence") or 0))):
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
                    record["last_observation_sequence"] = sequence
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
            return self._audit_interval_view(record)

    def get_interval(self, interval_id: str) -> dict | None:
        """Return AUDIT_ONLY history, never a current-live authority record."""
        with self._lock:
            record = self._intervals.get(str(interval_id))
            return self._audit_interval_view(record) if record else None

    def active_intervals(self, contract_id: str | None = None) -> list:
        contract = str(contract_id or self.contract_id)
        if contract != self.contract_id:
            return []
        with self._lock:
            return [self._audit_interval_view(record) for record in self._intervals.values()
                    if record.get("coverage_status") != CLOSED]
