"""Per-scan descriptive-memory retrieval telemetry.

ADD-PER-SCAN-MEMORY-RETRIEVAL-TELEMETRY (2026-08-07).

After a session we must be able to answer, from machine-countable evidence and
not from prose: was retrieval enabled on this scan, did the hook actually touch
the corpus, how many records were considered, how many were excluded and why,
which analogs reached the Brain, from which sessions, did semantic recurrence
collapse anything, did the per-session cap fire, and was the query complete.

TELEMETRY IS EVIDENCE, NOT MEMORY. It is written under the session archive root
and never into `data/ai_retrieval/memory_store.jsonl`. Nothing here can become
retrievable historical context.

Every record is derived from the SINGLE retrieval result the scan actually
consumed. Recomputing retrieval for telemetry would double the work and could
produce evidence that disagrees with what the Brain was shown.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytz

SCHEMA_VERSION = "memory_retrieval_telemetry.v1"
_EASTERN = pytz.timezone("America/New_York")

WRITE_FAILED = "RETRIEVAL_TELEMETRY_WRITE_FAILED"
INCOMPLETE_QUERY = "INCOMPLETE_RETRIEVAL_QUERY"

#: Load-bearing blocks whose disagreement gates a record. Mirrors the retrieval
#: contract; listed here so reason counts have a stable, complete key space.
CONTRADICTION_REASON_KEYS = ("market_regime", "volatility_state",
                             "delivery_state", "liquidity_state",
                             "direction_distribution")


def _suffix(value, n: int = 8) -> str:
    """Short, safe identifier tail. Never a full fingerprint."""
    s = str(value or "")
    return s[-n:] if s else ""


def session_root(session_id: str) -> str:
    return os.path.join(os.getenv("REPLAY_SESSIONS_DIR",
                                  os.path.join("data", "replay_sessions")),
                        str(session_id), "memory_retrieval")


def telemetry_path(session_id: str) -> str:
    return os.path.join(session_root(session_id), "retrieval_scans.jsonl")


# ── the record ───────────────────────────────────────────────────────────────
def build_record(*, session_id: str, scan_id: str, instrument: str,
                 contract: str, result: dict, startup_state: dict,
                 duration_ms: float = None, now_et: datetime = None) -> dict:
    """Describe ONE consumed retrieval result. Pure; never raises.

    `result` must be the exact object the scan handed to the Brain.
    """
    r = result or {}
    rejected = dict(r.get("rejected_reasons") or {})
    comp = r.get("completeness") or {}
    analogs = r.get("analogs") or []

    identity_rejected = sum(v for k, v in rejected.items()
                            if k.startswith(("retired_", "foreign_"))
                            or k == "missing_instrument_identity"
                            or k == "record_marked_ineligible")
    version_rejected = sum(v for k, v in rejected.items()
                           if "embedding" in k or "vector" in k
                           or k == "legacy_record_in_v2_corpus")
    expired = rejected.get("expired", 0)
    gated = rejected.get("load_bearing_contradiction", 0)
    below = rejected.get("below_min_similarity", 0)

    collapsed = r.get("recurrence_groups_collapsed") or []
    capped = r.get("per_session_cap_exclusions") or []
    corpus = int(r.get("corpus_size") or 0)

    # Stage progression, not overlapping buckets: a record has exactly one
    # terminal state. `recurrence_members_collapsed` counts members that were
    # ELIGIBLE and merged into a representative -- they are grouped
    # observations, not exclusions, and are reported separately so the
    # reconciliation below stays exact.
    merged = sum(max(0, int(g.get("count", 0)) - 1) for g in collapsed)
    # A refused query never stages the corpus at all, so every record's terminal
    # state is QUERY_INCOMPLETE. Counting it explicitly keeps the reconciliation
    # exact instead of reporting a phantom mismatch on a correctly refused scan.
    query_incomplete = corpus if r.get("refusal") else 0
    accounted = (identity_rejected + version_rejected + expired + gated + below
                 + merged + len(capped) + len(analogs) + query_incomplete)

    et = now_et or datetime.now(_EASTERN)
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "scan_id": scan_id,
        "timestamp_et": et.isoformat(),
        "instrument": instrument,
        "contract": contract,

        "retrieval_enabled": bool(r.get("enabled")),
        "startup_memory_state": startup_state.get("state"),

        # MANDATORY completeness is what decides refusal. Optional-block
        # absence is reported separately: conflating them made a fully
        # answerable query read as incomplete.
        "query_complete": (not comp) or bool(comp.get("satisfies_mandatory", True)),
        "optional_features_complete": (not comp) or bool(comp.get("complete")),
        "unknown_optional_blocks": [b for b in (comp.get("unknown_blocks") or [])
                                    if b not in (comp.get("missing_mandatory") or [])],
        "query_completeness_score": comp.get("score"),
        "missing_required_query_blocks": list(comp.get("missing_mandatory") or []),
        "incomplete_query_reason": (INCOMPLETE_QUERY if r.get("refusal")
                                    else None),

        "corpus_size": corpus,
        "descriptive_records": startup_state.get("descriptive_records"),
        "outcome_validated_records": startup_state.get("outcome_validated_records", 0),

        "query_incomplete_count": query_incomplete,
        "identity_rejected_count": identity_rejected,
        "version_rejected_count": version_rejected,
        "expired_count": expired,
        "contradiction_gated_count": gated,
        "below_threshold_count": below,
        "recurrence_members_collapsed": merged,
        "session_cap_excluded_count": len(capped),
        "returned_analog_count": len(analogs),
        "stage_accounting_reconciles": (accounted == corpus) if corpus else True,
        "stage_accounting_total": accounted,

        "contradiction_reason_counts": _contradiction_reasons(r),
        "contradiction_reason_occurrences": sum(
            _contradiction_reasons(r).values()),

        "exact_recurrence_groups": sum(
            1 for g in collapsed if g.get("recurrence_type") == "exact_same_session"),
        "semantic_recurrence_groups": sum(
            1 for g in collapsed if g.get("recurrence_type") == "semantic_same_session"),
        "recurrence_groups": [_group_view(g) for g in collapsed],

        "session_cap_exclusions": [
            {"source_session_id": c.get("session_id"),
             "memory_id_suffix": _suffix(c.get("memory_id")),
             "similarity": c.get("similarity"),
             "reason": "MAX_ANALOGS_PER_SOURCE_SESSION"} for c in capped],

        "max_analogs": r.get("max_analogs"),
        "max_analogs_per_source_session": r.get("max_analogs_per_source_session"),
        "similarity_threshold": r.get("min_similarity"),
        "retrieval_authority": r.get("retrieval_authority"),
        "vector_space": r.get("vector_space"),
        "embedding_version": r.get("embedding_version"),
        "manifest_fingerprint_suffix": _suffix(
            r.get("embedding_manifest_fingerprint"), 6),

        "returned_analogs": [_analog_view(a) for a in analogs],
        "source_sessions": sorted({a.get("session_id") for a in analogs
                                   if a.get("session_id")}),

        "retrieval_error": r.get("error"),
        "retrieval_duration_ms": (round(duration_ms, 2)
                                  if duration_ms is not None else None),
    }


def _contradiction_reasons(result: dict) -> dict:
    """Reason OCCURRENCES, which exceed gated-record count when a record
    contradicts on several blocks at once. Reported separately so the two are
    never confused."""
    counts = {}
    for key in CONTRADICTION_REASON_KEYS:
        counts[key] = 0
    for entry in result.get("_gated_detail") or []:
        for block in entry.get("blocks") or []:
            counts[block] = counts.get(block, 0) + 1
    return {k: v for k, v in counts.items() if v}


def _group_view(g: dict) -> dict:
    return {
        "recurrence_type": g.get("recurrence_type"),
        "recurrence_count": g.get("count"),
        "representative_memory_id_suffix": _suffix(g.get("representative")),
        "grouped_memory_id_suffixes": [_suffix(m)
                                       for m in g.get("grouped_memory_ids") or []],
        "occurrence_spans": g.get("spans"),
        "contextual_differences": g.get("contextual_differences"),
        "diagnostic_differences": g.get("diagnostic_differences"),
    }


def _analog_view(a: dict) -> dict:
    """Safe analog metadata only. No prices when levels are withheld, no
    account state, no raw model payload."""
    view = {
        "memory_id_suffix": _suffix(a.get("memory_id")),
        "source_session_id": a.get("session_id"),
        "source_session_date": a.get("session_date"),
        "segment": a.get("segment"),
        "similarity": a.get("similarity"),
        "authority": a.get("authority"),
        "outcome_validated": a.get("outcome_validated"),
        "source_model": a.get("source_model"),
        "levels_withheld": a.get("levels_withheld"),
        "market_regime": a.get("market_regime"),
        "dominant_direction": a.get("dominant_direction"),
        "embedding_version": a.get("embedding_version"),
    }
    if a.get("recurrence_count"):
        view.update({
            "recurrence_type": a.get("recurrence_type"),
            "recurrence_count": a.get("recurrence_count"),
            "occurrence_spans": a.get("occurrence_spans"),
            "grouped_memory_id_suffixes": [
                _suffix(m) for m in a.get("grouped_memory_ids") or []],
            "member_similarities": {
                _suffix(k): v for k, v in
                (a.get("member_similarities") or {}).items()},
            "member_representative_similarities": {
                _suffix(k): v for k, v in
                (a.get("member_representative_similarities") or {}).items()},
        })
    return view


# ── durable append ───────────────────────────────────────────────────────────
def write_record(record: dict) -> dict:
    """Append one telemetry record. Returns a status; NEVER raises.

    A telemetry-write failure degrades OBSERVABILITY, not safety: telemetry is
    not execution authority, and refusing to trade because a log file could not
    be opened would convert a reporting fault into a trading fault. It must
    still be loud -- the failure is returned and surfaced, never swallowed.
    """
    path = telemetry_path(record.get("session_id") or "UNKNOWN")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return {"ok": True, "path": path}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{WRITE_FAILED}: {exc}", "path": path}


# ── session accumulator ──────────────────────────────────────────────────────
class RetrievalTelemetrySession:
    """Per-scan emission plus a machine-countable session summary."""

    def __init__(self, session_id: str, instrument: str = "MNQ",
                 contract: str = "") -> None:
        self.session_id = session_id
        self.instrument = instrument
        self.contract = contract
        self.records: list = []
        self.write_failures: list = []
        self._previous_enabled = None

    def record_scan(self, *, scan_id: str, result: dict, startup_state: dict,
                    duration_ms: float = None, now_et: datetime = None,
                    persist: bool = True) -> dict:
        rec = build_record(session_id=self.session_id, scan_id=scan_id,
                           instrument=self.instrument, contract=self.contract,
                           result=result, startup_state=startup_state,
                           duration_ms=duration_ms, now_et=now_et)
        enabled = rec["retrieval_enabled"]
        if self._previous_enabled is not None and enabled != self._previous_enabled:
            rec["retrieval_state_transition"] = (
                "disabled_to_enabled" if enabled else "enabled_to_disabled")
        else:
            rec["retrieval_state_transition"] = None
        self._previous_enabled = enabled

        if persist:
            status = write_record(rec)
            rec["telemetry_write_ok"] = status["ok"]
            if not status["ok"]:
                rec["telemetry_write_error"] = status["error"]
                self.write_failures.append(status["error"])
        self.records.append(rec)
        return rec

    def summary(self) -> dict:
        recs = self.records
        reasons: dict = {}
        for r in recs:
            for k, v in (r.get("contradiction_reason_counts") or {}).items():
                reasons[k] = reasons.get(k, 0) + v
        memory_ids, sessions, authorities = set(), set(), set()
        for r in recs:
            for a in r["returned_analogs"]:
                memory_ids.add(a["memory_id_suffix"])
                if a.get("source_session_id"):
                    sessions.add(a["source_session_id"])
                authorities.add(a.get("authority"))
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "total_scans": len(recs),
            "retrieval_enabled_scans": sum(1 for r in recs if r["retrieval_enabled"]),
            "retrieval_disabled_scans": sum(1 for r in recs
                                            if not r["retrieval_enabled"]),
            "retrieval_state_transitions": [
                {"scan_id": r["scan_id"], "transition": r["retrieval_state_transition"]}
                for r in recs if r.get("retrieval_state_transition")],
            "scans_with_analogs": sum(1 for r in recs if r["returned_analog_count"]),
            "scans_without_analogs": sum(1 for r in recs
                                         if not r["returned_analog_count"]),
            "incomplete_query_scans": sum(1 for r in recs
                                          if not r["query_complete"]),
            "retrieval_error_scans": sum(1 for r in recs if r["retrieval_error"]),
            "total_analog_presentations": sum(r["returned_analog_count"]
                                              for r in recs),
            "unique_memory_ids_retrieved": len(memory_ids),
            "unique_source_sessions_retrieved": sorted(sessions),
            "semantic_recurrence_groups_presented": sum(
                r["semantic_recurrence_groups"] for r in recs),
            "exact_recurrence_groups_presented": sum(
                r["exact_recurrence_groups"] for r in recs),
            "recurrence_members_collapsed": sum(
                r["recurrence_members_collapsed"] for r in recs),
            "total_contradiction_gated_records": sum(
                r["contradiction_gated_count"] for r in recs),
            "contradiction_reason_counts": reasons,
            "session_cap_exclusions": sum(r["session_cap_excluded_count"]
                                          for r in recs),
            "levels_withheld_presentations": sum(
                1 for r in recs for a in r["returned_analogs"]
                if a.get("levels_withheld")),
            "authority_values_seen": sorted(a for a in authorities if a),
            "telemetry_write_failures": len(self.write_failures),
            "degraded_observability": bool(self.write_failures),
        }
