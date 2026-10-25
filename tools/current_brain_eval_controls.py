"""MOCK wiring and restraint controls over the sealed plan's constructed trajectories (zero provider calls).

    PYTHONPATH=src:tests python tools/current_brain_eval_controls.py --plan DIR/plan.json --out OUT

Each control runs one sealed CONSTRUCTED trajectory (same corpus, schedule,
CONTROLLED quotes and lane as the plan) in a fresh child under the fully
denying network guard, with a MOCK Brain script in place of the provider:

  W5_WIRING          the binding test's own mocked judgment (`_w5_reply`) on the
                     W5 bars: proves the harness can reach a real candidate at
                     T4 when the witnesses exist (participation wiring, not
                     cognition).
  PROPOSE_BEARISH /  an adversarial `propose_entry` in each direction at the
  PROPOSE_BULLISH    negative cases' single decision: the expected-restraint
                     basis is whatever real gate refuses it, read from the
                     producers' own lifecycle/path state at that tick.

Every row is MOCK: it says what the mechanics do with a scripted reply, never
what any model said or would say.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import eval_plan as EP  # noqa: E402

_PRELUDE = "import sys\nsys.path.insert(0, {tests!r})\nimport test_reversal_foundation_proof_closure as RF\n"
SCRIPTS = {
    "W5_WIRING": _PRELUDE + '''import test_campaign_scope_binding as B
from datetime import datetime
EXPIRES = datetime.fromisoformat({expires!r})
STATE = {{"n": 0}}


def script(request):
    payload = request["payload"]
    STATE["n"] += 1
    output = RF._valid_model_reply(payload)
    entry = (payload.get("market") or {{}}).get("current_price")
    return B._w5_reply(output, STATE["n"], payload, entry=entry, expires=EXPIRES)
''',
    "PROPOSE_BEARISH": _PRELUDE + '''

def script(request):
    return RF._valid_model_reply(request["payload"], action="propose_entry", direction="bearish")
''',
    "PROPOSE_BULLISH": _PRELUDE + '''

def script(request):
    return RF._valid_model_reply(request["payload"], action="propose_entry", direction="bullish")
''',
}
CONTROLS = (("W5-T2T3T4", "W5_WIRING"), ("C4-INTACT-RETRACE", "PROPOSE_BEARISH"),
            ("C4-INTACT-RETRACE", "PROPOSE_BULLISH"), ("C2-UNSUPPORTED-TRANSFER", "PROPOSE_BEARISH"),
            ("C2-UNSUPPORTED-TRANSFER", "PROPOSE_BULLISH"))


def _scan_rows(evidence: Path) -> list:
    from recognition_validation import recorder as REC
    rows = []
    for event in REC.read_events(evidence):
        if not event["event_kind"].startswith("SCAN:"):
            continue
        projection = next((json.loads((evidence / r["path"]).read_text()) for r in event["evidence_refs"]
                           if "layer_projection" in r["path"] or r.get("kind") == "layer_projection"), None)
        if projection is None:
            refs = event["evidence_refs"]
            projection = json.loads((evidence / refs[-1]["path"]).read_text()) if refs else {}
        layers = projection.get("layers") or {}
        delivery, composition = layers.get("DELIVERY") or {}, layers.get("COMPOSITION") or {}
        campaign = layers.get("CAMPAIGN") or {}
        rows.append({"decision_time": event["observed_at"], "settled_cutoff": event["settled_cutoff"],
                     "outcome": event["outcome"], "first_refusal_code": event["first_refusal_code"],
                     "candidate_present": bool(event.get("candidate_id")),
                     "primary_calls": event["primary_call_count"], "repair_calls": event["repair_call_count"],
                     "lifecycle_state": delivery.get("lifecycle_state"),
                     "lifecycle_reason": delivery.get("lifecycle_reason"), "path_owner": delivery.get("owner"),
                     "path_status": delivery.get("path_status"), "transfer_flags": delivery.get("transfer_flags"),
                     "last_invalidated": delivery.get("last_invalidated"),
                     "campaign_direction": campaign.get("direction"),
                     "campaign_authority_status": campaign.get("authority_status"),
                     "brain_direction": campaign.get("brain_direction"),
                     "tool_direction": (layers.get("TOOL") or {}).get("direction"),
                     "composition_outcome": composition.get("outcome")})
    return rows


def run_controls(plan_path, out: Path) -> dict:
    from recognition_validation import child as CH
    plan = EP.load_plan(plan_path)
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for session_id, name in CONTROLS:
        expires = None
        if name == "W5_WIRING":
            import test_campaign_scope as CS
            from datetime import datetime, timedelta
            expires = (datetime.fromisoformat(CS._tape()[98]["timestamp"]) + timedelta(minutes=5)).isoformat()
        script = out / "scripts" / f"{name}.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        if not script.exists():
            script.write_text(SCRIPTS[name].format(tests=str(ROOT / "tests"), expires=expires))
        spec = {"kind": "SCRIPT", "path": str(script), "sha256": C.sha256_hex(script.read_bytes())}
        for trajectory in [t for t in plan["trajectories"] if t["session_id"] == session_id]:
            request = EP.trajectory_request(plan, trajectory, authorization_path=out / "unused",
                                            pricing_path=out / "unused", receipt_root=out / "unused",
                                            ledger_path=out / "unused")
            request["mode"], request["responder"] = "B", spec
            request["run_document"] = dict(request["run_document"], control=name)
            root = out / "runs" / f"{name}-{trajectory['trajectory_id']}"
            status = CH.run_in_child(request, out_root=root, timeout_seconds=3600.0)
            evidence = Path(status["summary"]["evidence_root"]) if status.get("summary") else None
            rows.append({"control": name, "trajectory_id": trajectory["trajectory_id"], "lane": trajectory["lane"],
                         "session_id": session_id, "case": trajectory["case"], "origin": "MOCK",
                         "child_complete": status["complete"], "child_exit": status["exit_code"],
                         "network_attempts": (status.get("child_exit") or {}).get("network_attempts"),
                         "scans": _scan_rows(evidence) if evidence else [],
                         "stderr_tail": None if status["complete"] else status.get("stderr_tail", "")[-1500:]})
    doc = {"schema": "current_brain_eval_controls/v1", "origin": "MOCK", "external_requests_made": 0,
           "plan_seal": plan["seal"]["sha256"], "rows": rows,
           "scripts": {p.name: C.sha256_hex(p.read_bytes()) for p in sorted((out / "scripts").iterdir())}}
    (out / "controls.json").write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    doc = run_controls(args.plan, Path(args.out))
    for row in doc["rows"]:
        last = row["scans"][-1] if row["scans"] else {}
        print(row["control"], row["trajectory_id"], row["child_complete"], last.get("outcome"),
              last.get("first_refusal_code"), last.get("lifecycle_state"), last.get("candidate_present"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
