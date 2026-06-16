"""
Adaptive Learning — Phase 1A: Live Memory Writer (scar-tissue recorder).

Closed outcome → validate → deterministic memory_id → normalize → append to the
EXISTING vector store (data/ai_retrieval/memory_store.jsonl) → retrievable.

SCOPE GUARANTEES (Phase 1A):
  * RECORDING ONLY. Does not touch execution, risk, confidence, or Brain prompts.
  * Reuses ai_retrieval.vector_store (no second store) and ai_retrieval.memory_schema
    so the written record carries the SAME market_context / narrative_context /
    provenance the existing embedding.py + is_authoritative() already consume.
  * Idempotent: a deterministic memory_id keyed on (instrument, entry_timestamp,
    source_type) is checked against the store before every write.

This is the writer half of the learning loop. NOTHING reads these records back
into behaviour yet — that is a later phase. Never raises.
"""
from __future__ import annotations

import hashlib

from ai_retrieval.memory_schema import (
    make_record, win_loss_be_from_r, classify_provenance,
)
from ai_retrieval.vector_store import add_record, load_records

# Recognised provenance for the deterministic id's source_type component.
VALID_SOURCE_TYPES = ("closed_trade", "resolved_intent")

# Statuses that mean the position is NOT resolved — never recordable.
_OPEN_STATUSES = {
    "open", "active", "submitted", "partially_filled", "pending", "working",
}

# Market-state fields that must be present (non-empty) for a usable embedding.
# Without these the embedding degrades to a near-zero vector and the record is
# worthless as an analog, so we reject rather than poison the store.
REQUIRED_STATE_FIELDS = ("session", "regime", "volatility_state")
# At least ONE directional state field must be present (the embedding's
# narrative/delivery direction axis).
_DIRECTION_FIELDS = ("narrative_direction", "direction", "delivery_direction")


# ── deterministic id ──────────────────────────────────────────────────────────

def compute_memory_id(instrument: str, entry_timestamp: str, source_type: str) -> str:
    """SHA256(instrument + '*' + entry_timestamp + '*' + source_type)."""
    raw = f"{instrument}*{entry_timestamp}*{source_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── helpers ───────────────────────────────────────────────────────────────────

def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _existing_ids() -> set:
    """memory_ids already present in the store (only this writer sets them)."""
    ids = set()
    for rec in load_records():
        mid = rec.get("memory_id")
        if mid:
            ids.add(mid)
    return ids


def _result(reason: str, memory_id=None, **extra) -> dict:
    return {"written": False, "skipped": False, "memory_id": memory_id,
            "reason": reason, **extra}


# ── validation ────────────────────────────────────────────────────────────────

def validate_outcome(outcome: dict, source_type: str) -> tuple:
    """Return (ok: bool, reason: str). Pure; never raises."""
    if source_type not in VALID_SOURCE_TYPES:
        return False, f"invalid_source_type:{source_type}"

    instrument = _first(outcome, "instrument", "symbol")
    entry_ts = _first(outcome, "entry_timestamp", "timestamp", "entry_time")
    if not instrument:
        return False, "missing_instrument"
    if not entry_ts:
        return False, "missing_entry_timestamp"

    # open / unresolved
    status = (_first(outcome, "status", "order_status", "trade_status") or "").lower()
    if status in _OPEN_STATUSES:
        return False, "open_trade"
    if outcome.get("closed") is False:
        return False, "open_trade"

    # missing exit
    if _first(outcome, "exit_price", "exit") is None:
        return False, "missing_exit"

    # missing realized_r
    if _first(outcome, "realized_r") is None:
        return False, "missing_realized_r"

    # missing result (allowed to be derived from realized_r below; reject only
    # if neither an explicit result nor a derivable one exists)
    if _first(outcome, "result", "win_loss_be") is None \
            and win_loss_be_from_r(outcome.get("realized_r")) is None:
        return False, "missing_result"

    # required market-state embedding fields
    for f in REQUIRED_STATE_FIELDS:
        if not _first(outcome, f):
            return False, f"incomplete_market_state:{f}"
    if not any(_first(outcome, f) for f in _DIRECTION_FIELDS):
        return False, "incomplete_market_state:direction"

    return True, "ok"


# ── normalization ─────────────────────────────────────────────────────────────

