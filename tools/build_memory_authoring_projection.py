"""Project a sealed session into the layout the authoring tool consumes.

BUILD-VERIFIED-MEMORY-AUTHORING-PROJECTION (2026-08-07).

The sealed PROD-20260807 archive stores one file per scan holding the whole
Brain artifact. The authoring pipeline reads three parallel trees plus an index.
Both hold the same evidence; only the shape differs.

The previous dry run reshaped it in a scratchpad, which is exactly what must
never become the authoring path: a scratchpad has no provenance, so nothing
stops an undocumented semantic edit from entering memory. This tool produces the
same layout with every file traced back to a sealed original by SHA-256, and
records for each one WHICH of four operations produced it:

    COPY_BYTE_IDENTICAL       bytes unchanged
    NORMALIZE_LAYOUT_ONLY     a sub-object lifted out, contents untouched
    DERIVE_INDEX              an index computed from the originals
    RECOVER_SESSION_METADATA  a fact the session never recorded per scan,
                              supplied from session-bound evidence and labelled

There is no fifth operation. Anything that would need one is a semantic
transformation and does not belong in a projection.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

PROJECTION_SCHEMA = "memory_authoring_projection_manifest.v1"

COPY = "COPY_BYTE_IDENTICAL"
NORMALIZE = "NORMALIZE_LAYOUT_ONLY"
DERIVE = "DERIVE_INDEX"
RECOVER = "RECOVER_SESSION_METADATA"
OPERATIONS = (COPY, NORMALIZE, DERIVE, RECOVER)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str) -> str:
    return sha256_bytes(open(path, "rb").read())


def contract_evidence(session_id: str) -> dict:
    """Independent, session-bound proof of the traded contract.

    PROD-20260807 recorded no per-scan contract (the ProductionLoop defect that
    also left telemetry under UNSCOPED). Recovery requires at least one
    AUTHORITATIVE session-bound source and no contradictory evidence.
    """
    sources, contracts = [], set()
    auth = os.path.join("data", "integration", "topstepx",
                        f"session_auth_{session_id}.json")
    if os.path.exists(auth):
        record = json.load(open(auth, encoding="utf-8"))
        if record.get("session_id") == session_id and record.get("contract_id"):
            contracts.add(record["contract_id"])
            sources.append({
                "source": "session authorization record",
                "contract": record["contract_id"],
                "session_binding": f"session_id == {session_id}",
                "durable": True, "sha256": sha256_file(auth),
                "trust": "AUTHORITATIVE",
                "note": ("issued before the session opened and bound to it by "
                         "session_id and authorization fingerprint")})
    return {"sources": sources, "distinct_contracts": sorted(contracts)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--archive-path", required=True)
    ap.add_argument("--out", required=True, help="projection directory")
    args = ap.parse_args(argv)

    archive, out = args.archive_path, args.out
    archive_manifest_path = os.path.join(archive, "manifest.json")
    if not os.path.exists(archive_manifest_path):
        print(f"  REFUSED: {archive} is not a sealed archive")
        return 2
    archive_manifest = json.load(open(archive_manifest_path, encoding="utf-8"))
    if archive_manifest.get("session_id") != args.session_id:
        print(f"  REFUSED: archive is {archive_manifest.get('session_id')}, "
              f"not {args.session_id}")
        return 2

    closure_path = os.path.join(archive, "closure",
                                "session_closure_attestation.json")
    native = all(os.path.exists(os.path.join(archive, p)) for p in (
        os.path.join("launcher", "exit_statuses.json"),
        os.path.join("launcher", "shutdown_evidence.json")))
    if not native and not os.path.exists(closure_path):
        print("  REFUSED: neither native launcher closure artifacts nor a "
              "post-session closure attestation are present")
        return 2

    ce = contract_evidence(args.session_id)
    if len(ce["distinct_contracts"]) != 1:
        print(f"  REFUSED: CONTRACT_IDENTITY UNRECOVERABLE "
              f"(sources={len(ce['sources'])}, "
              f"distinct={ce['distinct_contracts']})")
        return 3
    contract = ce["distinct_contracts"][0]

    if os.path.exists(out):
        shutil.rmtree(out)
    for sub in ("scans/inputs", "brain/parsed_outputs", "brain/full_artifacts",
                "closure"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    entries, rows = [], []
    for i, src in enumerate(sorted(glob.glob(os.path.join(archive, "brain", "*.json"))), 1):
        name = os.path.basename(src)
        raw = open(src, "rb").read()
        src_sha = sha256_bytes(raw)
        rel_src = os.path.relpath(src, archive).replace(os.sep, "/")
        full = json.loads(raw)

        def emit(sub, payload, operation):
            path = os.path.join(out, *sub, name)
            blob = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
            with open(path, "wb") as fh:
                fh.write(blob)
            entries.append({
                "projected_path": "/".join(sub) + "/" + name,
                "source_archive_path": rel_src, "source_sha256": src_sha,
                "projected_sha256": sha256_bytes(blob),
                "projection_operation": operation})

        # Whole artifact: bytes preserved exactly.
        shutil.copy2(src, os.path.join(out, "brain", "full_artifacts", name))
        entries.append({
            "projected_path": f"brain/full_artifacts/{name}",
            "source_archive_path": rel_src, "source_sha256": src_sha,
            "projected_sha256": sha256_file(
                os.path.join(out, "brain", "full_artifacts", name)),
            "projection_operation": COPY})
        # Sub-objects lifted out unchanged.
        emit(("scans", "inputs"), full.get("input_payload") or {}, NORMALIZE)
        emit(("brain", "parsed_outputs"), full.get("parsed_output") or {}, NORMALIZE)

        stamp = name.rsplit("_", 1)[0]
        payload = full.get("input_payload") or {}
        rows.append({
            "scan": i, "phase": "single",
            "et": f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}",
            "market_timestamp": payload.get("timestamp"),
            "instrument": (full.get("symbol") or "").upper(),
            "contract": contract,
            "contract_identity_provenance": "RECOVERED_SESSION_LEVEL",
            "contract_original_per_scan": None,
            "current_price": (payload.get("market") or {}).get("current_price"),
            "input_degraded": full.get("input_degraded") or [],
            "engine_blocks_present": sorted(payload.keys()),
            "source_artifact_sha256": src_sha,
        })

    index = {"scans": rows,
             "contract_identity": {
                 "contract": contract,
                 "classification": "RECOVERED_SESSION_LEVEL",
                 "per_scan_contract_original": "ABSENT",
                 "reason": ("PROD-20260807 recorded no per-scan contract; the "
                            "same ProductionLoop defect blanked the telemetry "
                            "contract field"),
                 "identity_recovery_provenance": ce["sources"]}}
    index_blob = json.dumps(index, indent=1, default=str).encode("utf-8")
    with open(os.path.join(out, "scans", "scan_index.json"), "wb") as fh:
        fh.write(index_blob)
    entries.append({"projected_path": "scans/scan_index.json",
                    "source_archive_path": "brain/*.json + session authorization",
                    "source_sha256": archive_manifest.get("file_count"),
                    "projected_sha256": sha256_bytes(index_blob),
                    "projection_operation": DERIVE})

    for rel in ("manifest.json", "session_ledger.json"):
        src = os.path.join(archive, rel)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, rel))
            entries.append({"projected_path": rel,
                            "source_archive_path": rel,
                            "source_sha256": sha256_file(src),
                            "projected_sha256": sha256_file(os.path.join(out, rel)),
                            "projection_operation": COPY})
    closure_sha = None
    if os.path.exists(closure_path):
        dst = os.path.join(out, "closure", "session_closure_attestation.json")
        shutil.copy2(closure_path, dst)
        closure_sha = sha256_file(dst)
        entries.append({"projected_path": "closure/session_closure_attestation.json",
                        "source_archive_path": "closure/session_closure_attestation.json",
                        "source_sha256": closure_sha,
                        "projected_sha256": closure_sha,
                        "projection_operation": RECOVER})

    ledger_path = os.path.join(archive, "session_ledger.json")
    ledger = json.load(open(ledger_path, encoding="utf-8")) if os.path.exists(ledger_path) else {}
    attestation = json.load(open(closure_path, encoding="utf-8")) if closure_sha else {}

    manifest = {
        "schema_version": PROJECTION_SCHEMA,
        "session_id": args.session_id,
        "source_archive_path": archive.replace(os.sep, "/"),
        "source_archive_manifest_sha256": sha256_file(archive_manifest_path),
        "runtime_head": archive_manifest.get("runtime_head"),
        "normalization_head": _head(),
        "closure_attestation_sha256": closure_sha,
        "closure_type": attestation.get("closure_type"),
        "contract_identity": index["contract_identity"],
        "source_session_completeness": {
            "source_session_completion": "OPERATOR_TERMINATED",
            "observation_window_start_et": attestation.get("observation_start_et")
            or ledger.get("start_time_et"),
            "observation_window_end_et": attestation.get("observation_end_et")
            or ledger.get("end_time_et"),
            "configured_window": "09:30-14:00 America/New_York",
            "configured_window_completed": False,
            "claim": ("NO OBSERVATION AFTER the observation window end. This is "
                      "NOT a claim that no opportunities existed afterwards."),
        },
        "operations_used": sorted({e["projection_operation"] for e in entries}),
        "file_count": len(entries),
        "files": entries,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "created_by": "build_memory_authoring_projection",
    }
    mpath = os.path.join(out, "projection_manifest.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, default=str)

    print("=" * 84)
    print(f"  AUTHORING PROJECTION -- {args.session_id}")
    print("=" * 84)
    print(f"  source archive       : {archive}")
    print(f"  archive manifest sha : {manifest['source_archive_manifest_sha256']}")
    print(f"  runtime head         : {manifest['runtime_head']}")
    print(f"  normalization head   : {manifest['normalization_head']}")
    print(f"  closure type         : {manifest['closure_type']}")
    print(f"  closure sha          : {closure_sha}")
    print(f"  contract             : {contract}  ({len(ce['sources'])} authoritative source(s))")
    print(f"  completeness         : {manifest['source_session_completeness']['source_session_completion']}"
          f"  {manifest['source_session_completeness']['observation_window_start_et']}"
          f" -> {manifest['source_session_completeness']['observation_window_end_et']}")
    print(f"  operations used      : {manifest['operations_used']}")
    print(f"  projected files      : {len(entries)}")
    print(f"  projection manifest  : {mpath}")
    print(f"  manifest sha256      : {sha256_file(mpath)}")
    return 0


def _head() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
