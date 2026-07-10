"""
ADAPT-LOOP-4 — Earn-Back Governance (2026-07-10).

The adaptive layer could only punish (DEFENSIVE_ONLY). Earn-back is the
symmetric, GOVERNED path by which a punished bucket recovers — with evidence,
a replay-gate validation, an EXPLICIT approval, and a mode ladder.

CONSTITUTION (inverted DEFENSIVE_ONLY, equally bounded):
  * a promotion may ONLY LIFT one of the adaptive layer's OWN per-bucket
    restrictions (trade_block / risk_reduction / confidence_penalty for one
    (dimension, key)); the ceiling is NEUTRAL — earn-back can never boost
    confidence, never exceed size 1.0x, never touch anything it didn't restrict
  * hard safety caps (risk $, max trades, daily loss, stops, FC-0B, broker) and
    CAPITAL locks are NOT earn-back targets, ever
  * proposals are GENERATED from evidence, VALIDATED by the replay gate, and
    APPLIED only after an explicit approval — no self-approval path exists
  * EARNBACK_MODE: off (default, byte-identical) | shadow (records what WOULD
    be lifted — the required first live stage) | enforce (approved promotions
    lift their restriction; every application is recorded for the effect ledger)

Evidence thresholds (a proposal requires ALL that apply):
  * suppression evidence: >= MIN_RESOLVED scored shadow outcomes for the bucket
    with false-suppression rate >= FALSE_RATE_MIN (we keep blocking winners)
  * or performance recovery: bucket expectancy > 0 across >= MIN_TRADES trades
    while a restriction is active
Store: data/performance/<SYM>/earnback_proposals.json
"""
import json
import os
from datetime import datetime, timezone

from deployment.data_paths import resolve

MIN_RESOLVED = 20
FALSE_RATE_MIN = 0.6
MIN_TRADES = 20

_LIFTABLE = ("trade_block", "risk_reduction", "confidence_penalty")
_FILE = "earnback_proposals.json"


def earnback_mode() -> str:
    m = os.getenv("EARNBACK_MODE", "off").lower().strip()
    return m if m in ("off", "shadow", "enforce") else "off"


def _store_path(symbol: str, base_dir=None) -> str:
    root = base_dir or resolve("PERFORMANCE_TABLES_DIR", "data", "performance",
                               anchored=True)
    d = os.path.join(root, str(symbol).upper())
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, _FILE)


def load_proposals(symbol: str, base_dir=None) -> list:
    try:
        with open(_store_path(symbol, base_dir), encoding="utf-8") as fh:
            return json.load(fh).get("proposals", [])
    except (OSError, json.JSONDecodeError):
        return []


def _save(symbol: str, proposals: list, base_dir=None):
    path = _store_path(symbol, base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated_at": datetime.now(timezone.utc).isoformat(),
                   "proposals": proposals}, fh, indent=1, default=str)
    os.replace(tmp, path)


def generate_proposals(symbol: str, base_dir=None) -> list:
    """Evidence scan → NEW proposals (status='proposed'; never self-approved).
    One proposal per (dimension, key, action); existing ids are not duplicated."""
    from adaptive_learning.performance_tables import load_symbol_tables
    from adaptive_learning.suppression_cost_engine import get_suppression_stats

    proposals = load_proposals(symbol, base_dir)
    known = {p["proposal_id"] for p in proposals}
    new = []
    tables = load_symbol_tables(symbol, base_dir) or {}
    for dim, buckets in tables.items():
        if not isinstance(buckets, dict):
            continue
        for key, b in buckets.items():
            if not isinstance(b, dict):
                continue
            trades = int(b.get("trades", 0) or 0)
            exp = float(b.get("expectancy", 0.0) or 0.0)
            streak = int(b.get("loss_streak", 0) or 0)
            sup = get_suppression_stats(symbol, dim, key, base_dir)
            scored = (sup["correct_suppressions"] + sup["false_suppressions"])
            false_rate = (sup["false_suppressions"] / scored) if scored else 0.0

            evidence, actions = None, []
            if scored >= MIN_RESOLVED and false_rate >= FALSE_RATE_MIN:
                evidence = {"basis": "suppression",
                            "scored": scored,
                            "false_rate": round(false_rate, 3),
                            "suppression": sup}
                actions = ["trade_block", "risk_reduction"]
            elif trades >= MIN_TRADES and exp > 0 and streak == 0:
                evidence = {"basis": "performance_recovery",
                            "trades": trades, "expectancy": exp}
                actions = ["risk_reduction", "confidence_penalty"]
            if not evidence:
                continue
            for action in actions:
                pid = f"EB_{symbol}_{dim}_{key}_{action}"
                if pid in known:
                    continue
                new.append({"proposal_id": pid, "symbol": symbol,
                            "dimension": dim, "key": str(key),
                            "action": action, "evidence": evidence,
                            "status": "proposed", "validated": False,
                            "created_at": datetime.now(timezone.utc).isoformat()})
                known.add(pid)
    if new:
        _save(symbol, proposals + new, base_dir)
    return new


