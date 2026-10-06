"""Process-owned custody for settled PO3 reversal formation evidence.

This module retains only a detector-produced factual object. It is not an
entry permission, a direction owner, or a transfer authority. Each object is
reconstructed in canonical-history replay and is checked against the current
history revision, its settled bar witnesses, its protected anchor life, and the
exact contract/session before it is exposed to the current scan.
"""
from __future__ import annotations

import copy
import hashlib
import json


_VIEW_SEAL = object()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def _num(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _instant(value):
    try:
        from market_data.object_identity import canonical_instant
        return canonical_instant(value, strict=True)
    except Exception:  # noqa: BLE001
        return None


def _bar_fact(bar):
    if not isinstance(bar, dict):
        return None
    stamp = _instant(bar.get("timestamp") or bar.get("time") or bar.get("t"))
    values = {key: _num(bar.get(key)) for key in
              ("open", "high", "low", "close", "volume")}
    if stamp is None or any(values[k] is None for k in
                            ("open", "high", "low", "close")):
        return None
    return {"timestamp": stamp, **values,
            "contract": str(bar.get("contract") or bar.get("contractId") or "")}


def _bar_digest(bar):
    fact = _bar_fact(bar)
    if fact is None:
        return None
    return hashlib.sha256(_json(fact).encode("utf-8")).hexdigest()


class ProducerOwnedFormationView(dict):
    """JSON-readable view that loses its live marker when restored from JSON."""

    def __init__(self, rows, *, scope, seal):
        if seal is not _VIEW_SEAL:
            raise ValueError("reversal formation view is producer-minted only")
        super().__init__(copy.deepcopy(rows))
        self._seal = seal
        self._scope = scope


def is_producer_owned_view(value) -> bool:
    return (isinstance(value, ProducerOwnedFormationView)
            and getattr(value, "_seal", None) is _VIEW_SEAL)


class ReversalFormationCustody:
    """Rebuildable, bounded custody for current-session PO3 formation facts."""

    def __init__(self):
        self._contract = None
        self._session = None
        self._revision = None
        self._records = {}
        self._sweeps = {}
        self._lives = {}

    @staticmethod
    def _session_key(timestamp):
        try:
            from market_state.active_path import production_session_key
            return production_session_key(timestamp)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _protected(snapshot, direction, timeframe, level):
        side = "lows" if direction == "bullish" else "highs"
        rows = (((snapshot.get("protected_swings") or {}).get("by_timeframe")
                 or {}).get(side) or {})
        rec = rows.get(timeframe) if isinstance(rows, dict) else None
        if not isinstance(rec, dict) or _num(rec.get("level")) != _num(level):
            return None
        if (rec.get("timeframe") not in (None, timeframe)
                or rec.get("role") not in ("context", "active_leg")
                or not rec.get("swing_id") or not rec.get("registered_at")):
            return None
        return rec

    def _capture(self, snapshot, direction, block, revision, contract, session,
                 canonical_timeframes):
        tf = block.get("source_tf")
        anchor_tf = block.get("protected_swing_tf") or tf
        bars = (((snapshot.get("timeframes") or {}).get(tf) or {})
                .get("recent_candles") or [])
        settled = {(_instant(b.get("timestamp") or b.get("time") or b.get("t"))): b
                   for b in bars if isinstance(b, dict)
                   and b.get("temporal_status") == "settled"}
        anchor = self._protected(snapshot, direction, anchor_tf,
                                 block.get("invalidation_level"))
        if anchor is None:
            return None
        times = [block.get("creating_run_start"), block.get("creating_run_end"),
                 block.get("validation_timestamp"),
                 (block.get("sweep_evidence") or {}).get("event_time")]
        witness_bars = {}
        for raw_stamp in times:
            stamp = _instant(raw_stamp)
            if stamp is None:
                return None
            bar = settled.get(stamp)
            if bar is None:
                # A multi-bar run is recorded completely below; this first
                # pass also ensures its endpoints and validating event exist.
                continue
            digest = _bar_digest(bar)
            if digest is None:
                return None
            witness_bars[stamp] = digest
        run_start, run_end = (_instant(block.get("creating_run_start")),
                              _instant(block.get("creating_run_end")))
        validation = _instant(block.get("validation_timestamp"))
        if (run_start is None or run_end is None or validation is None
                or validation < run_end):
            return None
        # Bind every settled candle in the actual run and the first violating
        # close. The sweep event is another independent witness in the same
        # canonical timeframe.
        for stamp, bar in settled.items():
            if run_start <= stamp <= run_end or stamp == validation:
                digest = _bar_digest(bar)
                if digest is None:
                    return None
                witness_bars[stamp] = digest
        sweep_stamp = _instant((block.get("sweep_evidence") or {}).get("event_time"))
        if sweep_stamp is None or sweep_stamp not in settled:
            return None
        witness_bars[sweep_stamp] = _bar_digest(settled[sweep_stamp])
        if not all(stamp in witness_bars for stamp in
                   (run_start, run_end, validation, sweep_stamp)):
            return None
        sweep = block.get("sweep_evidence") or {}
        anchor_identity = {
            "contract_id": contract,
            "direction": direction,
            "side": "low" if direction == "bullish" else "high",
            "timeframe": anchor_tf,
            "swing_id": anchor.get("swing_id"),
            "registered_at": anchor.get("registered_at"),
            "level": _num(anchor.get("level")),
            "basis": anchor.get("basis"),
        }
        source_occurrence = sweep.get("occurrence_id")
        if not source_occurrence:
            try:
                from market_data.sweep_occurrence import liquidity_sweep_occurrence
                source_occurrence = (liquidity_sweep_occurrence(
                    sweep, source_tf=tf, contract=contract) or {}).get("occurrence_id")
            except Exception:  # noqa: BLE001
                source_occurrence = None
        if not source_occurrence:
            return None
        try:
            from market_data.object_identity import market_object_id
            occurrence = market_object_id(
                "PO3_REVERSAL_ORDER_BLOCK", contract=contract, timeframe=tf,
                instant=validation,
                discriminators=(direction, source_occurrence,
                                anchor_identity["swing_id"],
                                anchor_identity["registered_at"]))
        except Exception:  # noqa: BLE001
            return None
        return {
            "schema_version": 1,
            "occurrence_id": occurrence,
            "contract_id": contract,
            "market_session": session,
            "history_revision": revision,
            "direction": direction,
            "source_tf": tf,
            "anchor_identity": anchor_identity,
            "sweep_evidence": copy.deepcopy(sweep),
            "anchor_registration_occurrence_id": block.get(
                "protected_swing_occurrence_id"),
            "run_start": run_start,
            "run_end": run_end,
            "validation_timestamp": validation,
            "witness_bars": witness_bars,
            "block": copy.deepcopy(block),
        }

    @staticmethod
    def _history_index(canonical_timeframes, timeframe):
        raw = (canonical_timeframes or {}).get(timeframe) or []
        try:
            from market_data.candle_normalizer import normalize_candles
            rows = normalize_candles(raw)
        except Exception:  # noqa: BLE001
            rows = raw
        return {_instant((row or {}).get("timestamp") or (row or {}).get("time")
                         or (row or {}).get("t")): row
                for row in rows if isinstance(row, dict)
                and _instant(row.get("timestamp") or row.get("time") or row.get("t"))}

    def _still_current(self, snapshot, record, revision, contract, session,
                       canonical_timeframes):
        from market_state.active_path import (PROTECTED_SWING_REPLACED,
                                              PROTECTED_SWING_VIOLATED)
        if (record.get("contract_id") != contract
                or record.get("market_session") != session
                or record.get("history_revision") != revision):
            return False
        anchor = record.get("anchor_identity") or {}
        direction, tf = record.get("direction"), record.get("source_tf")
        anchor_tf = anchor.get("timeframe")
        live = self._protected(snapshot, direction, anchor_tf, anchor.get("level"))
        if (live is None or live.get("swing_id") != anchor.get("swing_id")
                or live.get("registered_at") != anchor.get("registered_at")
                or live.get("basis") != anchor.get("basis")):
            return False
        current_sweeps = (snapshot or {}).get("reversal_sweep_history")
        current_lives = (snapshot or {}).get("protected_swing_lifetime_history")
        sweep = record.get("sweep_evidence") or {}
        if not isinstance(current_sweeps, list) or not any(
                isinstance(row, dict)
                and row.get("occurrence_id") == sweep.get("occurrence_id")
                and row.get("contract") == contract
                and row.get("event_time") == sweep.get("event_time")
                and row.get("swept_level") == sweep.get("swept_level")
                for row in current_sweeps):
            return False
        registration_id = record.get("anchor_registration_occurrence_id")
        if (not isinstance(current_lives, list) or not registration_id
                or not any(isinstance(row, dict)
                           and row.get("occurrence_id") == registration_id
                           and row.get("contract") == contract
                           and row.get("source_tf") == anchor_tf
                           and row.get("swing_id") == anchor.get("swing_id")
                           and row.get("registered_at") == anchor.get("registered_at")
                           and row.get("level") == anchor.get("level")
                           for row in current_lives)):
            return False
        # A retained object depends on the exact anchor life remaining intact.
        # Do not trust a stale registry row if canonical ActivePath chronology
        # already records that same registration as violated or replaced.
        current_at = _instant((snapshot or {}).get("timestamp"))
        if current_at is None:
            return False
        for row in current_lives:
            if (not isinstance(row, dict)
                    or row.get("contract") != contract
                    or row.get("source_tf") != anchor_tf):
                continue
            event_type = row.get("event_type")
            same_life = (
                event_type == PROTECTED_SWING_VIOLATED
                and row.get("side") == anchor.get("side")
                and row.get("swing_id") == anchor.get("swing_id")
                and row.get("registered_at") == anchor.get("registered_at")
                and row.get("level") == anchor.get("level"))
            replaced_life = (
                event_type == PROTECTED_SWING_REPLACED
                and row.get("side") == anchor.get("side")
                and row.get("old_swing_id") == anchor.get("swing_id")
                and row.get("old_registered_at") == anchor.get("registered_at")
                and row.get("old_level") == anchor.get("level"))
            if not (same_life or replaced_life):
                continue
            event_at = _instant(row.get("source_bar_time"))
            # A matching but unorderable lifecycle event is contradictory
            # authority. A future row is outside this scan's causal view.
            if event_at is None or event_at <= current_at:
                return False
        current = self._history_index(canonical_timeframes, tf)
        if not current:
            return False
        ordered = sorted(current)
        earliest, latest = ordered[0], ordered[-1]
        for stamp, expected in (record.get("witness_bars") or {}).items():
            row = current.get(stamp)
            if row is None:
                # Finite history naturally sheds old leading bars. A missing
                # witness inside current coverage is a deletion; a witness
                # before coverage is ordinary rollout, and HistoryRevision
                # remains the authority for corrections to that old prefix.
                if stamp >= earliest and stamp <= latest:
                    return False
                if stamp > latest:
                    return False
                continue
            if _bar_digest(row) != expected:
                return False
        return True

    @staticmethod
    def _merge_rows(target, rows):
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict) or not row.get("occurrence_id"):
                continue
            target[str(row["occurrence_id"])] = copy.deepcopy(row)

    def _observe_current_sweep(self, snapshot, contract):
        from market_data.sweep_occurrence import liquidity_sweep_occurrence
        for tf, facts in ((snapshot or {}).get("liquidity") or {}).items():
            if not isinstance(facts, dict):
                continue
            fact = facts.get("sweep_fact")
            if not isinstance(fact, dict):
                continue
            row = liquidity_sweep_occurrence(
                fact, source_tf=tf, contract=contract, snapshot=snapshot)
            if row:
                self._sweeps[row["occurrence_id"]] = row

    def observe(self, snapshot, *, contract_id, history_revision,
                canonical_timeframes, sweep_events=None, lifetime_events=None,
                rebuilding=False):
        """Capture current formation, then expose only revalidated records."""
        from toolbox.price_levels import _detect_current_po3_reversal_order_block

        snap = snapshot if isinstance(snapshot, dict) else {}
        contract = str(contract_id or "").strip()
        revision = history_revision
        session = self._session_key(snap.get("timestamp"))
        if (not contract or not session or isinstance(revision, bool)
                or not isinstance(revision, int)):
            self._records.clear()
            return ProducerOwnedFormationView({}, scope=None, seal=_VIEW_SEAL)
        if (self._contract != contract or self._session != session
                or self._revision != revision):
            self._records.clear()
            self._sweeps.clear()
            self._lives.clear()
            self._contract, self._session, self._revision = contract, session, revision

        # Normal production scans must rebind event support to the current
        # authoritative occurrence-store view. Retained process memory is not
        # allowed to fill a hole in that view. During canonical rebuild only,
        # the extractor emits one prefix's lifetime events at a time, so those
        # events are accumulated as the prefix replay advances.
        if (not rebuilding
                and (not isinstance(sweep_events, list)
                     or not isinstance(lifetime_events, list))):
            self._records.clear()
            self._sweeps.clear()
            self._lives.clear()
            return ProducerOwnedFormationView({}, scope=None, seal=_VIEW_SEAL)
        if not rebuilding:
            self._sweeps.clear()
            self._lives.clear()

        # Only production-owned event rows for this exact contract/session are
        # retained. JSON audit material is never an input to this object.
        self._merge_rows(self._sweeps, sweep_events)
        self._merge_rows(self._lives, lifetime_events)
        self._observe_current_sweep(snap, contract)
        snap["reversal_sweep_history"] = [
            copy.deepcopy(row) for row in self._sweeps.values()
            if row.get("contract") == contract
            and self._session_key(row.get("event_time")) == session]
        snap["protected_swing_lifetime_history"] = [
            copy.deepcopy(row) for row in self._lives.values()
            if row.get("contract") == contract
            and self._session_key(row.get("event_time")) == session]

        for direction in ("bullish", "bearish"):
            block = _detect_current_po3_reversal_order_block(snap, direction)
            if not block.get("available"):
                continue
            record = self._capture(snap, direction, block, revision, contract,
                                   session, canonical_timeframes)
            if record is None:
                continue
            key = (direction, record["source_tf"])
            prior = self._records.get(key)
            if (prior is None or record["validation_timestamp"]
                    >= prior.get("validation_timestamp", "")):
                self._records[key] = record

        current_records = {}
        for key, record in list(self._records.items()):
            if self._still_current(snap, record, revision, contract, session,
                                   canonical_timeframes):
                current_records[key] = record
            else:
                del self._records[key]

        # Keep the source-timeframe selection law in price_levels: this view
        # exposes verified facts by direction/timeframe and never ranks them.
        rows = {}
        for direction in ("bullish", "bearish"):
            rows[direction] = {tf: copy.deepcopy(record)
                               for (d, tf), record in current_records.items()
                               if d == direction}
        scope = {"contract_id": contract, "market_session": session,
                 "history_revision": revision,
                 "rebuilding": bool(rebuilding)}
        return ProducerOwnedFormationView(rows, scope=scope, seal=_VIEW_SEAL)


