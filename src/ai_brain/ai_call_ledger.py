"""One durable row per outbound OpenAI request. Primary, shadow and repairs.

The 2026-08-10 usage audit could prove 116 of 175 dashboard requests. The
primary brain writes a per-scan artifact, so its calls were countable -- but:

  * a scan artifact is per SCAN, not per REQUEST. The repair paths can add up
    to three more calls to the same scan, and they would have hidden inside one
    artifact.
  * the shadow adjudicator wrote NOTHING. Its accounting lived in a module-level
    dict that died with the process. Up to 36 paid calls left no trace, and an
    offline reconstruction could only estimate ~17 of them.
  * no request carried an id, so no local row could ever be matched to a
    dashboard line or quoted to support.

So this ledger is deliberately per-REQUEST, written by the call site itself,
and it records the identity fields that make a row reconcilable:

    local client request id   ours, generated BEFORE the call, so a timeout
                              still leaves something to match on
    x-request-id              OpenAI's, read off the response headers

It also records the token CLASSES separately -- uncached input, cached input,
cache writes, output, reasoning -- because they are billed at different rates
and a single "prompt_tokens" number cannot be costed honestly. Nothing here
computes dollars; `ai_brain.model_pricing` is the single source for that.

NOTHING IN THIS MODULE MAY COST A CALL. Every write swallows its own failure
and no function returns a value any caller acts on. An accounting bug must
never be able to retry a request or block a trade.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid

LEDGER_SCHEMA = "ai_call.v1"

# ── roles and purposes ────────────────────────────────────────────────────────
PRIMARY = "primary"
SHADOW = "shadow"

PURPOSE_PRIMARY = "primary"
PURPOSE_JSON_REPAIR = "json_repair"
PURPOSE_FAMILY_REPAIR = "family_repair"
PURPOSE_INVALIDATION_REPAIR = "invalidation_repair"
PURPOSE_ADJUDICATION = "adjudication"

#: Bumped when the STABLE PREFIX changes in a way that must invalidate reuse.
#: Not the schema of this ledger -- the doctrine text the model actually reads.
PROMPT_DOCTRINE_VERSION = "2026-08-10.1"

CLIENT_REQUEST_HEADER = "X-Client-Request-Id"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def ledger_dir() -> str:
    return os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))


def ledger_path(session_id: str = "") -> str:
    day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    name = f"ai_calls_{session_id or 'UNSCOPED'}_{day}.jsonl"
    return os.path.join(ledger_dir(), name)


# ── identity ──────────────────────────────────────────────────────────────────
def new_client_request_id(*, session_id: str = "", scan: object = None,
                          role: str = PRIMARY, purpose: str = PURPOSE_PRIMARY,
                          attempt: int = 1) -> str:
    """A unique id we own, generated BEFORE the request leaves.

    Carries no account identifier and no secret -- it goes out as a header, so
    it holds only what is safe to hand a third party: which session, which scan,
    which brain, which purpose, which attempt, plus entropy.
    """
    stem = f"{session_id or 'nosess'}-s{scan if scan is not None else 'x'}"
    return f"{stem}-{role}-{purpose}-a{int(attempt)}-{uuid.uuid4().hex[:8]}"


def cache_key(*, role: str = PRIMARY, model: str = "",
              doctrine_version: str = PROMPT_DOCTRINE_VERSION,
              schema_version: str = "") -> str:
    """A STABLE key shared by every request with the same stable prefix.

    Deliberately excludes session id, scan number and timestamps: including any
    of them would give every request its own key and destroy the reuse this
    exists to create. Primary and shadow get different keys because their
    system prompts are different texts.
    """
    parts = [role, model or "model", doctrine_version]
    if schema_version:
        parts.append(schema_version)
    return "expbot-" + "-".join(str(p) for p in parts)


# ── usage decomposition ───────────────────────────────────────────────────────
def usage_breakdown(usage) -> dict:
    """Split a usage object into separately-billed token classes.

    Handles both the SDK object and a plain dict. Reasoning tokens are reported
    but NOT added to anything: OpenAI already counts them inside
    `completion_tokens`, and adding them again would inflate every later cost
    estimate built on this row.
    """
    def get(obj, name, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    prompt = get(usage, "prompt_tokens") or 0
    completion = get(usage, "completion_tokens") or 0
    pdet = get(usage, "prompt_tokens_details")
    cdet = get(usage, "completion_tokens_details")
    cached = get(pdet, "cached_tokens") or 0
    # Named differently across API surfaces; accept either rather than lose it.
    cache_write = (get(pdet, "cache_write_tokens")
                   or get(usage, "cache_write_tokens") or 0)
    reasoning = get(cdet, "reasoning_tokens")
    return {
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "uncached_input_tokens": max(prompt - cached, 0),
        "cache_write_tokens": cache_write,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": get(usage, "total_tokens") or (prompt + completion),
    }


def server_request_id(raw_response, response=None) -> str:
    """OpenAI's `x-request-id`, wherever this SDK version exposes it."""
    for source in (raw_response, response):
        if source is None:
            continue
        headers = getattr(source, "headers", None)
        if headers is not None:
            try:
                value = headers.get("x-request-id") or headers.get("X-Request-Id")
                if value:
                    return str(value)
            except Exception:  # noqa: BLE001
                pass
        for attr in ("request_id", "_request_id"):
            value = getattr(source, attr, None)
            if value:
                return str(value)
    return ""