def set_status(symbol: str, proposal_id: str, status: str,
               approved_by: str = None, base_dir=None,
               validated: bool = None) -> bool:
    """approve/reject/retire — approval REQUIRES prior replay-gate validation."""
    proposals = load_proposals(symbol, base_dir)
    for p in proposals:
        if p["proposal_id"] != proposal_id:
            continue
        if status == "approved":
            if not p.get("validated"):
                return False          # no approval without the replay gate
            p["approved_by"] = approved_by or "unspecified"
            p["approved_at"] = datetime.now(timezone.utc).isoformat()
        if validated is not None:
            p["validated"] = bool(validated)
        p["status"] = status
        _save(symbol, proposals, base_dir)
        return True
    return False


def mark_validated(symbol: str, proposal_id: str, gate_report: dict,
                   base_dir=None) -> bool:
    proposals = load_proposals(symbol, base_dir)
    for p in proposals:
        if p["proposal_id"] == proposal_id:
            p["validated"] = bool(gate_report.get("passed"))
            p["gate_report"] = gate_report
            _save(symbol, proposals, base_dir)
            return p["validated"]
    return False


def active_promotions(symbol: str, base_dir=None) -> dict:
    """{(dimension, key): set(actions)} for APPROVED proposals only."""
    out = {}
    for p in load_proposals(symbol, base_dir):
        if p.get("status") == "approved" and p.get("action") in _LIFTABLE:
            out.setdefault((p["dimension"], str(p["key"])), set()).add(p["action"])
    return out


def earnback_check(symbol: str, dimension: str, key, action: str,
                   base_dir=None) -> dict:
    """The policy engine's consult. Returns
    {lift: bool, shadow_lift: bool, mode, promoted}. lift=True ONLY in enforce
    mode with an approved promotion; shadow mode records without lifting."""
    mode = earnback_mode()
    rec = {"lift": False, "shadow_lift": False, "mode": mode, "promoted": False}
    try:
        if mode == "off" or action not in _LIFTABLE:
            return rec
        promoted = action in active_promotions(symbol, base_dir).get(
            (dimension, str(key)), set())
        rec["promoted"] = promoted
        if not promoted:
            return rec
        if mode == "enforce":
            rec["lift"] = True
        else:
            rec["shadow_lift"] = True
        return rec
    except Exception:  # noqa: BLE001 — governance failure = no lift, never a crash
        return rec


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ADAPT-LOOP-4 earn-back governance")
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--generate", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--approve", help="proposal id (requires prior validation)")
    p.add_argument("--reject", help="proposal id")
    p.add_argument("--by", default="cli")
    a = p.parse_args()
    if a.generate:
        out = generate_proposals(a.symbol)
        print(f"new proposals: {len(out)}")
        for x in out:
            print(" ", x["proposal_id"], x["evidence"]["basis"])
    if a.approve:
        ok = set_status(a.symbol, a.approve, "approved", approved_by=a.by)
        print("approved" if ok else "REFUSED (not found or not validated)")
    if a.reject:
        print("rejected" if set_status(a.symbol, a.reject, "rejected") else "not found")
    if a.list or not any((a.generate, a.approve, a.reject)):
        for x in load_proposals(a.symbol):
            print(f"{x['proposal_id']:60} {x['status']:9} validated={x.get('validated')}")
