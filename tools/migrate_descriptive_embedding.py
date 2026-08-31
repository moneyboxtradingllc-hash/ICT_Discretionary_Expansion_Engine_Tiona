"""Deterministic representation migration for descriptive memory.

REPAIR-RETRIEVAL-MARKET-NORMALIZATION (2026-08-07).

The delivery vocabulary was corrected against its authoritative producer
(`shared_market_context._delivery`, not `po3_engine._po3_alignment`), and the
retrieval liquidity normaliser was repaired. Both change the feature space, so
the embedding version moved and records written in the old space can no longer
be ranked in the new one.

This is a REPRESENTATION migration, not new learning. It re-embeds already
approved observations into the corrected space. Their factual content,
authority, provenance and session identity are preserved exactly; only
representation-dependent fields change.

DRY RUN BY DEFAULT. The live corpus is never touched without --commit-migration
AND --approve.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_retrieval import descriptive_memory as DM   # noqa: E402
from ai_retrieval import embedding_v2 as EV2        # noqa: E402
from ai_retrieval import vector_store               # noqa: E402

#: Fields that MAY change. Everything else must be byte-identical.
REPRESENTATION_FIELDS = {
    "schema_version", "embedding_version", "embedding_dimensions",
    "embedding_manifest_fingerprint", "feature_vector", "feature_dimensions",
    "feature_vector_fingerprint", "embedding_notes", "content_digest",
}


def migrate(record: dict) -> tuple:
    """Re-embed one record. Returns (migrated, changed_fields, semantic_changes)."""
    out = copy.deepcopy(record)
    out["schema_version"] = DM.SCHEMA_VERSION
    vector, notes = EV2.embed_v2(out)
    out["embedding_version"] = EV2.EMBEDDING_VERSION
    out["embedding_dimensions"] = EV2.EMBED_DIM_V2
    out["embedding_manifest_fingerprint"] = EV2.manifest_fingerprint()
    out["feature_vector"] = vector
    out["feature_dimensions"] = len(vector)
    out["feature_vector_fingerprint"] = EV2.vector_fingerprint(vector)
    out["embedding_notes"] = notes
    out["content_digest"] = DM.content_digest(out)

    changed = {k for k in set(record) | set(out)
               if json.dumps(record.get(k), sort_keys=True, default=str)
               != json.dumps(out.get(k), sort_keys=True, default=str)}
    semantic = sorted(changed - REPRESENTATION_FIELDS)
    return out, sorted(changed), semantic


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit-migration", action="store_true")
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args(argv)

    live = vector_store.load_records()
    path = vector_store._store_path()
    raw = open(path, "rb").read() if os.path.exists(path) else b""
    print("=" * 84)
    print("  DESCRIPTIVE EMBEDDING MIGRATION -- DRY RUN"
          if not args.commit_migration else
          "  DESCRIPTIVE EMBEDDING MIGRATION -- COMMIT")
    print("=" * 84)
    print(f"  live store        : {path}")
    print(f"  records           : {len(live)}")
    print(f"  bytes             : {len(raw)}")
    print(f"  sha256            : {hashlib.sha256(raw).hexdigest()}")
    print(f"  target version    : {EV2.EMBEDDING_VERSION} ({EV2.EMBED_DIM_V2} dims)")
    print(f"  target manifest   : {EV2.manifest_fingerprint()}")
    print()

    migrated, rejected, semantic_changes = [], [], 0
    for rec in live:
        try:
            out, changed, semantic = migrate(rec)
        except Exception as exc:  # noqa: BLE001
            rejected.append((rec.get("memory_id"), f"{type(exc).__name__}: {exc}"))
            continue
        ok, reasons = DM.validate_descriptive_record(out)
        if not ok:
            rejected.append((rec.get("memory_id"), reasons))
            continue
        if semantic:
            semantic_changes += 1
        migrated.append(out)
        print(f"  {rec['segment_start']}-{rec['segment_end']} "
              f"...{str(rec['memory_id'])[-8:]}  "
              f"{rec.get('embedding_dimensions')}d -> {out['embedding_dimensions']}d  "
              f"delivery={out['delivery_state']:28} liq={out['liquidity_state']:16}"
              f"{'  SEMANTIC CHANGE: ' + str(semantic) if semantic else ''}")

    print()
    print(f"  old count             : {len(live)}")
    print(f"  migrated proposals    : {len(migrated)}")
    print(f"  rejected              : {len(rejected)}")
    for mid, why in rejected:
        print(f"      ...{str(mid)[-8:]}: {why}")
    print(f"  semantic-content changes : {semantic_changes}")
    print()
    # Prove identity/factual preservation across the whole batch.
    preserved = ("session_id", "session_date", "instrument", "contract",
                 "segment_start", "segment_end", "scan_count", "memory_id",
                 "authority", "outcome_validated", "recommendation_authority",
                 "execution_authority", "provenance", "source_artifact_digest",
                 "direction_distribution", "market_regime", "volatility_state")
    drift = [(o["memory_id"], f) for o, n in zip(live, migrated) for f in preserved
             if json.dumps(o.get(f), sort_keys=True, default=str)
             != json.dumps(n.get(f), sort_keys=True, default=str)]
    print(f"  preserved-field drift : {len(drift)}  {drift[:3] if drift else ''}")

    if not args.commit_migration:
        out_dir = os.path.join("data", "replay_sessions", "_migrations",
                               EV2.EMBEDDING_VERSION)
        os.makedirs(out_dir, exist_ok=True)
        for m in migrated:
            json.dump(m, open(os.path.join(
                out_dir, f"{m['memory_id'].replace(':', '_')}.json"), "w",
                encoding="utf-8"), indent=1, default=str, sort_keys=True)
        print(f"\n  DRY RUN -- proposals written to {out_dir}")
        print(f"  live store UNCHANGED: {len(vector_store.load_records())} records")
        return 0

    if not args.approve:
        print("\n  REFUSED: --commit-migration requires --approve")
        return 2
    if rejected or semantic_changes or drift:
        print("\n  REFUSED: migration is not clean; nothing written")
        return 3
    with open(path, "w", encoding="utf-8") as fh:
        for m in migrated:
            fh.write(json.dumps(m, default=str) + "\n")
    print(f"\n  MIGRATED {len(migrated)} records in place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
