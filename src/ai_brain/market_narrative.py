"""NARRATIVE-FIRST-1: the Brain's own market read, kept apart from permission.

`output_direction_hold` rewrites the story, reasoning, direction and entry
fields of a read whose direction the mechanics cannot yet authorize. That held
object is the correct PARTICIPATION view and it stays exactly as it is. But it
was also the only thing remembered, so on PROD-20261023-C1 275 of 382 authored
market stories reached the next call as the generic hold sentence.

This module carries the other view: the validated primary judgment captured by
value BEFORE the hold, stamped with the cognition's actual provenance, and
transported to the next Brain as prior DESCRIPTIVE judgment. It is
OBSERVATIONAL_ONLY everywhere. Nothing here is read by a guard, the candidate
producer, Lifecycle, Draw, campaign/leg/transfer state or any execution path;
it is never a proved incumbent, a verified transfer, a falsifier or approval.

Absent, degraded or unvalidated cognition is UNKNOWN with a reason. A read is
never reconstructed from the held template.
"""
from __future__ import annotations

import copy
import hashlib
import json

READ_SCHEMA = "authored_market_read/v1"
HISTORY_SCHEMA = "market_narrative_history/v1"
AUTHORITY = "OBSERVATIONAL_ONLY"
SOURCE = "validated_primary_pre_authority_hold"
#: The authored judgment, flat. `current_action` is published as `authored_action`.
TEXT_FIELDS = ("market_story", "dominant_reasoning", "delivery_interpretation",
               "liquidity_interpretation", "protected_high_interpretation",
               "protected_low_interpretation", "thesis_health")
LABEL_FIELDS = ("narrative_direction", "narrative_phase")
TEXT_LIMIT = 1200
PRIOR_ITEMS = 4
SCOPE_NOTE = ("Prior DESCRIPTIVE market judgment you authored before any mechanical "
              "participation hold. It is not a proved incumbent, verified transfer, "
              "falsifier or entry approval, and it never states that participation "
              "was permitted; current permission is in narrative_continuity and the "
              "guarded stance_history.")


def digest(value) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unknown(reason: str, **context) -> dict:
    return {"schema": READ_SCHEMA, "status": "UNKNOWN", "reason": str(reason),
            "authority": AUTHORITY, **context}


def _bounded_text(value, field, truncations):
    text = "" if value is None else str(value)
    if len(text) > TEXT_LIMIT:
        truncations.append({"field": field, "chars": len(text),
                            "digest": digest(text)})
        text = text[:TEXT_LIMIT]
    return text


