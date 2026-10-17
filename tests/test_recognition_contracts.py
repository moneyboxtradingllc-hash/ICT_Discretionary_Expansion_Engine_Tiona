"""Stage 5 M02: strict contracts reject every malformed or laundered document by code."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recognition_validation import contracts as C  # noqa: E402

EXAMPLES = Path(C.__file__).resolve().parent / "examples"


def _load(name):
    return C.load_file(EXAMPLES / name)[0]


def _code(document, *, certification=False):
    with pytest.raises(C.ContractError) as exc:
        C.validate(document, certification=certification)
    return exc.value.code


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("*.json")))
def test_every_shipped_example_and_template_validates(name):
    doc, kind, digest = C.validate_file(EXAMPLES / name)
    assert kind == doc["schema_version"].split("/")[0] and len(digest) == 64


def test_examples_are_fictional_or_disabled_and_never_certify():
    annotation = _load("fictional_annotation.json")
    assert annotation["provenance"]["classification"] == "FICTIONAL"
    assert _code(annotation, certification=True) == "NONOWNER_ANNOTATION_NOT_CERTIFIABLE"
    assert _code(_load("fictional_scoring.json"), certification=True) == "THRESHOLDS_UNRATIFIED"
    assert _code(_load("current_brain_disabled.json"), certification=True) == "CURRENT_RECOGNITION_PREREQUISITES"


NEGATIVES = {
    "empty_window": ("fictional_annotation.json",
                     lambda d: d["labels"][0]["window"].update(end_utc=d["labels"][0]["window"]["start_utc"]),
                     "WINDOW_EMPTY_OR_REVERSED"),
    "timezone_missing": ("fictional_annotation.json", lambda d: d.update(created_at="2030-01-01T00:00:00"),
                         "TIMEZONE_REQUIRED"),
    "unowned_seal": ("fictional_annotation.json", lambda d: d.update(state="SEALED"),
                     "ANNOTATION_OWNER_SEAL_REQUIRED"),
    "duplicate_label": ("fictional_annotation.json", lambda d: d["labels"].append(copy.deepcopy(d["labels"][0])),
                        "DUPLICATE_LABEL"),
    "duplicate_session": ("fictional_corpus.json", lambda d: d["sessions"].append(copy.deepcopy(d["sessions"][0])),
                          "DUPLICATE_SESSION"),
    "path_traversal": ("fictional_corpus.json", lambda d: d["sessions"][0]["original"].update(path="../operator/.env"),
                       "UNSAFE_ARTIFACT_PATH"),
    "absolute_path": ("fictional_corpus.json", lambda d: d["sessions"][0]["original"].update(path="/etc/passwd"),
                      "UNSAFE_ARTIFACT_PATH"),
    "unratified_corpus": ("fictional_corpus.json", lambda d: d.update(selection_state="OWNER_RATIFIED"),
                          "CORPUS_RATIFICATION_REQUIRED"),
    "unauthorized_budget": ("current_brain_disabled.json", lambda d: d["budget"].update(max_external_requests=1),
                            "UNAUTHORIZED_REQUEST_BUDGET"),
    "fictional_external": ("current_brain_disabled.json", lambda d: d.update(model_calls_authorized=True),
                           "INVALID_EXTERNAL_PLAN"),
    "bool_not_coerced": ("current_brain_disabled.json", lambda d: d.update(ecu=1), "TYPE_BOOLEAN"),
    "mock_cognition_laundering": ("fictional_result.json", lambda d: d.update(current_brain_recognition="OWNER_ACCEPTED"),
                                  "MOCK_COGNITION_LAUNDERING"),
    "incomplete_ready_claim": ("fictional_result.json", lambda d: d.update(final_status="READY_FOR_OWNER_REVIEW"),
                               "INCOMPLETE_READY_CLAIM"),
    "mixed_contract": ("fictional_release.json", lambda d: d["bar"].update(contract="FOREIGN"), "CONTRACT_MISMATCH"),
    "bad_ohlc": ("fictional_release.json", lambda d: d["bar"].update(high=0), "INVALID_OHLC"),
    "forming_settlement_leak": ("fictional_release.json", lambda d: d.update(settled_at_utc="2030-01-02T14:00:01Z"),
                                "SETTLEMENT_OUTSIDE_VALID_INTERVAL"),
    "revision_order": ("fictional_release.json", lambda d: d.update(supersedes_version=d["version"]),
                       "INVALID_REVISION_ORDER"),
    "changed_event": ("fictional_event.json", lambda d: d.update(outcome="FALSE_PASS"), "EVENT_DIGEST_MISMATCH"),
    "disabled_authorization_budget": ("model_authorization_disabled.json",
                                      lambda d: d.update(max_external_requests=1), "DISABLED_AUTHORIZATION_HAS_BUDGET"),
    "duplicate_schedule_ordinal": ("fictional_schedule.json", lambda d: d["ticks"].append(copy.deepcopy(d["ticks"][0])),
                                   "DUPLICATE_SCHEDULE_ORDINAL"),
    "unknown_field": ("fictional_scoring.json", lambda d: d.update(extra=True), "UNKNOWN_FIELD"),
    "cache_discount": ("fictional_pricing.json", lambda d: d.update(cache_discount_assumed=True), "CONST"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVES))
def test_negative_documents_refuse_with_their_exact_code(case):
    name, mutate, code = NEGATIVES[case]
    doc = _load(name)
    C.validate(doc)                       # healthy twin
    mutate(doc)
    assert _code(doc) == code


def _sealed_chain():
    corpus, annotation, scoring = (_load("fictional_corpus.json"), _load("fictional_annotation.json"),
                                   _load("fictional_scoring.json"))
    run = _load("current_brain_disabled.json")
    corpus["seal"] = {"sha256": C.seal_digest(corpus), "sealed_at": "2030-01-01T00:00:00Z", "sealer_ref": "TEST"}
    annotation["corpus_digest"] = C.seal_digest(corpus)
    annotation["seal"] = {"sha256": C.seal_digest(annotation), "sealed_at": "2030-01-01T00:00:01Z",
                          "sealer_ref": "TEST"}
    scoring["corpus_digest"] = C.seal_digest(corpus)
    scoring["annotation_digests"] = [C.seal_digest(annotation)]
    run.update(corpus_digest=C.seal_digest(corpus), annotation_digest=C.seal_digest(annotation),
               scoring_plan_digest=C.seal_digest(scoring))
    return corpus, annotation, scoring, run


def test_sealed_documents_bind_acyclically_and_detect_tamper():
    corpus, annotation, scoring, run = _sealed_chain()
    for doc in (corpus, annotation, scoring, run):
        C.validate(doc)
    C.cross(corpus, annotation, scoring, run)
    tampered = copy.deepcopy(annotation)
    tampered["labels"][0]["notes"] = "changed after seal"
    assert _code(tampered) == "SEAL_MISMATCH"
    moved = copy.deepcopy(corpus)
    moved["sessions"][0]["contract_id"] = "CHANGED"
    assert _code(moved) == "SEAL_MISMATCH"
    with pytest.raises(C.ContractError) as exc:
        C.cross(corpus, {**annotation, "corpus_digest": "f" * 64}, scoring, run)
    assert exc.value.code == "ANNOTATION_CORPUS_MISMATCH"
    with pytest.raises(C.ContractError) as exc:
        C.cross(corpus, annotation, scoring, {**run, "scoring_plan_digest": "e" * 64})
    assert exc.value.code == "RUN_SCORING_MISMATCH"


@pytest.mark.parametrize("text,code", [('{"x":1,"x":2}', "DUPLICATE_KEY"), ('{"x":NaN}', "NONFINITE_JSON"),
                                       ('{"x":Infinity}', "NONFINITE_JSON"), ('{"x":', "INVALID_JSON")])
def test_strict_json_and_file_digest_on_failure(tmp_path, text, code):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(C.ContractError) as exc:
        C.validate_file(path)
    assert exc.value.code == code
    assert exc.value.file_digest == C.sha256_hex(path.read_bytes())


def test_validation_failure_reports_pointer_and_original_file_digest(tmp_path):
    doc = _load("fictional_release.json")
    doc["bar"]["high"] = 0
    path = tmp_path / "release.json"
    path.write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(C.ContractError) as exc:
        C.validate_file(path)
    assert (exc.value.code, exc.value.pointer) == ("INVALID_OHLC", "/bar")
    assert exc.value.file_digest == C.sha256_hex(path.read_bytes())


def test_unknown_schema_keyword_and_unknown_kind_refuse(monkeypatch):
    with pytest.raises(C.ContractError) as exc:
        C._structural({}, {"type": "object", "if": {}}, "")
    assert exc.value.code == "UNSUPPORTED_SCHEMA_KEYWORD"
    assert _code({"schema_version": "nonexistent/v1"}) == "UNKNOWN_SCHEMA"


def test_event_chain_requires_order_and_predecessor_digest():
    first = _load("fictional_event.json")
    first.update(sequence=0, previous_event_digest=None)
    first["event_payload_digest"] = C.event_digest(first)
    second = copy.deepcopy(first)
    second.update(sequence=1, previous_event_digest=C.event_digest(first), document_id="second")
    second["event_payload_digest"] = C.event_digest(second)
    assert C.verify_event_chain([first, second]) == C.event_digest(second)
    broken = copy.deepcopy(second)
    broken["previous_event_digest"] = "0" * 64
    broken["event_payload_digest"] = C.event_digest(broken)
    with pytest.raises(C.ContractError) as exc:
        C.verify_event_chain([first, broken])
    assert exc.value.code == "EVENT_CHAIN_BROKEN"
    with pytest.raises(C.ContractError) as exc:
        C.verify_event_chain([second])
    assert exc.value.code == "EVENT_SEQUENCE_GAP"
