"""`python -m recognition_validation` -- the Stage 5 operator commands (contract 07).

Exit codes: 0 command completed (never "recognition passed": the artifact
status is authoritative); 2 invalid contract or unauthorized request; 3
missing prerequisite / UNPROVEN input; 4 invariant or determinism failure;
5 infrastructure or recording error. `validate`, `plan` and the Mode C dry
run never reach a network, even from a credential-bearing environment.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from recognition_validation import contracts as C

EXIT_OK, EXIT_CONTRACT, EXIT_MISSING, EXIT_INVARIANT, EXIT_INFRA = 0, 2, 3, 4, 5
#: Refusals about the recorded evidence itself (not about the operator's inputs).
EVIDENCE_PREFIXES = ("ARTIFACT_", "EVENT_", "SYMLINK_ARTIFACT", "BRAIN_CALL_")


def _load(path, kind=None, *, certification=False) -> dict:
    document, found, _ = C.validate_file(path, certification=certification)
    if kind is not None:
        C.require(found == kind, "WRONG_DOCUMENT_KIND", "/schema_version", f"{found}!={kind}")
    return document


def _fresh(out) -> Path:
    out = Path(out)
    C.require(not out.exists() or not any(out.iterdir()), "OUTPUT_ROOT_REUSE", "/" + str(out))
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_json(path: Path, value) -> dict:
    data = json.dumps(value, sort_keys=True, indent=1).encode("utf-8")
    with open(path, "xb") as handle:
        handle.write(data)
    return {"path": path.name, "sha256": C.sha256_hex(data), "bytes": len(data), "origin": "CONSTRUCTED"}


def _schedule(corpus, session, prewarm_until, ticks_until):
    from recognition_validation import driver as DR
    stream = corpus.sessions[session].stream
    C.require(stream is not None, "RELEASE_STREAM_REQUIRED", f"/sessions/{session}")
    ticks = DR.minute_schedule(stream, prewarm_until=DR.utc(prewarm_until) if prewarm_until else None)
    if ticks_until:
        ticks = [t for t in ticks if t.decision_time <= DR.utc(ticks_until)]
    return ticks


def _session(corpus, requested):
    if requested:
        C.require(requested in corpus.sessions, "SESSION_NOT_IN_CORPUS", "/session", requested)
        return requested
    C.require(len(corpus.sessions) == 1, "SESSION_REQUIRED", "/session")
    return next(iter(corpus.sessions))


def cmd_validate(args) -> int:
    corpus = _load(args.corpus, "corpus", certification=args.certification)
    annotations = _load(args.annotations, "annotation", certification=args.certification) if args.annotations else None
    scoring = _load(args.scoring, "scoring", certification=args.certification) if args.scoring else None
    run = _load(args.run, "run", certification=args.certification) if args.run else None
    C.cross(corpus, annotations=annotations, scoring=scoring, run=run)
    print(json.dumps({"status": "VALID", "corpus_digest": C.seal_digest(corpus), "external_requests": 0}))
    return EXIT_OK


def cmd_plan(args) -> int:
    from recognition_validation import corpus as K
    from recognition_validation import ports as P
    with P.NetworkGuard().deny():
        corpus = K.load_corpus(args.corpus)
        session = _session(corpus, args.session)
        ticks = _schedule(corpus, session, args.prewarm_until, args.ticks_until)
        out = _fresh(args.out)
        _write_json(out / "plan.json", {
            "schema": "tick_plan/v1", "corpus_digest": corpus.digest, "session_id": session,
            "external_requests": 0, "tick_count": len(ticks),
            "ticks": [{"ordinal": t.ordinal, "kind": t.kind, "decision_time": t.decision_time.isoformat()}
                      for t in ticks]})
    print(json.dumps({"status": "PLANNED", "ticks": len(ticks), "external_requests": 0}))
    return EXIT_OK


def _script_responder(path):
    from recognition_validation import brain_gateway as G
    data = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location("stage5_mode_b_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    C.require(callable(getattr(module, "script", None)), "MOCK_SCRIPT_MISSING", "/script")
    return G.ScriptedResponder(module.script, fixture_digest=C.sha256_hex(data))


def _authorization(path):
    if path:
        return _load(path, "model_authorization")
    disabled = Path(__file__).parent / "examples" / "model_authorization_disabled.json"
    return _load(disabled, "model_authorization")


def _run_ticks(run, run_path, corpus, session, args):
    from recognition_validation import driver as DR, ports as P
    raw = C.verify_artifact(run["schedule_ref"], Path(run_path).resolve().parent, "/schedule_ref")
    schedule = C.loads_strict(raw.decode("utf-8"))
    C.require(C.validate(schedule) == "schedule", "WRONG_DOCUMENT_KIND", "/schedule_ref")
    C.require(bool(schedule["seal"]), "SCHEDULE_UNSEALED", "/schedule_ref")
    C.require(schedule["corpus_digest"] == corpus.digest, "SCHEDULE_CORPUS_MISMATCH", "/corpus_digest")
    C.require(C.instant(schedule["seal"]["sealed_at"]) <= P.real_utc_now(), "SCHEDULE_SEALED_IN_FUTURE", "/seal")
    C.require(all(t["session_id"] in corpus.sessions for t in schedule["ticks"]), "SCHEDULE_FOREIGN_SESSION", "/ticks")
    ticks = [DR.Tick(t["ordinal"], C.instant(t["decision_time_utc"]), t["kind"])
             for t in schedule["ticks"] if t["session_id"] == session]
    C.require(bool(ticks), "EMPTY_SCHEDULE", "/ticks")
    C.require(all(t.kind in DR.TICK_KINDS for t in ticks), "TICK_ADAPTER_UNAVAILABLE", "/ticks/kind")
    if args.prewarm_until or args.ticks_until:
        generated = _schedule(corpus, session, args.prewarm_until, args.ticks_until)
        C.require([(t.decision_time, t.kind) for t in ticks] == [(t.decision_time, t.kind) for t in generated],
                  "SCHEDULE_OVERRIDE_MISMATCH", "/schedule_ref")
    return ticks


def cmd_run(args) -> int:
    from recognition_validation import brain_gateway as G
    from recognition_validation import corpus as K
    from recognition_validation import driver as DR
    from recognition_validation import model_authority as MA
    from recognition_validation import ports as P
    run = _load(args.run, "run")
    C.require(run["mode"] == args.mode, "RUN_MODE_MISMATCH", "/mode", f"{run['mode']}!={args.mode}")
    corpus = K.load_corpus(args.corpus)
    C.cross(corpus.document, run=run)
    session = _session(corpus, args.session)
    if args.mode == "C":
        authorization = _authorization(args.authorization)
        if args.dry_run:
            with P.NetworkGuard().deny():
                ticks = _schedule(corpus, session, args.prewarm_until, args.ticks_until)
                pricing = _load(args.pricing, "pricing") if args.pricing else None
                profile = (MA.EvaluationParameters(args.max_completion_tokens)
                           if args.max_completion_tokens else None)
                plan = MA.dry_run_plan(tick_count=sum(1 for t in ticks if t.kind != "PREWARM"), lanes=1,
                                       trajectory_count=run["trajectory_count"], authorization=authorization,
                                       pricing=pricing, parameters=profile)
                out = _fresh(args.out)
                _write_json(out / "mode_c_dry_run.json", plan)
            print(json.dumps(plan, sort_keys=True))
            return EXIT_OK
        C.require(authorization["state"] == "OWNER_AUTHORIZED", "CURRENT_MODEL_CALLS_DISABLED", "/state")
        raise C.ContractError("EXTERNAL_TRANSPORT_UNAVAILABLE", "/mode",
                              detail="this build contains no external transport; only fake transports exist")
    C.verify_run_source(run)
    C.require(run["memory_policy"] == "EMPTY", "MEMORY_SEED_ADAPTER_UNAVAILABLE", "/memory_policy")
    C.require(run["trajectory_count"] == 1, "TRAJECTORY_ADAPTER_UNAVAILABLE", "/trajectory_count")
    ticks = _run_ticks(run, args.run, corpus, session, args)
    if args.mode == "B":
        C.require(bool(args.script), "MOCK_SCRIPT_MISSING", "/script")
        responder = _script_responder(args.script)
    else:
        C.require(bool(args.records), "HISTORICAL_RECORDS_MISSING", "/records")
        records = C.loads_strict(Path(args.records).read_text(encoding="utf-8"), pointer="/records")
        responder = G.HistoricalResponder(records, contract_id=corpus.sessions[session].entry["contract_id"])
    summary = DR.run_offline(corpus_path=args.corpus, session_id=session, out_root=args.out, responder=responder,
                             ecu=run["ecu"], trajectory_id=run["trajectory_id"], prewarm_until=args.prewarm_until,
                             ticks_until=args.ticks_until,
                             ticks=ticks, quote_policy=run["quote_policy"], run_document=run,
                             fingerprints={"brain": run["brain_fingerprint"], "retrieval": run["retrieval_fingerprint"]})
    status = {k: summary[k] for k in ("ticks", "events", "primary_calls", "repair_calls", "infrastructure_error")}
    print(json.dumps({"status": "RUN_COMPLETE" if not summary["infrastructure_error"] else "RUN_INCOMPLETE",
                      "evidence_root": summary["evidence_root"], **status}, sort_keys=True))
    if summary["infrastructure_error"]:
        return EXIT_INFRA
    if summary["network_attempts"] or summary["venue_writes"]:
        return EXIT_INVARIANT
    return EXIT_OK


def cmd_compare(args) -> int:
    from recognition_validation import compare as CMP
    C.require(args.projection == CMP.PROJECTION, "UNKNOWN_PROJECTION", "/projection", args.projection)
    report = CMP.compare_runs(_evidence(args.left), _evidence(args.right))
    print(json.dumps(report, sort_keys=True))
    return EXIT_OK if report["identical"] else EXIT_INVARIANT


def _evidence(root) -> Path:
    root = Path(root)
    return root / "evidence" if (root / "evidence").is_dir() else root


def cmd_report(args) -> int:
    from recognition_validation import report as RP
    from recognition_validation import scoring as SC
    root = _evidence(args.run)
    manifest = RP.read_manifest(root)
    missing = []
    started = (manifest or {}).get("real_started_at")
    corpus = _load(args.corpus, "corpus") if args.corpus else None
    if corpus is not None:
        SC.admit_corpus(corpus, run_started_at=started)
    annotation = None
    if args.annotations:
        annotation = _load(args.annotations, "annotation")
        SC.admit_annotation(annotation, corpus=corpus, run_started_at=started)
    else:
        missing.append("ANNOTATIONS_ABSENT: label metrics UNSCORED")
    scoring = _load(args.scoring, "scoring") if args.scoring else None
    if scoring is not None and corpus is not None:
        C.cross(corpus, annotations=annotation, scoring=scoring)
    mode = {"MOCK": "B", "HISTORICAL": "A", "CURRENT_EXTERNAL": "C"}.get((manifest or {}).get("evaluation_origin"),
                                                                         args.mode)
    C.require(mode in ("A", "B", "C"), "MODE_UNKNOWN", "/mode")
    scored = [SC.score_trace(root, mode=mode, session_id=(manifest or {}).get("session_id") or "UNKNOWN",
                             trajectory_id=(manifest or {}).get("trajectory_id") or "UNKNOWN",
                             annotation=annotation, scoring=scoring)]
    out = _fresh(args.out)
    refs = [{"path": f"evidence/{name}", "sha256": C.sha256_hex((root / name).read_bytes()),
             "bytes": (root / name).stat().st_size, "origin": "CONSTRUCTED"}
            for name in ("events.jsonl", "brain_calls.jsonl", RP.MANIFEST) if (root / name).exists()]
    result = RP.build_result(document_id=f"result:{scored[0]['summary']['trajectory_id']}",
                             run_digest=(manifest or {}).get("run_digest") or (manifest or {}).get("corpus_digest") or "0" * 64,
                             mode=mode, scored=scored,
                             manifest=manifest, artifact_refs=refs, missing_prerequisites=missing,
                             stage4_internal_status=args.stage4_status)
    _write_json(out / "result.json", result)
    (out / "report.md").write_text(RP.render_markdown(result, scored), encoding="utf-8")
    print(json.dumps({"final_status": result["final_status"], "engineering_status": result["engineering_status"],
                      "current_brain_recognition": result["current_brain_recognition"]}, sort_keys=True))
    if result["invariant_failures"]:
        return EXIT_INVARIANT
    if result["engineering_status"] == "INCOMPLETE":
        return EXIT_INFRA
    return EXIT_MISSING if annotation is None else EXIT_OK


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m recognition_validation")
    sub = top.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--corpus", required=True)
    v.add_argument("--annotations")
    v.add_argument("--scoring")
    v.add_argument("--run")
    v.add_argument("--certification", action="store_true")
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--corpus", required=True)
        p.add_argument("--session")
        p.add_argument("--out", required=True)
        p.add_argument("--prewarm-until")
        p.add_argument("--ticks-until")
        if name == "plan":
            p.add_argument("--run")
        else:
            p.add_argument("--run", required=True)
            p.add_argument("--mode", required=True, choices=["A", "B", "C"])
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--script")
            p.add_argument("--records")
            p.add_argument("--authorization")
            p.add_argument("--pricing")
            p.add_argument("--max-completion-tokens", type=int)
    c = sub.add_parser("compare")
    c.add_argument("--left", required=True)
    c.add_argument("--right", required=True)
    c.add_argument("--projection", default="semantic-v1")
    r = sub.add_parser("report")
    r.add_argument("--run", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--annotations")
    r.add_argument("--scoring")
    r.add_argument("--corpus")
    r.add_argument("--mode", default="B")
    r.add_argument("--stage4-status", default="UNPROVEN", choices=["PASS", "FAIL", "UNPROVEN"])
    return top


def main(argv=None) -> int:
    from recognition_validation import recorder as REC
    args = parser().parse_args(argv)
    handler = {"validate": cmd_validate, "plan": cmd_plan, "run": cmd_run, "compare": cmd_compare,
               "report": cmd_report}[args.command]
    try:
        return handler(args)
    except C.ContractError as error:
        print(json.dumps({"status": "REFUSED", "code": error.code, "pointer": error.pointer,
                          "detail": error.detail}), file=sys.stderr)
        if error.code.startswith(EVIDENCE_PREFIXES):
            return EXIT_INFRA  # recorded evidence missing or altered: the run is INCOMPLETE, never a pass
        return EXIT_MISSING if error.code.endswith("_MISSING") or error.code.endswith("_ABSENT") else EXIT_CONTRACT
    except (REC.RecorderError, OSError) as error:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "detail": f"{type(error).__name__}: {error}"}),
              file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
