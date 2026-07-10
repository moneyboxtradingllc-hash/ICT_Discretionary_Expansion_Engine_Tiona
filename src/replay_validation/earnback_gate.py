"""
ADAPT-LOOP-4 — Earn-Back Replay Gate (replay side, 2026-07-10).

A proposal may not be approved until this gate validates it. v1 checks (the
Counterfactual Decision Laboratory extends this with full session ablations):

  1. action is in the liftable set (adaptive layer's OWN restrictions only)
  2. evidence RE-VERIFIED from the current stores (not the snapshot taken at
     proposal time): suppression basis → scored >= MIN_RESOLVED and false-rate
     >= FALSE_RATE_MIN and the bucket's resolved shadow outcomes carry NET
     POSITIVE counterfactual R (we blocked more winner-R than loser-R);
     performance basis → trades >= MIN_TRADES, expectancy > 0, loss_streak == 0
  3. the restriction the proposal lifts is actually attributable to evidence
     (a lift of nothing is refused)

Writes the gate report onto the proposal (validated=true/false). Approval
remains a separate explicit act.

CLI: python -m replay_validation.earnback_gate --proposal EB_QQQ_...
"""
import json
import os

from adaptive_learning.earnback import (
    load_proposals, mark_validated, MIN_RESOLVED, FALSE_RATE_MIN, MIN_TRADES,
    _LIFTABLE,
)


def _net_false_suppression_r(symbol: str, dimension: str, key,
                             base_dir=None) -> "float | None":
    """Net counterfactual R across the bucket's RESOLVED shadow outcomes
    (suppression_resolved.jsonl): positive = our blocks cost R overall."""
    from deployment.data_paths import resolve
    root = base_dir or resolve("PERFORMANCE_TABLES_DIR", "data", "performance",
                               anchored=True)
    path = os.path.join(root, str(symbol).upper(), "suppression_resolved.jsonl")
    if not os.path.exists(path):
        return None
    net, n = 0.0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            dims = row.get("dimensions") or {}
            if str(dims.get(dimension)) != str(key):
                continue
            cost = row.get("suppression_cost")
            if isinstance(cost, (int, float)):
                net += float(cost)
                n += 1
    return round(net, 3) if n else None


def validate_proposal(symbol: str, proposal_id: str, base_dir=None) -> dict:
    """Re-verify a proposal against CURRENT evidence. Returns the gate report
    (also written onto the proposal)."""
    from adaptive_learning.performance_tables import load_symbol_tables
    from adaptive_learning.suppression_cost_engine import get_suppression_stats

    prop = next((p for p in load_proposals(symbol, base_dir)
                 if p["proposal_id"] == proposal_id), None)
    report = {"proposal_id": proposal_id, "passed": False, "checks": []}
    if prop is None:
        report["checks"].append("FAIL: proposal not found")
        return report
    dim, key, action = prop["dimension"], prop["key"], prop["action"]

    if action not in _LIFTABLE:
        report["checks"].append(f"FAIL: action '{action}' not liftable")
        mark_validated(symbol, proposal_id, report, base_dir)
        return report
    report["checks"].append(f"OK: action '{action}' is a liftable adaptive restriction")

    basis = (prop.get("evidence") or {}).get("basis")
    ok = False
    if basis == "suppression":
        sup = get_suppression_stats(symbol, dim, key, base_dir)
        scored = sup["correct_suppressions"] + sup["false_suppressions"]
        rate = (sup["false_suppressions"] / scored) if scored else 0.0
        net = _net_false_suppression_r(symbol, dim, key, base_dir)
        c1 = scored >= MIN_RESOLVED
        c2 = rate >= FALSE_RATE_MIN
        c3 = net is not None and net > 0
        report["checks"] += [
            f"{'OK' if c1 else 'FAIL'}: scored {scored} >= {MIN_RESOLVED}",
            f"{'OK' if c2 else 'FAIL'}: false rate {rate:.2f} >= {FALSE_RATE_MIN}",
            f"{'OK' if c3 else 'FAIL'}: net counterfactual R {net} > 0",
        ]
        ok = c1 and c2 and c3
    elif basis == "performance_recovery":
        b = (load_symbol_tables(symbol, base_dir) or {}).get(dim, {}).get(str(key)) or {}
        trades = int(b.get("trades", 0) or 0)
        exp = float(b.get("expectancy", 0.0) or 0.0)
        streak = int(b.get("loss_streak", 0) or 0)
        c1 = trades >= MIN_TRADES
        c2 = exp > 0
        c3 = streak == 0
        report["checks"] += [
            f"{'OK' if c1 else 'FAIL'}: trades {trades} >= {MIN_TRADES}",
            f"{'OK' if c2 else 'FAIL'}: expectancy {exp:+.2f} > 0",
            f"{'OK' if c3 else 'FAIL'}: loss_streak {streak} == 0",
        ]
        ok = c1 and c2 and c3
    else:
        report["checks"].append(f"FAIL: unknown evidence basis '{basis}'")

    report["passed"] = bool(ok)
    mark_validated(symbol, proposal_id, report, base_dir)
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Earn-back replay gate")
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--proposal", required=True)
    a = p.parse_args()
    r = validate_proposal(a.symbol, a.proposal)
    print(json.dumps(r, indent=1))
