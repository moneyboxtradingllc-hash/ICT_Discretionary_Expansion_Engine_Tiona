"""Build the sealed current-Brain evaluation plan (PREPARE ONLY; zero provider calls).

    PYTHONPATH=src:tests python tools/build_current_brain_eval_plan.py --out DIR

Deterministic from a CLEAN checkout: the same source commit gives byte-identical
artifacts and the same plan seal, so an auditor can rebuild and compare. The
plan binds the checkout it was built from (`production_source_sha` = HEAD), so
it is published beside the frozen runner, never committed into it.

Steps, all offline under the fully denying network guard of each child:
  1. tapes: the committed Friday 2026-10-23 settled tape (REPOSITORY_RECORDED);
     the W5 tape of test_campaign_scope (bars[:99], CONSTRUCTED); the C2/C4
     scenario tapes of test_campaign_leg_scope_labels translated +12h into the
     production window (CONSTRUCTED). Every source file is pinned by git blob.
  2. two sealed corpora, two sealed schedules (34 primary SCAN ticks, every
     other settled minute PREWARM, no warmup cognition), sealed CONTROLLED
     quote streams, the UNAPPROVED worst-case pricing and the parameter profile.
  3. the input bound, MEASURED: every one of the 8 trajectories runs through
     the real ProductionLoop in a fresh child with a MOCK script (valid
     production-shaped replies), and the largest byte-level input bound any
     primary or repair request reached is recorded. MOCK cognition, never a
     claim about any model.
  4. the cost plan, the DISABLED authorization template and the sealed plan.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import eval_plan as EP  # noqa: E402

SEALED_AT = "2026-10-25T00:00:00Z"
PRICING_ACCESSED_AT = "2026-10-25T20:28:11Z"
SHIFT = timedelta(hours=12)
FRIDAY = "tests/fixtures/session_20261023_settled_tape.json"
SOURCES = (FRIDAY, "tests/test_campaign_scope.py", "tests/test_campaign_scope_binding.py",
           "tests/test_campaign_leg_scope_labels.py", "tests/test_campaign_draw_temporal_authority.py",
           "tests/test_reversal_foundation_proof_closure.py")
#: The MOCK measurement script: production-shaped valid replies (stand_down when no lawful geometry).
MEASURE_SCRIPT = '''import sys
sys.path.insert(0, {tests!r})
import test_reversal_foundation_proof_closure as RF


def script(request):
    return RF._valid_model_reply(request["payload"], direction="bearish")
'''


def _git(*args) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True,
                          text=True).stdout.strip()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def friday_tape() -> list:
    data = json.loads((ROOT / FRIDAY).read_text())
    tape = data["tape"]
    digest = C.sha256_hex(json.dumps(tape, sort_keys=True, separators=(",", ":")).encode())
    C.require(digest == data["tape_canonical_sha256"] and len(tape) == data["bars"], "FRIDAY_TAPE_DIGEST", "/tape")
    return [{**b, "contract": EP.CONTRACT_ID} for b in sorted(tape, key=lambda b: b["timestamp"])]


def w5_tape() -> list:
    import test_campaign_scope as CS
    return [dict(b, contract=EP.CONTRACT_ID) for b in CS._tape()[:99]]


def c_tape(name: str) -> list:
    """The pinned scenario shape, every bar translated +12h (03:xx -> 15:xx UTC) and nothing else."""
    import test_campaign_draw_temporal_authority as TA
    import test_campaign_leg_scope_labels as L
    rows = list(TA.LATER) + list(L.SCENARIOS[name])
    return [dict(b, timestamp=_iso(datetime.fromisoformat(b["timestamp"]) + SHIFT), contract=EP.CONTRACT_ID)
            for b in rows]


def _opens(tape, hhmm_list, day):
    return [f"{day}T{h}:00+00:00" for h in hhmm_list]


def sessions():
    friday, w5 = friday_tape(), w5_tape()
    c2, c4 = c_tape("C2"), c_tape("C4")
    return {
        "friday": [{"session_id": "FRI-20261023", "tape": friday, "market_date": "2026-10-23",
                    "opens": _opens(friday, EP.FRIDAY_CUTOFFS, "2026-10-23"), "case": "FRIDAY_SETTLED",
                    "notes": "Friday 2026-10-23 settled 1m tape; 12 sealed 1m-open cutoffs."}],
        "constructed": [
            {"session_id": "W5-T2T3T4", "tape": w5, "market_date": "2026-08-19",
             "opens": [w5[96]["timestamp"], w5[97]["timestamp"], w5[98]["timestamp"]], "case": "W5_CONSTRUCTED",
             "notes": "test_campaign_scope W5 tape bars[:99]; decisions = binding-test scans 97/98/99 (T2/T3/T4). "
                      "Bars reused, mock replies NOT reused."},
            {"session_id": "C4-INTACT-RETRACE", "tape": c4, "market_date": "2026-08-19",
             "opens": [c4[-1]["timestamp"]], "case": "NEGATIVE_INTACT_RETRACEMENT",
             "notes": "test_campaign_leg_scope_labels C4 (TA.LATER + C4), +12h; decision at the C4 03:16 open "
                      "(15:16): a single opposing 1m break with the load-bearing 1m 29457 intact."},
            {"session_id": "C2-UNSUPPORTED-TRANSFER", "tape": c2, "market_date": "2026-08-19",
             "opens": [c2[-1]["timestamp"]], "case": "NEGATIVE_UNSUPPORTED_TRANSFER",
             "notes": "test_campaign_leg_scope_labels C2 (TA.LATER + C2), +12h; decision at the C2 03:14 open "
                      "(15:14): the 1m leg died at 03:06, a 15m raid rejection registers after the death."}]}


def _ref(root: Path, rel: str, origin: str) -> dict:
    data = (root / rel).read_bytes()
    return {"path": rel, "sha256": C.sha256_hex(data), "bytes": len(data), "origin": origin}


def _write(root: Path, rel: str, value, origin: str) -> dict:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    C.require(not target.exists(), "ARTIFACT_OVERWRITE_REFUSED", "/" + rel)
    target.write_bytes((json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8"))
    return _ref(root, rel, origin)


def build_artifacts(out: Path, identity: dict) -> dict:
    groups = sessions()
    artifacts, trajectories, corpora, schedules = {}, [], {}, {}
    for group, specs in groups.items():
        classification = "REPOSITORY_RECORDED" if group == "friday" else "CONSTRUCTED"
        root = out / "corpora" / group
        corpus = EP.build_corpus(root, document_id=f"CBE-{group.upper()}-20261025", classification=classification,
                                 sealed_at=SEALED_AT,
                                 sessions=[{"session_id": s["session_id"], "tape": s["tape"],
                                            "warmup_end": s["opens"][0], "notes": s["notes"],
                                            "market_date": s["market_date"]} for s in specs])
        decisions = {"__root__": str(root)}
        for spec in specs:
            decisions[spec["session_id"]] = EP._decisions_from_opens(spec["tape"], spec["opens"])
        schedule = EP.build_schedule(corpus, decisions, document_id=f"CBE-SCHEDULE-{group.upper()}-20261025",
                                     classification=classification, sealed_at=SEALED_AT,
                                     source_refs=[f"{p}@{_git('rev-parse', 'HEAD:' + p)}" for p in SOURCES])
        artifacts[f"corpus_{group}"] = _ref(out, f"corpora/{group}/corpus.json", classification)
        artifacts[f"schedule_{group}"] = _write(out, f"schedules/{group}.json", schedule, classification)
        corpora[group], schedules[group] = corpus, schedule
        for spec in specs:
            quotes = EP.controlled_quotes(spec["tape"])
            qname = f"quotes_{spec['session_id']}"
            artifacts[qname] = _write(out, f"quotes/{spec['session_id']}.json", quotes, "CONTROLLED")
            for lane, ecu in EP.LANES:
                trajectories.append({
                    "trajectory_id": f"CBE-{spec['session_id']}-{lane}", "lane": lane, "ecu": ecu,
                    "session_id": spec["session_id"], "case": spec["case"], "corpus": f"corpus_{group}",
                    "schedule": f"schedule_{group}", "quote_policy": "CONTROLLED", "controlled_quotes": qname,
                    "primary_decisions": len(spec["opens"]),
                    "decision_times_utc": [_iso(d) for d in decisions[spec["session_id"]]],
                    "decision_bar_opens_utc": spec["opens"], "warmup_cognition": "NONE",
                    "corpus_classification": classification})
    pins = {p: {"git_blob": _git("rev-parse", "HEAD:" + p)} for p in SOURCES}
    artifacts["source_pins"] = _write(out, "source_pins.json", {
        "schema": "current_brain_eval_source_pins/v1", "source_sha": identity["source_sha"], "files": pins,
        "translation": {"C2-UNSUPPORTED-TRANSFER": "+12h", "C4-INTACT-RETRACE": "+12h",
                        "reason": "original 03:xx UTC stamps are outside the production window, where "
                                  "ProductionLoop refuses window_closed before any authority gate"}},
        "REPOSITORY_RECORDED")
    return {"artifacts": artifacts, "trajectories": trajectories, "corpora": corpora, "schedules": schedules}


def measure(out: Path, plan_stub: dict, measure_root: Path) -> dict:
    """MOCK: run every trajectory in a fresh child; return the largest measured input bound."""
    from recognition_validation import child as CH
    from recognition_validation import model_authority as MA
    from recognition_validation import recorder as REC
    script = measure_root / "measure_script.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(MEASURE_SCRIPT.format(tests=str(ROOT / "tests")))
    spec = {"kind": "SCRIPT", "path": str(script), "sha256": C.sha256_hex(script.read_bytes())}
    rows = []
    for trajectory in plan_stub["trajectories"]:
        request = EP.trajectory_request(plan_stub, trajectory, authorization_path=out / "unused",
                                        pricing_path=out / "unused", receipt_root=out / "unused",
                                        ledger_path=out / "unused")
        request["mode"], request["responder"] = "B", spec
        request["run_document"] = dict(request["run_document"], measurement="MOCK_INPUT_BOUND")
        status = CH.run_in_child(request, out_root=measure_root / trajectory["trajectory_id"],
                                 timeout_seconds=5400.0)
        C.require(status["complete"], "MEASUREMENT_INCOMPLETE", "/" + trajectory["trajectory_id"],
                  status.get("stderr_tail", "")[-800:])
        evidence = Path(status["summary"]["evidence_root"])
        bounds = []
        for call in REC.read_calls(evidence):
            messages = []
            for key, role in (("prompt_ref", "system"), ("input_ref", "user")):
                ref = call.get(key)
                if ref:
                    messages.append({"role": role, "content": (evidence / ref["path"]).read_text(encoding="utf-8")})
            bounds.append({"purpose": call.get("purpose"), "bound": MA.input_token_bound(messages)})
        rows.append({"trajectory_id": trajectory["trajectory_id"], "calls": len(bounds),
                     "primary_calls": status["summary"]["primary_calls"],
                     "repair_calls": status["summary"]["repair_calls"],
                     "max_input_token_bound": max((b["bound"] for b in bounds), default=0),
                     "bounds": [b["bound"] for b in bounds]})
    return {"schema": "current_brain_eval_input_measurement/v1", "origin": "MOCK", "external_requests_made": 0,
            "method": "byte-level upper bound (one token >= one UTF-8 byte) + per-message overhead over the "
                      "exact system prompt and transported user content the real ProductionLoop built",
            "trajectories": rows, "max_input_token_bound": max(r["max_input_token_bound"] for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--measure-root", required=True, help="scratch root for the MOCK measurement children")
    args = ap.parse_args(argv)
    out, measure_root = Path(args.out), Path(args.measure_root)
    C.require(not out.exists() or not any(out.iterdir()), "OUTPUT_ROOT_REUSE", "/out")
    identity = C.source_identity()
    C.require(identity["dirty_tree_digest"] is None, "PLAN_SOURCE_DIRTY", "/source", "build from a clean checkout")
    from recognition_validation import model_authority as MA
    built = build_artifacts(out, identity)
    parameters = MA.EvaluationParameters(EP.BUDGET["max_completion_tokens"])
    stub = {"schema": EP.PLAN_SCHEMA, "contract_id": "CODEX-2026-10-25/1 PREPARE ONLY",
            "production_source_sha": identity["source_sha"], "production_source_tree": identity["source_tree"],
            "brain_fingerprint": identity["brain_fingerprint"],
            "retrieval_fingerprint": identity["retrieval_fingerprint"], "closure_digest": identity["closure_digest"],
            "model": EP.MODEL, "parameter_digest": parameters.digest,
            "corpus_set_digest": C.digest(sorted(C.seal_digest(c) for c in built["corpora"].values())),
            "schedule_set_digest": C.digest(sorted(C.seal_digest(s) for s in built["schedules"].values())),
            "artifacts": built["artifacts"], "trajectories": built["trajectories"], "_root": str(out)}
    measured = measure(out, stub, measure_root)
    stub.pop("_root")
    artifacts = stub["artifacts"]
    artifacts["input_measurement"] = _write(out, "input_measurement.json", measured, "MOCK")
    cap = EP.input_cap(measured["max_input_token_bound"])
    (out / "pricing_source.md").write_text(PRICING_SOURCE, encoding="utf-8")
    source = _ref(out, "pricing_source.md", "REPOSITORY_RECORDED")
    pricing = EP.pricing_document(source_ref=source, accessed_at=PRICING_ACCESSED_AT)
    artifacts["pricing_source"] = source
    artifacts["pricing"] = _write(out, "pricing_UNAPPROVED.json", pricing, "REPOSITORY_RECORDED")
    artifacts["parameters"] = _write(out, "evaluation_parameters.json", parameters.document(), "REPOSITORY_RECORDED")
    costs = EP.cost_plan(input_cap_tokens=cap, pricing=pricing)
    artifacts["cost_plan"] = _write(out, "cost_plan.json", costs, "REPOSITORY_RECORDED")
    plan = dict(stub, max_input_tokens_per_request=cap, budget_proposal=EP.BUDGET, authority="DISABLED",
                owner_approval=None, pricing_digest=C.seal_digest(pricing), lanes=[lane for lane, _ in EP.LANES],
                primary_requests=sum(t["primary_decisions"] for t in stub["trajectories"]),
                quote_policy="CONTROLLED (sealed; results conditional on controlled quotes, not historical fills)",
                broker_submission_path="NONE (venue lane DISARMED; no order/account port in the child)",
                seal=None)
    plan = EP.seal(plan, sealed_at=SEALED_AT, sealer="EVALUATION-PREPARATION engineering seal (not an owner seal)")
    (out / "plan.json").write_text(json.dumps(plan, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    template = EP.authorization_template(plan, sealed_at=SEALED_AT)
    (out / "authorization_DISABLED.json").write_text(json.dumps(template, sort_keys=True, indent=1) + "\n",
                                                     encoding="utf-8")
    EP.load_plan(out / "plan.json")
    print(json.dumps({"plan_seal": plan["seal"]["sha256"], "max_input_tokens_per_request": cap,
                      "measured_max_input_token_bound": measured["max_input_token_bound"],
                      "per_request_upper_bound_usd": costs["per_request_upper_bound_usd"],
                      "worst_case_total_usd": costs["worst_case_total_usd"], "external_requests_made": 0},
                     sort_keys=True))
    return 0


PRICING_SOURCE = """# gpt-6-luna pricing source (read-only public documentation; NOT owner-approved)

