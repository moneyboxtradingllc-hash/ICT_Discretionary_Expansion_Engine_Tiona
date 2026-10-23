"""Offline, sanitized evidence bundle for the zero-candidate audit of PROD-20261023-C1. Reads local files only.

    python3 -I session_evidence_bundle.py ~/stage5_combine_20261023/repo [out_dir]

What it does (no network, no run, nothing under repo/ is modified):
  * inventories every file under repo/data (relative path, size, UTC mtime, sha256 of the private original);
  * copies session evidence (decision journal, Brain-call records and call ledger, wake/plan events, stance/thesis
    journals, session tape and manifest, canonical candle/VAP market data) into the bundle, after redaction:
      - JSON keys naming account, balance, equity, capital, credentials, signatures or authorization fingerprints
        get the value "[REDACTED:<key>]";
      - every credential/account value from repo/.env is replaced wherever it appears;
  * EXCLUDES (listed in the manifest with their private hash only) the signed authorization/mission stores,
    capital/equity/account state, preflight/readiness/protection attestations and anything not session evidence;
  * derives decision_timeline.json (scan-to-artifact index and first/last/transition runs of every refusal,
    lifecycle, guard, Draw, scope and action/direction field in candidate_decisions.jsonl) and brain_calls_index.json
    (per Brain call: time, source, model, latency, error, PRE-guard action/direction from the raw model response vs
    POST-guard parsed action/direction, and every guard/continuity field present);
  * refuses to write the archive if any .env credential or account value would remain anywhere in it.
Fields that were never recorded are reported as UNKNOWN; nothing is inferred.
"""
import hashlib
import json
import os
import re
import sys
import tarfile
import time

