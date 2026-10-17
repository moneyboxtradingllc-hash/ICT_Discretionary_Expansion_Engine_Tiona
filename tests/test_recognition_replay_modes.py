"""Stage 5 M04: Mode B determinism and Mode A exact historical association.

Mode B runs the CONSTRUCTED distinct-anchor session twice from fresh roots;
the semantic-v1 traces are identical while raw traces keep their own
process lineage. Mode A replays "historical" records harvested from the
first B run's raw responses: exact association reproduces the trace, and
every attack (missing record, duplicate or foreign association, reuse,
changed input, different served model) is reported honestly instead of
substituting a neighbour.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_recognition_current_path as CP  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import compare as CMP  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402

SESSION, CONTRACT = CP.SESSION, CP.CONTRACT
PREWARM = "2026-08-19T15:30:00Z"


@pytest.fixture(scope="module")
def corpus_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus")
    return K.build_constructed_corpus(root, session_id=SESSION, contract_id=CONTRACT, market_date="2026-08-19",
                                      tape=W._tape(W._HEALTHY), warmup_end="2026-08-19T15:30:00+00:00",
                                      notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                      sealed_at="2026-10-17T00:00:00Z")


def _mode_b(corpus_path, root, *, ecu=False, ticks_until=None):
    script, _ = CP._script()
    return DR.run_offline(corpus_path=corpus_path, session_id=SESSION, out_root=root, ecu=ecu,
                          trajectory_id="S5-TRAJ", prewarm_until=PREWARM, ticks_until=ticks_until,
                          responder=G.ScriptedResponder(script, fixture_digest=C.digest("daw-script-v1")))


def _records(summary):
    return [{"settled_cutoff": r["settled_cutoff"], "cutoff_ordinal": r["cutoff_ordinal"], "purpose": r["purpose"],
             "contract_id": CONTRACT, "raw_response": r["reply"]["content"],
             "served_model": r["reply"]["served_model"], "input_digest": r["input_digest"],
             "input_text": r["user_contents"][0], "semantic_input_digest": r["semantic_input_digest"],
             "brain_fingerprint": None, "provider_request_id": None, "provider_response_id": None}
            for r in summary["requests"] if r.get("reply")]


def _mode_a(corpus_path, root, records, *, ticks_until=None):
    return DR.run_offline(corpus_path=corpus_path, session_id=SESSION, out_root=root, ecu=False,
                          trajectory_id="S5-TRAJ", prewarm_until=PREWARM, ticks_until=ticks_until,
                          responder=G.HistoricalResponder(records, contract_id=CONTRACT))


@pytest.fixture(scope="module")
def b_runs(corpus_path, tmp_path_factory):
    root = tmp_path_factory.mktemp("b")
    return _mode_b(corpus_path, root / "B1"), _mode_b(corpus_path, root / "B2")


def test_mode_b_repeats_are_semantically_identical_from_fresh_roots(b_runs):
    first, second = b_runs
    report = CMP.compare_runs(first["evidence_root"], second["evidence_root"])
    assert report["identical"], report["first_divergence"]
    assert report["left"]["semantic_events_sha256"] == report["right"]["semantic_events_sha256"]
    assert report["left"]["semantic_calls_sha256"] == report["right"]["semantic_calls_sha256"]
    events = REC.read_events(first["evidence_root"])
    assert any(e["tool_occurrence_id"] == W.FORMATION_ID for e in events)
    assert all(c["evaluation_origin"] == "MOCK" for c in REC.read_calls(first["evidence_root"]))
    # Raw traces keep their own process identities; only the projection agrees.
    assert report["left"]["raw_calls_sha256"] != report["right"]["raw_calls_sha256"]


def test_provider_call_stamps_come_from_the_decision_clock_not_the_wall(b_runs):
    """T32 seam: production's wall-clock stamp re-enters the next Brain input."""
    stamps = [json.loads(r["user_contents"][0]).get("campaign_draw_context", {}).get("brain_lineage", {})
              .get("provider_call_completed_at") for r in b_runs[0]["requests"]]
    stamps = [s for s in stamps if s]
    assert stamps and all(s.startswith("2026-08-19T") for s in stamps)
    previous = {r["settled_cutoff"]: r["decision_time"] for r in b_runs[0]["requests"]}
    assert all(C.instant(s) <= C.instant(max(previous.values())) for s in stamps)


