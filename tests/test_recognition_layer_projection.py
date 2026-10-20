"""Stage 5 gap mission 4: six-layer fact/campaign/causal/timing projection and scoring.

Every non-PREWARM tick of a real trajectory writes a `layer_projection/v1`
artifact read only from the actual producers (snapshot, Draw, active path,
Lifecycle, candidate or live plan, loop outcome, final-quote economics). The
scorer compares it to sealed admissible truth only: the sealed corpus for
MARKET_FACTS, annotation fields for the rest. Absent annotation is UNSCORED,
absent or unusable evidence UNPROVEN, each with a reason and source binding;
neither is a MISS and a no-trade is never wrong.

The healthy trajectories are the mission 3 CONSTRUCTED distinct-anchor
worlds (MOCK Brain `watching` plan, both venue lanes). Each layer is then
mutated independently -- in the producer inputs where a natural tape exists
(provider revision, missed scans), in a copy of the real projections where it
does not -- and the consumer/scoring boundary must detect it, against a healthy
control. All labels are FICTIONAL engineering labels, never owner truth.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_recognition_quote_wake_trigger as M3  # noqa: E402
import test_recognition_rule_coverage as RC  # noqa: E402
import test_recognition_scoring_cli as SCLI  # noqa: E402
from recognition_validation import __main__ as CLI  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import layers as LY  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402
from recognition_validation import report as RP  # noqa: E402
from recognition_validation import scoring as SC  # noqa: E402

DISARMED, REFUSING = DR.VENUE_LANES
SESSION = M3.CP.SESSION
OCCURRENCE = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T16:25:00+00:00:bearish:LIQUIDITY_SWEEP:"
              "CON.F.US.MNQ.Z26:5m:2026-08-19T16:15:00+00:00:5m:swing_high:29518.5:2026-08-19T16:19:00+00:00")
OBJECTIVE = "opposing_external_liquidity:sellside@29505.5"
ORIGIN = {"at": "2026-08-19T14:25:00+00:00",
          "occurrence_id": "LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:1m:2026-08-19T14:25:00+00:00:above_high"}


def _evidence(kind, event_id=None, *, source_time=None, level=None, timeframe=None):
    """One annotation evidence reference (annotation.schema campaign_origin/... items)."""
    return {"kind": kind, "event_id": event_id, "timeframe": timeframe, "source_time": source_time,
            "available_at": None, "level": level, "unresolved_reason": None}


def _world(tmp_path_factory, variant="HEALTHY", lane=DISARMED, **kw):
    world = M3.run(tmp_path_factory, variant, lane, **kw)
    if "projections" not in world:
        world["projections"] = SC.read_projections(world["evidence"], REC.read_events(world["evidence"]))
        world["stream"] = K.load_corpus(world["corpus_path"]).sessions[SESSION].stream
    return world


def _label(label_id="plan", start="16:29", end="16:35", **over):
    label = SCLI._label(label_id, start, end, action="WATCHING")
    label.update(delivery_state="RETRACEMENT", playbook_family="manipulation_to_distribution",
                 tool_family="po3_reversal_order_block", occurrence_id=OCCURRENCE,
                 campaign_objective=[_evidence("opposing_external_liquidity", OBJECTIVE, level=29505.5)],
                 campaign_origin=[_evidence("buy_side_raid_rejected", ORIGIN["occurrence_id"],
                                            source_time=ORIGIN["at"], timeframe="1m")])
    label.update(over)
    return label


def _score(projections, label, *, stream=None, findings=None):
    findings = findings or LY.sequence(projections)
    return {c["layer"]: c for c in LY.score_label(label, projections, findings, stream=stream,
                                                     stream_supplied=stream is not None)}


def _at(projections, hhmmss):
    return next(p for p in projections if p["tick"]["decision_time"][11:19] == hhmmss)


# -- acceptance: one healthy exact-source chronological trajectory, both lanes --------------

@pytest.mark.parametrize("ecu", [False, True], ids=["non-ECU", "ECU"])
@pytest.mark.parametrize("lane", [DISARMED, REFUSING])
def test_healthy_trajectory_projects_every_layer_from_the_actual_producers(tmp_path_factory, lane, ecu):
    world = _world(tmp_path_factory, lane=lane, ecu=ecu)
    projections, stream = world["projections"], world["stream"]
    ticks = [e for e in REC.read_events(world["evidence"]) if not e["event_kind"].startswith("PREWARM")]
    assert len(projections) == len(ticks) and len(projections) >= 15
    for p in projections:
        LY.check_projection(p)
        assert LY.chronology(p, stream=stream) == []
    assert LY.sequence(projections) == {"duplicate_cognition_cutoffs": [], "missed_scans": [], "revisions": [],
                                        "restarts": []}
    trigger = _at(projections, "16:32:30")
    layers = trigger["layers"]
    assert {name: layer["state"] for name, layer in layers.items()} == dict.fromkeys(LY.LAYERS, "PROJECTED")
    facts = layers["MARKET_FACTS"]
    assert (facts["bar_open"], facts["settled_cutoff"], facts["temporal_status"]) == (
        "2026-08-19T16:31:00+00:00", "2026-08-19T16:32:00+00:00", "settled")
    assert facts["release"]["version"] == 1 and facts["release"]["bar"] == facts["bar"]
    campaign = layers["CAMPAIGN"]
    assert (campaign["direction"], campaign["objective"]["identity"]) == ("bearish", OBJECTIVE)
    assert campaign["origin"]["occurrence_id"] == ORIGIN["occurrence_id"]
    # The brainless trigger has no current Brain authority: Lifecycle says so, the path owner is intact.
    assert (layers["DELIVERY"]["lifecycle_state"], layers["DELIVERY"]["projected_state"]) == ("AUTHORITY_UNKNOWN",
                                                                                             "UNKNOWN")
    assert layers["DELIVERY"]["owner"] == "bearish" and layers["DELIVERY"]["transfer_flags"] == []
    assert (layers["TOOL"]["occurrence_id"], layers["TOOL"]["direction"]) == (OCCURRENCE, "bearish")
    assert layers["COMPOSITION"]["route"] == "CONDITIONAL_TRIGGER" and layers["COMPOSITION"]["brain_primary_calls"] == 0
    timing = layers["TIMING"]
    # Every clock kept separate: market open < settled cutoff < decision; capture < trigger (< final quote).
    assert timing["market_open"] == "2026-08-19T13:00:00Z"
    assert (timing["settled_cutoff"], timing["latest_available_at"]) == ("2026-08-19T16:32:00+00:00",) * 2
    assert (timing["plan_capture_at"], timing["trigger_at"], timing["decision_time"]) == (
        "2026-08-19T16:30:00+00:00", "2026-08-19T16:32:30+00:00", "2026-08-19T16:32:30+00:00")
    if lane == REFUSING:
        quote = layers["COMPOSITION"]["final_quote"]
        assert quote["decision"] == "EXECUTE_AS_AUTHORIZED" and quote["reference"] == 29514.0
        assert timing["final_quote_at"] == "2026-08-19T16:32:30+00:00"
    else:
        assert layers["COMPOSITION"]["final_quote"] is None and timing["final_quote_at"] is None
    # Authoring scans carry the Brain's own judgment and current Lifecycle.
    authoring = _at(projections, "16:30:00")["layers"]
    assert authoring["CAMPAIGN"]["brain_direction"] == "bearish"
    assert authoring["DELIVERY"]["projected_state"] == "ACTIVE_DELIVERY"
    assert authoring["COMPOSITION"]["outcome"] == "CONDITIONAL_PLAN_PUBLISHED"


@pytest.mark.parametrize("lane", [DISARMED, REFUSING])
def test_healthy_labels_score_every_layer_and_local_opposing_movement_is_no_reversal(tmp_path_factory, lane):
    world = _world(tmp_path_factory, lane=lane)
    cells = _score(world["projections"], _label(), stream=world["stream"])
    assert {k: (c["state"], c["agreement"]) for k, c in cells.items()} == dict.fromkeys(LY.LAYERS, ("SCORED", True))
    # 16:31-16:32 rallies into the order block against the bearish campaign: a retracement, not a reversal.
    assert cells["DELIVERY"]["observed"] in LY.INTACT_STATES
    assert cells["TIMING"]["observed"] == "ON_TIME" and cells["MARKET_FACTS"]["observed"] == "CONSISTENT"
    assert all(c["source_binding"] and c["truth_field"] for c in cells.values())
    # Without the sealed corpus, MARKET_FACTS is UNPROVEN, never assumed.
    assert _score(world["projections"], _label())["MARKET_FACTS"]["reason"] == "SEALED_CORPUS_NOT_SUPPLIED"


def test_healthy_layers_round_trip_schema_cli_and_report(tmp_path_factory, tmp_path):
    world = _world(tmp_path_factory)
    corpus = K.load_corpus(world["corpus_path"])
    annotation = SCLI._annotation({"digest": corpus.digest}, [_label(), _label("quiet", "15:40", "15:50")])
    path = tmp_path / "annotation.json"
    path.write_text(json.dumps(annotation))
    code = CLI.main(["report", "--run", str(world["evidence"]), "--out", str(tmp_path / "report"),
                     "--annotations", str(path), "--corpus", str(world["corpus_path"])])
    result = json.loads((tmp_path / "report" / "result.json").read_text())
    assert code == CLI.EXIT_OK and result["invariant_failures"] == []
    C.validate(result)
    summary = result["session_summaries"][0]
    rows = {r["layer"]: r for r in summary["layer_table"]}
    assert list(rows) == list(LY.LAYERS) and all(rows[k]["agree"] == 1 for k in LY.LAYERS)
    # The label over declared-prewarm minutes has no projection at all: UNPROVEN in every layer, never a MISS.
    quiet = [c for c in summary["layer_cells"] if c["label_id"] == "quiet"]
    assert {c["state"] for c in quiet} == {"UNPROVEN"} and all(c["reason"].startswith("EVIDENCE_ABSENT") for c in quiet)
    metrics = {m["name"]: m for m in summary["metrics"]}
    assert metrics["layer_campaign"]["numerator"] == 1 and metrics["layer_campaign"]["unproven_count"] == 1
    report = (tmp_path / "report" / "report.md").read_text()
    assert "Six-layer projection" in report and "MARKET_FACTS" in report
    # Forged layer cell state is refused by the result schema.
    forged = copy.deepcopy(result)
    forged["session_summaries"][0]["layer_cells"][0]["state"] = "MISS"
    with pytest.raises(C.ContractError):
        C.validate(forged)


def test_facts_from_another_corpus_fail_the_result_end_to_end(tmp_path_factory):
    """The healthy trace scored against the revised corpus: the 16:31 bar it used is not that corpus's bar."""
    world, revised = _world(tmp_path_factory), _world(tmp_path_factory, "PROVIDER_REVISION")
    scored = SC.score_trace(world["evidence"], mode="B", session_id=SESSION, trajectory_id="S5-M3-HEALTHY",
                            annotation=None, stream=revised["stream"])
    assert scored["violations"] and all(v.startswith("FACT_NOT_SEALED:tick:") for v in scored["violations"])
    control = SC.score_trace(world["evidence"], mode="B", session_id=SESSION, trajectory_id="S5-M3-HEALTHY",
                             annotation=None, stream=world["stream"])
    assert control["violations"] == []
    manifest = dict(world["manifest"])
    result = RP.build_result(
        document_id="S5-M4-WRONG-CORPUS", run_digest=manifest["run_digest"], mode="B", scored=[scored],
        manifest=manifest, artifact_refs=[], missing_prerequisites=[])
    assert result["engineering_status"] == "FAIL" and result["final_status"] == "FAIL"
    assert result["invariant_failures"] == sorted(set(scored["violations"]))


