"""Where the scan died — the whole chain on one line.

A scan that does not trade currently prints its top blocker, which tells you the
last thing that said no but not how far the read actually got. Those are very
different situations: "no directional authority at all" and "authority, setup,
and a confirmed trigger, held one scan short on age" both print as NO_TRADE.

On 2026-07-24 that distinction was the whole story. The lane reported NO_TRADE on
all 133 scans; underneath, decision_authority returned ready_for_execution on 7,
and at 09:42 the only thing standing between the bot and a trade was a setup age
of 1 against a requirement of 2. None of that was visible.

This walks the chain in the order the organism evaluates it and names the FIRST
stage that refused. Reads only what the gate already publishes as structured
fields — nothing here re-derives a verdict or parses a blocker string.

Pure. Never raises. No authority: it reports, it never decides.
"""
from __future__ import annotations

_OK, _NO, _NA = "ok", "no", "n/a"


def _stage(name, state, detail):
    return {"stage": name, "state": state, "detail": detail}


def _authority(snapshot):
    da = snapshot.get("directional_authority") or {}
    bias = str(da.get("bias") or "neutral").lower()
    src = da.get("source")
    if bias not in ("bullish", "bearish") or not src:
        return _stage("authority", _NO, "no live liquidity objective or PO3 delivery")
    short = str(src).split(".")[0]
    intact = "" if da.get("intact", True) else " (INVALIDATED)"
    return _stage("authority", _OK, f"{bias} via {short}{intact}")


def _qualification(snapshot):
    q = snapshot.get("qualification") or {}
    status = str(q.get("status") or "unknown").lower()
    score = q.get("opportunity_score")
    detail = f"{status}" + (f" score={score}" if score is not None else "")
    return _stage("qualification", _OK if status == "qualified" else _NO, detail)


def _playbook(snapshot):
    pb = (snapshot.get("playbook") or {}).get("selected_playbook") or "no_playbook"
    tool = (snapshot.get("toolbox") or {}).get("preferred_tool")
    if pb == "no_playbook":
        return _stage("playbook", _NO, "no playbook selected")
    return _stage("playbook", _OK, f"{pb}" + (f" / {tool}" if tool else ""))


def _decision(decision):
    d = str((decision or {}).get("decision") or "unknown")
    ready = d in ("ready_for_execution", "prepare_long", "prepare_short")
    return _stage("decision", _OK if ready else _NO, d)


def _setup(gate):
    actual = gate.get("setup_age_actual")
    effective = gate.get("setup_age_effective", actual)
    required = gate.get("setup_age_requirement")
    if required in (None, 0):
        return _stage("setup_age", _NA, "no age requirement")
    met = bool(gate.get("setup_age_requirement_met"))
    note = ""
    if gate.get("thesis_age_applied"):
        note = " (thesis age applied)"
    return _stage("setup_age", _OK if met else _NO,
                  f"{effective} of {required} scans{note}")


def _trigger(gate):
    required = gate.get("required_trigger_status")
    actual = gate.get("actual_trigger_status")
    if not required:
        return _stage("trigger", _NA, f"no requirement (actual={actual})")
    met = bool(gate.get("trigger_requirement_met"))
    return _stage("trigger", _OK if met else _NO, f"{actual} (need {required})")


def _risk(gate):
    checks = gate.get("authorization_checks") or {}
    if "risk_allows_trade" not in checks:
        return _stage("risk", _NA, "not evaluated")
    ok = bool(checks["risk_allows_trade"])
    return _stage("risk", _OK if ok else _NO, "allows" if ok else "blocked")


def _permissions(gate):
    """The six independent authorities that can each veto silently."""
    checks = gate.get("authorization_checks") or {}
    watched = {
        "regime_permission_allowed": "regime",
        "council_permits_trade": "council",
        "narrative_permits_trade": "narrative",
        "commander_permits_trade": "commander",
        "no_promoted_rule_block": "promoted_rule",
        "thesis_invalidation_ok": "thesis",
        "brain_authorship_ok": "brain_authorship",
        "lifecycle_allows_trade": "lifecycle",
        "setup_not_invalidated": "setup_valid",
    }
    refused = [label for key, label in watched.items() if checks.get(key) is False]
    if refused:
        return _stage("permissions", _NO, "refused by " + ", ".join(refused))
    return _stage("permissions", _OK, "all authorities permit")


def _gate(gate):
    if gate.get("allow_execution"):
        return _stage("gate", _OK, "authorized")
    status = gate.get("gate_status") or "blocked"
    if not gate.get("execution_enabled"):
        would = gate.get("would_authorize_if_enabled")
        return _stage("gate", _NO,
                      f"{status} (execution disabled; would_authorize={bool(would)})")
    return _stage("gate", _NO, str(status))


def funnel_trace(snapshot: dict, decision: dict, gate: dict) -> dict:
    """Walk the chain and name the first refusal.

    Returns {stages, stopped_at, reached, line}. `reached` counts stages passed
    before the first refusal — a cheap progress metric across a session.
    """
    try:
        snapshot = snapshot or {}
        gate = gate or {}
        stages = [
            _authority(snapshot),
            _qualification(snapshot),
            _playbook(snapshot),
            _decision(decision),
            _setup(gate),
            _trigger(gate),
            _risk(gate),
            _permissions(gate),
            _gate(gate),
        ]
        stopped = next((s for s in stages if s["state"] == _NO), None)
        reached = len([s for s in stages if s["state"] != _NO])

        marks = {_OK: "+", _NO: "x", _NA: "-"}
        line = " ".join(f"{s['stage']}{marks[s['state']]}" for s in stages)
        return {
            "stages": stages,
            "stopped_at": stopped["stage"] if stopped else None,
            "stopped_because": stopped["detail"] if stopped else None,
            "reached": reached,
            "authorized": bool(gate.get("allow_execution")),
            "line": line,
        }
    except Exception as exc:  # noqa: BLE001 — telemetry must never break a scan
        return {"stages": [], "stopped_at": "trace_error", "reached": 0,
                "stopped_because": str(exc), "authorized": False, "line": "trace_error"}


def funnel_console(trace: dict) -> str:
    """Two compact lines for the operator console."""
    if not trace:
        return ""
    if trace.get("authorized"):
        return "FUNNEL: " + trace["line"] + " -> AUTHORIZED"
    detail = trace.get("stopped_because") or ""
    at = trace.get("stopped_at") or "unknown"
    return (f"FUNNEL: {trace['line']}\n"
            f"        STOPPED AT {at.upper()}: {detail}")
