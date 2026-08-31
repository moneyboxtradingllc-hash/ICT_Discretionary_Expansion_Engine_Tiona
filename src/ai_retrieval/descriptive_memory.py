"""Descriptive observation memory -- schema, identity, retention, language law.

BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).

The PROD-20260806 audit found the bot archived everything and learned nothing:
741 artifacts on disk, 0 retrievable records. The fix is NOT to dump 172 scans
into the corpus. A system that stores its own stand-downs and later retrieves
them as precedent is training on its own unverified opinion.

So there are exactly two memory classes, and they are not interchangeable:

  descriptive_observation   what the market and the system OBSERVED.
                            authority CONTEXT_ONLY, outcome_validated false.
                            May be authored from a no-trade session.

  outcome_validated         what a completed round trip actually PAID.
                            Requires real fills, reconciliation, bot
                            attribution, known fees and slippage evidence.
                            No August 6 record qualifies; none was authored.

A descriptive record states what was present and what was absent. It never
states that a decision was right. "No candidate existed because the action was
stand_down" is an observation. "Standing down avoided a loss" is a claim about a
counterfactual the organism never ran, and this module refuses to store it.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

from ai_retrieval import embedding_v2 as EV2
from ai_retrieval.retrieval_contract import (AUTHORITY_LABEL, MAX_AGE_DAYS,
                                             RETRIEVAL_SCHEMA_VERSION)

SCHEMA_VERSION = RETRIEVAL_SCHEMA_VERSION

MEMORY_TYPE_DESCRIPTIVE = "descriptive_observation"
MEMORY_TYPE_OUTCOME = "outcome_validated"

#: Descriptive memory carries no authority of any kind. Both fields are stored
#: explicitly rather than implied by absence -- a consumer must not have to know
#: the doctrine to read the record correctly.
RECOMMENDATION_AUTHORITY = "none"
EXECUTION_AUTHORITY = "none"

SESSION_TIMEZONE = "America/New_York"

# ── the language law ─────────────────────────────────────────────────────────
# A descriptive record may describe. It may not evaluate, congratulate or
# predict. These patterns are checked against every free-text value in the
# record before it is allowed to persist.
FORBIDDEN_ASSERTIONS = (
    (r"\bavoid(ed|s|ing)?\s+(a\s+)?(loss|losses|drawdown)", "avoided_loss_claim"),
    (r"\bsaved\s+(a\s+)?(loss|money|capital)", "avoided_loss_claim"),
    (r"\b(correct|right|good|wise|smart)\s+(decision|call|stand[\s_-]?down|choice)",
     "decision_correctness_claim"),
    (r"\bstand[\s_-]?down\s+was\s+(correct|right|justified|validated)",
     "decision_correctness_claim"),
    (r"\bwinning\s+(setup|trade|call)", "outcome_claim"),
    (r"\b(this|it)\s+would\s+have\s+(won|lost|paid)", "counterfactual_outcome_claim"),
    (r"\bdo\s+(this|that)\s+again", "recommendation_claim"),
    (r"\bshould\s+(enter|buy|sell|go\s+(long|short))", "recommendation_claim"),
    (r"\bwill\s+repeat", "prediction_claim"),
    (r"\bexpect\s+the\s+same\s+outcome", "prediction_claim"),
)

_FORBIDDEN = tuple((re.compile(p, re.IGNORECASE), reason)
                   for p, reason in FORBIDDEN_ASSERTIONS)

#: Fields whose values are free text and must pass the language law. Everything
#: else in the schema is a categorical token, a number or a timestamp.
_TEXT_FIELDS = ("structure_state", "liquidity_state", "active_draw",
                "no_candidate_reasons", "market_regime", "volatility_state",
                "session_phase", "narrative_phase", "delivery_state",
                "dominant_direction", "dominant_action",
                "protected_high_basis", "protected_low_basis")


class DescriptiveMemoryError(RuntimeError):
    """The record may not be stored as written."""


def scan_evaluative_language(record: dict) -> list:
    """Every forbidden assertion found in the record. Empty means clean."""
    hits = []
    for field in _TEXT_FIELDS:
        value = record.get(field)
        chunks = value if isinstance(value, (list, tuple)) else [value]
        for chunk in chunks:
            if not isinstance(chunk, str):
                continue
            for pattern, reason in _FORBIDDEN:
                if pattern.search(chunk):
                    hits.append({"field": field, "reason": reason,
                                 "text": chunk[:120]})
    return hits


# ── identity ─────────────────────────────────────────────────────────────────
def memory_id(*, session_id: str, instrument: str, contract: str,
              segment_start: str, segment_end: str,
              source_artifact_digest: str,
              schema_version: str = SCHEMA_VERSION) -> str:
    """Deterministic identity. The SAME session authored twice is the same id.

    Content is deliberately NOT hashed in: identical inputs must collide so the
    second authoring is recognised as a repeat, and a DIFFERENT reading of the
    same segment must collide too -- so it surfaces as a conflict instead of
    quietly appending a second version of the same moment.
    """
    raw = "|".join(str(p) for p in (schema_version, session_id, instrument,
                                    contract, segment_start, segment_end,
                                    source_artifact_digest))
    return "mem:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def content_digest(record: dict) -> str:
    """Identity of what the record SAYS, ignoring bookkeeping fields."""
    skip = {"memory_id", "created_at", "content_digest", "embedding"}
    body = {k: v for k, v in record.items() if k not in skip}
    blob = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


# ── retention ────────────────────────────────────────────────────────────────
def _as_session_date(value) -> "datetime | None":
    """Parse an ET session date (YYYY-MM-DD or YYYYMMDD). Naive by design.

    Age is measured in SESSION DATES, not wall-clock instants: a record written
    at 15:58 ET and a query at 09:31 ET the next morning are one session apart,
    not 0.7 days apart, and a timestamp-difference rule would round that wrong
    twice a day.
    """
    if not value:
        return None
    text = str(value).strip()[:10].replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text.replace("-", "") if fmt == "%Y%m%d"
                                     else text, fmt)
        except ValueError:
            continue
    return None


def expiry_date(session_date: str, max_age_days: int = MAX_AGE_DAYS) -> str:
    d = _as_session_date(session_date)
    if d is None:
        return ""
    return (d + timedelta(days=max_age_days)).strftime("%Y-%m-%d")


def is_expired(record: dict, today: str, max_age_days: int = MAX_AGE_DAYS) -> bool:
    """True when the record may no longer enter retrieval.

    An unparseable or missing session date expires immediately -- a record whose
    age cannot be established is not young, it is unknown.
    """
    now = _as_session_date(today)
    if now is None:
        return True
    stated = record.get("expires_at")
    end = _as_session_date(stated) if stated else None
    if end is None:
        end = _as_session_date(expiry_date(record.get("session_date"),
                                           max_age_days))
    if end is None:
        return True
    return now > end


# ── the record ───────────────────────────────────────────────────────────────
def make_descriptive_record(
    *, session_id: str, session_date: str, instrument: str, contract: str,
    segment_start: str, segment_end: str, scan_count: int,
    source_model: str, brain_contract_fingerprint_suffix: str,
    market_regime: str, volatility_state: str, session_phase: str,
    narrative_phase: str, delivery_state: str,
    structure_state: str, structure_evidence: dict, liquidity_state: str,
    protected_high: dict, protected_low: dict, active_draw_present: bool,
    exhaustion_present: bool,
    direction_distribution: dict, action_distribution: dict,
    dominant_direction: str, dominant_action: str,
    phase_confidence_summary: dict, candidate_count: int, trade_count: int,
    no_candidate_reasons: list, source_artifact_ids: list,
    source_artifact_digest: str, created_at: str,
    code_phases: list = None, levels_contract_scoped: bool = True,
    max_age_days: int = MAX_AGE_DAYS,
    session_provenance: dict = None,
) -> dict:
    """Build one descriptive segment record.

    Deliberately absent: account id, account fingerprint, balance, credentials,
    authorization fingerprint, raw prompt, raw model response. A market analog
    is market-centered. An account number is not a feature of the market and has
    no business travelling into a prompt.
    """
    record = {
        "schema_version": SCHEMA_VERSION,
        "memory_type": MEMORY_TYPE_DESCRIPTIVE,
        "authority": AUTHORITY_LABEL,
        "session_id": session_id,
        "session_date": session_date,
        "timezone": SESSION_TIMEZONE,
        "instrument": instrument,
        "contract": contract,
        "segment_start": segment_start,
        "segment_end": segment_end,
        "scan_count": int(scan_count),
        "source_model": source_model,
        "brain_contract_fingerprint_suffix": brain_contract_fingerprint_suffix,
        "market_regime": market_regime,
        "volatility_state": volatility_state,
        "session_phase": session_phase,
        "narrative_phase": narrative_phase,
        # V2: the ICT delivery vocabulary, in its own feature block. v1 routed
        # this through a DIRECTIONAL normaliser that recognised none of these
        # values, so every record shared one dead dimension.
        "delivery_state": delivery_state,
        "structure_state": structure_state,          # display metadata only
        "structure_evidence": dict(structure_evidence or {}),
        "liquidity_state": liquidity_state,
        # V2: ONE shape, always the same keys, present or absent. v1 stored
        # `null` on nine records and a nested dict on the tenth.
        "protected_high_level": (protected_high or {}).get("level"),
        "protected_high_timeframe": (protected_high or {}).get("timeframe"),
        "protected_high_basis": (protected_high or {}).get("basis"),
        "protected_high_registered_at": (protected_high or {}).get("registered_at"),
        "protected_low_level": (protected_low or {}).get("level"),
        "protected_low_timeframe": (protected_low or {}).get("timeframe"),
        "protected_low_basis": (protected_low or {}).get("basis"),
        "protected_low_registered_at": (protected_low or {}).get("registered_at"),
        "active_draw_present": bool(active_draw_present),
        # An INDEPENDENT delivery measurement, not a restatement of
        # narrative_phase. v1 carried a permanently-zero exhaustion scalar
        # because nothing ever wrote it.
        "exhaustion_present": bool(exhaustion_present),
        "direction_distribution": dict(direction_distribution or {}),
        "action_distribution": dict(action_distribution or {}),
        "dominant_direction": dominant_direction,
        "dominant_action": dominant_action,
        "phase_confidence_summary": dict(phase_confidence_summary or {}),
        "candidate_count": int(candidate_count),
        "trade_count": int(trade_count),
        "no_candidate_reasons": list(no_candidate_reasons or []),
        # Absolute levels are contract-scoped; retrieval withholds them when the
        # querying contract differs. The flag records that they are prices, not
        # dimensionless features.
        "levels_contract_scoped": bool(levels_contract_scoped),
        # The three PROD-20260806 code phases are preserved: a segment authored
        # under pre-repair code is not the same evidence as one authored after.
        "code_phases": list(code_phases or []),
        "outcome_validated": False,
        "recommendation_authority": RECOMMENDATION_AUTHORITY,
        "execution_authority": EXECUTION_AUTHORITY,
        "created_at": created_at,
        "expires_at": expiry_date(session_date, max_age_days),
        "source_artifact_ids": list(source_artifact_ids or []),
        "source_artifact_digest": source_artifact_digest,
        # Legacy-corpus compatibility. `is_authoritative` and the existing
        # instrument filter read these; a descriptive record must satisfy the
        # SAME gates as every other record, not bypass them.
        "provenance": {
            "direction_source": "ai_brain",
            "source_validated": True,
            "structure_tainted": False,
            "authored_by": "descriptive_session_memory",
            "instrument": instrument,
            # HOW THE SESSION ENDED, HOW ITS IDENTITY WAS ESTABLISHED, AND HOW
            # MUCH OF THE WINDOW IT ACTUALLY SAW. A reader that cannot tell a
            # partially observed session from a complete one will read absent
            # afternoon records as an observed absence of afternoon setups.
            **(session_provenance or {}),
        },
    }
    record["memory_id"] = memory_id(
        session_id=session_id, instrument=instrument, contract=contract,
        segment_start=segment_start, segment_end=segment_end,
        source_artifact_digest=source_artifact_digest)
    vector, notes = EV2.embed_v2(record)
    record["embedding_version"] = EV2.EMBEDDING_VERSION
    record["embedding_dimensions"] = EV2.EMBED_DIM_V2
    record["embedding_manifest_fingerprint"] = EV2.manifest_fingerprint()
    record["feature_vector"] = vector
    record["feature_dimensions"] = len(vector)
    record["feature_vector_fingerprint"] = EV2.vector_fingerprint(vector)
    # Every group that encoded as all-zeros. An under-specified record must be
    # visible as under-specified, not silently similar to every other one.
    record["embedding_notes"] = notes
    record["content_digest"] = content_digest(record)
    return record


def embed_descriptive(record: dict) -> list:
    """The v2 market-state vector. A named seam for callers."""
    return EV2.embed_v2(record)[0]


# ── validation ───────────────────────────────────────────────────────────────
REQUIRED_FIELDS = (
    "schema_version", "memory_id", "memory_type", "authority", "session_id",
    "session_date", "timezone", "instrument", "contract", "segment_start",
    "segment_end", "scan_count", "source_model",
    "brain_contract_fingerprint_suffix", "market_regime", "volatility_state",
    "session_phase", "narrative_phase", "delivery_state", "structure_state",
    "structure_evidence", "liquidity_state", "active_draw_present",
    "exhaustion_present",
    "protected_high_level", "protected_low_level",
    "direction_distribution", "action_distribution",
    "dominant_direction", "dominant_action", "phase_confidence_summary",
    "candidate_count", "trade_count", "no_candidate_reasons",
    "embedding_version", "embedding_dimensions", "embedding_manifest_fingerprint",
    "feature_vector", "feature_dimensions", "feature_vector_fingerprint",
    "outcome_validated", "recommendation_authority",
    "execution_authority", "created_at", "expires_at", "source_artifact_ids",
    "source_artifact_digest",
)

#: Never storable on a market-analog record.
FORBIDDEN_FIELDS = (
    "account_id", "account_fingerprint", "account_balance", "equity",
    "api_key", "authorization_fingerprint", "jwt", "token",
    "llm_prompt", "llm_raw_response", "raw_response", "prompt",
)


def validate_descriptive_record(record: dict) -> tuple:
    """(ok, reasons). A record that fails is not stored, not repaired."""
    reasons = []
    r = record or {}
    for field in REQUIRED_FIELDS:
        if field not in r:
            reasons.append(f"missing_field:{field}")
    for field in FORBIDDEN_FIELDS:
        if field in r:
            reasons.append(f"forbidden_field:{field}")
    if r.get("memory_type") != MEMORY_TYPE_DESCRIPTIVE:
        reasons.append("wrong_memory_type")
    if r.get("authority") != AUTHORITY_LABEL:
        reasons.append("wrong_authority")
    if r.get("outcome_validated") is not False:
        reasons.append("outcome_validated_must_be_false")
    if r.get("recommendation_authority") != RECOMMENDATION_AUTHORITY:
        reasons.append("recommendation_authority_must_be_none")
    if r.get("execution_authority") != EXECUTION_AUTHORITY:
        reasons.append("execution_authority_must_be_none")
    vector = r.get("feature_vector") or []
    if r.get("feature_dimensions") != len(vector):
        reasons.append("feature_dimension_mismatch")
    if r.get("embedding_version") != EV2.EMBEDDING_VERSION:
        reasons.append("embedding_version_not_" + EV2.EMBEDDING_VERSION)
    if r.get("embedding_dimensions") != EV2.EMBED_DIM_V2 or (
            len(vector) != EV2.EMBED_DIM_V2):
        reasons.append("embedding_dimensions_not_%d" % EV2.EMBED_DIM_V2)
    if r.get("embedding_manifest_fingerprint") != EV2.manifest_fingerprint():
        reasons.append("embedding_manifest_fingerprint_mismatch")
    try:
        if r.get("feature_vector_fingerprint") != EV2.vector_fingerprint(vector):
            reasons.append("feature_vector_fingerprint_mismatch")
    except (TypeError, ValueError):
        reasons.append("feature_vector_malformed")
    # The direction distribution must be a real distribution over the segment.
    try:
        props = EV2.direction_proportions(r.get("direction_distribution"),
                                          r.get("scan_count") or 0)
        if abs(sum(props.values()) - 1.0) > 1e-9:
            reasons.append("direction_distribution_does_not_sum_to_one")
    except EV2.EmbeddingError as exc:
        reasons.append("direction_distribution_invalid:%s" % exc)
    for hit in scan_evaluative_language(r):
        reasons.append(f"evaluative_language:{hit['reason']}:{hit['field']}")
    return (not reasons), reasons
