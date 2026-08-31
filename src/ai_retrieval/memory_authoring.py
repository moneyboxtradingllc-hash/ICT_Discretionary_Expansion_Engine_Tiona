"""Post-session authoring of descriptive memory. Never during a session.

BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).

Why authoring is post-session only: if the organism wrote memory during the
session it would retrieve its own developing conclusions an hour later and read
them as independent precedent. Ten scans agreeing with each other is one opinion
repeated, and the feedback loop would be invisible from inside the prompt. So
nothing is authored until the window has closed, the launcher has finished, and
the account is proven flat and reconciled.

Nothing here decides that a session went well. It decides only whether the
session ENDED in a state that can be described truthfully.
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
import os

from ai_retrieval import descriptive_memory as DM
from ai_retrieval import session_brain_contract as SBC
from ai_retrieval import session_closure as SC
from ai_retrieval import session_segmentation as SEG
from ai_retrieval import vector_store

AUTHORED = "AUTHORED"
DEFERRED = "MEMORY_AUTHORING_DEFERRED"
ALREADY_AUTHORED = "ALREADY_AUTHORED_UNCHANGED"
CONFLICT_REFUSED = "MEMORY_CONFLICT_REFUSED"
DRY_RUN = "DRY_RUN_ONLY"

#: The first deployment does not write unattended. The launcher exiting is not
#: consent; a human states that the session is describable.
OPERATOR_APPROVAL_REQUIRED = True

#: A non-final phase that was stopped externally does not by itself defer the
#: session, PROVIDED the final phase terminated cleanly and the account was
#: afterwards proven flat with a zero delta. PROD-20260806 is exactly this case:
#: phase A was killed by an external task manager while flat, phase C then ran
#: to window close with exit 0. The anomaly is recorded in provenance rather
#: than used to erase a session whose end state is fully evidenced. What DOES
#: defer is an unproven end state.
REQUIRE_EVERY_PHASE_CLEAN = False


class AuthoringRefused(RuntimeError):
    """Preconditions were not met. No partial write ever occurs."""


# ── preconditions ────────────────────────────────────────────────────────────
def check_session_closed(archive_path: str) -> dict:
    """Prove the session ended in a describable state. Reads only the archive.

    Two legitimate ways to end. A launcher that self-terminates writes its own
    closure artifacts and is checked below, unchanged. A session the operator
    stops writes none of them -- not because its end state is unknown, but
    because nothing was left running to record it -- and proves the same
    invariants through a post-session attestation instead.

    The classes never blur: an attestation is consulted ONLY when the native
    artifacts are absent, and `session_closure` refuses any attestation that
    claims to be a native close.
    """
    reasons, anomalies = [], []

    native_exits = os.path.join(archive_path, "launcher", "exit_statuses.json")
    attestation_path = os.path.join(archive_path, "closure",
                                    "session_closure_attestation.json")
    if not os.path.exists(native_exits) and os.path.exists(attestation_path):
        return _check_attested_close(archive_path, attestation_path)

    def _load(rel):
        path = os.path.join(archive_path, rel)
        try:
            return json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reasons.append(f"unreadable:{rel}")
            return None

    manifest = _load("manifest.json")
    exits = _load(os.path.join("launcher", "exit_statuses.json"))
    zero = _load(os.path.join("execution", "session_zero_state.json"))
    recon = _load(os.path.join("account", "reconciliation_redacted.json"))
    shutdown = _load(os.path.join("launcher", "shutdown_evidence.json"))

    phases = (exits or {}).get("phases") or []
    if not phases:
        reasons.append("no_phase_exit_evidence")
    else:
        for phase in phases[:-1]:
            if "CLEAN" not in str(phase.get("exit", "")).upper():
                anomalies.append({"phase": phase.get("phase"),
                                  "exit": phase.get("exit")})
        final = phases[-1]
        if final.get("exit_code") != 0:
            reasons.append(f"final_phase_exit_code:{final.get('exit_code')}")
        if "CLEAN" not in str(final.get("exit", "")).upper():
            reasons.append(f"final_phase_unclean:{final.get('exit')}")
        if REQUIRE_EVERY_PHASE_CLEAN and anomalies:
            reasons.append("non_final_phase_unclean")

    final_state = (shutdown or {}).get("phase_c_final_state") or {}
    if final_state.get("flat") is not True:
        reasons.append("launcher_did_not_prove_flat")

    if recon is None:
        reasons.append("no_account_reconciliation")
    else:
        if recon.get("positions") != 0:
            reasons.append(f"open_positions:{recon.get('positions')}")
        if recon.get("working_orders") != 0:
            reasons.append(f"working_orders:{recon.get('working_orders')}")

    if zero is None:
        reasons.append("no_execution_state")
    else:
        unresolved = {k: v for k, v in zero.items()
                      if k in ("execution_tokens",) and v}
        # An open token means an entry was authorised and its outcome is not
        # established. That is precisely an unresolved execution context.
        if unresolved:
            reasons.append(f"unresolved_execution_context:{sorted(unresolved)}")
        if zero.get("fills", 0) != zero.get("round_trips", 0):
            reasons.append("fills_and_round_trips_disagree")

    if manifest is None:
        reasons.append("no_manifest")

    return {"ok": not reasons, "reasons": reasons,
            "phase_exit_anomalies": anomalies,
            "closure_type": SC.NATIVE_LAUNCHER_CLOSE,
            "session_id": (manifest or {}).get("session_id"),
            "session_date": (manifest or {}).get("session_date"),
            "instrument": (manifest or {}).get("instrument"),
            "contract": (manifest or {}).get("active_contract"),
            "final_head": (manifest or {}).get("final_head")}


def _completeness_from(archive_path: str) -> dict:
    """Source-session completeness recorded by a verified projection manifest."""
    try:
        manifest = json.load(open(os.path.join(archive_path,
                                               "projection_manifest.json"),
                                  encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return manifest.get("source_session_completeness") or {}


def _check_attested_close(archive_path: str, attestation_path: str) -> dict:
    """Closure for an operator-terminated session, via post-session attestation.

    Every load-bearing invariant must be proven from durable evidence. The
    attestation cannot lower the bar -- it can only meet it by a different
    route, and `session_closure.closure_ok` decides whether it did.
    """
    reasons = []
    try:
        att = json.load(open(attestation_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "reasons": [f"unreadable_attestation:{exc}"],
                "phase_exit_anomalies": [], "closure_type": None}

    verdict = SC.closure_ok(att)
    reasons.extend(verdict["reasons"])

    manifest_path = os.path.join(archive_path, "manifest.json")
    manifest = None
    try:
        manifest = json.load(open(manifest_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reasons.append("no_manifest")
    if manifest and att.get("session_id") != manifest.get("session_id"):
        reasons.append("attestation_session_mismatch")
    if manifest and att.get("runtime_head") != manifest.get("runtime_head"):
        reasons.append("attestation_runtime_head_mismatch")

    index = {}
    try:
        index = json.load(open(os.path.join(archive_path, "scans",
                                            "scan_index.json"), encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    identity = index.get("contract_identity") or {}
    contract = identity.get("contract") or (manifest or {}).get("active_contract")
    if not contract:
        reasons.append("contract_identity_unrecoverable")

    return {
        "ok": not reasons, "reasons": reasons, "phase_exit_anomalies": [],
        "closure_type": att.get("closure_type"),
        "closure_invariants": verdict["invariants"],
        "closure_attestation": {
            "termination_reason": att.get("termination_reason"),
            "observation_start_et": att.get("observation_start_et"),
            "observation_end_et": att.get("observation_end_et"),
            "configured_window_completed": att.get("configured_window_completed"),
            "attestation_created_by": att.get("attestation_created_by"),
            "attestation_created_at": att.get("attestation_created_at")},
        "contract_identity": identity,
        "session_id": att.get("session_id"),
        "session_date": att.get("session_date"),
        "instrument": (manifest or {}).get("instrument") or "MNQ",
        "contract": contract,
        "final_head": att.get("runtime_head")}



def _last_present(scans: list, key: str) -> dict:
    """The most recent NON-EMPTY protected level in the segment.

    Always returns the normalised four-key shape, so a record never carries a
    scalar where another carries a dict.
    """
    empty = {"level": None, "timeframe": None, "basis": None,
             "registered_at": None}
    for scan in reversed(scans):
        block = scan.get(key) or {}
        if block.get("level") is not None:
            return {k: block.get(k) for k in empty}
    return dict(empty)


def _structure_label(evidence: dict) -> str:
    """Display string for structure evidence. One derivation, one answer."""
    if evidence.get("quiet"):
        return "witness_quiet"
    return f"witness_bos_{evidence['bos_count']}_mss_{evidence['mss_count']}"


def _segment_structure(scans: list) -> dict:
    """Segment-level BOS/MSS evidence from the authoritative witness flags.

    Read per scan by `embedding_v2.structure_evidence` and averaged, then
    rounded to the nearest whole event. A scan whose witness block is missing
    entirely is skipped rather than counted as quiet -- v1's display string
    could not tell "no events" from "no evidence".
    """
    from ai_retrieval import embedding_v2 as EV2
    per_scan = []
    for scan in scans:
        try:
            per_scan.append(EV2.structure_evidence(scan.get("structure_witness")))
        except EV2.EmbeddingError:
            continue
    if not per_scan:
        raise AuthoringRefused(
            "structure_witness_absent for every scan in a segment; refusing to "
            "encode missing evidence as quiet structure")
    bos = round(sum(e["bos_count"] for e in per_scan) / len(per_scan))
    mss = round(sum(e["mss_count"] for e in per_scan) / len(per_scan))
    # UNIT 3 — the segment may not re-manufacture the authority its members
    # lack. Averaging counts to zero says nothing about whether the scans that
    # produced those zeros could see. Weakest member wins, exactly as within a
    # single scan.
    caps = {e.get("structure_capability") or "UNKNOWN" for e in per_scan}
    cap = ("UNKNOWN" if "UNKNOWN" in caps
           else "UNEVALUABLE_EVIDENCE" if "UNEVALUABLE_EVIDENCE" in caps
           else "DETECTOR_EVALUATED")
    return {"bos_count": bos, "mss_count": mss,
            "quiet": bool(bos == 0 and mss == 0 and cap == "DETECTOR_EVALUATED"),
            "structure_capability": cap,
            "scans_with_witness": len(per_scan), "scans_in_segment": len(scans),
            "parser": per_scan[0]["parser"]}

# ── building the proposed records ────────────────────────────────────────────
def build_records(archive_path: str, *, now_iso: str = None) -> dict:
    """Segment the archived session into proposed descriptive records.

    Pure: reads the archive, writes nothing.
    """
    from ai_brain.production_model import brain_contract_fingerprint

    closed = check_session_closed(archive_path)
    if not closed["ok"]:
        return {"status": DEFERRED, "reasons": closed["reasons"],
                "records": [], "preconditions": closed}

    read = SEG.load_session_observations(archive_path)
    cut = SEG.cut_segments(read["observations"])
    now = now_iso or _dt.datetime.now(_dt.timezone.utc).isoformat()
    # WHO PRODUCED THE REASONING vs WHAT REPRESENTED IT. These were one field,
    # stamped from current code, so re-authoring a historical session relabelled
    # it with today's contract. The source contract comes from session evidence
    # and never falls back to the running code.
    source_contract = SBC.resolve_source_brain_contract(
        archive_path, closed.get("session_id") or read.get("session_id") or "")
    suffix = source_contract["source_brain_contract_fingerprint_suffix"]

    # Governance provenance, identical on every record of a session: how it
    # closed, how its contract identity was established, and how much of the
    # configured window it actually observed.
    identity = closed.get("contract_identity") or {}
    attestation = closed.get("closure_attestation") or {}
    completeness = (read.get("source_session_completeness")
                    or _completeness_from(archive_path) or {})
    session_provenance = {
        "closure_type": closed.get("closure_type"),
        **source_contract,
        # The representation side, explicitly labelled so it can never be read
        # as the contract that produced the historical narrative.
        "authoring_contract_fingerprint": brain_contract_fingerprint(),
        "authoring_contract_note": (
            "the contract of the code that BUILT this record, not the contract "
            "that produced the observed reasoning"),
        "contract_identity_provenance": (
            identity.get("classification") or "ORIGINAL_PER_SCAN"),
        "per_scan_contract_original": identity.get(
            "per_scan_contract_original", "PRESENT"),
    }
    if identity.get("identity_recovery_provenance"):
        session_provenance["identity_recovery_sources"] = [
            {k: v for k, v in src.items() if k != "sha256"}
            for src in identity["identity_recovery_provenance"]]
    if attestation:
        session_provenance.update({
            "termination_reason": attestation.get("termination_reason"),
            "observation_window_start_et": attestation.get("observation_start_et"),
            "observation_window_end_et": attestation.get("observation_end_et"),
            "configured_window_completed": attestation.get(
                "configured_window_completed"),
            "source_session_completion": (
                "OPERATOR_TERMINATED"
                if attestation.get("configured_window_completed") is False
                else "COMPLETED"),
            # Stated explicitly so it cannot be inferred the other way round.
            "partial_observation_claim": (
                "NO OBSERVATION AFTER observation_window_end_et. This is NOT a "
                "claim that no opportunities existed after that time."),
        })
    elif completeness:
        session_provenance.update(completeness)

    records, rejected = [], []
    for seg in cut["segments"]:
        scans = seg["scans"]
        directions = collections.Counter(s["narrative_direction"] for s in scans)
        actions = collections.Counter(s["action"] for s in scans)
        models = sorted({s["source_model"] for s in scans})
        contracts = sorted({s["contract"] for s in scans})
        phases = sorted({s["code_phase"] for s in scans if s["code_phase"]})
        candidate_count = 0          # candidates are counted from the archive
        record = DM.make_descriptive_record(
            session_id=closed["session_id"] or read["session_id"],
            session_date=closed["session_date"],
            instrument=closed["instrument"],
            contract=contracts[0] if len(contracts) == 1 else ",".join(contracts),
            segment_start=scans[0]["et"], segment_end=scans[-1]["et"],
            scan_count=len(scans),
            source_model=models[0] if len(models) == 1 else ",".join(models),
            brain_contract_fingerprint_suffix=suffix,
            market_regime=SEG._dominant([s["market_regime"] for s in scans]),
            volatility_state=SEG._dominant([s["volatility_state"] for s in scans]),
            session_phase=SEG._dominant([s["session_phase"] for s in scans]),
            narrative_phase=SEG._dominant([s["narrative_phase"] for s in scans]),
            delivery_state=SEG._dominant([s["delivery_state"] for s in scans]),
            # Derived from the SAME evidence the vector reads. Taking the mode
            # of the per-scan display strings while the vector reads the segment
            # MEAN let the two disagree: August 6 #3 and #4 both displayed
            # "witness_quiet" while their embedded evidence carried bos=1.
            structure_state=_structure_label(_segment_structure(scans)),
            # V2: the vector reads THIS, not the display string. Counts are the
            # segment MEAN, rounded -- a segment is a stretch of market, not a
            # single scan, and the modal count would discard every transition
            # inside it.
            structure_evidence=_segment_structure(scans),
            liquidity_state=SEG._dominant([s["liquidity_state"] for s in scans]),
            protected_high=_last_present(scans, "protected_high"),
            protected_low=_last_present(scans, "protected_low"),
            active_draw_present=any(s["draw_present"] for s in scans),
            # Majority over the segment: exhaustion is a condition that holds
            # for a stretch, not an event that fires once.
            exhaustion_present=(sum(1 for s in scans if s.get("exhaustion_present"))
                                * 2 > len(scans)),
            direction_distribution=dict(directions),
            action_distribution=dict(actions),
            dominant_direction=SEG._dominant([s["narrative_direction"] for s in scans]),
            dominant_action=SEG._dominant([s["action"] for s in scans]),
            phase_confidence_summary=SEG._confidence_summary(
                [s["phase_confidence"] for s in scans]),
            session_provenance=session_provenance,
            candidate_count=candidate_count, trade_count=0,
            no_candidate_reasons=SEG.no_candidate_reasons(scans, candidate_count),
            source_artifact_ids=[s["artifact_id"] for s in scans],
            source_artifact_digest=SEG.segment_digest(scans),
            created_at=now, code_phases=phases)
        ok, reasons = DM.validate_descriptive_record(record)
        (records if ok else rejected).append(
            record if ok else {"memory_id": record.get("memory_id"),
                               "reasons": reasons})

    return {"status": DRY_RUN, "records": records, "rejected": rejected,
            "tier": cut.get("tier"), "tier_keys": list(cut.get("tier_keys") or []),
            "raw_runs": cut.get("raw_runs"),
            "eligible_scans": len(read["observations"]),
            "total_scans": read["total_scans"],
            "excluded": read["excluded"], "preconditions": closed}


# ── committing ───────────────────────────────────────────────────────────────
def _existing_by_id() -> dict:
    out = {}
    for rec in vector_store.load_records():
        mid = rec.get("memory_id")
        if mid:
            out[mid] = rec
    return out


def commit_records(records: list, *, approved: bool = False) -> dict:
    """Write proposed records to the live store. Idempotent, never silent.

    `approved` is the operator's statement, not the launcher's. Without it this
    refuses, because "the process exited" is not "a human agreed this session is
    describable".
    """
    if OPERATOR_APPROVAL_REQUIRED and not approved:
        raise AuthoringRefused("OPERATOR_APPROVAL_REQUIRED: refusing to write "
                               "descriptive memory without explicit approval")
    existing = _existing_by_id()
    written, unchanged, conflicts = [], [], []
    for rec in records:
        ok, reasons = DM.validate_descriptive_record(rec)
        if not ok:
            raise AuthoringRefused(f"invalid record {rec.get('memory_id')}: {reasons}")
        mid = rec["memory_id"]
        prior = existing.get(mid)
        if prior is None:
            written.append(rec)
        elif prior.get("content_digest") == rec.get("content_digest"):
            unchanged.append(mid)
        else:
            conflicts.append({"memory_id": mid,
                              "stored_digest": prior.get("content_digest"),
                              "proposed_digest": rec.get("content_digest")})
    if conflicts:
        # Refuse the WHOLE batch. A partial write would leave the session half
        # described, and the operator would have to reconstruct which half.
        return {"status": CONFLICT_REFUSED, "conflicts": conflicts,
                "written": 0, "unchanged": len(unchanged)}
    for rec in written:
        vector_store.add_record(rec)
    status = AUTHORED if written else ALREADY_AUTHORED
    return {"status": status, "written": len(written),
            "unchanged": len(unchanged), "conflicts": []}


def write_proposed(records: list, out_dir: str, meta: dict = None) -> dict:
    """Dry-run output. Writes proposals to `out_dir`, never to the live store."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for rec in records:
        path = os.path.join(out_dir, f"{rec['memory_id'].replace(':', '_')}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1, default=str, sort_keys=True)
        paths.append(path)
    summary = os.path.join(out_dir, "PROPOSED_SUMMARY.json")
    with open(summary, "w", encoding="utf-8") as fh:
        json.dump({"proposed_count": len(records),
                   "memory_ids": [r["memory_id"] for r in records],
                   "authority": DM.AUTHORITY_LABEL if hasattr(DM, "AUTHORITY_LABEL")
                                else records[0]["authority"] if records else None,
                   "written_to_live_store": False,
                   **(meta or {})}, fh, indent=1, default=str)
    return {"paths": paths, "summary": summary}
