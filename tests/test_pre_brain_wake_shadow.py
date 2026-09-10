"""Synthetic experiment tests, never evidence of historical trade recall."""
import ast
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import pre_brain_wake_shadow as W


def observation(sequence=1):
    snapshot = {key: {"state": "stable"}
                for keys in W.SNAPSHOT_GROUPS.values() for key in keys}
    snapshot.update({
        "contract_id": "CON.TEST",
        "session": "new_york",
        "session_po3": {"phase": "EXCURSION_UNRESOLVED"},
        "structure_flips": [],
        "candle_continuity": {"continuous": True},
        "derived_state": {"current": True, "history_revision": 1, "derived_revision": 1},
        "execution_price": {"available": True, "fresh": True, "best_bid": 100, "best_ask": 100.25},
    })
    return {"session_id": "SYNTHETIC", "contract_id": "CON.TEST",
            "scan_id": f"scan-{sequence}", "sequence": sequence,
            "observed_at": f"2026-09-10T14:{sequence:02d}:00+00:00",
            "capture_stage": "pre_provider_after_catalogs", "pipeline_mode": "non_ecu",
            "snapshot": snapshot, "brain_input": {key: [] for key in W.CATALOGS}}


def bundle(count=3):
    return {"schema": W.BUNDLE_SCHEMA, "session_id": "SYNTHETIC",
            "evidence_kind": "synthetic", "expected_scan_count": count,
            "label_coverage": "complete", "trade_label_coverage": "complete",
            "candidate_labels": [], "observations": [observation(i + 1) for i in range(count)]}


def label(sequence, trade=None):
    return {"session_id": "SYNTHETIC", "contract_id": "CON.TEST",
            "scan_id": f"scan-{sequence}", "trade_id": trade}


def test_unchanged_unresolved_state_bootstraps_then_only_hypothetically_holds():
    data = bundle()
    before = copy.deepcopy(data)
    report = W.evaluate(data)
    assert [row["decision"] for row in report["decisions"]] == ["WAKE_SHADOW", "HOLD_SHADOW", "HOLD_SHADOW"]
    assert report["status"] == "SYNTHETIC_ONLY"
    assert report["candidate_scan_recall_proxy"] is None
    assert report["observed_candidate_gate"] == "NOT_TESTED_NO_POSITIVE_LABELS"
    assert report["model_calls_saved"] is None and report["cost_saved"] is None
    assert report["production_authorized"] is False
    assert data == before


@pytest.mark.parametrize("group", list(W.SNAPSHOT_GROUPS))
def test_any_evidence_family_change_wakes_without_a_bound_trade(group):
    first, second = observation(), observation(2)
    key = W.SNAPSHOT_GROUPS[group][0]
    if isinstance(second["snapshot"][key], dict):
        second["snapshot"][key]["new_occurrence"] = "event-2"
    else:
        second["snapshot"][key] = "new_phase"
    detector = W.ShadowDetector()
    detector.observe(first)
    result = detector.observe(second)
    assert result["decision"] == "WAKE_SHADOW"
    assert f"changed:{group}" in result["reasons"]


@pytest.mark.parametrize("catalog", W.CATALOGS)
def test_forming_tool_objective_or_invalidation_wakes(catalog):
    detector = W.ShadowDetector()
    detector.observe(observation())
    row = observation(2)
    row["brain_input"][catalog] = [{"occurrence_id": "new", "state": "forming"}]
    assert detector.observe(row)["decision"] == "WAKE_SHADOW"


@pytest.mark.parametrize("failure", ["ecu", "post_call", "missing", "null", "stale_quote",
                                    "gap", "stale_derived", "nan", "bad_time", "bad_identity"])
def test_uncertain_evidence_never_supports_suppression(failure):
    detector = W.ShadowDetector()
    detector.observe(observation())
    row = observation(2)
    if failure == "ecu":
        row["pipeline_mode"] = "ecu"
    elif failure == "post_call":
        row["snapshot"]["ai_brain"] = {"output": {}}
    elif failure == "missing":
        del row["snapshot"]["liquidity"]
    elif failure == "null":
        row["brain_input"]["authorized_objectives"] = None
    elif failure == "stale_quote":
        row["snapshot"]["execution_price"]["fresh"] = False
    elif failure == "gap":
        row["snapshot"]["candle_continuity"]["continuous"] = False
    elif failure == "stale_derived":
        row["snapshot"]["derived_state"]["current"] = False
    elif failure == "nan":
        row["snapshot"]["execution_price"]["best_bid"] = float("nan")
    elif failure == "bad_time":
        row["observed_at"] = "2026-09-10T14:02:00"
    else:
        row["contract_id"] = []
    result = detector.observe(row)
    assert result["decision"] == "PRESERVE_BASELINE" and result["issues"]
    assert detector.observe(observation(3))["decision"] == "WAKE_SHADOW"


