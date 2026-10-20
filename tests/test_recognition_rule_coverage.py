"""Stage 5 gap mission 1: every required scoring rule stays an explicit obligation.

Owner-audit residual: a ratified rule whose denominator was zero lost its
threshold_ref and vanished from the all-pass aggregation, so the report said
ELIGIBLE_FOR_OWNER_REVIEW while a required metric was unscored. Now every
ratified rule in every required session/trajectory carries PASS, FAIL or
UNPROVEN (with a reason) and eligibility needs complete coverage.

All scoring plans, inclusions and summaries here are FICTIONAL/CONSTRUCTED unit
preconditions -- never Maurice's annotation, a ratified plan, or a model call.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_recognition_current_path as CP  # noqa: E402
import test_recognition_scoring_cli as SCLI  # noqa: E402
from recognition_validation import __main__ as CLI  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import report as RP  # noqa: E402
from recognition_validation import scoring as SC  # noqa: E402

world = SCLI.world  # the real Mode B trace of the CONSTRUCTED distinct-anchor session

RULE_A = {"metric": "recognition_hits", "operator": ">=", "value": 1, "decision_ref": "FICTIONAL-UNIT-RULE-A"}
RULE_B = {"metric": "false_positive_entries", "operator": "<=", "value": 0, "decision_ref": "FICTIONAL-UNIT-RULE-B"}
REFS = dict(recognition_ratification_ref="FICTIONAL-UNIT-PRECONDITION-ONLY",
            stage4_owner_acceptance_ref="FICTIONAL-UNIT-PRECONDITION-ONLY")


class SyntheticInclusion:
    ratified = True
    current_recognition = True


def _plan(*rules, state="OWNER_RATIFIED"):
    return {"state": state, "thresholds": [dict(r) for r in rules]}


def _summary(counts, *, plan, session="FICTIONAL-UNIT-SESSION", trajectory="FICTIONAL-UNIT-T1", eligible=True):
    """A synthetic score_trace item: (numerator, denominator) per metric, thresholds via the real helper."""
    inclusion = SyntheticInclusion() if eligible else SC.Inclusion(mode="B", annotation=None, scoring=None)
    metrics = [SC._threshold(SC._metric(name, *counts.get(name, (0, 0))), plan, inclusion) for name in SC.METRIC_NAMES]
    summary = dict(session_id=session, trajectory_id=trajectory, scored_episode_count=0, missing_episode_count=0,
                   metrics=metrics, confusion_cells=[], first_recognition_utc=None, first_candidate_utc=None,
                   first_refusal_code=None, limitations=["CONSTRUCTED unit precondition; not owner truth"])
    return dict(summary=summary, violations=[], inclusion={"current_recognition_eligible": eligible},
                external_request_count=0, event_count=1, call_count=0)


def _result(scored, *, mode="C", scoring=None, units=None, refs=True):
    manifest = dict(events=len(scored), tick_count=len(scored), ticks=len(scored), primary_calls=0, repair_calls=0,
                    process_isolation={"kind": "FRESH_CHILD"})  # synthetic precondition (gap mission 2)
    return RP.build_result(document_id="FICTIONAL-UNIT-RESULT", run_digest="a" * 64, mode=mode, scored=scored,
                           manifest=manifest, artifact_refs=[], missing_prerequisites=[], scoring=scoring,
                           required_units=units, **(REFS if refs else {}))


def _units(*pairs):
    return [{"session_id": s, "trajectory_id": t} for s, t in pairs]


UNIT = _units(("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T1"))


def _obligations(result):
    return {(o["session_id"], o["trajectory_id"], o["metric"]): (o["status"], o["reason"])
            for o in result["rule_coverage"]["obligations"]}


# -- the owner-audit parent reproducer, through the actual scorer helpers + report consumer --

def test_parent_reproducer_zero_denominator_rule_no_longer_disappears():
    scoring = {"thresholds": [RULE_A, RULE_B]}
    metrics = [SC._threshold(SC._metric("recognition_hits", 0, 0), scoring, SyntheticInclusion()),
               SC._threshold(SC._metric("false_positive_entries", 0, 1), scoring, SyntheticInclusion())]
    # The required rule keeps its binding and is UNPROVEN, not silently dropped.
    assert metrics[0]["threshold_ref"] == "FICTIONAL-UNIT-RULE-A" and metrics[0]["assessment"] == "UNPROVEN"
    assert metrics[1]["assessment"] == "PASS"

    def consume(candidate):
        item = _summary({}, plan=scoring)
        item["summary"]["metrics"] = candidate
        return _result([item])
    report = consume(metrics)
    assert report["current_brain_recognition"] == "UNPROVEN"  # parent: ELIGIBLE_FOR_OWNER_REVIEW
    assert report["rule_coverage"]["status"] == "UNDECLARED"
    # Healthy failure control from the same probe: actual evidence violating rule A is FAIL.
    control = consume([SC._threshold(SC._metric("recognition_hits", 0, 1), scoring, SyntheticInclusion()), metrics[1]])
    assert control["current_brain_recognition"] == "FAIL" and control["rule_coverage"]["status"] == "FAIL"


# -- declared coverage: rule x required session/trajectory -----------------------------

def test_zero_denominator_single_rule_is_unproven_with_reason():
    plan = _plan(RULE_A)
    result = _result([_summary({}, plan=plan)], scoring=plan, units=UNIT)
    assert result["current_brain_recognition"] == "UNPROVEN"
    assert result["rule_coverage"]["status"] == "INCOMPLETE"
    assert _obligations(result) == {("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T1", "recognition_hits"):
                                    ("UNPROVEN", "ZERO_DENOMINATOR")}
    assert any(m.startswith("RULE_COVERAGE_INCOMPLETE: 1 of 1") for m in result["missing_prerequisites"])
    C.validate(json.loads(json.dumps(result)))


def test_multi_rule_zero_denominator_and_mixed_pass_unscored_stay_unproven():
    plan = _plan(RULE_A, RULE_B)
    mixed = _result([_summary({"false_positive_entries": (0, 3)}, plan=plan)], scoring=plan, units=UNIT)
    assert mixed["current_brain_recognition"] == "UNPROVEN" and mixed["rule_coverage"]["status"] == "INCOMPLETE"
    assert sorted(v for v in _obligations(mixed).values()) == [("PASS", None), ("UNPROVEN", "ZERO_DENOMINATOR")]
    allzero = _result([_summary({}, plan=plan)], scoring=plan, units=UNIT)
    assert {v for v in _obligations(allzero).values()} == {("UNPROVEN", "ZERO_DENOMINATOR")}
    assert allzero["current_brain_recognition"] == "UNPROVEN"
    # Missing coverage is never misreported as a demonstrated failure.
    assert "FAIL" not in {o["status"] for o in allzero["rule_coverage"]["obligations"]}


def test_missing_required_session_or_trajectory_owes_every_rule():
    plan = _plan(RULE_A, RULE_B)
    good = _summary({"recognition_hits": (2, 2), "false_positive_entries": (0, 2)}, plan=plan)
    units = _units(("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T1"), ("FICTIONAL-SESSION-2", None),
                   ("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T2"))
    result = _result([good], scoring=plan, units=units)
    status = _obligations(result)
    assert status[("FICTIONAL-SESSION-2", None, "recognition_hits")] == ("UNPROVEN", "REQUIRED_TRAJECTORY_NOT_SCORED")
    assert status[("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T2", "false_positive_entries")][1] == \
        "REQUIRED_TRAJECTORY_NOT_SCORED"
    assert len(status) == 6 and result["current_brain_recognition"] == "UNPROVEN"
    C.validate(json.loads(json.dumps(result)))
    # An empty required set (e.g. an ENGINEERING-only corpus) can never be complete.
    empty = _result([good], scoring=plan, units=[])
    assert empty["rule_coverage"]["status"] == "INCOMPLETE" and empty["current_brain_recognition"] == "UNPROVEN"


def test_actual_violated_rule_is_fail_even_beside_unscored_rules():
    plan = _plan(RULE_A, RULE_B)
    violated = _summary({"recognition_hits": (0, 4), "false_positive_entries": (0, 0)}, plan=plan)
    result = _result([violated], scoring=plan, units=UNIT)
    assert result["current_brain_recognition"] == "FAIL" and result["rule_coverage"]["status"] == "FAIL"
    assert _obligations(result)[("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T1", "recognition_hits")] == ("FAIL", None)
    C.validate(json.loads(json.dumps(result)))


def test_all_rules_genuinely_pass_reach_only_eligible_for_owner_review():
    plan = _plan(RULE_A, RULE_B)
    passing = _summary({"recognition_hits": (4, 4), "false_positive_entries": (0, 4)}, plan=plan)
    result = _result([passing], scoring=plan, units=UNIT)
    assert result["rule_coverage"]["status"] == "COMPLETE"
    assert result["current_brain_recognition"] == "ELIGIBLE_FOR_OWNER_REVIEW"
    assert result["final_status"] == "READY_FOR_OWNER_REVIEW" and result["production_authorized"] is False
    C.validate(json.loads(json.dumps(result)))
    # Same evidence, but any missing precondition keeps it UNPROVEN; never OWNER_ACCEPTED.
    assert _result([passing], scoring=plan, units=UNIT, refs=False)["current_brain_recognition"] == "UNPROVEN"
    assert _result([passing], scoring=plan, units=None)["current_brain_recognition"] == "UNPROVEN"
    assert _result([passing], scoring=_plan(RULE_A, RULE_B, state="PROPOSED"),
                   units=UNIT)["current_brain_recognition"] == "UNPROVEN"
    mock = _summary({"recognition_hits": (4, 4), "false_positive_entries": (0, 4)}, plan=plan, eligible=False)
    for mode in ("A", "B"):
        assert _result([mock], mode=mode, scoring=plan, units=UNIT)["current_brain_recognition"] == "UNPROVEN"
    assert _obligations(_result([mock], scoring=plan, units=UNIT))[
        ("FICTIONAL-UNIT-SESSION", "FICTIONAL-UNIT-T1", "recognition_hits")] == \
        ("UNPROVEN", "NOT_CURRENT_RECOGNITION_ELIGIBLE")


def test_unknown_or_duplicate_rules_keep_hard_refusals():
    item = _summary({}, plan=_plan(RULE_A))
    for plan, code in ((_plan(dict(RULE_A, metric="not_implemented")), "UNKNOWN_SCORING_METRIC"),
                       (_plan(RULE_A, dict(RULE_A, decision_ref="other")), "DUPLICATE_SCORING_METRIC")):
        with pytest.raises(C.ContractError) as exc:
            _result([item], scoring=plan, units=UNIT)
        assert exc.value.code == code
    with pytest.raises(C.ContractError) as exc:
        _result([item, copy.deepcopy(item)], scoring=_plan(RULE_A), units=UNIT)
    assert exc.value.code == "DUPLICATE_TRAJECTORY_SUMMARY"


# -- result/v2 schema round trip and forged-coverage refusals ------------------------

def test_result_schema_round_trip_and_forged_coverage_refuses():
    plan = _plan(RULE_A, RULE_B)
    result = json.loads(json.dumps(_result([_summary({"false_positive_entries": (0, 3)}, plan=plan)],
                                           scoring=plan, units=UNIT)))
    assert result["schema_version"] == "result/v2" and C.validate(result) == "result"

    def refused(mutate, code):
        forged = copy.deepcopy(result)
        mutate(forged)
        with pytest.raises(C.ContractError) as exc:
            C.validate(forged)
        assert exc.value.code == code

    def drop_unscored(doc):  # the parent defect, expressed in the artifact
        doc["rule_coverage"]["obligations"] = [o for o in doc["rule_coverage"]["obligations"]
                                               if o["status"] != "UNPROVEN"]
        doc["rule_coverage"]["status"] = "COMPLETE"
        doc["current_brain_recognition"] = "ELIGIBLE_FOR_OWNER_REVIEW"
        doc["recognition_ratification_ref"] = "x"
    refused(drop_unscored, "RULE_OBLIGATION_SET_INCOMPLETE")

    def upgrade_unscored(doc):
        o = next(o for o in doc["rule_coverage"]["obligations"] if o["status"] == "UNPROVEN")
        o.update(status="PASS", reason=None)
    refused(upgrade_unscored, "SCORED_OBLIGATION_WITHOUT_EVIDENCE")
    refused(lambda d: d["rule_coverage"].update(status="COMPLETE"), "RULE_COVERAGE_STATUS_MISMATCH")
    refused(lambda d: d.update(current_brain_recognition="ELIGIBLE_FOR_OWNER_REVIEW", recognition_ratification_ref="x"),
            "ELIGIBILITY_WITHOUT_COMPLETE_RULE_COVERAGE")
    refused(lambda d: d.update(current_brain_recognition="FAIL"), "FAIL_WITHOUT_SCORED_RULE_FAILURE")
    refused(lambda d: next(o for o in d["rule_coverage"]["obligations"] if o["status"] == "PASS").update(value=0.5),
            "OBLIGATION_ASSESSMENT_MISMATCH")
    refused(lambda d: d.pop("rule_coverage"), "RULE_COVERAGE_REQUIRED")
    # result/v1 stays readable but can no longer carry an unverifiable eligibility claim.
    v1 = json.loads((ROOT / "src/recognition_validation/examples/fictional_result.json").read_text())
    assert C.validate(v1) == "result"
    with pytest.raises(C.ContractError) as exc:
        C.validate({**v1, "mode": "C", "current_brain_recognition": "ELIGIBLE_FOR_OWNER_REVIEW",
                    "recognition_ratification_ref": "x", "stage4_owner_acceptance_ref": "y"})
    assert exc.value.code == "RESULT_V1_RULE_COVERAGE_UNVERIFIABLE"


def test_activated_mutant_dropping_the_missing_obligation_is_detected(monkeypatch):
    """Re-introduce the parent aggregation (unscored obligations vanish): the eligibility
    claim it produces is refused by the result contract instead of being emitted."""
    plan = _plan(RULE_A, RULE_B)
    item = _summary({"false_positive_entries": (0, 3)}, plan=plan)
    healthy = _result([item], scoring=plan, units=UNIT)
    assert healthy["current_brain_recognition"] == "UNPROVEN"
    real = RP.rule_coverage

    def parent_like(scored, *, scoring=None, units=None):
        coverage = real(scored, scoring=scoring, units=units)
        coverage["obligations"] = [o for o in coverage["obligations"] if o["status"] != "UNPROVEN"]
        coverage["status"] = RP.coverage_status(coverage["declared"], coverage["obligations"])
        return coverage
    monkeypatch.setattr(RP, "rule_coverage", parent_like)
    with pytest.raises(C.ContractError) as exc:
        _result([item], scoring=plan, units=UNIT)
    assert exc.value.code == "RULE_OBLIGATION_SET_INCOMPLETE"


# -- the real scorer -> report composition on an actual recorded trace -----------------

def _ratified_plan(world, *rules, annotation=None):
    doc = {"schema_version": "scoring/v1", "document_id": "FICTIONAL-RATIFIED-FOR-TEST",
           "provenance": {"classification": "FICTIONAL", "author_role": "STAGE5_TEST",
                          "source_refs": ["tests/test_recognition_rule_coverage.py"],
                          "notes": "FICTIONAL test plan; not an owner ratification."},
           "state": "OWNER_RATIFIED", "owner_decision_ref": "FICTIONAL-TEST-ONLY", "corpus_digest": world["digest"],
           "annotation_digests": [C.seal_digest(annotation)] if annotation else [], "direction_labels": list(SC.DIRECTIONS), "tolerance_seconds": None,
           "unknown_scoring_rule": "DESCRIPTIVE_ONLY", "thresholds": [dict(r) for r in rules],
           "unit_of_analysis": "SESSION_TRAJECTORY_EPISODE", "seal": None}
    doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": "2026-10-17T00:00:00Z", "sealer_ref": "TEST_ONLY"}
    C.validate(doc)
    return doc


def test_real_trace_scorer_to_report_keeps_every_required_obligation(world):
    plan = _ratified_plan(world, RULE_A, RULE_B)
    annotation = SCLI._annotation(world, SCLI._known_labels())
    scored = SC.score_trace(world["root"], mode="B", session_id=CP.SESSION, trajectory_id="S5-M06",
                            annotation=annotation, scoring=plan)
    units = _units((CP.SESSION, "S5-M06"), (CP.SESSION, "S5-M06-SECOND-TRAJECTORY"))
    result = RP.build_result(document_id="r", run_digest="a" * 64, mode="B", scored=[scored],
                             manifest=RP.read_manifest(world["root"]), artifact_refs=[], missing_prerequisites=[],
                             scoring=plan, required_units=units, **REFS)
    reasons = {(o["trajectory_id"], o["metric"]): o["reason"] for o in result["rule_coverage"]["obligations"]}
    assert reasons == {("S5-M06", "recognition_hits"): "NOT_CURRENT_RECOGNITION_ELIGIBLE",
                       ("S5-M06", "false_positive_entries"): "NOT_CURRENT_RECOGNITION_ELIGIBLE",
                       ("S5-M06-SECOND-TRAJECTORY", "recognition_hits"): "REQUIRED_TRAJECTORY_NOT_SCORED",
                       ("S5-M06-SECOND-TRAJECTORY", "false_positive_entries"): "REQUIRED_TRAJECTORY_NOT_SCORED"}
    assert result["current_brain_recognition"] == "UNPROVEN" and result["rule_coverage"]["status"] == "INCOMPLETE"
    C.validate(json.loads(json.dumps(result)))


def test_cli_report_round_trips_rule_coverage_from_the_corpus(world, tmp_path, capsys):
    annotation = SCLI._annotation(world, SCLI._known_labels())
    plan = _ratified_plan(world, RULE_A, annotation=annotation)
    scoring = tmp_path / "scoring.json"
    scoring.write_text(json.dumps(plan))
    corpus = str(world["corpus_path"])
    code = CLI.main(["report", "--run", str(world["root"]), "--out", str(tmp_path / "r"), "--corpus", corpus,
                     "--scoring", str(scoring), "--annotations", str(_write(tmp_path, annotation))])
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    result = json.loads((tmp_path / "r" / "result.json").read_text())
    C.validate(result)
    # The CONSTRUCTED corpus has only an ENGINEERING session: no evaluation obligation can be met.
    assert result["rule_coverage"]["declared"] is True and result["rule_coverage"]["required_units"] == []
    assert result["rule_coverage"]["status"] == "INCOMPLETE" and printed["rule_coverage"] == "INCOMPLETE"
    assert code == CLI.EXIT_MISSING and result["current_brain_recognition"] == "UNPROVEN"
    assert "Required rule coverage: INCOMPLETE" in (tmp_path / "r" / "report.md").read_text()
    # Without the corpus the required set is undeclared, and the report says so.
    CLI.main(["report", "--run", str(world["root"]), "--out", str(tmp_path / "r2"), "--scoring", str(scoring)])
    undeclared = json.loads((tmp_path / "r2" / "result.json").read_text())
    assert undeclared["rule_coverage"]["status"] == "UNDECLARED"
    assert any(m.startswith("CORPUS_ABSENT") for m in undeclared["missing_prerequisites"])
    capsys.readouterr()


def test_required_units_follow_only_the_owner_corpus_partition_and_ratified_exclusions():
    def session(sid, partition="EVALUATION", eligibility="ELIGIBLE", reasons=()):
        return {"session_id": sid, "partition": partition, "eligibility": eligibility,
                "exclusion_reasons": list(reasons)}
    corpus = {"selection_state": "OWNER_RATIFIED",
              "sessions": [session("eval-1"), session("eval-2"), session("cal", partition="CALIBRATION"),
                           session("excluded", eligibility="EXCLUDED", reasons=["FICTIONAL owner exclusion"]),
                           session("excluded-no-reason", eligibility="EXCLUDED")]}
    scored = [{"summary": {"session_id": "eval-1", "trajectory_id": "t1"}}]
    assert RP.required_units(corpus, scored) == _units(("eval-1", "t1"), ("eval-2", None),
                                                       ("excluded-no-reason", None))
    # An unratified corpus cannot exclude anything.
    proposed = dict(corpus, selection_state="PROPOSED")
    assert ("excluded", None) in {(u["session_id"], u["trajectory_id"]) for u in RP.required_units(proposed, scored)}


def _write(tmp_path, document):
    path = tmp_path / "annotation.json"
    path.write_text(json.dumps(document))
    return path