def test_semantic_projection_never_hides_identity_or_outcome_changes(b_runs):
    """T30: over-normalization mutant control."""
    events = REC.read_events(b_runs[0]["evidence_root"])
    changed = copy.deepcopy(events)
    hit = next(i for i, e in enumerate(changed) if e["tool_occurrence_id"])
    changed[hit]["tool_occurrence_id"] = changed[hit]["tool_occurrence_id"].replace("29518.5", "29519")
    assert CMP.first_divergence(CMP.project_events(events), CMP.project_events(changed))["fields"] == [
        "tool_occurrence_id"]
    outcome = copy.deepcopy(events)
    outcome[hit]["outcome"] = "NO_CANDIDATE"
    assert CMP.first_divergence(CMP.project_events(events), CMP.project_events(outcome))["index"] == hit
    # Bijective renaming keeps equality structure: two distinct lineages stay distinct.
    split = copy.deepcopy(events)
    split[-1]["process_lineage_id"] = "process:other"
    assert CMP.first_divergence(CMP.project_events(events), CMP.project_events(split)) is not None
    # Brain inputs: process-random ids are renamed, a market fact never is.
    text = b_runs[0]["requests"][-1]["user_contents"][0]
    document = json.loads(text)
    rows = document["campaign_premise_catalog"]["rows"]
    assert rows and CMP.rebinding(text, text) is not None
    moved = copy.deepcopy(document)
    moved["campaign_premise_catalog"]["rows"][0]["life"]["level"] += 0.25
    assert CMP.semantic_input_digest(json.dumps(moved)) != CMP.semantic_input_digest(text)
    assert CMP.rebinding(text, json.dumps(moved)) is None
    relabelled = json.loads(text.replace(rows[0]["premise_candidate_id"], "pc:000000000000000000000000"))
    assert CMP.semantic_input_digest(json.dumps(relabelled)) == CMP.semantic_input_digest(text)
    assert "proof_id" not in CMP.INPUT_TOKEN_KEYS and "canonical_sweep_id" not in CMP.INPUT_TOKEN_KEYS
    # An over-normalizing projection that also renamed formation identities
    # would hide the first change -- which is why ALPHA_FIELDS excludes it.
    assert "tool_occurrence_id" not in CMP.ALPHA_FIELDS and "formation_id" not in CMP.ALPHA_FIELDS


def test_mode_a_exact_association_reproduces_the_trace(corpus_path, b_runs, tmp_path):
    first = b_runs[0]
    replay = _mode_a(corpus_path, tmp_path / "A", _records(first))
    report = CMP.compare_runs(first["evidence_root"], replay["evidence_root"])
    assert report["left"]["semantic_events_sha256"] == report["right"]["semantic_events_sha256"]
    calls = REC.read_calls(replay["evidence_root"])
    assert calls and all(c["evaluation_origin"] == "HISTORICAL" for c in calls)
    assert all("HISTORICAL_OUTPUT_ON_CURRENT_INPUTS" not in c["provenance"]["notes"] for c in calls)
    # Archived outputs cite the archive process's premise ids; exact semantic
    # alignment of the archived input is what licenses the disclosed rebinding.
    assert all("HISTORICAL_INPUT_SEMANTIC_V1_MATCH" in c["provenance"]["notes"] for c in calls)
    rebound = [r["historical"]["rebound_identities"] for r in replay["requests"] if r.get("historical")]
    assert any(rebound)
    events = REC.read_events(replay["evidence_root"])
    assert any(e["tool_occurrence_id"] == W.FORMATION_ID for e in events)
    assert all(c["historical_brain_fingerprint"] is None and c["historical_unknown_reason"] for c in calls)


