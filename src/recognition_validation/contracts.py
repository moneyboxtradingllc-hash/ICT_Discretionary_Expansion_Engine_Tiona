"""Strict versioned contracts: parsing, canonical digests, seals, validation.

Every document is UTF-8 strict JSON: no duplicate keys, no NaN/Infinity, no
implicit timezone, no coerced booleans or numbers. JSON Schema (Draft 2020-12
subset, unknown keywords refused) is the machine interface; the semantic
laws below add temporal, hash, seal and cross-document bindings the schema
cannot express. A failure raises ContractError with a stable code, a JSON
pointer and, when the document came from a file, that file's SHA-256.

Canonical object bytes (seals, digests): json.dumps(sort_keys=True,
separators=(",", ":"), ensure_ascii=True, allow_nan=False) as UTF-8. File
artifact hashes bind ORIGINAL FILE BYTES. Schema acceptance never proves
market truth.
"""
from __future__ import annotations

import hashlib
import json
import re
import ast
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_KNOWN_KEYWORDS = {"$schema", "$id", "type", "additionalProperties", "properties", "required",
                   "items", "minItems", "minLength", "minimum", "pattern", "format", "enum",
                   "const", "anyOf"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def source_identity(repo_root=None) -> dict:
    """Observe the loaded checkout and canonical closure; never trust run-file labels."""
    root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    def git(*args):
        result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *args],
                                capture_output=True)
        require(result.returncode == 0, "SOURCE_IDENTITY_UNAVAILABLE", "/source_sha")
        return result.stdout
    require(not git("ls-files", "--others", "--exclude-standard", "--", "src", "tools").strip(),
            "UNTRACKED_RUNTIME_SOURCE", "/source_sha")
    model_path = root / "src/ai_brain/production_model.py"
    constants = {}
    for node in ast.parse(model_path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("_CONTRACT_SOURCES", "_CONTRACT_SOURCES_REPO"):
                constants[name] = ast.literal_eval(node.value)
    require(len(constants) == 2, "SOURCE_CLOSURE_UNAVAILABLE", "/closure_digest")
    paths = [(label, "src/" + path) for label, path in constants["_CONTRACT_SOURCES"]]
    paths += list(constants["_CONTRACT_SOURCES_REPO"])
    closure = [[label, path, sha256_hex((root/path).read_bytes().replace(b"\r\n", b"\n"))]
               for label, path in paths]
    pins = loads_strict((root/"docs/recognition_validation/baseline/SOURCE_PINS.json").read_text())
    for path, expected in pins["protected_sources"].items():
        require(sha256_hex((root/path).read_bytes().replace(b"\r\n", b"\n")) == expected,
                "PROTECTED_SOURCE_ALTERED", "/" + path)
    from ai_brain.production_model import brain_contract_fingerprint
    from ai_retrieval.retrieval_contract import retrieval_contract_fingerprint
    diff = git("diff", "--binary", "HEAD")
    return {"source_sha": git("rev-parse", "HEAD").decode().strip(),
            "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "dirty_tree_digest": sha256_hex(diff) if diff else None,
            "brain_fingerprint": brain_contract_fingerprint(),
            "retrieval_fingerprint": retrieval_contract_fingerprint(),
            "closure_digest": digest(closure)}


def verify_run_source(run: dict) -> dict:
    observed = source_identity()
    for key, value in observed.items():
        require(run[key] == value, "RUN_SOURCE_MISMATCH", "/" + key,
                f"declared {run[key]!r}; observed {value!r}")
    return observed


class ContractError(ValueError):
    """A contract violation with a stable code and location."""

    def __init__(self, code: str, pointer: str = "", *, file_digest: str | None = None,
                 detail: str = ""):
        self.code = code
        self.pointer = pointer or "/"
        self.file_digest = file_digest
        self.detail = detail
        text = f"{code} at {self.pointer}"
        if detail:
            text += f": {detail}"
        if file_digest:
            text += f" [file sha256 {file_digest}]"
        super().__init__(text)


def require(ok: bool, code: str, pointer: str = "", detail: str = "") -> None:
    if not ok:
        raise ContractError(code, pointer, detail=detail)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    return sha256_hex(canonical(value))


def seal_digest(document: dict) -> str:
    """Digest of the whole document except its `seal` property."""
    return digest({k: v for k, v in document.items() if k != "seal"})


def loads_strict(text: str, *, pointer: str = "") -> object:
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ContractError("DUPLICATE_KEY", pointer or "/", detail=key)
            out[key] = value
        return out

    def constant(name):
        raise ContractError("NONFINITE_JSON", pointer or "/", detail=name)
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_JSON", pointer or "/", detail=str(exc)) from exc


def load_file(path) -> tuple[object, str]:
    """Return (document, sha256 of the original file bytes)."""
    data = Path(path).read_bytes()
    file_digest = sha256_hex(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("NOT_UTF8", "/", file_digest=file_digest) from exc
    try:
        return loads_strict(text), file_digest
    except ContractError as exc:
        raise ContractError(exc.code, exc.pointer, file_digest=file_digest, detail=exc.detail) from exc


def instant(value, pointer: str = "") -> datetime:
    """An aware instant, canonicalized to UTC. Naive or malformed refuses."""
    require(type(value) is str, "TIME_NOT_STRING", pointer)
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("TIME_INVALID", pointer, detail=str(value)) from exc
    require(moment.tzinfo is not None and moment.utcoffset() is not None, "TIMEZONE_REQUIRED", pointer)
    return moment.astimezone(timezone.utc)


_SCHEMAS: dict[str, dict] = {}


def schema_for(kind: str) -> dict:
    if kind not in _SCHEMAS:
        path = SCHEMA_DIR / f"{kind}.schema.json"
        require(path.is_file(), "UNKNOWN_SCHEMA", "/schema_version", kind)
        _SCHEMAS[kind], _ = load_file(path)
    return _SCHEMAS[kind]


def _structural(value, schema: dict, pointer: str) -> None:
    require(not (set(schema) - _KNOWN_KEYWORDS), "UNSUPPORTED_SCHEMA_KEYWORD", pointer)
    if "anyOf" in schema:
        errors = []
        for choice in schema["anyOf"]:
            try:
                _structural(value, choice, pointer)
                return
            except ContractError as exc:
                errors.append(exc.code)
        raise ContractError("ANYOF_FAILED", pointer, detail=",".join(errors))
    if "const" in schema:
        require(type(value) is type(schema["const"]) and value == schema["const"], "CONST", pointer)
    if "enum" in schema:
        require(any(type(value) is type(x) and value == x for x in schema["enum"]), "ENUM", pointer)
    kind = schema.get("type")
    checks = {"object": type(value) is dict, "array": type(value) is list, "string": type(value) is str,
              "integer": type(value) is int, "number": type(value) in (int, float),
              "boolean": type(value) is bool, "null": value is None}
    if kind:
        require(checks[kind], "TYPE_" + kind.upper(), pointer)
    if kind == "object":
        missing = sorted(set(schema.get("required", [])) - set(value))
        require(not missing, "REQUIRED", pointer, ",".join(missing))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            require(not extra, "UNKNOWN_FIELD", pointer, ",".join(extra))
        for key, item in value.items():
            if key in props:
                _structural(item, props[key], f"{pointer}/{key}")
    elif kind == "array":
        require(len(value) >= schema.get("minItems", 0), "MIN_ITEMS", pointer)
        for index, item in enumerate(value):
            _structural(item, schema["items"], f"{pointer}/{index}")
    elif kind == "string":
        require(len(value) >= schema.get("minLength", 0), "MIN_LENGTH", pointer)
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, "PATTERN", pointer)
        if schema.get("format") == "date-time":
            instant(value, pointer)
    if kind in ("integer", "number") and "minimum" in schema:
        require(value >= schema["minimum"], "MINIMUM", pointer)


def safe_relative_path(path: str, pointer: str = "") -> PurePosixPath:
    """A content reference stays inside its root: relative, no traversal."""
    require(isinstance(path, str) and path, "UNSAFE_ARTIFACT_PATH", pointer)
    require("\\" not in path and ":" not in path and "\x00" not in path, "UNSAFE_ARTIFACT_PATH", pointer)
    pure = PurePosixPath(path)
    require(not pure.is_absolute() and ".." not in pure.parts, "UNSAFE_ARTIFACT_PATH", pointer)
    return pure


def _walk(value, pointer: str, visit) -> None:
    visit(value, pointer)
    if isinstance(value, dict):
        for key, item in value.items():
            _walk(item, f"{pointer}/{key}", visit)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{pointer}/{index}", visit)


def _decimal(value, pointer):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ContractError("DECIMAL_INVALID", pointer, detail=str(value)) from exc
    require(number.is_finite(), "DECIMAL_INVALID", pointer)
    return number


def _semantics(doc: dict, certification: bool) -> None:
    kind = doc["schema_version"].split("/")[0]

    def visit(value, pointer):
        if isinstance(value, dict):
            if set(value) == {"start_utc", "end_utc"}:
                require(instant(value["start_utc"], pointer) < instant(value["end_utc"], pointer),
                        "WINDOW_EMPTY_OR_REVERSED", pointer)
            if {"path", "sha256", "bytes", "origin"} <= set(value):
                safe_relative_path(value["path"], pointer + "/path")
    _walk(doc, "", visit)
    if doc.get("seal"):
        require(doc["seal"]["sha256"] == seal_digest(doc), "SEAL_MISMATCH", "/seal/sha256")
    getattr(_Semantics, kind, lambda d, c: None)(doc, certification)


class _Semantics:
    @staticmethod
    def corpus(doc, certification):
        ids = [s["session_id"] for s in doc["sessions"]]
        require(len(ids) == len(set(ids)), "DUPLICATE_SESSION", "/sessions")
        if doc["selection_state"] == "OWNER_RATIFIED":
            require(bool(doc["owner_decision_ref"]) and bool(doc["seal"]), "CORPUS_RATIFICATION_REQUIRED",
                    "/selection_state")
        for index, s in enumerate(doc["sessions"]):
            at = f"/sessions/{index}"
            try:
                ZoneInfo(s["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ContractError("TIMEZONE_UNKNOWN", at + "/timezone") from exc
            require(instant(s["warmup_window"]["end_utc"]) <= instant(s["scored_window"]["start_utc"]),
                    "WARMUP_OVERLAPS_SCORE", at)
            require(instant(s["session_window"]["start_utc"]) <= instant(s["scored_window"]["start_utc"])
                    and instant(s["scored_window"]["end_utc"]) <= instant(s["session_window"]["end_utc"]),
                    "SCORE_OUTSIDE_SESSION", at)
            if s["settlement"]["status"] == "PROVEN":
                require(bool(s["settlement"]["policy_ref"]), "SETTLEMENT_SOURCE_REQUIRED", at + "/settlement")
            if s["brain_fingerprint"] is None:
                require(bool(s["fingerprint_unknown_reason"]), "UNKNOWN_FINGERPRINT_REASON_REQUIRED", at)
            else:
                require(bool(s["fingerprint_evidence_ref"]), "FINGERPRINT_SOURCE_REQUIRED", at)
            if s["eligibility"] in ("PARTIAL", "EXCLUDED", "UNPROVEN"):
                require(bool(s["exclusion_reasons"]), "EXCLUSION_REASON_REQUIRED", at + "/exclusion_reasons")

    @staticmethod
    def annotation(doc, certification):
        labels = [x["label_id"] for x in doc["labels"]]
        require(len(labels) == len(set(labels)), "DUPLICATE_LABEL", "/labels")
        for index, label in enumerate(doc["labels"]):
            require(instant(label["recognition_target"]["end_utc"]) >= instant(label["earliest_available_utc"]),
                    "TARGET_BEFORE_AVAILABILITY", f"/labels/{index}")
        if doc["state"] == "SEALED":
            require(bool(doc["labels"]) and doc["annotator_role"] in ("OWNER", "AUTHORIZED_DELEGATE")
                    and bool(doc["annotator_id"]) and bool(doc["authorization_ref"]) and bool(doc["seal"]),
                    "ANNOTATION_OWNER_SEAL_REQUIRED", "/state")
        if certification:
            require(doc["state"] == "SEALED" and doc["provenance"]["classification"] != "FICTIONAL",
                    "NONOWNER_ANNOTATION_NOT_CERTIFIABLE", "/state")

    @staticmethod
    def scoring(doc, certification):
        if doc["state"] == "OWNER_RATIFIED":
            require(bool(doc["owner_decision_ref"]) and bool(doc["seal"]), "SCORING_RATIFICATION_REQUIRED", "/state")
        if certification:
            require(doc["state"] == "OWNER_RATIFIED" and bool(doc["thresholds"]), "THRESHOLDS_UNRATIFIED", "/state")

    @staticmethod
    def run(doc, certification):
        # The armed loop exists offline only against the refusing venue double, never in Mode C.
        require(doc.get("venue_lane", "DISARMED") == "DISARMED" or doc["mode"] in ("A", "B"),
                "REFUSING_VENUE_LANE_MODE_C", "/venue_lane")
        budget = doc["budget"]
        cost = _decimal(budget["max_cost_usd"], "/budget/max_cost_usd")
        if doc["mode"] != "C" or not doc["model_calls_authorized"]:
            require(budget["max_external_requests"] == 0 and cost == 0, "UNAUTHORIZED_REQUEST_BUDGET", "/budget")
        else:
            require(doc["provenance"]["classification"] != "FICTIONAL" and not doc["dry_run"]
                    and doc["trajectory_count"] > 0 and budget["max_external_requests"] > 0 and cost > 0,
                    "INVALID_EXTERNAL_PLAN", "/budget")
            require(bool(budget["authorization_ref"]) and bool(budget["pricing_table_ref"])
                    and bool(budget["expires_at"]) and bool(doc["model_requested"])
                    and budget["max_input_tokens_per_request"] > 0 and budget["max_output_tokens_per_request"] > 0,
                    "EXTERNAL_AUTHORIZATION_INCOMPLETE", "/budget")
        if doc["mode"] in ("A", "B"):
            require(not doc["model_calls_authorized"], "OFFLINE_MODE_EXTERNAL_AUTH", "/model_calls_authorized")
        if certification:
            require(doc["mode"] == "C" and doc["model_calls_authorized"] and bool(doc["annotation_digest"])
                    and bool(doc["scoring_plan_digest"]), "CURRENT_RECOGNITION_PREREQUISITES", "/mode")

    @staticmethod
    def release(doc, certification):
        bar = doc["bar"]
        require(bar["contract"] == doc["contract_id"], "CONTRACT_MISMATCH", "/bar/contract")
        require(instant(bar["timestamp"]) == instant(doc["bar_open_utc"]), "BAR_IDENTITY_MISMATCH", "/bar/timestamp")
        require(instant(doc["available_at_utc"]) >= instant(doc["bar_open_utc"]), "FUTURE_BAR_LEAK", "/available_at_utc")
        require(bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"],
                "INVALID_OHLC", "/bar")
        if doc["settlement_proven"]:
            require(doc["settled_at_utc"] is not None
                    and instant(doc["bar_open_utc"]) + timedelta(minutes=1) <= instant(doc["settled_at_utc"])
                    <= instant(doc["available_at_utc"]), "SETTLEMENT_OUTSIDE_VALID_INTERVAL", "/settled_at_utc")
        else:
            require(doc["settled_at_utc"] is None, "UNPROVEN_SETTLEMENT_CLAIM", "/settled_at_utc")
        if doc["supersedes_version"] is not None:
            require(doc["supersedes_version"] < doc["version"], "INVALID_REVISION_ORDER", "/supersedes_version")

    @staticmethod
    def brain_call(doc, certification):
        require(instant(doc["settled_cutoff"]) <= instant(doc["decision_time"]), "CUTOFF_AFTER_DECISION",
                "/settled_cutoff")
        if doc["completed_at"]:
            require(instant(doc["started_at"]) <= instant(doc["completed_at"]), "NEGATIVE_REQUEST_DURATION",
                    "/completed_at")
        if doc["evaluation_origin"] == "CURRENT_EXTERNAL" and doc["request_attempted"]:
            require(bool(doc["budget_reservation_id"]), "UNRESERVED_EXTERNAL_REQUEST", "/budget_reservation_id")

    @staticmethod
    def event(doc, certification):
        require(instant(doc["settled_cutoff"]) <= instant(doc["observed_at"]), "FUTURE_SETTLED_EVENT",
                "/settled_cutoff")
        require(doc["event_payload_digest"] == event_digest(doc), "EVENT_DIGEST_MISMATCH", "/event_payload_digest")

    @staticmethod
    def result(doc, certification):
        if doc["mode"] in ("A", "B"):
            require(doc["current_brain_recognition"] == "UNPROVEN" and doc["external_request_count"] == 0,
                    "MOCK_COGNITION_LAUNDERING", "/current_brain_recognition")
        if doc["current_brain_recognition"] in ("ELIGIBLE_FOR_OWNER_REVIEW", "OWNER_ACCEPTED"):
            require(bool(doc["recognition_ratification_ref"]) and bool(doc["stage4_owner_acceptance_ref"]),
                    "RECOGNITION_RATIFICATION_REQUIRED", "/current_brain_recognition")
        if doc["final_status"] == "READY_FOR_OWNER_REVIEW":
            require(doc["engineering_status"] == "COMPLETE" and not doc["invariant_failures"],
                    "INCOMPLETE_READY_CLAIM", "/final_status")
        claims = doc["current_brain_recognition"] in ("ELIGIBLE_FOR_OWNER_REVIEW", "OWNER_ACCEPTED")
        if doc["schema_version"] == "result/v1":
            # v1 carries no rule-obligation evidence: its records stay readable, but
            # an eligibility claim in one cannot be verified and is refused, not reinterpreted.
            require(not claims, "RESULT_V1_RULE_COVERAGE_UNVERIFIABLE", "/current_brain_recognition")
            require("rule_coverage" not in doc, "RESULT_V1_UNKNOWN_FIELD", "/rule_coverage")
            return
        require("rule_coverage" in doc, "RULE_COVERAGE_REQUIRED", "/rule_coverage")
        coverage = doc["rule_coverage"]
        obligations = coverage["obligations"]
        for index, item in enumerate(obligations):
            pointer = f"/rule_coverage/obligations/{index}"
            if item["status"] == "UNPROVEN":
                require(item["reason"] is not None, "UNPROVEN_OBLIGATION_REASON_REQUIRED", pointer)
                continue
            require(item["reason"] is None and bool(item["denominator"]) and item["value"] is not None,
                    "SCORED_OBLIGATION_WITHOUT_EVIDENCE", pointer)
            if item["operator"] is not None:
                holds = {"<=": item["value"] <= item["threshold_value"], ">=": item["value"] >= item["threshold_value"],
                         "==": item["value"] == item["threshold_value"]}[item["operator"]]
                require(holds == (item["status"] == "PASS"), "OBLIGATION_ASSESSMENT_MISMATCH", pointer)
        if coverage["declared"]:
            expected = sorted((u["session_id"], u["trajectory_id"] or "", r["metric"], r["decision_ref"])
                              for u in coverage["required_units"] for r in coverage["rules"])
            actual = sorted((o["session_id"], o["trajectory_id"] or "", o["metric"], o["decision_ref"] or "")
                            for o in obligations)
            require(expected == actual, "RULE_OBLIGATION_SET_INCOMPLETE", "/rule_coverage/obligations")
        statuses = {o["status"] for o in obligations}
        status = ("FAIL" if "FAIL" in statuses else "UNDECLARED" if not coverage["declared"]
                  else "COMPLETE" if obligations and statuses == {"PASS"} else "INCOMPLETE")
        require(coverage["status"] == status, "RULE_COVERAGE_STATUS_MISMATCH", "/rule_coverage/status")
        require(not claims or status == "COMPLETE", "ELIGIBILITY_WITHOUT_COMPLETE_RULE_COVERAGE",
                "/current_brain_recognition")
        require(doc["current_brain_recognition"] != "FAIL" or status == "FAIL", "FAIL_WITHOUT_SCORED_RULE_FAILURE",
                "/current_brain_recognition")

    @staticmethod
    def model_authorization(doc, certification):
        require(instant(doc["issued_at"]) < instant(doc["expires_at"]), "AUTHORIZATION_TIME_RANGE", "/expires_at")
        cost = _decimal(doc["max_cost_usd"], "/max_cost_usd")
        if doc["state"] == "DISABLED":
            require(doc["max_external_requests"] == 0 and cost == 0, "DISABLED_AUTHORIZATION_HAS_BUDGET", "/state")
        else:
            require(doc["provenance"]["classification"] != "FICTIONAL" and bool(doc["owner_receipt_ref"])
                    and bool(doc["model"]) and bool(doc["endpoint_identity"]) and doc["max_external_requests"] > 0
                    and cost > 0 and doc["trajectory_count"] > 0 and bool(doc["pricing_digest"])
                    and bool(doc["seal"]), "MODEL_AUTHORIZATION_INCOMPLETE", "/state")

    @staticmethod
    def schedule(doc, certification):
        keys = [(t["session_id"], t["ordinal"]) for t in doc["ticks"]]
        require(len(keys) == len(set(keys)), "DUPLICATE_SCHEDULE_ORDINAL", "/ticks")
        last = {}
        for index, tick in enumerate(doc["ticks"]):
            session, moment = tick["session_id"], instant(tick["decision_time_utc"])
            if session in last:
                require(last[session][0] < tick["ordinal"] and last[session][1] <= moment,
                        "SCHEDULE_NOT_CHRONOLOGICAL", f"/ticks/{index}")
            last[session] = (tick["ordinal"], moment)

    @staticmethod
    def pricing(doc, certification):
        for field in ("uncached_input_rate", "output_rate"):
            require(_decimal(doc[field], "/" + field) >= 0, "NEGATIVE_RATE", "/" + field)
        require(doc["cache_discount_assumed"] is False, "CACHE_DISCOUNT_NOT_CONSERVATIVE", "/cache_discount_assumed")


def event_digest(event: dict) -> str:
    return digest({k: v for k, v in event.items() if k != "event_payload_digest"})


def kind_of(doc) -> str:
    require(isinstance(doc, dict), "TYPE_OBJECT", "/")
    version = doc.get("schema_version")
    require(isinstance(version, str) and "/" in version, "UNKNOWN_SCHEMA", "/schema_version")
    return version.split("/")[0]


def validate(doc, *, certification: bool = False) -> str:
    """Structural + semantic validation. Returns the document kind."""
    kind = kind_of(doc)
    _structural(doc, schema_for(kind), "")
    _semantics(doc, certification)
    return kind


def validate_file(path, *, certification: bool = False) -> tuple[dict, str, str]:
    """(document, kind, original-file sha256) or ContractError carrying the digest."""
    doc, file_digest = load_file(path)
    try:
        kind = validate(doc, certification=certification)
    except ContractError as exc:
        raise ContractError(exc.code, exc.pointer, file_digest=file_digest, detail=exc.detail) from exc
    return doc, kind, file_digest


def cross(corpus: dict, annotations: dict | None = None, scoring: dict | None = None,
          run: dict | None = None) -> None:
    """Acyclic bindings: annotations/scoring/run name the sealed corpus digest."""
    corpus_digest = seal_digest(corpus)
    sessions = {s["session_id"]: s for s in corpus["sessions"]}
    if annotations:
        require(annotations["corpus_digest"] == corpus_digest, "ANNOTATION_CORPUS_MISMATCH", "/corpus_digest")
        require(annotations["session_id"] in sessions, "ANNOTATION_SESSION_MISSING", "/session_id")
        window = sessions[annotations["session_id"]]["scored_window"]
        for index, label in enumerate(annotations["labels"]):
            require(instant(window["start_utc"]) <= instant(label["window"]["start_utc"])
                    and instant(label["window"]["end_utc"]) <= instant(window["end_utc"]),
                    "ANNOTATION_OUTSIDE_SCORED_WINDOW", f"/labels/{index}/window")
    if scoring:
        require(scoring["corpus_digest"] == corpus_digest, "SCORING_CORPUS_MISMATCH", "/corpus_digest")
        if annotations:
            require(seal_digest(annotations) in scoring["annotation_digests"], "SCORING_ANNOTATION_MISMATCH",
                    "/annotation_digests")
    if run:
        require(run["corpus_digest"] == corpus_digest, "RUN_CORPUS_MISMATCH", "/corpus_digest")
        if annotations:
            require(run["annotation_digest"] == seal_digest(annotations), "RUN_ANNOTATION_MISMATCH",
                    "/annotation_digest")
        if scoring:
            require(run["scoring_plan_digest"] == seal_digest(scoring), "RUN_SCORING_MISMATCH",
                    "/scoring_plan_digest")


def verify_artifact(ref: dict, root, pointer: str = "") -> bytes:
    """Read a referenced artifact under `root` and bind its original bytes."""
    rel = safe_relative_path(ref["path"], pointer + "/path")
    base = Path(root).resolve()
    target = (base / Path(*rel.parts))
    require(not target.is_symlink(), "SYMLINK_ARTIFACT", pointer)
    target = target.resolve()
    require(target.is_relative_to(base) and target.is_file(), "ARTIFACT_MISSING", pointer, ref["path"])
    data = target.read_bytes()
    require(len(data) == ref["bytes"], "ARTIFACT_BYTES_MISMATCH", pointer)
    require(sha256_hex(data) == ref["sha256"], "ARTIFACT_DIGEST_MISMATCH", pointer)
    return data


def verify_event_chain(events: list) -> str | None:
    """Validate an append-only chain; returns the last computed event digest."""
    previous = None
    for index, event in enumerate(events):
        validate(event)
        require(event["sequence"] == index, "EVENT_SEQUENCE_GAP", f"/{index}/sequence")
        require(event["previous_event_digest"] == previous, "EVENT_CHAIN_BROKEN", f"/{index}/previous_event_digest")
        previous = event_digest(event)
        require(_HEX64.match(previous) is not None, "EVENT_DIGEST_MISMATCH", f"/{index}")
    return previous
