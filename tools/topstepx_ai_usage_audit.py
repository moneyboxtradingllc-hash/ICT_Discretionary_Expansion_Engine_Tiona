"""Read-only accounting of recorded outbound requests, never trading verdicts.

The ledger owns request/token classification; model_pricing owns prices and
cost calculation. A missing or damaged record is not evidence of zero usage.
No provider, trading session, or ledger writer is invoked by this tool.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_brain import ai_call_ledger as LEDGER
from ai_brain import model_pricing as PRICES
from ai_retrieval.retrieval_telemetry import telemetry_path


def read_rows(path: str) -> tuple[list, list]:
    """Keep readable evidence and name every unreadable row, with provenance.

    LEDGER.load deliberately returns [] for both missing and malformed files;
    that runtime convenience cannot establish forensic evidence availability.
    """
    rows, errors = [], []
    try:
        with open(path, encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("row is not an object")
                    rows.append((row, {"path": path, "line": line_number}))
                except ValueError as exc:
                    errors.append(f"{path}:{line_number}: {exc}")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return rows, errors


def returned_usage(row: dict) -> dict:
    """Invert the ledger's flattened usage shape, without estimating tokens.

    Missing required usage is UNKNOWN. The canonical writer stores zero when
    usage is absent; without a response identity that zero is not proof that
    the provider billed nothing. Reasoning stays INSIDE completion tokens.
    """
    for key in ("prompt_tokens", "cached_tokens", "completion_tokens",
                "uncached_input_tokens", "total_tokens"):
        if type(row.get(key)) is not int or row[key] < 0:
            raise ValueError(f"missing/invalid returned {key}")
    reasoning = row.get("reasoning_tokens")
    if reasoning is not None and (type(reasoning) is not int or reasoning < 0):
        raise ValueError("invalid reasoning_tokens")
    if row["cached_tokens"] > row["prompt_tokens"]:
        raise ValueError("cached tokens exceed prompt tokens")
    if row["uncached_input_tokens"] != row["prompt_tokens"] - row["cached_tokens"]:
        raise ValueError("recorded input token classes disagree")
    if row.get("cache_write_tokens"):
        raise ValueError("cache-write pricing is not defined by the pricing owner")
    if (not row["prompt_tokens"] and not row["completion_tokens"]
            and not row.get("response_id")):
        raise ValueError("zero usage without a returned response is not proof of zero cost")
    return {
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "prompt_tokens_details": {"cached_tokens": row["cached_tokens"]},
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }


def _costs(rows: list) -> dict:
    total = Decimal(0)
    groups = {key: {} for key in ("model", "role", "purpose")}
    unpriced = []
    for row, location in rows:
        model = row.get("model_returned") or row.get("model_requested") or "UNKNOWN"
        labels = dict(model=model, role=row.get("brain_role") or "UNKNOWN",
                      purpose=row.get("call_purpose") or "UNKNOWN")
        reason, unknown_model, cost = None, False, None
        try:
            PRICES.pricing_for(model)
        except PRICES.UnknownModelPricing as exc:
            reason, unknown_model = str(exc), True
        if reason is None:
            try:
                result = PRICES.cost_from_usage(returned_usage(row), model)
                cost, reason = result.get("cost_usd"), result.get("error")
            except ValueError as exc:
                reason = str(exc)
        if cost is None:
            unpriced.append(dict(location, model=model, reason=reason,
                unknown_model_pricing=unknown_model, scan=row.get("scan"),
                client_request_id=row.get("client_request_id")))
        else:
            total += Decimal(str(cost))
        for dimension, label in labels.items():
            bucket = groups[dimension].setdefault(label, {
                "requests": 0, "priced_requests": 0, "unpriced_requests": 0,
                "known_priced_cost_usd": Decimal(0)})
            bucket["requests"] += 1
            bucket["priced_requests" if cost is not None else "unpriced_requests"] += 1
            if cost is not None:
                bucket["known_priced_cost_usd"] += Decimal(str(cost))
    for dimension in groups.values():
        for bucket in dimension.values():
            bucket["status"] = ("UNKNOWN" if not bucket["priced_requests"]
                                else "LOWER_BOUND" if bucket["unpriced_requests"]
                                else "KNOWN")
            bucket["known_priced_cost_usd"] = (
                float(bucket["known_priced_cost_usd"]) if bucket["priced_requests"]
                else None)
    return dict(known_priced_cost_usd=float(total), by_model=groups["model"],
                by_role=groups["role"], by_purpose=groups["purpose"],
                unpriced_requests=unpriced, unpriced_request_count=len(unpriced),
                unknown_pricing_requests=[r for r in unpriced if r["unknown_model_pricing"]],
                unknown_pricing_request_count=sum(r["unknown_model_pricing"] for r in unpriced))


def audit(session: str, *, ledger_dir: str = None,
          retrieval_path: str = None) -> dict:
    paths = sorted(glob.glob(os.path.join(ledger_dir or LEDGER.ledger_dir(),
                       f"ai_calls_{glob.escape(session)}_*.jsonl")))
    found, errors = [], []
    for path in paths:
        rows, problems = read_rows(path)
        errors.extend(problems)
        for row, location in rows:
            if row.get("session_id") != session:
                errors.append(f"{path}:{location['line']}: session identity mismatch")
                continue
            if row.get("schema_version") != LEDGER.LEDGER_SCHEMA:
                errors.append(f"{path}:{location['line']}: unsupported ledger schema")
                continue
            # Invalid token rows remain requests, but cannot crash the canonical
            # summarizer or be costed as zeros. Their totals become UNKNOWN.
            found.append((row, location))
    found.sort(key=lambda r: str(r[0].get("at_utc") or ""))
    rows = [r for r, _ in found]
    result = dict(session=session, ledger_files=paths, evidence_errors=errors,
        evidence_status="MISSING" if not paths else "PARTIAL" if errors else "PRESENT",
        summary=None, cost=None,
        observation="Counts describe durable request rows, not provider invoice completeness.",
        interpretation="No inference of wasted, unnecessary, or avoidable calls.")
    if paths:
        try:
            summary = LEDGER.summarize(rows)
        except (ValueError, TypeError, OverflowError):
            # Preserve request classification; do not fabricate token totals.
            token_keys = ("prompt_tokens", "cached_tokens", "uncached_input_tokens",
                          "cache_write_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
            safe = [{**r, **{k: 0 for k in token_keys}} for r in rows]
            summary = LEDGER.summarize(safe)
            for key in list(summary):
                if "token" in key or key in ("cache_hit_requests", "cache_miss_requests"):
                    summary[key] = None
            errors.append("Token/cache aggregates UNKNOWN: malformed recorded usage")
        per_scan = defaultdict(list)
        for row, location in found:
            if row.get("scan") is not None:
                per_scan[str(row["scan"])].append(dict(location,
                    role=row.get("brain_role"), purpose=row.get("call_purpose"),
                    attempt=row.get("attempt"), at_utc=row.get("at_utc"),
                    client_request_id=row.get("client_request_id")))
        summary.update(
            fallback_bearing_requests=sum(bool(r.get("fallback_reason")) for r in rows),
            scans_with_ai_requests=len(per_scan),
            requests_without_scan_id=sum(r.get("scan") is None for r in rows),
            multi_request_scans={k: v for k, v in per_scan.items() if len(v) > 1},
            scans_with_multiple_requests=sum(len(v) > 1 for v in per_scan.values()),
            max_requests_on_identified_scan=max(map(len, per_scan.values()), default=0),
            repair_request_percentage=100 * summary["requests_repair"] / len(rows) if rows else 0,
            cache_hit_ratio=(summary["cache_hit_requests"] / len(rows)
                             if rows and summary["cache_hit_requests"] is not None else None),
            scan_identity_note="Unique recorded scan labels; process restarts may reuse numeric labels. Missing IDs are not a scan.")
        result["summary"] = summary
        cost = _costs(found)
        cost["status"] = "LOWER_BOUND" if cost["unpriced_requests"] or errors else "KNOWN_RECORDED_USAGE"
        cost["total_session_cost_usd"] = (None if cost["status"] == "LOWER_BOUND"
                                          else cost["known_priced_cost_usd"])
        cost["note"] = ("Known-priced subtotal/lower bound; total session cost UNKNOWN."
                        if cost["status"] == "LOWER_BOUND" else
                        "Cost of recorded returned usage using the canonical repository pricing table.")
        result["cost"] = cost
        if errors:
            result["evidence_status"] = "PARTIAL"

    path = retrieval_path or telemetry_path(session)
    retrieval = dict(path=path, status="MISSING", recorded_retrieval_scans=None,
        production_scan_count=None, requests_per_retrieval_scan=None,
        retrieval_scans_with_ai_activity=None, retrieval_scans_with_ai_percentage=None)
    if os.path.isfile(path):
        records, problems = read_rows(path)
        valid = [r for r, _ in records if r.get("session_id") == session and r.get("scan_id")]
        ids = {str(r["scan_id"]) for r in valid}
        complete = not problems and len(valid) == len(records) and len(ids) == len(valid)
        retrieval.update(status="PRESENT" if complete else "PARTIAL", errors=problems,
                         recorded_retrieval_scans=len(valid))
        if paths and complete and valid and not errors:
            retrieval["requests_per_retrieval_scan"] = len(rows) / len(valid)
            # Never join loop ordinals to timestamp-based snapshot IDs by order
            # or by equal counts. Only an explicit, matching identity proves it.
            links = [r.get("scan_id", r.get("scan")) for r in rows]
            if all(v is not None and str(v) in ids for v in links):
                active = len({str(v) for v in links})
                retrieval.update(retrieval_scans_with_ai_activity=active,
                    retrieval_scans_with_ai_percentage=100 * active / len(valid))
    retrieval["note"] = ("Retrieval records are not all loop iterations. Activity percentage is UNKNOWN without an exact durable scan-ID join.")
    result["retrieval"] = retrieval
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--ledger-dir")
    parser.add_argument("--retrieval-path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = audit(args.session, ledger_dir=args.ledger_dir,
                   retrieval_path=args.retrieval_path)
    if not args.json:
        print(f"AI USAGE AUDIT -- {args.session} -- READ-ONLY")
        print("OBSERVATION: missing evidence/null means UNKNOWN, never zero.")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