SESSION = "PROD-20261023-C1"
REPO = os.path.abspath(os.path.expanduser(sys.argv[1]))
OUT = os.path.abspath(os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/Desktop"))
DATA = os.path.join(REPO, "data")
NAME = f"{SESSION}_evidence_bundle"
STAGE = os.path.join(OUT, NAME)

EXCLUDE = re.compile(r"authoriz|mission|capital|equity|account|balance|readonly_preflight|combine_readiness|"
                     r"protection_authority|active_execution_context|\.env|signing|secret|credential", re.I)
INCLUDE = re.compile(r"(candidate_decisions|brain_wake_decisions|conditional_plan_events|session_tape|trade_lineage|"
                     r"stance_memory|active_thesis|thesis|ai_calls_|slippage_observations|volume_profile|"
                     r"^ai_brain/\d{8}_\d{6}_[A-Z]+\.json$|^market_data/|ai_retrieval/)", re.I)
REDACT_KEY = re.compile(r"(account|balance|equity|capital|api_?key|username|password|secret|signature|"
                        r"authorization_fingerprint|^token$|access_token|session_token|bearer|peak_)", re.I)
ROW_TS = ("ts", "timestamp", "decided_at", "recorded_at", "scan_at", "at", "created_at", "time")
ROW_SCAN = ("scan", "scan_index", "scan_number", "scan_id", "artifact_id", "decision_id")
TIMELINE_KEY = re.compile(r"lifecycle|refus|reason|disposition|action|direction|guard|continuity|draw|transfer|"
                          r"authority|scope|premise|qualif|stand|eligib|occurrence|tool|objective|currentness|"
                          r"revision|certificate|custody|active_path|activepath|owner|origin|status|degrad|source", re.I)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def env_secrets():
    vals = []
    p = os.path.join(REPO, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if len(v) >= 4 and re.search(r"USERNAME|API_KEY|ACCOUNT|FINGERPRINT|PASSWORD|TOKEN|SECRET", k):
                    vals.append(v)
    return sorted(set(vals), key=len, reverse=True)


SECRETS = env_secrets()


def scrub_text(s):
    for v in SECRETS:
        s = s.replace(v, "[REDACTED]")
    s = re.sub(r"(Bearer\s+)\S+", r"\1[REDACTED]", s)
    s = re.sub(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "[REDACTED_JWT]", s)
    return re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[REDACTED_KEY]", s)


def scrub(obj, redacted):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if REDACT_KEY.search(str(k)):
                out[k] = f"[REDACTED:{k}]"
                redacted[str(k)] = redacted.get(str(k), 0) + 1
            else:
                out[k] = scrub(v, redacted)
        return out
    if isinstance(obj, list):
        return [scrub(v, redacted) for v in obj]
    if isinstance(obj, str):
        return scrub_text(obj)
    return obj


def sanitize_file(src, dst, redacted):
    raw = open(src, encoding="utf-8", errors="replace").read()
    if src.endswith(".jsonl"):
        lines = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                lines.append(json.dumps(scrub(json.loads(line), redacted), default=str))
            except ValueError:
                lines.append(scrub_text(line))
        text = "\n".join(lines) + ("\n" if lines else "")
    elif src.endswith(".json"):
        try:
            text = json.dumps(scrub(json.loads(raw), redacted), indent=1, default=str)
        except ValueError:
            text = scrub_text(raw)
    else:
        text = scrub_text(raw)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(text)


def flat(d, prefix="", depth=0):
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 2:
            out.update(flat(v, key + ".", depth + 1))
        elif not isinstance(v, (dict, list)):
            out[key] = v
        elif isinstance(v, list) and len(v) <= 6 and all(not isinstance(x, (dict, list)) for x in v):
            out[key] = v
    return out


def first(d, names):
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def timeline(rows):
    runs, schema = {}, {}
    for i, row in enumerate(rows, 1):
        f = flat(row)
        for k in f:
            schema[k] = schema.get(k, 0) + 1
        ident = {"row": i, "scan": first(row, ROW_SCAN), "ts": first(row, ROW_TS)}
        for k, v in f.items():
            if not TIMELINE_KEY.search(k):
                continue
            val = json.dumps(v, default=str)[:160]
            lst = runs.setdefault(k, [])
            if lst and lst[-1]["value"] == val:
                lst[-1].update(last=ident, count=lst[-1]["count"] + 1)
            else:
                lst.append({"value": val, "first": ident, "last": ident, "count": 1})
    return runs, schema


def action_direction(d):
    if not isinstance(d, dict):
        return None, None
    f = flat(d)
    act = next((f[k] for k in f if re.search(r"(^|\.)(current_)?action$", k)), None)
    dirn = next((f[k] for k in f if re.search(r"(^|\.)(market_)?direction$|(^|\.)bias$", k)), None)
    return act, dirn


def brain_index(paths):
    out = []
    for p in sorted(paths):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            out.append({"file": os.path.basename(p), "error": "unreadable"})
            continue
        f = flat(rec)
        raw = rec.get("raw_response") or f.get("llm.raw_response") or f.get("call.raw_response")
        try:
            pre = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else None
        except ValueError:
            pre = None
        parsed = rec.get("parsed_output") or rec.get("parsed") or rec.get("parsed_response")
        pa, pd = action_direction(pre)
        qa, qd = action_direction(parsed)
        out.append({
            "file": os.path.basename(p),
            "source": first(rec, ("source", "brain_source")) or "UNKNOWN",
            "model": first(rec, ("model", "model_requested", "resolved_model")) or f.get("llm.model") or "UNKNOWN",
            "fallback_or_degradation": first(rec, ("fallback_reason", "degradation_reason", "degraded_reason")),
            "latency_seconds": first(rec, ("latency_seconds",)) or f.get("llm.latency_seconds"),
            "provider_call_started_at": first(rec, ("provider_call_started_at",)),
            "provider_call_completed_at": first(rec, ("provider_call_completed_at",)),
            "is_repair": first(rec, ("is_repair",)),
            "raw_response_retained": raw is not None,
            "pre_guard_action": pa if pre is not None else "UNKNOWN",
            "pre_guard_direction": pd if pre is not None else "UNKNOWN",
            "post_guard_action": qa if parsed is not None else "UNKNOWN",
            "post_guard_direction": qd if parsed is not None else "UNKNOWN",
            "guard_fields": {k: json.dumps(v, default=str)[:200] for k, v in f.items()
                             if re.search(r"guard|continuity|hold|authority", k, re.I)},
        })
    return out


def main():
    if not os.path.isdir(DATA):
        sys.exit(f"STOPPED: {DATA} not found")
    os.makedirs(STAGE, exist_ok=False)
    inventory, redacted = [], {}
    included, decisions, brain_files = [], [], []
    for root, _dirs, files in os.walk(DATA):
        for fn in sorted(files):
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, DATA)
            entry = {"path": scrub_text(rel), "bytes": os.path.getsize(src),
                     "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(src))),
                     "private_sha256": sha(src)}
            if EXCLUDE.search(rel):
                entry["disposition"] = "EXCLUDED (private: authorization/capital/account/attestation class)"
            elif INCLUDE.search(rel):
                dst = os.path.join(STAGE, "data", scrub_text(rel))
                sanitize_file(src, dst, redacted)
                entry["disposition"] = "INCLUDED (sanitized)"
                entry["sanitized_sha256"] = sha(dst)
                included.append(dst)
                if fn == "candidate_decisions.jsonl":
                    decisions.append(dst)
                if re.match(r"\d{8}_\d{6}_[A-Z]+\.json$", fn):
                    brain_files.append(dst)
            else:
                entry["disposition"] = "NOT EXPORTED (not on the session-evidence allowlist)"
            inventory.append(entry)

    rows = []
    for d in decisions:
        for line in open(d, encoding="utf-8"):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    runs, schema = timeline(rows)
    derived = {
        "decision_timeline.json": {
            "source": [os.path.relpath(d, STAGE) for d in decisions] or "UNKNOWN (no candidate_decisions.jsonl)",
            "rows": len(rows), "field_schema_counts": schema, "runs_by_field": runs,
            "scan_to_artifact": [{"row": i, "scan": first(r, ROW_SCAN), "ts": first(r, ROW_TS),
                                  "final_disposition": r.get("final_disposition")} for i, r in enumerate(rows, 1)],
        },
        "brain_calls_index.json": {"calls": brain_index(brain_files),
                                   "note": "pre_guard = raw model response; post_guard = parsed/consumed output. "
                                           "UNKNOWN where the record did not retain that field."},
    }
    for name, obj in derived.items():
        text = scrub_text(json.dumps(scrub(obj, redacted), indent=1, default=str))
        open(os.path.join(STAGE, name), "w", encoding="utf-8").write(text)
        included.append(os.path.join(STAGE, name))

    manifest = {
        "session": SESSION, "source_commit": "ffe00aef3db7fb2339780ed0fa9016149923c96e",
        "tool": os.path.basename(__file__), "tool_sha256": sha(os.path.abspath(__file__)),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "redaction": "JSON keys matching " + REDACT_KEY.pattern + " -> [REDACTED:<key>]; every .env credential/"
                     "account value replaced; Bearer/JWT/sk- tokens replaced. Hashes of private originals do not "
                     "authenticate them to a third party.",
        "redacted_key_counts": redacted,
        "not_recorded_or_absent": "Anything not listed in inventory was never written by the session: UNKNOWN.",
        "inventory": inventory,
    }
    open(os.path.join(STAGE, "MANIFEST.json"), "w").write(json.dumps(manifest, indent=1))

    for p in included + [os.path.join(STAGE, "MANIFEST.json")]:
        body = open(p, encoding="utf-8", errors="replace").read()
        if any(v in body for v in SECRETS):
            sys.exit(f"STOPPED: a private .env value remained in {os.path.relpath(p, STAGE)}; archive not written")

    archive = os.path.join(OUT, NAME + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(STAGE, arcname=NAME)
    print(f"files inventoried: {len(inventory)}  included: {sum(e['disposition'].startswith('INCLUDED') for e in inventory)}"
          f"  excluded: {sum(e['disposition'].startswith('EXCLUDED') for e in inventory)}")
    print(f"decision rows: {len(rows)}  brain-call records: {len(brain_files)}  redacted keys: {sum(redacted.values())}")
    print(f"archive: {archive.replace(os.path.expanduser('~'), '~')}  ({os.path.getsize(archive):,} bytes)")
    print(f"archive sha256: {sha(archive)}")


if __name__ == "__main__":
    main()
