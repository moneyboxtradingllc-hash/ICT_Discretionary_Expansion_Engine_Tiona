"""Deterministic scheduler for paid external Brain cognition.

The mechanical organism keeps running on every scan.  This component answers
one narrower question at the final pre-provider boundary: did the already-
computed mechanical evidence change enough to justify another external Brain
read?

It has no model client, no trade authority, no direction, and no risk or order
logic.  Any uncertainty returns WAKE.  HOLD must be earned by complete, current,
unchanged evidence and is bounded by a maximum-silence wake.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import datetime, timezone


SCHEMA_VERSION = "brain_wake_decision.v1"
PROJECTION_VERSION = "brain_wake_semantic_projection.v1"

OFF = "OFF"
AUDIT = "AUDIT"
ENFORCE = "ENFORCE"
MODES = (OFF, AUDIT, ENFORCE)

WAKE = "WAKE"
HOLD = "HOLD"
HOLD_SOURCE = "brain_sleep_hold"

MODE_ENV = "BRAIN_WAKE_MODE"
MAX_SILENCE_ENV = "BRAIN_WAKE_MAX_SILENCE_SECONDS"

# A configurable backstop, not an acceptance target.  ENFORCE is disabled by
# default, and historical replay must evaluate other values before deployment.
DEFAULT_MAX_SILENCE_SECONDS = 300.0

WRITE_FAILED = "BRAIN_WAKE_TELEMETRY_WRITE_FAILED"


def configured_mode(value=None) -> str:
    """Resolve OFF/AUDIT/ENFORCE.  Invalid configuration fails open as OFF."""
    raw = os.getenv(MODE_ENV, OFF) if value is None else value
    token = str(raw or "").strip().upper()
    return token if token in MODES else OFF


def configured_max_silence(value=None) -> "float | None":
    """Positive finite seconds, or None when configuration is unsafe."""
    raw = (os.getenv(MAX_SILENCE_ENV, str(DEFAULT_MAX_SILENCE_SECONDS))
           if value is None else value)
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _aware_datetime(value) -> "datetime | None":
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _pick(block, keys) -> dict:
    src = _dict(block)
    return {key: src.get(key) for key in keys if key in src}


def _sort_rows(rows: list) -> list:
    return sorted(rows, key=lambda row: json.dumps(
        row, sort_keys=True, separators=(",", ":"), default=str))


def _catalog_view(rows, keys) -> list:
    return _sort_rows([_pick(row, keys) for row in _list(rows)
                       if isinstance(row, dict)])


def _swing_registry(snapshot: dict, brain_input: dict) -> dict:
    raw = _dict(snapshot.get("protected_swings"))
    shown = _dict(brain_input.get("protected_swings"))
    by_tf = _dict(raw.get("by_timeframe"))
    registries = {}
    for side in ("highs", "lows"):
        registries[side] = {
            str(tf): _pick(rec, (
                "swing_id", "level", "basis", "registered_at", "status",
                "invalidated", "violated",
            ))
            for tf, rec in sorted(_dict(by_tf.get(side)).items())
            if isinstance(rec, dict)
        }
    ordinal = _dict(shown.get("ordinal_sequence"))
    return {
        "protected_high": _pick(shown.get("protected_high"),
                                ("swing_id", "level", "basis", "registered_at")),
        "protected_high_status": shown.get("protected_high_status"),
        "protected_low": _pick(shown.get("protected_low"),
                               ("swing_id", "level", "basis", "registered_at")),
        "protected_low_status": shown.get("protected_low_status"),
        "by_timeframe": registries,
        "roles": _dict(raw.get("roles")),
        "ordinal_sequence": _pick(ordinal, (
            "sequence", "authority", "confirmed_highs", "confirmed_lows",
            "high_ordinals", "low_ordinals",
        )),
    }


def _active_path_view(value) -> dict:
    block = _dict(value)
    load = _dict(block.get("load_bearing_structure"))
    origin = _dict(block.get("origin"))
    progression = _dict(block.get("progression"))
    invalidated = _dict(block.get("last_invalidated"))
    return {
        **_pick(block, ("state_available", "unavailable_reason", "owner",
                        "forming_direction", "status", "session",
                        "last_reset_reason")),
        "origin": _pick(origin, ("event", "source_tf", "occurrence_id", "at")),
        "load_bearing_structure": _pick(load, (
            "swing_id", "level", "side", "timeframe", "intact",
            "producer_backed", "last_move_favourable",
        )),
        "progression": _pick(progression, (
            "supporting_timeframes", "highest_confirmed", "successive_favourable",
        )),
        "transfer_evidence": _pick(block.get("transfer_evidence"), (
            "opposing_structure_break", "load_bearing_failure",
            "load_bearing_replaced_against_path", "opposing_raid_rejected",
            "opposing_market_structure_shift", "opposing_displacement",
        )),
        "last_invalidated": _pick(invalidated, (
            "occurrence_id", "event_type", "side", "level", "swing_id",
            "source_tf", "event_time", "reason",
        )),
    }


def _liquidity_view(snapshot: dict, brain_input: dict) -> dict:
    shown = _dict(brain_input.get("liquidity"))
    exact = []
    for event in _list(brain_input.get("liquidity_events")):
        if isinstance(event, dict):
            exact.append(_pick(event, (
                "occurrence_id", "timeframe", "tf", "event_time", "side",
                "liquidity_side_taken", "sweep_direction", "swept_level",
                "reclaimed", "reclaim", "detector_scope", "po3_scope",
            )))
    current = []
    for tf, block in sorted(_dict(snapshot.get("liquidity")).items()):
        if not isinstance(block, dict):
            continue
        fact = _dict(block.get("sweep_fact"))
        if block.get("sweep_detected") or fact:
            current.append({
                "timeframe": tf,
                **_pick(block, ("sweep_detected", "sweep_direction",
                                "reclaim_detected")),
                "fact": _pick(fact, (
                    "occurrence_id", "event_time", "sweep_direction",
                    "liquidity_side_taken", "swept_level", "reclaimed",
                    "detector_scope", "po3_scope",
                )),
            })
    draw = shown.get("active_draw")
    if isinstance(draw, dict):
        draw = _pick(draw, (
            "draw_id", "objective_id", "occurrence_id", "side", "direction",
            "level", "type", "kind", "source", "source_tf", "status",
            "valid", "available",
        ))
    return {"active_draw": draw, "current_events": _sort_rows(current),
            "event_identities": _sort_rows(exact)}


def _mtf_view(value) -> dict:
    block = _dict(value)
    synthesis = _dict(block.get("synthesis"))
    timeframes = {}
    for tf, facts in sorted(_dict(block.get("timeframes")).items()):
        facts = _dict(facts)
        timeframes[str(tf)] = {
            **_pick(facts, ("timeframe", "role", "price_vs_swing_low",
                            "price_vs_swing_high")),
            "confirmed": _pick(facts.get("confirmed"), (
                "last_swing_high", "last_swing_low", "mss_event",
            )),
            "realtime": _pick(facts.get("realtime"), (
                "bos_event", "broken_level", "sweep_detected",
                "reclaim_detected", "sweep_direction", "sweep_reclaim_complete",
            )),
        }
    return {
        "synthesis": _pick(synthesis, (
            "context_state", "active_leg_state", "transition_state",
            "execution_state", "timeframes_stating_something",
            "alignment_state", "conflicts",
        )),
        "timeframes": timeframes,
    }


_TOOL_KEYS = (
    "tool", "tool_family", "tool_id", "occurrence_id", "direction",
    "source_tf", "level_type", "execution_eligible", "temporal_class",
    "execution_ineligible_reason", "execution_quarantined",
    "execution_quarantine_reason", "zone_low", "zone_high", "midpoint",
    "mean_threshold", "invalidation_level", "protected_swing_id",
    "creating_run_start", "creating_run_end", "validation_timestamp",
    # Existing detector-owned location/actionability categories.  Deliberately
    # excludes current_price, bid/ask, distances and penetration percentages.
    "price_relation", "entered_zone", "invalidated", "location_basis",
    "readiness_next_status", "prerequisites_missing",
)

_OBJECTIVE_KEYS = (
    "objective_id", "kind", "type", "price", "side", "direction",
    "valid", "available", "eligible", "execution_eligible", "valid_for",
    "status", "source", "source_tf", "timeframe", "occurrence_id",
    "swing_id", "reference_semantics",
)

_INVALIDATION_KEYS = (
    "invalidation_id", "kind", "type", "price", "side", "direction",
    "valid", "available", "eligible", "execution_eligible", "valid_for",
    "status", "source", "timeframe", "original_swing_type",
    "break_direction", "lifecycle_state", "swing_id", "occurrence_id",
)


def semantic_projection(*, snapshot: dict, brain_input: dict,
                        session_id: str, contract_id: str) -> dict:
    """Small semantic state assembled only from existing detector outputs."""
    snap = _dict(snapshot)
    payload = _dict(brain_input)
    market = _dict(payload.get("market"))
    delivery = _dict(payload.get("delivery"))
    session_po3 = _dict(snap.get("session_po3")) or _dict(
        delivery.get("session_po3"))
    setup = _dict(snap.get("setup_lifecycle"))
    qualification = _dict(snap.get("qualification"))
    regime = _dict(snap.get("market_regime"))
    continuity = _dict(snap.get("candle_continuity"))
    derived = _dict(snap.get("derived_state"))
    quote = _dict(snap.get("execution_price")) or _dict(
        market.get("execution_price"))
    mtf = snap.get("mtf_market_state") or payload.get("MTF_MARKET_STATE")

    memory_rows = []
    for analog in _list(_dict(payload.get("memory_retrieval")).get("analogs")):
        if isinstance(analog, dict):
            memory_rows.append(_pick(analog, (
                "memory_id", "session_id", "source_session_id", "authority",
                "outcome_validated", "segment",
            )))

    return {
        "identity": {"session_id": session_id, "contract_id": contract_id,
                     "market_session": snap.get("session")},
        "integrity": {
            "continuous": continuity.get("continuous"),
            "history_revision": derived.get("history_revision"),
            "derived_revision": derived.get("derived_revision"),
            "derived_current": derived.get("current"),
            "quote_schema": quote.get("schema"),
            "quote_available": quote.get("available"),
            "quote_fresh": quote.get("fresh"),
            "quote_source": quote.get("source"),
        },
        "session_po3": _pick(session_po3, (
            "phase", "new_entry_allowed", "block_reason",
            "distribution_direction", "preferred_playbook_families",
        )) | {"manipulation": _pick(session_po3.get("manipulation"), (
            "classification", "direction", "conflicted",
        ))},
        "setup_lifecycle": _pick(setup, (
            "active", "setup_id", "playbook", "direction", "preferred_tool",
            "current_phase", "current_quality", "invalidated", "completed",
            "dormant",
        )),
        "active_path": _active_path_view(
            payload.get("active_path_state") or snap.get("active_path_state")),
        "liquidity": _liquidity_view(snap, payload),
        "protected_swings": _swing_registry(snap, payload),
        "structure_flips": _catalog_view(
            payload.get("structure_flips") or snap.get("structure_flips"),
            _INVALIDATION_KEYS + ("broken_at", "superseded_by", "invalidated_at")),
        "mtf_market_state": _mtf_view(mtf),
        "qualification": _pick(qualification, (
            "status", "qualified", "direction", "authorized_playbooks",
            "opportunity", "execution_eligible",
        )),
        "catalogs": {
            "tools": _catalog_view(payload.get("authorized_tool_catalog"),
                                   _TOOL_KEYS),
            "objectives": _catalog_view(payload.get("authorized_objectives"),
                                        _OBJECTIVE_KEYS),
            "invalidations": _catalog_view(payload.get("authorized_invalidations"),
                                           _INVALIDATION_KEYS),
        },
        "regime": _pick(regime, (
            "regime_label", "regime_family", "volatility_state",
            "expansion_state",
        )) | {
            "brain_volatility_state": market.get("volatility_state"),
            "brain_expansion_state": market.get("expansion_state"),
        },
        "memory_context": _sort_rows(memory_rows),
    }


def semantic_fingerprint(projection: dict) -> str:
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":"),
                     allow_nan=False, default=str).encode("utf-8")
    return "wake:" + hashlib.sha256(raw).hexdigest()[:16]


def evidence_issues(*, snapshot, brain_input, session_id, contract_id, scan,
                    now, pipeline_mode: str, catalogs_ok: bool = True) -> list:
    """Reasons this observation cannot earn HOLD."""
    issues = []
    if pipeline_mode != "non_ecu":
        return [f"unsupported_pipeline_state:{pipeline_mode or 'unknown'}"]
    if not isinstance(snapshot, dict):
        return ["malformed_required_evidence:snapshot"]
    if not isinstance(brain_input, dict):
        return ["malformed_required_evidence:brain_input"]
    if not isinstance(session_id, str) or not session_id.strip():
        issues.append("missing_required_identity:session_id")
    if not isinstance(contract_id, str) or not contract_id.strip():
        issues.append("missing_required_identity:contract_id")
    snap_contract = snapshot.get("contract_id")
    if snap_contract is not None and str(snap_contract) != str(contract_id):
        issues.append("contract_identity_mismatch")
    if type(scan) is not int or scan < 1:
        issues.append("invalid_scan_sequence")
    if _aware_datetime(now) is None:
        issues.append("invalid_observation_time")

    # An archived/post-provider object cannot prove a prior call was avoidable.
    if snapshot.get("ai_brain") or _dict(snapshot.get("candidate_thesis")).get(
            "brain_block"):
        issues.append("post_provider_evidence_present")

    continuity = snapshot.get("candle_continuity")
    if not isinstance(continuity, dict):
        issues.append("missing_required_evidence:candle_continuity")
    elif continuity.get("continuous") is not True:
        issues.append("candle_continuity_not_proven")

    derived = snapshot.get("derived_state")
    if not isinstance(derived, dict):
        issues.append("missing_required_evidence:derived_state")
    elif derived.get("current") is not True:
        issues.append("derived_state_not_current")
    elif (derived.get("history_revision") is not None
          and derived.get("derived_revision") is not None
          and derived.get("history_revision") != derived.get("derived_revision")):
        issues.append("derived_state_revision_mismatch")

    quote = snapshot.get("execution_price")
    if not isinstance(quote, dict):
        quote = _dict(_dict(brain_input.get("market")).get("execution_price"))
    if not isinstance(quote, dict) or not quote:
        issues.append("missing_required_evidence:execution_price")
    else:
        if quote.get("available") is not True:
            issues.append("executable_quote_unavailable")
        if quote.get("fresh") is not True:
            issues.append("executable_quote_stale")
        if not _finite_number(quote.get("best_bid")):
            issues.append("malformed_required_evidence:best_bid")
        if not _finite_number(quote.get("best_ask")):
            issues.append("malformed_required_evidence:best_ask")

    required_dicts = (
        "session_po3", "setup_lifecycle", "active_path_state", "liquidity",
        "protected_swings", "mtf_market_state", "qualification", "market_regime",
        "toolbox",
    )
    for key in required_dicts:
        if not isinstance(snapshot.get(key), dict):
            issues.append(f"missing_required_evidence:{key}")
    if not isinstance(snapshot.get("structure_flips"), list):
        issues.append("missing_required_evidence:structure_flips")

    po3 = _dict(snapshot.get("session_po3"))
    if not po3.get("phase"):
        issues.append("malformed_required_evidence:session_po3.phase")
    active_path = _dict(snapshot.get("active_path_state"))
    if active_path.get("state_available") is not True:
        issues.append("active_path_state_unavailable")
    mtf = _dict(snapshot.get("mtf_market_state"))
    if mtf.get("error") or not isinstance(mtf.get("synthesis"), dict):
        issues.append("mtf_market_state_unavailable")
    if not _dict(snapshot.get("qualification")).get("status"):
        issues.append("malformed_required_evidence:qualification.status")
    if not _dict(snapshot.get("market_regime")).get("regime_label"):
        issues.append("malformed_required_evidence:market_regime.regime_label")

    for key in ("authorized_tool_catalog", "authorized_objectives",
                "authorized_invalidations"):
        rows = brain_input.get(key)
        if not isinstance(rows, list):
            issues.append(f"missing_required_evidence:{key}")
        elif any(not isinstance(row, dict) for row in rows):
            issues.append(f"malformed_required_evidence:{key}")
    if not catalogs_ok:
        issues.append("catalog_construction_unproven")

    # Reuse the existing contamination authority.  A semantic projection must
    # never hide a newly malformed/direction-leaking payload merely because the
    # selected market dimensions stayed unchanged.
    try:
        from ai_brain.brain_validation import scan_payload_taint
        taint_clean, taint_paths = scan_payload_taint(brain_input)
        if not taint_clean:
            issues.extend(f"brain_input_tainted:{str(path)[:120]}"
                          for path in taint_paths)
    except Exception as exc:  # noqa: BLE001 -- inability to check is uncertainty
        issues.append(f"brain_input_taint_unproven:{type(exc).__name__}")

    degraded = brain_input.get("degraded")
    if not isinstance(degraded, list):
        issues.append("malformed_required_evidence:brain_input.degraded")
    else:
        issues.extend(f"brain_input_degraded:{str(marker)[:120]}"
                      for marker in degraded if marker)
    return sorted(set(issues))


def fail_open_decision(*, mode=OFF, reason="controller_exception",
                       session_id="", contract_id="", scan=None, now=None) -> dict:
    """A structured WAKE used when even the controller cannot complete."""
    stamp = _aware_datetime(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "projection_version": PROJECTION_VERSION,
        "decision": WAKE,
        "reasons": [str(reason)],
        "mode": configured_mode(mode),
        "session_id": session_id,
        "contract_id": contract_id,
        "scan": scan,
        "timestamp": stamp.isoformat() if stamp else str(now or ""),
        "semantic_fingerprint": None,
        "previous_fingerprint": None,
        "changed_dimensions": [],
        "seconds_since_last_brain": None,
        "seconds_since_last_scheduled_wake": None,
        "seconds_since_last_provider_call": None,
        "last_brain_scan": None,
        "last_scheduled_wake_scan": None,
        "last_provider_call_scan": None,
        "would_suppress": False,
        "provider_call_suppressed": False,
        "actually_suppressed": False,
        "wake_kind": "safety",
        "evidence_integrity": {"ok": False, "issues": [str(reason)]},
    }


class BrainWakeController:
    """Sequential, session/contract-scoped semantic observer."""

    def __init__(self, *, mode=None, max_silence_seconds=None) -> None:
        self.mode_override = mode
        self.max_silence_override = max_silence_seconds
        self._previous = None
        self._last_scheduled_at = None
        self._last_scheduled_scan = None
        self._last_provider_at = None
        self._last_provider_scan = None
        self._force_wake_reason = None
        self._lock = threading.Lock()

    def observe(self, *, snapshot, brain_input, session_id, contract_id, scan,
                now, pipeline_mode="non_ecu", catalogs_ok=True) -> dict:
        """Return WAKE/HOLD.  It never intentionally raises."""
        with self._lock:
            mode = configured_mode(self.mode_override)
            max_silence = configured_max_silence(self.max_silence_override)
            stamp = _aware_datetime(now)
            prior = self._previous
            previous_fingerprint = prior.get("fingerprint") if prior else None
            try:
                projection = semantic_projection(
                    snapshot=snapshot, brain_input=brain_input,
                    session_id=session_id, contract_id=contract_id)
                fingerprint = semantic_fingerprint(projection)
                issues = evidence_issues(
                    snapshot=snapshot, brain_input=brain_input,
                    session_id=session_id, contract_id=contract_id, scan=scan,
                    now=now, pipeline_mode=pipeline_mode,
                    catalogs_ok=catalogs_ok)
            except Exception as exc:  # noqa: BLE001 -- uncertainty wakes cognition
                self._previous = None
                return fail_open_decision(
                    mode=mode,
                    reason=f"controller_exception:{type(exc).__name__}",
                    session_id=session_id, contract_id=contract_id,
                    scan=scan, now=now)

            reasons = []
            changed = []
            identity = (session_id, contract_id)
            seconds_scheduled = (None if stamp is None or self._last_scheduled_at is None
                                 else max(0.0, (stamp - self._last_scheduled_at).total_seconds()))
            seconds_provider = (None if stamp is None or self._last_provider_at is None
                                else max(0.0, (stamp - self._last_provider_at).total_seconds()))

            if max_silence is None:
                issues.append("invalid_max_silence_configuration")
            if mode == OFF:
                reasons.append("mode_off")
            elif issues:
                reasons.extend(issues)
            elif prior is None:
                reasons.append("first_valid_scan_or_controller_state_reset")
            elif identity != prior["identity"]:
                if session_id != prior["identity"][0]:
                    reasons.append("session_change")
                if contract_id != prior["identity"][1]:
                    reasons.append("contract_change")
                self._last_scheduled_at = None
                self._last_scheduled_scan = None
                self._last_provider_at = None
                self._last_provider_scan = None
                seconds_scheduled = seconds_provider = None
            else:
                if scan != prior["scan"] + 1:
                    reasons.append("sequence_gap_or_observation_reordering")
                if stamp is None or stamp <= prior["when"]:
                    reasons.append("observation_time_reordering")
                changed = sorted(
                    key for key, value in projection.items()
                    if value != prior["projection"].get(key))
                reasons.extend(f"semantic_change:{key}" for key in changed)

            if self._force_wake_reason:
                reasons.append(self._force_wake_reason)
            if (not reasons and max_silence is not None
                    and seconds_scheduled is not None
                    and seconds_scheduled >= max_silence):
                reasons.append("maximum_silence_elapsed")
            if not reasons and self._last_scheduled_at is None:
                reasons.append("provider_history_unavailable")

            decision = WAKE if reasons else HOLD
            hard_issue = bool(issues or any(r in (
                "sequence_gap_or_observation_reordering",
                "observation_time_reordering") for r in reasons))
            if hard_issue:
                # Bad evidence must not become the reference that later earns a
                # HOLD.  The next clean scan bootstraps and wakes again.
                self._previous = None
            else:
                self._previous = {
                    "identity": identity, "scan": scan, "when": stamp,
                    "projection": projection, "fingerprint": fingerprint,
                }

            suppressed = mode == ENFORCE and decision == HOLD
            wake_kind = None
            if decision == WAKE:
                if "maximum_silence_elapsed" in reasons:
                    wake_kind = "maximum_silence"
                elif changed:
                    wake_kind = "event"
                elif issues or self._force_wake_reason:
                    wake_kind = "safety"
                else:
                    wake_kind = "bootstrap"
            return {
                "schema_version": SCHEMA_VERSION,
                "projection_version": PROJECTION_VERSION,
                "decision": decision,
                "reasons": list(dict.fromkeys(reasons)),
                "mode": mode,
                "session_id": session_id,
                "contract_id": contract_id,
                "scan": scan,
                "timestamp": stamp.isoformat() if stamp else str(now or ""),
                "semantic_fingerprint": fingerprint,
                "previous_fingerprint": previous_fingerprint,
                "changed_dimensions": changed,
                "seconds_since_last_brain": seconds_provider,
                "seconds_since_last_scheduled_wake": seconds_scheduled,
                "seconds_since_last_provider_call": seconds_provider,
                "last_brain_scan": self._last_provider_scan,
                "last_scheduled_wake_scan": self._last_scheduled_scan,
                "last_provider_call_scan": self._last_provider_scan,
                "would_suppress": decision == HOLD,
                "provider_call_suppressed": suppressed,
                "actually_suppressed": suppressed,
                "wake_kind": wake_kind,
                "max_silence_seconds": max_silence,
                "evidence_integrity": {"ok": not issues,
                                       "issues": sorted(set(issues))},
            }

    def note_provider_result(self, decision: dict, *, request_attempted: bool,
                             sovereign: bool) -> None:
        """Advance actual and counterfactual clocks after the provider path."""
        with self._lock:
            stamp = _aware_datetime((decision or {}).get("timestamp"))
            scan = (decision or {}).get("scan")
            if request_attempted and stamp is not None:
                self._last_provider_at = stamp
                self._last_provider_scan = scan
                if (decision or {}).get("decision") == WAKE:
                    self._last_scheduled_at = stamp
                    self._last_scheduled_scan = scan
            if not request_attempted:
                self._force_wake_reason = "previous_provider_request_not_attempted"
            elif not sovereign:
                self._force_wake_reason = "previous_brain_not_sovereign"
            else:
                self._force_wake_reason = None


_CONTROLLERS = {}
_REGISTRY_LOCK = threading.Lock()


def controller_for(*, session_id: str, contract_id: str,
                   pipeline_mode: str) -> BrainWakeController:
    """Process-local controller. Missing identity deliberately cannot persist."""
    if not session_id or not contract_id:
        return BrainWakeController()
    key = (str(session_id), str(contract_id), str(pipeline_mode))
    with _REGISTRY_LOCK:
        if key not in _CONTROLLERS:
            _CONTROLLERS[key] = BrainWakeController()
        return _CONTROLLERS[key]


def reset_controller_registry() -> None:
    """Test/process-restart hook; losing state guarantees a bootstrap WAKE."""
    with _REGISTRY_LOCK:
        _CONTROLLERS.clear()


def telemetry_path(session_id: str) -> str:
    from ai_retrieval.retrieval_telemetry import session_root
    return os.path.join(session_root(session_id or "UNSCOPED"),
                        "brain_wake_decisions.jsonl")


def write_telemetry(decision: dict, *, primary_provider_request: bool,
                    repair_provider_requests: int = 0) -> dict:
    """Append compact wake accounting. A write failure never gates a scan."""
    record = {
        key: (decision or {}).get(key) for key in (
            "schema_version", "projection_version", "session_id", "contract_id",
            "scan", "timestamp", "mode", "decision", "reasons", "wake_kind",
            "semantic_fingerprint", "previous_fingerprint", "changed_dimensions",
            "seconds_since_last_brain", "seconds_since_last_scheduled_wake",
            "seconds_since_last_provider_call", "last_brain_scan",
            "last_scheduled_wake_scan", "last_provider_call_scan",
            "would_suppress", "provider_call_suppressed", "actually_suppressed",
            "max_silence_seconds", "evidence_integrity",
        )
    }
    record["primary_provider_request"] = bool(primary_provider_request)
    record["repair_provider_requests"] = int(repair_provider_requests or 0)
    path = telemetry_path(record.get("session_id") or "UNSCOPED")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return {"ok": True, "path": path}
    except Exception as exc:  # noqa: BLE001 -- accounting cannot cost a scan
        return {"ok": False, "path": path,
                "error": f"{WRITE_FAILED}: {type(exc).__name__}: {exc}"}