Read 2026-10-25 between 20:27 and 20:28 UTC with a read-only documentation fetch. No account, dashboard,
credential or provider API was touched. The text below is what the fetch tool returned from these pages
(a tool summary of each page, not the raw page bytes): an auditor must re-read the pages before approving.

- https://developers.openai.com/api/docs/models/gpt-6-luna
  - Model ID `gpt-6-luna` (the only listed snapshot and the default).
  - Per 1M tokens: input $0.10, cached input $0.01, output $0.50, cache writes $0.125.
  - Context window 1,050,000; maximum input 922,000; max output 128,000. Chat Completions supported.
  - Prompts over 272K input tokens cost 2x input/cache and 1.5x output for the entire request.
- https://developers.openai.com/api/docs/pricing (gpt-6-luna rows, per 1M tokens, short <=272K / long >272K)

| Tier | Input | Cached input | Cache write 30m | Cache write 12h | Output |
|---|---|---|---|---|---|
| Standard | 0.10 / 0.20 | 0.01 / 0.02 | 0.125 / 0.25 | 0.25 / 0.50 | 0.50 / 0.75 |
| Batch | 0.05 / 0.10 | 0.005 / 0.01 | 0.0625 / 0.125 | 0.125 / 0.25 | 0.25 / 0.375 |
| Flex | 0.05 / 0.10 | 0.005 / 0.01 | 0.0625 / 0.125 | 0.125 / 0.25 | 0.25 / 0.375 |
| Fast (formerly Priority) | 0.20 / 0.40 | 0.02 / 0.04 | 0.25 / 0.50 | 0.50 / 1.00 | 1.00 / 1.50 |

  - "Priority processing was renamed Fast mode on July 30, 2026."
  - Regional processing (data residency) and FedRAMP endpoints carry a 10% uplift; the pinned endpoint
    https://api.openai.com/v1 is neither.
  - No statement on reasoning-token billing was found; reasoning tokens are priced as output here.
- https://developers.openai.com/api/docs/guides/reasoning (reasoning tokens are generated output and count
  against the output cap).

## Worst-case pricing used by the plan (conservative, no cache discount)

Production sets no `service_tier`, so the project's tier is unknown. Every input token is priced at the
dearest SHORT-context input class of the dearest tier ($0.50/1M: Fast 12h cache write) and every output or
reasoning token at Fast output ($1.00/1M). The plan's input cap stays below 272K, so the long-context rates
cannot apply. These are 5x (input) and 2x (output) the Standard rates.
"""


if __name__ == "__main__":
    sys.exit(main())
