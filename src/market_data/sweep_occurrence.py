"""LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — the production-safe occurrence adapter.

WHY THIS MODULE EXISTS AT ALL. `market_events` already holds a sweep-event shape
and the right "reclaim is an attribute" reasoning, and the obvious move was to
put this function there. A certified invariant refused it:

    test_no_production_module_imports_market_events
        "...market_events, whose `_sweep_at` authors sweeps from a bridged
         array-neighbour close. Either remove the dependency or give that caller
         real cadence -- do not update this test to accept it."

That module contains cadence-unsafe historical reconstruction — `_sweep_at`
inferring the swept level from `nearest_*_liquidity` (the nearest pool NOW, which
is not proof of what the tape took) and `analyze_liquidity(..., allow_uncadenced=
True)`, the synthetic adjacency the production path refuses. MODULE PLACEMENT
CARRIES AUTHORITY CONSEQUENCES: importing it into production would drag that
reconstruction across the quarantine line whether or not this function calls it.

So only the PURE canonicalization lives here. Nothing in this module
reconstructs history, bridges cadence, or infers a level after the fact.

    DETECTION TRUTH   liquidity_engine        what happened (ref_high/ref_low)
    IDENTITY          this module            which canonical object it is
    ID THEOREM        object_identity        the ONE id owner, unchanged
    WRITER            production_scan_cycle  the sole production writer
    PERSISTENCE       occurrence_ledger      what must not be forgotten
    MEANING           PO3 / Luna, later      what it implies for a trade

`reclaimed` is an ATTRIBUTE, never its own event. The detector only declares a
sweep when ONE settled candle both pierces a level and closes back through it, so
a SWEPT -> RECLAIMED lifecycle would be an ontology the evidence cannot support.
`market_events._sweep_at` reached the same conclusion independently; that
reasoning is adopted, its implementation is not.
"""
from __future__ import annotations

import math

from market_data.object_identity import (canonical_contract, canonical_instant,
                                         market_object_id)

#: The event-type ontology name. `market_events` defines the same string for its
#: own quarantined reconstruction path; they are pinned equal by test so the two
#: can never drift into meaning different things. This module is the authority
#: for the PRODUCTION path.
LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"


def liquidity_sweep_occurrence(sweep_fact: dict, *, source_tf: str,
                               contract, snapshot: dict = None) -> "dict | None":
    """The canonical LIQUIDITY_SWEEP occurrence for ONE authoritative sweep fact.

    Consumes the birth evidence `liquidity_engine` publishes at the instant of
    detection -- the exact `ref_high`/`ref_low` it compared against -- and adds
    exactly one thing: canonical identity.

    FAILS CLOSED. Returns None when the instant, the timeframe or the contract
    cannot be established. An occurrence with no provable identity is not an
    occurrence, and may not be written to a durable factual store.
    """
    if not isinstance(sweep_fact, dict):
        return None
    when = sweep_fact.get("event_time")
    level = sweep_fact.get("swept_level")
    if not when or level is None or not source_tf:
        return None
    try:
        occurrence_id = market_object_id(LIQUIDITY_SWEEP, contract=contract,
                                         timeframe=str(source_tf), instant=when)
    except Exception:            # noqa: BLE001 — unprovable identity is absence
        return None
    row = {
        "occurrence_id": occurrence_id,
        "event_type": LIQUIDITY_SWEEP,
        "contract": canonical_contract(contract, where=LIQUIDITY_SWEEP),
        "source_tf": str(source_tf),
        "event_time": canonical_instant(when),
        "sweep_direction": sweep_fact.get("sweep_direction"),
        "liquidity_side_taken": sweep_fact.get("liquidity_side_taken"),
        "swept_level": level,
        "swept_level_id": sweep_fact.get("swept_level_id"),
        "reclaimed": bool(sweep_fact.get("reclaimed")),
        "reclaimed_at": sweep_fact.get("reclaimed_at"),
        "reclaim_basis": sweep_fact.get("reclaim_basis"),
        "source_bars": list(sweep_fact.get("source_bars") or ()),
        # LUNA-LIQUIDITY-SCOPE-TRUTH-1. Frozen at mint, with the reference each
        # claim was judged against. A later scan may mint a DIFFERENT occurrence
        # with a different scope; it may never restate this one.
        "scope_schema": sweep_fact.get("scope_schema"),
        "detector_scope": sweep_fact.get("detector_scope") or "unknown",
        "detector_scope_reference": sweep_fact.get("detector_scope_reference"),
        "po3_scope": sweep_fact.get("po3_scope") or "unknown",
        "po3_scope_reference": sweep_fact.get("po3_scope_reference"),
        "scope_reason": sweep_fact.get("scope_reason"),
    }
    # Bind the protected life that was simultaneously current when this sweep
    # was observed. This is additive evidence: the canonical sweep identity
    # above is unchanged, and an absent/mismatched anchor simply leaves this
    # optional relationship unavailable.
    lifetime = protected_swing_lifetime_at_sweep(
        row, snapshot=snapshot, source_tf=str(source_tf))
    if lifetime is not None:
        row["protected_swing_lifetime"] = lifetime
    return row


def protected_swing_lifetime_at_sweep(sweep: dict, *, snapshot: dict,
                                      source_tf: str) -> dict | None:
    """Name an exact current protected life observed with a settled sweep.

    The relationship is captured at the producer boundary, where the detector
    event and current registry coexist. Price equality is one required field,
    never the identity proof by itself.
    """
    if not isinstance(sweep, dict) or not isinstance(snapshot, dict):
        return None
    contract = str(snapshot.get("contract_id") or "").strip()
    direction = sweep.get("sweep_direction")
    side = "low" if direction == "below_low" else (
        "high" if direction == "above_high" else None)
    if (not contract or sweep.get("contract") != contract or not side
            or sweep.get("source_tf") != source_tf
            or sweep.get("reclaimed") is not True):
        return None
    try:
        level = float(sweep.get("swept_level"))
        if not math.isfinite(level):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    event_at = sweep.get("event_time")
    source_bars = sweep.get("source_bars")
    if not isinstance(source_bars, list) or event_at not in source_bars:
        return None
    registry = (((snapshot.get("protected_swings") or {}).get("by_timeframe")
                 or {}).get("lows" if side == "low" else "highs") or {})
    record = registry.get(source_tf)
    if not isinstance(record, dict):
        return None
    try:
        protected_level = float(record.get("level"))
    except (TypeError, ValueError, OverflowError):
        return None
    if (protected_level != level
            or record.get("timeframe") != source_tf
            or record.get("side") not in (None, side)
            or record.get("role") not in ("context", "active_leg")
            or not record.get("swing_id") or not record.get("registered_at")
            or not record.get("basis")):
        return None
    observed_at = snapshot.get("timestamp")
    try:
        from market_data.object_identity import canonical_instant
        if (canonical_instant(observed_at, strict=True)
                < canonical_instant(event_at, strict=True)):
            return None
    except Exception:  # noqa: BLE001 - ambiguous chronology is not authority
        return None
    try:
        from market_state.active_path import production_session_key
        session = production_session_key(observed_at)
    except Exception:  # noqa: BLE001
        return None
    if not session:
        return None
    return {
        "contract": contract,
        "market_session": session,
        "source_tf": source_tf,
        "side": side,
        "swing_id": str(record["swing_id"]),
        "registered_at": str(record["registered_at"]),
        "level": protected_level,
        "basis": str(record["basis"]),
        "observed_at": str(observed_at),
        "sweep_occurrence_id": sweep.get("occurrence_id"),
    }
