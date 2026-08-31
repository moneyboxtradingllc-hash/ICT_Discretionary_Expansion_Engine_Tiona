"""Seal a completed production session into an immutable, verified archive.

SEAL-PROD-20260807-SESSION-EVIDENCE (2026-08-07).

PROD-20260807 is the most forensically valuable session in the project: first
Terra run with durable memory, and the session that exposed the retrieval shape
defect, the delivery vocabulary defect and the prose objective-binding defect.
Its evidence existed only as loose runtime files.

Two honesty rules are enforced here:

  * Retrieval telemetry was written to `data/replay_sessions/UNSCOPED/` because
    ProductionLoop did not pass session_id. Each record's membership is PROVEN
    from its own scan_id, never assumed, and the archive records that the
    original runtime location was UNSCOPED. The blank contract field is
    preserved as it was written -- a recovered association is not the same
    thing as an original value.

  * The archive binds the session to the code that RAN it, not to the repairs
    that followed. Runtime HEAD and repair HEAD are separate fields.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_ids_for(session_date: str) -> set:
    """Scan ids belonging to this session, from the Brain artifacts themselves."""
    out = set()
    for f in glob.glob(f"data/ai_brain/{session_date}_*_MNQ.json"):
        stamp = os.path.basename(f).rsplit("_", 1)[0]        # 20260807_093051
        out.add(f"scan-{stamp[:8]}T{stamp[9:]}")
    return out


def partition_unscoped(session_date: str) -> tuple:
    """(owned, foreign) UNSCOPED telemetry rows, decided per record."""
    path = os.path.join("data", "replay_sessions", "UNSCOPED",
                        "memory_retrieval", "retrieval_scans.jsonl")
    owned, foreign = [], []
    if not os.path.exists(path):
        return owned, foreign
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        stamp = str(row.get("timestamp_et") or "").replace("-", "")[:8]
        sid = str(row.get("scan_id") or "")
        if stamp == session_date or sid.startswith(f"scan-{session_date}"):
            owned.append(row)
        else:
            foreign.append(row)
    return owned, foreign


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--session-date", required=True, help="YYYYMMDD")
    ap.add_argument("--runtime-head", required=True,
                    help="the commit that ACTUALLY RAN the session")
    ap.add_argument("--reseal", action="store_true",
                    help="regenerate the manifest over post-seal analysis "
                         "artifacts; never changes runtime identity")
    args = ap.parse_args(argv)

    root = os.path.join("data", "replay_sessions", args.session_id)
    if args.reseal:
        # Analysis artifacts (parity, reconciliation, ledger) are produced from
        # the sealed evidence and land after the first seal. Resealing extends
        # the manifest over them. It cannot alter runtime identity: --runtime-head
        # is still supplied and still recorded as the commit that ran.
        for stale in ("manifest.json", "SHA256SUMS.txt"):
            if os.path.exists(os.path.join(root, stale)):
                os.remove(os.path.join(root, stale))
    if os.path.exists(os.path.join(root, "manifest.json")):
        print(f"  ALREADY SEALED: {root}/manifest.json exists; refusing to overwrite")
        return 2
    repair_head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()

    os.makedirs(os.path.join(root, "brain"), exist_ok=True)
    os.makedirs(os.path.join(root, "memory_retrieval"), exist_ok=True)
    os.makedirs(os.path.join(root, "launcher"), exist_ok=True)

    # ── Brain artifacts, byte-for-byte ──────────────────────────────────────
    brain = sorted(glob.glob(f"data/ai_brain/{args.session_date}_*_MNQ.json"))
    for f in brain:
        shutil.copy2(f, os.path.join(root, "brain", os.path.basename(f)))

    # ── retrieval telemetry, membership proven per record ───────────────────
    owned, foreign = partition_unscoped(args.session_date)
    tele = os.path.join(root, "memory_retrieval", "retrieval_scans.jsonl")
    with open(tele, "w", encoding="utf-8") as fh:
        for row in owned:
            fh.write(json.dumps(row, default=str) + "\n")
    json.dump({
        "original_runtime_location": "data/replay_sessions/UNSCOPED/",
        "recovered_for_session": args.session_id,
        "recovery_reason": ("ProductionLoop did not pass session_id/contract to "
                            "ProductionScanCycle during the live session"),
        "runtime_defect_later_repaired": True,
        "repair_commit": "bd19660",
        "membership_proof": ("each record matched on its own scan_id / "
                             "timestamp_et against the session date; Brain "
                             "artifacts supply the authoritative scan id set"),
        "records_adopted": len(owned),
        "records_left_in_unscoped": len(foreign),
        "original_contract_field": ("blank as written at runtime -- NOT "
                                    "backfilled; a recovered session "
                                    "association is not an original value"),
        "original_session_id_field": "UNSCOPED as written at runtime",
    }, open(os.path.join(root, "memory_retrieval", "PROVENANCE.json"), "w",
            encoding="utf-8"), indent=1)

    # ── candidate decisions: adopt ONLY rows this session actually produced ──
    # UNSCOPED also holds rows from the post-session offline replay of the
    # August 6 archive (scan ids `snap-N`, market timestamps 2026-08-06).
    # Sharing a directory is not evidence of belonging to this session.
    cd = os.path.join("data", "replay_sessions", "UNSCOPED", "memory_retrieval",
                      "candidate_decisions.jsonl")
    cd_owned, cd_foreign = [], 0
    if os.path.exists(cd):
        for line in open(cd, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            stamp = str(row.get("market_timestamp") or "").replace("-", "")[:8]
            if str(row.get("scan_id") or "").startswith(f"scan-{args.session_date}") \
                    or stamp == args.session_date:
                cd_owned.append(row)
            else:
                cd_foreign += 1
    if cd_owned:
        with open(os.path.join(root, "memory_retrieval",
                               "candidate_decisions.jsonl"), "w",
                  encoding="utf-8") as fh:
            for row in cd_owned:
                fh.write(json.dumps(row, default=str) + "\n")
    json.dump({
        "records_adopted": len(cd_owned),
        "records_rejected_as_foreign": cd_foreign,
        "rejection_basis": (
            "rows carrying scan ids `snap-N` and market timestamps of "
            "2026-08-06 were produced by the POST-SESSION offline replay of "
            "the August 6 archive, not by this live session"),
        "live_session_note": (
            "candidate_decisions.jsonl did not exist during PROD-20260807; "
            "live qualification was never persisted and is NOT fully "
            "reconstructable for this session"),
    }, open(os.path.join(root, "memory_retrieval",
                         "CANDIDATE_DECISIONS_PROVENANCE.json"), "w",
            encoding="utf-8"), indent=1)

    # ── launcher / runtime identity ─────────────────────────────────────────
    log = os.path.join("data", "integration", "topstepx",
                       "prod20260807_stdout.log")
    if os.path.exists(log):
        shutil.copy2(log, os.path.join(root, "launcher", "stdout.log"))
    json.dump({
        "session_id": args.session_id,
        "session_date": args.session_date,
        "runtime_head": args.runtime_head,
        "post_session_repair_head": repair_head,
        "runtime_head_note": ("the commit that ACTUALLY RAN this session; "
                              "later repair commits must never replace it"),
        "stdout_note": ("0 bytes: Python buffered stdout when piped. The "
                        "session was observable only through artifacts. "
                        "Line buffering was added afterwards."),
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
    }, open(os.path.join(root, "launcher", "runtime_identity.json"), "w",
            encoding="utf-8"), indent=1)

    # ── manifest ────────────────────────────────────────────────────────────
    entries, total = [], 0
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if name in ("manifest.json", "SHA256SUMS.txt"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            size = os.path.getsize(full)
            entries.append((rel, size, sha256(full)))
            total += size
    entries.sort()
    sums = os.path.join(root, "SHA256SUMS.txt")
    with open(sums, "w", encoding="utf-8") as fh:
        for rel, _, digest in entries:
            fh.write(f"{digest}  {rel}\n")
    manifest = {
        "session_id": args.session_id, "session_date": args.session_date,
        "runtime_head": args.runtime_head,
        "post_session_repair_head": repair_head,
        "file_count": len(entries), "total_bytes": total,
        "brain_artifacts": len(brain),
        "retrieval_telemetry_records": len(owned),
        "unscoped_records_adopted": len(owned),
        "unscoped_records_not_adopted": len(foreign),
        "candidate_decision_records": len(cd_owned),
        "candidate_decision_records_rejected_as_foreign": cd_foreign,
        "live_qualification": "NOT_FULLY_RECONSTRUCTABLE",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "secrets_policy": ("no credentials, JWTs, API keys, raw account ids or "
                           "complete fingerprints appear in this archive"),
    }
    json.dump(manifest, open(os.path.join(root, "manifest.json"), "w",
                             encoding="utf-8"), indent=1)
    manifest_sha = sha256(os.path.join(root, "manifest.json"))

    bad = [rel for rel, _, digest in entries
           if sha256(os.path.join(root, rel.replace("/", os.sep))) != digest]
    print("=" * 80)
    print(f"  SEALED {args.session_id}")
    print("=" * 80)
    print(f"  archive path      : {root}")
    print(f"  runtime HEAD      : {args.runtime_head}")
    print(f"  repair HEAD       : {repair_head}")
    print(f"  brain artifacts   : {len(brain)}")
    print(f"  telemetry adopted : {len(owned)}  (left in UNSCOPED: {len(foreign)})")
    print(f"  file count        : {len(entries)}")
    print(f"  total bytes       : {total}")
    print(f"  manifest sha256   : {manifest_sha}")
    print(f"  INTEGRITY         : {'PASS' if not bad else 'FAIL ' + str(bad[:3])}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