def _metadata(fn):
    """Actual metadata or None: a failing producer is reported missing, never guessed."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def capture(output, *, source, fallback_reason, llm_call, repair, snapshot,
            symbol, stance_memory) -> dict:
    """Snapshot the validated primary judgment before the authority hold.

    Called with the output AFTER schema validation (and any accepted repair)
    and BEFORE `output_direction_hold`. The returned dict shares nothing with
    `output`, so a later guard mutation cannot alias it.
    """
    try:
        if source != "llm" or fallback_reason:
            return unknown("cognition_not_validated_primary",
                           cognition_source=source, fallback_reason=fallback_reason)
        if not isinstance(output, dict):
            return unknown("validated_output_unavailable")
        authored = copy.deepcopy(output)
        snap = snapshot if isinstance(snapshot, dict) else {}
        derived = snap.get("derived_state")
        scope = {}
        lineage = None
        if stance_memory is not None and getattr(stance_memory, "production_scope", None):
            scope = _metadata(lambda: stance_memory._current_scope(snap)) or {}
            lineage = {"custody": _metadata(lambda: stance_memory.custody_token),
                       "history_revision": scope.get("history_revision")}
        from ai_brain.production_model import brain_contract_fingerprint
        from ai_retrieval.retrieval_contract import retrieval_contract_fingerprint
        truncations = []
        read = {"schema": READ_SCHEMA, "status": "AVAILABLE", "authority": AUTHORITY}
        for field in LABEL_FIELDS:
            read[field] = authored.get(field)
        for field in TEXT_FIELDS:
            read[field] = _bounded_text(authored.get(field), field, truncations)
        read["authored_action"] = authored.get("current_action")
        call = llm_call if isinstance(llm_call, dict) else {}
        read["provenance"] = {
            "source": SOURCE,
            "contract_id": scope.get("contract_id") or snap.get("contract_id"),
            "symbol": symbol,
            "market_session": scope.get("market_session"),
            "settled_cutoff": scope.get("recorded_at_cutoff") or snap.get("timestamp"),
            "history_revision": (scope.get("history_revision") if scope else
                                 (derived.get("history_revision")
                                  if isinstance(derived, dict) else None)),
            "process_session_id": scope.get("process_session_id"),
            "history_lineage": lineage,
            "served_model": call.get("model"),
            "brain_fingerprint": _metadata(brain_contract_fingerprint),
            "retrieval_fingerprint": _metadata(retrieval_contract_fingerprint),
            "repair": {"json_repair_accepted": bool((repair or {}).get("json")),
                       "family_repair_accepted": bool((repair or {}).get("family")),
                       "invalidation_repair_accepted": bool((repair or {}).get("invalidation"))},
            "pre_hold_output_digest": digest(authored),
        }
        read["truncations"] = truncations
        return read
    except Exception as exc:  # noqa: BLE001 -- narrative telemetry never costs a scan
        return unknown(f"capture_error:{type(exc).__name__}")


def accepts_read(recorder) -> bool:
    """True when `recorder.record` declares the observational read parameter."""
    import inspect
    try:
        params = inspect.signature(recorder.record).parameters
    except (TypeError, ValueError, AttributeError):
        return False
    return "authored_market_read" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def for_record(read) -> dict:
    """What a stance row keeps: an AVAILABLE read verbatim, or a typed UNKNOWN."""
    if isinstance(read, dict) and read.get("schema") == READ_SCHEMA:
        if read.get("status") == "AVAILABLE":
            return copy.deepcopy(read)
        return unknown(read.get("reason") or "unknown")
    return unknown("authored_read_not_supplied")


def _item(row, current=None) -> dict:
    """One flat history item from a stance row; never authority."""
    cutoff = row.get("recorded_at_cutoff") or row.get("timestamp")
    read = row.get("authored_market_read")
    if not isinstance(read, dict):
        return unknown("legacy_row_without_authored_read", recorded_at_cutoff=cutoff)
    if read.get("status") != "AVAILABLE":
        return unknown(read.get("reason") or "unknown", recorded_at_cutoff=cutoff)
    prov = read.get("provenance") or {}
    if current is not None:
        # The read must belong to the very row (and scope) that carries it: a
        # copied or relabelled read cannot borrow a proved row's eligibility.
        for field, row_value in (("contract_id", row.get("contract_id")),
                                 ("market_session", row.get("market_session")),
                                 ("settled_cutoff", row.get("recorded_at_cutoff")),
                                 ("process_session_id", row.get("process_session_id"))):
            if prov.get(field) != row_value:
                return unknown(f"provenance_mismatch:{field}", recorded_at_cutoff=cutoff)
        lineage = row.get("history_lineage") or {}
        if prov.get("history_revision") != lineage.get("history_revision"):
            return unknown("provenance_mismatch:history_revision", recorded_at_cutoff=cutoff)
    if read.get("authority") != AUTHORITY:
        return unknown("authority_label_invalid", recorded_at_cutoff=cutoff)
    item = {k: copy.deepcopy(read.get(k)) for k in
            ("status", "authority", *LABEL_FIELDS, *TEXT_FIELDS, "authored_action",
             "truncations")}
    # The pre-hold digest stays in the envelope and stance row. It hashes the
    # whole authored object, including per-process catalog/custody ids, so in
    # the transported input it would make identical cognition look different.
    transported = {k: copy.deepcopy(v) for k, v in prov.items()
                   if k != "pre_hold_output_digest"}
    item.update(schema=READ_SCHEMA, recorded_at_cutoff=cutoff, provenance=transported)
    return item


def history(rows, *, current=None, withheld_reasons=None) -> dict:
    """The next Brain's `market_narrative_history`, from already-eligible rows."""
    items = [_item(r, current) for r in rows if isinstance(r, dict)]
    last = items[-1] if items else None
    return {
        "schema": HISTORY_SCHEMA,
        "authority": AUTHORITY,
        "scope_note": SCOPE_NOTE,
        "available": bool(last and last.get("status") == "AVAILABLE"),
        "last": last,
        "prior": items[-1 - PRIOR_ITEMS:-1] if len(items) > 1 else [],
        "unknown_count": sum(1 for i in items if i.get("status") != "AVAILABLE"),
        "withheld_rows": dict(withheld_reasons or {}),
    }


def unavailable_history(reason: str) -> dict:
    return {"schema": HISTORY_SCHEMA, "authority": AUTHORITY, "scope_note": SCOPE_NOTE,
            "available": False, "last": None, "prior": [], "unknown_count": 0,
            "withheld_rows": {}, "reason": reason}


def strip_from_stance_view(value):
    """Remove the read from a guarded stance_history view (it travels separately)."""
    if isinstance(value, dict):
        value.pop("authored_market_read", None)
    return value
