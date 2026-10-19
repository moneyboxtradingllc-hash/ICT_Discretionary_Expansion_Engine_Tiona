"""Stage 5 M06: sealed-annotation scoring, result/report, operator CLI (T27-T29).

Labels here are FICTIONAL or CONSTRUCTED test documents, never Maurice's
annotations; they exercise the join and its refusals on the real Mode B trace
of the CONSTRUCTED distinct-anchor session.
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_recognition_current_path as CP  # noqa: E402
from recognition_validation import __main__ as CLI  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import compare as CMP  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import report as RP  # noqa: E402
from recognition_validation import scoring as SC  # noqa: E402

UNTIL = "2026-08-19T16:46:00Z"
PREWARM = "2026-08-19T15:30:00Z"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("m06")
    corpus_path = K.build_constructed_corpus(base / "corpus", session_id=CP.SESSION, contract_id=CP.CONTRACT,
                                             market_date="2026-08-19", tape=W._tape(W._HEALTHY),
                                             warmup_end="2026-08-19T15:30:00+00:00",
                                             notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                             sealed_at="2026-10-17T00:00:00Z")
    script, _ = CP._script()
    summary = DR.run_offline(corpus_path=corpus_path, session_id=CP.SESSION, out_root=base / "B", ecu=False,
                             trajectory_id="S5-M06", prewarm_until=PREWARM, ticks_until=UNTIL,
                             responder=G.ScriptedResponder(script, fixture_digest=C.digest("daw-script-v1")))
    corpus = K.load_corpus(corpus_path)
    return {"base": base, "corpus_path": corpus_path, "corpus": corpus.document, "digest": corpus.digest,
            "root": Path(summary["evidence_root"])}


def _label(label_id, start, end, *, direction="bearish", action="ENTRY", confidence="CLEAR", ambiguous=False,
           occurrence=None, earliest=None, opportunity="eligible", target=None):
    day = "2026-08-19T"
    return {"label_id": label_id, "window": {"start_utc": day + start + ":00Z", "end_utc": day + end + ":00Z"},
            "earliest_available_utc": day + (earliest or start) + ":00Z",
            "recognition_target": {"start_utc": day + (target or (start, end))[0] + ":00Z",
                                   "end_utc": day + (target or (start, end))[1] + ":00Z"},
            "dominant_campaign_direction": direction, "campaign_origin": [], "campaign_objective": [],
            "delivery_state": "ACTIVE_DELIVERY", "required_invalidation_evidence": [],
            "opposing_transfer_evidence": [], "opportunity": opportunity, "playbook_family": None,
            "tool_family": None, "occurrence_id": occurrence, "timeframes": ["5m", "15m"],
            "expected_action": action, "expected_unknown_or_stand_down_reason": None, "confidence": confidence,
            "ambiguous": ambiguous, "source_evidence": [], "notes": "CONSTRUCTED test label"}


def _annotation(world, labels, *, state="FICTIONAL", role="FICTIONAL", author="CONTRACT_EXAMPLE",
                classification="FICTIONAL", sealed_at=None):
    doc = {"schema_version": "annotation/v1", "document_id": "TEST-ANNOTATION",
           "provenance": {"classification": classification, "author_role": author,
                          "source_refs": ["tests/test_recognition_scoring_cli.py"],
                          "notes": "CONSTRUCTED test labels; never Maurice's annotation."},
           "corpus_digest": world["digest"], "session_id": CP.SESSION, "annotator_id": "test-annotator",
           "annotator_role": role, "authorization_ref": "TEST-ONLY" if state == "SEALED" else None,
           "state": state, "created_at": "2026-10-17T00:00:00Z", "labels": labels, "seal": None}
    if state == "SEALED":
        doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": sealed_at or "2026-10-17T01:00:00Z",
                       "sealer_ref": "test"}
    return doc


def _known_labels():
    return [_label("entry-window", "16:39", "16:45", occurrence=W.FORMATION_ID),
            _label("quiet", "15:31", "15:40", action="STAND_DOWN", target=("15:31", "15:40")),
            _label("unclear", "15:41", "15:50", direction="UNKNOWN", action="UNKNOWN", confidence="UNKNOWN",
                   ambiguous=True, opportunity="UNKNOWN")]


def _cells(scored, layer):
    return {(c["expected"], c["observed"]) for c in scored["summary"]["confusion_cells"] if c["layer"] == layer}


def _metric(scored, name):
    return next(m for m in scored["summary"]["metrics"] if m["name"] == name)


# -- positive: exact expected metrics --------------------------------------------

def test_known_labels_on_the_real_trace_give_exact_separate_cells(world):
    annotation = _annotation(world, _known_labels())
    SC.admit_annotation(annotation, corpus=world["corpus"], run_started_at=None)
    scored = SC.score_trace(world["root"], mode="B", session_id=CP.SESSION, trajectory_id="S5-M06",
                            annotation=annotation)
    assert _cells(scored, "REFUSAL") == {("ENTRY", "HIT"), ("STAND_DOWN", "CORRECT_REFUSAL"),
                                         ("UNKNOWN", "HONEST_UNKNOWN")}
    # Deterministic truth: the exact production occurrence identity, compared raw.
    assert _cells(scored, "FACT") == {(W.FORMATION_ID, "EXACT_OCCURRENCE")}
    entry = next(e for e in scored["episodes"] if e["label_id"] == "entry-window")
    # This label starts at 16:39 decision time; the already-delivering campaign
    # also has candidates before that window. Score the first observation inside it.
    assert entry["first_candidate_utc"][11:16] == "16:39" and entry["selected_occurrences"] == [W.FORMATION_ID]
    assert _metric(scored, "exact_occurrence_selected")["numerator"] == 1
    assert _metric(scored, "correct_refusals")["numerator"] == 1
    assert _metric(scored, "false_positive_entries")["numerator"] == 0
    # Mode B recognition is a diagnostic only: outside current-recognition denominators.
    current = _metric(scored, "recognition_hits")
    assert current["denominator"] == 0 and current["assessment"] == "UNSCORED" and current["excluded_count"] == 3
    assert _metric(scored, "recognition_hits_diagnostic")["numerator"] == 2
    assert scored["violations"] == [] and scored["external_request_count"] == 0
    assert any(x.startswith("MODE_B") for x in scored["summary"]["limitations"])


def test_correct_no_trade_blocked_recognition_and_unknown_contradiction_are_separate():
    def event(cutoff, outcome):
        return {"settled_cutoff": f"2026-08-19T{cutoff}:00+00:00", "event_kind": f"SCAN:{outcome}",
                "outcome": outcome, "tool_occurrence_id": None, "first_refusal_code": None, "candidate_id": None}
    directions = [(C.instant("2026-08-19T16:00:00Z"), "bearish", "CURRENT_EXTERNAL")]
    blocked = SC.classify_episode(_label("b", "16:00", "16:05"), [event("16:01", "RISK_REJECTED")], directions)
    quiet = SC.classify_episode(_label("q", "16:00", "16:05", action="STAND_DOWN"),
                                [event("16:01", "NO_CANDIDATE")], directions)
    unknown = SC.classify_episode(_label("u", "16:00", "16:05", direction="UNKNOWN", action="UNKNOWN",
                                         confidence="UNKNOWN", ambiguous=True, opportunity="UNKNOWN"),
                                  [event("16:01", "NO_CANDIDATE")], directions)
    names = {e["label_id"]: {(c["layer"], c["observed"]) for c in e["cells"]} for e in (blocked, quiet, unknown)}
    assert ("REFUSAL", "RECOGNIZED_BLOCKED_BY_RISK_REJECTED") in names["b"] and ("RECOGNITION", "HIT") in names["b"]
    assert ("REFUSAL", "CORRECT_REFUSAL") in names["q"]
    assert ("RECOGNITION", "UNKNOWN_TRUTH_DIRECTIONAL_OBSERVATION") in names["u"]
    assert len({frozenset(v) for v in names.values()}) == 3


# -- T29: tolerance never grants authority before availability ----------------

def test_tolerance_never_moves_availability_earlier():
    directions = [(C.instant("2026-08-19T15:58:00Z"), "bearish", "CURRENT_EXTERNAL")]
    label = _label("late", "15:55", "16:10", earliest="16:00", target=("15:55", "16:05"))
    early_entry = {"settled_cutoff": "2026-08-19T15:59:00+00:00", "event_kind": "SCAN:QUALIFIED_CANDIDATE_OBSERVED",
                   "outcome": "QUALIFIED_CANDIDATE_OBSERVED", "tool_occurrence_id": "x", "first_refusal_code": None,
                   "candidate_id": "c"}
    result = SC.classify_episode(label, [early_entry], directions, tolerance_seconds=3600)
    assert result["first_recognition_utc"] is None
    assert ("TIMING", "EARLY_BEFORE_AVAILABILITY") in {(c["layer"], c["observed"]) for c in result["cells"]}
    assert any(v.startswith("EARLY_POSITIVE_AUTHORITY") for v in result["violations"])
    # Activated control: a tolerant-lookahead label (availability pulled earlier)
    # turns the same early judgment into a hit -- the guard above is what prevents it.
    lookahead = copy.deepcopy(label)
    lookahead["earliest_available_utc"] = "2026-08-19T15:55:00Z"
    assert SC.classify_episode(lookahead, [], directions, tolerance_seconds=3600)["first_recognition_utc"]
    # The same judgment after true availability is a legitimate (late) recognition.
    later = [(C.instant("2026-08-19T16:07:00Z"), "bearish", "CURRENT_EXTERNAL")]
    result = SC.classify_episode(label, [], later, tolerance_seconds=3600)
    assert result["first_recognition_utc"].startswith("2026-08-19T16:07") and result["latency_seconds"] == 120.0
    assert SC.classify_episode(label, [], later)["first_recognition_utc"] is None  # outside target, no tolerance


# -- T28: truth cannot change after scoring ------------------------------------

def test_self_authored_owner_annotation_and_outcome_as_truth_refuse(world):
    forged = _annotation(world, _known_labels(), state="SEALED", role="OWNER", author="STAGE5_ENGINEERING",
                         classification="CONSTRUCTED")
    with pytest.raises(C.ContractError) as exc:
        SC.admit_annotation(forged, corpus=world["corpus"], run_started_at="2026-10-18T00:00:00Z")
    assert exc.value.code == "SELF_AUTHORED_OWNER_ANNOTATION"
    labels = _known_labels()
    events = (world["root"] / "events.jsonl").read_bytes()
    labels[0]["source_evidence"] = [{"path": "events.jsonl", "sha256": C.sha256_hex(events), "bytes": len(events),
                                     "origin": "CONSTRUCTED"}]
    with pytest.raises(C.ContractError) as exc:
        SC.score_trace(world["root"], mode="B", session_id=CP.SESSION, trajectory_id="S5-M06",
                       annotation=_annotation(world, labels))
    assert exc.value.code == "OUTCOME_AS_TRUTH"


def test_post_output_reseal_mutation_and_curated_corpus_refuse(world):
    started = RP.read_manifest(world["root"])["real_started_at"]
    owner = dict(state="SEALED", role="AUTHORIZED_DELEGATE", author="OWNER_DELEGATE", classification="CONSTRUCTED")
    late = _annotation(world, _known_labels(), sealed_at="2099-01-01T00:00:00Z", **owner)
    with pytest.raises(C.ContractError) as exc:
        SC.admit_annotation(late, corpus=world["corpus"], run_started_at=started)
    assert exc.value.code == "ANNOTATION_SEALED_AFTER_OUTPUTS"
    sealed = _annotation(world, _known_labels(), **owner)
    assert SC.admit_annotation(sealed, corpus=world["corpus"], run_started_at=started) == []
    mutated = copy.deepcopy(sealed)
    mutated["labels"][1]["expected_action"] = "ENTRY"
    with pytest.raises(C.ContractError) as exc:
        SC.admit_annotation(mutated, corpus=world["corpus"], run_started_at=started)
    assert exc.value.code == "SEAL_MISMATCH"
    with pytest.raises(C.ContractError) as exc:
        SC.admit_annotation(_annotation(world, _known_labels()), corpus=world["corpus"], run_started_at=started,
                            certification=True)
    assert exc.value.code == "NONOWNER_ANNOTATION_NOT_CERTIFIABLE"
    curated = copy.deepcopy(world["corpus"])
    curated["seal"] = {"sha256": "0" * 64, "sealed_at": "2099-01-01T00:00:00Z", "sealer_ref": "x"}
    with pytest.raises(C.ContractError) as exc:
        SC.admit_corpus(curated, run_started_at=started)
    assert exc.value.code == "CORPUS_SEALED_AFTER_OUTPUTS"


def test_mode_b_can_never_be_declared_current_recognition(world):
    owner = dict(state="SEALED", role="AUTHORIZED_DELEGATE", author="OWNER_DELEGATE", classification="CONSTRUCTED")
    annotation = _annotation(world, _known_labels(), **owner)
    scoring = {"schema_version": "scoring/v1", "document_id": "S", "state": "OWNER_RATIFIED",
               "thresholds": [{"metric": "recognition_hits", "operator": ">=", "value": 0.0, "decision_ref": "x"}]}
    scored = SC.score_trace(world["root"], mode="B", session_id=CP.SESSION, trajectory_id="S5-M06",
                            annotation=annotation, scoring=scoring)
    assert scored["inclusion"]["current_recognition_eligible"] is False
    assert _metric(scored, "recognition_hits")["assessment"] == "UNSCORED"
    result = RP.build_result(document_id="r", run_digest="a" * 64, mode="B", scored=[scored],
                             manifest=RP.read_manifest(world["root"]), artifact_refs=[], missing_prerequisites=[],
                             recognition_ratification_ref="x", stage4_owner_acceptance_ref="y")
    assert result["current_brain_recognition"] == "UNPROVEN"
    with pytest.raises(C.ContractError) as exc:
        C.validate({**result, "current_brain_recognition": "ELIGIBLE_FOR_OWNER_REVIEW"})
    assert exc.value.code == "MOCK_COGNITION_LAUNDERING"


def test_missing_denominators_are_unscored_and_projection_cannot_be_scored(world, tmp_path):
    empty = SC._metric("x", 0, 0)
    assert empty["value"] is None and empty["assessment"] == "UNSCORED"
    with pytest.raises(C.ContractError):
        SC._metric("x", 2, 1)
    scored = SC.score_trace(world["root"], mode="B", session_id=CP.SESSION, trajectory_id="S5-M06", annotation=None)
    assert all(m["assessment"] == "UNSCORED" for m in scored["summary"]["metrics"]
               if m["name"] in ("episodes_with_evidence", "recognition_hits", "exact_occurrence_selected"))
    assert "NO_ANNOTATION" in scored["summary"]["limitations"][0]
    # Identity collapse: an alpha-renamed (semantic) trace has no verifiable chain.
    from recognition_validation import recorder as REC
    projected = CMP.project_events(REC.read_events(world["root"]))
    (tmp_path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in projected))
    with pytest.raises(C.ContractError):
        SC.score_trace(tmp_path, mode="B", session_id=CP.SESSION, trajectory_id="S5-M06", annotation=None)
    raw = REC.read_events(world["root"])
    assert _metric(scored, "unique_candidates")["numerator"] == len({e["candidate_id"] for e in raw
                                                                     if e["candidate_id"]})


# -- CLI ---------------------------------------------------------------------------

def _run_doc(world, path, **over):
    doc = json.loads((ROOT / "src/recognition_validation/examples/current_brain_disabled.json").read_text())
    doc.update(document_id="TEST-RUN", provenance={"classification": "CONSTRUCTED", "author_role": "STAGE5_TEST",
                                                   "source_refs": [], "notes": "CONSTRUCTED test run."},
               corpus_digest=world["digest"], mode="B", ecu=True, trajectory_id="S5-CLI", dry_run=False,
               trajectory_count=1)
    doc.update(over)
    doc.update(C.source_identity())
    doc["quote_policy"] = "CONSTRUCTED"
    stream = K.load_corpus(world["corpus_path"]).sessions[CP.SESSION].stream
    ticks = [t for t in DR.minute_schedule(stream, prewarm_until=DR.utc(PREWARM)) if t.decision_time <= DR.utc(UNTIL)]
    schedule = json.loads((ROOT / "src/recognition_validation/examples/fictional_schedule.json").read_text())
    schedule.update(corpus_digest=world["digest"], ticks=[{"session_id":CP.SESSION,"ordinal":t.ordinal,
                    "decision_time_utc":t.decision_time.isoformat(),"kind":t.kind,"source_ref":None} for t in ticks], seal=None)
    schedule["seal"] = {"sha256":C.seal_digest(schedule),"sealed_at":"2026-10-17T00:00:00Z","sealer_ref":"TEST_ONLY"}
    data = C.canonical(schedule)
    schedule_path = path.with_suffix(".schedule.json")
    schedule_path.write_bytes(data)
    doc["schedule_ref"] = {"path":schedule_path.name,"sha256":C.sha256_hex(data),"bytes":len(data),"origin":"CONSTRUCTED"}
    C.validate(doc)
    path.write_text(json.dumps(doc))
    return path


def _script_file(tmp_path):
    path = tmp_path / "mode_b_script.py"
    path.write_text("import sys\n"
                    f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
                    "import test_recognition_current_path as CP\n"
                    "script, _state = CP._script()\n")
    return path


def test_cli_commands_and_exit_codes(world, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-never-be-used")
    corpus = str(world["corpus_path"])
    assert CLI.main(["validate", "--corpus", corpus]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "corpus/v1", "schema_version": "corpus/v1"}')
    assert CLI.main(["validate", "--corpus", str(bad)]) == 2
    assert CLI.main(["plan", "--corpus", corpus, "--out", str(tmp_path / "plan"), "--prewarm-until", PREWARM]) == 0
    plan = json.loads((tmp_path / "plan" / "plan.json").read_text())
    assert plan["external_requests"] == 0 and plan["tick_count"] > 0
    run = _run_doc(world, tmp_path / "run.json")
    args = ["run", "--mode", "B", "--run", str(run), "--corpus", corpus, "--out", str(tmp_path / "B-ecu"),
            "--script", str(_script_file(tmp_path)), "--prewarm-until", PREWARM, "--ticks-until", UNTIL]
    assert CLI.main(args) == 0
    assert CLI.main(args) == 2  # output root reuse
    assert CLI.main(["run", "--mode", "A", "--run", str(run), "--corpus", corpus, "--out", str(tmp_path / "x")]) == 2
    # Both lanes are separate trajectories with their own reports.
    assert CLI.main(["compare", "--left", str(tmp_path / "B-ecu"), "--right", str(tmp_path / "B-ecu")]) == 0
    tampered = tmp_path / "tampered"
    shutil.copytree(world["root"], tampered)
    lines = (tampered / "events.jsonl").read_text().splitlines()
    assert CLI.main(["compare", "--left", str(world["root"]), "--right", str(tampered)]) == 0
    (tampered / "events.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    assert CLI.main(["compare", "--left", str(world["root"]), "--right", str(tampered)]) == 4
    assert CLI.main(["report", "--run", str(tmp_path / "B-ecu"), "--out", str(tmp_path / "r0")]) == 3
    result = json.loads((tmp_path / "r0" / "result.json").read_text())
    assert result["current_brain_recognition"] == "UNPROVEN" and result["final_status"] == "READY_FOR_OWNER_REVIEW"
    assert result["session_summaries"][0]["trajectory_id"] == "S5-CLI"
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps(_annotation(world, _known_labels())))
    assert CLI.main(["report", "--run", str(tmp_path / "B-ecu"), "--out", str(tmp_path / "r1"), "--corpus", corpus,
                     "--annotations", str(annotations)]) == 0
    report = (tmp_path / "r1" / "report.md").read_text()
    assert "CORRECT_REFUSAL" in report and "UNPROVEN" in report
    # Mode C: dry run is a finite zero-request plan; a real run is refused.
    run_c = _run_doc(world, tmp_path / "run_c.json", mode="C", dry_run=True, trajectory_count=0)
    assert CLI.main(["run", "--mode", "C", "--dry-run", "--run", str(run_c), "--corpus", corpus,
                     "--out", str(tmp_path / "C-dry"), "--prewarm-until", PREWARM]) == 0
    dry = json.loads((tmp_path / "C-dry" / "mode_c_dry_run.json").read_text())
    assert dry["external_requests_made"] == 0 and "CURRENT_MODEL_CALLS_DISABLED" in dry["blockers"]
    assert CLI.main(["run", "--mode", "C", "--run", str(run_c), "--corpus", corpus,
                     "--out", str(tmp_path / "C-live")]) == 2
    assert not (tmp_path / "C-live").exists()
    capsys.readouterr()


def test_t27_recording_failure_or_missing_artifact_is_incomplete_never_a_pass(world, tmp_path):
    broken = tmp_path / "broken"
    shutil.copytree(world["root"], broken)
    manifest = json.loads((broken / RP.MANIFEST).read_text())
    manifest["infrastructure_error"] = "OSError: No space left on device"
    manifest["seal"]["sha256"] = C.seal_digest(manifest)
    (broken / RP.MANIFEST).write_text(json.dumps(manifest))
    assert CLI.main(["report", "--run", str(broken), "--out", str(tmp_path / "r")]) == 5
    result = json.loads((tmp_path / "r" / "result.json").read_text())
    assert result["engineering_status"] == "INCOMPLETE" and result["final_status"] == "ENGINEERING_INCOMPLETE"
    missing = tmp_path / "missing"
    shutil.copytree(world["root"], missing)
    victim = next((missing / "artifacts" / "raw").iterdir())
    victim.unlink()
    assert CLI.main(["report", "--run", str(missing), "--out", str(tmp_path / "r2")]) == 5
    assert not (tmp_path / "r2" / "result.json").exists()
    nomanifest = tmp_path / "nomanifest"
    shutil.copytree(world["root"], nomanifest)
    (nomanifest / RP.MANIFEST).unlink()
    assert CLI.main(["report", "--run", str(nomanifest), "--out", str(tmp_path / "r3")]) == 5
