"""
Phase 5H.2 — Shadow Evaluator.

Evaluates every active shadow rule against the SharedMarketContext each scan
and builds divergence-ledger event records.

OBSERVE-ONLY BY CONSTRUCTION (constitutional, immutable):
  - This module is called AFTER the execution gate and paper execution have
    fully settled. Nothing downstream reads its output.
  - There is NO enforce-mode flag and never will be. Promotion is a
    human-reviewed code change to the enforcement layer, not a switch here.
  - Never raises — any failure degrades to a warning field, never to a scan
    failure and never to an execution change.

Opportunity definition:
  A scan is an OPPORTUNITY iff execution_gate.would_authorize_if_enabled is
  True. Rules are evaluated every scan for rate statistics, but only
  opportunity-scan firings create scoreable ledger events — a candidate that
  duplicates an existing 5F block never collects a sample (the champion
  blocks those scans first), so redundant legislation starves and dies.
"""
import os
from datetime import datetime

import pytz

from rule_governance.predicates import get_predicate
from rule_governance.rule_registry import active_rules

_EASTERN   = pytz.timezone("America/New_York")
_AUTHORITY = "observe_only"


def _enabled() -> bool:
    return os.getenv("RULE_GOVERNANCE_ENABLED", "true").lower().strip() == "true"


def _council_digest(snapshot: dict) -> list:
    """Compact member-vote record for later calibration scoring."""
    out = []
    for m in (snapshot.get("council", {}) or {}).get("members", []):
        out.append({
            "member":     m.get("member"),
            "vote":       m.get("vote"),
            "confidence": m.get("confidence"),
        })
    return out


def evaluate_shadow_rules(snapshot: dict, symbol: str) -> dict:
    """
    Phase 5H.2 — Evaluate shadow rules for this scan.
    Returns the rule_governance dict stored on the snapshot, including the
    event records for the divergence ledger. Never raises.
    """
    try:
        return _evaluate(snapshot or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled":         True,
            "authority_level": _AUTHORITY,
            "evaluated":       0,
            "fired":           [],
            "opportunity":     False,
            "events":          [],
            "warning":         f"shadow evaluation error: {exc}",
        }


def _evaluate(snapshot: dict, symbol: str) -> dict:
    if not _enabled():
        return {
            "enabled":         False,
            "authority_level": _AUTHORITY,
            "evaluated":       0,
            "fired":           [],
            "opportunity":     False,
            "events":          [],
        }

    ctx  = snapshot.get("shared_context", {}) or {}
    gate = snapshot.get("execution_gate", {}) or {}
    pe   = snapshot.get("paper_execution", {}) or {}
    ti   = snapshot.get("trade_intent", {}) or {}

    opportunity = bool(gate.get("would_authorize_if_enabled", False))
    executed    = (pe.get("status") or "") == "submitted"
    trade_id    = pe.get("trade_id")
    intent_id   = ti.get("intent_id")

    now_str = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    # Only predicate-bearing rules are evaluated here. Shadow management
    # policies (5T, rule_class=management_policy) carry no context predicate —
    # they are measured by the management ledger, not this evaluator.
    rules  = [
        r for r in active_rules("shadow")
        if symbol in r.get("scope", []) and r.get("predicate_id")
    ]
    fired  = []
    events = []

    for rule in rules:
        predicate = get_predicate(rule.get("predicate_id"))
        if predicate is None:
            continue  # registry validation should prevent this; belt and braces

        rule_fired, reason = predicate(ctx)
        if rule_fired:
            fired.append(rule["rule_id"])

        # Only opportunity-scan firings are scoreable events (see module doc).
        if rule_fired and opportunity:
            events.append({
                "event_id":          f"EV_{symbol}_{now_str}_{rule['rule_id']}",
                "rule_id":           rule["rule_id"],
                "predicate_version": rule.get("predicate_id"),
                "symbol":            symbol,
                "timestamp":         now_str,
                "fired":             True,
                "fire_reason":       reason,
                "opportunity":       True,
                "executed":          executed,
                "trade_id":          trade_id,
                "intent_id":         intent_id,
                "context_digest":    dict(ctx),
                "council_digest":    _council_digest(snapshot),
                "resolution":        {"state": "pending"},
            })

    return {
        "enabled":         True,
        "authority_level": _AUTHORITY,
        "evaluated":       len(rules),
        "fired":           fired,
        "opportunity":     opportunity,
        "executed":        executed,
        "events":          events,
    }
