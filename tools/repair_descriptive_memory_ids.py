"""Re-derive descriptive memory ids that the v2.2 migration left stale.

REPAIR-V2_2-DESCRIPTIVE-MEMORY-IDENTITY (2026-08-07).

`memory_id` hashes the schema version, deliberately: identical inputs must
collide so a second authoring is recognised as a repeat rather than appended as
a second version of the same moment.

The v2.1 -> v2.2 migration re-embedded every record and set `schema_version` to
`descriptive.v2.2`, but carried the old ids across unchanged. Each live record
therefore asserts an identity it can no longer reproduce from its own fields,
and the collision that makes re-authoring safe cannot happen: re-authoring
PROD-20260806 today mints ten different ids and would append ten duplicates of
observations already held.

The fix is to re-derive the ids, NOT to drop the schema version from identity.
Identity doctrine is preserved; the stale values are corrected to match it.

Nothing semantic moves. Only `memory_id` changes, and the old -> new mapping is
written to a durable ledger so historical references stay resolvable. DRY RUN
BY DEFAULT.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_retrieval import descriptive_memory as DM   # noqa: E402
from ai_retrieval import vector_store               # noqa: E402

LEDGER_DIR = os.path.join("data", "replay_sessions", "_migrations",
                          "descriptive.v2.2-memory-id-repair")
REASON = "V2_1_TO_V2_2_MIGRATION_PRESERVED_STALE_ID"

#: Everything except the identity pointer must survive byte-identical.
MUTABLE_FIELDS = {"memory_id", "content_digest"}


def canonical_id(record: dict) -> str:
    """The id this record's OWN current fields derive."""
    return DM.memory_id(
        session_id=record["session_id"], instrument=record["instrument"],
        contract=record["contract"], segment_start=record["segment_start"],
        segment_end=record["segment_end"],
        source_artifact_digest=record["source_artifact_digest"])