def normalize_outcome(outcome: dict, source_type: str, memory_id: str) -> dict:
    """Build the canonical record: nested contexts (for embedding/provenance) +
    the flat Phase-1A contract fields. Never raises."""
    instrument = _first(outcome, "instrument", "symbol")
    entry_ts = _first(outcome, "entry_timestamp", "timestamp", "entry_time")
    direction = _first(outcome, "direction", "narrative_direction", "trade_direction")
    narrative_dir = _first(outcome, "narrative_direction", "direction")
    delivery_dir = _first(outcome, "delivery_direction", "narrative_direction", "direction")
    realized_r = outcome.get("realized_r")
    result = _first(outcome, "result", "win_loss_be") or win_loss_be_from_r(realized_r)
    direction_source = _first(outcome, "direction_source") or (
        "ai_brain" if _first(outcome, "ai_thesis_summary") else None)

    # Base record carries market_context / narrative_context / provenance EXACTLY
    # as the existing embedding.py + is_authoritative() expect.
    record = make_record(
        record_type="trade",
        timestamp=entry_ts,
        symbol=instrument,
        session=_first(outcome, "session"),
        regime=_first(outcome, "regime"),
        volatility_state=_first(outcome, "volatility_state"),
        narrative_direction=narrative_dir,
        narrative_phase=_first(outcome, "narrative_phase"),
        active_liquidity_draw=_first(outcome, "active_liquidity_draw"),
        protected_high=outcome.get("protected_high"),
        protected_low=outcome.get("protected_low"),
        delivery_direction=delivery_dir,
        delivery_direction_source=direction_source,
        active_playbook=_first(outcome, "playbook"),
        trade_taken=True,
        trade_direction=direction,
        win_loss_be=result,
        r_multiple=realized_r,
        management_path=_first(outcome, "management_path", "close_reason", "exit_reason"),
        direction_source=direction_source,
    )

    validated, tainted = classify_provenance(direction_source)

    # Flat Phase-1A contract fields (the explicit required output surface).
    record.update({
        "memory_id":               memory_id,
        "source_type":             source_type,
        "timestamp":               entry_ts,
        "instrument":              instrument,
        "session":                 _first(outcome, "session"),
        "regime":                  _first(outcome, "regime"),
        "playbook":                _first(outcome, "playbook"),
        "direction":               direction,
        "ai_thesis_summary":       _first(outcome, "ai_thesis_summary"),
        "ai_confidence_at_entry":  outcome.get("ai_confidence_at_entry"),
        "entry_price":             outcome.get("entry_price"),
        "stop_price":              outcome.get("stop_price"),
        "target_price":            outcome.get("target_price"),
        "exit_price":              _first(outcome, "exit_price", "exit"),
        "result":                  result,
        "realized_r":              realized_r,
        "mfe":                     outcome.get("mfe"),
        "mae":                     outcome.get("mae"),
        "management_path":         _first(outcome, "management_path", "close_reason", "exit_reason"),
        "success_or_failure_reason": _first(
            outcome, "success_or_failure_reason", "close_reason", "exit_reason"),
        "volatility_state":        _first(outcome, "volatility_state"),
        "is_authoritative":        bool(validated and not tainted),
    })
    return record


# ── public entry point ────────────────────────────────────────────────────────

def write_outcome(outcome: dict, source_type: str = "closed_trade") -> dict:
    """
    Validate, dedup, normalize, and append one resolved outcome to the vector
    store. Returns a result dict:
        {written, skipped, memory_id, reason}
    Never raises. RECORDING ONLY — no behavioural influence (Phase 1A).
    """
    try:
        ok, reason = validate_outcome(outcome or {}, source_type)
        if not ok:
            return _result(reason)

        instrument = _first(outcome, "instrument", "symbol")
        entry_ts = _first(outcome, "entry_timestamp", "timestamp", "entry_time")
        memory_id = compute_memory_id(instrument, entry_ts, source_type)

        if memory_id in _existing_ids():
            return {"written": False, "skipped": True, "memory_id": memory_id,
                    "reason": "duplicate"}

        record = normalize_outcome(outcome, source_type, memory_id)
        wrote = add_record(record)   # embeds + appends to the existing store
        if not wrote:
            return _result("store_write_failed", memory_id=memory_id)
        return {"written": True, "skipped": False, "memory_id": memory_id,
                "reason": "ok", "record": record}
    except Exception as exc:  # noqa: BLE001
        return _result(f"writer_error:{type(exc).__name__}")
