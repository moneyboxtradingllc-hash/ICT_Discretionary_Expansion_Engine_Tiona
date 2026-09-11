"""READ-ONLY. Package one session's ORIGINAL runtime evidence, with a manifest.

PROD-20260911 EVIDENCE REQUEST. The owner asked for the original runtime
artifacts from the deployment machine, unedited, one archive per session, with
per-file provenance.

THIS MODULE OPENS EVERY EVIDENCE FILE "rb" AND NEVER WRITES INTO THE EVIDENCE
TREE. It writes exactly two things, both under `--out-dir`, which must sit
outside the runtime store: the archive and the manifest. Nothing is normalized,
regenerated, reclassified or reconstructed on the way in. A file is copied
byte-for-byte or it is not copied.

ORIGINAL vs DERIVED IS DECLARED, NEVER GUESSED AT BY THE READER.

    ORIGINAL_RUNTIME   written by the live session as it ran
    DERIVED_REPORT     produced afterwards by an audit tool -- including the
                       `candidate_decisions.reclassified_*.jsonl` copies this
                       operator generated. They are INCLUDED because hiding
                       them would misrepresent the directory, and LABELLED
                       because presenting them as runtime evidence would be
                       worse.

MISSING IS A FINDING, NOT AN OMISSION. Every category the owner named is
listed; one with no files says MISSING and stays in the manifest. No empty
substitute is created, and no reconstructed tape is offered in place of absent
pre-call evidence.

PRE/POST-CALL PROVENANCE is reported only where the writer makes it knowable,
and UNKNOWN otherwise.

    python tools/topstepx_evidence_export.py --session PROD-20260909 \
        --out-dir ~/Desktop/tiona_evidence
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone

ORIGINAL = "ORIGINAL_RUNTIME"
DERIVED = "DERIVED_REPORT"

#: (category, glob template, provenance, kind). `{s}` = session id,
#: `{d}` = the yyyymmdd date embedded in the session id.
CATEGORIES = [
    ("session_authorization", "data/integration/topstepx/session_auth_{s}.json",
     "pre-call: signed before any scan ran", ORIGINAL),
    ("trade_missions", "data/integration/topstepx/trade_mission_{s}_*.json",
     "post-call: venue-observed execution facts", ORIGINAL),
    ("flight_recorder_submissions",
     "data/integration/topstepx/submissions_{s}.jsonl",
     "PRE-TRANSPORT then post-response: open_submission writes before the "
     "request leaves, record_response after", ORIGINAL),
    ("candidate_decisions",
     "data/replay_sessions/{s}/memory_retrieval/candidate_decisions.jsonl",
     "post-call: one row per terminal scan decision", ORIGINAL),
    ("retrieval_scans",
     "data/replay_sessions/{s}/memory_retrieval/retrieval_scans.jsonl",
     "post-call: describes the retrieval result handed to the Brain", ORIGINAL),
    ("candidate_lineage",
     "data/replay_sessions/{s}/memory_retrieval/trade_lineage.jsonl",
     "post-call", ORIGINAL),
    ("session_tape",
     "data/replay_sessions/{s}/memory_retrieval/session_tape.jsonl",
     "post-call", ORIGINAL),
    ("session_tape_manifest",
     "data/replay_sessions/{s}/memory_retrieval/session_tape_manifest.json",
     "post-call", ORIGINAL),
    ("replay_session_tree_other", "data/replay_sessions/{s}/**/*",
     "mixed; see per-file kind", ORIGINAL),
    ("ai_call_ledger", "data/ai_brain/ai_calls_{s}_*.jsonl",
     "post-call: one row per provider request, written after the response",
     ORIGINAL),
    ("brain_call_artifacts", "data/ai_brain/{d}_*.json",
     "BOTH: raw_snapshot is the pre-call input handed to the provider; the "
     "response is post-call", ORIGINAL),
    ("retrieval_logs", "data/ai_retrieval/retrieval_logs/retrieval_{d}_*.json",
     "pre-call: retrieval performed to build the Brain input", ORIGINAL),
    ("ai_shadow", "data/ai_shadow/*{d}*.jsonl", "post-call", ORIGINAL),
    ("occurrence_ledger", "data/occurrence_ledger/**/*", "mixed", ORIGINAL),
    ("ops_incidents", "data/ops/incidents_{d}.json", "post-call", ORIGINAL),
    ("market_data_candles", "data/market_data/topstepx/CON_*.jsonl",
     "post-call: append-only 1m journal, NOT per-session", ORIGINAL),
    ("market_data_vap", "data/market_data/topstepx/vap_*.jsonl",
     "post-call: live-capture only, NOT per-session", ORIGINAL),
    ("halt_observations", "data/market_data/halt_observations/**/*",
     "post-call", ORIGINAL),
    ("live_snapshots", "data/live_snapshots/**/*", "mixed", ORIGINAL),
    ("htf_memory", "data/htf_memory/**/*", "mixed", ORIGINAL),
    ("rule_governance", "data/rule_governance/**/*", "mixed", ORIGINAL),
]

#: Filename markers that make a file a LATER DERIVED REPORT regardless of where
#: it sits. The reclassification copies are the operator's own, and calling
#: them runtime evidence would be exactly the misrepresentation this export
#: exists to avoid.
DERIVED_MARKERS = ("reclassified", "postmortem", "_report", "audit")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(path: str, default_kind: str) -> str:
    name = os.path.basename(path).lower()
    return DERIVED if any(m in name for m in DERIVED_MARKERS) else default_kind


def collect(root: str, session: str) -> dict:
    date = "".join(ch for ch in session if ch.isdigit())[:8]
    seen, categories = set(), []
    for name, pattern, provenance, kind in CATEGORIES:
        rel = pattern.format(s=session, d=date)
        matches = sorted(
            p for p in glob.glob(os.path.join(root, rel), recursive=True)
            if os.path.isfile(p))
        rows = []
        for path in matches:
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            rows.append({
                "absolute_path": real,
                "bytes": os.path.getsize(real),
                "sha256": sha256_of(real),
                "session_identity": session,
                "kind": classify(real, kind),
                "provenance": provenance,
                "modified_utc": datetime.fromtimestamp(
                    os.path.getmtime(real), timezone.utc).isoformat(),
            })
        categories.append({
            "category": name, "pattern": rel,
            "status": "PRESENT" if rows else "MISSING",
            "file_count": len(rows), "files": rows,
            "note": ("" if rows else
                     "no file matched; this artifact was never durably written "
                     "by the historical build, or is not written per-session"),
        })
    return {"session": session, "runtime_root": os.path.realpath(root),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "categories": categories}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--root", default=".", help="the runtime/repository root")
    ap.add_argument("--out-dir", required=True,
                    help="where the ZIP and manifest are written; must be "
                         "OUTSIDE the runtime root")
    ap.add_argument("--no-zip", action="store_true",
                    help="manifest only; copy nothing")
    args = ap.parse_args()

    root = os.path.realpath(args.root)
    out = os.path.realpath(os.path.expanduser(args.out_dir))
    # THE EXPORT MAY NOT WRITE INTO THE EVIDENCE IT IS EXPORTING.
    if out == root or out.startswith(root + os.sep):
        print(f"REFUSED: --out-dir {out} is inside the runtime root {root}. "
              f"An export that writes into the evidence tree changes the thing "
              f"it is measuring. Choose a directory outside it.")
        return 2
    os.makedirs(out, exist_ok=True)

    manifest = collect(root, args.session)
    present = [c for c in manifest["categories"] if c["status"] == "PRESENT"]
    missing = [c for c in manifest["categories"] if c["status"] == "MISSING"]
    files = [f for c in present for f in c["files"]]
    originals = [f for f in files if f["kind"] == ORIGINAL]
    derived = [f for f in files if f["kind"] == DERIVED]

    print(f"EVIDENCE EXPORT -- {args.session}")
    print(f"  runtime root        : {manifest['runtime_root']}")
    print(f"  categories present  : {len(present)}")
    print(f"  categories MISSING  : {len(missing)}")
    print(f"  files               : {len(files)} "
          f"({len(originals)} original runtime, {len(derived)} derived report)")
    print(f"  total bytes         : {sum(f['bytes'] for f in files):,}")
    if missing:
        print("\n  MISSING (reported, not substituted):")
        for c in missing:
            print(f"    {c['category']:<28} {c['pattern']}")
    if derived:
        print("\n  DERIVED REPORTS (included, labelled, NOT runtime evidence):")
        for f in derived:
            print(f"    {os.path.basename(f['absolute_path'])}")

    manifest_path = os.path.join(out, f"MANIFEST_{args.session}.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\n  manifest            : {manifest_path}")

    if args.no_zip:
        print("  --no-zip: nothing copied.")
        return 0

    zip_path = os.path.join(out, f"{args.session}_evidence.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # Stored under its path RELATIVE TO THE RUNTIME ROOT, so the
            # original layout is reconstructable without guessing.
            arc = os.path.relpath(f["absolute_path"], root)
            zf.write(f["absolute_path"], arcname=os.path.join(args.session, arc))
        zf.write(manifest_path, arcname=os.path.basename(manifest_path))
    print(f"  archive             : {zip_path}")
    print(f"  archive bytes       : {os.path.getsize(zip_path):,}")
    print(f"  archive sha256      : {sha256_of(zip_path)}")
    print("\n  Nothing in the evidence tree was written, renamed or altered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