def repair(record: dict) -> tuple:
    """Returns (new_record, old_id, new_id, semantic_changes)."""
    out = copy.deepcopy(record)
    old_id = record["memory_id"]
    new_id = canonical_id(record)
    out["memory_id"] = new_id
    out["content_digest"] = DM.content_digest(out)
    semantic = sorted(
        field for field in set(record) | set(out)
        if field not in MUTABLE_FIELDS
        and json.dumps(record.get(field), sort_keys=True, default=str)
        != json.dumps(out.get(field), sort_keys=True, default=str))
    return out, old_id, new_id, semantic


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit-migration", action="store_true")
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args(argv)

    path = vector_store._store_path()
    raw = open(path, "rb").read() if os.path.exists(path) else b""
    live = vector_store.load_records()

    print("=" * 86)
    print("  DESCRIPTIVE MEMORY ID REPAIR -- "
          + ("COMMIT" if args.commit_migration else "DRY RUN"))
    print("=" * 86)
    print(f"  store            : {path}")
    print(f"  records          : {len(live)}")
    print(f"  bytes            : {len(raw)}")
    print(f"  sha256 before    : {hashlib.sha256(raw).hexdigest()}")
    print()

    already = [r for r in live if r["memory_id"] == canonical_id(r)]
    if len(already) == len(live) and live:
        print(f"  ALREADY_CANONICAL_UNCHANGED -- all {len(live)} ids reproduce "
              f"from their own fields; 0 writes")
        return 0

    repaired, mapping, semantic_changes = [], [], 0
    print(f"  {'SEGMENT':22} {'OLD':30} {'NEW':30} SEMANTIC")
    for record in live:
        out, old_id, new_id, semantic = repair(record)
        semantic_changes += bool(semantic)
        repaired.append(out)
        mapping.append({
            "old_memory_id": old_id, "new_memory_id": new_id,
            "source_session": record["session_id"],
            "session_date": record["session_date"],
            "instrument": record["instrument"], "contract": record["contract"],
            "segment_start": record["segment_start"],
            "segment_end": record["segment_end"],
            "schema_version": record["schema_version"],
            "reason": REASON,
            "changed": old_id != new_id})
        print(f"  {record['segment_start']}-{record['segment_end']}  "
              f"{old_id:30} {new_id:30} "
              f"{semantic if semantic else 'none'}")

    old_ids = {m["old_memory_id"] for m in mapping}
    new_ids = {m["new_memory_id"] for m in mapping}
    collisions = len(mapping) - len(new_ids)
    print()
    print(f"  source records        : {len(live)}")
    print(f"  target records        : {len(repaired)}")
    print(f"  unique old ids        : {len(old_ids)}")
    print(f"  unique new ids        : {len(new_ids)}")
    print(f"  new-id collisions     : {collisions}")
    print(f"  ids changed           : {sum(1 for m in mapping if m['changed'])}")
    print(f"  semantic changes      : {semantic_changes}")

    # Prove the untouchables are untouched, field by field, across the batch.
    guarded = ("session_id", "session_date", "instrument", "contract",
               "segment_start", "segment_end", "scan_count", "authority",
               "outcome_validated", "recommendation_authority",
               "execution_authority", "feature_vector", "embedding_version",
               "embedding_dimensions", "embedding_manifest_fingerprint",
               "market_regime", "volatility_state", "delivery_state",
               "liquidity_state", "structure_state", "direction_distribution",
               "provenance", "source_artifact_digest", "schema_version")
    drift = [(o["memory_id"], f) for o, n in zip(live, repaired) for f in guarded
             if json.dumps(o.get(f), sort_keys=True, default=str)
             != json.dumps(n.get(f), sort_keys=True, default=str)]
    print(f"  guarded-field drift   : {len(drift)}  {drift[:3] if drift else ''}")

    if collisions or semantic_changes or drift:
        print("\n  REFUSED: migration is not clean; nothing written")
        return 3

    os.makedirs(LEDGER_DIR, exist_ok=True)
    ledger = {
        "schema_version": "descriptive_memory_id_repair.v1",
        "reason": REASON,
        "explanation": ("the v2.1 -> v2.2 migration re-embedded every record "
                        "and updated schema_version but preserved ids derived "
                        "under descriptive.v2.1; memory_id hashes the schema "
                        "version, so the stored ids could no longer be "
                        "reproduced from the records' own fields"),
        "identity_fields": ["schema_version", "session_id", "instrument",
                            "contract", "segment_start", "segment_end",
                            "source_artifact_digest"],
        "schema_version_in_identity": True,
        "records": len(mapping), "mappings": mapping,
        "store_sha256_before": hashlib.sha256(raw).hexdigest(),
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "historical_evidence_note": (
            "session artifacts are NOT rewritten. A runtime record that named "
            "an old id keeps naming it; this ledger resolves it forward."),
    }
    ledger["mapping_sha256"] = hashlib.sha256(json.dumps(
        mapping, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    if not args.commit_migration:
        out_path = os.path.join(LEDGER_DIR, "PROPOSED_mapping.json")
        json.dump(ledger, open(out_path, "w", encoding="utf-8"), indent=1,
                  default=str)
        print(f"\n  DRY RUN -- proposal written to {out_path}")
        print(f"  mapping sha256        : {ledger['mapping_sha256']}")
        print(f"  live store UNCHANGED  : {len(vector_store.load_records())} records")
        return 0

    if not args.approve:
        print("\n  REFUSED: --commit-migration requires --approve")
        return 2

    tmp = path + ".repair.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for record in repaired:
            fh.write(json.dumps(record, default=str) + "\n")
    os.replace(tmp, path)

    after = open(path, "rb").read()
    ledger["store_sha256_after"] = hashlib.sha256(after).hexdigest()
    json.dump(ledger, open(os.path.join(LEDGER_DIR, "mapping.json"), "w",
                           encoding="utf-8"), indent=1, default=str)
    print(f"\n  REPAIRED {len(repaired)} ids in place")
    print(f"  sha256 after          : {ledger['store_sha256_after']}")
    print(f"  mapping sha256        : {ledger['mapping_sha256']}")
    print(f"  ledger                : {LEDGER_DIR}/mapping.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
