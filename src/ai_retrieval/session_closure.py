"""Two ways a production session can legitimately end, and what each must prove.

SUPPORT-OPERATOR-TERMINATED-SESSION-CLOSURE (2026-08-07).

The original authoring law demanded four launcher artifacts by NAME. That
conflated evidence with filenames. PROD-20260806 self-terminated at window
close and wrote all four; PROD-20260807 was stopped by the operator at 13:11 ET
with its stdout buffered to nothing, so it wrote none of them -- and a session
whose end state is fully knowable became unauthorable for a filing reason.

An operator stopping the bot is a normal lifecycle event, not an anomaly. What
the law actually needs is the INVARIANTS the four files happened to carry:

    the session stopped observing, at a known time
    final positions are known
    final working orders are known
    no execution context was left unresolved
    execution accounting is self-consistent
    the reason it ended is known
    the source evidence is durable

A native close proves those from artifacts the launcher wrote as it died. An
operator-terminated close proves them from durable independent evidence, in a
post-session attestation that says plainly that it was written afterwards, by a
forensic process, and not by the launcher.

The two classes never substitute for each other silently. An attestation that
claims NATIVE_LAUNCHER_CLOSE is rejected: only a launcher can make that claim,
and a launcher does not write attestations.
"""
from __future__ import annotations

import datetime as _dt

ATTESTATION_SCHEMA = "session_closure_attestation.v1"

NATIVE_LAUNCHER_CLOSE = "NATIVE_LAUNCHER_CLOSE"
OPERATOR_TERMINATED_CLOSE = "OPERATOR_TERMINATED_CLOSE"
CLOSURE_CLASSES = (NATIVE_LAUNCHER_CLOSE, OPERATOR_TERMINATED_CLOSE)

#: Only a running launcher can attest to its own clean exit. An attestation is
#: by definition post-mortem, so this class may never be claimed by one.
ATTESTABLE_CLASSES = (OPERATOR_TERMINATED_CLOSE,)

PROVEN_NATIVE = "PROVEN_NATIVE"
PROVEN_POST_SESSION = "PROVEN_POST_SESSION"
UNPROVEN = "UNPROVEN"

#: How each fact was established. Conflating these is how a forensic guess
#: becomes an observation.
OBSERVED_LIVE = "FACT_OBSERVED_LIVE"
VERIFIED_AFTER = "FACT_VERIFIED_AFTER_TERMINATION"
UNAVAILABLE = "FACT_UNAVAILABLE"

#: (key, description). Every one is load-bearing: authoring may not proceed
#: while any is UNPROVEN, in either closure class.
CLOSURE_INVARIANTS = (
    ("observation_ended", "the session stopped observing the market"),
    ("observation_end_known", "the time it stopped is known"),
    ("final_positions_known", "final open positions are known"),
    ("final_working_orders_known", "final working orders are known"),
    ("execution_context_resolved", "no execution token was left open"),
    ("execution_accounting_consistent", "fills and round trips agree"),
    ("termination_reason_known", "why the session ended is known"),
    ("source_evidence_durable", "the evidence survives outside the process"),
)

LOAD_BEARING = tuple(k for k, _ in CLOSURE_INVARIANTS)


class ClosureError(ValueError):
    """The attestation is malformed or claims something it may not claim."""


def _parse(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def validate_attestation(att: dict, *, now: _dt.datetime = None) -> list:
    """Structural and honesty checks. Returns a list of reasons; empty is good."""
    reasons = []
    att = att or {}
    if att.get("schema_version") != ATTESTATION_SCHEMA:
        reasons.append(f"schema_version must be {ATTESTATION_SCHEMA}")
    closure = att.get("closure_type")
    if closure not in CLOSURE_CLASSES:
        reasons.append(f"closure_type {closure!r} is not a known closure class")
    elif closure not in ATTESTABLE_CLASSES:
        # The whole point of the separation.
        reasons.append(
            f"{closure} cannot be attested post-session; only the launcher "
            f"itself can evidence a native close")
    if att.get("attestation_created_by") != "POST_SESSION_FORENSIC_PROCESS":
        reasons.append("attestation_created_by must name the forensic process")
    for field in ("session_id", "session_date", "runtime_head",
                  "observation_start_et", "observation_end_et",
                  "termination_reason", "attestation_created_at"):
        if not att.get(field):
            reasons.append(f"missing {field}")

    # An attestation describes a session that already ended. One stamped at or
    # before the observation it describes is either backdated or wrong.
    created = _parse(att.get("attestation_created_at"))
    if created is None:
        reasons.append("attestation_created_at is not a timestamp")
    else:
        if created.tzinfo is None:
            reasons.append("attestation_created_at must carry a timezone")
        now = now or _dt.datetime.now(_dt.timezone.utc)
        if created.tzinfo and created > now + _dt.timedelta(minutes=5):
            reasons.append("attestation_created_at is in the future")
        end = _parse(att.get("observation_end_utc") or "")
        if end is not None and created.tzinfo and end.tzinfo and created < end:
            reasons.append("attestation_created_at precedes the session end "
                           "it describes (backdated)")
    return reasons


def evaluate_invariants(att: dict) -> dict:
    """Per-invariant status for an operator-terminated close.

    Returns {invariant: {"status", "evidence", "source"}}. A fact whose
    provenance is UNAVAILABLE is UNPROVEN, however confidently it is asserted.
    """
    facts = (att or {}).get("facts") or {}
    out = {}
    for key, description in CLOSURE_INVARIANTS:
        fact = facts.get(key) or {}
        provenance = fact.get("provenance")
        has_value = "value" in fact and fact.get("value") is not None
        if has_value and provenance == OBSERVED_LIVE:
            status = PROVEN_NATIVE
        elif has_value and provenance == VERIFIED_AFTER:
            status = PROVEN_POST_SESSION
        else:
            status = UNPROVEN
        out[key] = {"status": status, "description": description,
                    "value": fact.get("value"), "provenance": provenance,
                    "evidence": fact.get("evidence"),
                    "source": fact.get("source")}
    return out


def closure_ok(att: dict, *, now: _dt.datetime = None) -> dict:
    """The whole decision: is this session closed well enough to describe?"""
    reasons = validate_attestation(att, now=now)
    invariants = evaluate_invariants(att) if not reasons else {}
    unproven = [k for k in LOAD_BEARING
                if invariants.get(k, {}).get("status", UNPROVEN) == UNPROVEN]
    if invariants and unproven:
        reasons.append(f"unproven_closure_invariants:{unproven}")
    return {"ok": not reasons, "reasons": reasons, "invariants": invariants,
            "unproven": unproven,
            "closure_type": (att or {}).get("closure_type"),
            "verdict": ("OPERATOR_TERMINATED_CLOSURE_SUFFICIENT" if not reasons
                        else "OPERATOR_TERMINATED_CLOSURE_INSUFFICIENT")}
