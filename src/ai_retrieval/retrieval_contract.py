"""The retrieval policy Terra is bound to.

BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).
REFINE-DESCRIPTIVE-MEMORY-VECTOR-V2 (2026-08-06).

Retrieval changes what the Brain receives. An authorization that binds only the
model and the prompt/schema/validator sources would still be honoured after the
similarity threshold, the analog ceiling, the vector layout or the authority
label changed underneath it -- and the Brain would be reading a materially
different payload under a signature that says nothing happened.

So the policy lives HERE, as named values, and its fingerprint is folded into
`brain_contract_fingerprint()`. Changing any value invalidates every previously
issued authorization. That is the point.

Nothing in this module retrieves, scores or authors anything.
"""
from __future__ import annotations

import hashlib
import json

from ai_retrieval import embedding_v2 as EV2

# ── the bound policy ─────────────────────────────────────────────────────────
RETRIEVAL_SCHEMA_VERSION = "descriptive.v2.2"

#: Nothing retrieved may establish direction, invalidation, target or entry.
AUTHORITY_LABEL = "CONTEXT_ONLY"

#: How many analogs may reach the Brain in one scan.
MAX_ANALOGS = 5

#: How many may come from any ONE source session.
#:
#: PROD-20260806 under v1 put three indistinguishable lunch segments into the
#: top five. Even with v2 telling them apart, one quiet Thursday should not be
#: able to speak five times: a corpus of one session would otherwise present
#: itself as five independent precedents, which is the self-confirmation the
#: whole descriptive-memory doctrine exists to prevent. 2 leaves room for a
#: session to contribute a state and its neighbour, and no more.
MAX_ANALOGS_PER_SOURCE_SESSION = 2

#: Below this cosine similarity a record is not an analog, it is noise.
#:
#: Re-derived a SECOND time under v2.1. The load-bearing contradiction gate now
#: removes disagreeing records by rule, so the threshold no longer has to
#: separate "contradicts the question" from "resembles it" -- a job the probe
#: bake-off proved no threshold could do anyway. Its only remaining job is
#: suppressing weak non-contradicting matches.
#:
#: Chosen from an INSENSITIVITY BAND, not fitted to a record. With the gate
#: active, every August 6 query returns an identical set at 0.40, 0.50, 0.60 and
#: 0.70; the weakest legitimate surviving analog scores 0.7194 and the weakest
#: synthetic non-contradicting probe 0.8662. 0.60 sits inside that flat band
#: with ~0.12 headroom under the weakest observed legitimate match, and above
#: the legacy value it replaces.
MIN_SIMILARITY = 0.60

#: Beyond this age a descriptive record stops entering retrieval. The record
#: itself is NOT deleted -- expiry is a retrieval rule, not a retention rule.
MAX_AGE_DAYS = 60

#: Absolute price levels are contract-scoped. A level from an expired MNQ
#: contract is a number from a different instrument-month; the categorical
#: regime features remain comparable, the prices do not.
WITHHOLD_LEVELS_ACROSS_CONTRACTS = True

#: Two records from the SAME session with an identical vector fingerprint are
#: one observation seen twice. They collapse to a single representative that
#: consumes one slot and carries `recurrence_count` and the occurrence spans.
#: Records from DIFFERENT sessions never collapse -- those are independent
#: historical observations of a recurring market state.
RECURRENCE_COLLAPSE_SAME_SESSION = True

#: Applied in order, after collapse, before top-k. Replaces v1's implicit
#: JSONL-append-order tie-break, which made ranking depend on write order.
TIE_BREAK_ORDER = ("similarity_desc", "session_date_desc", "scan_count_desc",
                   "segment_duration_desc", "memory_id_asc")

#: Deterministic representative for a collapsed recurrence group. Confidence is
#: deliberately NOT a criterion: a more confident occurrence is not a more
#: correct one, and ranking by it would smuggle self-evaluation into retrieval.
RECURRENCE_REPRESENTATIVE_ORDER = ("similarity_desc", "scan_count_desc",
                                   "segment_duration_desc",
                                   "segment_start_asc", "memory_id_asc")

