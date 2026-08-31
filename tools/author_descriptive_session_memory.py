"""Author descriptive session memory from a completed session archive.

BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).

    python tools/author_descriptive_session_memory.py \
        --session-id PROD-20260806 \
        --archive-path data/replay_sessions/PROD-20260806

Dry-run is the DEFAULT and is what happens when the flag is forgotten. Writing
to the live retrieval corpus requires --commit-memory AND --approve, because
"the launcher exited" is not consent and a forgotten flag must never be the
difference between analysing a session and permanently learning from it.

No doctrine value is entered by hand: the instrument, the contract, the segment
ceiling, the retention window and the authority label all come from the modules
that own them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_retrieval import descriptive_memory as DM          # noqa: E402
from ai_retrieval import memory_authoring as MA            # noqa: E402
from ai_retrieval import retrieval_contract as RC          # noqa: E402
from ai_retrieval import session_segmentation as SEG       # noqa: E402
from ai_retrieval import vector_store                      # noqa: E402
from doctrine.instrument_identity import PRODUCTION_INSTRUMENT  # noqa: E402


def _refuse(message: str) -> int:
    print(f"\nREFUSED: {message}\n")
    return 2


def verify_projection(path: str, session_id: str) -> tuple:
    """Fail closed. Every input must trace to sealed evidence or a labelled
    post-session recovery artifact, and the projection must be bound to THIS
    session, THIS archive and THIS runtime."""
    import hashlib
    try:
        manifest = json.load(open(os.path.join(path, "projection_manifest.json"),
                                  encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unreadable projection manifest: {exc}"
    if manifest.get("schema_version") != "memory_authoring_projection_manifest.v1":
        return False, "unknown projection manifest schema"
    if manifest.get("session_id") != session_id:
        return False, (f"projection is for {manifest.get('session_id')}, "
                       f"not {session_id}")

    source_archive = manifest.get("source_archive_path") or ""
    src_manifest = os.path.join(source_archive, "manifest.json")
    if not os.path.exists(src_manifest):
        return False, f"source archive missing: {source_archive}"
    have = hashlib.sha256(open(src_manifest, "rb").read()).hexdigest()
    if have != manifest.get("source_archive_manifest_sha256"):
        return False, "source archive manifest hash mismatch"
    src_meta = json.load(open(src_manifest, encoding="utf-8"))
    if src_meta.get("session_id") != session_id:
        return False, "source archive belongs to another session"
    if src_meta.get("runtime_head") != manifest.get("runtime_head"):
        return False, "runtime identity mismatch between archive and projection"

    allowed = {"COPY_BYTE_IDENTICAL", "NORMALIZE_LAYOUT_ONLY",
               "DERIVE_INDEX", "RECOVER_SESSION_METADATA"}
    files = manifest.get("files") or []
    if not files:
        return False, "projection manifest lists no files"
    for entry in files:
        op = entry.get("projection_operation")
        if op not in allowed:
            return False, f"undocumented projection operation: {op}"
        full = os.path.join(path, entry["projected_path"].replace("/", os.sep))
        if not os.path.exists(full):
            return False, f"projected file missing: {entry['projected_path']}"
        digest = hashlib.sha256(open(full, "rb").read()).hexdigest()
        if digest != entry.get("projected_sha256"):
            return False, f"projected file altered: {entry['projected_path']}"

    if not manifest.get("closure_attestation_sha256") and not os.path.exists(
            os.path.join(path, "launcher", "exit_statuses.json")):
        return False, "no closure evidence of either class"
    identity = manifest.get("contract_identity") or {}
    if not identity.get("contract"):
        return False, "contract identity unproven"
    return True, "verified"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--archive-path", required=True,
                    help="the authoritative completed-session source")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-write analysis (the default behaviour)")
    ap.add_argument("--commit-memory", action="store_true",
                    help="write to the live retrieval corpus")
    ap.add_argument("--approve", action="store_true",
                    help="operator approval; required with --commit-memory")
    ap.add_argument("--out-dir", default=None,
                    help="where dry-run proposals are written")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.archive_path):
        return _refuse(f"archive path not found: {args.archive_path}")

    # A source is either a NATIVE SESSION LAYOUT or a VERIFIED AUTHORING
    # PROJECTION -- never an arbitrary directory. The previous dry run reshaped
    # the archive in a scratchpad, which has no provenance and would let an
    # undocumented semantic edit walk into memory.
    projection = os.path.join(args.archive_path, "projection_manifest.json")
    source_kind = "NATIVE_SESSION_LAYOUT"
    if os.path.exists(projection):
        source_kind = "VERIFIED_AUTHORING_PROJECTION"
        ok, why = verify_projection(args.archive_path, args.session_id)
        if not ok:
            return _refuse(f"projection verification FAILED: {why}")
    elif not os.path.exists(os.path.join(args.archive_path, "manifest.json")):
        return _refuse(f"{args.archive_path} is neither a sealed session "
                       f"archive nor a verified authoring projection")

    print("=" * 78)
    print("  DESCRIPTIVE SESSION MEMORY -- AUTHORING")
    print("=" * 78)
    print(f"  SESSION                  : {args.session_id}")
    print(f"  ARCHIVE                  : {args.archive_path}")
    print(f"  SOURCE KIND              : {source_kind}")
    print(f"  MODE                     : "
          f"{'COMMIT' if args.commit_memory else 'DRY RUN (default)'}")
    print(f"  SCHEMA                   : {DM.SCHEMA_VERSION}")
    print(f"  AUTHORITY                : {RC.AUTHORITY_LABEL}")
    print(f"  SEGMENT CEILING          : {SEG.SEGMENT_CEILING}")
    print(f"  MIN SEGMENT SCANS        : {SEG.MIN_SEGMENT_SCANS}")
    print(f"  RETENTION (retrieval)    : {RC.MAX_AGE_DAYS} days")
    print(f"  LIVE CORPUS BEFORE       : {vector_store.count()} records")
    print()

    built = MA.build_records(args.archive_path)

    if built["status"] == MA.DEFERRED:
        print(f"  STATUS                   : {MA.DEFERRED}")
        for reason in built["reasons"]:
            print(f"    - {reason}")
        print()
        return 3

    pre = built["preconditions"]
    stated = pre.get("session_id")
    if stated and stated != args.session_id:
        return _refuse(f"archive is {stated}, --session-id says {args.session_id}")
    if pre.get("instrument") != PRODUCTION_INSTRUMENT:
        return _refuse(f"instrument identity conflict: archive says "
                       f"{pre.get('instrument')!r}, production is "
                       f"{PRODUCTION_INSTRUMENT!r}")

    print(f"  TOTAL SCANS              : {built['total_scans']}")
    print(f"  QUALITY-ELIGIBLE SCANS   : {built['eligible_scans']}")
    for reason, n in sorted(built["excluded"].items()):
        print(f"    excluded {reason:34}: {n}")
    print(f"  SIGNATURE TIER           : {built['tier']} "
          f"({', '.join(built['tier_keys'])})")
    print(f"  RAW RUNS                 : {built['raw_runs']}")
    print(f"  PROPOSED SEGMENTS        : {len(built['records'])}")
    if built["rejected"]:
        print(f"  REJECTED RECORDS         : {len(built['rejected'])}")
        for bad in built["rejected"]:
            print(f"    {bad['memory_id']}: {bad['reasons']}")
    if pre.get("phase_exit_anomalies"):
        print("  PHASE EXIT ANOMALIES     : (recorded, not suppressed)")
        for a in pre["phase_exit_anomalies"]:
            print(f"    phase {a['phase']}: {a['exit']}")
    print()

    for rec in built["records"]:
        print(f"  {rec['segment_start']}-{rec['segment_end']}  "
              f"n={rec['scan_count']:>3}  {rec['session_phase']:<21} "
              f"{rec['market_regime']:<15}{rec['volatility_state']:<10}"
              f"{rec['dominant_direction']:<12}{rec['dominant_action']:<12}"
              f"{rec['memory_id']}")
    print()

    if not args.commit_memory:
        out_dir = args.out_dir or os.path.join(
            args.archive_path, "analysis", "proposed_descriptive_memory")
        written = MA.write_proposed(built["records"], out_dir, meta={
            "session_id": args.session_id, "mode": MA.DRY_RUN,
            "tier": built["tier"], "eligible_scans": built["eligible_scans"],
            "total_scans": built["total_scans"], "excluded": built["excluded"]})
        print(f"  DRY RUN                  : {MA.DRY_RUN}")
        print(f"  PROPOSALS WRITTEN TO     : {out_dir}")
        print(f"  FILES                    : {len(written['paths']) + 1}")
        print(f"  LIVE CORPUS AFTER        : {vector_store.count()} records "
              f"(unchanged)")
        print()
        return 0

    if not args.approve:
        return _refuse("--commit-memory requires --approve. The first "
                       "deployment is OPERATOR_APPROVAL_REQUIRED: a session "
                       "ending is not a decision to learn from it.")
    try:
        result = MA.commit_records(built["records"], approved=True)
    except MA.AuthoringRefused as exc:
        return _refuse(str(exc))
    print(f"  STATUS                   : {result['status']}")
    print(f"  WRITTEN                  : {result['written']}")
    print(f"  ALREADY PRESENT          : {result['unchanged']}")
    if result.get("conflicts"):
        print("  CONFLICTS                : (whole batch refused)")
        for c in result["conflicts"]:
            print(f"    {c['memory_id']}: stored={c['stored_digest']} "
                  f"proposed={c['proposed_digest']}")
        print()
        return 4
    print(f"  LIVE CORPUS AFTER        : {vector_store.count()} records")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