# -- absent annotation / evidence, unknown and contradictory judgment ---------------------

def test_absent_annotation_fields_are_unscored_and_unknown_truth_is_never_scored(tmp_path_factory):
    world = _world(tmp_path_factory)
    bare = _label(playbook_family=None, tool_family=None, occurrence_id=None)
    assert _score(world["projections"], bare)["TOOL"]["reason"] == "ANNOTATION_ABSENT:playbook_family/tool_family/occurrence_id"
    unknown = _label(dominant_campaign_direction="UNKNOWN", delivery_state="UNKNOWN", expected_action="UNKNOWN",
                     confidence="UNKNOWN", ambiguous=True)
    cells = _score(world["projections"], unknown, stream=world["stream"])
    for layer in ("CAMPAIGN", "DELIVERY", "COMPOSITION", "TIMING"):
        assert (cells[layer]["state"], cells[layer]["reason"]) == ("UNSCORED", "ANNOTATION_UNKNOWN")
    assert cells["MARKET_FACTS"]["state"] == "SCORED"   # facts are judged against the corpus, not the label


def test_unknown_and_contradictory_judgment_are_unproven(tmp_path_factory):
    world = _world(tmp_path_factory)
    # 16:31-16:33 is the brainless stretch: production's Lifecycle is AUTHORITY_UNKNOWN throughout.
    cells = _score(world["projections"], _label("brainless", "16:31", "16:33"))
    assert (cells["DELIVERY"]["state"], cells["DELIVERY"]["reason"]) == ("UNPROVEN", "LIFECYCLE_AUTHORITY_UNKNOWN")
    contradictory = copy.deepcopy(world["projections"])
    _at(contradictory, "16:29:00")["layers"]["CAMPAIGN"]["brain_direction"] = "bullish"
    cell = _score(contradictory, _label())["CAMPAIGN"]
    assert (cell["state"], cell["observed"]) == ("UNPROVEN", "CONTRADICTORY_JUDGMENT")
    assert _score(world["projections"], _label())["CAMPAIGN"]["agreement"] is True   # healthy control


