"""
Phase FC-1 — Promoted-Rule Enforcement Path.

The shadow plane (5H) records what rules WOULD have done; this module is the
enforcement_ref where promoted rules actually do it. June 11 evidence: R-001
fired "compound hostility (3)" two seconds after order submission on a trade
that resolved -1.34R — and fired again on the 13:17 trade the same day.

Wiring:
  - PROMOTED_RULES (csv env, default "R-001") names the rules with blocking
    authority. RULE_GOVERNANCE_MODE=enforce arms the path; default "shadow"
    is bit-for-bit pre-FC behavior.
  - rule_id -> predicate_id resolves through the same registry and the same
    predicate library the shadow evaluator uses. Same context, same
    deterministic predicate — the ledger record and the gate decision can
    never disagree.
  - The divergence ledger keeps recording every fire (shadow AND enforced):
    promotion does not stop the measurement that justifies demotion.

Constitution:
  - Reads SharedMarketContext only (snapshot["shared_context"]).
  - Never raises; any failure returns a non-blocking result (fail-open —
    a broken predicate must not halt trading; it gets fixed, not obeyed).

Rollback: RULE_GOVERNANCE_MODE=shadow (or remove a rule from PROMOTED_RULES).
"""
import os

from rule_governance.predicates import get_predicate
from rule_governance.rule_registry import load_registry

# Fallback map: rules promotable even if the registry file is unavailable.
_BUILTIN_PREDICATE_IDS = {
    "R-001": "regime_environmental_compound_v1",
}


def _mode() -> str:
    mode = os.getenv("RULE_GOVERNANCE_MODE", "shadow").lower().strip()
    return mode if mode in ("shadow", "enforce") else "shadow"


def _promoted_ids() -> list:
    raw = os.getenv("PROMOTED_RULES", "R-001")
    return [r.strip().upper() for r in raw.split(",") if r.strip()]


def _predicate_id_for(rule_id: str) -> "str | None":
    try:
        registry = load_registry() or {}
        for rule in registry.get("rules", []):
            if (rule.get("rule_id") or "").upper() == rule_id:
                return rule.get("predicate_id")
    except Exception:  # noqa: BLE001
        pass
    return _BUILTIN_PREDICATE_IDS.get(rule_id)


def evaluate_promoted_rules(ctx: dict) -> dict:
    """
    Evaluate promoted rules against the SharedMarketContext.

    Returns:
      {"enforced": bool, "blocked": bool,
       "fired": [{"rule_id", "reason"}...], "promoted_rules": [...]}
    Never raises.
    """
    try:
        if _mode() != "enforce":
            return {"enforced": False, "blocked": False, "fired": [],
                    "promoted_rules": _promoted_ids()}

        fired = []
        for rule_id in _promoted_ids():
            predicate_id = _predicate_id_for(rule_id)
            predicate    = get_predicate(predicate_id) if predicate_id else None
            if predicate is None:
                continue   # unknown rule: fail-open, never block on config drift
            rule_fired, reason = predicate(ctx or {})
            if rule_fired:
                fired.append({"rule_id": rule_id, "reason": reason})

        return {
            "enforced":       True,
            "blocked":        bool(fired),
            "fired":          fired,
            "promoted_rules": _promoted_ids(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"enforced": False, "blocked": False, "fired": [],
                "promoted_rules": [],
                "error": f"promoted rule evaluation error (fail-open): {exc}"}