# ── the write ─────────────────────────────────────────────────────────────────
def record(*, session_id: str = "", scan: object = None, role: str = PRIMARY,
           purpose: str = PURPOSE_PRIMARY, attempt: int = 1,
           model_requested: str = "", model_returned: str = "",
           client_request_id: str = "", request_id: str = "",
           response_id: str = "", usage=None, ok: bool = True,
           fallback_reason: str = "", latency_seconds: float = None,
           prompt_cache_key: str = "", cache_mode: str = "",
           extra: dict = None) -> dict:
    """Append one row. Never raises, never returns anything a gate reads."""
    row = {
        "schema_version": LEDGER_SCHEMA,
        "at_utc": _now(),
        "session_id": session_id,
        "scan": scan,
        "brain_role": role,
        "call_purpose": purpose,
        "attempt": int(attempt),
        "model_requested": model_requested,
        "model_returned": model_returned,
        "client_request_id": client_request_id,
        "request_id": request_id,
        "response_id": response_id,
        "ok": bool(ok),
        "fallback_reason": fallback_reason or None,
        "latency_seconds": (round(float(latency_seconds), 3)
                            if latency_seconds is not None else None),
        "prompt_cache_key": prompt_cache_key or None,
        "cache_mode": cache_mode or None,
        "doctrine_version": PROMPT_DOCTRINE_VERSION,
    }
    row.update(usage_breakdown(usage))
    if extra:
        row.update({k: v for k, v in extra.items() if k not in row})
    try:
        directory = ledger_dir()
        os.makedirs(directory, exist_ok=True)
        with open(ledger_path(session_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
    except Exception:  # noqa: BLE001 — accounting may never cost a call
        pass
    return row


# ── reading it back ───────────────────────────────────────────────────────────
def load(session_id: str = "", path: str = "") -> list:
    try:
        with open(path or ledger_path(session_id), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def summarize(rows: list) -> dict:
    """Counts and token classes, split the way they are actually billed."""
    rows = rows or []
    def total(key):
        return sum(int(r.get(key) or 0) for r in rows)

    by_role, by_purpose, by_model = {}, {}, {}
    for r in rows:
        by_role[r.get("brain_role")] = by_role.get(r.get("brain_role"), 0) + 1
        by_purpose[r.get("call_purpose")] = by_purpose.get(r.get("call_purpose"), 0) + 1
        m = r.get("model_returned") or r.get("model_requested")
        by_model[m] = by_model.get(m, 0) + 1
    hits = [r for r in rows if int(r.get("cached_tokens") or 0) > 0]
    prompt = total("prompt_tokens")
    # Per-scan concentration: a scan that quietly made four requests is the
    # thing an aggregate count hides, and it is exactly what the repair paths
    # can create.
    per_scan = {}
    for r in rows:
        key = (r.get("session_id"), r.get("scan"))
        per_scan[key] = per_scan.get(key, 0) + 1
    repair_scans = {(r.get("session_id"), r.get("scan")) for r in rows
                    if str(r.get("call_purpose") or "").endswith("_repair")}
    return {
        "requests_total": len(rows),
        "requests_primary": by_role.get(PRIMARY, 0),
        "requests_shadow": by_role.get(SHADOW, 0),
        # the exact per-purpose breakdown a cost audit needs
        "primary_calls": by_purpose.get(PURPOSE_PRIMARY, 0),
        "json_repair_calls": by_purpose.get(PURPOSE_JSON_REPAIR, 0),
        "family_repair_calls": by_purpose.get(PURPOSE_FAMILY_REPAIR, 0),
        "invalidation_repair_calls": by_purpose.get(PURPOSE_INVALIDATION_REPAIR, 0),
        "repair_calls_total": sum(v for k, v in by_purpose.items()
                                  if k and k.endswith("_repair")),
        "shadow_calls": by_role.get(SHADOW, 0),
        "total_ai_calls": len(rows),
        "scans_with_repairs": len(repair_scans),
        "max_ai_calls_observed_single_scan": max(per_scan.values()) if per_scan else 0,
        "requests_repair": sum(v for k, v in by_purpose.items()
                               if k and k.endswith("_repair")),
        "requests_failed": len([r for r in rows if not r.get("ok")]),
        "by_role": by_role, "by_purpose": by_purpose, "by_model": by_model,
        "input_tokens_total": prompt,
        "cached_input_tokens": total("cached_tokens"),
        "uncached_input_tokens": total("uncached_input_tokens"),
        "cache_write_tokens": total("cache_write_tokens"),
        "output_tokens": total("completion_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "total_tokens": total("total_tokens"),
        "cache_hit_requests": len(hits),
        "cache_miss_requests": len(rows) - len(hits),
        "cache_hit_ratio_by_tokens": (round(total("cached_tokens") / prompt, 4)
                                      if prompt else 0.0),
    }
