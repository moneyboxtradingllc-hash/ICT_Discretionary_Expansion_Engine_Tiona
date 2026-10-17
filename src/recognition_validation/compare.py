"""Deterministic A/B comparison under a documented semantic projection.

Raw records keep every process-random identity. For determinism only, the
`semantic-v1` projection alpha-renames the fields listed in ALPHA_FIELDS by
first appearance (a bijection: equal stays equal, different stays different,
references and lineage changes survive) and drops the chain digests that
necessarily cover those identities. Brain inputs and outputs get the same
treatment for the identities production mints from a per-process uuid4
lineage (INPUT_TOKEN_KEYS), wherever those values recur, plus the one order
and digest they drive (the premise catalog). Nothing else is normalized: source-event
and formation identities, prices, OHLC, market time, availability, revision,
status, refusal codes, source/model/fingerprint and ownership relationships
pass through untouched. Both raw and semantic hashes are reported.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from recognition_validation import contracts as C
from recognition_validation import recorder as REC

PROJECTION = "semantic-v1"
#: Process-random identities only (pid/object-address lineage, per-process ids).
#: draw_record_id hashes CampaignDrawTruth's per-process uuid4 namespace
#: (market_data/campaign_draw_truth.py), so it differs by construction.
#: scope_id is "campaign:" + digest(custody uuid4 lineage, ...) in
#: market_data/campaign_scope.py; scope_proof_id is content-derived and kept.
ALPHA_FIELDS = ("process_lineage_id", "candidate_id", "plan_id", "draw_record_id", "scope_id")
#: Chain digests cover the renamed fields; they are re-derived, never compared raw.
DROP_FIELDS = ("event_payload_digest", "previous_event_digest")
CALL_DROP_FIELDS = ("document_id",)
#: Mock provider ids hash the raw request digest, which covers the raw input.
CALL_ALPHA_FIELDS = ("provider_request_id", "provider_response_id")
#: Brain-input keys whose string values are minted from a per-process uuid4:
#: CampaignScopeCustody._lineage (custody_lineage, history lineage custody,
#: premise_candidate_id, proposal ids, campaign ids; market_data/campaign_scope.py)
#: and CampaignDrawTruth's namespace/episode (record_id, campaign_episode_id).
#: Content-derived ids (proof_id, scope_proof_id, tip_digest, sweep and
#: occurrence ids) are deliberately absent and compared raw.
INPUT_TOKEN_KEYS = frozenset({
    "custody_lineage", "custody", "premise_candidate_id", "proposal_id", "activation_proposal_id",
    "campaign_id", "successor_campaign_id", "predecessor_campaign_id", "incumbent_id",
    "campaign_episode_id", "record_id"})
#: The premise catalog sorts rows by premise_candidate_id and digests its
#: context (custody_lineage); only that digest and that order are re-derived.
CATALOG_SCHEMA_PREFIX = "campaign_premise_catalog/"


class _Alpha:
    def __init__(self):
        self.maps: dict = {}

    def __call__(self, family: str, value):
        if value is None:
            return None
        table = self.maps.setdefault(family, {})
        if value not in table:
            table[value] = f"{family}#{len(table)}"
        return table[value]


def project_events(events: list, *, alpha: _Alpha | None = None) -> list:
    alpha = alpha or _Alpha()
    out = []
    for event in events:
        row = {k: v for k, v in event.items() if k not in DROP_FIELDS}
        for name in ALPHA_FIELDS:
            row[name] = alpha(name, row.get(name))
        out.append(row)
    return out


def _walk_tokens(node, found: set, key=None) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_tokens(v, found, k)
    elif isinstance(node, list):
        for v in node:
            _walk_tokens(v, found, key)
    elif isinstance(node, str) and node and key in INPUT_TOKEN_KEYS:
        found.add(node)


def _substitute(node, pattern, mapping):
    if pattern is None:
        return node
    if isinstance(node, dict):
        return {k: _substitute(v, pattern, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, pattern, mapping) for v in node]
    if isinstance(node, str):
        return pattern.sub(lambda m: mapping[m.group(0)], node)
    return node


def _pattern(tokens):
    return re.compile("|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))) if tokens else None


def _normalize_catalogs(node, masked_pattern, mask):
    if isinstance(node, list):
        return [_normalize_catalogs(v, masked_pattern, mask) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: _normalize_catalogs(v, masked_pattern, mask) for k, v in node.items()}
    if str(out.get("schema") or "").startswith(CATALOG_SCHEMA_PREFIX):
        out.pop("digest", None)
        if isinstance(out.get("rows"), list):
            out["rows"] = sorted(out["rows"], key=lambda r: C.canonical(_substitute(r, masked_pattern, mask)))
    return out


def _parse(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def input_tokens(text: str) -> tuple:
    """(normalized document, process-random tokens in first-appearance order)."""
    document = _parse(text)
    found: set = set()
    _walk_tokens(document, found)
    pattern = _pattern(found)
    mask = {t: "*" for t in found}
    document = _normalize_catalogs(document, pattern, mask)
    rendered = C.canonical(document).decode("utf-8")
    ordered = sorted(found, key=lambda t: (rendered.find(json.dumps(t)[1:-1]), t))
    return document, ordered


def _bind(document, ordered, alpha: _Alpha):
    mapping = {t: alpha("pr", t) for t in ordered}
    return _substitute(document, _pattern(mapping), mapping)


def project_input(text: str, alpha: _Alpha | None = None):
    document, ordered = input_tokens(text)
    return _bind(document, ordered, alpha or _Alpha())


def semantic_input_digest(text: str) -> str:
    return C.digest(project_input(text))


def rebinding(archived_text: str, current_text: str) -> dict | None:
    """archived -> current token map, only when the inputs are semantic-v1 equal."""
    archived, current = input_tokens(archived_text), input_tokens(current_text)
    if C.digest(_bind(*archived, _Alpha())) != C.digest(_bind(*current, _Alpha())):
        return None
    return dict(zip(archived[1], current[1]))


def _artifact_text(root: Path, ref):
    return None if not ref else (root / ref["path"]).read_text(encoding="utf-8")


def project_calls(calls: list, root=None) -> list:
    """Without `root` only drop fields; with it, re-derive artifact semantics."""
    alpha, out = _Alpha(), []
    for call in calls:
        row = {k: copy.deepcopy(v) for k, v in call.items() if k not in CALL_DROP_FIELDS}
        for name in CALL_ALPHA_FIELDS:
            row[name] = alpha(name, row.get(name))
        if root is not None:
            root = Path(root)
            document, ordered = input_tokens(_artifact_text(root, call["input_ref"]) or "")
            mapping = {t: alpha("pr", t) for t in ordered}
            pattern = _pattern(mapping)
            row["input_ref"] = {"semantic": C.digest(_substitute(document, pattern, mapping))}
            for name in ("raw_response_ref", "parsed_output_ref", "post_guard_output_ref"):
                text = _artifact_text(root, call.get(name))
                row[name] = None if text is None else {
                    "semantic": C.digest(_substitute(_parse(text), pattern, mapping))}
        out.append(row)
    return out


def trace_digests(root) -> dict:
    events = REC.read_events(root)
    calls = REC.read_calls(root)
    return {"projection": PROJECTION, "events": len(events), "calls": len(calls),
            "raw_events_sha256": C.digest(events), "raw_calls_sha256": C.digest(calls),
            "semantic_events_sha256": C.digest(project_events(events)),
            "semantic_calls_sha256": C.digest(project_calls(calls, root))}


def first_divergence(left: list, right: list) -> dict | None:
    """First (index, field) where two projected traces differ."""
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            return {"index": index, "fields": keys, "left": {k: a.get(k) for k in keys},
                    "right": {k: b.get(k) for k in keys}}
    if len(left) != len(right):
        return {"index": min(len(left), len(right)), "fields": ["length"], "left": len(left), "right": len(right)}
    return None


def compare_runs(left_root, right_root) -> dict:
    left_events, right_events = REC.read_events(left_root), REC.read_events(right_root)
    left_calls, right_calls = REC.read_calls(left_root), REC.read_calls(right_root)
    semantic_left, semantic_right = project_events(left_events), project_events(right_events)
    calls_left, calls_right = project_calls(left_calls, left_root), project_calls(right_calls, right_root)
    divergence = first_divergence(semantic_left, semantic_right) or first_divergence(calls_left, calls_right)
    return {"projection": PROJECTION, "identical": divergence is None, "first_divergence": divergence,
            "left": trace_digests(left_root), "right": trace_digests(right_root)}
