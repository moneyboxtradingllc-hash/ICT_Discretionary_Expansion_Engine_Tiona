"""
Phase 5H.1 — Candidate Rule Registry.

The law book. Governance STATE lives here as data (auditable, restart-safe);
rule LOGIC lives in predicates.py as code (testable, reviewable).

Record shape:
  rule_id, name, predicate_id, sponsor, rule_class, status, created,
  review_by, scope, evidence_refs, notes
  (+ enforcement_ref for promoted/grandfathered records)

INVARIANTS:
  - review_by is MANDATORY for every record. No review date -> record invalid.
  - status "shadow" requires a predicate that exists in the library.
  - status "promoted"/"grandfathered" requires enforcement_ref (where the law
    is enforced in code) — these records are monitored, not evaluated.
  - Local-truth sponsors (QUALIFICATION, TOOLBOX) may only sponsor
    "annotation" rules — never "blocking_candidate".
  - Legal transitions only:
      shadow       -> promoted | retired
      promoted     -> retired
      grandfathered-> retired
    retired is terminal. Re-legislation requires a NEW rule_id.
  - Promotion remains a human-reviewed code change; transition_rule() only
    flips registry status and records the evidence reference.

Never raises: invalid records are quarantined with reasons, not fatal.
"""
import json
import os
from datetime import datetime

from rule_governance.predicates import predicate_exists

_VALID_STATUS    = frozenset({"shadow", "promoted", "grandfathered", "retired"})
_BLOCKING_SPONSORS = frozenset({"REGIME", "DELIVERY", "RISK", "OPPORTUNITY"})
_VALID_CLASSES   = frozenset({"blocking_candidate", "annotation"})

_LEGAL_TRANSITIONS = {
    "shadow":        frozenset({"promoted", "retired"}),
    "promoted":      frozenset({"retired"}),
    "grandfathered": frozenset({"retired"}),
    "retired":       frozenset(),
}

_REQUIRED_FIELDS = (
    "rule_id", "name", "sponsor", "rule_class", "status",
    "created", "review_by", "scope",
)


def _registry_dir() -> str:
    return os.getenv(
        "RULE_GOVERNANCE_DIR",
        os.path.join("data", "rule_governance"),
    )


def registry_path() -> str:
    return os.path.join(_registry_dir(), "registry.json")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_record(rec: dict) -> tuple:
    """Returns (ok: bool, reason: str)."""
    if not isinstance(rec, dict):
        return False, "record is not a dict"

    for field in _REQUIRED_FIELDS:
        if not rec.get(field):
            return False, f"missing required field '{field}'"

    status = rec.get("status")
    if status not in _VALID_STATUS:
        return False, f"invalid status '{status}'"

    rule_class = rec.get("rule_class")
    if rule_class not in _VALID_CLASSES:
        return False, f"invalid rule_class '{rule_class}'"

    sponsor = rec.get("sponsor", "")
    if rule_class == "blocking_candidate" and sponsor not in _BLOCKING_SPONSORS:
        return False, (
            f"sponsor '{sponsor}' may not sponsor blocking_candidate rules "
            "(local-truth members sponsor annotations only)"
        )

    if status == "shadow":
        pid = rec.get("predicate_id")
        if not predicate_exists(pid):
            return False, f"shadow rule requires a library predicate (got '{pid}')"

    if status in ("promoted", "grandfathered"):
        if not rec.get("enforcement_ref"):
            return False, f"{status} rule requires enforcement_ref"

    if not isinstance(rec.get("scope"), list) or not rec["scope"]:
        return False, "scope must be a non-empty list of symbols"

    return True, "ok"


# ── Load / save ───────────────────────────────────────────────────────────────

def load_registry() -> dict:
    """
    Load and validate the registry.
    Returns {"rules": [valid records], "quarantined": [(rule_id, reason)],
             "loaded": bool, "path": str}.
    Never raises.
    """
    path = registry_path()
    result = {"rules": [], "quarantined": [], "loaded": False, "path": path}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        result["quarantined"].append(("<registry>", "registry file not found"))
        return result
    except (OSError, json.JSONDecodeError) as exc:
        result["quarantined"].append(("<registry>", f"registry unreadable: {exc}"))
        return result

    seen_ids = set()
    for rec in data.get("rules", []):
        ok, reason = validate_record(rec)
        rid = rec.get("rule_id", "<missing>") if isinstance(rec, dict) else "<bad>"
        if not ok:
            result["quarantined"].append((rid, reason))
            continue
        if rid in seen_ids:
            result["quarantined"].append((rid, "duplicate rule_id"))
            continue
        seen_ids.add(rid)
        result["rules"].append(rec)

    result["loaded"] = True
    return result


def active_rules(status: str = "shadow") -> list:
    """Valid rules with the given status. Never raises."""
    return [r for r in load_registry()["rules"] if r.get("status") == status]


def _save(rules: list) -> bool:
    """Atomic write of the full registry. Never raises."""
    path = registry_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"rules": rules}, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ── Transitions ───────────────────────────────────────────────────────────────

def transition_rule(rule_id: str, new_status: str, evidence_ref: str) -> dict:
    """
    Flip a rule's status (the data half of promotion/retirement).
    The code half — editing the enforcement layer — is a separate, human-
    reviewed commit. evidence_ref (e.g. a weekly report path) is mandatory.
    Returns {"ok": bool, "reason": str}.
    """
    if not evidence_ref:
        return {"ok": False, "reason": "evidence_ref is mandatory for any transition"}

    reg = load_registry()
    if not reg["loaded"]:
        return {"ok": False, "reason": "registry could not be loaded"}

    rules = reg["rules"]
    rec = next((r for r in rules if r.get("rule_id") == rule_id), None)
    if rec is None:
        return {"ok": False, "reason": f"rule '{rule_id}' not found"}

    current = rec.get("status")
    if new_status not in _LEGAL_TRANSITIONS.get(current, frozenset()):
        return {
            "ok": False,
            "reason": f"illegal transition {current} -> {new_status}",
        }

    rec["status"] = new_status
    rec.setdefault("evidence_refs", []).append({
        "ref":        evidence_ref,
        "transition": f"{current}->{new_status}",
        "at":         datetime.now().strftime("%Y-%m-%d"),
    })

    if not _save(rules):
        return {"ok": False, "reason": "registry save failed"}
    return {"ok": True, "reason": f"{rule_id}: {current} -> {new_status}"}


def rules_near_review(days: int = 7) -> list:
    """Rules whose review_by falls within `days` (or already past). Never raises."""
    out = []
    today = datetime.now().date()
    for rec in load_registry()["rules"]:
        if rec.get("status") == "retired":
            continue
        try:
            review = datetime.strptime(rec["review_by"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if (review - today).days <= days:
            out.append({"rule_id": rec["rule_id"], "review_by": rec["review_by"],
                        "overdue": review < today})
    return out
