"""Offline narrative extract of an EXISTING session archive. No network, no run, nothing modified.

    python3 -I narrative_extract.py <PROD-...evidence_bundle.tar.gz> [<.env>]

Reads Brain call records (data/ai_brain/YYYYMMDD_HHMMSS_<SYM>.json) and the 1m tape straight from the
tarball. For every call writes: the ORIGINAL model response fields (parsed from llm_raw_response), the
consumed/held output, guard metadata, and the mechanical context the Brain was given (narrative
continuity, active path, protected swings, liquidity), each block size-capped with its digest.
The optional .env is read only to refuse output containing any account/credential value.

Writes ~/Desktop/narrative_extract_<archive sha12>.json.gz and prints its SHA-256.
"""
import gzip
import hashlib
import json
import os
import re
import sys
import tarfile

CAP = 6000
CALL = re.compile(r"/data/ai_brain/(\d{8}_\d{6})_[A-Z]+\.json$")
WANTED = ("narrative_continuity", "active_path_state", "protected_swings", "liquidity",
          "stance_history", "campaign_lifecycle", "settled_source", "timestamp", "contract_id")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def capped(value):
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) <= CAP:
        return value
    return {"_truncated": True, "_bytes": len(text), "_sha16": digest(value), "_head": text[:CAP]}


def find(obj, key, depth=0):
    """First value under `key` anywhere in a nested record (depth-limited)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj[:50]:
            r = find(v, key, depth + 1)
            if r is not None:
                return r
    return None


def private_values(envp):
    vals = []
    if envp and os.path.exists(envp):
        for line in open(envp, encoding="utf-8", errors="replace"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if len(v) >= 4 and re.search(r"ACCOUNT|USERNAME|API_KEY|FINGERPRINT|PASSWORD|TOKEN|SECRET", k):
                    vals.append(v)
    return vals


def main():
    path = os.path.expanduser(sys.argv[1])
    envp = os.path.expanduser(sys.argv[2]) if len(sys.argv) > 2 else ""
    archive_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    calls, tape = [], []
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name
            if name.endswith("market_data/topstepx/MNQ_1m.jsonl"):
                for line in tar.extractfile(member).read().decode("utf-8", "replace").splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if str(row.get("timestamp", "")).startswith("2026-10-23"):
                        tape.append({k: row.get(k) for k in ("timestamp", "open", "high", "low", "close")})
                continue
            m = CALL.search("/" + name)
            if not m:
                continue
            try:
                rec = json.loads(tar.extractfile(member).read())
            except ValueError:
                calls.append({"file": os.path.basename(name), "error": "unreadable_json"})
                continue
            raw_text = rec.get("llm_raw_response", rec.get("raw_response"))
            try:
                raw = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
            except ValueError:
                raw = {"_unparsed_raw_text_head": str(raw_text)[:CAP]}
            payload = rec.get("input_payload") or {}
            row = {"file": os.path.basename(name), "top_level_keys": sorted(rec.keys()),
                   "llm_model": rec.get("llm_model"),
                   "provider_latency_seconds": rec.get("provider_latency_seconds"),
                   "record_narrative_direction": rec.get("narrative_direction"),
                   "original_response": capped(raw),
                   "input_keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
                   "input_context": {k: capped(find(payload, k)) for k in WANTED}}
            for key, value in rec.items():
                if key in ("llm_raw_response", "raw_response", "input_payload"):
                    continue
                row.setdefault("record", {})[key] = capped(value)
            calls.append(row)
    calls.sort(key=lambda r: r["file"])
    tape.sort(key=lambda r: r["timestamp"] or "")
    out = {"schema": "narrative_extract/v1", "archive_sha256": archive_sha,
           "calls": calls, "tape_1m_20261023": tape}
    text = json.dumps(out, sort_keys=True, default=str)
    for v in private_values(envp):
        if v in text:
            sys.exit("STOPPED: a private .env value would appear in the extract; nothing written")
    if re.search(r"acct:[0-9a-f]{6}", text):
        sys.exit("STOPPED: a fingerprint-shaped value would appear in the extract; nothing written")
    dest = os.path.expanduser(f"~/Desktop/narrative_extract_{archive_sha[:12]}.json.gz")
    with gzip.open(dest, "wb") as fh:
        fh.write(text.encode())
    print(f"archive sha256 : {archive_sha}")
    print(f"brain calls    : {len(calls)}   tape bars: {len(tape)}")
    print(f"extract file   : {dest.replace(os.path.expanduser('~'), '~')}")
    print(f"extract sha256 : {hashlib.sha256(open(dest, 'rb').read()).hexdigest()}")
    print(f"extract bytes  : {os.path.getsize(dest)}")


if __name__ == "__main__":
    main()