def current_block(snapshot, direction):
    """Return only a current-process formation that survived revalidation."""
    view = (snapshot or {}).get("reversal_formation_view")
    if not is_producer_owned_view(view):
        return None
    scope = getattr(view, "_scope", None)
    derived = (snapshot or {}).get("derived_state") or {}
    contract = str((snapshot or {}).get("contract_id") or "").strip()
    session = ReversalFormationCustody._session_key(
        (snapshot or {}).get("timestamp"))
    if (not isinstance(scope, dict) or scope.get("contract_id") != contract
            or scope.get("market_session") != session
            or scope.get("history_revision") != derived.get("history_revision")
            or derived.get("current") is not True
            or derived.get("derived_revision") != derived.get("history_revision")):
        return None
    rows = view.get(direction) if direction in ("bullish", "bearish") else None
    if not isinstance(rows, dict):
        return None
    # Preserve the existing source-timeframe priority. This layer validates
    # authority; it does not rank or choose among market objects.
    try:
        from toolbox.price_levels import _allowed_source_tfs
        priority = _allowed_source_tfs((snapshot or {}).get("symbol", ""))
    except Exception:  # noqa: BLE001
        priority = ("15m", "5m", "3m", "1m")
    valid = None
    for timeframe in priority:
        record = rows.get(timeframe)
        if (isinstance(record, dict)
                and record.get("contract_id") == contract
                and record.get("market_session") == session
                and record.get("history_revision") == derived.get("history_revision")):
            valid = record
            break
    if valid is None:
        return None
    current_at = _instant((snapshot or {}).get("timestamp"))
    validation_at = _instant(valid.get("validation_timestamp"))
    if current_at is None or validation_at is None or validation_at > current_at:
        return None
    # Recheck against the public facts at the consumer boundary as well as at
    # scan attachment. A mutated/stale view must not outrank a revised event
    # ledger, canonical history, or a later retirement of the exact anchor life.
    checker = ReversalFormationCustody()
    timeframe_rows = {}
    raw_timeframes = (snapshot or {}).get("timeframes") or {}
    if not isinstance(raw_timeframes, dict):
        return None
    for timeframe, facts in raw_timeframes.items():
        if not isinstance(facts, dict):
            return None
        bars = facts.get("recent_candles")
        if not isinstance(bars, list):
            return None
        timeframe_rows[timeframe] = bars
    if not checker._still_current(
            snapshot, valid, derived.get("history_revision"), contract, session,
            timeframe_rows):
        return None
    block = copy.deepcopy(valid.get("block") or {})
    if not block.get("available"):
        return None
    block["formation_authority"] = {
        "status": "CURRENT_PROCESS_REVALIDATED",
        "occurrence_id": valid.get("occurrence_id"),
        "history_revision": derived.get("history_revision"),
        "anchor_identity": copy.deepcopy(valid.get("anchor_identity")),
        "sweep_occurrence_id": (valid.get("sweep_evidence") or {}).get(
            "occurrence_id"),
    }
    return block
