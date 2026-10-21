"""analyze_rehearsal.py <clone> <shard_dir> <out_dir>: merge traces; per gate module, functions defined vs reached."""
import ast, json, sys
from pathlib import Path
clone, shards, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
GATES = {  # Maurice's rehearsal categories -> production modules that implement them
 "entrypoint / startup refusals / window / shutdown": ["tools/topstepx_production_session.py"],
 "production loop (scan, campaign, Brain, candidate, route)": ["src/broker/topstepx_production_loop.py", "src/live_scan/production_scan_cycle.py"],
 "conditional plan / zero-new-Brain trigger / final quote": ["src/broker/conditional_plan_authority.py", "src/live_scan/wake_registry.py"],
 "arming / authorization / mission limits": ["src/broker/topstepx_session_authorization.py", "src/broker/topstepx_mission_state.py",
                                             "src/broker/topstepx_mission_recovery.py", "src/broker/topstepx_mission_reconciler.py"],
 "order gate / venue submission": ["src/broker/topstepx_execution_runner.py", "src/broker/topstepx_production_session.py",
                                   "src/broker/topstepx_live_session.py", "src/broker/topstepx_client.py"],
 "risk (daily loss, combine, protection, sizing)": ["src/broker/daily_loss_budget.py", "src/broker/topstepx_combine_risk.py",
                                                    "src/broker/topstepx_protection_authority.py", "src/broker/protection_state.py"],
 "stale data / freshness / cognition lock / restart": ["src/broker/topstepx_candidate_freshness.py", "src/broker/topstepx_session_cognition_lock.py",
                                                       "src/broker/topstepx_session_ledger.py", "src/broker/topstepx_session_lifecycle.py"],
 "emergency stop / hard flatten / safe shutdown": ["src/broker/topstepx_hard_flatten.py", "src/broker/topstepx_emergency_liquidation.py"],
}
hits, connects, exits = {}, [], {}
for t in sorted(shards.glob("shard_*.trace.json")):
    d = json.loads(t.read_text())
    exits[t.name] = d["exitstatus"]
    connects += d["connects"]
    for k, v in d["function_first_hit"].items():
        hits.setdefault(k, v)
def defined(rel):
    p = clone / rel
    if not p.exists():
        return None
    names = []
    def walk(node, prefix):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + n.name
                names.append(q); walk(n, q + ".<locals>.")
            elif isinstance(n, ast.ClassDef):
                walk(n, prefix + n.name + ".")
    walk(ast.parse(p.read_text()), "")
    return names
table, lines = {}, []
for cat, mods in GATES.items():
    for rel in mods:
        names = defined(rel)
        if names is None:
            table[rel] = {"category": cat, "missing_module": True}; continue
        top = [n for n in names if ".<locals>." not in n]
        reached = {n: hits[f"{rel}::{n}"] for n in top if f"{rel}::{n}" in hits}
        table[rel] = {"category": cat, "functions": len(top), "reached": len(reached),
                      "unreached": sorted(set(top) - set(reached)), "first_test": reached}
        lines.append(f"{cat} | {rel} | {len(reached)}/{len(top)} reached")
summary = {"shard_exitstatus": exits, "connect_attempts": len(connects),
           "refused_non_loopback": sum(c["refused"] for c in connects),
           "by_kind": {k: sum(1 for c in connects if c["kind"] == k) for k in sorted({c["kind"] for c in connects})},
           "refused_examples": [c for c in connects if c["refused"]][:20],
           "dead_proxy_examples": [c for c in connects if c["kind"] == "loopback_dead_proxy_port_9"][:20],
           "production_functions_reached": len(hits)}
(out / "REHEARSAL_GATE_COVERAGE.json").write_text(json.dumps(table, indent=1))
(out / "REHEARSAL_NETWORK.json").write_text(json.dumps({"summary": summary, "connects": connects}, indent=1))
(out / "REHEARSAL_FUNCTION_FIRST_HIT.json").write_text(json.dumps(dict(sorted(hits.items())), indent=1))
print(json.dumps(summary, indent=1)[:3000]); print("\n".join(lines))