def test_no_trade_is_never_wrong(tmp_path_factory):
    world = _world(tmp_path_factory)
    cell = _score(world["projections"], _label("pre", "16:21", "16:29", expected_action="ENTRY"))["COMPOSITION"]
    assert (cell["observed"], cell["state"], cell["reason"]) == ("NO_TRADE", "UNSCORED", "NO_TRADE_NEVER_WRONG")


# -- each layer mutated independently: the consumer/scoring boundary detects it --------------

def _mutate(projections, at, layer, **fields):
    out = copy.deepcopy(projections)
    _at(out, at)["layers"][layer].update(fields)
    return out


def _bar(projections, at, **bar):
    out = copy.deepcopy(projections)
    _at(out, at)["layers"]["MARKET_FACTS"]["bar"].update(bar)
    return out


MUTATIONS = {
    # layer 1: settled facts and chronology
    "fact-not-sealed": (lambda p: _bar(p, "16:30:00", close=29600.0), "MARKET_FACTS", "FACT_NOT_SEALED"),
    "look-ahead-cutoff": (lambda p: _mutate(p, "16:30:00", "MARKET_FACTS", settled_cutoff="2026-08-19T16:31:00+00:00"),
                          "MARKET_FACTS", "FACT_AFTER_DECISION"),
    "forming-bar": (lambda p: _mutate(p, "16:30:00", "MARKET_FACTS", temporal_status="forming"), "MARKET_FACTS",
                    "FORMING_BAR_AS_FACT"),
    "replayed-future-evidence": (lambda p: _mutate(p, "16:30:00", "TIMING",
                                                   latest_available_at="2026-08-19T16:34:00+00:00"),
                                 "MARKET_FACTS", "FUTURE_EVIDENCE"),
    # layer 2: campaign direction / objective / origin, stale Draw, prefix eviction
    "campaign-direction": (lambda p: _mutate(p, "16:29:00", "CAMPAIGN", direction="bullish", brain_direction="bullish"),
                           "CAMPAIGN", "DIRECTION_bullish"),
    "campaign-objective": (lambda p: _mutate(p, "16:29:00", "CAMPAIGN",
                                             objective={"identity": "other", "kind": None, "price": None}),
                           "CAMPAIGN", "OBJECTIVE_MISMATCH"),
    "campaign-origin": (lambda p: _mutate(p, "16:29:00", "CAMPAIGN", origin={"event": "x", "at": ORIGIN["at"],
                                                                            "occurrence_id": "other"}),
                        "CAMPAIGN", "ORIGIN_MISMATCH"),
    "stale-draw": (lambda p: _mutate(p, "16:29:00", "CAMPAIGN", draw_history_revision=7), "CAMPAIGN", "STALE_DRAW"),
    "prefix-eviction": (lambda p: _mutate(p, "16:29:00", "CAMPAIGN", history_start="2026-08-19T15:00:00+00:00"),
                        "CAMPAIGN", "PREFIX_EVICTED"),
    # layer 3: false reversal against a retracement
    "false-reversal": (lambda p: _mutate(p, "16:33:00", "DELIVERY", projected_state="TRANSFER_CONFIRMED"),
                       "DELIVERY", "FALSE_REVERSAL"),
    # layer 4: exact occurrence and its ownership
    "tool-occurrence": (lambda p: _mutate(p, "16:30:00", "TOOL", occurrence_id="other-occurrence"), "TOOL",
                        "OCCURRENCE_ID_MISMATCH"),
    "tool-ownership": (lambda p: _mutate(p, "16:30:00", "TOOL", direction="bullish"), "TOOL",
                       "OCCURRENCE_OWNERSHIP_MISMATCH"),
    # layer 5: capture / trigger / final-quote composition
    "trigger-before-capture": (lambda p: _mutate(p, "16:32:30", "TIMING", trigger_at="2026-08-19T16:29:30+00:00"),
                               "COMPOSITION", "TRIGGER_BEFORE_CAPTURE"),
    "final-quote-outside-zone": (lambda p: _mutate(p, "16:32:30", "COMPOSITION", final_quote={
        "decision": "EXECUTE_AS_AUTHORIZED", "reference": 29519.0, "refusal_reason": None}),
        "COMPOSITION", "FINAL_QUOTE_OUTSIDE_ZONE"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_layer_mutation_is_detected_against_its_healthy_control(tmp_path_factory, name):
    world = _world(tmp_path_factory)
    mutate, layer, observed = MUTATIONS[name]
    control = _score(world["projections"], _label(), stream=world["stream"])[layer]
    assert (control["state"], control["agreement"]) == ("SCORED", True)
    mutated = mutate(world["projections"])
    cell = _score(mutated, _label(), stream=world["stream"])[layer]
    assert cell["observed"] == observed or cell["reason"] == observed, cell
    assert cell["agreement"] is not True
    if observed in LY.VIOLATIONS:
        # ... and the same mutation is an invariant violation at the scoring boundary.
        assert any(observed in LY.chronology(p, stream=world["stream"]) for p in mutated)


def test_missed_transfer_is_a_scored_disagreement_not_a_reversal_claim(tmp_path_factory):
    world = _world(tmp_path_factory)
    cell = _score(world["projections"], _label(delivery_state="TRANSFER_CONFIRMED"))["DELIVERY"]
    assert (cell["state"], cell["observed"], cell["agreement"]) == ("SCORED", "MISSED_TRANSFER", False)


@pytest.mark.parametrize("case", ["early", "late", "duplicate", "restart"])
def test_timing_mutations_are_detected(tmp_path_factory, case):
    world = _world(tmp_path_factory)
    projections = world["projections"]
    control = _score(projections, _label())["TIMING"]
    assert (control["observed"], control["agreement"]) == ("ON_TIME", True)
    if case == "early":
        # A matching judgment before the fact was knowable is never a hit.
        cell = _score(projections, _label(earliest_available_utc="2026-08-19T16:33:00Z"))["TIMING"]
        assert cell["observed"] == "EARLY_BEFORE_AVAILABILITY" and cell["agreement"] is False
    elif case == "late":
        label = _label(start="16:20", recognition_target={"start_utc": "2026-08-19T16:20:00Z",
                                                          "end_utc": "2026-08-19T16:21:00Z"})
        cell = _score(projections, label)["TIMING"]
        assert cell["observed"] == "LATE" and cell["agreement"] is False
    elif case == "duplicate":
        mutated = copy.deepcopy(projections)
        twin = copy.deepcopy(_at(mutated, "16:30:00"))
        twin["tick"]["ordinal"] += 1000
        mutated.insert(mutated.index(_at(mutated, "16:30:00")) + 1, twin)
        found = LY.sequence(mutated)["duplicate_cognition_cutoffs"]
        assert found == [{"settled_cutoff": "2026-08-19T16:30:00+00:00",
                          "ticks": [_at(mutated, "16:30:00")["tick"]["ordinal"], twin["tick"]["ordinal"]]}]
    else:
        mutated = copy.deepcopy(projections)
        for p in mutated:
            if p["tick"]["decision_time"] >= "2026-08-19T16:31":
                p["process_lineage_id"] = "process:restarted"
        cell = _score(mutated, _label())["TIMING"]
        assert (cell["state"], cell["reason"]) == ("UNPROVEN", "RESTART_IN_WINDOW")


# -- natural producer variants: revision, missed scans --------------------------------------

def test_provider_revision_is_projected_and_a_superseded_match_is_unproven(tmp_path_factory):
    world = _world(tmp_path_factory, "PROVIDER_REVISION")
    projections, stream = world["projections"], world["stream"]
    findings = LY.sequence(projections)
    assert [(r["from"], r["to"]) for r in findings["revisions"]] == [(0, 1)]
    revised = _at(projections, "16:32:30")["layers"]["MARKET_FACTS"]
    assert revised["release"]["version"] == 2 and revised["bar_open"] == "2026-08-19T16:31:00+00:00"
    assert all(LY.chronology(p, stream=stream) == [] for p in projections)   # facts track the sealed revision
    label = _label(recognition_target={"start_utc": "2026-08-19T16:29:00Z", "end_utc": "2026-08-19T16:33:00Z"})
    cell = _score(projections, label)["TIMING"]
    assert (cell["state"], cell["reason"]) == ("UNPROVEN", "MATCH_ON_SUPERSEDED_REVISION")
    healthy = _world(tmp_path_factory)
    assert _score(healthy["projections"], label)["TIMING"]["observed"] == "ON_TIME"   # control


def test_missed_scans_are_found_and_unproven_never_a_miss(tmp_path_factory):
    world = _world(tmp_path_factory)
    corpus = world["corpus_path"]
    ticks = [t for t in M3._ticks(corpus, "HEALTHY") if not ("16:24" <= t.decision_time.isoformat()[11:16] <= "16:27")]
    ticks = [DR.Tick(i, t.decision_time, t.kind) for i, t in enumerate(ticks)]
    out = tmp_path_factory.mktemp("m4-missed")
    summary = DR.run_offline(corpus_path=corpus, session_id=SESSION, out_root=out / "run", ecu=False,
                             trajectory_id="S5-M4-MISSED", ticks=ticks, quote_policy="CONSTRUCTED",
                             responder=M3.G.ScriptedResponder(M3._watching_script(1800), fixture_digest="m4"))
    evidence = Path(summary["evidence_root"])
    projections = SC.read_projections(evidence, REC.read_events(evidence))
    gaps = LY.sequence(projections)["missed_scans"]
    assert gaps == [{"after_cutoff": "2026-08-19T16:23:00+00:00", "catch_up_cutoff": "2026-08-19T16:28:00+00:00",
                     "missed_bars": 4}]
    label = _label("gap", "16:23", "16:28", recognition_target={"start_utc": "2026-08-19T16:24:00Z",
                                                               "end_utc": "2026-08-19T16:27:00Z"},
                   earliest_available_utc="2026-08-19T16:24:00Z")
    cell = _score(projections, label)["TIMING"]
    assert (cell["state"], cell["reason"]) == ("UNPROVEN", "MISSED_SCAN_CATCH_UP")
    assert _score(world["projections"], label)["TIMING"]["observed"] == "ON_TIME"   # control: every minute scanned


# -- mission 1 coverage rerun on complete and incomplete layer outputs -----------------------

def test_required_layer_rules_are_obligations_on_complete_and_incomplete_layer_outputs(tmp_path_factory):
    world = _world(tmp_path_factory)
    healthy = LY.score_label(_label(), world["projections"], LY.sequence(world["projections"]),
                             stream=world["stream"], stream_supplied=True)
    absent = LY.score_label(_label("quiet", "15:40", "15:50"), world["projections"], LY.sequence(world["projections"]))
    rules = [{"metric": LY.METRICS[layer], "operator": ">=", "value": 1, "decision_ref": f"FICTIONAL-UNIT-{layer}"}
             for layer in LY.LAYERS]
    plan = RC._plan(*rules)
    SC.check_rules(plan)

    def result(cells):
        counts = {m["name"]: (m["numerator"], m["denominator"]) for m in LY.metrics(cells, SC._metric)}
        return RC._result([RC._summary(counts, plan=plan)], scoring=plan, units=RC.UNIT)
    complete = result(healthy)
    assert complete["rule_coverage"]["status"] == "COMPLETE"
    assert {o["status"] for o in complete["rule_coverage"]["obligations"]} == {"PASS"}
    incomplete = result(absent)
    assert incomplete["rule_coverage"]["status"] == "INCOMPLETE"
    assert {(o["metric"], o["status"], o["reason"]) for o in incomplete["rule_coverage"]["obligations"]} == {
        (LY.METRICS[layer], "UNPROVEN", "ZERO_DENOMINATOR") for layer in LY.LAYERS}
    assert incomplete["current_brain_recognition"] == "UNPROVEN"
    failing = result([dict(c, agreement=False) if c["layer"] == "CAMPAIGN" else c for c in healthy])
    assert failing["rule_coverage"]["status"] == "FAIL"
    for doc in (complete, incomplete, failing):
        C.validate(json.loads(json.dumps(doc)))


def test_repeated_watching_trajectories_are_semantically_identical_with_projections(tmp_path_factory):
    """Tick traces and layer projections carry no process-random identity: repeats compare identical."""
    from recognition_validation import compare as CMP
    left = M3.run(tmp_path_factory, "HEALTHY", REFUSING, tag="repeat-left")
    right = M3.run(tmp_path_factory, "HEALTHY", REFUSING, tag="repeat-right")
    # The registry reads the decision clock: no wake carries the wall-clock date of the run.
    wakes = [w for _, trace in left["ticks"].values() for w in (trace.get("registry") or {}).get("new_wakes") or []]
    assert wakes and all(w["observed_at"].startswith("2026-08-19T") for w in wakes)
    verdict = CMP.compare_runs(left["evidence"], right["evidence"])
    assert verdict["identical"], verdict["first_divergence"]
    assert verdict["left"]["semantic_events_sha256"] == verdict["right"]["semantic_events_sha256"]