#: The framing every descriptive analog carries into the prompt. It is part of
#: the contract because weakening this sentence weakens the authority boundary.
ANALOG_FRAMING = (
    "This record describes a prior market state. It is not an outcome-validated "
    "trading recommendation. It cannot establish direction, invalidation, target "
    "or entry authority.")

ANALOG_PROMPT_HEADER = "HISTORICAL DESCRIPTIVE ANALOGS"


def retrieval_policy() -> dict:
    """The resolved policy, exactly as production will apply it."""
    return {
        "retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION,
        "authority_label": AUTHORITY_LABEL,
        "max_analogs": MAX_ANALOGS,
        "max_analogs_per_source_session": MAX_ANALOGS_PER_SOURCE_SESSION,
        "min_similarity": MIN_SIMILARITY,
        "max_age_days": MAX_AGE_DAYS,
        "withhold_levels_across_contracts": WITHHOLD_LEVELS_ACROSS_CONTRACTS,
        "recurrence_collapse_same_session": RECURRENCE_COLLAPSE_SAME_SESSION,
        # Semantic recurrence: grouping is decided on FIELDS, never on cosine.
        "recurrence_mode": "semantic_same_session",
        "semantic_recurrence_policy_version": "semantic_recurrence.v1.1",
        # Representative selection runs on a projection with the diagnostic
        # block zeroed, so no confidence value can reach the decision even
        # indirectly through cosine.
        "representative_similarity_excludes":
            list(EV2.REPRESENTATIVE_EXCLUDED_GROUPS),
        "representative_similarity_is_confidence_free": True,
        "recurrence_identity_fields": list(EV2.RECURRENCE_IDENTITY_FIELDS),
        "recurrence_load_bearing_fields": list(EV2.RECURRENCE_LOAD_BEARING_FIELDS),
        "recurrence_contextual_exact_fields":
            list(EV2.RECURRENCE_CONTEXTUAL_EXACT_FIELDS),
        "recurrence_permitted_contextual_differences":
            list(EV2.RECURRENCE_PERMITTED_CONTEXTUAL_DIFFERENCES),
        "direction_component_tolerance": EV2.DIRECTION_COMPONENT_TOLERANCE,
        "recurrence_representative_order": list(RECURRENCE_REPRESENTATIVE_ORDER),
        "tie_break_order": list(TIE_BREAK_ORDER),
        "analog_framing": ANALOG_FRAMING,
        "analog_prompt_header": ANALOG_PROMPT_HEADER,
        # The vector space itself. A layout change must invalidate an
        # authorization exactly as a threshold change does -- the Brain would be
        # reading analogs selected in a different geometry.
        "embedding_version": EV2.EMBEDDING_VERSION,
        "embedding_dimensions": EV2.EMBED_DIM_V2,
        "embedding_manifest_fingerprint": EV2.manifest_fingerprint(),
        "normalization_law": EV2.MANIFEST["normalization_law"],
        "internal_normalization_law": EV2.MANIFEST["internal_normalization_law"],
        "missing_value_law": EV2.MANIFEST["missing_value_law"],
        # Block weighting and the query-completeness law both change WHICH
        # analogs reach the Brain, so both are bound exactly like the threshold.
        "weight_profile": EV2.ACTIVE_PROFILE,
        "block_weights": EV2.block_weights(),
        "authority_tiers": EV2.MANIFEST["authority_tiers"],
        "mandatory_query_blocks": list(EV2.MANDATORY_QUERY_BLOCKS),
        "incomplete_query_treatment": "REFUSE_IF_MANDATORY_MISSING_ELSE_PENALISE",
        # Contradiction is a rule, not a distance. Weighting provably cannot
        # express it, so it is bound separately.
        "contradiction_blocks": list(EV2.CONTRADICTION_BLOCKS),
        "direction_agreement_min": EV2.DIRECTION_AGREEMENT_MIN,
        "max_load_bearing_contradictions": EV2.MAX_LOAD_BEARING_CONTRADICTIONS,
    }


def retrieval_contract_fingerprint() -> str:
    """Deterministic identity of the RESOLVED policy values.

    Hashing the source file would miss a value that arrives from configuration.
    Hashing the resolved values cannot.
    """
    blob = json.dumps(retrieval_policy(), sort_keys=True, separators=(",", ":"))
    return "retr:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