def _first_window_record(records):
    return next(i for i, r in enumerate(records) if r["settled_cutoff"][11:16] == W.WINDOW[0])


def test_mode_a_missing_record_is_missing_cognition_never_a_neighbour(corpus_path, b_runs, tmp_path):
    records = _records(b_runs[0])
    missing = records[_first_window_record(records)]
    records.remove(missing)
    replay = _mode_a(corpus_path, tmp_path / "A", records, ticks_until="2026-08-19T16:41:00Z")
    calls = REC.read_calls(replay["evidence_root"])
    gap = [c for c in calls if c["settled_cutoff"] == missing["settled_cutoff"]]
    assert gap and all(c["evaluation_origin"] == "MISSING" and c["fallback_reason"] for c in gap)
    events = {e["settled_cutoff"]: e for e in REC.read_events(replay["evidence_root"])}
    assert events[missing["settled_cutoff"]]["outcome"] != "QUALIFIED_CANDIDATE_OBSERVED"
    # Every other window record was consumed by its own scan only.
    later = [c for c in calls if c["settled_cutoff"] > missing["settled_cutoff"]]
    assert later and all(c["evaluation_origin"] == "HISTORICAL" for c in later)


@pytest.mark.parametrize("attack,code", [("duplicate", "HISTORICAL_DUPLICATE_ASSOCIATION"),
                                         ("foreign", "HISTORICAL_FOREIGN_CONTRACT")])
def test_mode_a_ambiguous_or_foreign_records_refuse_at_load(b_runs, attack, code):
    records = _records(b_runs[0])
    if attack == "duplicate":
        records.append(dict(records[-1]))
    else:
        records[3]["contract_id"] = "CON.F.US.MNQ.H27"
    with pytest.raises(C.ContractError) as exc:
        G.HistoricalResponder(records, contract_id=CONTRACT)
    assert exc.value.code == code


def test_mode_a_record_is_consumed_once_and_never_reused():
    record = {"settled_cutoff": "2026-08-19T16:38:00+00:00", "cutoff_ordinal": 0, "purpose": "PRIMARY",
              "contract_id": CONTRACT, "raw_response": "{}", "served_model": "gpt-6-luna", "input_digest": "x"}
    responder = G.HistoricalResponder([record], contract_id=CONTRACT)
    request = {"settled_cutoff": record["settled_cutoff"], "cutoff_ordinal": 0, "purpose": "PRIMARY",
               "input_digest": "x"}
    responder.respond(dict(request))
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond(dict(request))
    assert exc.value.code == "HISTORICAL_RECORD_ALREADY_CONSUMED"
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond({**request, "cutoff_ordinal": 1})
    assert exc.value.code == "MISSING_COGNITION"


def test_mode_a_changed_input_and_other_served_model_are_disclosed(corpus_path, b_runs, tmp_path):
    records = _records(b_runs[0])
    index = _first_window_record(records)
    tampered = json.loads(records[index]["input_text"])
    tampered["archive_tampered"] = True
    records[index].update(input_digest="0" * 64, semantic_input_digest="0" * 64, input_text=json.dumps(tampered))
    records[index + 1]["served_model"] = "gpt-4o-2024-08-06"
    replay = _mode_a(corpus_path, tmp_path / "A", records, ticks_until="2026-08-19T16:42:00Z")
    calls = {c["settled_cutoff"]: c for c in REC.read_calls(replay["evidence_root"]) if c["purpose"] == "PRIMARY"}
    changed = calls[records[index]["settled_cutoff"]]
    assert "HISTORICAL_OUTPUT_ON_CURRENT_INPUTS" in changed["provenance"]["notes"]
    other = calls[records[index + 1]["settled_cutoff"]]
    # Production's own served-model check refuses the foreign author.
    assert other["served_model"] is None and other["fallback_reason"].startswith("provider_model_mismatch")
    assert other["record_status"] != "COMPLETE"
