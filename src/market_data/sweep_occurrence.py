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

from market_data.object_identity import (canonical_contract, canonical_instant,
                                         market_object_id)

#: The event-type ontology name. `market_events` defines the same string for its
#: own quarantined reconstruction path; they are pinned equal by test so the two
#: can never drift into meaning different things. This module is the authority
#: for the PRODUCTION path.
LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"


def liquidity_sweep_occurrence(sweep_fact: dict, *, source_tf: str,
                               contract) -> "dict | None":
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
    return {
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
    }