@pytest.mark.parametrize("failure", ["duplicate", "out_of_order", "gap", "time_reversal"])
def test_sequence_and_identity_are_not_repaired_by_sorting(failure):
    detector = W.ShadowDetector()
    detector.observe(observation())
    row = observation(2)
    if failure == "duplicate":
        row["scan_id"] = "scan-1"
    elif failure == "out_of_order":
        row["sequence"] = 1
    elif failure == "gap":
        row["sequence"] = 3
    else:
        row["observed_at"] = "2026-09-10T14:00:00+00:00"
    assert detector.observe(row)["decision"] == "PRESERVE_BASELINE"


@pytest.mark.parametrize("identity", ["session_id", "contract_id"])
def test_restart_session_or_contract_change_bootstraps(identity):
    detector = W.ShadowDetector()
    detector.observe(observation())
    row = observation(2)
    row[identity] = "NEW"
    if identity == "contract_id":
        row["snapshot"][identity] = "NEW"
    assert detector.observe(row)["decision"] == "WAKE_SHADOW"
    assert W.ShadowDetector().observe(observation(2))["decision"] == "WAKE_SHADOW"


def test_future_candidate_and_trade_labels_cannot_choose_wakes():
    data = bundle()
    before = W.evaluate(data)
    data["candidate_labels"] = [label(2, "T2")]
    after = W.evaluate(data)
    assert after["decisions"] == before["decisions"]
    assert after["candidate_scan_recall_proxy"] == 0
    assert after["trade_recall_proxy"] == 0
    assert after["observed_candidate_gate"] == "REJECTED_OBSERVED_MISS"
    assert after["missed_candidate_scans"][0]["trade_id"] == "T2"
    # A preceding wake gets no unproven credit for a later held opportunity.
    assert after["decisions"][0]["decision"] == "WAKE_SHADOW"


def test_exact_same_scan_recall_is_only_a_proxy_even_when_every_label_is_captured():
    data = bundle()
    data["observations"][1]["snapshot"]["structure_flips"] = [{"id": "new-flip"}]
    data["candidate_labels"] = [label(1, "T1"), label(2, "T2")]
    result = W.evaluate(data)
    assert result["candidate_scan_recall_proxy"] == 1
    assert result["trade_recall_proxy"] == 1
    assert result["production_authorized"] is False
    assert result["provenance_independently_verified"] is False


@pytest.mark.parametrize("issue", ["count", "missing_label_coverage", "unmatched",
                                  "duplicate_label", "wrong_contract", "wrong_session"])
def test_incomplete_coverage_or_join_never_claims_recall(issue):
    data = bundle()
    data["candidate_labels"] = [label(1, "T1")]
    if issue == "count":
        data["expected_scan_count"] = 4
    elif issue == "missing_label_coverage":
        del data["label_coverage"]
    elif issue == "unmatched":
        data["candidate_labels"] = [label(9, "T1")]
    elif issue == "duplicate_label":
        data["candidate_labels"] *= 2
    elif issue == "wrong_contract":
        data["candidate_labels"][0]["contract_id"] = "OTHER"
    else:
        data["observations"][1]["session_id"] = "OTHER"
    result = W.evaluate(data)
    assert result["candidate_scan_recall_proxy"] is None
    assert result["hold_fraction"] is None
    assert result["observed_candidate_gate"] == "UNPROVEN"


def test_absent_session_evidence_stays_unknown(tmp_path, capsys):
    assert W.main(["--session", "PROD-20260910", "--bundle", str(tmp_path / "absent.json")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "MISSING_EVIDENCE"
    assert result["observations"] is None and result["hold_fraction"] is None
    assert result["candidate_scan_recall_proxy"] is None and result["model_calls_saved"] is None


def test_cli_only_reads_bundle_and_prints_report(tmp_path, capsys):
    path = tmp_path / "synthetic.json"
    original = json.dumps(bundle()).encode()
    path.write_bytes(original)
    assert W.main(["--session", "SYNTHETIC", "--bundle", str(path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "SYNTHETIC_ONLY"
    assert result["observed_candidate_gate"] == "NOT_TESTED_NO_POSITIVE_LABELS"
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_cli_rejects_an_observed_candidate_miss(tmp_path, capsys):
    path = tmp_path / "miss.json"
    data = bundle()
    data["candidate_labels"] = [label(2, "T2")]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert W.main(["--session", "SYNTHETIC", "--bundle", str(path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["observed_candidate_gate"] == "REJECTED_OBSERVED_MISS"


def test_no_production_import_or_model_broker_dependency():
    source = Path(W.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert roots <= {"__future__", "argparse", "hashlib", "json", "datetime", "pathlib"}
    for path in (ROOT / "src").rglob("*.py"):
        assert "pre_brain_wake_shadow" not in path.read_text(encoding="utf-8")
