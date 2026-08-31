"""Replace leaked current-Brain-contract stamps with session-bound provenance.

BIND-HISTORICAL-BRAIN-CONTRACT-PROVENANCE (2026-08-07).

`build_records` stamped `brain_contract_fingerprint()` -- the contract of the
authoring code -- into `brain_contract_fingerprint_suffix`. PROD-20260806 ran
`gpt-5.6-luna`, yet its live records carry `33fc76`, a value from the Terra era,
present only because that was current when the records were authored. The field
claimed provenance it never had.

This migration re-derives every live record from its own sealed session archive
using the current authoring path, and keeps the result only if the market
content is byte-identical. What changes is the provenance: the source contract
now comes from session evidence (or is honestly UNRECORDED_AT_RUNTIME with the
runtime commit that pins it), and the authoring contract is recorded separately
and labelled as representation.

DRY RUN BY DEFAULT.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_retrieval import memory_authoring as MA    # noqa: E402
from ai_retrieval import vector_store              # noqa: E402

LEDGER_DIR = os.path.join("data", "replay_sessions", "_migrations",
                          "historical-brain-contract-provenance")

#: Market meaning. None of it may move.
SEMANTIC_FIELDS = (
    "session_id", "session_date", "instrument", "contract", "segment_start",
    "segment_end", "scan_count", "source_model", "market_regime",
    "volatility_state", "session_phase", "narrative_phase", "delivery_state",
    "structure_state", "structure_evidence", "liquidity_state",
    "active_draw_present", "exhaustion_present", "protected_high_level",
    "protected_low_level", "direction_distribution", "action_distribution",
    "dominant_direction", "dominant_action", "phase_confidence_summary",
    "candidate_count", "trade_count", "source_artifact_ids",
    "source_artifact_digest", "memory_id", "memory_type", "authority",
    "outcome_validated", "recommendation_authority", "execution_authority",
    "feature_vector", "embedding_version", "embedding_dimensions",
    "embedding_manifest_fingerprint", "schema_version",
)

#: session_id -> sealed archive that authored it.
ARCHIVES = {"PROD-20260806": os.path.join("data", "replay_sessions",
                                          "PROD-20260806")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit-migration", action="store_true")
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args(argv)

    path = vector_store._store_path()
    raw = open(path, "rb").read() if os.path.exists(path) else b""
    live = vector_store.load_records()

    print("=" * 88)
    print("  HISTORICAL BRAIN-CONTRACT PROVENANCE REPAIR -- "
          + ("COMMIT" if args.commit_migration else "DRY RUN"))
    print("=" * 88)
    print(f"  records       : {len(live)}")
    print(f"  sha256 before : {hashlib.sha256(raw).hexdigest()}")

    sessions = sorted({r["session_id"] for r in live})
    missing = [s for s in sessions if s not in ARCHIVES]
    if missing:
        print(f"\n  REFUSED: no sealed archive registered for {missing}; a "
              f"record whose source cannot be re-derived is not migrated")
        return 2

    rebuilt = {}
    for session in sessions:
        built = MA.build_records(ARCHIVES[session])
        if built["status"] == MA.DEFERRED:
            print(f"\n  REFUSED: {session} archive no longer closes: "
                  f"{built['reasons']}")
            return 3
        for record in built["records"]:
            rebuilt[record["memory_id"]] = record

    out, drift, changed = [], [], 0
    print(f"\n  {'SEGMENT':22} {'OLD SUFFIX':22} {'NEW SOURCE CONTRACT':22} RESOLUTION")
    for record in live:
        fresh = rebuilt.get(record["memory_id"])
        if fresh is None:
            print(f"\n  REFUSED: {record['memory_id']} has no counterpart in a "
                  f"re-derivation of its own archive")
            return 3
        moved = [f for f in SEMANTIC_FIELDS
                 if json.dumps(record.get(f), sort_keys=True, default=str)
                 != json.dumps(fresh.get(f), sort_keys=True, default=str)]
        drift.extend((record["memory_id"], f) for f in moved)
        merged = dict(fresh)
        # Bookkeeping stays with the original record: this is a provenance
        # correction, not a re-authoring, and the memory was not created today.
        for keep in ("created_at", "expires_at"):
            if keep in record:
                merged[keep] = record[keep]
        merged["content_digest"] = __import__(
            "ai_retrieval.descriptive_memory", fromlist=["x"]
        ).content_digest(merged)
        out.append(merged)
        changed += record.get("brain_contract_fingerprint_suffix") != \
            merged.get("brain_contract_fingerprint_suffix")
        prov = merged["provenance"]
        print(f"  {record['segment_start']}-{record['segment_end']}  "
              f"{str(record.get('brain_contract_fingerprint_suffix')):22} "
              f"{str(prov.get('source_brain_contract_fingerprint')):22} "
              f"{prov.get('source_brain_contract_resolution')}")

    print()
    print(f"  records in  : {len(live)}     records out : {len(out)}")
    print(f"  semantic drift (must be 0) : {len(drift)}  {drift[:3] if drift else ''}")
    print(f"  contract stamps corrected  : {changed}")
    if drift:
        print("\n  REFUSED: market content moved; nothing written")
        return 3
    if changed == 0:
        print("\n  ALREADY_SESSION_BOUND_UNCHANGED -- 0 writes")
        return 0

    ledger = {
        "schema_version": "historical_brain_contract_repair.v1",
        "reason": "AUTHORING_CODE_CONTRACT_LEAKED_INTO_HISTORICAL_PROVENANCE",
        "explanation": (
            "build_records stamped the CURRENT Brain contract into "
            "brain_contract_fingerprint_suffix, so re-authoring a historical "
            "session relabelled it with today's contract. PROD-20260806 ran "
            "gpt-5.6-luna but its records carried a Terra-era value."),
        "records": [{"memory_id": r["memory_id"],
                     "session_id": r["session_id"],
                     "segment_start": r["segment_start"],
                     "segment_end": r["segment_end"],
                     "old_brain_contract_suffix": o.get(
                         "brain_contract_fingerprint_suffix"),
                     "source_brain_contract_fingerprint": r["provenance"].get(
                         "source_brain_contract_fingerprint"),
                     "source_brain_contract_evidence": r["provenance"].get(
                         "source_brain_contract_evidence"),
                     "source_runtime_head": r["provenance"].get(
                         "source_runtime_head"),
                     "authoring_contract_fingerprint": r["provenance"].get(
                         "authoring_contract_fingerprint")}
                    for o, r in zip(live, out)],
        "store_sha256_before": hashlib.sha256(raw).hexdigest(),
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    if not args.commit_migration:
        os.makedirs(LEDGER_DIR, exist_ok=True)
        json.dump(ledger, open(os.path.join(LEDGER_DIR, "PROPOSED_mapping.json"),
                               "w", encoding="utf-8"), indent=1, default=str)
        print(f"\n  DRY RUN -- proposal written to {LEDGER_DIR}")
        print(f"  live store UNCHANGED : {len(vector_store.load_records())} records")
        return 0
    if not args.approve:
        print("\n  REFUSED: --commit-migration requires --approve")
        return 2

    tmp = path + ".contract.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for record in out:
            fh.write(json.dumps(record, default=str) + "\n")
    os.replace(tmp, path)
    ledger["store_sha256_after"] = hashlib.sha256(
        open(path, "rb").read()).hexdigest()
    os.makedirs(LEDGER_DIR, exist_ok=True)
    json.dump(ledger, open(os.path.join(LEDGER_DIR, "mapping.json"), "w",
                           encoding="utf-8"), indent=1, default=str)
    print(f"\n  REPAIRED {len(out)} records in place")
    print(f"  sha256 after : {ledger['store_sha256_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
